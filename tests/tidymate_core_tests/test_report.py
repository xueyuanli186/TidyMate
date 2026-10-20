"""Report renderers and artifact writing.

The important assertions here are cross-format: the Markdown numbers must equal the JSON
numbers, which must equal the plan's own counters. A report that disagrees with the data it
was built from is worse than no report (iron rule 10).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tidymate_core.planning.artifacts import ArtifactError, write_artifacts
from tidymate_core.planning.models import (
    ChangeStatus,
    ConflictType,
    Plan,
    PlannedChange,
    PlanStats,
    RejectReason,
)
from tidymate_core.planning.report import (
    plan_to_dict,
    plan_to_json,
    render_markdown,
    render_table,
)

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
OUT = r"C:\out"


def make_plan() -> Plan:
    changes = (
        PlannedChange(
            seq=1,
            src=r"C:\in\a.jpg",
            dst=r"C:\out\a.jpg",
            op="move",
            rule_id="images",
            status=ChangeStatus.EXECUTE,
            size=100,
        ),
        PlannedChange(
            seq=2,
            src=r"C:\in\b.jpg",
            dst=r"C:\out\b.jpg",
            op="move",
            rule_id="images",
            status=ChangeStatus.SKIP,
            conflict=ConflictType.EXISTS_ON_DISK,
            size=200,
        ),
        PlannedChange(
            seq=3,
            src=r"C:\in\c.jpg",
            dst=r"C:\out\b.jpg",
            op="move",
            rule_id="images",
            status=ChangeStatus.SKIP,
            conflict=ConflictType.INTRA_BATCH,
            size=300,
        ),
        PlannedChange(
            seq=4,
            src=r"C:\in\locked.jpg",
            dst=None,
            op="move",
            rule_id="images",
            status=ChangeStatus.REJECT,
            reason=RejectReason.SPECIAL_FILE,
            notes=("read-only",),
            size=400,
        ),
        PlannedChange(
            seq=5,
            src=r"C:\in\junk.tmp",
            dst=None,
            op="trash",
            rule_id="junk",
            status=ChangeStatus.EXECUTE,
            size=500,
        ),
    )
    stats = PlanStats(
        total_scanned=9,
        matched=5,
        will_execute=2,
        will_skip=2,
        rejected=1,
        conflicts=2,
        conflicts_exists=1,
        conflicts_intra=1,
        conflicts_review=0,
        bytes_freed=500,
        bytes_added=0,
        by_rule={"images": 4, "junk": 1},
    )
    return Plan(
        batch_id="dryrun-20261020-120000",
        created_at=NOW,
        output_root=OUT,
        rules_source="rules.yaml",
        changes=changes,
        stats=stats,
        plan_hash="a" * 64,
        warnings=("regex timed out after 200ms",),
    )


def test_plan_to_dict_has_the_required_fields() -> None:
    payload = plan_to_dict(make_plan())
    for key in ("batch_id", "created_at", "output_root", "plan_hash", "stats", "changes"):
        assert key in payload
    change = payload["changes"][0]  # type: ignore[index]
    assert set(change) == {
        "seq",
        "src",
        "dst",
        "op",
        "rule_id",
        "status",
        "conflict",
        "reason",
        "error_kind",
        "mtime_utc",
        "flags",
        "notes",
        "size",
    }


def test_plan_json_is_parseable_and_stable() -> None:
    first = plan_to_json(make_plan())
    second = plan_to_json(make_plan())
    assert first == second
    assert json.loads(first)["plan_hash"] == "a" * 64


def test_table_contains_summary_and_markers() -> None:
    table = render_table(make_plan())
    assert "dry-run" in table
    assert "hash=aaaaaaaaaaaaaaaa" in table
    assert "execute=2" in table
    assert "conflicts=2" in table
    assert "!" in table, "conflict rows must be marked"


def test_table_truncates_long_plans() -> None:
    table = render_table(make_plan(), limit=2)
    assert "more change(s) not shown" in table


def test_markdown_has_every_required_section() -> None:
    report = render_markdown(make_plan())
    for heading in (
        "## 摘要",
        "## 已跳过：ADS / OneDrive 占位",
        "## 冲突",
        "## 拒绝项",
        "## 失败项",
        "## 将执行",
        "## 按规则分组",
    ):
        assert heading in report
    assert "⚠️" in report
    assert "本次没有修改任何文件" in report


def test_markdown_numbers_match_json_numbers() -> None:
    plan = make_plan()
    payload = plan_to_dict(plan)
    report = render_markdown(plan)
    stats = payload["stats"]
    assert isinstance(stats, dict)
    for label, key in (
        ("总扫描数", "total_scanned"),
        ("命中规则数", "matched"),
        ("将执行数", "will_execute"),
        ("将跳过数", "will_skip"),
        ("拒绝数", "rejected"),
        ("冲突总数", "conflicts"),
    ):
        assert f"| {label} | {stats[key]} |" in report


def test_markdown_counts_match_change_list() -> None:
    plan = make_plan()
    payload = plan_to_dict(plan)
    changes = payload["changes"]
    assert isinstance(changes, list)
    assert sum(1 for c in changes if c["status"] == "execute") == plan.stats.will_execute
    assert sum(1 for c in changes if c["conflict"] != "none") == plan.stats.conflicts
    assert sum(1 for c in changes if c["status"] == "reject") == plan.stats.rejected


def test_write_artifacts_creates_both_files(tmp_path: Path) -> None:
    plan = make_plan()
    plan = Plan(
        batch_id=plan.batch_id,
        created_at=plan.created_at,
        output_root=str(tmp_path),
        rules_source=plan.rules_source,
        changes=plan.changes,
        stats=plan.stats,
        plan_hash=plan.plan_hash,
        warnings=plan.warnings,
    )
    directory = tmp_path / "reports"
    paths = write_artifacts(plan, str(directory))
    assert paths.plan_json.is_file()
    assert paths.report_md.is_file()
    assert json.loads(paths.plan_json.read_text(encoding="utf-8"))["batch_id"] == plan.batch_id


def test_write_artifacts_accepts_an_ordinary_directory(tmp_path: Path) -> None:
    plan = make_plan()
    paths = write_artifacts(plan, str(tmp_path / "reports"))
    assert paths.plan_json.is_file()


def test_write_artifacts_refuses_protected_locations() -> None:
    plan = make_plan()
    with pytest.raises(ArtifactError, match="protected location"):
        write_artifacts(plan, r"C:\Windows\Temp\tidymate")


def test_artifact_filenames_are_fixed() -> None:
    from tidymate_core.planning.artifacts import PLAN_FILENAME, REPORT_FILENAME

    assert PLAN_FILENAME == "plan.json"
    assert REPORT_FILENAME == "report.md"
