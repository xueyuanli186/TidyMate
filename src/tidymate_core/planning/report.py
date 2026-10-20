"""Dry-run report renderers: terminal table, JSON and Markdown.

All three views are derived from the same :class:`~tidymate_core.planning.models.Plan`,
so the numbers cannot drift between formats. A test asserts they agree with the plan.

Conflict highlighting is not cosmetic: every entry with a conflict is rendered with a
marker in the table, a ``⚠️`` row in Markdown, and its own section, because "it's in the
report somewhere" is how conflicts get missed.
"""

from __future__ import annotations

import json

from tidymate_core.planning.models import ChangeStatus, ConflictType, Plan, PlannedChange
from tidymate_core.planning.planner import change_to_dict, stats_to_dict

_CONFLICT_LABEL: dict[ConflictType, str] = {
    ConflictType.NONE: "-",
    ConflictType.EXISTS_ON_DISK: "exists-on-disk",
    ConflictType.INTRA_BATCH: "intra-batch",
    ConflictType.NEEDS_REVIEW: "needs-review",
}

_STATUS_LABEL: dict[ChangeStatus, str] = {
    ChangeStatus.EXECUTE: "execute",
    ChangeStatus.SKIP: "skip",
    ChangeStatus.REJECT: "reject",
}


def plan_to_dict(plan: Plan) -> dict[str, object]:
    """Return the JSON-ready representation of *plan* (deterministic key order)."""
    return {
        "schema": 1,
        "batch_id": plan.batch_id,
        # Local time with an explicit offset: users read this field, and a bare UTC stamp
        # next to a local-looking batch_id would be confusing.
        "created_at": plan.created_at.astimezone().isoformat(),
        "output_root": plan.output_root,
        "rules_source": plan.rules_source,
        "plan_hash": plan.plan_hash,
        "stats": stats_to_dict(plan.stats),
        "warnings": list(plan.warnings),
        "changes": [change_to_dict(change) for change in plan.changes],
    }


def plan_to_json(plan: Plan) -> str:
    """Serialise *plan* for ``plan.json``."""
    return json.dumps(plan_to_dict(plan), indent=2, ensure_ascii=False)


def _shorten(text: str, width: int) -> str:
    if width <= 3:
        return text[:width]
    if len(text) <= width:
        return text
    head = (width - 3) // 2
    tail = width - 3 - head
    return f"{text[:head]}...{text[-tail:]}"


def _destination(change: PlannedChange) -> str:
    if change.dst is not None:
        return change.dst
    if change.op == "trash":
        return "<recycle bin>"
    return "-"


def _table_row(change: PlannedChange, *, path_width: int) -> str:
    marker = "!" if change.conflict is not ConflictType.NONE else " "
    return (
        f"{change.seq:>4} {marker} {_STATUS_LABEL[change.status]:<7} "
        f"{(change.op or '-'):<6} {(change.rule_id or '-'):<16} "
        f"{_CONFLICT_LABEL[change.conflict]:<14} "
        f"{_shorten(change.src, path_width):<{path_width}} -> "
        f"{_shorten(_destination(change), path_width)}"
    )


def render_table(plan: Plan, *, limit: int = 40, path_width: int = 34) -> str:
    """Render a terminal table. Long plans are truncated, with the remainder counted."""
    header = (
        f"{'seq':>4}   {'status':<7} {'op':<6} {'rule':<16} {'conflict':<14} "
        f"{'source':<{path_width}} -> destination"
    )
    lines = [
        f"TidyMate dry-run  batch={plan.batch_id}  hash={plan.plan_hash[:16]}",
        f"scanned={plan.stats.total_scanned} matched={plan.stats.matched} "
        f"execute={plan.stats.will_execute} skip={plan.stats.will_skip} "
        f"reject={plan.stats.rejected} conflicts={plan.stats.conflicts}",
        "",
        header,
        "-" * min(len(header), 200),
    ]
    for change in plan.changes[:limit]:
        lines.append(_table_row(change, path_width=path_width))
    remaining = len(plan.changes) - limit
    if remaining > 0:
        lines.append(
            f"... {remaining} more change(s) not shown; export plan.json for the full list",
        )
    return "\n".join(lines)


def _conflict_section(plan: Plan, conflict: ConflictType, title: str) -> list[str]:
    entries = [change for change in plan.changes if change.conflict is conflict]
    lines = [f"### {title} ({len(entries)})", ""]
    if not entries:
        return [*lines, "_none_", ""]
    lines.extend(
        [
            "| seq | source | destination | rule | notes |",
            "| --- | --- | --- | --- | --- |",
        ],
    )
    for change in entries:
        notes = "<br>".join(change.notes) or "-"
        lines.append(
            f"| {change.seq} | `{change.src}` | `{_destination(change)}` | "
            f"{change.rule_id or '-'} | {notes} |",
        )
    lines.append("")
    return lines


