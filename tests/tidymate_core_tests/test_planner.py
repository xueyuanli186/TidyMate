"""Planner tests: the dry-run must be complete, honest and reproducible."""

from __future__ import annotations

import textwrap
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tidymate_core.planning.models import ChangeStatus, ConflictType, RejectReason
from tidymate_core.planning.planner import PlanRequest, build_plan
from tidymate_core.rules.engine import RuleSet
from tidymate_core.rules.loader import load_rules_from_text
from tidymate_core.scanning import ScanConfig

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


def rules(yaml_text: str) -> RuleSet:
    return load_rules_from_text(textwrap.dedent(yaml_text))


def request(
    root: Path,
    out: Path,
    ruleset: RuleSet,
    *,
    created: datetime | None = None,
) -> PlanRequest:
    return PlanRequest(
        scan=ScanConfig(roots=(str(root),)),
        rules=ruleset,
        output_root=str(out),
        created_at=created or NOW,
        local_tz=UTC,
        now=NOW,
    )


JPG_RULE = """
rules:
  - id: images
    when:
      ext: [".jpg"]
    action:
      op: move
      template: "flat/{name}"
      conflict: skip
"""


def test_basic_plan_executes(tmp_path: Path) -> None:
    root = tmp_path / "root"
    out = tmp_path / "out"
    root.mkdir()
    (root / "a.jpg").write_bytes(b"x" * 10)
    (root / "b.jpg").write_bytes(b"y" * 20)

    plan = build_plan(request(root, out, rules(JPG_RULE)))

    assert plan.stats.total_scanned == 2
    assert plan.stats.matched == 2
    assert plan.stats.will_execute == 2
    assert all(change.status is ChangeStatus.EXECUTE for change in plan.changes)
    assert {Path(change.dst).name for change in plan.changes if change.dst} == {"a.jpg", "b.jpg"}


def test_unmatched_file_is_not_in_the_plan(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "notes.txt").write_text("x", encoding="utf-8")

    plan = build_plan(request(root, tmp_path / "out", rules(JPG_RULE)))

    assert plan.stats.total_scanned == 1
    assert plan.stats.matched == 0
    assert plan.changes == ()


def test_intra_batch_same_destination_is_detected(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "x").mkdir(parents=True)
    (root / "y").mkdir(parents=True)
    (root / "x" / "same.jpg").write_bytes(b"a")
    (root / "y" / "same.jpg").write_bytes(b"b")

    plan = build_plan(request(root, tmp_path / "out", rules(JPG_RULE)))

    assert plan.stats.will_execute == 1
    assert plan.stats.conflicts_intra == 1
    conflict = next(
        change for change in plan.changes if change.conflict is ConflictType.INTRA_BATCH
    )
    assert conflict.status is ChangeStatus.SKIP
    assert any("same destination" in note for note in conflict.notes)


def test_case_insensitive_intra_batch_conflict(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "x").mkdir(parents=True)
    (root / "y").mkdir(parents=True)
    (root / "x" / "Report.pdf").write_bytes(b"a")
    (root / "y" / "report.pdf").write_bytes(b"b")

    pdf_rule = """
    rules:
      - id: pdfs
        when: {ext: [".pdf"]}
        action: {op: move, template: "flat/{name}"}
    """
    plan = build_plan(request(root, tmp_path / "out", rules(pdf_rule)))

    assert plan.stats.matched == 2
    assert plan.stats.conflicts_intra == 1, "Report.pdf and report.pdf are the same file on Windows"


def test_existing_destination_is_skipped(tmp_path: Path) -> None:
    root = tmp_path / "root"
    out = tmp_path / "out"
    root.mkdir()
    (out / "flat").mkdir(parents=True)
    (out / "flat" / "a.jpg").write_bytes(b"existing")
    (root / "a.jpg").write_bytes(b"new")

    plan = build_plan(request(root, out, rules(JPG_RULE)))

    change = plan.changes[0]
    assert change.status is ChangeStatus.SKIP
    assert change.conflict is ConflictType.EXISTS_ON_DISK
    assert plan.stats.will_execute == 0
    assert plan.stats.conflicts_exists == 1


def test_rename_policy_finds_a_free_name(tmp_path: Path) -> None:
    root = tmp_path / "root"
    out = tmp_path / "out"
    root.mkdir()
    (out / "flat").mkdir(parents=True)
    (out / "flat" / "a.jpg").write_bytes(b"existing")
    (root / "a.jpg").write_bytes(b"new")

    rename_rule = JPG_RULE.replace("conflict: skip", "conflict: rename")
    plan = build_plan(request(root, out, rules(rename_rule)))

    change = plan.changes[0]
    assert change.status is ChangeStatus.EXECUTE
    assert change.dst is not None
    assert change.dst.endswith("a (1).jpg")
    assert any("renamed" in note for note in change.notes)


