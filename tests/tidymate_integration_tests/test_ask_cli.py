"""CLI ``ask`` policy: every answer path, including abort.

``ask`` is the only place where a human decision enters the batch, so each key is tested:
``y`` executes, ``n`` skips, ``q`` aborts without touching anything.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tidymate_cli.main import app

ASK_RULES = """
rules:
  - id: text
    when: { ext: [".txt"] }
    action: { op: move, template: "Text/{name}", conflict: ask }
"""


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def prepare(tmp_path: Path) -> tuple[Path, Path, Path]:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "a.txt").write_text("new", encoding="utf-8")
    target = tmp_path / "out" / "Text"
    target.mkdir(parents=True)
    (target / "a.txt").write_text("old", encoding="utf-8")
    rules = tmp_path / "rules.yaml"
    rules.write_text(ASK_RULES, encoding="utf-8")
    return inbox, rules, tmp_path / "j.db"


def preview(runner: CliRunner, tmp_path: Path, inbox: Path, rules: Path, db: Path) -> str:
    result = runner.invoke(
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
    assert result.exit_code == 0, result.output
    match = re.search(r"batch=(\S+)", result.output)
    assert match is not None
    return match.group(1)


def test_ask_yes_never_overwrites_either(
    tmp_path: Path,
    runner: CliRunner,
) -> None:
    inbox, rules, db = prepare(tmp_path)
    batch = preview(runner, tmp_path, inbox, rules, db)

    result = runner.invoke(
        app,
        ["apply", batch, "--db", str(db), "--yes"],
        input="y\n",
    )

    assert (tmp_path / "out" / "Text" / "a.txt").read_text(encoding="utf-8") == "old"
    assert result.exit_code == 1, "accepting the move must still fail on an existing target"
    assert "failed=1" in result.output


def test_ask_no_skips_without_touching(tmp_path: Path, runner: CliRunner) -> None:
    inbox, rules, db = prepare(tmp_path)
    batch = preview(runner, tmp_path, inbox, rules, db)

    result = runner.invoke(app, ["apply", batch, "--db", str(db), "--yes"], input="n\n")

    assert result.exit_code == 0, result.output
    assert (inbox / "a.txt").exists()
    assert "skipped=1" in result.output


def test_ask_quit_aborts_the_batch(tmp_path: Path, runner: CliRunner) -> None:
    inbox, rules, db = prepare(tmp_path)
    batch = preview(runner, tmp_path, inbox, rules, db)

    result = runner.invoke(app, ["apply", batch, "--db", str(db), "--yes"], input="q\n")

    assert result.exit_code == 1
    assert (inbox / "a.txt").exists()
    with __import__("tidymate_core.journal", fromlist=["Journal"]).Journal(db) as journal:
        assert journal.batch_status(batch) == "aborted"
