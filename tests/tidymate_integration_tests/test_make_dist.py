"""Packaging contract tests for scripts/make_dist.py.

Stage 0 acceptance: the CI must produce a downloadable windows artifact. Locally we can
only prove the *artifact assembly* half (the upload is GitHub's job), so these tests pin:

* the bundle/archive naming contract: ``TidyMate-<version>-windows``;
* the zip contains exactly the declared files (no stale leakage);
* the archive is byte-reproducible, so a release can be verified by checksum;
* the checksum file matches the archive.
"""

from __future__ import annotations

import tomllib
import zipfile
from pathlib import Path

import pytest
from scripts.make_dist import build, bundle_dir_name, sha256_file

import tidymate_core

EXPECTED_ENTRIES = [
    "BUNDLE.txt",
    "VERSION.txt",
    "bin/README.txt",
    "bin/tidymate-gui.cmd",
    "bin/tidymate.cmd",
]


def test_bundle_and_archive_names(tmp_path: Path) -> None:
    version = tidymate_core.__version__
    bundle, archive = build(out_dir=tmp_path)
    assert bundle.name == f"TidyMate-{version}-windows"
    assert archive.name == f"TidyMate-{version}-windows.zip"
    assert bundle_dir_name(version) == bundle.name


def test_zip_contains_exactly_the_declared_entries(tmp_path: Path) -> None:
    bundle, archive = build(out_dir=tmp_path)
    with zipfile.ZipFile(archive) as zf:
        names = sorted(zf.namelist())
    assert names == sorted(f"{bundle.name}/{entry}" for entry in EXPECTED_ENTRIES)
    assert zf_all_paths_are_relative(names)


def zf_all_paths_are_relative(names: list[str]) -> bool:
    """Every archive entry must be relative and free of traversal segments."""
    return all(not name.startswith(("/", "\\")) and ".." not in name for name in names)


def test_archive_is_reproducible(tmp_path: Path) -> None:
    _, first = build(out_dir=tmp_path / "a")
    _, second = build(out_dir=tmp_path / "b")
    assert sha256_file(first) == sha256_file(second), (
        "two builds of the same version must be byte identical"
    )


def test_checksum_file_matches_archive(tmp_path: Path) -> None:
    from scripts.make_dist import main

    assert main(["--out-dir", str(tmp_path)]) == 0
    archive = tmp_path / f"{bundle_dir_name(tidymate_core.__version__)}.zip"
    checksum_file = archive.with_name(archive.name + ".sha256")
    recorded = checksum_file.read_text(encoding="utf-8").split()[0]
    assert recorded == sha256_file(archive)


def test_version_txt_matches_single_source(tmp_path: Path) -> None:
    _, archive = build(out_dir=tmp_path)
    with zipfile.ZipFile(archive) as zf:
        version_txt = zf.read(f"{bundle_dir_name(tidymate_core.__version__)}/VERSION.txt")
    assert version_txt.decode().strip() == f"TidyMate {tidymate_core.__version__}"


def test_cli_launcher_targets_the_cli_module(tmp_path: Path) -> None:
    _, archive = build(out_dir=tmp_path)
    with zipfile.ZipFile(archive) as zf:
        launcher = zf.read(f"{bundle_dir_name(tidymate_core.__version__)}/bin/tidymate.cmd")
    assert b"tidymate_cli" in launcher
    assert b"python -m" in launcher


def test_pyproject_wheel_targets_all_three_packages(repo_root: Path) -> None:
    data = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    packages = data["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    assert packages == ["src/tidymate_core", "src/tidymate_cli", "src/tidymate_app"]


@pytest.mark.parametrize("relative", ["bin/tidymate.cmd", "bin/tidymate-gui.cmd"])
def test_launchers_use_crlf(tmp_path: Path, relative: str) -> None:
    _, archive = build(out_dir=tmp_path)
    with zipfile.ZipFile(archive) as zf:
        payload = zf.read(f"{bundle_dir_name(tidymate_core.__version__)}/{relative}")
    assert b"\r\n" in payload
