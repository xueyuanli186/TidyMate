"""YAML rule loading with strict, line-numbered validation.

The contract is all-or-nothing: a single invalid rule rejects the whole file. "Skip the
bad rule and continue" is explicitly forbidden, because a partially applied rule set is a
silently different organiser than the one the user wrote.

Every problem is collected before raising, so one run of ``tidymate`` reports all typos
instead of one per attempt.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from tidymate_core.rules.engine import RuleSet
from tidymate_core.rules.errors import RuleError, RuleLoadError
from tidymate_core.rules.matcher import glob_to_regex
from tidymate_core.rules.models import Action, ConflictPolicy, Rule, RuleOp, When
from tidymate_core.rules.regex_safe import (
    DEFAULT_TIMEOUT_MS,
    RegexCompileError,
    SafeRegex,
)
from tidymate_core.rules.size_expr import parse_size_expression
from tidymate_core.rules.template import TemplateError, TemplateSpec, parse_template
from tidymate_core.rules.time_expr import parse_time_expression

_LINE_KEY = "__line__"
_LINES_KEY = "__lines__"
_META_KEYS = frozenset({_LINE_KEY, _LINES_KEY})

_ALLOWED_TOP = frozenset({"rules", "first_match_only", "firstMatchOnly"})
_ALLOWED_RULE = frozenset({"id", "enabled", "priority", "when", "action"})
_ALLOWED_WHEN = frozenset(
    {"path_glob", "path_regex", "ext", "size", "mtime", "name_regex"},
)
_ALLOWED_ACTION = frozenset({"op", "template", "conflict"})


class _LineLoader(yaml.SafeLoader):  # type: ignore[misc]
    """SafeLoader that records line numbers and refuses duplicate mapping keys."""

    def construct_mapping(self, node: Any, deep: bool = False) -> Any:
        field_lines: dict[str, int] = {}
        if isinstance(node, yaml.MappingNode):
            seen: set[Any] = set()
            for key_node, _value_node in node.value:
                key = self.construct_object(key_node, deep=True)
                if key in seen:
                    raise yaml.constructor.ConstructorError(
                        "while constructing a mapping",
                        node.start_mark,
                        f"found duplicate key {key!r}",
                        key_node.start_mark,
                    )
                seen.add(key)
                # Per-key line numbers let a validation error point at `size:` rather
                # than at the enclosing `when:` block.
                field_lines[str(key)] = key_node.start_mark.line + 1
        mapping = super().construct_mapping(node, deep=deep)
        if isinstance(node, yaml.MappingNode):
            mapping[_LINE_KEY] = node.start_mark.line + 1
            mapping[_LINES_KEY] = field_lines
        return mapping


# PyYAML resolves booleans with YAML 1.1 rules, where `off`, `no`, `on` and `yes` become
# booleans. That silently turns `id: off` into `False` and produces a confusing error.
# Restrict bool resolution to true/false (YAML 1.2 behaviour) so every other word stays a
# string and the error message describes what the user actually wrote.
_BOOL_TAG = "tag:yaml.org,2002:bool"
_LineLoader.yaml_implicit_resolvers = {
    first: [(tag, regexp) for tag, regexp in resolvers if tag != _BOOL_TAG]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_LineLoader.add_implicit_resolver(
    _BOOL_TAG,
    re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"),
)


def _line_of(mapping: dict[str, Any]) -> int | None:
    value = mapping.get(_LINE_KEY)
    return value if isinstance(value, int) else None


def _field_line(mapping: dict[str, Any], key: str, fallback: int | None) -> int | None:
    """Line of a specific key inside *mapping*, falling back to the mapping's own line."""
    lines = mapping.get(_LINES_KEY)
    if isinstance(lines, dict):
        value = lines.get(key)
        if isinstance(value, int):
            return value
    return fallback


def _fail(errors: list[RuleError], message: str, *, line: int | None, field: str) -> None:
    errors.append(RuleError(message=message, line=line, field=field))


