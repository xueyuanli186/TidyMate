"""Rule model: what a rule *is*, independent of how it is loaded.

The model is frozen and side-effect free. Loading (validation, line numbers) lives in
:mod:`tidymate_core.rules.loader`; matching lives in :mod:`tidymate_core.rules.matcher`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from tidymate_core.rules.regex_safe import SafeRegex
from tidymate_core.rules.size_expr import SizeCondition
from tidymate_core.rules.template import TemplateSpec
from tidymate_core.rules.time_expr import TimeCondition


class RuleOp(StrEnum):
    """What a matched rule would do. Nothing here executes anything yet."""

    MOVE = "move"
    RENAME = "rename"
    COPY = "copy"
    TRASH = "trash"


class ConflictPolicy(StrEnum):
    """What to do when the destination already exists. Never "overwrite"."""

    SKIP = "skip"
    RENAME = "rename"
    ASK = "ask"


@dataclass(frozen=True, slots=True)
class When:
    """All conditions of a rule. Multiple conditions are AND-ed."""

    path_glob: str | None = None
    path_glob_regex: SafeRegex | None = None
    path_regex: SafeRegex | None = None
    #: Case-insensitive substring of the full path (form-friendly alternative to a regex).
    path_contains: str | None = None
    #: Exact name of the file's immediate parent directory (case-insensitive).
    parent: str | None = None
    #: Case-insensitive substring of the immediate parent directory name.
    parent_contains: str | None = None
    extensions: frozenset[str] = frozenset()
    #: Extensions that must NOT match (the builder's "not contains").
    excluded_extensions: frozenset[str] = frozenset()
    size: SizeCondition | None = None
    #: Inclusive upper bound used by the visual builder's "range" operator.
    size_max: SizeCondition | None = None
    mtime: TimeCondition | None = None
    #: Upper bound used by the visual builder's "between" operator.
    mtime_before: TimeCondition | None = None
    name_regex: SafeRegex | None = None

    def __post_init__(self) -> None:
        if not self.has_any_condition():
            raise ValueError("a When needs at least one condition")

    def has_any_condition(self) -> bool:
        """True when at least one condition is set (an empty rule would match everything)."""
        return any(
            (
                self.path_glob is not None,
                self.path_regex is not None,
                self.path_contains is not None,
                self.parent is not None,
                self.parent_contains is not None,
                bool(self.extensions),
                bool(self.excluded_extensions),
                self.size is not None,
                self.size_max is not None,
                self.mtime is not None,
                self.mtime_before is not None,
                self.name_regex is not None,
            ),
        )


@dataclass(frozen=True, slots=True)
class Action:
    """The declared effect of a rule (not executed in the read-only stages)."""

    op: RuleOp
    template: str
    template_spec: TemplateSpec | None
    conflict: ConflictPolicy


@dataclass(frozen=True, slots=True)
class Rule:
    """One validated rule."""

    id: str
    enabled: bool
    priority: int
    when: When
    action: Action
    line: int | None = None

    @property
    def sort_key(self) -> tuple[int, int]:
        """Priority ascending; ``line`` keeps file order stable within a priority."""
        return (self.priority, self.line or 0)
