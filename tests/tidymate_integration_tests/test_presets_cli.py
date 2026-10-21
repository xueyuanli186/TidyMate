"""CLI surface for presets: listing, copying and previewing."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from tidymate_cli.main import app


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_list_presets_shows_all_eight(runner: CliRunner) -> None:
    result = runner.invoke(app, ["list-presets"])
    assert result.exit_code == 0
    assert "downloads-cleanup" in result.output
    assert "old-files-archive" in result.output


def test_list_rules_after_first_run_copy(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    runner.invoke(app, ["list-presets"])
    result = runner.invoke(app, ["list-rules"])
    assert result.exit_code == 0
    assert "photos-by-year.yaml" in result.output


def test_use_preset_copies_and_previews(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    inbox = tmp_path / "Downloads"
    inbox.mkdir()
    (inbox / "a.jpg").write_bytes(b"x")
    (inbox / "b.pdf").write_bytes(b"x")
    result = runner.invoke(
        app,
        [
            "use-preset",
            "downloads-cleanup",
            str(inbox),
            "-o",
            str(tmp_path / "out"),
            "--db",
            str(tmp_path / "j.db"),
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "downloads-images" in result.output
    assert (tmp_path / "TidyMate" / "rules" / "downloads-cleanup.yaml").exists()


def test_unknown_preset_is_rejected(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "use-preset",
            "nope",
            str(tmp_path),
            "-o",
            str(tmp_path),
            "--db",
            str(tmp_path / "j.db"),
            "--yes",
        ],
    )
    assert result.exit_code == 2


def test_list_rules_when_the_rule_directory_cannot_be_seeded(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "empty"))
    monkeypatch.setattr(
        "tidymate_cli.main.presets.install_presets_if_missing",
        lambda: (_ for _ in ()).throw(OSError("denied")),
    )
    result = runner.invoke(app, ["list-rules"])
    assert result.exit_code == 0
    assert "还没有自定义规则" in result.output
