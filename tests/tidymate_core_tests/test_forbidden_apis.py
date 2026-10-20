"""Tests for the permanent-delete API guard (iron rule 3).

Two kinds of assertions:

1. the scanner actually detects each spelling (test with generated files);
2. the repository itself is clean, and the scanner does not flag itself.

Point 2 is the part that matters at review time: it turns an aspiration into a CI gate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tidymate_core.safety import forbidden_apis
from tidymate_core.safety.forbidden_apis import (
    DEFAULT_ROOTS,
    FORBIDDEN_PATTERNS,
    scan_file,
    scan_tree,
)


@pytest.mark.parametrize(
    ("snippet", "expected_rule"),
    [
        ("os.remove(target)", "os.remove"),
        ("os.unlink(target)", "os.unlink"),
        ("shutil.rmtree(folder)", "shutil.rmtree"),
        ("path.unlink()", "pathlib unlink"),
        ("File.Delete(path);", "System.IO.File.Delete"),
        ("Directory.Delete(path, true);", "System.IO.Directory.Delete"),
        ("new FileInfo(p).Delete();", "dotnet instance Delete()"),
        ("SHFileOperation(ref op);", "shell file operation API"),
        ("SHFileOperationW(&op);", "shell file operation API"),
        ("flags = FOF_NOCONFIRMATION;", "shell operation without confirmation"),
        ("Remove-Item -Recurse -Force $p", "PowerShell remove item cmdlet"),
        ("rm -rf /tmp/x", "POSIX rm recursive force"),
        ("rd /s /q C:\\x", "cmd rd/rmdir recursive"),
    ],
)
def test_each_forbidden_spelling_is_detected(
    tmp_path: Path,
    snippet: str,
    expected_rule: str,
) -> None:
    target = tmp_path / "sample.py"
    target.write_text(snippet + "\n", encoding="utf-8")
    rules = {violation.rule for violation in scan_file(target)}
    assert expected_rule in rules


def test_clean_file_has_no_violations(tmp_path: Path) -> None:
    target = tmp_path / "clean.py"
    target.write_text("from send2trash import send2trash\n", encoding="utf-8")
    assert scan_file(target) == []


def test_powershell_file_is_scanned(tmp_path: Path) -> None:
    target = tmp_path / "danger.ps1"
    target.write_text("Remove-Item -LiteralPath $p -Force\n", encoding="utf-8")
    assert len(scan_file(target)) == 1


def test_markdown_and_yaml_are_not_scanned_for_code(tmp_path: Path) -> None:
    doc = tmp_path / "notes.md"
    doc.write_text("never call os.remove() in this project\n", encoding="utf-8")
    assert scan_tree(tmp_path) == []


def test_guard_does_not_flag_itself() -> None:
    own_file = Path(forbidden_apis.__file__)
    assert scan_file(own_file) == [], (
        "the pattern table must be written so it cannot match its own source"
    )


def test_repository_is_clean(repo_root: Path) -> None:
    violations = []
    for root_name in DEFAULT_ROOTS:
        violations.extend(scan_tree(repo_root / root_name))
    assert violations == [], "\n".join(v.render() for v in violations)


def test_main_returns_zero_on_clean_tree(repo_root: Path) -> None:
    assert forbidden_apis.main([], repo_root=repo_root) == 0


def test_main_returns_one_and_reports_on_violation(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "bad.py").write_text("import os\nos.remove(p)\n", encoding="utf-8")
    assert forbidden_apis.main([], repo_root=tmp_path) == 1


def test_every_pattern_has_a_name_and_compiles() -> None:
    for rule, pattern in FORBIDDEN_PATTERNS:
        assert rule
        assert pattern.search("x") is None
