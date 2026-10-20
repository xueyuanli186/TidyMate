"""Static scanner for permanent-delete APIs (iron rule 3 enforcement).

The rule: no code path in this repository may permanently delete a file. The only allowed
deletion is "move the copy *we just created* to the recycle bin during a rollback", and
even that goes through send2trash.

This module scans source files for the usual ways people spell "delete forever": the
Python stdlib helpers, pathlib, the .NET file and directory deletion members, the Win32
shell file-operation API, the PowerShell cmdlet, and the POSIX recursive-force pattern.
The concrete patterns live in ``FORBIDDEN_PATTERNS`` below.

Design notes
------------
* Patterns and rule names are written with character classes / neutral wording so that
  this file can never match itself. That is intentional: the guard should not need a
  self-exclusion rule to stay honest, and a test asserts that scanning this very file
  yields zero violations.
* It is a *text* scan, not an AST scan, on purpose: it also covers PowerShell, cmd and
  WiX fragments, which have no Python AST. False positives are preferred over blind spots;
  the allowlist mechanism is deliberately absent until a reviewed exception exists.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

SCAN_SUFFIXES: frozenset[str] = frozenset(
    {".py", ".ps1", ".psm1", ".cmd", ".bat", ".cs", ".wxs", ".wxi"},
)

EXCLUDED_DIRS: frozenset[str] = frozenset(
    {"__pycache__", ".git", ".venv", "venv", "dist", "node_modules", ".mypy_cache", ".ruff_cache"},
)

#: (human readable name, compiled pattern)
FORBIDDEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("os.remove", re.compile(r"\bos[.]remove\s*\(")),
    ("os.unlink", re.compile(r"\bos[.]unlink\s*\(")),
    ("shutil.rmtree", re.compile(r"\bshutil[.]rmtree\s*\(")),
    ("pathlib unlink", re.compile(r"[.]unlink\s*\(")),
    ("System.IO.File.Delete", re.compile(r"\bFile[.]Delete\s*\(")),
    ("System.IO.Directory.Delete", re.compile(r"\bDirectory[.]Delete\s*\(")),
    ("dotnet instance Delete()", re.compile(r"[.]Delete\s*\(")),
    ("shell file operation API", re.compile(r"\bSHFile[Oo]peration[AW]?\b")),
    ("shell operation without confirmation", re.compile(r"\bFOF_NOCONF[I]RMATION\b")),
    ("PowerShell remove item cmdlet", re.compile(r"\bRemove[-]Item\b")),
    ("POSIX rm recursive force", re.compile(r"\brm\s+-[a-z]*r[a-z]*\b")),
    ("cmd rd/rmdir recursive", re.compile(r"\b(rd|rmdir)\s+/s\b")),
)

DEFAULT_ROOTS: tuple[str, ...] = ("src", "scripts", "build")


@dataclass(frozen=True, slots=True)
class Violation:
    """One forbidden API occurrence, with enough context to fix it."""

    path: str
    lineno: int
    rule: str
    line: str

    def render(self) -> str:
        """Return a single-line, CI-friendly description."""
        return f"{self.path}:{self.lineno}: {self.rule} -> {self.line.strip()}"


def iter_source_files(root: Path) -> list[Path]:
    """Return scannable files under *root*, skipping vendored/build directories."""
    if not root.exists():
        return []
    if root.is_file():
        return [root] if root.suffix.lower() in SCAN_SUFFIXES else []
    found: list[Path] = []
    for path in sorted(root.rglob("*")):
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        if path.is_file() and path.suffix.lower() in SCAN_SUFFIXES:
            found.append(path)
    return found


def scan_file(path: Path, *, display_root: Path | None = None) -> list[Violation]:
    """Return every forbidden-API hit inside a single file."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    shown = str(path)
    if display_root is not None:
        try:
            shown = path.relative_to(display_root).as_posix()
        except ValueError:
            shown = str(path)
    violations: list[Violation] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for rule, pattern in FORBIDDEN_PATTERNS:
            if pattern.search(line):
                violations.append(
                    Violation(path=shown, lineno=lineno, rule=rule, line=line),
                )
    return violations


def scan_tree(root: Path) -> list[Violation]:
    """Scan *root* recursively; returns an empty list when the repository is clean."""
    violations: list[Violation] = []
    for file_path in iter_source_files(root):
        violations.extend(scan_file(file_path, display_root=root))
    return violations


def main(argv: list[str] | None = None, *, repo_root: Path | None = None) -> int:
    """CLI entry point used by CI. Returns a process exit code."""
    args = list(sys.argv[1:] if argv is None else argv)
    base = repo_root if repo_root is not None else Path.cwd()
    roots = [base / raw for raw in (args or list(DEFAULT_ROOTS))]
    violations: list[Violation] = []
    for root in roots:
        violations.extend(scan_tree(root))
    if violations:
        print("FORBIDDEN DELETE APIS FOUND (iron rule 3):")  # noqa: T201
        for violation in violations:
            print(f"  {violation.render()}")  # noqa: T201
        print(  # noqa: T201
            "\nUse send2trash for deletions, or the journal rollback path for copies we"
            " created ourselves.",
        )
        return 1
    scanned = sum(len(iter_source_files(root)) for root in roots)
    print(f"OK: no forbidden delete APIs in {scanned} scanned files.")  # noqa: T201
    return 0