def _bool_field(
    raw: dict[str, Any],
    key: str,
    default: bool,
    prefix: str,
    errors: list[RuleError],
) -> bool:
    if key not in raw:
        return default
    value = raw[key]
    if not isinstance(value, bool):
        _fail(errors, f"{key} must be true or false", line=_line_of(raw), field=f"{prefix}.{key}")
        return default
    return value


def _int_field(
    raw: dict[str, Any],
    key: str,
    default: int,
    prefix: str,
    errors: list[RuleError],
) -> int:
    if key not in raw:
        return default
    value = raw[key]
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(errors, f"{key} must be an integer", line=_line_of(raw), field=f"{prefix}.{key}")
        return default
    return value


def _str_field(
    raw: dict[str, Any],
    key: str,
    prefix: str,
    errors: list[RuleError],
) -> str | None:
    if key not in raw:
        return None
    value = raw[key]
    if not isinstance(value, str) or not value.strip():
        _fail(
            errors,
            f"{key} must be a non-empty string",
            line=_line_of(raw),
            field=f"{prefix}.{key}",
        )
        return None
    return value


def _parse_extensions(
    raw: dict[str, Any],
    prefix: str,
    errors: list[RuleError],
    fallback_line: int | None,
) -> frozenset[str]:
    if "ext" not in raw:
        return frozenset()
    value = raw["ext"]
    line = _field_line(raw, "ext", fallback_line)
    if not isinstance(value, list) or not value:
        _fail(errors, "ext must be a non-empty list", line=line, field=f"{prefix}.ext")
        return frozenset()
    result: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item.startswith(".") or len(item) < 2:
            _fail(
                errors,
                f"ext entry {item!r} must start with '.' (e.g. '.jpg')",
                line=line,
                field=f"{prefix}.ext",
            )
            continue
        result.add(item.lower())
    return frozenset(result)


def _parse_when(
    raw: Any,
    prefix: str,
    errors: list[RuleError],
    warnings: list[str],
    timeout_ms: int,
) -> When | None:
    if not isinstance(raw, dict):
        _fail(errors, "when must be a mapping", line=None, field=f"{prefix}.when")
        return None

    line = _line_of(raw)
    before = len(errors)

    for key in sorted(set(raw) - _ALLOWED_WHEN - _META_KEYS):
        _fail(errors, f"unknown condition {key!r}", line=line, field=f"{prefix}.when")

    used = set(raw) - _META_KEYS
    if not used & _ALLOWED_WHEN:
        _fail(
            errors,
            "when must contain at least one condition (an empty rule would match everything)",
            line=line,
            field=f"{prefix}.when",
        )

    path_glob = _str_field(raw, "path_glob", f"{prefix}.when", errors)
    path_glob_regex: SafeRegex | None = None
    if path_glob is not None:
        try:
            path_glob_regex = SafeRegex.compile(
                glob_to_regex(path_glob),
                timeout_ms=timeout_ms,
                flags=re.IGNORECASE,
                on_timeout=warnings.append,
            )
        except RegexCompileError as exc:
            _fail(
                errors,
                str(exc),
                line=_field_line(raw, "path_glob", line),
                field=f"{prefix}.when.path_glob",
            )

    path_regex: SafeRegex | None = None
    raw_path_regex = _str_field(raw, "path_regex", f"{prefix}.when", errors)
    if raw_path_regex is not None:
        path_regex = _compile_regex(
            raw_path_regex,
            f"{prefix}.when.path_regex",
            _field_line(raw, "path_regex", line),
            errors,
            warnings,
            timeout_ms,
        )

    name_regex: SafeRegex | None = None
    raw_name_regex = _str_field(raw, "name_regex", f"{prefix}.when", errors)
    if raw_name_regex is not None:
        name_regex = _compile_regex(
            raw_name_regex,
            f"{prefix}.when.name_regex",
            _field_line(raw, "name_regex", line),
            errors,
            warnings,
            timeout_ms,
        )

    extensions = _parse_extensions(raw, f"{prefix}.when", errors, line)

    size = None
    size_line = _field_line(raw, "size", line)
    if "size" in raw:
        raw_size = raw["size"]
        if not isinstance(raw_size, str):
            _fail(errors, "size must be a string", line=size_line, field=f"{prefix}.when.size")
        else:
            try:
                size = parse_size_expression(raw_size)
            except ValueError as exc:
                _fail(errors, str(exc), line=size_line, field=f"{prefix}.when.size")

    mtime = None
    mtime_line = _field_line(raw, "mtime", line)
    if "mtime" in raw:
        raw_mtime = raw["mtime"]
        if not isinstance(raw_mtime, str):
            _fail(errors, "mtime must be a string", line=mtime_line, field=f"{prefix}.when.mtime")
        else:
            try:
                mtime = parse_time_expression(raw_mtime)
            except ValueError as exc:
                _fail(errors, str(exc), line=mtime_line, field=f"{prefix}.when.mtime")

    if len(errors) > before:
        return None

    return When(
        path_glob=path_glob,
        path_glob_regex=path_glob_regex,
        path_regex=path_regex,
        extensions=extensions,
        size=size,
        mtime=mtime,
        name_regex=name_regex,
    )


