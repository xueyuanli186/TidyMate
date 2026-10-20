"""Version single-source-of-truth tests (stage 0 requirement 10).

The contract: exactly one editable place holds the version, and every consumer derives
from it. If someone adds a second literal version string, these tests fail.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from scripts.version import VERSION_FILE, main, read_version

import tidymate_core


def test_pyproject_does_not_hardcode_a_version(repo_root: Path) -> None:
    data = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    assert "version" not in data["project"], "version must be dynamic, not literal"
    assert data["project"]["dynamic"] == ["version"]
    assert data["tool"]["hatch"]["version"]["path"] == "src/tidymate_core/_version.py"


def test_helper_reads_the_same_value_as_the_package() -> None:
    assert read_version() == tidymate_core.__version__


def test_helper_reads_from_the_declared_file() -> None:
    expected = Path(__file__).resolve().parents[2] / "src" / "tidymate_core" / "_version.py"
    assert expected == VERSION_FILE


def test_cli_version_equals_package_version() -> None:
    from typer.testing import CliRunner

    from tidymate_cli.main import app

    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"tidymate {tidymate_core.__version__}"


def test_assert_tag_accepts_matching_tag() -> None:
    assert main(["--assert-tag", f"v{tidymate_core.__version__}"]) == 0


@pytest.mark.parametrize("bad_tag", ["v9.9.9", "0.1.0", "v0.1.0-rc1", "v0.1"])
def test_assert_tag_rejects_mismatched_tag(bad_tag: str) -> None:
    assert main(["--assert-tag", bad_tag]) == 1


def test_github_output_format() -> None:
    assert main(["--github-output"]) == 0
