"""TidyMate CLI entry point.

Stage 3-4 scope: ``--version``, ``status`` and the read-only ``plan`` command. There is no
``apply``, ``undo`` or ``verify`` command yet, and nothing here moves, renames, copies or
deletes a file. ``plan`` only writes when the user explicitly passes ``--export``, and even
then only ``plan.json`` / ``report.md`` are created (see ``planning.artifacts``).

``--version`` is part of the single-source-of-truth contract: it must print exactly the
value stored in :mod:`tidymate_core._version`, which is also the value CI resolves into
the artifact name and the release workflow checks against the git tag.
"""

from __future__ import annotations

from pathlib import Path

import typer

from tidymate_core._version import __version__
from tidymate_core.planning import PlanRequest, build_plan, render_table, write_artifacts
from tidymate_core.rules import RuleLoadError, load_rules
from tidymate_core.scanning import ScanConfig

app = typer.Typer(
    name="tidymate",
    help="TidyMate - local Windows file organiser. Dry-run by default; never deletes.",
    add_completion=False,
    no_args_is_help=True,
)


def _version_callback(value: bool) -> bool:
    if value:
        typer.echo(f"tidymate {__version__}")
        raise typer.Exit
    return value


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        help="Print the TidyMate version and exit.",
        is_eager=True,
        callback=_version_callback,
    ),
) -> None:
    """Global options shared by every subcommand."""


@app.command()
def status() -> None:
    """Report what this build can actually do (honest, stage 4)."""
    typer.echo(f"tidymate {__version__}")
    typer.echo("stage           : 4 (scan + rules + dry-run preview, read-only)")
    typer.echo("scanner         : streaming os.scandir, long-path aware, error tolerant")
    typer.echo("rules           : YAML, all-or-nothing validation, regex timeout 200 ms")
    typer.echo("planning        : templates, conflicts, ancestor/blacklist checks, plan_hash")
    typer.echo("journal         : not implemented yet")
    typer.echo("write commands  : none (this stage cannot modify user files)")
    typer.echo("network         : disabled (no network dependency is installed)")


@app.command()
def plan(
    root: Path = typer.Argument(..., help="Directory to scan (must exist)."),
    rules_path: Path = typer.Option(
        ...,
        "--rules",
        "-r",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Rule file (YAML). Invalid rules abort the whole run.",
    ),
    out_root: Path = typer.Option(
        ...,
        "--out-root",
        "-o",
        help="Root directory the templates are resolved against.",
    ),
    export: Path | None = typer.Option(
        None,
        "--export",
        "-e",
        help="If given, write plan.json and report.md into this directory.",
    ),
    limit: int = typer.Option(40, "--limit", help="Maximum table rows to print."),
) -> None:
    """Preview what the rules would do. Never modifies a file."""
    try:
        ruleset = load_rules(rules_path)
    except RuleLoadError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc

    request = PlanRequest(
        scan=ScanConfig(roots=(str(root),)),
        rules=ruleset,
        output_root=str(out_root),
    )
    result = build_plan(request)
    typer.echo(render_table(result, limit=limit))
    typer.echo("")
    typer.echo("dry-run only: no files were modified.")

    if export is not None:
        written = write_artifacts(result, str(export))
        typer.echo(f"plan.json : {written.plan_json}")
        typer.echo(f"report.md : {written.report_md}")
