"""Scanner against a real temporary file system.

These tests create their own tree under ``tmp_path``; nothing outside it is touched, and
nothing is deleted by the test suite (the project forbids deletion calls, including in
tests). Pytest keeps the last few temporary directories for inspection.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tidymate_core.scanning import ScanConfig, ScanErrorKind, cancel, scan

WINDOWS_ONLY = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only behaviour")

FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4


def _set_attributes(path: Path, attributes: int) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    if not kernel32.SetFileAttributesW(str(path), attributes):
        raise ctypes.WinError(ctypes.get_last_error())


def _make_junction(link: Path, target: Path) -> bool:
    shell = os.environ.get("COMSPEC", "cmd.exe")
    result = subprocess.run(
        [shell, "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and link.exists()


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    (root / "sub" / "deep").mkdir(parents=True)
    (root / "skipdir").mkdir()
    (root / "a.txt").write_text("0123456789", encoding="utf-8")
    (root / "b.JPG").write_text("x" * 20, encoding="utf-8")
    (root / "sub" / "c.txt").write_text("y" * 30, encoding="utf-8")
    (root / "sub" / "deep" / "d.txt").write_text("z" * 40, encoding="utf-8")
    (root / "skipdir" / "e.txt").write_text("e", encoding="utf-8")
    return root


def test_finds_all_files(tree: Path) -> None:
    result = scan(ScanConfig(roots=(str(tree),)))
    assert {entry.name for entry in result.entries} == {
        "a.txt",
        "b.JPG",
        "c.txt",
        "d.txt",
        "e.txt",
    }
    assert result.stats.errors == 0
    assert result.stats.files == 5


def test_entry_metadata_matches_disk(tree: Path) -> None:
    result = scan(ScanConfig(roots=(str(tree),)))
    entry = next(item for item in result.entries if item.name == "a.txt")
    assert entry.stem == "a"
    assert entry.ext == ".txt"
    assert entry.size == 10
    assert entry.path_length == len(entry.full_path)
    assert entry.mtime_utc.tzinfo is not None
    assert entry.io_path.startswith("\\\\?\\")
    assert entry.normalized_path == entry.full_path


def test_extension_is_lowercased(tree: Path) -> None:
    result = scan(ScanConfig(roots=(str(tree),)))
    entry = next(item for item in result.entries if item.name == "b.JPG")
    assert entry.ext == ".jpg"
    assert entry.stem == "b"


def test_max_depth_zero_only_root(tree: Path) -> None:
    result = scan(ScanConfig(roots=(str(tree),), max_depth=0))
    assert {entry.name for entry in result.entries} == {"a.txt", "b.JPG"}


def test_max_depth_one_includes_first_level(tree: Path) -> None:
    result = scan(ScanConfig(roots=(str(tree),), max_depth=1))
    # root files + files of every first-level directory (sub and skipdir), but not deep/
    assert {entry.name for entry in result.entries} == {"a.txt", "b.JPG", "c.txt", "e.txt"}


def test_max_file_size_filters_large_files(tree: Path) -> None:
    result = scan(ScanConfig(roots=(str(tree),), max_file_size=15))
    names = {entry.name for entry in result.entries}
    assert "a.txt" in names
    assert "b.JPG" not in names
    assert result.stats.skipped >= 1


def test_exclude_dir_by_name(tree: Path) -> None:
    result = scan(ScanConfig(roots=(str(tree),), exclude_dirs=("skipdir",)))
    assert "e.txt" not in {entry.name for entry in result.entries}


def test_exclude_dir_by_glob(tree: Path) -> None:
    result = scan(ScanConfig(roots=(str(tree),), exclude_dirs=("skip*",)))
    assert "e.txt" not in {entry.name for entry in result.entries}


def test_exclude_dir_by_absolute_path(tree: Path) -> None:
    result = scan(ScanConfig(roots=(str(tree),), exclude_dirs=(str(tree / "sub"),)))
    names = {entry.name for entry in result.entries}
    assert "c.txt" not in names
    assert "d.txt" not in names
    assert "a.txt" in names


def test_exclude_dir_is_case_insensitive(tree: Path) -> None:
    result = scan(ScanConfig(roots=(str(tree),), exclude_dirs=("SkipDir",)))
    assert "e.txt" not in {entry.name for entry in result.entries}


@WINDOWS_ONLY
def test_exclude_hidden(tree: Path) -> None:
    hidden = tree / "secret.txt"
    hidden.write_text("h", encoding="utf-8")
    _set_attributes(hidden, FILE_ATTRIBUTE_HIDDEN)

    included = scan(ScanConfig(roots=(str(tree),)))
    assert "secret.txt" in {entry.name for entry in included.entries}

    excluded = scan(ScanConfig(roots=(str(tree),), exclude_hidden=True))
    assert "secret.txt" not in {entry.name for entry in excluded.entries}


@WINDOWS_ONLY
def test_exclude_system(tree: Path) -> None:
    system_file = tree / "system.dat"
    system_file.write_text("s", encoding="utf-8")
    _set_attributes(system_file, FILE_ATTRIBUTE_SYSTEM)

    excluded = scan(ScanConfig(roots=(str(tree),), exclude_system=True))
    assert "system.dat" not in {entry.name for entry in excluded.entries}


@WINDOWS_ONLY
def test_junction_is_skipped_and_reported_by_default(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (target / "inside.txt").write_text("x", encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()
    if not _make_junction(root / "link", target):
        pytest.skip("this machine cannot create junctions")

    result = scan(ScanConfig(roots=(str(root),)))
    assert "inside.txt" not in {entry.name for entry in result.entries}
    reparse_errors = [error for error in result.errors if error.kind is ScanErrorKind.REPARSE_POINT]
    assert reparse_errors, "a skipped junction must be reported, not hidden"
    assert all(error.skipped for error in reparse_errors)
    assert result.stats.errors == 0
    assert result.stats.skipped >= 1


@WINDOWS_ONLY
def test_junction_is_followed_when_enabled(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (target / "inside.txt").write_text("x", encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()
    if not _make_junction(root / "link", target):
        pytest.skip("this machine cannot create junctions")

    result = scan(ScanConfig(roots=(str(root),), follow_symlinks=True))
    assert "inside.txt" in {entry.name for entry in result.entries}


@WINDOWS_ONLY
def test_long_path_file_is_reachable(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    deep = root
    for index in range(4):
        deep = deep / (f"segment{index}-" + "x" * 55)
    try:
        Path("\\\\?\\" + str(deep)).mkdir(parents=True)
    except OSError:  # pragma: no cover - depends on host policy
        pytest.skip("long paths are not supported on this host")
    target = deep / "long.txt"
    Path("\\\\?\\" + str(target)).write_text("long", encoding="utf-8")

    result = scan(ScanConfig(roots=(str(root),)))
    long_entries = [entry for entry in result.entries if entry.is_long_path]
    assert long_entries, "the scanner must still see files beyond MAX_PATH"
    assert long_entries[0].name == "long.txt"


def test_stats_are_consistent_with_entries(tree: Path) -> None:
    result = scan(ScanConfig(roots=(str(tree),)))
    assert result.stats.files == len(result.entries)
    assert result.stats.errors == sum(1 for error in result.errors if not error.skipped)
    assert result.stats.elapsed_s > 0


def test_scan_accepts_multiple_roots(tmp_path: Path) -> None:
    first = tmp_path / "one"
    second = tmp_path / "two"
    first.mkdir()
    second.mkdir()
    (first / "a.txt").write_text("a", encoding="utf-8")
    (second / "b.txt").write_text("b", encoding="utf-8")

    result = scan(ScanConfig(roots=(str(first), str(second))))
    assert {entry.name for entry in result.entries} == {"a.txt", "b.txt"}


def test_full_scan_reports_cancel_flag_false(tree: Path) -> None:
    result = scan(ScanConfig(roots=(str(tree),)))
    assert result.stats.cancelled is False
    assert cancel.CHECK_INTERVAL >= 1