def render_markdown(plan: Plan) -> str:
    """Render the human-readable ``report.md``."""
    stats = plan.stats
    lines: list[str] = [
        "# TidyMate Dry-run 报告",
        "",
        "> **本次没有修改任何文件。** 这是一份预览。",
        "",
        f"- 批次：`{plan.batch_id}`",
        f"- 生成时间：{plan.created_at.astimezone().isoformat()}",
        f"- 输出根目录：`{plan.output_root}`",
        f"- 规则文件：`{plan.rules_source}`",
        f"- plan_hash：`{plan.plan_hash}`",
        "",
        "## 摘要",
        "",
        "| 指标 | 数值 |",
        "| --- | --- |",
        f"| 总扫描数 | {stats.total_scanned} |",
        f"| 命中规则数 | {stats.matched} |",
        f"| 将执行数 | {stats.will_execute} |",
        f"| 将跳过数 | {stats.will_skip} |",
        f"| 拒绝数 | {stats.rejected} |",
        f"| 冲突总数 | {stats.conflicts} |",
        f"| ├ 与磁盘已存在冲突 | {stats.conflicts_exists} |",
        f"| ├ 批内同名冲突 | {stats.conflicts_intra} |",
        f"| └ 需人工确认 | {stats.conflicts_review} |",
        f"| 预计释放空间（trash） | {stats.bytes_freed} 字节 |",
        f"| 预计新增占用（copy） | {stats.bytes_added} 字节 |",
        "",
        "`move` 与 `rename` 不改变总占用空间，因此不计入释放/占用。",
        "",
        "## 冲突（必须人工处理）",
        "",
    ]
    lines.extend(
        _conflict_section(
            plan,
            ConflictType.EXISTS_ON_DISK,
            "⚠️ 与磁盘上已存在的文件冲突",
        ),
    )
    lines.extend(
        _conflict_section(
            plan,
            ConflictType.INTRA_BATCH,
            "⚠️ 批内自相冲突（多条变更目标相同）",
        ),
    )
    lines.extend(
        _conflict_section(
            plan,
            ConflictType.NEEDS_REVIEW,
            "⚠️ 需人工确认（conflict: ask）",
        ),
    )

    rejected = plan.rejected()
    lines.extend([f"## 拒绝项 ({len(rejected)})", ""])
    if rejected:
        lines.extend(["| seq | source | 原因 | 说明 |", "| --- | --- | --- | --- |"])
        for change in rejected:
            reason = change.reason.value if change.reason is not None else "-"
            notes = "<br>".join(change.notes) or "-"
            lines.append(f"| {change.seq} | `{change.src}` | **{reason}** | {notes} |")
    else:
        lines.append("_none_")
    lines.append("")

    executable = plan.executable()
    lines.extend([f"## 将执行 ({len(executable)})", ""])
    if executable:
        lines.extend(
            [
                "| seq | source | destination | op | rule | flags |",
                "| --- | --- | --- | --- | --- | --- |",
            ],
        )
        for change in executable:
            flags = ", ".join(change.flags) or "-"
            lines.append(
                f"| {change.seq} | `{change.src}` | `{_destination(change)}` | "
                f"{change.op or '-'} | {change.rule_id or '-'} | {flags} |",
            )
    else:
        lines.append("_none_")
    lines.append("")

    lines.extend(["## 按规则分组", "", "| 规则 | 命中数 |", "| --- | --- |"])
    for rule_id, count in sorted(stats.by_rule.items()):
        lines.append(f"| {rule_id} | {count} |")
    lines.append("")

    if plan.warnings:
        lines.extend(["## 警告", ""])
        lines.extend(f"- {warning}" for warning in plan.warnings)
        lines.append("")

    lines.extend(
        [
            "---",
            "",
            "执行按钮在阶段 5 才开放。本报告由 `python scripts/` 之外的只读管线生成，",
            "`plan.json` 中的 `plan_hash` 可用于校验两次 dry-run 的输入是否一致。",
            "",
        ],
    )
    return "\n".join(lines)


def stats_lines(plan: Plan) -> list[str]:
    """Short key=value summary used by the CLI and the GUI status bar."""
    stats = plan.stats
    return [
        f"scanned={stats.total_scanned}",
        f"matched={stats.matched}",
        f"execute={stats.will_execute}",
        f"skip={stats.will_skip}",
        f"reject={stats.rejected}",
        f"conflicts={stats.conflicts}",
        f"bytes_freed={stats.bytes_freed}",
        f"bytes_added={stats.bytes_added}",
    ]
