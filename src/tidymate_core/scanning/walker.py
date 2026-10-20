"""Streaming directory walker.

Design constraints that shaped this file:

* **Streaming, not materialised.** ``iter_scan`` yields one item at a time; a directory
  with 100k entries is never turned into a list inside the walker.
* **Never abort on a bad path.** A denied directory, a locked file or an over-long path
  becomes a :class:`ScanError` and the walk continues. Nothing is swallowed silently.
* **Long paths everywhere.** Every OS call receives the ``\\\\?\\`` form, while the emitted
  ``full_path`` stays display-friendly.
* **Reparse points are policy, not accidents.** With ``follow_symlinks=False`` (default)
  they are skipped *and reported*, so a junction never quietly disappears from a report.
"""

from __future__ import annotations

import errno
import fnmatch
import os
import time
import tracemalloc
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

from tidymate_core.safety import paths
from tidymate_core.scanning import streams as stream_probe
from tidymate_core.scanning.cancel import CHECK_INTERVAL, CancelToken
from tidymate_core.scanning.config import ScanConfig
from tidymate_core.scanning.models import (
    ErrorFlags,
    FileAttributes,
    FileEntry,
    ScanError,
    ScanErrorKind,
    ScanResult,
    ScanStats,
)

_SCAN_ITEM = FileEntry | ScanError

_PATH_TOO_LONG_WINERRORS = frozenset({206})
_IN_USE_WINERRORS = frozenset({32, 33})
_INVALID_NAME_WINERRORS = frozenset({123, 161})


class DirEntryLike(Protocol):
    """Structural subset of :class:`os.DirEntry` the walker relies on."""

    name: str
    path: str

    def is_dir(self, *, follow_symlinks: bool = True) -> bool:
        """True when the entry is a directory."""
        ...

    def is_file(self, *, follow_symlinks: bool = True) -> bool:
        """True when the entry is a regular file."""
        ...

    def is_symlink(self) -> bool:
        """True when the entry itself is a symbolic link."""
        ...

    def stat(self, *, follow_symlinks: bool = True) -> os.stat_result:
        """Return the entry's stat information."""
        ...


class ScandirResult(Protocol):
    """Structural subset of the object returned by :func:`os.scandir`."""

    def __enter__(self) -> Iterator[DirEntryLike]:
        """Enter the context manager, yielding an entry iterator."""
        ...

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        """Close the underlying handle."""
        ...


ScandirFn = Callable[[str], ScandirResult]


def classify_os_error(exc: OSError) -> ScanErrorKind:
    """Map an OS error onto the scanner's public error taxonomy."""
    if isinstance(exc, PermissionError):
        return ScanErrorKind.PERMISSION_DENIED
    winerror = getattr(exc, "winerror", None)
    if winerror in _PATH_TOO_LONG_WINERRORS or exc.errno in (
        errno.ENAMETOOLONG,
        errno.EMSGSIZE,
    ):
        return ScanErrorKind.PATH_TOO_LONG
    if winerror in _IN_USE_WINERRORS:
        return ScanErrorKind.IN_USE
    if winerror in _INVALID_NAME_WINERRORS:
        return ScanErrorKind.INVALID_PATH
    return ScanErrorKind.OS_ERROR


def make_scan_error(path: str, exc: OSError, *, skipped: bool = False) -> ScanError:
    """Build a :class:`ScanError` with errno/winerror preserved for diagnosis."""
    winerror = getattr(exc, "winerror", None)
    return ScanError(
        path=path,
        kind=classify_os_error(exc),
        message=f"{type(exc).__name__}: {exc}",
        errno=getattr(exc, "errno", None),
        winerror=winerror if isinstance(winerror, int) else None,
        skipped=skipped,
    )


def _file_attributes(stat_result: os.stat_result) -> FileAttributes:
    raw = getattr(stat_result, "st_file_attributes", 0)
    return FileAttributes(int(raw)) if raw else FileAttributes.NONE


