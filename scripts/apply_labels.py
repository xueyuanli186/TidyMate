"""Apply the labels declared in .github/labels.yml to the GitHub repository.

Requires the GitHub CLI (``gh``) to be installed and authenticated. Using a local script
instead of a third-party action keeps the supply chain surface at zero and works the same
way on a laptop and in CI.

Usage:
    python scripts/apply_labels.py --dry-run
    python scripts/apply_labels.py
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
LABELS_FILE = REPO_ROOT / ".github" / "labels.yml"

_REQUIRED_KEYS = ("name", "color", "description")


def load_labels(path: Path = LABELS_FILE) -> list[dict[str, str]]:
    """Parse and validate labels.yml; raise SystemExit on malformed input."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"cannot read {path}: {exc}") from exc
    if not isinstance(raw, list):
        raise SystemExit(f"{path} must contain a YAML list of labels")

    labels: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw, start=1):
        if not isinstance(entry, dict):
            raise SystemExit(f"{path}: entry #{index} is not a mapping")
        label = {key: str(entry.get(key, "")) for key in _REQUIRED_KEYS}
        missing = [key for key, value in label.items() if not value]
        if missing:
            raise SystemExit(f"{path}: entry #{index} is missing {', '.join(missing)}")
        if len(label["color"]) != 6:
            raise SystemExit(f"{path}: {label['name']} colour must be 6 hex chars")
        if label["name"] in seen:
            raise SystemExit(f"{path}: duplicate label {label['name']!r}")
        seen.add(label["name"])
        labels.append(label)
    return labels


def apply(labels: list[dict[str, str]], *, gh: str = "gh", dry_run: bool = False) -> int:
    """Create/update every label; returns a process exit code."""
    if not dry_run and shutil.which(gh) is None:
        print("gh CLI not found; install GitHub CLI or use --dry-run", file=sys.stderr)
        return 127
    for label in labels:
        command = [
            gh,
            "label",
            "create",
            label["name"],
            "--color",
            label["color"],
            "--description",
            label["description"],
            "--force",
        ]
        if dry_run:
            print("DRY-RUN:", " ".join(command))
            continue
        # Fixed argv, no shell: the label text comes from a repository file we control.
        subprocess.run(command, check=True)
    print(f"applied {len(labels)} labels")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="sync .github/labels.yml to GitHub")
    parser.add_argument("--dry-run", action="store_true", help="print commands only")
    parser.add_argument("--gh", default="gh", help="path to the gh executable")
    args = parser.parse_args(argv)
    return apply(load_labels(), gh=str(args.gh), dry_run=bool(args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
