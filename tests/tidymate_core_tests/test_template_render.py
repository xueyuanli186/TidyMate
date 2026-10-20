"""Template rendering: every whitelisted variable, every forbidden one, every sanitiser."""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest

from tidymate_core.rules.template import (
    ALLOWED_VARIABLES,
    FORBIDDEN_VARIABLES,
    MAX_SEGMENT_LENGTH,
    TemplateContext,
    TemplateError,
    parse_template,
    render_template,
    sanitize_segment,
)

MTIME = datetime(2024, 3, 7, 15, 4, 5, tzinfo=UTC)


def context(**overrides: object) -> TemplateContext:
    base: dict[str, object] = {
        "mtime_utc": MTIME,
        "local_tz": UTC,
        "ext": ".jpg",
        "stem": "IMG_0001",
        "name": "IMG_0001.jpg",
        "parent": "Downloads",
        "size": 500,
        "rule_id": "images",
        "seq": 42,
    }
    base.update(overrides)
    return TemplateContext(**base)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("variable", "expected"),
    [
        ("year", "2024"),
        ("month", "03"),
        ("day", "07"),
        ("hour", "15"),
        ("minute", "04"),
        ("year_utc", "2024"),
        ("month_utc", "03"),
        ("day_utc", "07"),
        ("ext", ".jpg"),
        ("ext_nodot", "jpg"),
        ("stem", "IMG_0001"),
        ("name", "IMG_0001.jpg"),
        ("parent", "Downloads"),
        ("size_bucket", "tiny"),
        ("rule_id", "images"),
        ("seq", "000042"),
    ],
)
def test_each_whitelisted_variable_renders(variable: str, expected: str) -> None:
    rendered = render_template("{" + variable + "}", context())
    assert rendered.segments == (expected,)


def test_whitelist_matches_the_documented_set() -> None:
    assert {
        "year",
        "month",
        "day",
        "hour",
        "minute",
        "year_utc",
        "month_utc",
        "day_utc",
        "ext",
        "ext_nodot",
        "stem",
        "name",
        "parent",
        "size_bucket",
        "rule_id",
        "seq",
    } == ALLOWED_VARIABLES


def test_local_and_utc_dates_can_differ() -> None:
    from datetime import timedelta, timezone

    late_utc = datetime(2024, 3, 7, 23, 30, tzinfo=UTC)
    shanghai = timezone(timedelta(hours=8))
    rendered = render_template(
        "{year_utc}-{month_utc}-{day_utc}_{year}-{month}-{day}",
        context(mtime_utc=late_utc, local_tz=shanghai),
    )
    assert rendered.segments == ("2024-03-07_2024-03-08",)


@pytest.mark.parametrize(
    ("size", "bucket"),
    [
        (0, "tiny"),
        (100 * 1024 - 1, "tiny"),
        (100 * 1024, "small"),
        (10 * 1024 * 1024 - 1, "small"),
        (10 * 1024 * 1024, "medium"),
        (1024**3 - 1, "medium"),
        (1024**3, "large"),
    ],
)
def test_size_bucket_boundaries(size: int, bucket: str) -> None:
    assert render_template("{size_bucket}", context(size=size)).segments == (bucket,)


@pytest.mark.parametrize("variable", sorted(FORBIDDEN_VARIABLES))
def test_explicitly_forbidden_variables_are_rejected(variable: str) -> None:
    with pytest.raises(TemplateError, match=re.escape(variable)):
        parse_template("{" + variable + "}")


def test_env_prefix_is_rejected_by_name() -> None:
    with pytest.raises(TemplateError, match="explicitly forbidden"):
        parse_template("{env:USERPROFILE}")


def test_hash_prefix_is_rejected() -> None:
    with pytest.raises(TemplateError, match="explicitly forbidden"):
        parse_template("{hash8}")


@pytest.mark.parametrize("variable", ["Year", "YEAR", "ImgStem"])
def test_case_variants_are_rejected_and_named(variable: str) -> None:
    with pytest.raises(TemplateError, match=re.escape(variable)):
        parse_template("{" + variable + "}")


def test_unknown_variable_is_named_in_the_error() -> None:
    with pytest.raises(TemplateError, match="bogus"):
        parse_template("x/{bogus}")


def test_unbalanced_brace_is_rejected() -> None:
    with pytest.raises(TemplateError, match="unbalanced"):
        parse_template("Sorted/{year")


def test_consecutive_separator_is_rejected() -> None:
    with pytest.raises(TemplateError, match="empty path segment"):
        parse_template("Sorted//{year}")


def test_whitespace_only_render_falls_back() -> None:
    rendered = render_template("{stem}", context(stem="   "))
    assert rendered.segments == ("untitled_000042",)
    assert any("empty segment" in note for note in rendered.notes)


def test_empty_stem_falls_back_to_untitled() -> None:
    rendered = render_template("x/{stem}", context(stem=""))
    assert rendered.segments == ("x", "untitled_000042")


@pytest.mark.parametrize("char", [":", "*", "?", '"', "<", ">", "|"])
def test_illegal_filename_characters_are_replaced(char: str) -> None:
    # Windows file names cannot contain these, but values can arrive from other
    # file systems; rendering must repair them rather than fail the whole plan.
    rendered = render_template("{name}", context(name="a" + char + "b.jpg"))
    assert rendered.segments == ("a_b.jpg",)
    assert any("illegal filename characters" in note for note in rendered.notes)


def test_control_characters_are_dropped() -> None:
    rendered = render_template("{name}", context(name="a\x01\x02b.jpg"))
    assert rendered.segments == ("ab.jpg",)


def test_leading_space_and_trailing_dot_are_trimmed() -> None:
    # Windows forbids a trailing dot/space but allows a leading dot, so ".name" survives.
    rendered = render_template("  .name.  ", context())
    assert rendered.segments == (".name",)


def test_leading_dot_is_preserved() -> None:
    rendered = render_template("{name}", context(name=".gitignore"))
    assert rendered.segments == (".gitignore",)


def test_short_segment_is_not_truncated() -> None:
    rendered = render_template("{stem}", context(stem="x" * 10))
    assert rendered.segments[0] == "x" * 10
    assert rendered.notes == ()


def test_long_segment_is_truncated_with_hash_and_extension() -> None:
    long_name = "a" * 120 + ".jpg"
    rendered = render_template("{name}", context(name=long_name))
    segment = rendered.segments[0]
    assert len(segment) <= MAX_SEGMENT_LENGTH
    assert segment.endswith(".jpg")
    assert re.search(r"-[0-9a-f]{8}\.jpg$", segment)
    assert any("truncated" in note for note in rendered.notes)


def test_truncation_hash_is_stable_and_input_specific() -> None:
    first = render_template("{name}", context(name="a" * 120 + ".jpg")).segments[0]
    second = render_template("{name}", context(name="a" * 120 + ".jpg")).segments[0]
    other = render_template("{name}", context(name="b" * 120 + ".jpg")).segments[0]
    assert first == second, "same input must produce the same truncated name"
    assert first != other, "different input must produce a different hash suffix"


def test_nested_template_still_rejected() -> None:
    with pytest.raises(TemplateError):
        parse_template("{{year}}")


def test_render_rejects_invalid_template() -> None:
    with pytest.raises(TemplateError):
        render_template("x/{nope}", context())


def test_sanitize_segment_reports_replacement() -> None:
    notes: list[str] = []
    assert sanitize_segment("a:b", seq=1, notes=notes) == "a_b"
    assert notes
