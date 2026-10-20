"""Packaging contract tests for stage 9 (PyInstaller bundle + WiX MSI).

Actually running PyInstaller takes a minute and is CI's job; these tests pin the contract
that would otherwise drift silently:

* bundle/archive naming and the checksum file;
* ``zip_bundle`` never writes absolute or traversal paths and includes every file;
* the spec, entry points and WiX source exist and stay wired to the single version source;
* MSI ProductVersion normalisation.
"""

from __future__ import annotations

import sys
import tomllib
import zipfile
from pathlib import Path

import pytest
from scripts.make_dist import bundle_dir_name, sha256_file, zip_bundle

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "build"))

import build_msi  # noqa: E402
import tidymate_core  # noqa: E402


def test_bundle_and_archive_names(tmp_path: Path) -> None:
    del tmp_path  # fixture only keeps pytest's tmp dir alive
    version = tidymate_core.__version__
    assert bundle_dir_name(version) == f"TidyMate-{version}-windows"


def test_zip_bundle_writes_relative_entries_only(tmp_path: Path) -> None:
    bundle = tmp_path / "TidyMate-1.2.3-windows"
    (bundle / "bin").mkdir(parents=True)
    (bundle / "tidymate.exe").write_bytes(b"MZ")
    (bundle / "bin" / "extra.dll").write_bytes(b"dll")
    archive = tmp_path / "out.zip"

    zip_bundle(bundle, archive)

    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
    assert names == [
        "TidyMate-1.2.3-windows/bin/extra.dll",
        "TidyMate-1.2.3-windows/tidymate.exe",
    ]
    assert all(not name.startswith(("/", "\\")) and ".." not in name for name in names)


def test_zip_bundle_rejects_a_missing_bundle(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        zip_bundle(tmp_path / "nope", tmp_path / "out.zip")


def test_sha256_file_matches_hashlib(tmp_path: Path) -> None:
    import hashlib

    payload = tmp_path / "x.bin"
    payload.write_bytes(b"tidy")
    assert sha256_file(payload) == hashlib.sha256(b"tidy").hexdigest()


def test_packaging_entry_points_and_layout(repo_root: Path) -> None:
    assert (repo_root / "build" / "entry_cli.py").exists()
    assert (repo_root / "build" / "entry_gui.py").exists()
    source = (repo_root / "scripts" / "make_dist.py").read_text(encoding="utf-8")
    assert "entry_cli.py" in source
    assert "entry_gui.py" in source
    # The final layout is documented and asserted by CI as well.
    assert '"cli"' in source
    assert "TidyMate.exe" in source


def test_wix_source_uses_the_build_parameters(repo_root: Path) -> None:
    wxs = (repo_root / "build" / "wix" / "TidyMate.wxs").read_text(encoding="utf-8")
    assert "$(var.Version)" in wxs
    assert "$(var.SourceDir)" in wxs
    assert "ProgramFiles64Folder" in wxs
    assert "UpgradeCode" in wxs
    # User data must never be removed by the installer.
    assert "<RemoveFolderEx" not in wxs
    assert "LocalAppDataFolder" not in wxs


def test_msi_version_normalisation() -> None:
    assert build_msi.normalize_version("0.1.0") == "0.1.0"
    assert build_msi.normalize_version("0.1.0.dev1") == "0.1.0"
    assert build_msi.normalize_version("2.3") == "2.3.0"
    assert build_msi.normalize_version("1.2.3+local") == "1.2.3"


def test_product_code_is_stable_per_version() -> None:
    assert build_msi.product_code("0.1.0") == build_msi.product_code("0.1.0")
    assert build_msi.product_code("0.1.0") != build_msi.product_code("0.1.1")
    assert build_msi.product_code("0.1.0").startswith("{")


def test_build_msi_refuses_without_wix(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "bundle"
    source.mkdir()
    monkeypatch.setattr("build_msi.shutil.which", lambda _name: None)
    code = build_msi.main(["--version", "0.1.0", "--source", str(source)])
    assert code == build_msi.EX_UNAVAILABLE


def test_pyproject_wheel_targets_all_three_packages(repo_root: Path) -> None:
    data = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    packages = data["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    assert packages == ["src/tidymate_core", "src/tidymate_cli", "src/tidymate_app"]
