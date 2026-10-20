"""Stage 5-6 tests: journal, gate and executor against real temporary directories.

Every test works inside ``tmp_path``; none of them may touch a user directory. The
assertions deliberately check the file system, not the journal's own claim of success.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tidymate_core.execution import ExecutionOptions, Executor, evaluate
from tidymate_core.execution.executor import Executor as ExecutorClass
from tidymate_core.journal import BatchAlreadyAppliedError, Journal
from tidymate_core.planning.models import (
    ChangeStatus,
    ConflictType,
    Plan,
    PlannedChange,
    PlanStats,
    RejectReason,
)
from tidymate_core.planning.planner import compute_plan_hash
from tidymate_core.scanning.cancel import CancelToken

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


def make_plan(
    tmp_path: Path,
    changes: list[PlannedChange],
    *,
    batch: str = "dryrun-test-0001",
) -> Plan:
    """Build a plan by hand so a test can describe exactly one risky operation."""
    output_root = str(tmp_path / "out")
    stats = PlanStats(
        total_scanned=len(changes),
        matched=len(changes),
        will_execute=sum(1 for c in changes if c.is_executable),
        will_skip=sum(1 for c in changes if c.status is ChangeStatus.SKIP),
        rejected=sum(1 for c in changes if c.status is ChangeStatus.REJECT),
        failed=sum(1 for c in changes if c.status is ChangeStatus.FAILED),
        conflicts=0,
        conflicts_exists=0,
        conflicts_intra=0,
        conflicts_review=0,
        bytes_freed=0,
        bytes_added=0,
    )
    return Plan(
        batch_id=batch,
        created_at=NOW,
        output_root=output_root,
        rules_source="rules.yaml",
        changes=tuple(changes),
        stats=stats,
        plan_hash=compute_plan_hash(tuple(changes), stats),
    )


def change(
    seq: int,
    src: Path,
    dst: Path | None,
    op: str,
    *,
    status: ChangeStatus = ChangeStatus.EXECUTE,
    conflict: ConflictType = ConflictType.NONE,
    reason: RejectReason | None = None,
    size: int = 0,
) -> PlannedChange:
    return PlannedChange(
        seq=seq,
        src=str(src),
        dst=None if dst is None else str(dst),
        op=op,
        rule_id="test",
        status=status,
        conflict=conflict,
        reason=reason,
        size=size,
    )


@pytest.fixture
def journal(tmp_path: Path) -> Iterator[Journal]:
    with Journal(tmp_path / "journal.db") as opened:
        yield opened


def test_move_writes_intent_then_ok(tmp_path: Path, journal: Journal) -> None:
    src = tmp_path / "a.jpg"
    src.write_bytes(b"x" * 8)
    dst = tmp_path / "out" / "a.jpg"
    plan = make_plan(tmp_path, [change(1, src, dst, "move")])
    journal.record_preview(plan)

    report = Executor(journal).run(plan)

    assert report.counts["ok"] == 1
    assert dst.read_bytes() == b"x" * 8
    assert not src.exists()
    rows = journal.operations(plan.batch_id)
    assert rows[0]["state"] == "ok"
    assert rows[0]["final_dst"] == str(dst)


def test_rename_stays_in_the_same_directory(tmp_path: Path, journal: Journal) -> None:
    src = tmp_path / "old.jpg"
    src.write_bytes(b"x")
    dst = tmp_path / "new.jpg"
    plan = make_plan(tmp_path, [change(1, src, dst, "rename")])
    journal.record_preview(plan)

    Executor(journal).run(plan)

    assert dst.exists()
    assert not src.exists()


def test_copy_keeps_the_source_and_the_mtime(tmp_path: Path, journal: Journal) -> None:
    src = tmp_path / "a.bin"
    src.write_bytes(b"payload")
    old = 1_600_000_000
    os.utime(src, (old, old))
    dst = tmp_path / "out" / "a.bin"
    plan = make_plan(tmp_path, [change(1, src, dst, "copy")])
    journal.record_preview(plan)

    Executor(journal).run(plan)

    assert src.exists(), "copy must never touch the source"
    assert dst.read_bytes() == b"payload"
    assert int(dst.stat().st_mtime) == old


@pytest.mark.skipif(sys.platform != "win32", reason="recycle bin is Windows-only")
def test_trash_goes_to_the_recycle_bin(tmp_path: Path, journal: Journal) -> None:
    src = tmp_path / "junk.tmp"
    src.write_bytes(b"x")
    plan = make_plan(tmp_path, [change(1, src, None, "trash")])
    journal.record_preview(plan)

    Executor(journal).run(plan)

    assert not src.exists()


def test_executor_refuses_to_overwrite_an_existing_destination(
    tmp_path: Path,
    journal: Journal,
) -> None:
    src = tmp_path / "a.jpg"
    src.write_bytes(b"new")
    dst = tmp_path / "out" / "a.jpg"
    dst.parent.mkdir(parents=True)
    dst.write_bytes(b"old")
    plan = make_plan(tmp_path, [change(1, src, dst, "move")])
    journal.record_preview(plan)

    report = Executor(journal).run(plan)

    assert report.counts["failed"] == 1
    assert dst.read_bytes() == b"old", "existing content must survive"
    assert src.exists(), "the source must not be lost on a refused move"


def test_repeated_apply_of_the_same_batch_is_rejected(
    tmp_path: Path,
    journal: Journal,
) -> None:
    src = tmp_path / "a.jpg"
    src.write_bytes(b"x")
    plan = make_plan(tmp_path, [change(1, src, tmp_path / "out" / "a.jpg", "move")])
    journal.record_preview(plan)
    Executor(journal).run(plan)

    with pytest.raises(BatchAlreadyAppliedError):
        Executor(journal).run(plan)


def test_completed_operations_are_skipped_on_rerun(tmp_path: Path, journal: Journal) -> None:
    first = tmp_path / "a.jpg"
    first.write_bytes(b"a")
    second = tmp_path / "b.jpg"
    second.write_bytes(b"b")
    plan = make_plan(
        tmp_path,
        [
            change(1, first, tmp_path / "out" / "a.jpg", "move"),
            change(2, second, tmp_path / "out" / "b.jpg", "move"),
        ],
    )
    journal.record_preview(plan)
    # Pretend the first operation finished and the process died.
    journal.intent(plan.batch_id, 1, plan.changes[0])
    journal.finish(plan.batch_id, 1, "ok", final_dst=str(tmp_path / "out" / "a.jpg"))
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "a.jpg").write_bytes(b"a")
    first.unlink()

    report = Executor(journal).run(plan)

    assert report.counts["skipped"] == 1
    assert report.counts["ok"] == 1
    assert (tmp_path / "out" / "b.jpg").exists()


def test_gate_rejects_a_batch_without_a_preview(tmp_path: Path, journal: Journal) -> None:
    src = tmp_path / "a.jpg"
    src.write_bytes(b"x")
    plan = make_plan(tmp_path, [change(1, src, tmp_path / "out" / "a.jpg", "move")])

    result = evaluate(plan, journal)

    assert not result.ok
    assert {problem.code for problem in result.problems} == {"no_preview"}


def test_gate_rejects_a_changed_plan(tmp_path: Path, journal: Journal) -> None:
    src = tmp_path / "a.jpg"
    src.write_bytes(b"x")
    plan = make_plan(tmp_path, [change(1, src, tmp_path / "out" / "a.jpg", "move")])
    journal.record_preview(plan)
    tampered = make_plan(
        tmp_path,
        [change(1, src, tmp_path / "out" / "elsewhere.jpg", "move")],
        batch=plan.batch_id,
    )

    result = evaluate(tampered, journal)

    assert not result.ok
    assert "plan_changed" in {problem.code for problem in result.problems}


def test_gate_rejects_a_blacklisted_path(tmp_path: Path, journal: Journal) -> None:
    src = tmp_path / "a.jpg"
    src.write_bytes(b"x")
    windows = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "Temp" / "x.jpg"
    plan = make_plan(tmp_path, [change(1, src, windows, "move")])
    journal.record_preview(plan)

    result = evaluate(plan, journal)

    assert not result.ok
    assert "blacklist" in {problem.code for problem in result.problems}


def test_gate_rejects_an_ancestor_target(tmp_path: Path, journal: Journal) -> None:
    src = tmp_path / "a"
    src.mkdir()
    plan = make_plan(tmp_path, [change(1, src, src / "nested" / "a", "move")])
    journal.record_preview(plan)

    result = evaluate(plan, journal)

    assert not result.ok
    assert "ancestor" in {problem.code for problem in result.problems}


def test_cross_volume_move_copies_then_recycles(
    tmp_path: Path,
    journal: Journal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    src = tmp_path / "big.bin"
    src.write_bytes(b"z" * 4096)
    dst = tmp_path / "out" / "big.bin"
    plan = make_plan(tmp_path, [change(1, src, dst, "move")])
    journal.record_preview(plan)
    monkeypatch.setattr(ExecutorClass, "_cross_volume", lambda *_: True)

    report = Executor(journal).run(plan)

    assert report.counts["ok"] == 1
    assert dst.read_bytes() == b"z" * 4096
    assert not src.exists()
    assert not list(dst.parent.glob("*.tidymate-partial"))


def test_fuse_stops_after_consecutive_failures(tmp_path: Path, journal: Journal) -> None:
    changes = []
    for index in range(6):
        missing = tmp_path / f"missing-{index}.jpg"
        changes.append(change(index + 1, missing, tmp_path / "out" / f"{index}.jpg", "move"))
    plan = make_plan(tmp_path, changes)
    journal.record_preview(plan)

    report = Executor(journal, ExecutionOptions(fuse_after=3)).run(plan)

    assert report.fused is True
    assert len(report.outcomes) == 3


def test_cancel_stops_between_operations(tmp_path: Path, journal: Journal) -> None:
    changes = []
    for index in range(3):
        src = tmp_path / f"f{index}.jpg"
        src.write_bytes(b"x")
        changes.append(change(index + 1, src, tmp_path / "out" / f"f{index}.jpg", "move"))
    plan = make_plan(tmp_path, changes)
    journal.record_preview(plan)
    token = CancelToken()

    def on_event(_change: PlannedChange, _outcome: object) -> None:
        token.cancel()

    report = Executor(journal, ExecutionOptions(), cancel=token, on_event=on_event).run(plan)

    assert report.cancelled is True
    assert report.counts["ok"] == 1


def test_limit_and_only_rule(tmp_path: Path, journal: Journal) -> None:
    srcs = []
    for index in range(3):
        src = tmp_path / f"l{index}.jpg"
        src.write_bytes(b"x")
        srcs.append(src)
    plan = make_plan(
        tmp_path,
        [
            change(index + 1, src, tmp_path / "out" / src.name, "move")
            for index, src in enumerate(srcs)
        ],
    )
    journal.record_preview(plan)

    report = Executor(journal, ExecutionOptions(limit=2)).run(plan)

    assert report.counts["ok"] == 2
    assert srcs[2].exists()


# --------------------------------------------------------------------------- blacklist
@pytest.mark.parametrize(
    ("raw", "needle"),
    [
        (r"C:\Windows\System32\drivers\etc\hosts", "Windows"),
        (r"C:\Program Files\Something\app.exe", "Program Files"),
        (r"C:\ProgramData\Microsoft\Windows\Start Menu", "ProgramData"),
        (r"C:\$Recycle.Bin\S-1-5-21", "Recycle Bin"),
        (r"C:\Boot\BCD", "Boot"),
        ("C:\\", "drive root"),
        (str(Path.home()), "user profile"),
    ],
)
def test_blacklist_categories(raw: str, needle: str) -> None:
    from tidymate_core.safety import blacklist

    hit = blacklist.check_blacklisted(raw)
    assert hit is not None, f"{raw} should be protected"
    assert needle.lower() in hit.lower()


def test_unc_paths_are_refused_by_default() -> None:
    from tidymate_core.safety import blacklist

    unc = chr(92) * 2 + "server" + chr(92) + "share" + chr(92) + "file.txt"
    assert blacklist.check_unc(unc) is not None
    assert blacklist.check_unc(r"C:\Users\me\file.txt") is None


def test_installer_directory_is_detected(tmp_path: Path) -> None:
    from tidymate_core.safety import blacklist

    (tmp_path / "unins000.exe").write_bytes(b"x")
    assert blacklist.check_installer_directory(str(tmp_path)) is not None
    other = tmp_path / "data"
    other.mkdir()
    assert blacklist.check_installer_directory(str(other)) is None


# ------------------------------------------------------------------------ crash safety
def test_recover_marks_unfinished_intent_as_interrupted(tmp_path: Path, journal: Journal) -> None:
    src = tmp_path / "a.jpg"
    src.write_bytes(b"x")
    plan = make_plan(tmp_path, [change(1, src, tmp_path / "out" / "a.jpg", "move")])
    journal.record_preview(plan)
    journal.intent(plan.batch_id, 1, plan.changes[0])

    recovered = journal.recover(plan.batch_id)

    assert recovered == 1
    assert journal.operations(plan.batch_id)[0]["state"] == "interrupted"
    assert src.exists(), "recover must not guess that the file moved"


def test_gate_rejects_when_the_copy_would_not_fit(
    tmp_path: Path,
    journal: Journal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    src = tmp_path / "big.bin"
    src.write_bytes(b"x" * 100)
    plan = make_plan(tmp_path, [change(1, src, tmp_path / "out" / "big.bin", "copy", size=10_000)])
    journal.record_preview(plan)
    monkeypatch.setattr(
        "tidymate_core.execution.gate.shutil.disk_usage",
        lambda _path: __import__("collections").namedtuple("usage", "total used free")(1, 0, 1),
    )

    result = evaluate(plan, journal)

    assert "disk_space" in {problem.code for problem in result.problems}


def test_journal_metadata_helpers(tmp_path: Path, journal: Journal) -> None:
    src = tmp_path / "a.jpg"
    src.write_bytes(b"x")
    plan = make_plan(tmp_path, [change(1, src, tmp_path / "out" / "a.jpg", "move")])
    journal.record_preview(plan)

    assert journal.has_any_batch() is True
    assert journal.latest_batch() == plan.batch_id
    assert journal.batch_status(plan.batch_id) == "previewed"
    journal.intent(plan.batch_id, 1, plan.changes[0])
    journal.finish(plan.batch_id, 1, "ok")
    assert journal.counts(plan.batch_id) == {"ok": 1}
    assert journal.completed_seqs(plan.batch_id) == {1}
