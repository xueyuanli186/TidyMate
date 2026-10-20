"""TidyMate CLI entry point.

Stage 0 scope: ``--version`` and ``status`` only. No scan, plan, apply, undo or verify
command exists yet, and no command in this file may write to the file system until the
dry-run gate of stage 3 is implemented.

``--version`` is part of the single-source-of-truth contract: it must print exactly the
value stored in :mod:`tidymate_core._version`, which is also the value CI resolves into
the artifact name and the release workflow checks against the git tag.
"""

from __future__ import annotations

import typer

from tidymate_core._version import __version__

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
    """Report what this build can actually do (honest, stage 0)."""
    typer.echo(f"tidymate {__version__}")
    typer.echo("stage           : 0 (skeleton)")
    typer.echo("journal         : not implemented yet")
    typer.echo("write commands  : none (dry-run only by construction)")
    typer.echo("network         : disabled (no network dependency is installed)")