def _compile_regex(
    pattern: str,
    field: str,
    line: int | None,
    errors: list[RuleError],
    warnings: list[str],
    timeout_ms: int,
) -> SafeRegex | None:
    try:
        return SafeRegex.compile(pattern, timeout_ms=timeout_ms, on_timeout=warnings.append)
    except RegexCompileError as exc:
        _fail(errors, str(exc), line=line, field=field)
        return None


def _parse_action(
    raw: Any,
    prefix: str,
    errors: list[RuleError],
) -> Action | None:
    if not isinstance(raw, dict):
        _fail(errors, "action must be a mapping", line=None, field=f"{prefix}.action")
        return None

    line = _line_of(raw)
    before = len(errors)

    for key in sorted(set(raw) - _ALLOWED_ACTION - _META_KEYS):
        _fail(errors, f"unknown action key {key!r}", line=line, field=f"{prefix}.action")

    op: RuleOp | None = None
    raw_op = raw.get("op")
    if not isinstance(raw_op, str):
        _fail(errors, "op must be one of move/rename/copy/trash", line=line, field=f"{prefix}.op")
    else:
        try:
            op = RuleOp(raw_op.lower())
        except ValueError:
            _fail(
                errors,
                f"op {raw_op!r} is not one of move/rename/copy/trash",
                line=line,
                field=f"{prefix}.op",
            )

    conflict = ConflictPolicy.SKIP
    raw_conflict = raw.get("conflict", "skip")
    if not isinstance(raw_conflict, str):
        _fail(
            errors,
            "conflict must be one of skip/rename/ask",
            line=line,
            field=f"{prefix}.conflict",
        )
    else:
        try:
            conflict = ConflictPolicy(raw_conflict.lower())
        except ValueError:
            _fail(
                errors,
                f"conflict {raw_conflict!r} is not one of skip/rename/ask",
                line=line,
                field=f"{prefix}.conflict",
            )

    template = ""
    template_spec = None
    raw_template = raw.get("template")
    if op is RuleOp.TRASH:
        # Deleting does not need a destination; if one is given it must still be valid.
        if raw_template is not None:
            template, template_spec = _parse_template(
                raw_template,
                f"{prefix}.template",
                line,
                errors,
            )
    else:
        if not isinstance(raw_template, str) or not raw_template.strip():
            _fail(
                errors,
                f"template is required for op={op.value if op else '<op>'}",
                line=line,
                field=f"{prefix}.template",
            )
        else:
            template, template_spec = _parse_template(
                raw_template,
                f"{prefix}.template",
                line,
                errors,
            )

    if len(errors) > before or op is None:
        return None
    return Action(op=op, template=template, template_spec=template_spec, conflict=conflict)


def _parse_template(
    raw: Any,
    field: str,
    line: int | None,
    errors: list[RuleError],
) -> tuple[str, TemplateSpec | None]:
    if not isinstance(raw, str):
        _fail(errors, "template must be a string", line=line, field=field)
        return "", None
    try:
        spec = parse_template(raw)
    except TemplateError as exc:
        _fail(errors, str(exc), line=line, field=field)
        return "", None
    return spec.raw, spec


