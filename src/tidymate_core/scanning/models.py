"""Data model for directory scanning.

Every field here exists because a later stage needs it, not because it was easy to collect:

* ``full_path`` / ``io_path`` carry the display and ``\\\\?\\`` forms of the same file;
* ``normalized_path`` is what rules match against (never the extended form);
* ``error_flags`` classifies the special cases the project must report separately
  (iron rule 8), so ``skipped`` never silently means "disappeared".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import IntFlag, StrEnum

from tidymate_core.safety import paths


#: Win32 file attribute bits we care about (see ``FILE_ATTRIBUTE_*``).
class FileAttributes(IntFlag):
    """Subset of Win32 file attributes used by the organiser."""

    NONE = 0x0000
    READ_ONLY = 0x0001
    HIDDEN = 0x0002
    SYSTEM = 0x0004
    DIRECTORY = 0x0010
    ARCHIVE = 0x0020
    REPARSE_POINT = 0x0400
    OFFLINE = 0x1000
    RECALL_ON_OPEN = 0x00040000
    RECALL_ON_DATA_ACCESS = 0x00400000


class ErrorFlags(IntFlag):
    """Per-entry classification flags.

    Named ``ErrorFlags`` because the scanning contract asked for it, but the semantics are
    "things a later stage must treat carefully" rather than "the entry failed".
    """

    NONE = 0
    LONG_PATH = 1 << 0
    REPARSE_POINT = 1 << 1
    READ_ONLY = 1 << 2
    SYSTEM = 1 << 3
    HIDDEN = 1 << 4
    UNC = 1 << 5
    OFFLINE = 1 << 6


class ScanErrorKind(StrEnum):
    """Why a path could not be processed, or why it was deliberately skipped."""

    PERMISSION_DENIED = "permission_denied"
    PATH_TOO_LONG = "path_too_long"
    IN_USE = "in_use"
    REPARSE_POINT = "reparse_point"
    INVALID_PATH = "invalid_path"
    OS_ERROR = "os_error"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class FileEntry:
    """One regular file discovered by the scanner."""

    full_path: str
    normalized_path: str
    io_path: str
    name: str
    stem: str
    ext: str
    size: int
    mtime_utc: datetime
    attributes: FileAttributes
    is_reparse_point: bool
    is_read_only: bool
    path_length: int
    error_flags: ErrorFlags

    def __post_init__(self) -> None:
        if self.mtime_utc.tzinfo is None:
            raise ValueError("mtime_utc must be timezone aware")
        if self.mtime_utc.utcoffset() is None:
            raise ValueError("mtime_utc must have a UTC offset")

    @property
    def is_long_path(self) -> bool:
        """True when the display path exceeds ``MAX_PATH``."""
        return self.path_length > paths.MAX_PATH

    @property
    def ext_without_dot(self) -> str:
        """Extension without the leading dot, lower case (``""`` when absent)."""
        return self.ext[1:] if self.ext.startswith(".") else self.ext


@dataclass(frozen=True, slots=True)
class ScanError:
    """A path that failed, or was skipped for a documented reason.

    ``skipped=True`` marks a *policy* outcome (reparse point, over-long path with the
    feature disabled, ...). Those must never be counted as failures, and failures must
    never be counted as success (iron rule 10).
    """

    path: str
    kind: ScanErrorKind
    message: str
    errno: int | None = None
    winerror: int | None = None
    skipped: bool = False


@dataclass(slots=True)
class ScanStats:
    """Aggregate counters for one scan run."""

    dirs: int = 0
    files: int = 0
    errors: int = 0
    skipped: int = 0
    elapsed_s: float = 0.0
    peak_memory_bytes: int | None = None
    cancelled: bool = False

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-friendly view for reports and tests."""
        return {
            "dirs": self.dirs,
            "files": self.files,
            "errors": self.errors,
            "skipped": self.skipped,
            "elapsed_s": round(self.elapsed_s, 4),
            "peak_memory_bytes": self.peak_memory_bytes,
            "cancelled": self.cancelled,
        }


@dataclass(frozen=True, slots=True)
class ScanResult:
    """Materialised scan output.

    Only for callers that genuinely need every entry in memory (tests, small reports).
    Large runs should consume :func:`tidymate_core.scanning.walker.iter_scan` instead.
    """

    entries: tuple[FileEntry, ...]
    errors: tuple[ScanError, ...]
    stats: ScanStats


def utc_now() -> datetime:
    """Return the current time as an aware UTC datetime."""
    return datetime.now(tz=UTC)
