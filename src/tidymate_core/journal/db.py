"""SQLite journal: the only durable record of what a batch did.

Iron rule 7 lives here: **write the intent before touching a file, update the outcome
immediately afterwards**. Nothing is buffered "until the end", because a crash between
two files must still leave a truthful log.

The database is append-mostly and small; every write commits immediately. ``WAL`` is
enabled so a reader (status command, GUI) never blocks an apply run.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from tidymate_core.planning.models import Plan, PlannedChange
from tidymate_core.planning.planner import plan_from_dict
from tidymate_core.planning.report import plan_to_dict

_SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
    batch_id      TEXT PRIMARY KEY,
    plan_hash     TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    output_root   TEXT NOT NULL,
    rules_source  TEXT NOT NULL,
    status        TEXT NOT NULL,
    applied_at    TEXT,
    finished_at   TEXT,
    options_json  TEXT,
    plan_json     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS operations (
    batch_id       TEXT NOT NULL,
    seq            INTEGER NOT NULL,
    op             TEXT NOT NULL,
    src            TEXT NOT NULL,
    dst            TEXT,
    final_dst      TEXT,
    state          TEXT NOT NULL,
    error          TEXT,
    error_kind     TEXT,
    size           INTEGER NOT NULL DEFAULT 0,
    cross_volume   INTEGER,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    PRIMARY KEY (batch_id, seq),
    FOREIGN KEY (batch_id) REFERENCES batches(batch_id)
);

CREATE INDEX IF NOT EXISTS idx_operations_batch_state
    ON operations (batch_id, state);
"""


class JournalError(RuntimeError):
    """Base class for journal refusals."""


class BatchAlreadyAppliedError(JournalError):
    """Raised when ``apply`` is asked to run a batch that already finished."""


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


