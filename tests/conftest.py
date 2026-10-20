"""Shared pytest fixtures."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT: Final = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Absolute path to the repository root."""
    return REPO_ROOT


@pytest.fixture(scope="session")
def powershell() -> list[str]:
    """Command prefix for a PowerShell interpreter.

    Prefers PowerShell 7 (``pwsh``, what CI uses) and falls back to Windows PowerShell
    5.1, which the sandbox script also supports. Skips the test when neither exists.
    """
    pwsh = shutil.which("pwsh")
    if pwsh is not None:
        return [pwsh, "-NoProfile", "-NonInteractive"]
    legacy = shutil.which("powershell")
    if legacy is not None:
        return [legacy, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass"]
    pytest.skip("neither pwsh nor powershell is available")
    raise AssertionError("unreachable")  # keeps type checkers happy
