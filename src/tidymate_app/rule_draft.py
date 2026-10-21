"""Form model -> YAML for the visual rule builder (stage 10).

Kept free of Qt so the translation can be unit tested. The output is ordinary YAML parsed
by the same strict loader as hand-written rules - the builder is a convenience, not a
second rule format.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from tidymate_core.planning import Plan, PlanRequest, build_plan
from tidymate_core.rules import load_rules_from_text
from tidymate_core.scanning import ScanConfig

#: field id -> (Chinese label, operators)
FIELD_LABELS: dict[str, str] = {
    "ext": "文件扩展名",
    "size": "文件大小",
    "mtime": "修改时间",
    "name": "文件名",
    "path": "文件路径",
    "parent": "父目录名",
}

OPERATORS: dict[str, tuple[tuple[str, str], ...]] = {
    "ext": (("包含", "in"), ("不包含", "not_in"), ("等于", "equals")),
    "size": (("大于", "gt"), ("小于", "lt"), ("等于", "eq"), ("范围", "range")),
    "mtime": (
        ("早于", "before"),
        ("晚于", "after"),
        ("在...之间", "between"),
        ("最近N天", "last"),
    ),
    "name": (
        ("包含", "contains"),
        ("开头是", "startswith"),
        ("结尾是", "endswith"),
        ("匹配正则", "regex"),
    ),
    "path": (("包含", "contains"), ("匹配正则", "regex")),
    "parent": (("等于", "equals"), ("包含", "contains")),
}

OPERATOR_LABELS: dict[str, str] = {
    "in": "包含",
    "not_in": "不包含",
    "equals": "等于",
    "gt": "大于",
    "lt": "小于",
    "eq": "等于",
    "range": "范围",
    "before": "早于",
    "after": "晚于",
    "between": "在...之间",
    "last": "最近N天",
    "contains": "包含",
    "startswith": "开头是",
    "endswith": "结尾是",
    "regex": "匹配正则",
}


@dataclass(slots=True)
class Condition:
    """One row of the condition table."""

    field: str = "ext"
    operator: str = "in"
    value: str = ""
    value2: str = ""


@dataclass(slots=True)
class RuleDraft:
    """Everything the form collects."""

    name: str = ""
    description: str = ""
    priority: int = 10
    enabled: bool = True
    conditions: list[Condition] = field(default_factory=list)
    op: str = "move"
    template: str = ""
    conflict: str = "rename"

    @property
    def rule_id(self) -> str:
        """Stable id derived from the display name."""
        digest = hashlib.sha256(self.name.strip().encode("utf-8")).hexdigest()[:8]
        return f"user-{digest}" if self.name.strip() else "user-rule"


def _quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _ext_list(raw: str) -> str:
    parts = [part.strip() for chunk in raw.split(",") for part in chunk.split()]
    items = []
    for part in parts:
        if not part:
            continue
        items.append(part if part.startswith(".") else f".{part}")
    return "[" + ", ".join(_quote(item.lower()) for item in items) + "]"


def _regex_for_name(operator: str, value: str) -> str:
    if operator == "regex":
        return value
    escaped = re.escape(value)
    if operator == "startswith":
        return f"^{escaped}"
    if operator == "endswith":
        return f"{escaped}$"
    return f".*{escaped}.*"


def condition_lines(condition: Condition) -> list[tuple[str, str]]:
    """Translate one form row into ``(yaml_key, yaml_value)`` pairs."""
    value = condition.value.strip()
    if not value:
        return []
    field = condition.field
    operator = condition.operator

    if field == "ext":
        if operator == "not_in":
            return [("ext_exclude", _ext_list(value))]
        return [("ext", _ext_list(value))]

    if field == "size":
        if operator == "range":
            upper = condition.value2.strip()
            pairs = [("size", _quote(f">={value}"))]
            if upper:
                pairs.append(("size_max", _quote(f"<={upper}")))
            return pairs
        comparison = {"gt": ">", "lt": "<", "eq": "=="}[operator]
        return [("size", _quote(f"{comparison}{value}"))]

    if field == "mtime":
        if operator == "last":
            days = value.rstrip("d").strip() or "30"
            return [("mtime", _quote(f"last-{days}d"))]
        if operator == "between":
            pairs = [("mtime", _quote(f">={value}"))]
            if condition.value2.strip():
                pairs.append(("mtime_before", _quote(f"<={condition.value2.strip()}")))
            return pairs
        comparison = {"before": "<", "after": ">="}[operator]
        return [("mtime", _quote(f"{comparison}{value}"))]

    if field == "name":
        return [("name_regex", _quote(_regex_for_name(operator, value)))]
    if field == "path":
        if operator == "regex":
            return [("path_regex", _quote(value))]
        return [("path_contains", _quote(value))]
    if field == "parent":
        if operator == "contains":
            return [("parent_contains", _quote(value))]
        return [("parent", _quote(value))]
    return []


def draft_to_yaml(draft: RuleDraft) -> str:
    """Render the draft as a complete rule file, metadata comments included."""
    lines = [
        f"# name: {draft.name.strip() or '未命名规则'}",
        f"# description: {draft.description.strip()}",
        "# author: TidyMate",
        "# version: 1.0",
        "# tags: []",
        "# icon: file",
        "",
        "rules:",
        f"  - id: {draft.rule_id}",
        f"    priority: {draft.priority}",
        f"    enabled: {'true' if draft.enabled else 'false'}",
        "    when:",
    ]
    pairs: list[tuple[str, str]] = []
    for condition in draft.conditions:
        pairs.extend(condition_lines(condition))
    if not pairs:
        # The loader rejects an empty `when`; emit a harmless always-false condition so the
        # preview shows "no match" instead of a crash while the user is still typing.
        pairs = [("name_regex", _quote("(?!)"))]
    for key, value in pairs:
        lines.append(f"      {key}: {value}")

    lines.append("    action:")
    lines.append(f"      op: {draft.op}")
    if draft.op == "trash":
        lines.append("      conflict: skip")
    else:
        template = draft.template.strip() or "{name}"
        lines.append(f"      template: {_quote(template)}")
        lines.append(f"      conflict: {draft.conflict}")
    lines.append("")
    return "\n".join(lines)


def build_preview(draft: RuleDraft, root: str, out_root: str) -> Plan:
    """Load the generated YAML and plan against *root* (read-only)."""
    ruleset = load_rules_from_text(draft_to_yaml(draft))
    request = PlanRequest(
        scan=ScanConfig(roots=(root,)),
        rules=ruleset,
        output_root=out_root,
    )
    return build_plan(request)


__all__ = [
    "FIELD_LABELS",
    "OPERATORS",
    "OPERATOR_LABELS",
    "Condition",
    "RuleDraft",
    "build_preview",
    "condition_lines",
    "draft_to_yaml",
]