def test_ask_policy_marks_for_review(tmp_path: Path) -> None:
    root = tmp_path / "root"
    out = tmp_path / "out"
    root.mkdir()
    (out / "flat").mkdir(parents=True)
    (out / "flat" / "a.jpg").write_bytes(b"existing")
    (root / "a.jpg").write_bytes(b"new")

    ask_rule = JPG_RULE.replace("conflict: skip", "conflict: ask")
    plan = build_plan(request(root, out, rules(ask_rule)))

    change = plan.changes[0]
    assert change.status is ChangeStatus.SKIP
    assert change.conflict is ConflictType.NEEDS_REVIEW
    assert plan.stats.conflicts_review == 1


def test_read_only_file_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    locked = root / "locked.jpg"
    locked.write_bytes(b"x")
    locked.chmod(0o444)

    plan = build_plan(request(root, tmp_path / "out", rules(JPG_RULE)))

    change = plan.changes[0]
    assert change.status is ChangeStatus.REJECT
    assert change.reason is RejectReason.SPECIAL_FILE
    assert "read-only" in change.notes[0]


def test_target_equal_to_source_is_rejected_as_ancestor(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.jpg").write_bytes(b"x")

    in_place = """
    rules:
      - id: images
        when: {ext: [".jpg"]}
        action: {op: move, template: "{name}"}
    """
    plan = build_plan(request(root, root, rules(in_place)))

    change = plan.changes[0]
    assert change.status is ChangeStatus.REJECT
    assert change.reason is RejectReason.ANCESTOR


def test_trash_plan_frees_space(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "junk.tmp").write_bytes(b"z" * 4096)

    trash_rule = """
    rules:
      - id: junk
        when: {ext: [".tmp"]}
        action: {op: trash}
    """
    plan = build_plan(request(root, tmp_path / "out", rules(trash_rule)))

    change = plan.changes[0]
    assert change.dst is None
    assert change.op == "trash"
    assert plan.stats.bytes_freed == 4096
    assert plan.stats.bytes_added == 0


def test_plan_hash_is_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    for name in ("a.jpg", "b.jpg", "c.jpg"):
        (root / name).write_bytes(b"x")

    ruleset = rules(JPG_RULE)
    first = build_plan(request(root, tmp_path / "out", ruleset, created=NOW))
    second = build_plan(
        request(root, tmp_path / "out", ruleset, created=NOW + timedelta(hours=3)),
    )
    assert first.plan_hash == second.plan_hash
    assert first.batch_id != second.batch_id


def test_plan_hash_changes_when_content_changes(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.jpg").write_bytes(b"x")
    ruleset = rules(JPG_RULE)

    before = build_plan(request(root, tmp_path / "out", ruleset))
    (root / "b.jpg").write_bytes(b"y")
    after = build_plan(request(root, tmp_path / "out", ruleset))
    assert before.plan_hash != after.plan_hash


def test_stats_reconcile_with_entries(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.jpg").write_bytes(b"x")
    (root / "b.jpg").write_bytes(b"y")
    (root / "c.txt").write_text("z", encoding="utf-8")

    plan = build_plan(request(root, tmp_path / "out", rules(JPG_RULE)))
    stats = plan.stats

    assert stats.total_scanned == 3
    assert stats.matched == 2
    assert stats.will_execute + stats.will_skip + stats.rejected == stats.matched
    assert stats.will_execute == sum(1 for c in plan.changes if c.is_executable)
    assert stats.matched == len(plan.changes)
    assert sum(stats.by_rule.values()) == stats.matched


def test_sequence_numbers_are_stable_and_ordered(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    for name in ("c.jpg", "a.jpg", "b.jpg"):
        (root / name).write_bytes(b"x")

    plan = build_plan(request(root, tmp_path / "out", rules(JPG_RULE)))
    assert [change.seq for change in plan.changes] == [1, 2, 3]
    assert [Path(change.src).name for change in plan.changes] == ["a.jpg", "b.jpg", "c.jpg"]


def test_output_root_inside_blacklist_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.jpg").write_bytes(b"x")

    plan = build_plan(request(root, Path(r"C:\Windows\Temp"), rules(JPG_RULE)))
    assert plan.changes[0].status is ChangeStatus.REJECT
    assert plan.changes[0].reason is RejectReason.BLACKLIST


@pytest.mark.parametrize("op", ["move", "rename", "copy"])
def test_every_op_is_previewed(tmp_path: Path, op: str) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.jpg").write_bytes(b"x")

    yaml_text = f"""
    rules:
      - id: images
        when: {{ext: [".jpg"]}}
        action: {{op: {op}, template: "flat/{{name}}"}}
    """
    plan = build_plan(request(root, tmp_path / "out", rules(yaml_text)))
    assert plan.changes[0].op == op
    assert plan.changes[0].status is ChangeStatus.EXECUTE
