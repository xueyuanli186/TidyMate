"""Executor: the only module allowed to move, copy or recycle user files.

Invariants (each has a test):

* **never overwrite** - every destination is checked with ``exists`` immediately before the
  operation, and the same-volume move uses ``os.rename``, which fails instead of replacing;
* **never delete permanently** - the only removal is ``send2trash``; the only exception is
  rolling back a partial copy *we* created, which also goes to the recycle bin;
* **never report success without proof** - ``ok`` is written after the file system agrees
  (destination exists, source gone), not after the call returned;
* **write the intent first** - ``journal.intent`` runs before any file system call.

Cross-volume moves are the risky case: ``os.rename`` cannot cross volumes, and a naive
copy-then-delete loses data if the delete succeeds and the copy was short. The implementation
copies to a temporary sibling, verifies size + SHA-256, renames it into place, and only then
recycles the source.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
from collections.abc import Callable
from dataclasses import asdict
from pathlib import PureWindowsPath

from send2trash import send2trash

from tidymate_core.execution.models import (
    ExecutionOptions,
    ExecutionReport,
    OperationOutcome,
    OutcomeState,
)
from tidymate_core.journal import Journal
from tidymate_core.planning.models import ChangeStatus, Plan, PlannedChange
from tidymate_core.safety import blacklist, paths
from tidymate_core.scanning.cancel import CancelToken

_IN_USE_WINERRORS = frozenset({32, 33})
_PARTIAL_SUFFIX = ".tidymate-partial"


class _FatalError(RuntimeError):
    """Disk full / global permission loss: stop the batch instead of grinding through."""


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(paths.to_extended(path), "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _error_kind(exc: OSError) -> str:
    if isinstance(exc, FileExistsError):
        return "conflict"
    winerror = getattr(exc, "winerror", None)
    if winerror in _IN_USE_WINERRORS:
        return "in_use"
    if winerror == 112:  # ERROR_DISK_FULL
        return "disk_full"
    if isinstance(exc, PermissionError):
        return "permission_denied"
    return "os_error"


class Executor:
    """Apply one plan, one change at a time, journaling every step."""

    def __init__(
        self,
        journal: Journal,
        options: ExecutionOptions | None = None,
        *,
        cancel: CancelToken | None = None,
        on_event: Callable[[PlannedChange, OperationOutcome], None] | None = None,
    ) -> None:
        self._journal = journal
        self._options = options or ExecutionOptions()
        self._cancel = cancel
        self._on_event = on_event

    def run(self, plan: Plan) -> ExecutionReport:
        """Execute every eligible change; never raises for a single-file failure."""
        report = ExecutionReport(batch_id=plan.batch_id)
        self._journal.start_apply(plan.batch_id, asdict(self._options))
        recovered = self._journal.recover(plan.batch_id)
        if recovered:
            report.outcomes.extend(
                OperationOutcome(
                    seq=int(str(row["seq"])),
                    state=OutcomeState.INTERRUPTED,
                    src=str(row["src"]),
                    dst=str(row["dst"]) if row["dst"] is not None else None,
                    error="left unfinished by an earlier run",
                    error_kind="interrupted",
                )
                for row in self._journal.operations(plan.batch_id)
                if row["state"] == "interrupted"
            )

        completed = self._journal.completed_seqs(plan.batch_id)
        selected = self._select(plan)
        consecutive_failures = 0

        for change in selected:
            if self._cancel is not None and self._cancel.cancelled:
                report.cancelled = True
                break
            if change.seq in completed:
                outcome = OperationOutcome(
                    seq=change.seq,
                    state=OutcomeState.SKIPPED,
                    src=change.src,
                    dst=change.dst,
                    final_dst=change.dst,
                    error="already completed in an earlier run",
                    error_kind="already_done",
                )
                report.outcomes.append(outcome)
                self._emit(change, outcome)
                continue

            self._journal.intent(plan.batch_id, change.seq, change)
            if change.status is ChangeStatus.SKIP:
                outcome = OperationOutcome(
                    seq=change.seq,
                    state=OutcomeState.SKIPPED,
                    src=change.src,
                    dst=change.dst,
                    error="skipped before execution (user decision)",
                    error_kind=change.error_kind or "skip",
                )
            else:
                outcome = self._run_one(change)
            self._journal.finish(
                plan.batch_id,
                change.seq,
                outcome.state.value,
                final_dst=outcome.final_dst,
                error=outcome.error,
                error_kind=outcome.error_kind,
                cross_volume=outcome.cross_volume,
            )
            report.outcomes.append(outcome)
            self._emit(change, outcome)

            if outcome.state is OutcomeState.FAILED:
                consecutive_failures += 1
                if consecutive_failures >= self._options.fuse_after:
                    report.fused = True
                    break
            else:
                consecutive_failures = 0

        if report.fatal or report.cancelled or report.fused:
            self._journal.mark_finished(plan.batch_id, "aborted")
        else:
            self._journal.mark_finished(plan.batch_id, "applied")
        return report

    # ------------------------------------------------------------------ helpers
    def _select(self, plan: Plan) -> list[PlannedChange]:
        selected = [
            change
            for change in plan.changes
            if change.is_executable or change.error_kind == "ask_skipped"
        ]
        if self._options.only_rule is not None:
            selected = [c for c in selected if c.rule_id == self._options.only_rule]
        if self._options.limit is not None:
            selected = selected[: self._options.limit]
        return selected

    def _emit(self, change: PlannedChange, outcome: OperationOutcome) -> None:
        if self._on_event is not None:
            self._on_event(change, outcome)

    def _run_one(self, change: PlannedChange) -> OperationOutcome:
        try:
            self._preflight(change)
            if change.op == "trash":
                send2trash(self._display(change.src))
                return OperationOutcome(
                    seq=change.seq,
                    state=OutcomeState.OK,
                    src=change.src,
                    dst=None,
                    final_dst=None,
                )
            dst = change.dst
            if dst is None:
                raise ValueError("planned change has no destination")
            os.makedirs(self._display(_parent(dst)), exist_ok=True)

            if change.op == "rename":
                self._ensure_absent(dst)
                os.rename(self._display(change.src), self._display(dst))
                return self._ok(change, dst, cross_volume=False)

            if change.op == "move":
                cross = self._cross_volume(change.src, dst)
                if cross:
                    self._move_across_volumes(change.src, dst)
                else:
                    self._ensure_absent(dst)
                    os.rename(self._display(change.src), self._display(dst))
                return self._ok(change, dst, cross_volume=cross)

            if change.op == "copy":
                self._copy(change.src, dst)
                return self._ok(change, dst, cross_volume=False)

            raise ValueError(f"unsupported operation {change.op!r}")
        except _FatalError as exc:
            return OperationOutcome(
                seq=change.seq,
                state=OutcomeState.FAILED,
                src=change.src,
                dst=change.dst,
                error=str(exc),
                error_kind="fatal",
            )
        except OSError as exc:
            return OperationOutcome(
                seq=change.seq,
                state=OutcomeState.FAILED,
                src=change.src,
                dst=change.dst,
                error=f"{type(exc).__name__}: {exc}",
                error_kind=_error_kind(exc),
            )

    def _preflight(self, change: PlannedChange) -> None:
        hit = blacklist.check_blacklisted(change.src)
        if hit is not None:
            raise PermissionError(f"source is protected: {hit}")
        if change.dst is not None:
            hit = blacklist.check_blacklisted(change.dst)
            if hit is not None:
                raise PermissionError(f"target is protected: {hit}")
        if self._options.clear_readonly and os.path.exists(self._display(change.src)):
            mode = os.stat(self._display(change.src)).st_mode
            if not mode & stat.S_IWRITE:
                os.chmod(self._display(change.src), mode | stat.S_IWRITE)

    def _ensure_absent(self, dst: str) -> None:
        if os.path.exists(self._display(dst)):
            raise FileExistsError(f"destination already exists: {dst} (never overwrite)")

    def _cross_volume(self, src: str, dst: str) -> bool:
        try:
            return (
                os.stat(self._display(src)).st_dev
                != os.stat(
                    self._display(_parent(dst)),
                ).st_dev
            )
        except OSError:
            return False

    def _move_across_volumes(self, src: str, dst: str) -> None:
        temporary = self._display(dst) + _PARTIAL_SUFFIX
        if os.path.exists(temporary):
            raise FileExistsError(f"staging file already exists: {temporary}")
        try:
            shutil.copy2(self._display(src), temporary)
            if not self._same_content(src, temporary):
                raise OSError(f"copy verification failed for {src}")
            os.rename(temporary, self._display(dst))
        except BaseException:
            if os.path.exists(temporary):
                send2trash(temporary)
            raise
        try:
            send2trash(self._display(src))
        except OSError:
            # The copy is in place but the source could not be recycled: roll the copy back
            # through the recycle bin so the user is not left with two copies silently.
            send2trash(self._display(dst))
            raise

    def _copy(self, src: str, dst: str) -> None:
        self._ensure_absent(dst)
        shutil.copy2(self._display(src), self._display(dst))

    def _same_content(self, src: str, candidate: str) -> bool:
        src_size = os.stat(self._display(src)).st_size
        dst_size = os.stat(candidate).st_size
        return src_size == dst_size and _sha256(src) == _sha256(candidate)

    def _ok(self, change: PlannedChange, dst: str, *, cross_volume: bool) -> OperationOutcome:
        # Proof, not faith: the destination must exist and the source must be gone.
        if not os.path.exists(self._display(dst)):
            raise OSError(f"destination missing after operation: {dst}")
        if change.op in {"move", "rename"} and os.path.exists(self._display(change.src)):
            raise OSError(f"source still exists after move: {change.src}")
        return OperationOutcome(
            seq=change.seq,
            state=OutcomeState.OK,
            src=change.src,
            dst=dst,
            final_dst=dst,
            cross_volume=cross_volume,
        )

    @staticmethod
    def _display(path: str) -> str:
        return paths.from_extended(path)


def _parent(path: str) -> str:
    return str(PureWindowsPath(paths.normalize(path)).parent)
