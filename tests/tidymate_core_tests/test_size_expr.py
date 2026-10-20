"""Size expressions: units, boundaries and rejection of anything ambiguous."""

from __future__ import annotations

import pytest

from tidymate_core.rules.size_expr import parse_size_expression

ONE_MB = 1024 * 1024


def test_parses_megabytes() -> None:
    condition = parse_size_expression(">=1MB")
    assert condition.op == ">="
    assert condition.value_bytes == ONE_MB


def test_boundary_is_inclusive_for_greater_equal() -> None:
    assert parse_size_expression(">=1MB").matches(ONE_MB) is True
    assert parse_size_expression(">=1MB").matches(ONE_MB - 1) is False


def test_boundary_is_exclusive_for_greater_than() -> None:
    assert parse_size_expression(">1MB").matches(ONE_MB) is False
    assert parse_size_expression(">1MB").matches(ONE_MB + 1) is True


def test_lower_than_operator() -> None:
    assert parse_size_expression("<500KB").matches(499 * 1024) is True
    assert parse_size_expression("<500KB").matches(500 * 1024) is False


def test_equality_and_inequality() -> None:
    assert parse_size_expression("==0B").matches(0) is True
    assert parse_size_expression("==0B").matches(1) is False
    assert parse_size_expression("!=0B").matches(1) is True


def test_decimal_amounts_are_exact() -> None:
    assert parse_size_expression("==1.5KB").value_bytes == 1536


def test_units_are_case_insensitive() -> None:
    assert parse_size_expression(">=1mb").value_bytes == ONE_MB
    assert parse_size_expression(">=1Mb").value_bytes == ONE_MB
    assert parse_size_expression(">=1024b").value_bytes == 1024


def test_unit_defaults_to_bytes() -> None:
    assert parse_size_expression(">=100").value_bytes == 100


def test_whitespace_is_tolerated() -> None:
    assert parse_size_expression("  >=  2   GB ").value_bytes == 2 * 1024**3
    assert parse_size_expression(">= 1 MB").value_bytes == ONE_MB


def test_bare_number_means_bytes() -> None:
    assert parse_size_expression(">1").value_bytes == 1


def test_str_roundtrip() -> None:
    assert str(parse_size_expression(">=1MB")) == ">=1048576B"


@pytest.mark.parametrize(
    "expression",
    [
        "1MB",  # missing operator
        "=>1MB",  # wrong operator order
        ">=1XB",  # unknown unit
        "",  # empty
        "~1MB",  # unknown operator
        ">=1MB extra",  # trailing garbage
    ],
)
def test_invalid_expressions_are_rejected(expression: str) -> None:
    with pytest.raises(ValueError):
        parse_size_expression(expression)


def test_non_string_is_rejected() -> None:
    with pytest.raises(ValueError, match="must be a string"):
        parse_size_expression(1024)  # type: ignore[arg-type]
