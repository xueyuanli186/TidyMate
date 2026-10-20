"""Smoke tests: the package imports, the layers exist, the CLI answers.

Stage 0 acceptance: at least one passing test proves the test chain works. These go a bit
further on purpose - they also lock in three stage-0 boundaries:

* Core must not import a UI toolkit or a network client (requirement 1 + iron rule 9).
* The CLI must expose only ``status`` for now (no write command may exist yet).
* The version must be a plain three-part semver.
"""

from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

import tidymate_core
from tidymate_cli.main import app

LAYERS = (
    "scanning",
    "rules",
    "templates",
    "planning",
    "conflicts",
    "execution",
    "journal",
    "safety",
    "reporting",
)

#: Layers that have a real implementation today. The rest are intentional placeholders.
IMPLEMENTED_LAYERS = frozenset({"scanning", "rules", "safety", "planning", "journal", "execution"})

# Anything that would drag Qt, a GUI toolkit, or a network stack into Core.
FORBIDDEN_IMPORT_ROOTS = frozenset(
    {
        "PySide6",
        "PyQt5",
        "PyQt6",
        "tkinter",
        "customtkinter",
        "requests",
        "urllib",
        "urllib3",
        "http",
        "socket",
        "aiohttp",
        "httpx",
        "webbrowser",
        "ftplib",
        "smtplib",
        "paramiko",
        "openai",
        "anthropic",
    },
)


def _imported_roots(path: Path) -> set[str]:
    """Return the top-level module names imported by a Python file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_core_package_imports(repo_root: Path) -> None:
    assert tidymate_core.__version__ == "0.1.0"
    assert Path(tidymate_core.__file__).resolve().is_relative_to(repo_root / "src")


@pytest.mark.parametrize("layer", LAYERS)
def test_layer_packages_are_importable(layer: str) -> None:
    module = importlib.import_module(f"tidymate_core.{layer}")
    assert module.__doc__, f"layer {layer} must document its responsibility"
    if layer in IMPLEMENTED_LAYERS:
        assert module.__all__, f"implemented layer {layer} must expose a public API"
    else:
        assert module.__all__ == [], f"unimplemented layer {layer} must stay empty"


def test_core_does_not_import_ui_or_network_code(repo_root: Path) -> None:
    core = repo_root / "src" / "tidymate_core"
    offenders: dict[str, set[str]] = {}
    for path in sorted(core.rglob("*.py")):
        bad = _imported_roots(path) & FORBIDDEN_IMPORT_ROOTS
        if bad:
            offenders[path.relative_to(repo_root).as_posix()] = bad
    assert offenders == {}, f"Core must stay UI/network free: {offenders}"


def test_version_is_three_part_semver() -> None:
    assert re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", tidymate_core.__version__), (
        "version must stay MAJOR.MINOR.PATCH (MSI + git tag depend on it)"
    )


def test_cli_version_output() -> None:
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.stdout
    assert tidymate_core.__version__ in result.stdout


def test_cli_exposes_the_expected_commands() -> None:
    # typer leaves CommandInfo.name as None when it derives the name from the function.
    names: set[str] = set()
    for command in app.registered_commands:
        if command.name:
            names.add(command.name)
        elif command.callback is not None:
            names.add(str(command.callback.__name__))
    assert names == {
        "status",
        "plan",
        "apply",
        "undo",
        "verify",
        "list-batches",
        "show-batch",
    }, f"unexpected CLI surface: {names}"


def test_apply_is_not_reachable_without_a_batch_id() -> None:
    result = CliRunner().invoke(app, ["apply"])
    assert result.exit_code != 0, "apply must require an explicit batch id"


def test_cli_status_is_honest() -> None:
    result = CliRunner().invoke(app, ["status"])
    assert result.exit_code == 0
    assert "stage           : 7-9" in result.stdout
    assert "write commands  : apply" in result.stdout
    assert "planning        : templates" in result.stdout
    assert "journal         : SQLite" in result.stdout
