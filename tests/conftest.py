"""Shared pytest fixtures."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final, cast

import pytest

from tidymate_core.scanning.models import FileAttributes, FileEntry
from tidymate_core.scanning.walker import build_entry

REPO_ROOT: Final = Path(__file__).resolve().parents[1]
DEFAULT_MTIME: Final = datetime(2024, 5, 1, 12, 0, 0, tzinfo=UTC)

EntryFactory = Callable[..., FileEntry]


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


@pytest.fixture
def make_entry() -> EntryFactory:
    """Build a :class:`FileEntry` for rule tests without touching the disk.

    Goes through the real :func:`build_entry` so extension lower-casing, flag derivation
    and path normalisation are exercised rather than re-implemented in tests.
    """

    def factory(
        name: str = "photo.JPG",
        *,
        parent: str = r"C:\data",
        size: int = 1024,
        mtime: datetime = DEFAULT_MTIME,
        attributes: FileAttributes = FileAttributes.ARCHIVE,
    ) -> FileEntry:
        stat_result = SimpleNamespace(
            st_size=size,
            st_mtime=mtime.timestamp(),
            st_file_attributes=int(attributes),
            st_dev=0,
            st_ino=0,
        )
        return build_entry(parent, name, cast("Any", stat_result))

    return factory
