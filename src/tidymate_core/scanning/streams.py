"""Alternate-data-stream detection (Windows only).

Why this module exists: an NTFS alternate data stream (ADS) is invisible to
``os.stat`` but disappears when a file is copied through most APIs - including the
ones a naive "move" implementation would use. ``Zone.Identifier`` is the one Windows
attaches to files downloaded from the internet; losing it silently downgrades
Defender's "mark of the web" warning. Iron rule 8 therefore says: detect, report,
never move by default.

The detection uses ``GetFileInformationByHandleEx(FileStreamInfo)`` rather than
enumerating ``path:stream`` names, because the latter cannot tell "no such stream"
from "access denied" and would produce false negatives on locked files.

Nothing here writes: the handle is opened with ``FILE_READ_ATTRIBUTES`` only, which
also avoids hydrating OneDrive placeholders (a read would download the file).
"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes

from tidymate_core.safety import paths

#: The default unnamed data stream is not an "alternate" stream.
_DEFAULT_STREAM = "::$DATA"

_FILE_READ_ATTRIBUTES = 0x0080
_FILE_SHARE_ALL = 0x00000007  # read | write | delete
_OPEN_EXISTING = 3
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
#: ``FILE_INFO_BY_HANDLE_CLASS.FileStreamInfo`` (the enum value is 7, not 22).
_FILE_STREAM_INFO_CLASS = 7
_ERROR_MORE_DATA = 234
_MAX_BUFFER = 1 << 20
_INVALID_HANDLE = ctypes.c_void_p(-1).value


class _StreamInfoHeader(ctypes.Structure):
    """Fixed part of ``FILE_STREAM_INFO``; the stream name follows it inline."""

    _fields_ = (
        ("next_entry_offset", wintypes.DWORD),
        ("stream_name_length", wintypes.DWORD),
        ("stream_size", ctypes.c_longlong),
        ("stream_allocation_size", ctypes.c_longlong),
    )


_HEADER_SIZE = ctypes.sizeof(_StreamInfoHeader)


def _kernel32() -> ctypes.WinDLL:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    kernel32.GetFileInformationByHandleEx.restype = wintypes.BOOL
    kernel32.GetFileInformationByHandleEx.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    return kernel32


def _decode_name(raw: bytes) -> str:
    """Turn ``:Zone.Identifier:$DATA`` into ``Zone.Identifier``."""
    name = raw.decode("utf-16-le", errors="replace").rstrip("\x00")
    if name.endswith(":$DATA"):
        name = name[: -len(":$DATA")]
    if name.startswith(":"):
        name = name[1:]
    return name


def _parse_streams(buffer: bytes) -> tuple[str, ...]:
    """Walk the ``FILE_STREAM_INFO`` chain and return non-default stream names."""
    names: list[str] = []
    offset = 0
    while offset + _HEADER_SIZE <= len(buffer):
        header = _StreamInfoHeader.from_buffer_copy(buffer[offset : offset + _HEADER_SIZE])
        name_start = offset + _HEADER_SIZE
        raw = buffer[name_start : name_start + int(header.stream_name_length)]
        full = raw.decode("utf-16-le", errors="replace")
        if full and full != _DEFAULT_STREAM:
            decoded = _decode_name(raw)
            if decoded:
                names.append(decoded)
        step = int(header.next_entry_offset)
        if step <= 0:
            break
        offset += step
    return tuple(names)


def list_alternate_streams(path: str) -> tuple[str, ...] | None:
    """Return the alternate stream names of *path*, or ``None`` when unknown.

    ``None`` means "could not decide" (non-Windows host, unreadable handle). Callers
    must treat it as *unknown*, not as "clean": iron rule 10 forbids pretending a
    check succeeded when it did not. The scanner records that as a warning-free
    unknown today; the limitation is listed in ``docs/HANDOFF.md``.
    """
    if sys.platform != "win32" or os.name != "nt":
        return None

    kernel32 = _kernel32()
    handle = kernel32.CreateFileW(
        paths.to_extended(path),
        _FILE_READ_ATTRIBUTES,
        _FILE_SHARE_ALL,
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_BACKUP_SEMANTICS,
        None,
    )
    if handle is None or handle == _INVALID_HANDLE:
        return None
    try:
        size = 4096
        while size <= _MAX_BUFFER:
            buffer = ctypes.create_string_buffer(size)
            if kernel32.GetFileInformationByHandleEx(
                handle,
                _FILE_STREAM_INFO_CLASS,
                buffer,
                size,
            ):
                return _parse_streams(buffer.raw)
            if ctypes.get_last_error() != _ERROR_MORE_DATA:
                return None
            size *= 2
        return None
    finally:
        kernel32.CloseHandle(handle)
