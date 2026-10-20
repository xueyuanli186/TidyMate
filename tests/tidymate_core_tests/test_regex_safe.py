"""SafeRegex: compile-time screening and runtime timeout.

The timeout test is the important one: a catastrophic pattern must degrade to "no match"
within the budget, report a warning, and never raise or hang.
"""

from __future__ import annotations

import time

import pytest

from tidymate_core.rules.regex_safe import (
    MAX_PATTERN_LENGTH,
    CatastrophicPatternError,
    RegexCompileError,
    SafeRegex,
    detects_catastrophic_backtracking,
)


def test_simple_match() -> None:
    matcher = SafeRegex.compile(r"^IMG_\d{4}")
    assert matcher.search("IMG_0001.jpg") is True
    assert matcher.search("holiday.jpg") is False


def test_invalid_syntax_is_rejected() -> None:
    with pytest.raises(RegexCompileError, match="invalid regular expression"):
        SafeRegex.compile("(")


def test_empty_pattern_is_rejected() -> None:
    with pytest.raises(RegexCompileError):
        SafeRegex.compile("")


def test_pattern_length_limit() -> None:
    with pytest.raises(RegexCompileError, match="limit"):
        SafeRegex.compile("a" * (MAX_PATTERN_LENGTH + 1))


@pytest.mark.parametrize("pattern", [r"(a+)+", r"(a*)*", r"(?:\d+)+", r"(x+)*$"])
def test_catastrophic_patterns_are_rejected(pattern: str) -> None:
    assert detects_catastrophic_backtracking(pattern) is True
    with pytest.raises(CatastrophicPatternError):
        SafeRegex.compile(pattern)


@pytest.mark.parametrize("pattern", [r"(a|aa)+", r"(ab)+", r"\d{4}", r"(?:a|b)*c"])
def test_ordinary_patterns_are_not_flagged(pattern: str) -> None:
    assert detects_catastrophic_backtracking(pattern) is False
    assert SafeRegex.compile(pattern).pattern == pattern


def test_allow_catastrophic_escape_hatch_for_tests() -> None:
    matcher = SafeRegex.compile(r"(a+)+", allow_catastrophic=True)
    assert matcher.search("aaa") is True


def test_timeout_returns_false_and_warns() -> None:
    warnings: list[str] = []
    matcher = SafeRegex.compile(r"(a|aa)+$", timeout_ms=50, on_timeout=warnings.append)

    started = time.perf_counter()
    result = matcher.search("a" * 40 + "X")
    elapsed = time.perf_counter() - started

    assert result is False, "a timed-out match must never be reported as a match"
    assert elapsed < 2.0, "the timeout must actually bound the runtime"
    assert len(warnings) == 1
    assert "timed out" in warnings[0]


def test_timeout_without_callback_does_not_raise() -> None:
    matcher = SafeRegex.compile(r"(a|aa)+$", timeout_ms=30)
    assert matcher.search("a" * 40 + "X") is False


def test_equality_and_hash_are_value_based() -> None:
    first = SafeRegex.compile("abc")
    second = SafeRegex.compile("abc")
    other = SafeRegex.compile("abc", timeout_ms=999)
    assert first == second
    assert first != other
    assert hash(first) == hash(second)


def test_repr_shows_pattern_and_budget() -> None:
    text = repr(SafeRegex.compile("abc", timeout_ms=123))
    assert "abc" in text
    assert "123" in text