class Journal:
    """Thin, explicit wrapper around one SQLite file."""

    def __init__(self, db_path: str | Path) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        """Close the underlying connection."""
        self._conn.close()

    def __enter__(self) -> Journal:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ------------------------------------------------------------------ previews
    def record_preview(self, plan: Plan) -> None:
        """Persist a dry-run plan so ``apply`` can prove the hash still matches."""
        row = self._conn.execute(
            "SELECT status, plan_hash FROM batches WHERE batch_id = ?",
            (plan.batch_id,),
        ).fetchone()
        if row is not None:
            if row["status"] in {"applying", "applied"}:
                raise JournalError(
                    f"batch {plan.batch_id!r} already started; a new preview gets a new id",
                )
            if row["plan_hash"] != plan.plan_hash:
                raise JournalError(
                    f"batch {plan.batch_id!r} already has a different plan hash; "
                    "re-run the preview in another second",
                )
        self._conn.execute(
            """
            INSERT INTO batches
                (batch_id, plan_hash, created_at, output_root, rules_source, status, plan_json)
            VALUES (?, ?, ?, ?, ?, 'previewed', ?)
            ON CONFLICT(batch_id) DO UPDATE SET
                plan_hash = excluded.plan_hash,
                plan_json = excluded.plan_json
            """,
            (
                plan.batch_id,
                plan.plan_hash,
                plan.created_at.isoformat(),
                plan.output_root,
                plan.rules_source,
                json.dumps(plan_to_dict(plan), ensure_ascii=False),
            ),
        )
        self._conn.commit()

    def load_plan(self, batch_id: str) -> Plan | None:
        """Return the stored plan for *batch_id*, or ``None``."""
        row = self._conn.execute(
            "SELECT plan_json FROM batches WHERE batch_id = ?",
            (batch_id,),
        ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row["plan_json"]))
        return plan_from_dict(payload)

    def batch_status(self, batch_id: str) -> str | None:
        """Return ``previewed`` / ``applying`` / ``applied`` / ``failed`` or ``None``."""
        row = self._conn.execute(
            "SELECT status FROM batches WHERE batch_id = ?",
            (batch_id,),
        ).fetchone()
        return None if row is None else str(row["status"])

    def latest_batch(self) -> str | None:
        """Return the most recent batch id, if any."""
        row = self._conn.execute(
            "SELECT batch_id FROM batches ORDER BY created_at DESC LIMIT 1",
        ).fetchone()
        return None if row is None else str(row["batch_id"])

    def has_any_batch(self) -> bool:
        """True when this database has seen at least one preview."""
        return self.latest_batch() is not None

    # -------------------------------------------------------------------- apply
    def start_apply(self, batch_id: str, options: dict[str, object] | None = None) -> None:
        """Mark a batch as being applied; refuse when it already finished."""
        status = self.batch_status(batch_id)
        if status is None:
            raise JournalError(f"unknown batch {batch_id!r}: run a preview first")
        if status == "applied":
            raise BatchAlreadyAppliedError(
                f"batch {batch_id!r} was already applied; refusing to run it twice",
            )
        self._conn.execute(
            "UPDATE batches SET status = 'applying', applied_at = ?, options_json = ? "
            "WHERE batch_id = ?",
            (_now(), json.dumps(options or {}, ensure_ascii=False), batch_id),
        )
        self._conn.commit()

    def intent(self, batch_id: str, seq: int, change: PlannedChange) -> None:
        """Write the planned-state row *before* touching the file system."""
        stamp = _now()
        self._conn.execute(
            """
            INSERT INTO operations
                (batch_id, seq, op, src, dst, state, size, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'planned', ?, ?, ?)
            ON CONFLICT(batch_id, seq) DO UPDATE SET
                state = 'planned', error = NULL, updated_at = excluded.updated_at
            """,
            (
                batch_id,
                seq,
                change.op or "unknown",
                change.src,
                change.dst,
                change.size,
                stamp,
                stamp,
            ),
        )
        self._conn.commit()

    def finish(
        self,
        batch_id: str,
        seq: int,
        state: str,
        *,
        final_dst: str | None = None,
        error: str | None = None,
        error_kind: str | None = None,
        cross_volume: bool | None = None,
    ) -> None:
        """Record the outcome of one operation immediately after it happens."""
        self._conn.execute(
            """
            UPDATE operations
               SET state = ?, final_dst = ?, error = ?, error_kind = ?,
                   cross_volume = ?, updated_at = ?
             WHERE batch_id = ? AND seq = ?
            """,
            (
                state,
                final_dst,
                error,
                error_kind,
                None if cross_volume is None else int(cross_volume),
                _now(),
                batch_id,
                seq,
            ),
        )
        self._conn.commit()

    def recover(self, batch_id: str) -> int:
        """Turn rows left in ``planned`` by a crash into ``interrupted`` records."""
        cursor = self._conn.execute(
            "UPDATE operations SET state = 'interrupted', updated_at = ? "
            "WHERE batch_id = ? AND state = 'planned'",
            (_now(), batch_id),
        )
        self._conn.commit()
        return int(cursor.rowcount)

    def completed_seqs(self, batch_id: str) -> set[int]:
        """Every sequence number already recorded as ``ok`` (idempotent re-runs)."""
        rows = self._conn.execute(
            "SELECT seq FROM operations WHERE batch_id = ? AND state = 'ok'",
            (batch_id,),
        ).fetchall()
        return {int(row["seq"]) for row in rows}

    def operations(self, batch_id: str) -> list[dict[str, object]]:
        """Return every operation row for reporting (ordered by seq)."""
        rows = self._conn.execute(
            "SELECT * FROM operations WHERE batch_id = ? ORDER BY seq",
            (batch_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def mark_finished(self, batch_id: str, status: str) -> None:
        """Close a batch with ``applied`` / ``failed`` / ``aborted``."""
        self._conn.execute(
            "UPDATE batches SET status = ?, finished_at = ? WHERE batch_id = ?",
            (status, _now(), batch_id),
        )
        self._conn.commit()

    def check_writable(self) -> str | None:
        """Return an error string when the database cannot take a write."""
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            self._conn.rollback()
        except sqlite3.Error as exc:
            return str(exc)
        return None

    def counts(self, batch_id: str) -> dict[str, int]:
        """Return ``{state: count}`` for one batch."""
        rows = self._conn.execute(
            "SELECT state, COUNT(*) AS n FROM operations WHERE batch_id = ? GROUP BY state",
            (batch_id,),
        ).fetchall()
        return {str(row["state"]): int(row["n"]) for row in rows}


__all__ = ["BatchAlreadyAppliedError", "Journal", "JournalError"]
