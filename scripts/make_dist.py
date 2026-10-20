"""Build the stage-0 placeholder bundle and zip it.

This is the "packaging placeholder" required by stage 0: no PyInstaller yet, only the
directory layout and the naming contract that later stages must keep.

Contract:
    bundle directory : dist/TidyMate-<version>-windows/
    archive          : dist/TidyMate-<version>-windows.zip
    checksum         : dist/TidyMate-<version>-windows.zip.sha256
    artifact name    : TidyMate-<version>-windows   (set by ci.yml from the same version)

Design choices:
* the zip is written from an explicit file list, never by walking the output directory,
  so a stale file can never leak into a release artifact;
* zip entries get a fixed timestamp and mode, so two builds of the same version produce
  byte-identical archives (reproducible build, easy to diff in CI);
* nothing here deletes anything. Re-running overwrites files in place.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from tidymate_core._version import __version__  # noqa: E402

_LAUNCHER_CLI = """@echo off
setlocal
rem TidyMate CLI launcher (stage 0 placeholder).
rem A bundled python runtime replaces the interpreter on PATH in a later stage.
python -m tidymate_cli %*
endlocal
"""

_LAUNCHER_GUI = """@echo off
setlocal
rem TidyMate GUI launcher (stage 0 placeholder).
python -m tidymate_app.main %*
endlocal
"""

_BIN_README = """TidyMate - stage 0 placeholder bundle
=====================================

This directory is NOT a usable build. It exists so that the packaging, artifact naming
and checksum pipeline can be exercised end to end before any file-moving code exists.

What is real here:
  * the version, taken from src/tidymate_core/_version.py
  * the launcher contract (bin/tidymate.cmd runs the Typer CLI)
  * the archive name: TidyMate-<version>-windows.zip

What is not real yet:
  * no Python runtime is bundled (PyInstaller onedir lands in a later stage)
  * no MSI (WiX v4 lands in the release stage)
  * the launchers require "python" on PATH

Safety: this bundle contains no code that moves, deletes or writes user files.
"""


def bundle_dir_name(version: str) -> str:
    """Return the canonical bundle directory / artifact name."""
    return f"TidyMate-{version}-windows"


def _files(version: str) -> dict[str, bytes]:
    return {
        "BUNDLE.txt": _BIN_README.replace("\n", "\r\n").encode(),
        "VERSION.txt": f"TidyMate {version}\r\n".encode(),
        "bin/README.txt": _BIN_README.replace("\n", "\r\n").encode(),
        "bin/tidymate.cmd": _LAUNCHER_CLI.replace("\n", "\r\n").encode(),
        "bin/tidymate-gui.cmd": _LAUNCHER_GUI.replace("\n", "\r\n").encode(),
    }


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(filename=name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    info.create_system = 3  # unix, for a stable external_attr interpretation
    return info


def build(out_dir: Path = REPO_ROOT / "dist", version: str = __version__) -> tuple[Path, Path]:
    """Write the bundle directory and the zip; return ``(bundle, archive)``."""
    name = bundle_dir_name(version)
    bundle = out_dir / name
    archive = out_dir / f"{name}.zip"
    payload = _files(version)

    for relative, data in payload.items():
        target = bundle / Path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    archive.parent.mkdir(parents=True, exist_ok=True)
    compression = zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(archive, mode="w", compression=compression, compresslevel=9) as zf:
        for relative in sorted(payload):
            zf.writestr(_zip_info(f"{name}/{relative}"), payload[relative])
    return bundle, archive


def sha256_file(path: Path) -> str:
    """Return the hex sha256 of *path*."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 256), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    """Build the bundle, write the checksum file and print a summary."""
    parser = argparse.ArgumentParser(description="build the TidyMate placeholder bundle")
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / "dist")
    parser.add_argument("--version", default=__version__)
    args = parser.parse_args(argv)

    bundle, archive = build(out_dir=args.out_dir, version=str(args.version))
    checksum = sha256_file(archive)
    checksum_file = archive.with_name(archive.name + ".sha256")
    checksum_file.write_text(f"{checksum}  {archive.name}\n", encoding="utf-8")

    print(f"bundle : {bundle}")
    print(f"zip    : {archive} ({archive.stat().st_size} bytes)")
    print(f"sha256 : {checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
