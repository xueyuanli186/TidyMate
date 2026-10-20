"""Coverage for the remaining M7-M9 branches: dry-run undo, verify codes, CLI reports."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tidymate_cli.main import app
from tidymate_core.execution import Executor, Undoer, verify_batch, write_reports
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
"""


def plan_for(root: Path, out: Path) -> Plan:
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


def seed(tmp_path: Path) -> tuple[Path, Path]:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "a.txt").write_text("x", encoding="utf-8")
    return inbox, tmp_path / "out"


def test_undo_dry_run_changes_nothing(tmp_path: Path) -> None:
    inbox, out = seed(tmp_path)
    with Journal(tmp_path / "j.db") as journal:
        plan = plan_for(inbox, out)
        journal.record_preview(plan)
        Executor(journal).run(plan)
        report = Undoer(journal).run(plan.batch_id, dry_run=True)
        assert [o.state for o in report.outcomes] == ["would_undo"]
        assert (out / "Text" / "a.txt").exists()
        assert not (inbox / "a.txt").exists()
        assert journal.batch_status(plan.batch_id) == "applied"


def test_verify_reports_size_mismatch(tmp_path: Path) -> None:
    inbox, out = seed(tmp_path)
    with Journal(tmp_path / "j.db") as journal:
        plan = plan_for(inbox, out)
        journal.record_preview(plan)
        Executor(journal).run(plan)
        (out / "Text" / "a.txt").write_text("a much longer replacement", encoding="utf-8")
        problems = verify_batch(journal, plan.batch_id)
        assert any(problem.code == "size_mismatch" for problem in problems)


def test_verify_reports_interrupted(tmp_path: Path) -> None:
    inbox, out = seed(tmp_path)
    with Journal(tmp_path / "j.db") as journal:
        plan = plan_for(inbox, out)
        journal.record_preview(plan)
        journal.intent(plan.batch_id, 1, plan.changes[0])
        problems = verify_batch(journal, plan.batch_id)
        assert any(problem.code == "interrupted" for problem in problems)


def test_unknown_error_gets_a_banner(tmp_path: Path) -> None:
    inbox, out = seed(tmp_path)
    with Journal(tmp_path / "j.db") as journal:
        plan = plan_for(inbox, out)
        journal.record_preview(plan)
        journal.intent(plan.batch_id, 1, plan.changes[0])
        journal.finish(
            plan.batch_id,
            1,
            "failed",
            error="mystery",
            error_kind="unknown",
        )
        paths = write_reports(journal, plan.batch_id, tmp_path / "reports")
        markdown = paths.markdown.read_text(encoding="utf-8")
        payload = json.loads(paths.json.read_text(encoding="utf-8"))
        assert "未分类错误" in markdown
        assert payload["unknown_present"] is True


def test_cli_list_show_and_verify(tmp_path: Path) -> None:
    inbox, out = seed(tmp_path)
    db = tmp_path / "j.db"
    rules = tmp_path / "rules.yaml"
    rules.write_text(RULES, encoding="utf-8")
    runner = CliRunner()
    preview = runner.invoke(
        app,
        ["plan", str(inbox), "-r", str(rules), "-o", str(out), "--db", str(db), "--yes"],
    )
    batch = next(word.split("batch=")[1] for word in preview.output.split() if "batch=" in word)
    runner.invoke(app, ["apply", batch, "--db", str(db), "--yes"], input="YES\n")

    listed = runner.invoke(app, ["list-batches", "--db", str(db)])
    assert batch in listed.output
    shown = runner.invoke(app, ["show-batch", batch, "--db", str(db), "--json"])
    assert shown.exit_code == 0
    assert json.loads(shown.stdout)["summary"]["ok"] == 1
    verified = runner.invoke(app, ["verify", batch, "--db", str(db)])
    assert verified.exit_code == 0, verified.output
    assert "0 inconsistency" in verified.output