def _parse_rule(
    raw: Any,
    index: int,
    errors: list[RuleError],
    warnings: list[str],
    timeout_ms: int,
) -> Rule | None:
    prefix = f"rules[{index}]"
    if not isinstance(raw, dict):
        _fail(errors, "rule must be a mapping", line=None, field=prefix)
        return None

    line = _line_of(raw)
    before = len(errors)

    for key in sorted(set(raw) - _ALLOWED_RULE - _META_KEYS):
        _fail(errors, f"unknown rule key {key!r}", line=line, field=prefix)

    rule_id = raw.get("id")
    if not isinstance(rule_id, str) or not rule_id.strip():
        _fail(errors, "id must be a non-empty string", line=line, field=f"{prefix}.id")
        rule_id = ""

    enabled = _bool_field(raw, "enabled", True, prefix, errors)
    priority = _int_field(raw, "priority", 0, prefix, errors)
    when = _parse_when(raw.get("when"), prefix, errors, warnings, timeout_ms)
    action = _parse_action(raw.get("action"), prefix, errors)

    if len(errors) > before or when is None or action is None or not rule_id:
        return None

    return Rule(
        id=rule_id,
        enabled=enabled,
        priority=priority,
        when=when,
        action=action,
        line=line,
    )


def load_rules_from_text(
    text: str,
    *,
    source: str = "<rules>",
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> RuleSet:
    """Parse and validate a YAML rule document.

    Raises:
        RuleLoadError: if *any* part of the document is invalid. Nothing is returned.
    """
    try:
        document = yaml.load(text, Loader=_LineLoader)  # noqa: S506 - _LineLoader is a SafeLoader
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = mark.line + 1 if mark is not None else None
        raise RuleLoadError([RuleError(message=str(exc), line=line)], source=source) from exc

    errors: list[RuleError] = []
    warnings: list[str] = []

    if not isinstance(document, dict):
        raise RuleLoadError(
            [RuleError(message="top level must be a mapping with a 'rules:' key", line=1)],
            source=source,
        )

    top_line = _line_of(document)
    for key in sorted(set(document) - _ALLOWED_TOP - _META_KEYS):
        _fail(errors, f"unknown top-level key {key!r}", line=top_line, field=str(key))

    first_match_only = True
    has_snake = "first_match_only" in document
    has_camel = "firstMatchOnly" in document
    if has_snake and has_camel:
        _fail(
            errors,
            "use only one of 'first_match_only' and 'firstMatchOnly'",
            line=top_line,
            field="first_match_only",
        )
    elif has_snake or has_camel:
        value = document["first_match_only" if has_snake else "firstMatchOnly"]
        if not isinstance(value, bool):
            _fail(
                errors,
                "first_match_only must be true or false",
                line=top_line,
                field="first_match_only",
            )
        else:
            first_match_only = value

    raw_rules = document.get("rules")
    if not isinstance(raw_rules, list):
        _fail(errors, "'rules' must be a list", line=top_line, field="rules")
        raw_rules = []

    parsed: list[Rule] = []
    for index, raw_rule in enumerate(raw_rules):
        rule = _parse_rule(raw_rule, index, errors, warnings, timeout_ms)
        if rule is not None:
            parsed.append(rule)

    seen: dict[str, int | None] = {}
    for rule in parsed:
        if rule.id in seen:
            _fail(
                errors,
                f"duplicate rule id {rule.id!r} (first defined at line {seen[rule.id]})",
                line=rule.line,
                field="rules",
            )
        else:
            seen[rule.id] = rule.line

    if errors:
        raise RuleLoadError(errors, source=source)

    ordered = tuple(sorted(parsed, key=lambda rule: rule.sort_key))
    return RuleSet(
        rules=ordered,
        first_match_only=first_match_only,
        source=source,
        warnings=warnings,
    )


def load_rules(
    path: str | Path,
    *,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> RuleSet:
    """Read and validate a rule file from disk (read-only)."""
    target = Path(path)
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuleLoadError(
            [RuleError(message=f"cannot read rule file: {exc}")],
            source=str(target),
        ) from exc
    return load_rules_from_text(text, source=str(target), timeout_ms=timeout_ms)
