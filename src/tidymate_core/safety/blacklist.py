"""Hard-coded directory blacklist (iron rule 4).

This list is **code**, not configuration. There is no flag, environment variable or config
key that can disable it, and the function signatures reflect that: there is no parameter to
turn the check off.

A path is refused when it *is* a protected directory or lives underneath one. The check is
case-insensitive and segment-aware (``C:\\Windows`` does not match ``C:\\WindowsApps``).

Two kinds of entries exist here, and the difference matters:

* **containers** - anything underneath is refused too (``C:\\Windows\\**``);
* **exact objects** - only the path itself is refused. The user profile and its
  ``Desktop`` / ``Downloads`` / ``Documents`` folders belong to this kind: they are
  legitimate *scan roots*, but "move the whole folder" is never acceptable.
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
    ("%ProgramW6432%", "Program Files (64-bit)"),
    ("%ProgramData%", "ProgramData"),
    ("%ProgramData%\\Microsoft", "ProgramData\\Microsoft"),
    ("%LocalAppData%\\Microsoft", "LocalAppData\\Microsoft"),
    ("%AppData%\\Microsoft", "AppData\\Microsoft"),
    ("%SystemDrive%\\$Recycle.Bin", "Recycle Bin"),
    ("%SystemDrive%\\System Volume Information", "System Volume Information"),
    ("%SystemDrive%\\Recovery", "Recovery"),
    ("%SystemDrive%\\Boot", "Boot"),
    ("%SystemDrive%\\EFI", "EFI"),
    ("%SystemDrive%\\PerfLogs", "PerfLogs"),
)

#: Paths that may be scanned but must never be moved/renamed themselves.
_EXACT_ONLY: tuple[tuple[str, str], ...] = (
    ("%USERPROFILE%", "user profile root"),
    ("%USERPROFILE%\\Desktop", "Desktop folder itself"),
    ("%USERPROFILE%\\Downloads", "Downloads folder itself"),
    ("%USERPROFILE%\\Documents", "Documents folder itself"),
)

#: Directory names that are protected on any drive.
_PROTECTED_NAMES: frozenset[str] = frozenset(
    {"$recycle.bin", "system volume information", "recovery", "boot", "efi"},
)

#: Runtime directories that must be protected (install dir, logs, batch workspace).
_RUNTIME_PROTECTED: set[str] = set()
#: Runtime files that must be protected exactly (the journal database itself). A file
#: entry protects only that file: putting the DB in a folder must not make the folder
#: untouchable, or "output root next to the journal" would be impossible.
_RUNTIME_PROTECTED_FILES: set[str] = set()


def _expand(value: str) -> str | None:
    expanded = os.path.expandvars(value)
    if "%" in expanded or not expanded:
        return None
    try:
        return paths.normalize(expanded)
    except ValueError:
        return None


def _same(left: str, right: str) -> bool:
    return (
        paths.strip_trailing_separator(left).casefold()
        == paths.strip_trailing_separator(
            right,
        ).casefold()
    )


def protected_roots() -> tuple[tuple[str, str], ...]:
    """Return ``(normalized_path, label)`` for every protected container on this host."""
    entries: list[tuple[str, str]] = []
    for raw, label in _PROTECTED_ROOTS:
        expanded = _expand(raw)
        if expanded is not None:
            entries.append((expanded, label))
    return tuple(entries)


def register_protected_path(path: str) -> None:
    """Protect a runtime directory (install dir, journal DB, logs, batch workspace).

    Registration only ever *adds* protection. There is no unregister call outside the test
    suite, by design: a long-running process must not be able to shrink this set.
    """
    try:
        _RUNTIME_PROTECTED.add(paths.normalize(path))
    except ValueError:
        return


def register_protected_file(path: str) -> None:
    """Protect one runtime *file* (the journal database), exactly."""
    try:
        _RUNTIME_PROTECTED_FILES.add(paths.normalize(path))
    except ValueError:
        return


def reset_runtime_protected_paths() -> None:
    """Test helper: forget every registered runtime path and file."""
    _RUNTIME_PROTECTED.clear()
    _RUNTIME_PROTECTED_FILES.clear()


def is_drive_root(path: str) -> bool:
    """True for ``C:\\`` (the root itself, not its contents)."""
    candidate = paths.from_extended(path).rstrip("\\")
    return len(candidate) == 2 and candidate[1] == ":" and candidate[0].isalpha()


def check_blacklisted(path: str) -> str | None:
    """Return the label of the protected root containing *path*, or ``None``.

    This function deliberately has no "disabled" parameter. Callers that need to *report*
    a hit must do so explicitly; they cannot opt out.
    """
    raw = paths.from_extended(path)
    if is_drive_root(raw):
        return "drive root itself"

    try:
        candidate = paths.normalize(path)
    except ValueError:
        return None

    # Resolve junctions / symlinks before comparing: a link such as
    # C:/Users/All Users is really C:/ProgramData, and a check that only sees the link
    # name would wave it through. realpath() resolves the longest existing prefix, so a
    # not-yet-created target still gets its parent chain resolved.
    try:
        resolved = paths.normalize(os.path.realpath(candidate))
    except (OSError, ValueError):
        resolved = candidate
    if resolved != candidate:
        hit = _check_resolved(resolved)
        if hit is not None:
            return hit

    return _check_resolved(candidate)


def _check_resolved(candidate: str) -> str | None:
    """Compare one already-normalised path against every protected root."""
    for protected_file in _RUNTIME_PROTECTED_FILES:
        if _same(protected_file, candidate):
            return "TidyMate runtime file"
    for root in _RUNTIME_PROTECTED:
        if paths.is_ancestor_or_self(root, candidate):
            return "TidyMate runtime directory"

    for raw_pattern, label in _EXACT_ONLY:
        expanded = _expand(raw_pattern)
        if expanded is not None and _same(expanded, candidate):
            return label

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


def check_unc(path: str) -> str | None:
    """Return a reason when *path* is a UNC/network path, else ``None``.

    Kept separate from :func:`check_blacklisted` because ``--allow-unc`` may opt out of
    *this* policy only; it can never opt out of the blacklist.
    """
    if paths.is_unc(paths.from_extended(path)):
        return "UNC / network path (pass --allow-unc to opt in)"
    return None


_INSTALLER_NAMES = ("unins*.exe", "*.msi")


def check_installer_directory(directory: str) -> str | None:
    """Return a reason when *directory* looks like an application install directory.

    Heuristic from the product owner: a directory holding an uninstaller executable or an
    MSI is a program directory, not a user data directory. Only the directory's own top
    level is inspected - walking ancestors would make every scan pay a full tree read.
    """
    import fnmatch

    try:
        candidate = paths.normalize(directory)
    except ValueError:
        return None
    try:
        names = [entry.name.casefold() for entry in os.scandir(candidate)]
    except OSError:
        return None
    for name in names:
        if any(fnmatch.fnmatchcase(name, pattern) for pattern in _INSTALLER_NAMES):
            return f"installer found in {candidate!r} (unins*.exe / *.msi)"
    return None
