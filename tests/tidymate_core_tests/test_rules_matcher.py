"""Condition matching: extensions, globs, regex, size, mtime, timeouts."""

from __future__ import annotations

import textwrap
from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from tidymate_core.rules.loader import load_rules_from_text
from tidymate_core.rules.matcher import glob_to_regex, matches
from tidymate_core.rules.models import When
from tidymate_core.scanning.models import FileEntry

WhenFactory = Callable[[str], When]


@pytest.fixture
def when_factory() -> WhenFactory:
    """Build a `When` by loading it as YAML, so the loader is exercised too."""

    def build(when_yaml: str) -> When:
        text = (
            "rules:\n"
            "  - id: t\n"
            "    when:\n" + textwrap.indent(textwrap.dedent(when_yaml).strip(), "      ") + "\n"
            "    action: {op: move, template: 'x/{stem}'}\n"
        )
        return load_rules_from_text(text).rules[0].when

    return build


def test_ext_matches_case_insensitively(
    make_entry: Callable[..., FileEntry],
    when_factory: WhenFactory,
) -> None:
    when = when_factory('ext: [".jpg"]')
    assert matches(make_entry("PHOTO.JPG"), when) is True
    assert matches(make_entry("photo.Jpg"), when) is True


def test_ext_rejects_other_extension(
    make_entry: Callable[..., FileEntry],
    when_factory: WhenFactory,
) -> None:
    when = when_factory('ext: [".jpg", ".png"]')
    assert matches(make_entry("photo.gif"), when) is False
    assert matches(make_entry("README"), when) is False


def test_path_glob_matches_downloads(
    make_entry: Callable[..., FileEntry],
    when_factory: WhenFactory,
) -> None:
    when = when_factory('path_glob: "**/Downloads/**"')
    in_downloads = make_entry("a.jpg", parent=r"C:\Users\me\Downloads")
    elsewhere = make_entry("a.jpg", parent=r"C:\Users\me\Documents")
    assert matches(in_downloads, when) is True
    assert matches(elsewhere, when) is False


def test_path_glob_single_star_does_not_cross_separator(
    make_entry: Callable[..., FileEntry],
    when_factory: WhenFactory,
) -> None:
    # path_glob matches the whole absolute path, so a bare "*.txt" matches nothing:
    # every absolute path contains at least one separator.
    entry = make_entry("a.txt", parent=r"C:\data")
    plain = when_factory('path_glob: "*.txt"')
    any_depth = when_factory('path_glob: "**/*.txt"')
    assert matches(entry, plain) is False
    assert matches(entry, any_depth) is True


def test_path_glob_double_star_matches_any_depth(
    make_entry: Callable[..., FileEntry],
    when_factory: WhenFactory,
) -> None:
    when = when_factory('path_glob: "**/*.txt"')
    assert matches(make_entry("a.txt", parent=r"C:\a\b\c"), when) is True


def test_path_glob_double_star_matches_zero_directories(
    make_entry: Callable[..., FileEntry],
    when_factory: WhenFactory,
) -> None:
    when = when_factory('path_glob: "**/Downloads/**"')
    assert matches(make_entry("a.jpg", parent=r"C:\Downloads"), when) is True


def test_path_regex_is_case_insensitive_when_flagged(
    make_entry: Callable[..., FileEntry],
    when_factory: WhenFactory,
) -> None:
    when = when_factory('path_regex: "(?i)download"')
    assert matches(make_entry("a.jpg", parent=r"C:\X\DOWNLOAD\y"), when) is True


def test_path_glob_and_regex_are_anded(
    make_entry: Callable[..., FileEntry],
    when_factory: WhenFactory,
) -> None:
    when = when_factory(
        """
        path_glob: "**/Downloads/**"
        path_regex: "(?i)2024"
        """,
    )
    both = make_entry("a.jpg", parent=r"C:\Downloads\2024")
    only_glob = make_entry("a.jpg", parent=r"C:\Downloads\2023")
    only_regex = make_entry("a.jpg", parent=r"C:\Documents\2024")
    assert matches(both, when) is True
    assert matches(only_glob, when) is False
    assert matches(only_regex, when) is False


def test_unc_path_matches_glob(
    make_entry: Callable[..., FileEntry],
    when_factory: WhenFactory,
) -> None:
    when = when_factory('path_glob: "**/Downloads/**"')
    entry = make_entry("a.jpg", parent=r"\\server\share\Downloads")
    assert matches(entry, when) is True


def test_size_boundary_exactly_one_megabyte(
    make_entry: Callable[..., FileEntry],
    when_factory: WhenFactory,
) -> None:
    one_mb = 1024 * 1024
    assert matches(make_entry("a.bin", size=one_mb), when_factory('size: ">=1MB"')) is True
    assert matches(make_entry("a.bin", size=one_mb), when_factory('size: ">1MB"')) is False
    assert matches(make_entry("a.bin", size=one_mb - 1), when_factory('size: ">=1MB"')) is False


def test_mtime_compares_in_utc(
    make_entry: Callable[..., FileEntry],
    when_factory: WhenFactory,
) -> None:
    when = when_factory('mtime: ">=2024-01-01"')
    after = make_entry("a.jpg", mtime=datetime(2024, 6, 1, tzinfo=UTC))
    before = make_entry("a.jpg", mtime=datetime(2023, 12, 31, 23, 59, tzinfo=UTC))
    assert matches(after, when) is True
    assert matches(before, when) is False


def test_mtime_relative_window(
    make_entry: Callable[..., FileEntry],
    when_factory: WhenFactory,
) -> None:
    when = when_factory('mtime: "last-30d"')
    now = datetime(2026, 10, 20, tzinfo=UTC)
    fresh = make_entry("a.jpg", mtime=datetime(2026, 10, 1, tzinfo=UTC))
    stale = make_entry("a.jpg", mtime=datetime(2026, 1, 1, tzinfo=UTC))
    assert matches(fresh, when, now=now) is True
    assert matches(stale, when, now=now) is False


def test_name_regex(
    make_entry: Callable[..., FileEntry],
    when_factory: WhenFactory,
) -> None:
    when = when_factory("name_regex: '^IMG_\\d{4}'")
    assert matches(make_entry("IMG_0001.jpg"), when) is True
    assert matches(make_entry("HOLIDAY.jpg"), when) is False


def test_timeout_is_reported_and_treated_as_no_match(
    make_entry: Callable[..., FileEntry],
) -> None:
    ruleset = load_rules_from_text(
        textwrap.dedent(
            """
            rules:
              - id: slow
                when: {name_regex: "(a|aa)+$"}
                action: {op: move, template: "x/{stem}"}
            """,
        ),
        timeout_ms=50,
    )
    entry = make_entry("a" * 40 + "X")
    assert matches(entry, ruleset.rules[0].when) is False
    assert ruleset.warnings, "a timed-out match must leave a warning behind"


def test_glob_to_regex_escapes_regex_metacharacters() -> None:
    translated = glob_to_regex("a+b(c).txt")
    assert "a\\+b\\(c\\)\\.txt" in translated
