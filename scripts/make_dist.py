"""Build the Windows bundle with PyInstaller and zip it (stage 9).

Contract (unchanged from stage 0, so CI and the release workflow keep working):

    bundle directory : dist/TidyMate-<version>-windows/
    archive          : dist/TidyMate-<version>-windows.zip
    checksum         : dist/TidyMate-<version>-windows.zip.sha256

Layout inside the bundle::

    TidyMate-<version>-windows/
        TidyMate.exe        windowed GUI
        _internal/          Qt and Python runtime
        cli/
            tidymate.exe    console CLI (own runtime under cli/_internal)

Two *independent* PyInstaller builds are used on purpose. A single spec with two EXEs and
one shared PYZ produced an executable that hung before printing anything; separate onedir
trees are larger but each executable is known-good (the CLI one is smoke-tested in CI).

Nothing here deletes user data: PyInstaller owns its own output directory (``--noconfirm``
lets it refresh), and this script only adds files.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from tidymate_core._version import __version__  # noqa: E402

EX_UNAVAILABLE = 69


def bundle_dir_name(version: str) -> str:
    """Return the canonical bundle directory / artifact name."""
    return f"TidyMate-{version}-windows"


def sha256_file(path: Path) -> str:
    """Return the hex sha256 of *path*."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 256), b""):
            digest.update(chunk)
    return digest.hexdigest()


def zip_bundle(bundle: Path, archive: Path) -> None:
    """Zip *bundle* into *archive*, one top-level directory, no absolute paths."""
    if not bundle.is_dir():
        raise FileNotFoundError(f"bundle directory does not exist: {bundle}")
    archive.parent.mkdir(parents=True, exist_ok=True)
    name = bundle.name
    compression = zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(archive, mode="w", compression=compression, compresslevel=9) as zf:
        for path in sorted(bundle.rglob("*")):
            if path.is_file():
                relative = path.relative_to(bundle).as_posix()
                zf.write(path, arcname=f"{name}/{relative}")


def _run_pyinstaller(
    *,
    entry: str,
    name: str,
    windowed: bool,
    dist_path: Path,
) -> None:
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name",
        name,
        "--paths",
        str(REPO_ROOT / "src"),
        "--distpath",
        str(dist_path),
        "--workpath",
        str(REPO_ROOT / "build" / "pyinstaller" / name),
        "--specpath",
        str(REPO_ROOT / "build" / "specs"),
        "--windowed" if windowed else "--console",
        str(REPO_ROOT / "build" / entry),
    ]
    result = subprocess.run(command, cwd=REPO_ROOT, check=False)  # noqa: S603 - fixed argv
    if result.returncode != 0:
        raise RuntimeError(
            f"PyInstaller failed for {name!r}; install it with `python -m pip install pyinstaller`",
        )


def _normalise_layout(bundle: Path, name: str) -> None:
    """Turn PyInstaller's default names into the documented layout.

    * the GUI executable is renamed from ``<bundle-name>.exe`` to ``TidyMate.exe``;
    * the CLI tree is lifted from ``cli/tidymate/*`` to ``cli/*`` so its ``_internal``
      sits next to ``tidymate.exe`` (PyInstaller resolves it relative to the exe).
    """
    gui_exe = bundle / f"{name}.exe"
    target = bundle / "TidyMate.exe"
    if gui_exe.exists() and not target.exists():
        gui_exe.rename(target)

    nested = bundle / "cli" / "tidymate"
    if nested.is_dir():
        for item in list(nested.iterdir()):
            destination = bundle / "cli" / item.name
            if not destination.exists():
                item.rename(destination)
        nested.rmdir()


def build(
    out_dir: Path = REPO_ROOT / "dist",
    version: str = __version__,
    *,
    run_pyinstaller: bool = True,
) -> tuple[Path, Path]:
    """Build the GUI + CLI onedir trees and the zip; return ``(bundle, archive)``."""
    name = bundle_dir_name(version)
    bundle = out_dir / name
    archive = out_dir / f"{name}.zip"
    out_dir.mkdir(parents=True, exist_ok=True)

    if run_pyinstaller:
        _run_pyinstaller(
            entry="entry_gui.py",
            name=name,
            windowed=True,
            dist_path=out_dir,
        )
        _run_pyinstaller(
            entry="entry_cli.py",
            name="tidymate",
            windowed=False,
            dist_path=bundle / "cli",
        )

    if not bundle.is_dir():
        raise RuntimeError(f"PyInstaller produced no bundle at {bundle}")

    _normalise_layout(bundle, name)
    (bundle / "VERSION.txt").write_text(f"TidyMate {version}\r\n", encoding="utf-8")
    zip_bundle(bundle, archive)
    return bundle, archive


def main(argv: list[str] | None = None) -> int:
    """Build the bundle, write the checksum file and print a summary."""
    parser = argparse.ArgumentParser(description="build the TidyMate Windows bundle")
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / "dist")
    parser.add_argument("--version", default=__version__)
    parser.add_argument(
        "--no-pyinstaller",
        action="store_true",
        help="Reuse an existing bundle directory (debugging only).",
    )
    args = parser.parse_args(argv)

    try:
        bundle, archive = build(
            out_dir=args.out_dir,
            version=str(args.version),
            run_pyinstaller=not args.no_pyinstaller,
        )
    except (RuntimeError, FileNotFoundError) as exc:
        print(f"build failed: {exc}", file=sys.stderr)
        return EX_UNAVAILABLE

    checksum = sha256_file(archive)
    checksum_file = archive.with_name(archive.name + ".sha256")
    checksum_file.write_text(f"{checksum}  {archive.name}\n", encoding="utf-8")

    print(f"bundle : {bundle}")
    print(f"zip    : {archive} ({archive.stat().st_size} bytes)")
    print(f"sha256 : {checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