def test_cli_undo_dry_run_and_plain_show(tmp_path: Path) -> None:
    inbox, out = seed(tmp_path)
    db = tmp_path / "j.db"
    rules = tmp_path / "rules.yaml"
    rules.write_text(RULES, encoding="utf-8")
    runner = CliRunner()
    preview = runner.invoke(
        app, ["plan", str(inbox), "-r", str(rules), "-o", str(out), "--db", str(db), "--yes"]
    )
    batch = next(w.split("batch=")[1] for w in preview.output.split() if "batch=" in w)
    runner.invoke(app, ["apply", batch, "--db", str(db), "--yes"], input="YES\n")

    dry = runner.invoke(app, ["undo", batch, "--db", str(db), "--dry-run"])
    assert dry.exit_code == 0
    assert "将回滚 1 条" in dry.output
    assert (out / "Text" / "a.txt").exists(), "dry-run must not move anything"

    shown = runner.invoke(app, ["show-batch", batch, "--db", str(db)])
    assert shown.exit_code == 0
    assert "summary" in shown.output


def test_status_reports_the_latest_batch(tmp_path: Path) -> None:
    inbox, out = seed(tmp_path)
    db = tmp_path / "j.db"
    rules = tmp_path / "rules.yaml"
    rules.write_text(RULES, encoding="utf-8")
    runner = CliRunner()
    runner.invoke(
        app, ["plan", str(inbox), "-r", str(rules), "-o", str(out), "--db", str(db), "--yes"]
    )
    result = runner.invoke(app, ["status", "--db", str(db)])
    assert result.exit_code == 0
    assert "latest batch" in result.output
    assert "previewed" in result.output


