"""Error reports (M9): ``errors-<batch>.md`` / ``.json`` after apply and undo.

Two rules the product owner insisted on:

* ``failed`` and ``skipped`` are never merged, and neither is ever counted as ``ok``;
* any ``error_kind=unknown`` puts a loud banner at the top of the report.

Numbers come from :meth:`Journal.agg_stats` (SQL aggregation), never from the objects that
happened to be in memory.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from tidymate_core.journal import Journal

_KIND_ADVICE: dict[str, str] = {
    "in_use": "关闭占用该文件的程序（编辑器、同步客户端）后重试。",
    "permission": "检查文件/目录权限，或以有权限的账户重试；不要手动改只读位掩盖问题。",
    "permission_denied": "检查文件/目录权限，或以有权限的账户重试。",
    "modified_since": "文件在 apply 之后被修改过；确认新内容后再决定是否手动移回。",
    "missing": "目标位置已没有该文件；先确认它被移动/删除到了哪里，再人工处理。",
    "src_occupied": "原位置已有别的文件；先处理占用者，工具不会覆盖它。",
    "recycle_gone": "回收站里已没有该项；请从备份恢复，或使用文件恢复工具。",
    "blacklist": "命中受保护目录（不应发生，门禁应提前拦截）；请报告为 bug。",
    "ancestor": "源与目标重叠（不应发生）；请报告为 bug。",
    "diskfull": "目标磁盘空间不足；清理后重试。",
    "disk_full": "目标磁盘空间不足；清理后重试。",
    "unknown": "未分类错误；请人工复核并在 Issue 中附上本报告。",
}

_IMPACT_ON_UNDO: dict[str, str] = {
    "ok": "可撤销",
    "failed": "无需撤销（未落盘）",
    "skipped": "无需撤销（未落盘）",
    "undone": "已撤销",
    "undo_failed": "**未复原**，需人工处理",
}


@dataclass(frozen=True, slots=True)
class ReportPaths:
    """Where the two report files were written."""

    markdown: Path
    json: Path


def _rows(journal: Journal, batch_id: str) -> list[dict[str, object]]:
    return [
        row
        for row in journal.operations(batch_id)
        if row["state"] in {"failed", "skipped", "undo_failed"} or row.get("error")
    ]


def _group(rows: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        kind = str(row.get("error_kind") or "unknown")
        grouped.setdefault(kind, []).append(row)
    return dict(sorted(grouped.items()))


def render_markdown(journal: Journal, batch_id: str) -> str:
    """Render the human-readable error report."""
    batch = journal.batch_row(batch_id) or {}
    stats = journal.agg_stats(batch_id)
    rows = _rows(journal, batch_id)
    grouped = _group(rows)
    lines = [
        f"# TidyMate 错误报告：{batch_id}",
        "",
        f"- 模式：{batch.get('mode', '-')}",
        f"- 状态：{batch.get('status', '-')}",
        f"- 生成时间：{batch.get('finished_at') or '-'}",
        f"- 规则文件：{batch.get('rules_file') or '-'}",
        "",
    ]
    if "unknown" in grouped:
        lines.extend(
            [
                "> ⚠️ **存在未分类错误（error_kind=unknown），请人工复核。**",
                "",
            ],
        )
    lines.extend(
        [
            "## 摘要（来自 SQL 聚合）",
            "",
            "| 指标 | 数值 |",
            "| --- | --- |",
            f"| total | {stats['total']} |",
            f"| ok | {stats['ok']} |",
            f"| failed | {stats['failed']} |",
            f"| skipped | {stats['skipped']} |",
            f"| undo_total | {stats['undo_total']} |",
            f"| undo_ok | {stats['undo_ok']} |",
            f"| undo_failed | {stats['undo_failed']} |",
            "",
            "> failed 与 skipped 分开统计，且都不计入 ok。",
            "",
        ],
    )
    if not grouped:
        lines.extend(["_没有失败或跳过项。_", ""])
        return "\n".join(lines)

    for kind, items in grouped.items():
        advice = _KIND_ADVICE.get(kind, "人工复核。")
        lines.extend([f"## {kind} ({len(items)})", "", f"建议动作：{advice}", ""])
        lines.extend(
            [
                "| seq | op | src | dst | 原因 | 对撤销的影响 |",
                "| --- | --- | --- | --- | --- | --- |",
            ],
        )
        for row in items:
            state = str(row.get("state"))
            lines.append(
                f"| {row.get('seq')} | {row.get('op')} | `{row.get('src')}` | "
                f"`{row.get('final_dst') or row.get('dst') or '-'}` | "
                f"{row.get('error') or '-'} | {_IMPACT_ON_UNDO.get(state, '-')} |",
            )
        lines.append("")
    return "\n".join(lines)


def render_json(journal: Journal, batch_id: str) -> str:
    """Render the machine-readable error report."""
    batch = journal.batch_row(batch_id) or {}
    stats = journal.agg_stats(batch_id)
    grouped = _group(_rows(journal, batch_id))
    payload = {
        "batch_id": batch_id,
        "mode": batch.get("mode"),
        "status": batch.get("status"),
        "summary": stats,
        "unknown_present": "unknown" in grouped,
        "groups": {
            kind: [
                {
                    "seq": row.get("seq"),
                    "op": row.get("op"),
                    "state": row.get("state"),
                    "src": row.get("src"),
                    "dst": row.get("dst"),
                    "final_dst": row.get("final_dst"),
                    "error": row.get("error"),
                    "error_kind": row.get("error_kind"),
                    "impact": _IMPACT_ON_UNDO.get(str(row.get("state")), "-"),
                }
                for row in items
            ]
            for kind, items in grouped.items()
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def write_reports(journal: Journal, batch_id: str, out_dir: str | Path) -> ReportPaths:
    """Write both report files and return their paths."""
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    markdown = directory / f"errors-{batch_id}.md"
    payload = directory / f"errors-{batch_id}.json"
    markdown.write_text(render_markdown(journal, batch_id), encoding="utf-8")
    payload.write_text(render_json(journal, batch_id), encoding="utf-8")
    return ReportPaths(markdown=markdown, json=payload)
