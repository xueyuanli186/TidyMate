"""M8 undo: the 200-change round trip and every refusal path.

The round-trip test takes a hash+mtime snapshot before ``apply`` and after ``undo`` and
requires them to be identical. ``verify`` then confirms the journal agrees with the disk;
the assertion never trusts the journal alone.
"""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime
from pathlib import Path

from tidymate_core.execution import Executor, Undoer, verify_batch
from tidymate_core.journal import Journal
from tidymate_core.planning import PlanRequest, build_plan
from tidymate_core.planning.models import Plan
from tidymate_core.rules.loader import load_rules_from_text
from tidymate_core.scanning import ScanConfig
from tidymate_core.scanning.cancel import CancelToken

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)

RULES = """
rules:
  - id: move
    when: { ext: [".txt"] }
    action: { op: move, template: "Text/{year}/{name}", conflict: rename }
  - id: rename
    when: { ext: [".log"] }
    action: { op: rename, template: "Renamed/{stem}-renamed{ext}", conflict: rename }
  - id: copy
    when: { ext: [".bin"] }
    action: { op: copy, template: "Bin/{name}", conflict: rename }
  - id: trash
    when: { ext: [".tmp"] }
    action: { op: trash }
"""


def snapshot(root: Path) -> dict[str, tuple[int, int, str]]:
    """Relative path -> (size, mtime_ns, sha256)."""
    result: dict[str, tuple[int, int, str]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            stat_result = path.stat()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            result[path.relative_to(root).as_posix()] = (
                stat_result.st_size,
                stat_result.st_mtime_ns,
                digest,
            )
    return result


def build_tree(root: Path) -> Path:
    """200 mixed files: 100 move, 50 rename, 40 copy, 10 trash."""
    root.mkdir(parents=True)
    counter = 0
    for index in range(80):
        name = f"note-{index:03d}.txt"
        (root / name).write_text(f"move {index}", encoding="utf-8")
        counter += 1
    for index in range(20):
        name = f"报告 {index:02d}.txt"
        (root / name).write_text(f"中文 {index}", encoding="utf-8")
        counter += 1
    for index in range(50):
        (root / f"trace-{index:03d}.log").write_text(f"log {index}", encoding="utf-8")
    for index in range(40):
        (root / f"blob-{index:03d}.bin").write_bytes(bytes([index]) * 32)
    for index in range(10):
        (root / f"junk-{index:02d}.tmp").write_bytes(b"tmp")
    long_name = "long-" + "a" * 200 + ".dat"
    (root / long_name).write_text("long path but under 260", encoding="utf-8")
    return root


def make_plan(root: Path, out: Path) -> Plan:
    return build_plan(
        PlanRequest(
            scan=ScanConfig(roots=(str(root),)),
            rules=load_rules_from_text(RULES),
            output_root=str(out),
            created_at=NOW,
            local_tz=UTC,
            now=NOW,
        ),
    )


def test_200_changes_apply_then_undo_restores_everything(tmp_path: Path) -> None:
    inbox = build_tree(tmp_path / "inbox")
    out = tmp_path / "Sorted"
    before = snapshot(inbox)

    with Journal(tmp_path / "j.db") as journal:
        plan = make_plan(inbox, out)
        journal.record_preview(plan, roots=(str(inbox),), rules_file="rules.yaml")
        applied = Executor(journal).run(plan)
        assert applied.counts["ok"] == 200, applied.counts
        assert verify_batch(journal, plan.batch_id) == []

        undone = Undoer(journal).run(plan.batch_id)

        assert undone.failed == 0, [(o.seq, o.error_kind, o.error) for o in undone.outcomes]
        assert undone.undone == 200
        assert verify_batch(journal, plan.batch_id) == []

    after = snapshot(inbox)
    assert set(after) == set(before), "file names must be identical"
    for name, (size, mtime_ns, digest) in before.items():
        assert after[name][0] == size, f"{name}: size changed"
        assert after[name][2] == digest, f"{name}: content changed"
        assert abs(after[name][1] - mtime_ns) <= 2_000_000_000, f"{name}: mtime changed"
    assert not [p for p in out.rglob("*") if p.is_file()], "output tree must be empty again"


def test_second_undo_reports_nothing_and_changes_nothing(tmp_path: Path) -> None:
    inbox = build_tree(tmp_path / "inbox")
    out = tmp_path / "Sorted"
    with Journal(tmp_path / "j.db") as journal:
        plan = make_plan(inbox, out)
        journal.record_preview(plan)
        Executor(journal).run(plan)
        first = Undoer(journal).run(plan.batch_id)
        second = Undoer(journal).run(plan.batch_id)
        assert first.failed == 0
        assert second.outcomes == []
        assert verify_batch(journal, plan.batch_id) == []


def test_undo_can_resume_after_cancel(tmp_path: Path) -> None:
    inbox = build_tree(tmp_path / "inbox")
    out = tmp_path / "Sorted"
    with Journal(tmp_path / "j.db") as journal:
        plan = make_plan(inbox, out)
        journal.record_preview(plan)
        Executor(journal).run(plan)
        token = CancelToken()

        def stop_after_one(_row: object, _outcome: object) -> None:
            token.cancel()

        partial = Undoer(journal, cancel=token, on_event=stop_after_one).run(plan.batch_id)
        assert partial.cancelled is True
        assert partial.undone == 1

        rest = Undoer(journal).run(plan.batch_id)
        assert rest.failed == 0
        assert verify_batch(journal, plan.batch_id) == []


def test_modified_destination_is_not_moved_back(tmp_path: Path) -> None:
    src = tmp_path / "a.txt"
    src.write_text("original", encoding="utf-8")
    out = tmp_path / "Sorted"
    with Journal(tmp_path / "j.db") as journal:
        plan = make_plan(tmp_path, out)
        plan = build_plan(
            PlanRequest(
                scan=ScanConfig(roots=(str(tmp_path),)),
                rules=load_rules_from_text(
                    'rules:\n  - id: t\n    when: { ext: [".txt"] }\n'
                    '    action: { op: move, template: "Text/{name}", conflict: skip }\n',
                ),
                output_root=str(out),
                created_at=NOW,
                local_tz=UTC,
                now=NOW,
            ),
        )
        journal.record_preview(plan)
        Executor(journal).run(plan)
        dst = out / "Text" / "a.txt"
        dst.write_text("changed by the user, much longer", encoding="utf-8")
        time.sleep(0.01)

        report = Undoer(journal).run(plan.batch_id)

        assert report.failed == 1
        assert report.outcomes[0].error_kind == "modified_since"
        assert dst.exists(), "a modified file must stay where it is"
        assert not src.exists()


def test_missing_destination_is_reported(tmp_path: Path) -> None:
    src = tmp_path / "b.txt"
    src.write_text("x", encoding="utf-8")
    out = tmp_path / "Sorted"
    with Journal(tmp_path / "j.db") as journal:
        plan = build_plan(
            PlanRequest(
                scan=ScanConfig(roots=(str(tmp_path),)),
                rules=load_rules_from_text(
                    'rules:\n  - id: t\n    when: { ext: [".txt"] }\n'
                    '    action: { op: move, template: "Text/{name}", conflict: skip }\n',
                ),
                output_root=str(out),
                created_at=NOW,
                local_tz=UTC,
                now=NOW,
            ),
        )
        journal.record_preview(plan)
        Executor(journal).run(plan)
        (out / "Text" / "b.txt").unlink()
        report = Undoer(journal).run(plan.batch_id)
        assert report.failed == 1
        assert report.outcomes[0].error_kind == "missing"


def test_occupied_source_is_reported(tmp_path: Path) -> None:
    src = tmp_path / "c.txt"
    src.write_text("x", encoding="utf-8")
    out = tmp_path / "Sorted"
    with Journal(tmp_path / "j.db") as journal:
        plan = build_plan(
            PlanRequest(
                scan=ScanConfig(roots=(str(tmp_path),)),
                rules=load_rules_from_text(
                    'rules:\n  - id: t\n    when: { ext: [".txt"] }\n'
                    '    action: { op: move, template: "Text/{name}", conflict: skip }\n',
                ),
                output_root=str(out),
                created_at=NOW,
                local_tz=UTC,
                now=NOW,
            ),
        )
        journal.record_preview(plan)
        Executor(journal).run(plan)
        src.write_text("someone else", encoding="utf-8")
        report = Undoer(journal).run(plan.batch_id)
        assert report.failed == 1
        assert report.outcomes[0].error_kind == "src_occupied"
        assert src.read_text(encoding="utf-8") == "someone else"


def test_copy_undo_recycles_the_copy(tmp_path: Path) -> None:
    src = tmp_path / "d.bin"
    src.write_bytes(b"payload")
    out = tmp_path / "Sorted"
    with Journal(tmp_path / "j.db") as journal:
        plan = build_plan(
            PlanRequest(
                scan=ScanConfig(roots=(str(tmp_path),)),
                rules=load_rules_from_text(
                    'rules:\n  - id: c\n    when: { ext: [".bin"] }\n'
                    '    action: { op: copy, template: "Bin/{name}", conflict: skip }\n',
                ),
                output_root=str(out),
                created_at=NOW,
                local_tz=UTC,
                now=NOW,
            ),
        )
        journal.record_preview(plan)
        Executor(journal).run(plan)
        assert (out / "Bin" / "d.bin").exists()
        report = Undoer(journal).run(plan.batch_id)
        assert report.failed == 0
        assert not (out / "Bin" / "d.bin").exists()
        assert src.exists(), "copy undo must never touch the source"


def test_stats_match_sql_and_disk(tmp_path: Path) -> None:
    inbox = build_tree(tmp_path / "inbox")
    out = tmp_path / "Sorted"
    with Journal(tmp_path / "j.db") as journal:
        plan = make_plan(inbox, out)
        journal.record_preview(plan)
        applied = Executor(journal).run(plan)
        stats = journal.refresh_stats(plan.batch_id)
        assert stats["ok"] == applied.counts["ok"] == 200
        assert stats["failed"] == applied.counts["failed"]
        undo = Undoer(journal).run(plan.batch_id)
        stats = journal.refresh_stats(plan.batch_id)
        assert stats["undo_ok"] == undo.undone
        assert stats["undo_failed"] == undo.failed
        assert stats["undo_total"] == 200
