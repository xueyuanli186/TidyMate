"""Tests for scripts/make-sandbox.ps1.

The sandbox is the safety net for every later stage: no real user directory is ever used
for destructive testing. These tests assert that the script produces the conditions the
organiser must handle, and - just as important - that it refuses to touch an existing
directory.

Runs under pwsh (CI) or Windows PowerShell 5.1 (developer machines without PS7).
"""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

import pytest


def _run_sandbox(
    interpreter: list[str],
    repo_root: Path,
    root: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            *interpreter,
            "-File",
            str(repo_root / "scripts" / "make-sandbox.ps1"),
            "-Root",
            str(root),
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


@pytest.fixture(scope="module")
def sandbox(
    tmp_path_factory: pytest.TempPathFactory,
    powershell: list[str],
    repo_root: Path,
) -> Path:
    root = tmp_path_factory.mktemp("sandbox-parent") / "sandbox"
    result = _run_sandbox(powershell, repo_root, root)
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert root.is_dir()
    assert (root / "sandbox-manifest.txt").is_file()
    return root


def test_manifest_header(sandbox: Path) -> None:
    manifest = (sandbox / "sandbox-manifest.txt").read_text(encoding="utf-8")
    assert manifest.splitlines()[0] == "TidyMate drill sandbox manifest"
    assert f"root      : {sandbox}" in manifest


def test_script_refuses_existing_root(
    sandbox: Path,
    powershell: list[str],
    repo_root: Path,
) -> None:
    again = _run_sandbox(powershell, repo_root, sandbox)
    assert again.returncode != 0
    assert "Already exists" in (again.stdout + again.stderr)


def test_expected_structure(sandbox: Path) -> None:
    expected_files = [
        "inbox/notes.txt",
        "inbox/report.docx",
        "inbox/UPPER.TXT",
        "inbox/README",
        "inbox/.dotfile",
        "inbox/file with spaces.txt",
        "inbox/文件-中文名.txt",
        "inbox/2024/01/15/deep.txt",
        "inbox/keep/photo.jpg",
        "inbox/tmp/photo.jpg",
        "tidymate-journal.db",
    ]
    for relative in expected_files:
        assert (sandbox / relative).is_file(), f"missing {relative}"

    assert (sandbox / "empty-dir").is_dir()
    assert not any((sandbox / "empty-dir").iterdir())


def test_zero_byte_file(sandbox: Path) -> None:
    target = sandbox / "inbox/zero-byte.bin"
    assert target.is_file()
    assert target.stat().st_size == 0


def test_read_only_file_is_read_only(sandbox: Path) -> None:
    target = sandbox / "inbox/locked-readonly.txt"
    mode = target.stat().st_mode
    assert not (mode & stat.S_IWRITE), "read-only attribute is missing"


def test_system_and_hidden_attributes(sandbox: Path) -> None:
    assert (sandbox / "inbox/hidden-attribute.txt").exists()
    assert (sandbox / "inbox/system-flagged.dat").exists()


def test_alternate_data_stream_exists(sandbox: Path) -> None:
    target = sandbox / "inbox/with-alternate-stream.txt"
    assert target.is_file()
    assert Path(f"{target}:Zone.Identifier").exists()


def test_links_exist(sandbox: Path) -> None:
    junction = sandbox / "links/junction-to-inbox"
    assert junction.is_dir()
    assert (junction / "notes.txt").is_file(), "junction does not expose its target"

    link = sandbox / "links/symlink-to-notes.txt"
    assert link.exists()


def test_long_component_file(sandbox: Path) -> None:
    matches = [p for p in (sandbox / "inbox").iterdir() if p.name.startswith("longname-")]
    assert len(matches) == 1
    assert matches[0].name.endswith(".txt")
    assert matches[0].is_file()


def test_long_path_over_max_path(sandbox: Path) -> None:
    manifest = (sandbox / "sandbox-manifest.txt").read_text(encoding="utf-8")
    deep_lines = [line for line in manifest.splitlines() if line.startswith("longpath\\segment-")]
    assert len(deep_lines) == 1, "sandbox must contain exactly one >MAX_PATH file"
    relative = deep_lines[0].split(" | ", 1)[0]
    full = sandbox / relative
    assert len(str(full)) > 260, f"expected >260 chars, got {len(str(full))}"
    assert Path("\\\\?\\" + str(full)).exists(), "long path file is not reachable"


def test_manifest_is_complete(sandbox: Path) -> None:
    manifest = (sandbox / "sandbox-manifest.txt").read_text(encoding="utf-8")
    file_lines = [line for line in manifest.splitlines() if " | file | " in line]
    assert len(file_lines) >= 20
    assert "EXTENSIONS" in manifest
