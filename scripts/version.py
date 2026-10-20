"""Resolve and validate the single-source version.

Used by CI (to name artifacts), by the release workflow (to refuse a tag/version mismatch)
and by packaging scripts.

Exit codes:
    0  version printed / tag matched
    1  version file unreadable or tag mismatch
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = REPO_ROOT / "src" / "tidymate_core" / "_version.py"

# MAJOR.MINOR.PATCH only: WiX/MSI needs three numeric fields, and the git tag must be
# exactly "v" + this string.
_VERSION_PATTERN = re.compile(r'^__version__\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"\s*$', re.MULTILINE)


def read_version(path: Path = VERSION_FILE) -> str:
    """Return the version declared in *path*, or raise :class:`ValueError`."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read version file {path}: {exc}") from exc
    match = _VERSION_PATTERN.search(text)
    if match is None:
        raise ValueError(
            f"no MAJOR.MINOR.PATCH __version__ assignment found in {path}",
        )
    return match.group(1)


def main(argv: list[str] | None = None) -> int:
    """Print the version; optionally emit a GitHub Actions output or check a tag."""
    parser = argparse.ArgumentParser(description="TidyMate version helper")
    parser.add_argument(
        "--github-output",
        action="store_true",
        help="print 'version=X' (paste into $GITHUB_OUTPUT)",
    )
    parser.add_argument(
        "--assert-tag",
        metavar="TAG",
        default=None,
        help="fail unless TAG equals 'vVERSION' (used by the release workflow)",
    )
    args = parser.parse_args(argv)

    try:
        version = read_version()
    except ValueError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1

    if args.assert_tag is not None:
        tag = str(args.assert_tag).strip()
        expected = f"v{version}"
        if tag != expected:
            print(
                f"::error::release tag {tag!r} does not match version {expected!r} "
                f"(see src/tidymate_core/_version.py)",
                file=sys.stderr,
            )
            return 1
        print(f"OK: tag {tag} matches version {version}")

    if args.github_output:
        print(f"version={version}")
    else:
        print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
