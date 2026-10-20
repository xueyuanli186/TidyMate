"""SQLite journal: the only durable record of what a batch did (M7).

Iron rule 7 lives here: **write the intent before touching a file, update the outcome
immediately afterwards**. Nothing is buffered "until the end", because a crash between two
files must still leave a truthful log.

Schema notes
------------
* ``(batch_id, seq)`` is the natural key; the requirement's surrogate ``id`` column is not
  needed for identity and is intentionally omitted (the UNIQUE constraint carries the same
  semantics). Every other column from the required DDL exists.
* Older databases (stage 5-6) are migrated in place with ``ALTER TABLE ... ADD COLUMN``;
  no row is dropped.
* Statistics columns on ``batches`` are a cache. :meth:`Journal.refresh_stats` recomputes
  them from ``operations`` in SQL, so the cache can never drift from the rows.
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
    batch_id        TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL,
    finished_at     TEXT,
    app_version     TEXT NOT NULL DEFAULT '',
    roots           TEXT NOT NULL DEFAULT '[]',
    rules_file      TEXT,
    rules_hash      TEXT,
    plan_hash       TEXT,
    mode            TEXT NOT NULL DEFAULT 'dryrun',
    conflict_policy TEXT,
    status          TEXT NOT NULL,
    total           INTEGER NOT NULL DEFAULT 0,
    ok              INTEGER NOT NULL DEFAULT 0,
    failed          INTEGER NOT NULL DEFAULT 0,
    skipped         INTEGER NOT NULL DEFAULT 0,
    undo_total      INTEGER NOT NULL DEFAULT 0,
    undo_ok         INTEGER NOT NULL DEFAULT 0,
    undo_failed     INTEGER NOT NULL DEFAULT 0,
    notes           TEXT,
    output_root     TEXT NOT NULL DEFAULT '',
    rules_source    TEXT NOT NULL DEFAULT '',
    applied_at      TEXT,
    options_json    TEXT,
    plan_json       TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS operations (
    batch_id          TEXT NOT NULL,
    seq               INTEGER NOT NULL,
    op                TEXT NOT NULL,
    src               TEXT NOT NULL,
    dst               TEXT,
    final_dst         TEXT,
    size              INTEGER NOT NULL DEFAULT 0,
    mtime_utc         TEXT,
    src_existed       INTEGER,
    dst_existed_before INTEGER,
    state             TEXT NOT NULL,
    error             TEXT,
    error_kind        TEXT,
    flags             TEXT,
    recycle_ref       TEXT,
    cross_volume      INTEGER,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    executed_at       TEXT,
    undone_at         TEXT,
    PRIMARY KEY (batch_id, seq),
    FOREIGN KEY (batch_id) REFERENCES batches(batch_id)
);

CREATE INDEX IF NOT EXISTS idx_ops_batch_state ON operations (batch_id, state);
CREATE INDEX IF NOT EXISTS idx_ops_src ON operations (src);
"""

_BATCH_COLUMNS = {
    "finished_at": "TEXT",
    "app_version": "TEXT NOT NULL DEFAULT ''",
    "roots": "TEXT NOT NULL DEFAULT '[]'",
    "rules_file": "TEXT",
    "rules_hash": "TEXT",
    "plan_hash": "TEXT",
    "mode": "TEXT NOT NULL DEFAULT 'dryrun'",
    "conflict_policy": "TEXT",
    "total": "INTEGER NOT NULL DEFAULT 0",
    "ok": "INTEGER NOT NULL DEFAULT 0",
    "failed": "INTEGER NOT NULL DEFAULT 0",
    "skipped": "INTEGER NOT NULL DEFAULT 0",
    "undo_total": "INTEGER NOT NULL DEFAULT 0",
    "undo_ok": "INTEGER NOT NULL DEFAULT 0",
    "undo_failed": "INTEGER NOT NULL DEFAULT 0",
    "notes": "TEXT",
    "output_root": "TEXT NOT NULL DEFAULT ''",
    "rules_source": "TEXT NOT NULL DEFAULT ''",
    "applied_at": "TEXT",
    "options_json": "TEXT",
    "plan_json": "TEXT NOT NULL DEFAULT '{}'",
}

_OPERATION_COLUMNS = {
    "final_dst": "TEXT",
    "size": "INTEGER NOT NULL DEFAULT 0",
    "mtime_utc": "TEXT",
    "src_existed": "INTEGER",
    "dst_existed_before": "INTEGER",
    "error": "TEXT",
    "error_kind": "TEXT",
    "flags": "TEXT",
    "recycle_ref": "TEXT",
    "cross_volume": "INTEGER",
    "executed_at": "TEXT",
    "undone_at": "TEXT",
}


class JournalError(RuntimeError):
    """Base class for journal refusals."""


class BatchAlreadyAppliedError(JournalError):
    """Raised when ``apply`` is asked to run a batch that already finished."""


