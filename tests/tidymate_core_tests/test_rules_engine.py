"""Rule set evaluation: priority ordering and first-match semantics."""

from __future__ import annotations

import textwrap
from collections.abc import Callable

import pytest

from tidymate_core.rules.engine import RuleSet
from tidymate_core.rules.loader import load_rules_from_text
from tidymate_core.scanning.models import FileEntry

TWO_RULES = """
rules:
  - id: general-images
    priority: 20
    when:
      ext: [".jpg"]
    action:
      op: move
      template: "Sorted/images/{stem}{ext}"
  - id: download-images
    priority: 10
    when:
      ext: [".jpg"]
      path_glob: "**/Downloads/**"
    action:
      op: move
      template: "Sorted/downloads/{stem}{ext}"
  - id: disabled-images
    priority: 1
    when:
      ext: [".jpg"]
    action:
      op: move
      template: "Sorted/never/{stem}{ext}"
    enabled: false
"""


@pytest.fixture
def ruleset() -> RuleSet:
    return load_rules_from_text(textwrap.dedent(TWO_RULES))


def test_priority_decides_the_winner(
    ruleset: RuleSet,
    make_entry: Callable[..., FileEntry],
) -> None:
    entry = make_entry("photo.jpg", parent=r"C:\Users\me\Downloads")
    matched = ruleset.match(entry)
    assert matched is not None
    assert matched.id == "download-images"


def test_disabled_rule_never_matches(
    ruleset: RuleSet,
    make_entry: Callable[..., FileEntry],
) -> None:
    entry = make_entry("photo.jpg")
    matched = ruleset.match(entry)
    assert matched is not None
    assert matched.id == "general-images"


def test_first_match_only_returns_one(
    ruleset: RuleSet,
    make_entry: Callable[..., FileEntry],
) -> None:
    entry = make_entry("photo.jpg", parent=r"C:\Users\me\Downloads")
    assert len(ruleset.match_all(entry)) == 2
    assert ruleset.first_match_only is True


def test_first_match_only_can_be_disabled(
    make_entry: Callable[..., FileEntry],
) -> None:
    ruleset = load_rules_from_text(textwrap.dedent("first_match_only: false\n" + TWO_RULES))
    entry = make_entry("photo.jpg", parent=r"C:\Users\me\Downloads")
    assert len(ruleset.match_all(entry)) == 2


def test_no_match_returns_none(
    ruleset: RuleSet,
    make_entry: Callable[..., FileEntry],
) -> None:
    assert ruleset.match(make_entry("document.pdf")) is None
    assert ruleset.match_all(make_entry("document.pdf")) == ()


def test_enabled_rules_excludes_disabled(ruleset: RuleSet) -> None:
    assert [rule.id for rule in ruleset.enabled_rules] == [
        "download-images",
        "general-images",
    ]


def test_ruleset_is_iterable(ruleset: RuleSet) -> None:
    # Sorted by priority: the disabled rule has priority 1, so it comes first.
    assert [rule.id for rule in ruleset] == [
        "disabled-images",
        "download-images",
        "general-images",
    ]


def test_ruleset_length(ruleset: RuleSet) -> None:
    assert len(ruleset) == 3


def test_match_accepts_injected_now(
    make_entry: Callable[..., FileEntry],
) -> None:
    from datetime import UTC, datetime

    ruleset = load_rules_from_text(
        textwrap.dedent(
            """
            rules:
              - id: recent
                when: {mtime: "last-7d"}
                action: {op: move, template: "x/{stem}"}
            """,
        ),
    )
    entry = make_entry("a.txt", mtime=datetime(2026, 10, 15, tzinfo=UTC))
    assert ruleset.match(entry, now=datetime(2026, 10, 20, tzinfo=UTC)) is not None
    assert ruleset.match(entry, now=datetime(2026, 11, 20, tzinfo=UTC)) is None