def build_entry(
    parent: str,
    name: str,
    stat_result: os.stat_result,
    *,
    alternate_streams: tuple[str, ...] = (),
) -> FileEntry:
    """Create a :class:`FileEntry` from a stat result (pure, testable).

    ``alternate_streams`` is passed in rather than probed here so this function stays
    free of OS calls; :func:`_process_entry` owns the handle-based detection.
    """
    full_path = paths.join(parent, name)
    name_path = Path(name)
    stem, ext = name_path.stem, name_path.suffix
    attributes = _file_attributes(stat_result)
    mtime = datetime.fromtimestamp(stat_result.st_mtime, tz=UTC)
    length = paths.path_length(full_path)

    flags = ErrorFlags.NONE
    if length > paths.MAX_PATH:
        flags |= ErrorFlags.LONG_PATH
    if attributes & FileAttributes.REPARSE_POINT:
        flags |= ErrorFlags.REPARSE_POINT
    if attributes & FileAttributes.READ_ONLY:
        flags |= ErrorFlags.READ_ONLY
    if attributes & FileAttributes.SYSTEM:
        flags |= ErrorFlags.SYSTEM
    if attributes & FileAttributes.HIDDEN:
        flags |= ErrorFlags.HIDDEN
    if paths.is_unc(full_path):
        flags |= ErrorFlags.UNC
    if attributes & FileAttributes.OFFLINE:
        flags |= ErrorFlags.OFFLINE
    if attributes & (
        FileAttributes.RECALL_ON_DATA_ACCESS
        | FileAttributes.RECALL_ON_OPEN
        | FileAttributes.OFFLINE
    ):
        flags |= ErrorFlags.ONEDRIVE_PLACEHOLDER
    if alternate_streams:
        flags |= ErrorFlags.ADS

    return FileEntry(
        full_path=full_path,
        normalized_path=paths.normalize(full_path),
        io_path=paths.to_extended(full_path),
        name=name,
        stem=stem,
        ext=ext.lower(),
        size=int(stat_result.st_size),
        mtime_utc=mtime,
        attributes=attributes,
        is_reparse_point=bool(attributes & FileAttributes.REPARSE_POINT),
        is_read_only=bool(attributes & FileAttributes.READ_ONLY),
        path_length=length,
        error_flags=flags,
        alternate_streams=alternate_streams,
    )


def _is_excluded_directory(
    config: ScanConfig,
    normalized: str,
    name: str,
) -> bool:
    if normalized.casefold() in config.excluded_absolute:
        return True
    lowered = name.casefold()
    return any(fnmatch.fnmatchcase(lowered, pattern) for pattern in config.excluded_globs)


def _should_stop(token: CancelToken, processed: int) -> bool:
    """Sample the cancellation flag every ``CHECK_INTERVAL`` entries (cheap by design)."""
    return processed % CHECK_INTERVAL == 0 and token.cancelled


def iter_scan(
    config: ScanConfig,
    *,
    cancel: CancelToken | None = None,
    stats: ScanStats | None = None,
    scandir: ScandirFn | None = None,
) -> Iterator[_SCAN_ITEM]:
    """Walk ``config.roots`` lazily, yielding files and errors as they are found.

    ``scandir`` is injectable so tests and the benchmark can supply synthetic trees
    without touching the real file system.
    """
    token = cancel if cancel is not None else CancelToken()
    counters = stats if stats is not None else ScanStats()
    scan_fn: ScandirFn = scandir if scandir is not None else cast("ScandirFn", os.scandir)
    seen_dirs: set[tuple[int, int]] = set()
    processed = 0

    stack: list[tuple[str, int]] = [(root, 0) for root in reversed(config.normalized_roots)]
    while stack:
        if token.cancelled:
            counters.cancelled = True
            return
        current, depth = stack.pop()
        counters.dirs += 1

        try:
            handle = scan_fn(paths.to_extended(current))
        except OSError as exc:
            yield make_scan_error(current, exc)
            counters.errors += 1
            continue

        try:
            with handle as iterator:
                for entry in iterator:
                    processed += 1
                    if _should_stop(token, processed):
                        counters.cancelled = True
                        return

                    item = _process_entry(
                        config,
                        current,
                        depth,
                        entry,
                        stack,
                        seen_dirs,
                        counters,
                    )
                    if isinstance(item, str):
                        counters.skipped += 1
                        yield ScanError(
                            path=paths.join(current, entry.name),
                            kind=ScanErrorKind.REPARSE_POINT,
                            message=item,
                            skipped=True,
                        )
                    elif item is not None:
                        if isinstance(item, ScanError):
                            if item.skipped:
                                counters.skipped += 1
                            else:
                                counters.errors += 1
                        else:
                            counters.files += 1
                        yield item
        except OSError as exc:
            counters.errors += 1
            yield make_scan_error(current, exc)