class BatchAlreadyUndoneError(JournalError):
    """Raised when ``undo`` is asked to run twice."""


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _migrate(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = _columns(conn, table)
    for name, ddl in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


class Journal:
    """Thin, explicit wrapper around one SQLite file."""

    def __init__(self, db_path: str | Path) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        _migrate(self._conn, "batches", _BATCH_COLUMNS)
        _migrate(self._conn, "operations", _OPERATION_COLUMNS)
        self._conn.execute("PRAGMA user_version=1")
        self._conn.commit()

    def close(self) -> None:
        """Close the underlying connection."""
        self._conn.close()

    def __enter__(self) -> Journal:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ------------------------------------------------------------------ previews
    def record_preview(
        self,
        plan: Plan,
        *,
        roots: tuple[str, ...] = (),
        rules_file: str | None = None,
        rules_hash: str | None = None,
        conflict_policy: str | None = None,
        app_version: str = "",
    ) -> None:
        """Persist a dry-run plan so ``apply`` can prove the hash still matches."""
        row = self._conn.execute(
            "SELECT status, plan_hash FROM batches WHERE batch_id = ?",
            (plan.batch_id,),
        ).fetchone()
        if row is not None:
            if row["status"] in {"running", "applying", "applied", "completed", "partial"}:
                raise JournalError(
                    f"batch {plan.batch_id!r} already started; a new preview gets a new id",
                )
            if row["plan_hash"] and row["plan_hash"] != plan.plan_hash:
                raise JournalError(
                    f"batch {plan.batch_id!r} already has a different plan hash; "
                    "re-run the preview in another second",
                )
        self._conn.execute(
            """
            INSERT INTO batches
                (batch_id, created_at, app_version, roots, rules_file, rules_hash,
                 plan_hash, mode, conflict_policy, status, output_root, rules_source,
                 plan_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'dryrun', ?, 'previewed', ?, ?, ?)
            ON CONFLICT(batch_id) DO UPDATE SET
                plan_hash = excluded.plan_hash,
                plan_json = excluded.plan_json,
                roots = excluded.roots,
                rules_file = excluded.rules_file,
                rules_hash = excluded.rules_hash,
                conflict_policy = excluded.conflict_policy
            """,
            (
                plan.batch_id,
                plan.created_at.isoformat(),
                app_version,
                json.dumps(list(roots), ensure_ascii=False),
                rules_file or plan.rules_source,
                rules_hash,
                plan.plan_hash,
                conflict_policy,
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
        if row is None or not row["plan_json"]:
            return None
        return plan_from_dict(json.loads(str(row["plan_json"])))

    def batch_status(self, batch_id: str) -> str | None:
        """Return the batch status string, or ``None``."""
        row = self._conn.execute(
            "SELECT status FROM batches WHERE batch_id = ?",
            (batch_id,),
        ).fetchone()
        return None if row is None else str(row["status"])

    def batch_row(self, batch_id: str) -> dict[str, object] | None:
        """Return the full batch row as a dictionary."""
        row = self._conn.execute(
            "SELECT * FROM batches WHERE batch_id = ?",
            (batch_id,),
        ).fetchone()
        return None if row is None else dict(row)

    def list_batches(self, limit: int = 20) -> list[dict[str, object]]:
        """Most recent batches first."""
        rows = self._conn.execute(
            "SELECT * FROM batches ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

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
        """Mark a batch as running; refuse when it already finished."""
        status = self.batch_status(batch_id)
        if status is None:
            raise JournalError(f"unknown batch {batch_id!r}: run a preview first")
        if status in {"applied", "completed", "partial"}:
            raise BatchAlreadyAppliedError(
                f"batch {batch_id!r} was already applied; refusing to run it twice",
            )
        self._conn.execute(
            "UPDATE batches SET status = 'running', mode = 'apply', applied_at = ?, "
            "options_json = ? WHERE batch_id = ?",
            (_now(), json.dumps(options or {}, ensure_ascii=False), batch_id),
        )
        self._conn.commit()

    def intent(self, batch_id: str, seq: int, change: PlannedChange) -> None:
        """Write the planned-state row *before* touching the file system."""
        stamp = _now()
        mtime = change.mtime_utc.isoformat() if change.mtime_utc is not None else None
        flags = json.dumps(list(change.flags), ensure_ascii=False)
        self._conn.execute(
            """
            INSERT INTO operations
                (batch_id, seq, op, src, dst, size, mtime_utc, src_existed,
                 dst_existed_before, state, flags, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'planned', ?, ?, ?)
            ON CONFLICT(batch_id, seq) DO UPDATE SET
                state = 'planned', error = NULL, error_kind = NULL,
                updated_at = excluded.updated_at
            """,
            (
                batch_id,
                seq,
                change.op or "unknown",
                change.src,
                change.dst,
                change.size,
                mtime,
                1,
                1 if change.dst is not None else 0,
                flags,
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
        recycle_ref: str | None = None,
    ) -> None:
        """Record the outcome of one operation immediately after it happens."""
        self._conn.execute(
            """
            UPDATE operations
               SET state = ?, final_dst = ?, error = ?, error_kind = ?,
                   cross_volume = ?, recycle_ref = ?, executed_at = ?, updated_at = ?
             WHERE batch_id = ? AND seq = ?
            """,
            (
                state,
                final_dst,
                error,
                error_kind,
                None if cross_volume is None else int(cross_volume),
                recycle_ref,
                _now(),
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
            "WHERE batch_id = ? AND state IN ('planned', 'running')",
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
        """Close a batch with ``completed`` / ``partial`` / ``failed`` / ``cancelled``."""
        self._conn.execute(
            "UPDATE batches SET status = ?, finished_at = ? WHERE batch_id = ?",
            (status, _now(), batch_id),
        )
        self._conn.commit()
        self.refresh_stats(batch_id)

    # ---------------------------------------------------------------- statistics
    def agg_stats(self, batch_id: str) -> dict[str, int]:
        """Aggregate counts in SQL; never from in-memory counters."""
        row = self._conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN state = 'ok' THEN 1 ELSE 0 END) AS ok,
                SUM(CASE WHEN state = 'failed' THEN 1 ELSE 0 END) AS failed,
                SUM(CASE WHEN state = 'skipped' THEN 1 ELSE 0 END) AS skipped,
                SUM(CASE WHEN undone_at IS NOT NULL THEN 1 ELSE 0 END) AS undo_total,
                SUM(CASE WHEN undone_at IS NOT NULL AND state = 'undone' THEN 1 ELSE 0 END)
                    AS undo_ok,
                SUM(CASE WHEN undone_at IS NOT NULL AND state = 'undo_failed' THEN 1 ELSE 0 END)
                    AS undo_failed
            FROM operations WHERE batch_id = ?
            """,
            (batch_id,),
        ).fetchone()
        return {
            "total": int(row["total"] or 0),
            "ok": int(row["ok"] or 0),
            "failed": int(row["failed"] or 0),
            "skipped": int(row["skipped"] or 0),
            "undo_total": int(row["undo_total"] or 0),
            "undo_ok": int(row["undo_ok"] or 0),
            "undo_failed": int(row["undo_failed"] or 0),
        }

    def refresh_stats(self, batch_id: str) -> dict[str, int]:
        """Recompute the cached counters on ``batches`` from the rows."""
        stats = self.agg_stats(batch_id)
        self._conn.execute(
            """
            UPDATE batches SET total = ?, ok = ?, failed = ?, skipped = ?,
                   undo_total = ?, undo_ok = ?, undo_failed = ?
             WHERE batch_id = ?
            """,
            (
                stats["total"],
                stats["ok"],
                stats["failed"],
                stats["skipped"],
                stats["undo_total"],
                stats["undo_ok"],
                stats["undo_failed"],
                batch_id,
            ),
        )
        self._conn.commit()
        return stats

    def counts(self, batch_id: str) -> dict[str, int]:
        """Return ``{state: count}`` for one batch."""
        rows = self._conn.execute(
            "SELECT state, COUNT(*) AS n FROM operations WHERE batch_id = ? GROUP BY state",
            (batch_id,),
        ).fetchall()
        return {str(row["state"]): int(row["n"]) for row in rows}

    # --------------------------------------------------------------------- undo
    def undo_candidates(self, batch_id: str) -> list[dict[str, object]]:
        """Operations that were executed and have not been undone yet."""
        rows = self._conn.execute(
            "SELECT * FROM operations WHERE batch_id = ? AND state = 'ok' "
            "AND undone_at IS NULL ORDER BY seq DESC",
            (batch_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def start_undo(self, batch_id: str) -> None:
        """Flip the batch into ``undoing``; refuse when there is nothing to undo."""
        status = self.batch_status(batch_id)
        if status is None:
            raise JournalError(f"unknown batch {batch_id!r}")
        if not self.undo_candidates(batch_id):
            raise BatchAlreadyUndoneError(f"batch {batch_id!r} has nothing left to undo")
        self._conn.execute(
            "UPDATE batches SET status = 'undoing' WHERE batch_id = ?",
            (batch_id,),
        )
        self._conn.commit()

    def finish_undo(
        self,
        batch_id: str,
        seq: int,
        state: str,
        *,
        error: str | None = None,
        error_kind: str | None = None,
    ) -> None:
        """Record one undo outcome (``undone`` or ``undo_failed``)."""
        self._conn.execute(
            """
            UPDATE operations SET state = ?, error = ?, error_kind = ?, undone_at = ?,
                   updated_at = ?
             WHERE batch_id = ? AND seq = ?
            """,
            (state, error, error_kind, _now(), _now(), batch_id, seq),
        )
        self._conn.commit()

    def close_undo(self, batch_id: str) -> str:
        """Close an undo run as ``undone`` or ``undo_partial`` and return that status."""
        stats = self.refresh_stats(batch_id)
        status = "undone" if stats["undo_failed"] == 0 else "undo_partial"
        self._conn.execute(
            "UPDATE batches SET status = ?, finished_at = ? WHERE batch_id = ?",
            (status, _now(), batch_id),
        )
        self._conn.commit()
        return status

    def check_writable(self) -> str | None:
        """Return an error string when the database cannot take a write."""
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            self._conn.rollback()
        except sqlite3.Error as exc:
            return str(exc)
        return None


__all__ = ["BatchAlreadyAppliedError", "BatchAlreadyUndoneError", "Journal", "JournalError"]
