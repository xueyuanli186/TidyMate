"""Regular expressions with a hard time budget.

Python's :mod:`re` has no timeout, so a rule author (or a malicious rules file shared in an
issue) could freeze the organiser with one catastrophic pattern. This module uses the
:mod:`regex` package, which supports a real timeout, and adds two protections:

1. **Compile-time pattern screening** - nested quantifiers such as ``(a+)+`` are rejected
   outright. They have no legitimate use in a filename rule.
2. **Runtime timeout** - a match that exceeds the budget (200 ms by default) is treated as
   *no match* and reported as a warning. Never as "matched", and never as a crash.

A timeout is not an error: the scan must keep going, and every skipped file has to be
explainable. So it degrades to "did not match" and is counted.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Final

import regex

#: Default time budget for a single match, in milliseconds.
DEFAULT_TIMEOUT_MS: Final = 200

#: Patterns longer than this are refused: no filename rule needs 4 KB of regex.
MAX_PATTERN_LENGTH: Final = 4096

#: ``(a+)+`` / ``(a*)*`` / ``(?:a+)*`` - nested quantifiers with a single atom inside.
_NESTED_QUANTIFIER = re.compile(r"\((?:\?:)?[^()]*[+*]\)[+*]")


class RegexCompileError(ValueError):
    """The pattern cannot be used (bad syntax, too long, or catastrophic)."""


class CatastrophicPatternError(RegexCompileError):
    """The pattern contains nested quantifiers that invite exponential backtracking."""


def detects_catastrophic_backtracking(pattern: str) -> bool:
    """Return True for the classic nested-quantifier shapes.

    This is a heuristic, not a proof. It catches the patterns people actually write by
    accident; the runtime timeout is the real backstop.
    """
    return _NESTED_QUANTIFIER.search(pattern) is not None


class SafeRegex:
    """A compiled pattern that can never run longer than its budget."""

    __slots__ = ("_compiled", "_on_timeout", "pattern", "timeout_ms")

    def __init__(
        self,
        pattern: str,
        compiled: Any,
        timeout_ms: int,
        on_timeout: Callable[[str], None] | None = None,
    ) -> None:
        self.pattern = pattern
        self.timeout_ms = timeout_ms
        self._compiled = compiled
        self._on_timeout = on_timeout

    @classmethod
    def compile(
        cls,
        pattern: str,
        *,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        flags: int = 0,
        on_timeout: Callable[[str], None] | None = None,
        allow_catastrophic: bool = False,
    ) -> SafeRegex:
        """Compile *pattern*, refusing anything unsafe.

        Args:
            pattern: regular expression source.
            timeout_ms: per-match budget in milliseconds.
            flags: :mod:`regex` flags (e.g. ``regex.IGNORECASE``).
            on_timeout: called with the pattern when a match exceeds the budget.
            allow_catastrophic: escape hatch for tests only; never set from a rule file.

        Raises:
            CatastrophicPatternError: nested quantifiers detected.
            RegexCompileError: syntax error or oversized pattern.
        """
        if not isinstance(pattern, str) or not pattern:
            raise RegexCompileError("pattern must be a non-empty string")
        if len(pattern) > MAX_PATTERN_LENGTH:
            raise RegexCompileError(
                f"pattern is {len(pattern)} characters, limit is {MAX_PATTERN_LENGTH}",
            )
        if not allow_catastrophic and detects_catastrophic_backtracking(pattern):
            raise CatastrophicPatternError(
                f"pattern {pattern!r} contains nested quantifiers and could backtrack "
                "exponentially; rewrite it without the outer quantifier",
            )
        try:
            compiled = regex.compile(pattern, flags)
        except regex.error as exc:
            raise RegexCompileError(f"invalid regular expression {pattern!r}: {exc}") from exc
        if timeout_ms <= 0:
            raise RegexCompileError("timeout_ms must be positive")
        return cls(pattern, compiled, timeout_ms, on_timeout)

    def search(self, text: str) -> bool:
        """Return True when the pattern matches anywhere in *text*.

        A timeout returns False and reports a warning: "did not match in time" must never
        be confused with "matched".
        """
        try:
            return bool(self._compiled.search(text, timeout=self.timeout_ms / 1000.0))
        except TimeoutError:
            if self._on_timeout is not None:
                self._on_timeout(
                    f"regex timed out after {self.timeout_ms}ms (treated as no match): "
                    f"{self.pattern}",
                )
            return False

    def __repr__(self) -> str:
        return f"SafeRegex({self.pattern!r}, timeout_ms={self.timeout_ms})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SafeRegex):
            return NotImplemented
        return self.pattern == other.pattern and self.timeout_ms == other.timeout_ms

    def __hash__(self) -> int:
        return hash((self.pattern, self.timeout_ms))
