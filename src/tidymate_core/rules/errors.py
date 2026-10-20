"""Structured rule-loading errors.

A rule file is rejected as a whole. There is no "load the good rules, skip the bad ones"
mode: a half-applied rule set is exactly the kind of silent divergence that makes an
organiser dangerous. So every problem is collected, reported with its YAML line number,
and nothing is returned.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RuleError:
    """One validation failure, pointing at a line and a field."""

    message: str
    line: int | None = None
    field: str = ""

    def render(self) -> str:
        """Human readable single line, e.g. ``line 12, rules[0].when.size: ...``."""
        parts: list[str] = []
        parts.append(f"line {self.line}" if self.line is not None else "file")
        if self.field:
            parts.append(self.field)
        return f"{', '.join(parts)}: {self.message}"


class RuleLoadError(Exception):
    """Raised when a rule file cannot be loaded at all."""

    def __init__(self, errors: Sequence[RuleError], *, source: str = "<rules>") -> None:
        self.errors: tuple[RuleError, ...] = tuple(errors)
        self.source: str = source
        super().__init__(self._summary())

    def _summary(self) -> str:
        lines = [f"{self.source}: {len(self.errors)} rule error(s), nothing was loaded"]
        lines.extend(f"  {error.render()}" for error in self.errors)
        return "\n".join(lines)

    def rendered(self) -> str:
        """Return the full multi-line report (the exception message already is one)."""
        return str(self)
