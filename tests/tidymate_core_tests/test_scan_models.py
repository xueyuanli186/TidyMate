"""Scanning data model invariants."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from datetime import datetime

import pytest

from tidymate_core.scanning.models import (
    ErrorFlags,
    FileAttributes,
    FileEntry,
    ScanError,
    ScanErrorKind,
    ScanStats,
)


def test_mtime_must_be_timezone_aware(make_entry: Callable[..., FileEntry]) -> None:
    entry = make_entry("a.txt")
    with pytest.raises(ValueError, match="timezone aware"):
        dataclasses.replace(entry, mtime_utc=datetime(2024, 1, 1))


def test_ext_is_lowercase_with_dot(make_entry: Callable[..., FileEntry]) -> None:
    entry = make_entry("PHOTO.JPG")
    assert entry.ext == ".jpg"
    assert entry.ext_without_dot == "jpg"


def test_stem_keeps_original_case(make_entry: Callable[..., FileEntry]) -> None:
    assert make_entry("MyFile.TXT").stem == "MyFile"


def test_file_without_extension(make_entry: Callable[..., FileEntry]) -> None:
    entry = make_entry("README")
    assert entry.ext == ""
    assert entry.ext_without_dot == ""


def test_double_extension_uses_last_segment(make_entry: Callable[..., FileEntry]) -> None:
    assert make_entry("bundle.tar.gz").ext == ".gz"


def test_dotfile_has_no_extension(make_entry: Callable[..., FileEntry]) -> None:
    assert make_entry(".gitignore").ext == ""


def test_io_path_carries_extended_prefix(make_entry: Callable[..., FileEntry]) -> None:
    entry = make_entry("a.txt")
    assert entry.io_path == "\\\\?\\C:\\data\\a.txt"
    assert entry.full_path == "C:\\data\\a.txt"


def test_long_path_flag_is_derived(make_entry: Callable[..., FileEntry]) -> None:
    entry = make_entry("x" * 250 + ".txt")
    assert entry.is_long_path is True
    assert ErrorFlags.LONG_PATH in entry.error_flags


def test_short_path_has_no_long_flag(make_entry: Callable[..., FileEntry]) -> None:
    assert make_entry("a.txt").error_flags & ErrorFlags.LONG_PATH == ErrorFlags.NONE


def test_read_only_flag_is_derived(make_entry: Callable[..., FileEntry]) -> None:
    entry = make_entry("locked.txt", attributes=FileAttributes.READ_ONLY)
    assert entry.is_read_only is True
    assert ErrorFlags.READ_ONLY in entry.error_flags


def test_reparse_point_flag_is_derived(make_entry: Callable[..., FileEntry]) -> None:
    entry = make_entry("link.txt", attributes=FileAttributes.REPARSE_POINT)
    assert entry.is_reparse_point is True
    assert ErrorFlags.REPARSE_POINT in entry.error_flags


def test_unc_flag_is_derived(make_entry: Callable[..., FileEntry]) -> None:
    entry = make_entry("a.txt", parent="\\\\server\\share\\dir")
    assert ErrorFlags.UNC in entry.error_flags


def test_scan_error_defaults_to_failure() -> None:
    error = ScanError(path="C:\\a", kind=ScanErrorKind.OS_ERROR, message="boom")
    assert error.skipped is False


def test_scan_stats_serialises_to_json_friendly_dict() -> None:
    stats = ScanStats(dirs=2, files=3, errors=1, skipped=4, elapsed_s=0.123456)
    payload = stats.as_dict()
    assert payload["dirs"] == 2
    assert payload["elapsed_s"] == 0.1235
    assert payload["cancelled"] is False


def test_scan_stats_counts_are_independent() -> None:
    stats = ScanStats()
    stats.files += 1
    stats.errors += 1
    assert stats.files == 1
    assert stats.skipped == 0
