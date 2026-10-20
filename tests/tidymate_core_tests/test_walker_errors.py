"""Error tolerance with an injected ``scandir``.

The point of these tests is the *contract*: a bad path becomes an error entry, the walk
continues, and failures never get counted as skips (or vice versa). Injecting ``scandir``
keeps them fast and independent of the host's permissions.
"""

from __future__ import annotations

import errno
import os
from collections.abc import Iterator
from typing import Any, cast

import pytest

from tidymate_core.safety import paths
from tidymate_core.scanning import ScanConfig, ScanErrorKind, scan
from tidymate_core.scanning.cancel import CancelToken
from tidymate_core.scanning.models import FileAttributes, ScanStats
from tidymate_core.scanning.walker import iter_scan

ROOT = "C:\\fake"


class _Stat:
    def __init__(self, *, size: int, attributes: int) -> None:
        self.st_size = size
        self.st_file_attributes = attributes
        self.st_mtime = 1_700_000_000.0
        self.st_dev = 1
        self.st_ino = 2


class FakeEntry:
    """Minimal structural stand-in for :class:`os.DirEntry`."""

    def __init__(
        self,
        name: str,
        *,
        directory: bool = False,
        size: int = 10,
        attributes: int = 0,
        stat_error: OSError | None = None,
    ) -> None:
        self.name = name
        self.path = name
        self._directory = directory
        self._size = size
        self._attributes = attributes
        self._stat_error = stat_error

    def is_dir(self, *, follow_symlinks: bool = True) -> bool:  # noqa: ARG002
        return self._directory

    def is_file(self, *, follow_symlinks: bool = True) -> bool:  # noqa: ARG002
        return not self._directory

    def is_symlink(self) -> bool:
        return False

    def stat(self, *, follow_symlinks: bool = True) -> os.stat_result:  # noqa: ARG002
        if self._stat_error is not None:
            raise self._stat_error
        result = _Stat(size=self._size, attributes=self._attributes)
        return cast("os.stat_result", cast("Any", result))


class _Handle:
    def __init__(self, entries: list[FakeEntry]) -> None:
        self._entries = entries

    def __enter__(self) -> Iterator[FakeEntry]:
        return iter(self._entries)

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class FakeScandir:
    def __init__(self, mapping: dict[str, list[FakeEntry] | BaseException]) -> None:
        self.mapping = mapping
        self.calls: list[str] = []

    def __call__(self, path: str) -> _Handle:
        self.calls.append(path)
        value = self.mapping.get(path, [])
        if isinstance(value, BaseException):
            raise value
        return _Handle(value)


def _config(**kwargs: object) -> ScanConfig:
    return ScanConfig(roots=(ROOT,), **kwargs)  # type: ignore[arg-type]


def test_permission_denied_directory_does_not_abort() -> None:
    root = paths.to_extended(ROOT)
    mapping: dict[str, list[FakeEntry] | BaseException] = {
        root: [FakeEntry("a.txt"), FakeEntry("locked", directory=True)],
        paths.to_extended(ROOT + "\\locked"): PermissionError(errno.EACCES, "denied"),
    }
    result = scan(_config(), scandir=FakeScandir(mapping))

    assert {entry.name for entry in result.entries} == {"a.txt"}
    assert len(result.errors) == 1
    assert result.errors[0].kind is ScanErrorKind.PERMISSION_DENIED
    assert result.errors[0].skipped is False
    assert result.stats.errors == 1


def test_scan_continues_to_sibling_directories_after_error() -> None:
    root = paths.to_extended(ROOT)
    mapping: dict[str, list[FakeEntry] | BaseException] = {
        root: [
            FakeEntry("bad", directory=True),
            FakeEntry("good", directory=True),
        ],
        paths.to_extended(ROOT + "\\bad"): PermissionError(errno.EACCES, "denied"),
        paths.to_extended(ROOT + "\\good"): [FakeEntry("inside.txt")],
    }
    result = scan(_config(), scandir=FakeScandir(mapping))

    assert "inside.txt" in {entry.name for entry in result.entries}
    assert len(result.errors) == 1


