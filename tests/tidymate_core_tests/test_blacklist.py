"""Blacklist tests (iron rule 4: hard-coded, not configurable)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tidymate_core.safety import blacklist


def test_windows_directory_is_blocked() -> None:
    system_root = os.environ.get("SYSTEMROOT", r"C:\Windows")
    assert blacklist.check_blacklisted(str(Path(system_root) / "System32" / "kernel32.dll"))


def test_program_files_is_blocked() -> None:
    program_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
    assert blacklist.check_blacklisted(str(Path(program_files) / "app" / "app.exe"))


def test_recycle_bin_is_blocked() -> None:
    assert blacklist.check_blacklisted(r"C:\$Recycle.Bin\S-1-5-21") is not None


def test_system_volume_information_is_blocked() -> None:
    assert blacklist.check_blacklisted(r"D:\System Volume Information\x") is not None


def test_ordinary_user_directory_is_allowed() -> None:
    assert blacklist.check_blacklisted(r"C:\Users\someone\Downloads\a.jpg") is None


def test_segment_boundary_is_respected() -> None:
    # "C:\WindowsApps" must not be treated as being inside "C:\Windows".
    assert blacklist.check_blacklisted(r"C:\WindowsApps\a.txt") is None


def test_check_is_case_insensitive() -> None:
    assert blacklist.check_blacklisted(r"c:\WINDOWS\system32\x.dll") is not None


def test_blacklisted_flag_matches_check() -> None:
    assert blacklist.is_blacklisted(r"C:\Windows\notepad.exe") is True
    assert blacklist.is_blacklisted(r"C:\Users\me\notes.txt") is False


def test_protected_roots_are_never_empty() -> None:
    roots = blacklist.protected_roots()
    assert roots, "a supported Windows host must expose at least one protected root"
    for path, label in roots:
        assert path
        assert label


def test_function_has_no_disable_parameter() -> None:
    """Iron rule 4: configuration cannot switch the blacklist off."""
    import inspect

    signature = inspect.signature(blacklist.check_blacklisted)
    assert list(signature.parameters) == ["path"]


@pytest.mark.parametrize("bad", [""])
def test_degenerate_paths_do_not_crash(bad: str) -> None:
    assert blacklist.check_blacklisted(bad) is None


def test_bare_drive_is_treated_as_its_root() -> None:
    # "C:" and "C:\\" are the same location; both must be refused as a drive root.
    assert blacklist.check_blacklisted("C:") == "drive root itself"
