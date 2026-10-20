"""M8/M9 edge cases: crash recovery, recycle-bin restore, reports, CLI undo."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tidymate_cli.main import app
from tidymate_core.execution import Executor, Undoer, verify_batch, write_reports
from tidymate_core.execution import undo as undo_module
from tidymate_core.journal import Journal
from tidymate_core.planning import PlanRequest, build_plan
from tidymate_core.planning.models import Plan
from tidymate_core.rules.loader import load_rules_from_text
from tidymate_core.scanning import ScanConfig

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)

RULES = """
rules:
  - id: t
    when: { ext: [".txt"] }
    action: { op: move, template: "Text/{name}", conflict: skip }
  - id: junk
    when: { ext: [".tmp"] }
    action: { op: trash }
"""


def make_plan(root: Path, out: Path, rules_text: str = RULES) -> Plan:
    return build_plan(
        PlanRequest(
            scan=ScanConfig(roots=(str(root),)),
            rules=load_rules_from_text(rules_text),
            output_root=str(out),
            created_at=NOW,
            local_tz=UTC,
            now=NOW,
        ),
    )


def test_crash_recovery_marks_interrupted_as_partial(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "a.txt").write_text("x", encoding="utf-8")
    (inbox / "b.txt").write_text("y", encoding="utf-8")
    with Journal(tmp_path / "j.db") as journal:
        plan = make_plan(inbox, tmp_path / "out")
        journal.record_preview(plan)
        # Simulate a crash after the intent of seq 1 and nothing else.
        journal.intent(plan.batch_id, 1, plan.changes[0])
        journal.start_apply(plan.batch_id, {})

        recovered = journal.recover(plan.batch_id)
        journal.mark_finished(plan.batch_id, "partial")
        stats = journal.refresh_stats(plan.batch_id)

        assert recovered == 1
        assert journal.batch_status(plan.batch_id) == "partial"
        assert stats["ok"] == 0, "a planned row must never be counted as done"
        assert journal.completed_seqs(plan.batch_id) == set()
        assert journal.undo_candidates(plan.batch_id) == []
        assert journal.operations(plan.batch_id)[0]["state"] == "interrupted"


@pytest.mark.skipif(sys.platform != "win32", reason="recycle bin is Windows-only")
def test_trash_undo_restores_the_file(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "junk.tmp").write_bytes(b"junk")
    with Journal(tmp_path / "j.db") as journal:
        plan = make_plan(inbox, tmp_path / "out")
        journal.record_preview(plan)
        Executor(journal).run(plan)
        assert not (inbox / "junk.tmp").exists()

        report = Undoer(journal).run(plan.batch_id)

        assert report.failed == 0, [(o.seq, o.error_kind, o.error) for o in report.outcomes]
        assert (inbox / "junk.tmp").exists()
        assert verify_batch(journal, plan.batch_id) == []


def test_recycle_gone_is_reported_without_crashing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "gone.tmp").write_bytes(b"junk")
    monkeypatch.setattr(undo_module, "restore_to", lambda _path: (False, "not_found"))
    with Journal(tmp_path / "j.db") as journal:
        plan = make_plan(inbox, tmp_path / "out")
        journal.record_preview(plan)
        Executor(journal).run(plan)

        report = Undoer(journal).run(plan.batch_id)

        assert report.failed == 1
        assert report.outcomes[0].error_kind == "recycle_gone"
        assert "recycle" in (report.outcomes[0].error or "").lower()


def test_error_report_has_groups_and_sql_numbers(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "ok.txt").write_text("x", encoding="utf-8")
    (inbox / "clash.txt").write_text("new", encoding="utf-8")
    out = tmp_path / "out"
    with Journal(tmp_path / "j.db") as journal:
        plan = make_plan(inbox, out)
        journal.record_preview(plan)
        # The preview saw a free destination; someone creates it before apply runs.
        (out / "Text").mkdir(parents=True)
        (out / "Text" / "clash.txt").write_text("old", encoding="utf-8")
        report = Executor(journal).run(plan)
        assert report.counts["failed"] == 1
        paths = write_reports(journal, plan.batch_id, tmp_path / "reports")
        markdown = paths.markdown.read_text(encoding="utf-8")
        payload = json.loads(paths.json.read_text(encoding="utf-8"))

        assert "## conflict" in markdown
        assert "| ok | 1 |" in markdown
        assert "| failed | 1 |" in markdown
        assert payload["summary"]["ok"] == 1
        assert payload["summary"]["failed"] == 1
        assert "unknown" not in payload["groups"]


def test_cli_undo_round_trip(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "a.txt").write_text("hello", encoding="utf-8")
    db = tmp_path / "j.db"
    rules = tmp_path / "rules.yaml"
    rules.write_text(RULES, encoding="utf-8")
    runner = CliRunner()

    preview = runner.invoke(
        app,
        [
            "plan",
            str(inbox),
            "-r",
            str(rules),
            "-o",
            str(tmp_path / "out"),
            "--db",
            str(db),
            "--yes",
        ],
    )
    assert preview.exit_code == 0, preview.output
    batch = next(word.split("batch=")[1] for word in preview.output.split() if "batch=" in word)
    applied = runner.invoke(app, ["apply", batch, "--db", str(db), "--yes"], input="YES\n")
    assert applied.exit_code == 0, applied.output
    assert not (inbox / "a.txt").exists()

    undone = runner.invoke(app, ["undo", batch, "--db", str(db), "--yes"])

    assert undone.exit_code == 0, undone.output
    assert (inbox / "a.txt").read_text(encoding="utf-8") == "hello"
    assert "undone=1" in undone.output
