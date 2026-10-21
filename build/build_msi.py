"""Build the TidyMate MSI with WiX v4 (stage 9).

Interface kept from the stage-0 placeholder so CI and the release workflow do not change:

    python build/build_msi.py --version 0.1.0 \
        --source dist/TidyMate-0.1.0-windows \
        --output dist/TidyMate-0.1.0-windows.msi

When WiX v4 is missing this exits with EX_UNAVAILABLE and says how to install it. It never
pretends to have produced an installer.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EX_UNAVAILABLE = 69
EX_SOFTWARE = 70

_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_NAMESPACE = uuid.UUID("6f2a9c1e-4b7d-4e83-9c0a-2f5b8d7e1a34")


def product_code(version: str) -> str:
    """Return a stable ProductCode for *version*.

    WiX generates a random ProductCode per build unless one is supplied. Two builds of the
    same version then appear as two products in "Apps & features" and ``msiexec /x`` by
    path cannot remove the installed one (error 1605). A version-derived UUID keeps the
    code stable for a release and different for the next one.
    """
    return "{" + str(uuid.uuid5(_NAMESPACE, f"TidyMate-{version}")).upper() + "}"


def normalize_version(raw: str) -> str:
    """Return the MSI-legal ``MAJOR.MINOR.PATCH`` form of *raw*.

    MSI rejects pre-release suffixes, so ``0.1.0.dev1`` becomes ``0.1.0``. The full
    version still appears in the bundle name and in ``tidymate --version``.
    """
    parts = re.split(r"[.\-+]", raw.strip())
    numeric = [part for part in parts if part.isdigit()]
    while len(numeric) < 3:
        numeric.append("0")
    candidate = ".".join(numeric[:3])
    if not _VERSION_RE.match(candidate):
        raise ValueError(f"cannot normalise version {raw!r}")
    return candidate


def main(argv: list[str] | None = None) -> int:
    """Run ``wix build`` against the PyInstaller bundle."""
    parser = argparse.ArgumentParser(description="build the TidyMate MSI with WiX v4")
    parser.add_argument("--version", required=True)
    parser.add_argument("--source", required=True, help="PyInstaller onedir bundle")
    parser.add_argument("--output", default="")
    args = parser.parse_args(argv)

    source = Path(args.source).resolve()
    if not source.is_dir():
        print(f"source bundle does not exist: {source}", file=sys.stderr)
        return EX_UNAVAILABLE

    wix = shutil.which("wix")
    if wix is None:
        print(
            "WiX v4 is not installed.\n"
            "Install it with:  dotnet tool install --global wix\n"
            "Then ensure %USERPROFILE%\\.dotnet\\tools is on PATH.",
            file=sys.stderr,
        )
        return EX_UNAVAILABLE

    version = normalize_version(args.version)
    output = Path(args.output).resolve() if args.output else source.parent / f"{source.name}.msi"
    output.parent.mkdir(parents=True, exist_ok=True)

    command = [
        wix,
        "build",
        str(REPO_ROOT / "build" / "wix" / "TidyMate.wxs"),
        "-d",
        f"Version={version}",
        "-d",
        f"SourceDir={source}",
        "-d",
        f"ProductCode={product_code(version)}",
        "-arch",
        "x64",
        "-o",
        str(output),
    ]
    result = subprocess.run(command, check=False)  # noqa: S603 - fixed argv, no shell
    if result.returncode != 0:
        print(f"wix build failed with exit code {result.returncode}", file=sys.stderr)
        return result.returncode
    if not output.exists():
        print(f"wix reported success but produced no MSI at {output}", file=sys.stderr)
        return EX_SOFTWARE

    print(f"msi    : {output} ({output.stat().st_size} bytes)")
    print(f"version: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
