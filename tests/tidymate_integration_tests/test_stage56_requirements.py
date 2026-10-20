"""Stage 5-6 requirement coverage that is easier to prove at the edges.

* a reparse point (symlink) is rejected by the planner, not silently walked;
* a >260 character source path is rejected with a reason;
* the blacklist resolves junction targets before deciding;
* a whole sandbox run is verified with a file-system snapshot: the number of ``ok``
  outcomes equals the number of real changes on disk.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from tidymate_core.execution import Executor
from tidymate_core.journal import Journal
from tidymate_core.planning import PlanRequest, build_plan
from tidymate_core.planning.models import ChangeStatus
from tidymate_core.rules.engine import RuleSet
from tidymate_core.rules.loader import load_rules_from_text
from tidymate_core.scanning import ScanConfig
from tidymate_core.scanning.walker import build_entry

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)

RULES = """
rules:
  - id: text
    when: { ext: [".txt"] }
    action: { op: move, template: "Text/{name}", conflict: skip }
  - id: bin
    when: { ext: [".bin"] }
    action: { op: copy, template: "Bin/{name}", conflict: skip }
  - id: junk
    when: { ext: [".tmp"] }
    action: { op: trash }
"""


def ruleset() -> RuleSet:
    return load_rules_from_text(RULES)


def make_request(root: Path, **kwargs: Any) -> PlanRequest:
    return PlanRequest(
        scan=ScanConfig(roots=(str(root),)),
        rules=ruleset(),
        output_root=str(root.parent / "Sorted"),
        created_at=NOW,
        local_tz=UTC,
        now=NOW,
        **kwargs,
    )


def test_symlink_is_rejected_not_followed(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    real = root / "real.txt"
    real.write_text("x", encoding="utf-8")
    link = root / "link.txt"
    try:
        link.symlink_to(real)
    except OSError:
        pytest.skip("creating a symlink needs Developer Mode or elevation")

    plan = build_plan(make_request(root))

    by_name = {Path(change.src).name: change for change in plan.changes}
    assert by_name["link.txt"].status is ChangeStatus.REJECT
    assert "reparse" in " ".join(by_name["link.txt"].notes)


def test_long_source_path_is_rejected(tmp_path: Path) -> None:
    long_name = "a" * 250 + ".txt"
    root = tmp_path / "root"
    root.mkdir()
    fake_stat = SimpleNamespace(st_size=1, st_mtime=NOW.timestamp(), st_file_attributes=0)
    entry = build_entry(str(root), long_name, cast("Any", fake_stat), link_count=1)
    assert entry.path_length > 260

    plan = build_plan(make_request(root, entries=(entry,)))

    assert plan.changes[0].status is ChangeStatus.REJECT
    assert "characters" in plan.changes[0].notes[0]


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are Windows-only")
def test_blacklist_resolves_junction_targets(tmp_path: Path) -> None:
    from tidymate_core.safety import blacklist

    junction = tmp_path / "windows-link"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), os.environ.get("SYSTEMROOT", r"C:\Windows")],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"could not create a junction: {result.stderr or result.stdout}")

    target = junction / "System32" / "drivers" / "etc" / "hosts"
    hit = blacklist.check_blacklisted(str(target))

    assert hit is not None, "a junction into C:\\Windows must be resolved before comparison"


def snapshot(root: Path) -> dict[str, str]:
    """Map relative path -> sha256 for every file under *root*."""
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            result[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def test_ok_count_equals_real_changes(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "a.txt").write_text("a", encoding="utf-8")
    (inbox / "b.txt").write_text("b", encoding="utf-8")
    (inbox / "c.bin").write_bytes(b"copy-me")
    (inbox / "d.tmp").write_bytes(b"junk")
    out = tmp_path / "Sorted"
    before_inbox = snapshot(inbox)

    with Journal(tmp_path / "j.db") as journal:
        plan = build_plan(make_request(inbox))
        journal.record_preview(plan)
        report = Executor(journal).run(plan)

    after_inbox = snapshot(inbox)
    after_out = snapshot(out)
    removed = set(before_inbox) - set(after_inbox)
    added = set(after_out)

    assert report.counts["ok"] == 4
    # move x2 + trash x1 leave the inbox; copy's source stays.
    assert removed == {"a.txt", "b.txt", "d.tmp"}
    # move x2 + copy x1 land in the output tree.
    assert added == {"Text/a.txt", "Text/b.txt", "Bin/c.bin"}
    assert after_out["Bin/c.bin"] == hashlib.sha256(b"copy-me").hexdigest()
    assert "c.bin" in after_inbox
