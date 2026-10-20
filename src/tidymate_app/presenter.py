"""GUI-agnostic presentation logic for the PySide6 shell.

Kept free of Qt imports so it can be unit tested on any machine, including CI runners
without PySide6 installed. The widget layer is deliberately thin: it only moves strings
from this module into widgets.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tidymate_core.planning import (
    ChangeStatus,
    Plan,
    PlanRequest,
    build_plan,
    write_artifacts,
)
from tidymate_core.rules import RuleLoadError, load_rules
from tidymate_core.scanning import ScanConfig

#: Column headers of the preview table, in display order.
TABLE_HEADERS: tuple[str, ...] = (
    "seq",
    "status",
    "op",
    "rule",
    "conflict",
    "source",
    "destination",
)


@dataclass(frozen=True, slots=True)
class DryRunOutcome:
    """Result of a dry-run request: a plan, or a message explaining why not."""

    plan: Plan | None
    error: str | None = None


def run_dry_run(root: str, rules_path: str, output_root: str) -> DryRunOutcome:
    """Load rules, scan *root* and build a plan. Never writes anything."""
    if not root:
        return DryRunOutcome(plan=None, error="请先选择要整理的目录")
    if not rules_path:
        return DryRunOutcome(plan=None, error="请先选择规则文件")
    if not output_root:
        return DryRunOutcome(plan=None, error="请先选择目标根目录")
    if not Path(root).is_dir():
        return DryRunOutcome(plan=None, error=f"目录不存在：{root}")

    try:
        ruleset = load_rules(rules_path)
    except RuleLoadError as exc:
        return DryRunOutcome(plan=None, error=str(exc))

    request = PlanRequest(
        scan=ScanConfig(roots=(root,)),
        rules=ruleset,
        output_root=output_root,
    )
    return DryRunOutcome(plan=build_plan(request))


def table_rows(plan: Plan) -> list[list[str]]:
    """Flatten a plan into table cells (one list per row)."""
    rows: list[list[str]] = []
    for change in plan.changes:
        rows.append(
            [
                f"{change.seq:04d}",
                change.status.value,
                change.op or "-",
                change.rule_id or "-",
                change.conflict.value,
                change.src,
                change.dst or ("<recycle bin>" if change.op == "trash" else "-"),
            ],
        )
    return rows


def is_conflict_row(plan: Plan, row_index: int) -> bool:
    """True when the table row at *row_index* is a conflict or a rejection."""
    if row_index < 0 or row_index >= len(plan.changes):
        return False
    change = plan.changes[row_index]
    return change.conflict.value != "none" or change.status is ChangeStatus.REJECT


def summary_text(plan: Plan) -> str:
    """One-line summary for the status bar."""
    stats = plan.stats
    return (
        f"扫描 {stats.total_scanned} · 命中 {stats.matched} · "
        f"将执行 {stats.will_execute} · 跳过 {stats.will_skip} · "
        f"拒绝 {stats.rejected} · 冲突 {stats.conflicts} · "
        f"plan_hash {plan.plan_hash[:12]}"
    )


def export(plan: Plan, directory: str) -> tuple[str, str]:
    """Write the two artifacts and return their paths as strings."""
    written = write_artifacts(plan, directory)
    return str(written.plan_json), str(written.report_md)
