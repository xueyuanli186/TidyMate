"""GUI-agnostic execution helpers for the stage-8 window.

The widget layer never re-implements safety logic: ``run_apply`` calls the same
``gate.evaluate`` + ``Executor`` the CLI uses, and ``run_undo`` calls the same ``Undoer``.
"""

from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass
from pathlib import Path

from tidymate_core.execution import (
    ExecutionOptions,
    ExecutionReport,
    Executor,
    GateResult,
    Undoer,
    UndoReport,
    evaluate,
    write_reports,
)
from tidymate_core.journal import Journal, JournalError
from tidymate_core.planning import Plan


def default_db_path() -> Path:
    """Same database location as the CLI."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "TidyMate" / "tidymate.db"


@dataclass(frozen=True, slots=True)
class ApplySummary:
    """What the confirmation dialog must show before writing anything."""

    count: int
    directories: int
    trash: int
    policy: str


def describe_apply(plan: Plan) -> ApplySummary:
    """Summarise an executable plan for the confirmation dialog."""
    executable = [change for change in plan.changes if change.is_executable]
    directories = {str(Path(change.dst).parent) for change in executable if change.dst}
    trash = sum(1 for change in executable if (change.op or "").lower() == "trash")
    rename_override = any("overridden to 'rename'" in warning for warning in plan.warnings)
    policy = "rename（自动改名，不覆盖任何已有文件）" if rename_override else "按规则（skip 默认）"
    return ApplySummary(len(executable), len(directories), trash, policy)


def open_journal(db_path: str | Path | None = None) -> Journal:
    """Open (and create if needed) the journal used by the window."""
    return Journal(Path(db_path) if db_path is not None else default_db_path())


def record_preview(journal: Journal, plan: Plan, rules_file: str, root: str) -> None:
    """Persist the dry-run so the gate can verify the hash at apply time."""
    journal.record_preview(
        plan,
        roots=(root,),
        rules_file=rules_file,
        rules_hash=None,
        conflict_policy=None,
        app_version="",
    )


def preflight(plan: Plan, journal: Journal, options: ExecutionOptions | None = None) -> GateResult:
    """Run the gates without executing (the window shows the problems verbatim)."""
    return evaluate(plan, journal, options or ExecutionOptions())


def run_apply(
    plan: Plan,
    journal: Journal,
    options: ExecutionOptions | None = None,
) -> tuple[GateResult, ExecutionReport | None]:
    """Evaluate the gates and, when they pass, execute the plan."""
    gate = evaluate(plan, journal, options or ExecutionOptions())
    if not gate.ok:
        return gate, None
    report = Executor(journal, options).run(plan)
    with contextlib.suppress(JournalError):
        write_reports(journal, plan.batch_id, journal.path.parent / "reports")
    return gate, report


def undo_preview(journal: Journal, batch_id: str) -> UndoReport:
    """Dry-run the undo so the window can show what would be restored."""
    return Undoer(journal).run(batch_id, dry_run=True)


def run_undo(journal: Journal, batch_id: str) -> UndoReport:
    """Execute the undo and write its error report."""
    report = Undoer(journal).run(batch_id)
    with contextlib.suppress(JournalError):
        write_reports(journal, batch_id, journal.path.parent / "reports")
    return report
