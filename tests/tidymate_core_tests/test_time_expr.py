"""Time expressions: UTC comparison, timezone handling, relative windows."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from tidymate_core.rules.time_expr import UNIT_SECONDS, parse_time_expression

NOW = datetime(2026, 10, 20, 12, 0, 0, tzinfo=UTC)


def test_absolute_date_means_midnight_utc() -> None:
    condition = parse_time_expression(">=2024-01-01")
    assert condition.threshold() == datetime(2024, 1, 1, tzinfo=UTC)


def test_absolute_date_boundary_is_inclusive_for_greater_equal() -> None:
    condition = parse_time_expression(">=2024-01-01")
    assert condition.matches(datetime(2024, 1, 1, tzinfo=UTC)) is True
    assert condition.matches(datetime(2023, 12, 31, 23, 59, 59, tzinfo=UTC)) is False


def test_absolute_instant_with_zulu_suffix() -> None:
    condition = parse_time_expression("<2024-06-01T12:30:00Z")
    assert condition.threshold() == datetime(2024, 6, 1, 12, 30, tzinfo=UTC)


def test_absolute_instant_with_offset_is_converted_to_utc() -> None:
    condition = parse_time_expression("==2024-01-01T08:00:00+08:00")
    assert condition.threshold() == datetime(2024, 1, 1, tzinfo=UTC)


def test_same_instant_in_two_timezones_is_the_same_threshold() -> None:
    utc = parse_time_expression("==2024-01-01T00:00:00Z")
    shanghai = parse_time_expression("==2024-01-01T08:00:00+08:00")
    assert utc.threshold() == shanghai.threshold()


def test_last_n_days_is_anchored_to_injected_now() -> None:
    condition = parse_time_expression("last-30d")
    assert condition.matches(NOW - timedelta(days=29), now=NOW) is True
    assert condition.matches(NOW - timedelta(days=31), now=NOW) is False
    assert condition.matches(NOW, now=NOW) is True


def test_older_than_is_strictly_older() -> None:
    condition = parse_time_expression("older-than-1y")
    exactly_one_year = NOW - timedelta(days=365)
    assert condition.matches(exactly_one_year, now=NOW) is False
    assert condition.matches(exactly_one_year - timedelta(seconds=1), now=NOW) is True


def test_week_and_month_units() -> None:
    assert parse_time_expression("last-2w").relative_delta == timedelta(seconds=14 * 86400)
    assert parse_time_expression("last-6m").relative_delta == timedelta(seconds=6 * 30 * 86400)
    assert UNIT_SECONDS["y"] == 365 * 86400


def test_relative_expressions_default_to_now() -> None:
    condition = parse_time_expression("last-30d")
    assert condition.matches(datetime.now(tz=UTC)) is True


def test_naive_mtime_is_rejected() -> None:
    condition = parse_time_expression(">=2024-01-01")
    with pytest.raises(ValueError, match="timezone aware"):
        condition.matches(datetime(2024, 6, 1))


def test_utc_and_local_represent_the_same_instant() -> None:
    condition = parse_time_expression(">=2024-01-01")
    local = datetime(2024, 1, 1, 8, 0, tzinfo=timezone(timedelta(hours=8)))
    assert condition.matches(local) is True


@pytest.mark.parametrize(
    "expression",
    [
        "2024-01-01",  # bare date, no operator
        ">=2024-13-01",  # month 13
        ">=2024-01-32",  # day 32
        "last-0d",  # zero window
        "last-30",  # missing unit
        "older-30d",  # typo for older-than
        ">=yesterday",  # no natural language
        "",
    ],
)
def test_invalid_expressions_are_rejected(expression: str) -> None:
    with pytest.raises(ValueError):
        parse_time_expression(expression)


def test_non_string_is_rejected() -> None:
    with pytest.raises(ValueError, match="must be a string"):
        parse_time_expression(12)  # type: ignore[arg-type]
