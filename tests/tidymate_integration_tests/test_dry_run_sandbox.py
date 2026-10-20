"""End-to-end dry-run on a real directory tree, including artifact export."""

from __future__ import annotations

import json
import textwrap
from datetime import UTC, datetime
from pathlib import Path

from tidymate_core.planning import PlanRequest, build_plan, write_artifacts
from tidymate_core.planning.models import ChangeStatus, ConflictType, RejectReason
from tidymate_core.rules import load_rules_from_text
from tidymate_core.scanning import ScanConfig

RULES = """
rules:
  - id: images
    priority: 10
    when:
      ext: [".jpg", ".jpeg"]
    action:
      op: move
      template: "images/{year}/{ext_nodot}/{name}"
      conflict: skip
  - id: texts
    priority: 20
    when:
      ext: [".txt"]
    action:
      op: copy
      template: "texts/{name}"
      conflict: skip
"""


def test_dry_run_on_real_tree(tmp_path: Path) -> None:
    root = tmp_path / "inbox"
    (root / "keep").mkdir(parents=True)
    (root / "photo.jpg").write_bytes(b"a" * 100)
    (root / "keep" / "photo.jpg").write_bytes(b"b" * 200)
    (root / "IMG_0001.JPG").write_bytes(b"c" * 300)
    (root / "notes.txt").write_bytes(b"d" * 50)
    locked = root / "locked.txt"
    locked.write_bytes(b"e" * 10)
    locked.chmod(0o444)

    ruleset = load_rules_from_text(textwrap.dedent(RULES))
    request = PlanRequest(
        scan=ScanConfig(roots=(str(root),)),
        rules=ruleset,
        output_root=str(tmp_path / "sorted"),
        created_at=datetime(2026, 10, 20, 12, 0, tzinfo=UTC),
        now=datetime(2026, 10, 20, 12, 0, tzinfo=UTC),
    )
    plan = build_plan(request)

    assert plan.stats.total_scanned == 5
    assert plan.stats.matched == 5
    assert plan.stats.conflicts_intra == 1, "two photo.jpg files render to the same target"
    assert plan.stats.rejected == 1, "the read-only file must be refused"
    assert plan.stats.bytes_added == 50, "only the copy contributes to added bytes"

    rejected = [c for c in plan.changes if c.reason is RejectReason.SPECIAL_FILE]
    assert len(rejected) == 1
    assert rejected[0].src.endswith("locked.txt")

    intra = [c for c in plan.changes if c.conflict is ConflictType.INTRA_BATCH]
    assert len(intra) == 1
    assert intra[0].status is ChangeStatus.SKIP

    reports = tmp_path / "reports"
    written = write_artifacts(plan, str(reports))
    assert written.plan_json.is_file()
    assert written.report_md.is_file()

    payload = json.loads(written.plan_json.read_text(encoding="utf-8"))
    assert payload["plan_hash"] == plan.plan_hash
    assert payload["stats"]["total_scanned"] == plan.stats.total_scanned
    assert len(payload["changes"]) == len(plan.changes)
    assert "本次没有修改任何文件" in written.report_md.read_text(encoding="utf-8")


def test_two_dry_runs_produce_the_same_hash(tmp_path: Path) -> None:
    root = tmp_path / "inbox"
    root.mkdir()
    for name in ("a.jpg", "b.jpg", "c.txt"):
        (root / name).write_bytes(b"x")

    ruleset = load_rules_from_text(textwrap.dedent(RULES))

    def run(created: datetime) -> str:
        plan = build_plan(
            PlanRequest(
                scan=ScanConfig(roots=(str(root),)),
                rules=ruleset,
                output_root=str(tmp_path / "sorted"),
                created_at=created,
                now=created,
            ),
        )
        return plan.plan_hash

    first = run(datetime(2026, 10, 20, 12, 0, tzinfo=UTC))
    second = run(datetime(2030, 1, 1, 0, 0, tzinfo=UTC))
    assert first == second


def test_dry_run_does_not_touch_the_source_tree(tmp_path: Path) -> None:
    root = tmp_path / "inbox"
    root.mkdir()
    (root / "a.jpg").write_bytes(b"x" * 10)
    before = sorted(p.name for p in root.iterdir())

    ruleset = load_rules_from_text(textwrap.dedent(RULES))
    plan = build_plan(
        PlanRequest(
            scan=ScanConfig(roots=(str(root),)),
            rules=ruleset,
            output_root=str(tmp_path / "sorted"),
        ),
    )
    assert plan.stats.will_execute == 1

    after = sorted(p.name for p in root.iterdir())
    assert before == after, "a dry-run must not create, move or delete anything"
    assert not (tmp_path / "sorted").exists(), "a dry-run must not create the output tree"