def test_stat_error_on_file_is_recorded_and_skipped_over() -> None:
    root = paths.to_extended(ROOT)
    mapping: dict[str, list[FakeEntry] | BaseException] = {
        root: [
            FakeEntry("broken.txt", stat_error=PermissionError(errno.EACCES, "denied")),
            FakeEntry("fine.txt"),
        ],
    }
    result = scan(_config(), scandir=FakeScandir(mapping))

    assert {entry.name for entry in result.entries} == {"fine.txt"}
    assert result.errors[0].path.endswith("broken.txt")
    assert result.errors[0].kind is ScanErrorKind.PERMISSION_DENIED


def test_path_too_long_by_errno() -> None:
    root = paths.to_extended(ROOT)
    mapping: dict[str, list[FakeEntry] | BaseException] = {
        root: [FakeEntry("deep", directory=True)],
        paths.to_extended(ROOT + "\\deep"): OSError(errno.ENAMETOOLONG, "name too long"),
    }
    result = scan(_config(), scandir=FakeScandir(mapping))

    assert result.errors
    assert result.errors[0].kind is ScanErrorKind.PATH_TOO_LONG


def test_in_use_error_by_winerror() -> None:
    root = paths.to_extended(ROOT)
    exc = OSError(errno.EBUSY, "sharing violation")
    exc.winerror = 32
    mapping: dict[str, list[FakeEntry] | BaseException] = {
        root: [FakeEntry("busy", directory=True)],
        paths.to_extended(ROOT + "\\busy"): exc,
    }
    result = scan(_config(), scandir=FakeScandir(mapping))

    assert result.errors
    assert result.errors[0].kind is ScanErrorKind.IN_USE


def test_reparse_entry_is_skipped_not_failed() -> None:
    root = paths.to_extended(ROOT)
    mapping: dict[str, list[FakeEntry] | BaseException] = {
        root: [
            FakeEntry("a.txt"),
            FakeEntry(
                "junction",
                directory=True,
                attributes=int(FileAttributes.REPARSE_POINT),
            ),
        ],
    }
    result = scan(_config(), scandir=FakeScandir(mapping))

    assert result.stats.files == 1
    assert result.stats.errors == 0
    assert result.stats.skipped == 1
    assert result.errors[0].skipped is True
    assert result.errors[0].kind is ScanErrorKind.REPARSE_POINT


def test_cancel_stops_scan_and_keeps_partial_stats() -> None:
    root = paths.to_extended(ROOT)
    entries = [FakeEntry(f"f{index}.txt") for index in range(2000)]
    stats = ScanStats()
    token = CancelToken()
    seen = 0
    for _item in iter_scan(
        _config(),
        cancel=token,
        stats=stats,
        scandir=FakeScandir({root: entries}),
    ):
        seen += 1
        if seen == 300:
            token.cancel()

    assert stats.cancelled is True
    assert seen < 2000
    assert stats.files == seen


def test_cancel_before_start_reports_cancelled() -> None:
    token = CancelToken()
    token.cancel()
    stats = ScanStats()
    items = list(iter_scan(_config(), cancel=token, stats=stats, scandir=FakeScandir({})))
    assert items == []
    assert stats.cancelled is True


def test_missing_directory_yields_error() -> None:
    result = scan(_config(), scandir=FakeScandir({}))
    # An empty mapping returns an empty listing, not an error; the root is still counted.
    assert result.stats.dirs == 1
    assert result.entries == ()


@pytest.mark.parametrize(
    ("attributes", "expected_flag"),
    [
        (FileAttributes.READ_ONLY, "READ_ONLY"),
        (FileAttributes.HIDDEN, "HIDDEN"),
        (FileAttributes.SYSTEM, "SYSTEM"),
    ],
)
def test_attribute_flags_are_derived(attributes: FileAttributes, expected_flag: str) -> None:
    root = paths.to_extended(ROOT)
    entry = FakeEntry("a.txt", attributes=int(attributes))
    result = scan(_config(), scandir=FakeScandir({root: [entry]}))
    assert expected_flag in (result.entries[0].error_flags.name or "")
