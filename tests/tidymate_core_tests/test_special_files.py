"""P0: ADS and OneDrive placeholders must be skipped, reported and explained.

Neither hazard can be created on demand: Windows refuses to set
``FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS`` from user code, and a real OneDrive folder is
not available in CI. The Two tests therefore cover the contract from both ends:

* a real NTFS ``Zone.Identifier`` stream (skipped when the volume cannot hold ADS);
* an injected :class:`FileEntry` carrying the placeholder attribute bits, which
  exercises the identical planner path without pretending the OS cooperated.
"""

from __future__ import annotations

import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from tidymate_core.planning import planner
from tidymate_core.planning.models import ChangeStatus
from tidymate_core.planning.planner import PlanRequest, build_plan
from tidymate_core.planning.report import plan_to_dict, render_markdown
from tidymate_core.rules.engine import RuleSet
from tidymate_core.rules.loader import load_rules_from_text
from tidymate_core.scanning import ScanConfig
from tidymate_core.scanning.models import FileAttributes, FileEntry
from tidymate_core.scanning.streams import list_alternate_streams
from tidymate_core.scanning.walker import build_entry

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)

RULES = """
rules:
  - id: images
    when:
      ext: [".jpg"]
    action:
      op: move
      template: "flat/{name}"
      conflict: skip
"""


RENAME_RULES = """
rules:
  - id: images
    when:
      ext: [".jpg"]
    action:
      op: move
      template: "flat/{name}"
      conflict: rename
"""


def ruleset() -> RuleSet:
    return load_rules_from_text(RULES)


def rename_ruleset() -> RuleSet:
    return load_rules_from_text(RENAME_RULES)


def make_request(
    root: Path,
    entries: tuple[FileEntry, ...] | None = None,
    *,
    rules: RuleSet | None = None,
) -> PlanRequest:
    return PlanRequest(
        scan=ScanConfig(roots=(str(root),)),
        rules=rules or ruleset(),
        output_root=str(root / "out"),
        created_at=NOW,
        local_tz=UTC,
        now=NOW,
        entries=entries,
    )


def fake_entry(
    root: Path, name: str, *, attributes: int, streams: tuple[str, ...] = ()
) -> FileEntry:
    """Build an entry whose Win32 attribute bits come from the test, not the disk."""
    path = root / name
    path.write_bytes(b"x" * 10)
    stat_result = path.stat()
    fake = SimpleNamespace(
        st_size=stat_result.st_size,
        st_mtime=stat_result.st_mtime,
        st_file_attributes=attributes,
    )
    return build_entry(
        str(root),
        name,
        cast("Any", fake),
        alternate_streams=streams,
    )


@pytest.mark.skipif(sys.platform != "win32", reason="NTFS alternate streams are Windows-only")
def test_real_zone_identifier_stream_is_detected_and_skipped(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    download = root / "download.jpg"
    download.write_bytes(b"x" * 10)
    try:
        with open(  # noqa: PTH123 - a stream name is not a Path, only a string works
            f"{download}:Zone.Identifier", "w", encoding="utf-8"
        ) as handle:
            handle.write("[ZoneTransfer]\r\nZoneId=3\r\n")
    except OSError:
        pytest.skip("the temporary volume does not support alternate data streams")
    assert list_alternate_streams(str(download)) == ("Zone.Identifier",)

    plan = build_plan(make_request(root))

    assert plan.stats.ads_skipped == 1
    change = plan.changes[0]
    assert change.status is ChangeStatus.SKIP
    assert change.error_kind == "ads"
    assert "Zone.Identifier" in change.notes[0]
    assert "Sysinternals Streams" in change.notes[1]
    assert plan_to_dict(plan)["changes"][0]["error_kind"] == "ads"  # type: ignore[index]

    report = render_markdown(plan)
    assert "## 已跳过：ADS / OneDrive 占位" in report
    assert "streams -d" in report


def test_onedrive_placeholder_is_skipped_with_guidance(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    entry = fake_entry(
        root,
        "cloud.jpg",
        attributes=int(FileAttributes.RECALL_ON_DATA_ACCESS),
    )
    assert entry.is_onedrive_placeholder

    plan = build_plan(make_request(root, entries=(entry,)))

    assert plan.stats.onedrive_skipped == 1
    assert plan.stats.will_execute == 0
    change = plan.changes[0]
    assert change.status is ChangeStatus.SKIP
    assert change.error_kind == "onedrive_placeholder"
    assert "Always keep on this device" in " ".join(change.notes)

    report = render_markdown(plan)
    assert "## 已跳过：ADS / OneDrive 占位" in report
    assert "Always keep on this device" in report


def test_ads_wins_over_onedrive_when_both_apply(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    entry = fake_entry(
        root,
        "both.jpg",
        attributes=int(FileAttributes.OFFLINE),
        streams=("Zone.Identifier",),
    )

    plan = build_plan(make_request(root, entries=(entry,)))

    assert plan.changes[0].error_kind == "ads"
    assert "also a cloud placeholder" in plan.changes[0].notes[0]


def test_rename_falls_back_to_a_timestamp_after_999_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.jpg").write_bytes(b"x")
    out = tmp_path / "out" / "flat"
    out.mkdir(parents=True)
    (out / "a.jpg").write_bytes(b"y")

    def always_conflicting(path: str) -> bool:
        name = Path(path).name
        return name == "a.jpg" or bool(re.fullmatch(r"a \(\d+\)\.jpg", name))

    monkeypatch.setattr(planner, "conflicts_on_disk", always_conflicting)

    plan = build_plan(make_request(root, rules=rename_ruleset()))

    change = plan.changes[0]
    assert change.status is ChangeStatus.EXECUTE
    assert change.dst is not None
    assert re.fullmatch(r"a_20261020-120000_000000\.jpg", Path(change.dst).name)


def test_rename_marks_failed_when_the_timestamp_also_collides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.jpg").write_bytes(b"x")

    monkeypatch.setattr(planner, "conflicts_on_disk", lambda _path: True)

    plan = build_plan(make_request(root, rules=rename_ruleset()))

    change = plan.changes[0]
    assert change.status is ChangeStatus.FAILED
    assert change.error_kind == "rename_exhausted"
    assert plan.stats.failed == 1
    assert plan.stats.will_execute == 0
    assert "## 失败项 (1)" in render_markdown(plan)


def test_report_states_the_bytes_accounting_rule(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.jpg").write_bytes(b"x")

    report = render_markdown(build_plan(make_request(root)))

    assert "字节变化口径" in report
    assert "move/rename 未计入" in report