def test_journal_migrates_an_old_database(tmp_path: Path) -> None:
    import sqlite3

    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE batches (
            batch_id TEXT PRIMARY KEY, plan_hash TEXT, created_at TEXT,
            output_root TEXT, rules_source TEXT, status TEXT,
            applied_at TEXT, finished_at TEXT, options_json TEXT, plan_json TEXT
        );
        CREATE TABLE operations (
            batch_id TEXT, seq INTEGER, op TEXT, src TEXT, dst TEXT,
            state TEXT, error TEXT, error_kind TEXT, size INTEGER,
            cross_volume INTEGER, created_at TEXT, updated_at TEXT,
            PRIMARY KEY (batch_id, seq)
        );
        INSERT INTO batches VALUES ('old-1', 'h', '2026-01-01', 'C:/out', 'r.yaml',
                                    'applied', NULL, NULL, NULL, '{}');
        """,
    )
    conn.commit()
    conn.close()

    with Journal(db) as journal:
        row = journal.batch_row("old-1")
        assert row is not None
        assert row["mode"] == "dryrun"
        assert row["undo_total"] == 0
        assert journal.agg_stats("old-1")["total"] == 0


def test_undo_cross_volume_copy_path(tmp_path: Path) -> None:
    dst = tmp_path / "out" / "a.txt"
    dst.parent.mkdir(parents=True)
    dst.write_text("payload", encoding="utf-8")
    src = tmp_path / "inbox" / "a.txt"
    src.parent.mkdir(parents=True)
    with Journal(tmp_path / "j.db") as journal:
        undoer = Undoer(journal)
        undoer._move_back_across_volumes(str(dst), str(src))
    assert src.read_text(encoding="utf-8") == "payload"
    assert not dst.exists()


def test_verify_rolls_up_undo_failed_and_missing(tmp_path: Path) -> None:
    inbox, out = seed(tmp_path)
    with Journal(tmp_path / "j.db") as journal:
        plan = plan_for(inbox, out)
        journal.record_preview(plan)
        Executor(journal).run(plan)
        (out / "Text" / "a.txt").unlink()
        journal.finish(plan.batch_id, 1, "undo_failed", error="x", error_kind="missing")
        problems = verify_batch(journal, plan.batch_id)
        assert [problem.code for problem in problems] == ["undo_failed_and_missing"]


def test_undo_unknown_operation_is_reported(tmp_path: Path) -> None:
    inbox, out = seed(tmp_path)
    with Journal(tmp_path / "j.db") as journal:
        plan = plan_for(inbox, out)
        journal.record_preview(plan)
        journal.intent(plan.batch_id, 1, plan.changes[0])
        journal.finish(plan.batch_id, 1, "ok")
        journal._conn.execute(
            "UPDATE operations SET op = 'teleport' WHERE batch_id = ?", (plan.batch_id,)
        )
        journal._conn.commit()
        report = Undoer(journal).run(plan.batch_id)
        assert report.failed == 1
        assert report.outcomes[0].error_kind == "unknown"


def test_start_undo_on_unknown_batch_raises(tmp_path: Path) -> None:
    from tidymate_core.journal import JournalError

    with Journal(tmp_path / "j.db") as journal:
        try:
            journal.start_undo("nope")
        except JournalError:
            pass
        else:  # pragma: no cover - the assertion below documents the failure
            raise AssertionError("start_undo should refuse an unknown batch")


def test_cli_verify_json_and_unknown_undo(tmp_path: Path) -> None:
    inbox, out = seed(tmp_path)
    db = tmp_path / "j.db"
    rules = tmp_path / "rules.yaml"
    rules.write_text(RULES, encoding="utf-8")
    runner = CliRunner()
    preview = runner.invoke(
        app, ["plan", str(inbox), "-r", str(rules), "-o", str(out), "--db", str(db), "--yes"]
    )
    batch = next(w.split("batch=")[1] for w in preview.output.split() if "batch=" in w)
    runner.invoke(app, ["apply", batch, "--db", str(db), "--yes"], input="YES\n")
    result = runner.invoke(app, ["verify", batch, "--db", str(db), "--json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == []
    missing = runner.invoke(app, ["undo", "does-not-exist", "--db", str(db), "--yes"])
    assert missing.exit_code == 2


def test_gate_rejects_an_installer_target_directory(tmp_path: Path) -> None:
    from tidymate_core.execution import evaluate
    from tidymate_core.execution.models import ExecutionOptions

    inbox, out = seed(tmp_path)
    (out / "Text").mkdir(parents=True)
    (out / "Text" / "unins000.exe").write_bytes(b"x")
    with Journal(tmp_path / "j.db") as journal:
        plan = plan_for(inbox, out)
        journal.record_preview(plan)
        gate = evaluate(plan, journal, ExecutionOptions())
        assert "installer_dir" in {problem.code for problem in gate.problems}


def test_cli_list_batches_on_an_empty_database(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["list-batches", "--db", str(tmp_path / "empty.db")])
    assert result.exit_code == 0
    assert "还没有任何批次" in result.output


def test_record_preview_refuses_a_started_batch(tmp_path: Path) -> None:
    from tidymate_core.journal import JournalError

    inbox, out = seed(tmp_path)
    with Journal(tmp_path / "j.db") as journal:
        plan = plan_for(inbox, out)
        journal.record_preview(plan)
        journal.mark_finished(plan.batch_id, "applied")
        try:
            journal.record_preview(plan)
        except JournalError:
            pass
        else:  # pragma: no cover
            raise AssertionError("a started batch must not be re-previewed")


def test_cli_version_and_bad_rules(tmp_path: Path) -> None:
    from tidymate_core._version import __version__

    runner = CliRunner()
    version = runner.invoke(app, ["--version"])
    assert version.exit_code == 0
    assert __version__ in version.stdout

    inbox, out = seed(tmp_path)
    bad = tmp_path / "bad.yaml"
    bad.write_text("rules: [oops", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "plan",
            str(inbox),
            "-r",
            str(bad),
            "-o",
            str(out),
            "--db",
            str(tmp_path / "j.db"),
            "--yes",
        ],
    )
    assert result.exit_code == 2


def test_cli_plan_can_export_artifacts(tmp_path: Path) -> None:
    inbox, out = seed(tmp_path)
    rules = tmp_path / "rules.yaml"
    rules.write_text(RULES, encoding="utf-8")
    report_dir = tmp_path / "reports"
    result = CliRunner().invoke(
        app,
        [
            "plan",
            str(inbox),
            "-r",
            str(rules),
            "-o",
            str(out),
            "--db",
            str(tmp_path / "j.db"),
            "--export",
            str(report_dir),
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.output
    assert (report_dir / "plan.json").exists()


def test_cli_undo_reports_a_failed_restore(tmp_path: Path) -> None:
    inbox, out = seed(tmp_path)
    db = tmp_path / "j.db"
    rules = tmp_path / "rules.yaml"
    rules.write_text(RULES, encoding="utf-8")
    runner = CliRunner()
    preview = runner.invoke(
        app, ["plan", str(inbox), "-r", str(rules), "-o", str(out), "--db", str(db), "--yes"]
    )
    batch = next(w.split("batch=")[1] for w in preview.output.split() if "batch=" in w)
    runner.invoke(app, ["apply", batch, "--db", str(db), "--yes"], input="YES\n")
    (out / "Text" / "a.txt").write_text("edited after apply", encoding="utf-8")

    result = runner.invoke(app, ["undo", batch, "--db", str(db), "--yes"])

    assert result.exit_code == 1
    assert "modified_since" in result.output
    assert (out / "Text" / "a.txt").exists()


def test_cli_show_batch_unknown(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["show-batch", "nope", "--db", str(tmp_path / "j.db")])
    assert result.exit_code == 2


def test_verify_sample_limits_the_check(tmp_path: Path) -> None:
    inbox, out = seed(tmp_path)
    db = tmp_path / "j.db"
    rules = tmp_path / "rules.yaml"
    rules.write_text(RULES, encoding="utf-8")
    runner = CliRunner()
    preview = runner.invoke(
        app, ["plan", str(inbox), "-r", str(rules), "-o", str(out), "--db", str(db), "--yes"]
    )
    batch = next(word.split("batch=")[1] for word in preview.output.split() if "batch=" in word)
    runner.invoke(app, ["apply", batch, "--db", str(db), "--yes"], input="YES\n")
    result = runner.invoke(app, ["verify", batch, "--db", str(db), "--sample", "1"])
    assert result.exit_code == 0
    assert "0 inconsistency" in result.output


def test_rows_without_a_destination_are_reported(tmp_path: Path) -> None:
    inbox, out = seed(tmp_path)
    with Journal(tmp_path / "j.db") as journal:
        plan = plan_for(inbox, out)
        journal.record_preview(plan)
        Executor(journal).run(plan)
        journal._conn.execute(
            "UPDATE operations SET dst = NULL, final_dst = NULL WHERE batch_id = ?",
            (plan.batch_id,),
        )
        journal._conn.commit()
        codes = [problem.code for problem in verify_batch(journal, plan.batch_id)]
        assert "no_destination" in codes
        report = Undoer(journal).run(plan.batch_id)
        assert report.outcomes[0].error_kind == "missing"


def test_recycle_reference_records_the_original_path() -> None:
    from tidymate_core.execution.recycle import recycle_reference

    payload = json.loads(recycle_reference(r"C:\Users\someone\中文 文件.txt"))
    assert payload["name"] == "中文 文件.txt"
    assert payload["parent"] == r"C:\Users\someone"


def test_trash_undo_tolerates_a_broken_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "x.tmp").write_bytes(b"junk")
    rules_text = """
rules:
  - id: junk
    when: { ext: [".tmp"] }
    action: { op: trash }
"""
    with Journal(tmp_path / "j.db") as journal:
        plan = build_plan(
            PlanRequest(
                scan=ScanConfig(roots=(str(inbox),)),
                rules=load_rules_from_text(rules_text),
                output_root=str(tmp_path / "out"),
                created_at=NOW,
                local_tz=UTC,
                now=NOW,
            ),
        )
        journal.record_preview(plan)
        Executor(journal).run(plan)
        journal._conn.execute(  # corrupt the reference on purpose
            "UPDATE operations SET recycle_ref = 'not-json' WHERE batch_id = ?",
            (plan.batch_id,),
        )
        journal._conn.commit()
        monkeypatch.setattr(
            "tidymate_core.execution.undo.restore_to",
            lambda _path: (True, "restored"),
        )
        report = Undoer(journal).run(plan.batch_id)
        assert report.failed == 0
