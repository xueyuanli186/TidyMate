"""Undo engine (M8): put every executed change back, or say precisely why not.

Safety rules, in the order they are checked:

1. the destination must still exist (``missing`` otherwise);
2. its size and mtime must match the journal (``modified_since`` otherwise) - a file the
   user edited is never moved, because moving it would silently relocate new content;
3. the original location must be free (``src_occupied``) - never overwrite;
4. only then is the file moved back, using ``os.rename`` on one volume and
   copy + verify + recycle on several.

Undo runs in reverse ``seq`` order, one independent journal write per item, so an
interrupted undo leaves a truthful, resumable log.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import PureWindowsPath

from send2trash import send2trash

from tidymate_core.execution.recycle import restore_to
from tidymate_core.journal import Journal
from tidymate_core.safety import paths
from tidymate_core.scanning.cancel import CancelToken

_MTIME_TOLERANCE_S = 2.0


@dataclass(frozen=True, slots=True)
class UndoOutcome:
    """What happened to one operation during undo."""

    seq: int
    op: str
    src: str
    dst: str | None
    state: str  # undone | undo_failed | would_undo | would_fail
    error: str | None = None
    error_kind: str | None = None


@dataclass(slots=True)
class UndoReport:
    """Result of one undo run."""

    batch_id: str
    outcomes: list[UndoOutcome] = field(default_factory=list)
    dry_run: bool = False
    cancelled: bool = False
    status: str = "preview"

    @property
    def undone(self) -> int:
        """Number of items actually restored."""
        return sum(1 for outcome in self.outcomes if outcome.state == "undone")

    @property
    def failed(self) -> int:
        """Number of items that could not be restored."""
        return sum(1 for outcome in self.outcomes if outcome.state == "undo_failed")


def _display(path: str) -> str:
    return paths.from_extended(path)


def _parent(path: str) -> str:
    return str(PureWindowsPath(paths.normalize(path)).parent)


def _matches_journal(row: dict[str, object], path: str) -> tuple[bool, str]:
    """Compare size (and mtime when recorded) with the journal."""
    try:
        stat_result = os.stat(_display(path))
    except OSError as exc:
        return False, f"cannot stat {path!r}: {exc}"
    expected_size = int(str(row.get("size") or 0))
    if expected_size and stat_result.st_size != expected_size:
        return False, f"size changed since apply ({stat_result.st_size} != {expected_size})"
    raw_mtime = row.get("mtime_utc")
    if raw_mtime:
        expected = datetime.fromisoformat(str(raw_mtime)).timestamp()
        if abs(stat_result.st_mtime - expected) > _MTIME_TOLERANCE_S:
            return False, "mtime changed since apply"
    return True, ""


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(_display(path), "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Undoer:
    """Reverse one applied batch, one operation at a time."""

    def __init__(
        self,
        journal: Journal,
        *,
        cancel: CancelToken | None = None,
        on_event: object | None = None,
    ) -> None:
        self._journal = journal
        self._cancel = cancel
        self._on_event = on_event

    def run(self, batch_id: str, *, dry_run: bool = False) -> UndoReport:
        """Undo every executed change of *batch_id* (or preview what would happen)."""
        candidates = self._journal.undo_candidates(batch_id)
        if not candidates:
            report = UndoReport(batch_id=batch_id, dry_run=dry_run)
            report.status = self._journal.batch_status(batch_id) or "undone"
            return report
        report = UndoReport(batch_id=batch_id, dry_run=dry_run)
        if not dry_run:
            self._journal.start_undo(batch_id)

        for row in candidates:
            if self._cancel is not None and self._cancel.cancelled:
                report.cancelled = True
                break
            outcome = self._undo_one(row, dry_run=dry_run)
            report.outcomes.append(outcome)
            if self._on_event is not None and callable(self._on_event):
                self._on_event(row, outcome)
            if not dry_run:
                self._journal.finish_undo(
                    batch_id,
                    int(str(row["seq"])),
                    "undone" if outcome.state == "undone" else "undo_failed",
                    error=outcome.error,
                    error_kind=outcome.error_kind,
                )

        if not dry_run:
            self._prune_empty_directories(batch_id)
            report.status = self._journal.close_undo(batch_id)
        return report

    def _prune_empty_directories(self, batch_id: str) -> None:
        """Recycle directories this batch created and that undo has emptied.

        Only directories below the batch's own ``output_root`` are considered, deepest
        first, and only when they are empty. A user directory that existed before the run
        is therefore never removed.
        """
        batch = self._journal.batch_row(batch_id) or {}
        root = str(batch.get("output_root") or "")
        if not root:
            return
        directories: set[str] = set()
        for row in self._journal.operations(batch_id):
            final = row.get("final_dst")
            if final:
                directories.add(_parent(str(final)))
        for directory in sorted(directories, key=len, reverse=True):
            try:
                if not os.path.isdir(_display(directory)):
                    continue
                if os.listdir(_display(directory)):
                    continue
                if (
                    not os.path.abspath(_display(directory))
                    .lower()
                    .startswith(os.path.abspath(_display(root)).lower())
                ):
                    continue
                if (
                    os.path.abspath(_display(directory)).lower()
                    == os.path.abspath(_display(root)).lower()
                ):
                    continue
                send2trash(_display(directory))
            except OSError:
                continue

    # ------------------------------------------------------------------ per item
    def _undo_one(self, row: dict[str, object], *, dry_run: bool) -> UndoOutcome:
        op = str(row["op"])
        src = str(row["src"])
        dst = row.get("final_dst") or row.get("dst")
        dst_text = str(dst) if dst is not None else None
        seq = int(str(row["seq"]))

        if op in {"move", "rename"}:
            return self._undo_move(row, seq, op, src, dst_text, dry_run=dry_run)
        if op == "copy":
            return self._undo_copy(row, seq, src, dst_text, dry_run=dry_run)
        if op == "trash":
            return self._undo_trash(row, seq, src, dry_run=dry_run)
        return UndoOutcome(
            seq=seq,
            op=op,
            src=src,
            dst=dst_text,
            state="undo_failed",
            error=f"unknown operation {op!r}",
            error_kind="unknown",
        )

    def _undo_move(
        self,
        row: dict[str, object],
        seq: int,
        op: str,
        src: str,
        dst: str | None,
        *,
        dry_run: bool,
    ) -> UndoOutcome:
        if dst is None:
            return UndoOutcome(seq, op, src, None, "undo_failed", "no destination", "missing")
        if not os.path.exists(_display(dst)):
            return UndoOutcome(
                seq,
                op,
                src,
                dst,
                "undo_failed",
                "the file is no longer at its planned destination",
                "missing",
            )
        matches, why = _matches_journal(row, dst)
        if not matches:
            return UndoOutcome(seq, op, src, dst, "undo_failed", why, "modified_since")
        if os.path.exists(_display(src)):
            return UndoOutcome(
                seq,
                op,
                src,
                dst,
                "undo_failed",
                "the original path is occupied by another file",
                "src_occupied",
            )
        if dry_run:
            return UndoOutcome(seq, op, src, dst, "would_undo")

        os.makedirs(_display(_parent(src)), exist_ok=True)
        try:
            if os.stat(_display(dst)).st_dev == os.stat(_display(_parent(src))).st_dev:
                os.rename(_display(dst), _display(src))
            else:
                self._move_back_across_volumes(dst, src)
        except OSError as exc:
            return UndoOutcome(
                seq,
                op,
                src,
                dst,
                "undo_failed",
                f"{type(exc).__name__}: {exc}",
                "permission" if isinstance(exc, PermissionError) else "unknown",
            )
        return UndoOutcome(seq, op, src, dst, "undone")

    def _move_back_across_volumes(self, dst: str, src: str) -> None:
        temporary = _display(src) + ".tidymate-undo"
        if os.path.exists(temporary):
            raise FileExistsError(f"staging file already exists: {temporary}")
        shutil.copy2(_display(dst), temporary)
        if os.stat(temporary).st_size != os.stat(_display(dst)).st_size:
            send2trash(temporary)
            raise OSError("copy size mismatch during undo")
        if _sha256(temporary) != _sha256(dst):
            send2trash(temporary)
            raise OSError("copy hash mismatch during undo")
        os.rename(temporary, _display(src))
        try:
            send2trash(_display(dst))
        except OSError:
            # The restored copy exists; the extra one could not be recycled. Never delete
            # it permanently - report the failure so a human can decide.
            raise OSError(f"restored to {src} but could not recycle {dst}") from None

    def _undo_copy(
        self,
        row: dict[str, object],
        seq: int,
        src: str,
        dst: str | None,
        *,
        dry_run: bool,
    ) -> UndoOutcome:
        if dst is None or not os.path.exists(_display(dst)):
            return UndoOutcome(
                seq,
                "copy",
                src,
                dst,
                "undo_failed",
                "the copy no longer exists",
                "missing",
            )
        matches, why = _matches_journal(row, dst)
        if not matches:
            return UndoOutcome(seq, "copy", src, dst, "undo_failed", why, "modified_since")
        if dry_run:
            return UndoOutcome(seq, "copy", src, dst, "would_undo")
        try:
            send2trash(_display(dst))
        except OSError as exc:
            return UndoOutcome(
                seq,
                "copy",
                src,
                dst,
                "undo_failed",
                f"{type(exc).__name__}: {exc}",
                "permission",
            )
        return UndoOutcome(seq, "copy", src, dst, "undone")

    def _undo_trash(
        self, row: dict[str, object], seq: int, src: str, *, dry_run: bool
    ) -> UndoOutcome:
        reference = row.get("recycle_ref")
        original = src
        if reference:
            try:
                payload = json.loads(str(reference))
                original = str(payload.get("original", src))
            except (ValueError, TypeError):
                original = src
        if dry_run:
            return UndoOutcome(seq, "trash", src, None, "would_undo")
        restored, reason = restore_to(original)
        if restored:
            return UndoOutcome(seq, "trash", src, None, "undone")
        if reason == "not_found":
            return UndoOutcome(
                seq,
                "trash",
                src,
                None,
                "undo_failed",
                "the item is no longer in the recycle bin; restore it manually or from a backup",
                "recycle_gone",
            )
        return UndoOutcome(
            seq,
            "trash",
            src,
            None,
            "undo_failed",
            f"shell refused: {reason}",
            "unknown",
        )
