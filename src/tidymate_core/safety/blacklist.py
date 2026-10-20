"""Hard-coded directory blacklist (iron rule 4).

This list is **code**, not configuration. There is no flag, environment variable or config
key that can disable it, and the function signatures reflect that: there is no parameter to
turn the check off.

A path is refused when it *is* a protected directory or lives underneath one. The check is
case-insensitive and segment-aware (``C:\\Windows`` does not match ``C:\\WindowsApps``).
"""

from __future__ import annotations

import os

from tidymate_core.safety import paths

#: (environment variable or literal root, human label). ``None`` values are skipped on
#: hosts where the variable is missing, but the well-known ones are always present on a
#: supported Windows install.
_PROTECTED_ROOTS: tuple[tuple[str, str], ...] = (
    ("%SystemRoot%", "Windows"),
    ("%SystemRoot%\\System32", "Windows System32"),
    ("%SystemRoot%\\SysWOW64", "Windows SysWOW64"),
    ("%SystemRoot%\\WinSxS", "Windows WinSxS"),
    ("%ProgramFiles%", "Program Files"),
    ("%ProgramFiles(x86)%", "Program Files (x86)"),
    ("%ProgramData%", "ProgramData"),
    ("%SystemDrive%\\$Recycle.Bin", "Recycle Bin"),
    ("%SystemDrive%\\System Volume Information", "System Volume Information"),
    ("%SystemDrive%\\Recovery", "Recovery"),
    ("%SystemDrive%\\Boot", "Boot"),
    ("%SystemDrive%\\EFI", "EFI"),
    ("%SystemDrive%\\PerfLogs", "PerfLogs"),
)

#: Directory names that are protected on any drive.
_PROTECTED_NAMES: frozenset[str] = frozenset(
    {"$recycle.bin", "system volume information", "recovery", "boot", "efi"},
)


def _expand(value: str) -> str | None:
    expanded = os.path.expandvars(value)
    if "%" in expanded or not expanded:
        return None
    try:
        return paths.normalize(expanded)
    except ValueError:
        return None


def protected_roots() -> tuple[tuple[str, str], ...]:
    """Return ``(normalized_path, label)`` for every protected root on this host."""
    entries: list[tuple[str, str]] = []
    for raw, label in _PROTECTED_ROOTS:
        expanded = _expand(raw)
        if expanded is not None:
            entries.append((expanded, label))
    return tuple(entries)


def check_blacklisted(path: str) -> str | None:
    """Return the label of the protected root containing *path*, or ``None``.

    This function deliberately has no "disabled" parameter. Callers that need to *report*
    a hit must do so explicitly; they cannot opt out.
    """
    try:
        candidate = paths.normalize(path)
    except ValueError:
        return None

    for root, label in protected_roots():
        if paths.is_ancestor_or_self(root, candidate):
            return label

    # Any drive's recycle bin / system volume, not just the system drive.
    parts = candidate.split("\\")
    for part in parts[1:]:
        if part.casefold() in _PROTECTED_NAMES:
            return f"protected directory name ({part})"
    return None


def is_blacklisted(path: str) -> bool:
    """Convenience wrapper used by the planner and the GUI."""
    return check_blacklisted(path) is not None
