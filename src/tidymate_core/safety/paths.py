"""Windows path normalisation and long-path handling.

Two different paths exist for every file:

* the **display path** the user sees (``C:\\Users\\me\\a.txt``), kept free of the
  ``\\\\?\\`` marker so it can be shown, matched and logged without surprises;
* the **IO path** handed to the operating system (``\\\\?\\C:\\Users\\me\\a.txt``),
  which lifts the 260 character limit.

This module is the only place allowed to convert between them. All functions are pure
string operations built on :mod:`ntpath`, so they behave identically on any host and can be
unit tested without touching a file system.
"""

from __future__ import annotations

import ntpath

EXTENDED_PREFIX = "\\\\?\\"
UNC_EXTENDED_PREFIX = "\\\\?\\UNC\\"
DEVICE_PREFIX = "\\\\.\\"

#: Classic Win32 path limit. Anything longer needs the extended prefix (iron rule 8).
MAX_PATH = 260


def is_extended(path: str) -> bool:
    """Return True when *path* already carries an extended-length prefix."""
    return path.startswith(EXTENDED_PREFIX) or path.startswith(DEVICE_PREFIX)


def is_unc(path: str) -> bool:
    """Return True for a ``\\\\server\\share`` path (but not for ``\\\\?\\`` forms)."""
    if path.startswith(EXTENDED_PREFIX) or path.startswith(DEVICE_PREFIX):
        return False
    drive, _ = ntpath.splitdrive(path)
    return drive.startswith("\\\\")


def is_absolute(path: str) -> bool:
    """Return True for a rooted Windows path (drive-qualified or UNC)."""
    candidate = from_extended(path)
    return ntpath.isabs(candidate)


def to_extended(path: str) -> str:
    """Return the ``\\\\?\\`` form of an absolute *path*.

    Relative paths are rejected on purpose: an extended path must be fully qualified, and
    silently resolving against the current directory is how "it worked on my machine"
    bugs are born.
    """
    if is_extended(path):
        return path
    if not ntpath.isabs(path):
        raise ValueError(f"extended paths require an absolute path, got {path!r}")
    if is_unc(path):
        return UNC_EXTENDED_PREFIX + path[2:]
    return EXTENDED_PREFIX + path


def from_extended(path: str) -> str:
    """Strip a ``\\\\?\\`` / ``\\\\.\\`` prefix, returning the display path."""
    if path.startswith(UNC_EXTENDED_PREFIX):
        return "\\\\" + path[len(UNC_EXTENDED_PREFIX) :]
    if path.startswith(EXTENDED_PREFIX) or path.startswith(DEVICE_PREFIX):
        return path[4:]
    return path


def normalize(path: str) -> str:
    """Return a canonical absolute display path.

    * relative input is resolved against the current directory;
    * separators become ``\\`` and redundant ``..``/``.`` segments collapse;
    * a trailing separator is dropped except for a drive or share root;
    * the drive letter is upper-cased (``c:`` -> ``C:``);
    * case of the remaining segments is preserved (only comparisons are case-insensitive).
    """
    raw = from_extended(str(path))
    if not raw or raw in {".", ".."}:
        raise ValueError(f"cannot normalize an empty or relative-to-nothing path: {path!r}")
    if not ntpath.isabs(raw):
        raw = ntpath.abspath(raw)
    normalized = ntpath.normpath(raw)

    if len(normalized) == 2 and normalized[1] == ":":
        # "C:" -> "C:\"
        normalized += "\\"
    elif len(normalized) > 1 and normalized[1] == ":":
        normalized = normalized[0].upper() + normalized[1:]
    return normalized


def path_length(path: str) -> int:
    """Return the character length of the display path (what MAX_PATH counts)."""
    return len(from_extended(path))


def is_long_path(path: str) -> bool:
    """Return True when the display path exceeds the classic 260 character limit."""
    return path_length(path) > MAX_PATH


def strip_trailing_separator(path: str) -> str:
    """Drop trailing separators, keeping the root separator of ``C:\\`` intact."""
    if len(path) == 3 and path[1] == ":" and path[2] == "\\":
        return path
    return path.rstrip("\\")


def is_ancestor_or_self(candidate: str, path: str) -> bool:
    """Return True when *candidate* is *path* itself or one of its ancestors.

    Comparison follows NTFS semantics (case-insensitive) and is done on segment
    boundaries, so ``C:\\data`` is **not** an ancestor of ``C:\\database``.
    """
    left = strip_trailing_separator(normalize(candidate)).casefold()
    right = strip_trailing_separator(normalize(path)).casefold()
    if left == right:
        return True
    # A drive root keeps its separator ("C:\"), so do not double it.
    prefix = left if left.endswith("\\") else left + "\\"
    return right.startswith(prefix)


def join(parent: str, child: str) -> str:
    """Join a parent directory and a child name without normalising either."""
    return ntpath.join(parent, child)
