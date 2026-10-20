"""Pre-flight gate: every condition that can reject a whole batch.

The product rule is explicit: a gate failure rejects the **batch**, not one entry. "Apply
93 of 100 files and skip the ones in C:\\Windows" is not a safer middle ground - it means
the user's mental model of the plan no longer matches what runs.

What is checked here:

* a stored preview with the same ``batch_id`` and ``plan_hash`` exists;
* no path hits the hard-coded blacklist, the UNC policy, or an installer directory;
* no source/target pair is an ancestor of the other;
* the journal is writable and the target volume has ``copy_bytes * 1.2`` free.

User confirmation is enforced by the CLI (and later the GUI), because "confirmed" belongs
to the invocation rather than to the plan; the executor records it in the journal.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import PureWindowsPath

from tidymate_core.execution.models import ExecutionOptions
from tidymate_core.journal import Journal
from tidymate_core.planning.models import ChangeStatus, Plan
from tidymate_core.safety import blacklist, paths

#: Headroom over the raw copy size, so a batch cannot fill the volume to the last byte.
SPACE_MARGIN = 1.2


@dataclass(frozen=True, slots=True)
class GateProblem:
    """One reason the batch must not run."""

    code: str
    message: str
    seq: int | None = None

    def render(self) -> str:
        """Return a single line for the CLI."""
        where = f" (seq {self.seq})" if self.seq is not None else ""
        return f"[{self.code}]{where} {self.message}"


@dataclass(frozen=True, slots=True)
class GateResult:
    """Outcome of the pre-flight checks."""

    problems: tuple[GateProblem, ...]
    warnings: tuple[str, ...] = ()
    copy_bytes: int = 0
    free_bytes: int | None = None

    @property
    def ok(self) -> bool:
        """True only when nothing blocks the batch."""
        return not self.problems


def _parent_dir(path: str) -> str:
    return str(PureWindowsPath(paths.normalize(path)).parent)


def _free_space(path: str) -> int | None:
    """Free bytes on the volume holding *path* (walking up to the first existing parent)."""
    candidate = paths.normalize(path)
    for _ in range(64):
        if os.path.exists(candidate):
            try:
                return int(shutil.disk_usage(candidate).free)
            except OSError:
                return None
        parent = str(PureWindowsPath(candidate).parent)
        if parent == candidate:
            return None
        candidate = parent
    return None


def evaluate(plan: Plan, journal: Journal, options: ExecutionOptions | None = None) -> GateResult:
    """Run every pre-flight check and return the complete problem list."""
    opts = options or ExecutionOptions()
    problems: list[GateProblem] = []
    warnings: list[str] = []

    stored = journal.load_plan(plan.batch_id)
    if stored is None:
        problems.append(
            GateProblem(
                "no_preview",
                f"no dry-run preview for batch {plan.batch_id!r}; run `plan` first",
            ),
        )
    elif stored.plan_hash != plan.plan_hash:
        problems.append(
            GateProblem(
                "plan_changed",
                "the plan no longer matches the preview (plan_hash differs): "
                "files or rules changed since the dry-run",
            ),
        )

    for change in plan.changes:
        if change.status is not ChangeStatus.EXECUTE or change.dst is None:
            continue
        for label, value in (("source", change.src), ("target", change.dst)):
            hit = blacklist.check_blacklisted(value)
            if hit is not None:
                problems.append(
                    GateProblem("blacklist", f"{label} is protected: {hit}", change.seq),
                )
            unc = blacklist.check_unc(value)
            if unc is not None and not opts.allow_unc:
                problems.append(GateProblem("unc", f"{label}: {unc}", change.seq))
            installer = blacklist.check_installer_directory(_parent_dir(value))
            if installer is not None:
                problems.append(
                    GateProblem("installer_dir", f"{label} directory: {installer}", change.seq),
                )

        if paths.is_ancestor_or_self(change.src, change.dst) or paths.is_ancestor_or_self(
            change.dst,
            change.src,
        ):
            problems.append(
                GateProblem(
                    "ancestor",
                    f"target {change.dst!r} and source {change.src!r} overlap",
                    change.seq,
                ),
            )

    db_error = journal.check_writable()
    if db_error is not None:
        problems.append(GateProblem("journal", f"journal database is not writable: {db_error}"))

    copy_bytes = sum(
        change.size
        for change in plan.changes
        if change.status is ChangeStatus.EXECUTE
        and change.is_executable
        and (change.op or "").lower() == "copy"
    )
    free = _free_space(plan.output_root)
    if copy_bytes and free is not None and free < int(copy_bytes * SPACE_MARGIN):
        problems.append(
            GateProblem(
                "disk_space",
                f"need {int(copy_bytes * SPACE_MARGIN)} bytes free for copy, have {free}",
            ),
        )
    elif copy_bytes and free is None:
        warnings.append("could not determine free space; the copy size was not checked")

    return GateResult(tuple(problems), tuple(warnings), copy_bytes, free)
