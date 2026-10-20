"""Dry-run artifact writer - the ONLY product module allowed to write in stages 3-4.

Why this exception exists: a dry-run that cannot export ``plan.json`` and ``report.md`` is
not reviewable, and "copy the console output into an issue" is how numbers get lost. So the
project allows exactly one write path, with three hard constraints:

1. only the two fixed report names are ever created - a caller cannot pick a file name;
2. protected locations (``C:\\Windows``, Program Files, recycle bins...) are refused by the
   same hard-coded blacklist that guards file moves;
3. deletions and moves are still forbidden everywhere (see ``forbidden_apis``).

``readonly_guard.ALLOWED_MODULES`` names this file. Any other module that gains a write call
fails CI.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tidymate_core.planning.models import Plan
from tidymate_core.planning.report import plan_to_json, render_markdown
from tidymate_core.safety import paths
from tidymate_core.safety.blacklist import check_blacklisted

#: Fixed artifact names. A caller cannot choose arbitrary file names.
PLAN_FILENAME = "plan.json"
REPORT_FILENAME = "report.md"


class ArtifactError(ValueError):
    """The requested output location is not allowed."""


@dataclass(frozen=True, slots=True)
class ArtifactPaths:
    """Where the two artifacts ended up."""

    directory: str
    plan_json: Path
    report_md: Path


def _verify_destination(directory: str) -> str:
    """Refuse protected locations; allow any ordinary directory the user picked."""
    normalized = paths.normalize(directory)
    blacklisted = check_blacklisted(normalized)
    if blacklisted is not None:
        raise ArtifactError(
            f"refusing to write artifacts into a protected location: "
            f"{normalized!r} is inside {blacklisted}",
        )
    return normalized


def write_artifacts(
    plan: Plan,
    directory: str,
    *,
    write_json: bool = True,
    write_markdown: bool = True,
) -> ArtifactPaths:
    """Write ``plan.json`` and/or ``report.md`` under *directory*.

    Raises:
        ArtifactError: when *directory* is a protected location.
    """
    target_dir = _verify_destination(directory)
    path = Path(target_dir)
    path.mkdir(parents=True, exist_ok=True)

    plan_path = path / PLAN_FILENAME
    report_path = path / REPORT_FILENAME
    if write_json:
        plan_path.write_text(plan_to_json(plan) + "\n", encoding="utf-8", newline="\n")
    if write_markdown:
        report_path.write_text(render_markdown(plan), encoding="utf-8", newline="\n")
    return ArtifactPaths(directory=target_dir, plan_json=plan_path, report_md=report_path)