def _process_entry(
    config: ScanConfig,
    current: str,
    depth: int,
    entry: DirEntryLike,
    stack: list[tuple[str, int]],
    seen_dirs: set[tuple[int, int]],
    counters: ScanStats,
) -> FileEntry | ScanError | str | None:
    """Classify one directory entry.

    Returns a :class:`FileEntry`, a :class:`ScanError`, a ``str`` message meaning
    "skipped reparse point with this reason", or ``None`` meaning "consumed silently"
    (a directory pushed onto the stack, or an entry filtered by config).
    """
    full_path = paths.join(current, entry.name)

    try:
        stat_result = entry.stat(follow_symlinks=False)
        is_directory = entry.is_dir(follow_symlinks=False)
    except OSError as exc:
        return make_scan_error(full_path, exc)

    attributes = _file_attributes(stat_result)
    is_reparse = bool(attributes & FileAttributes.REPARSE_POINT)

    if is_reparse and not config.follow_symlinks:
        return f"reparse point not followed (follow_symlinks=false): {entry.name}"

    target_is_directory = False
    if is_reparse and config.follow_symlinks:
        try:
            target_is_directory = entry.is_dir(follow_symlinks=True)
        except OSError as exc:
            return make_scan_error(full_path, exc)

    if is_directory or target_is_directory:
        if config.max_depth is not None and depth >= config.max_depth:
            counters.skipped += 1
            return None
        if _is_excluded_directory(config, paths.normalize(full_path), entry.name):
            counters.skipped += 1
            return None
        if config.exclude_hidden and attributes & FileAttributes.HIDDEN:
            counters.skipped += 1
            return None
        if config.exclude_system and attributes & FileAttributes.SYSTEM:
            counters.skipped += 1
            return None
        if is_reparse:
            key = (int(stat_result.st_dev), int(stat_result.st_ino))
            if key in seen_dirs:
                return f"reparse point cycle detected: {entry.name}"
            seen_dirs.add(key)
        stack.append((full_path, depth + 1))
        return None

    if not entry.is_file(follow_symlinks=False) and not is_reparse:
        # Sockets, devices and other exotic entries are not files we can organise.
        counters.skipped += 1
        return None

    size = int(stat_result.st_size)
    if config.max_file_size is not None and size > config.max_file_size:
        counters.skipped += 1
        return None
    if config.exclude_hidden and attributes & FileAttributes.HIDDEN:
        counters.skipped += 1
        return None
    if config.exclude_system and attributes & FileAttributes.SYSTEM:
        counters.skipped += 1
        return None

    streams_found: tuple[str, ...] = ()
    if config.detect_alternate_streams:
        detected = stream_probe.list_alternate_streams(full_path)
        if detected:
            streams_found = detected

    return build_entry(
        current,
        entry.name,
        stat_result,
        alternate_streams=streams_found,
    )


def scan(
    config: ScanConfig,
    *,
    cancel: CancelToken | None = None,
    scandir: ScandirFn | None = None,
) -> ScanResult:
    """Run a full scan and materialise the result.

    Prefer :func:`iter_scan` for large trees; this helper is for tests and small reports.
    It records wall-clock duration and, when ``config.measure_memory`` is set, the
    allocator peak via :mod:`tracemalloc` (which slows the walk down: measure, then turn
    it off).
    """
    counters = ScanStats()
    entries: list[FileEntry] = []
    errors: list[ScanError] = []

    tracing = config.measure_memory
    if tracing:
        tracemalloc.start()
    started = time.perf_counter()
    try:
        for item in iter_scan(config, cancel=cancel, stats=counters, scandir=scandir):
            if isinstance(item, FileEntry):
                entries.append(item)
            else:
                errors.append(item)
    finally:
        counters.elapsed_s = time.perf_counter() - started
        if tracing:
            _, peak = tracemalloc.get_traced_memory()
            counters.peak_memory_bytes = int(peak)
            tracemalloc.stop()

    return ScanResult(entries=tuple(entries), errors=tuple(errors), stats=counters)
