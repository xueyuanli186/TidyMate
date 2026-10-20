"""MSI build entry point - not implemented in stage 0.

Kept as an executable placeholder so the release workflow has a stable contract to call
once WiX v4 packaging lands:

    python build/build_msi.py --version 0.1.0 --archive dist/TidyMate-0.1.0-windows.zip

Today it exits with EX_UNAVAILABLE (69) and an explicit message. It deliberately does NOT
pretend to succeed: a green release job that silently ships no installer is exactly the
kind of "false success" the project forbids.
"""

from __future__ import annotations

import argparse
import sys

EX_UNAVAILABLE = 69


def main(argv: list[str] | None = None) -> int:
    """Parse the future interface, then refuse to do anything."""
    parser = argparse.ArgumentParser(description="build the TidyMate MSI (not implemented)")
    parser.add_argument("--version", default="0.0.0")
    parser.add_argument("--archive", default="")
    parser.parse_args(argv)

    print(
        "MSI packaging is not implemented yet (stage 0).\n"
        "Planned approach: PyInstaller onedir output + WiX v4 (see build/wix/README.md).\n"
        "Nothing was built. This is expected for this stage.",
        file=sys.stderr,
    )
    return EX_UNAVAILABLE


if __name__ == "__main__":
    raise SystemExit(main())
