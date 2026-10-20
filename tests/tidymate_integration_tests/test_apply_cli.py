"""End-to-end CLI tests: preview, gate, apply, and the refusals.

These run the real Typer app against a temporary journal, so they cover the wiring that
unit tests cannot: "did the CLI actually refuse?", "did the exit code say so?".
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tidymate_cli.main import app

RULES = """
rules:
  - id: text
    when: { ext: [".txt"] }
    action: { op: move, template: "Text/{name}", conflict: rename }
  - id: trash
    when: { ext: [".tmp"] }
    action: { op: trash }
"""


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def write_rules(tmp_path: Path) -> Path:
    path = tmp_path / "rules.yaml"
    path.write_text(RULES, encoding="utf-8")
    return path


def test_plan_then_apply_moves_files(
    tmp_path: Path,
    runner: CliRunner,
) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "a.txt").write_text("hello", encoding="utf-8")
    (inbox / "b.tmp").write_text("junk", encoding="utf-8")
    db = tmp_path / "j.db"
    rules = write_rules(tmp_path)

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
    batch = re.search(r"batch=(\S+)", preview.output)
    assert batch is not None

    applied = runner.invoke(
        app,
        ["apply", batch.group(1), "--db", str(db), "--yes"],
        input="YES\n",
    )
    assert applied.exit_code == 0, applied.output
    assert (tmp_path / "out" / "Text" / "a.txt").read_text(encoding="utf-8") == "hello"
    assert not (inbox / "a.txt").exists(), "move must remove the source"
    assert not (inbox / "b.tmp").exists(), "trash must remove the source"


def test_apply_without_preview_is_refused(tmp_path: Path, runner: CliRunner) -> None:
    result = runner.invoke(
        app,
        ["apply", "dryrun-does-not-exist", "--db", str(tmp_path / "j.db"), "--yes"],
    )
    assert result.exit_code == 2


def test_second_apply_of_the_same_batch_is_refused(
    tmp_path: Path,
    runner: CliRunner,
) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "a.txt").write_text("x", encoding="utf-8")
    db = tmp_path / "j.db"
    rules = write_rules(tmp_path)
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
    batch = re.search(r"batch=(\S+)", preview.output).group(1)  # type: ignore[union-attr]

    first = runner.invoke(app, ["apply", batch, "--db", str(db), "--yes"], input="YES\n")
    assert first.exit_code == 0, first.output
    second = runner.invoke(app, ["apply", batch, "--db", str(db), "--yes"], input="YES\n")
    assert second.exit_code == 4, second.output


def test_first_run_prompt_can_abort_before_scanning(
    tmp_path: Path,
    runner: CliRunner,
) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "a.txt").write_text("x", encoding="utf-8")
    db = tmp_path / "j.db"
    rules = write_rules(tmp_path)

    result = runner.invoke(
        app,
        ["plan", str(inbox), "-r", str(rules), "-o", str(tmp_path / "out"), "--db", str(db)],
        input="no\n",
    )

    assert result.exit_code == 1
    assert "第一次运行" in result.output
    assert not db.exists(), "aborting the first run must not even create the journal"


def test_gate_refuses_a_blacklisted_target(tmp_path: Path, runner: CliRunner) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "a.txt").write_text("x", encoding="utf-8")
    db = tmp_path / "j.db"
    rules = write_rules(tmp_path)
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
    batch = re.search(r"batch=(\S+)", preview.output).group(1)  # type: ignore[union-attr]

    # Deliberately corrupt the stored plan so it points into Windows, re-signing the hash.
    import json
    import sqlite3
    from dataclasses import replace as dataclass_replace

    from tidymate_core.journal import Journal
    from tidymate_core.planning.planner import compute_plan_hash
    from tidymate_core.planning.report import plan_to_dict

    with Journal(db) as journal:
        plan = journal.load_plan(batch)
    assert plan is not None
    tampered = dataclass_replace(
        plan.changes[0], dst="C:/Windows/Temp/tidymate-should-not-exist.txt"
    )
    changes = (tampered,)
    new_plan = dataclass_replace(
        plan,
        changes=changes,
        plan_hash=compute_plan_hash(changes, plan.stats),
    )
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "UPDATE batches SET plan_json = ? WHERE batch_id = ?",
            (json.dumps(plan_to_dict(new_plan), ensure_ascii=False), batch),
        )
        conn.commit()
    finally:
        conn.close()

    result = runner.invoke(app, ["apply", batch, "--db", str(db), "--yes"], input="YES\n")

    assert result.exit_code == 3, result.output
    assert "blacklist" in result.output
