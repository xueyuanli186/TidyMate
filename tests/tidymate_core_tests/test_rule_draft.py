"""The visual builder's form -> YAML translation."""

from __future__ import annotations

from pathlib import Path

from tidymate_app.rule_draft import Condition, RuleDraft, build_preview, draft_to_yaml
from tidymate_core.rules import load_rules_from_text
from tidymate_core.rules.models import Rule


def load(draft: RuleDraft) -> Rule:
    return load_rules_from_text(draft_to_yaml(draft)).rules[0]


def test_ext_and_parent_round_trip() -> None:
    draft = RuleDraft(
        name="图片",
        conditions=[
            Condition("ext", "in", ".jpg, png"),
            Condition("parent", "equals", "Downloads"),
        ],
        template="Pictures/{year}/{name}",
    )
    rule = load(draft)
    assert rule.when.extensions == frozenset({".jpg", ".png"})
    assert rule.when.parent == "Downloads"
    assert rule.action.op.value == "move"


def test_size_range_and_mtime_between() -> None:
    draft = RuleDraft(
        name="范围",
        conditions=[
            Condition("size", "range", "1MB", "100MB"),
            Condition("mtime", "between", "2026-01-01", "2026-12-31"),
        ],
        template="Archive/{name}",
    )
    rule = load(draft)
    assert rule.when.size is not None
    assert rule.when.size.value_bytes == 1024**2
    assert rule.when.size_max is not None
    assert rule.when.mtime is not None
    assert rule.when.mtime_before is not None


def test_name_contains_becomes_a_regex() -> None:
    rule = load(RuleDraft(name="报告", conditions=[Condition("name", "contains", "报告")]))
    assert rule.when.name_regex is not None
    assert rule.when.name_regex.search("2026 报告.pdf")


def test_not_in_becomes_ext_exclude() -> None:
    rule = load(RuleDraft(name="x", conditions=[Condition("ext", "not_in", ".tmp, .log")]))
    assert rule.when.excluded_extensions == frozenset({".tmp", ".log"})


def test_empty_conditions_still_load_but_match_nothing() -> None:
    rule = load(RuleDraft(name="空"))
    assert rule.when.name_regex is not None
    assert not rule.when.name_regex.search("anything.txt")


def test_preview_matches_real_files(tmp_path: Path) -> None:
    inbox = tmp_path / "Downloads"
    inbox.mkdir()
    (inbox / "a.jpg").write_bytes(b"x")
    (inbox / "b.pdf").write_bytes(b"x")
    draft = RuleDraft(
        name="图片",
        conditions=[Condition("ext", "in", ".jpg")],
        template="Pictures/{year}/{name}",
    )
    plan = build_preview(draft, str(inbox), str(tmp_path / "out"))
    assert plan.stats.total_scanned == 2
    assert plan.stats.matched == 1
    assert plan.executable()[0].dst is not None
