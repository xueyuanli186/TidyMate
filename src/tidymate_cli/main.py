"""TidyMate CLI entry point.

Stage 5-6 adds the first write-capable command, ``apply``. It is deliberately hard to
invoke by accident: a batch must have a stored preview with the same ``plan_hash``, every
gate must pass, and the user types ``YES`` (``--yes`` exists for tests and CI and skips the
typing prompt only - never a gate).
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import typer

from tidymate_core._version import __version__
from tidymate_core.execution import (
    ExecutionOptions,
    Executor,
    GateResult,
    evaluate,
)
from tidymate_core.journal import BatchAlreadyAppliedError, Journal, JournalError
from tidymate_core.planning import PlanRequest, build_plan, render_table, write_artifacts
from tidymate_core.planning.models import ChangeStatus, ConflictType, Plan
from tidymate_core.rules import ConflictPolicy, RuleLoadError, load_rules
from tidymate_core.safety import blacklist
from tidymate_core.scanning import ScanConfig

FIRST_RUN_BANNER = """
============================================================
  TidyMate 第一次运行
============================================================
本工具会移动你的文件。请第一次先在测试目录演练，重要数据请先备份。
删除只进回收站，所有操作可按批次撤销。

一键生成演练目录：pwsh -File scripts/make-sandbox.ps1
============================================================
"""

app = typer.Typer(
    name="tidymate",
    help="TidyMate - local Windows file organiser. Dry-run by default; never deletes.",
    add_completion=False,
    no_args_is_help=True,
)


def _default_db() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "TidyMate" / "tidymate.db"


def _open_journal(db: Path, *, protect_dir: bool = False) -> Journal:
    blacklist.register_protected_file(str(db))
    if protect_dir:
        # The default journal lives in TidyMate's own folder; a user-supplied --db may sit
        # next to their data, and protecting its parent would block legitimate targets.
        blacklist.register_protected_path(str(db.parent))
    return Journal(db)


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
    """Report what this build can actually do (honest, stage 5-6)."""
    typer.echo(f"tidymate {__version__}")
    typer.echo("stage           : 5-6 (conflicts + executor)")
    typer.echo(
        "scanner         : streaming os.scandir, long-path aware, ADS/OneDrive/reparse aware"
    )
    typer.echo("rules           : YAML, all-or-nothing validation, regex timeout 200 ms")
    typer.echo("planning        : templates, conflicts, ancestor/blacklist checks, plan_hash")
    typer.echo("journal         : SQLite (WAL), write-ahead per operation")
    typer.echo("write commands  : apply (gated, journaled, recycle-bin only)")
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
    db: Path | None = typer.Option(
        None, "--db", help="Journal database (default: %LOCALAPPDATA%)."
    ),
    conflict: ConflictPolicy | None = typer.Option(
        None,
        "--conflict",
        help="Override every rule's conflict policy (skip / rename / ask).",
    ),
    clear_readonly: bool = typer.Option(
        False,
        "--clear-readonly",
        help="Allow read-only files into the plan (the executor clears the bit).",
    ),
    yes: bool = typer.Option(False, "--yes", help="Skip the first-run prompt (tests/CI)."),
) -> None:
    """Preview what the rules would do, and record the preview for ``apply``."""
    db_path = db or _default_db()
    if not db_path.exists() and not yes:
        typer.echo(FIRST_RUN_BANNER)
        answer = typer.prompt("输入 YES 表示你已在测试目录演练或已备份")
        if answer.strip().upper() != "YES":
            typer.echo("已取消（没有扫描、没有写日志）。", err=True)
            raise typer.Exit(code=1)

    journal = _open_journal(db_path, protect_dir=db is None)
    try:
        if not yes and not journal.has_any_batch():
            typer.echo(FIRST_RUN_BANNER)
            answer = typer.prompt("输入 YES 表示你已在测试目录演练或已备份")
            if answer.strip().upper() != "YES":
                typer.echo("已取消（没有扫描、没有写日志）。", err=True)
                raise typer.Exit(code=1)

        try:
            ruleset = load_rules(rules_path)
        except RuleLoadError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from exc

        request = PlanRequest(
            scan=ScanConfig(roots=(str(root),)),
            rules=ruleset,
            output_root=str(out_root),
            conflict_override=conflict,
            clear_readonly=clear_readonly,
        )
        result = build_plan(request)
        journal.record_preview(result)
    finally:
        journal.close()

    typer.echo(render_table(result, limit=limit))
    typer.echo("")
    typer.echo(f"dry-run only: no files were modified.  batch={result.batch_id}")

    if export is not None:
        written = write_artifacts(result, str(export))
        typer.echo(f"plan.json : {written.plan_json}")
        typer.echo(f"report.md : {written.report_md}")


def _describe_plan(plan: Plan) -> tuple[int, int, int, str]:
    """Return (executable, directories, trash, conflict-policy label)."""
    executable = [c for c in plan.changes if c.is_executable]
    directories = {str(Path(c.dst).parent) for c in executable if c.dst is not None}
    trash = sum(1 for c in executable if (c.op or "").lower() == "trash")
    rename_override = any("overridden to 'rename'" in warning for warning in plan.warnings)
    policy = "rename (自动改名，不覆盖任何已有文件)" if rename_override else "per-rule (skip 默认)"
    return len(executable), len(directories), trash, policy


def _ask_review(plan: Plan, journal: Journal, options: ExecutionOptions) -> Plan | None:
    """Turn ``ask`` conflicts into decisions; ``None`` means the user aborted."""
    reviewed = list(plan.changes)
    skip_all = False
    for index, change in enumerate(reviewed):
        if change.conflict is not ConflictType.NEEDS_REVIEW:
            continue
        if skip_all:
            reviewed[index] = replace(
                change,
                status=ChangeStatus.SKIP,
                error_kind="ask_skipped",
                notes=(*change.notes, "skipped by user (s)"),
            )
            continue
        typer.echo("")
        typer.echo(f"冲突 seq {change.seq}: {change.src}")
        typer.echo(f"           -> {change.dst}")
        answer = typer.prompt("  [y]执行 / [n]跳过 / [s]全部跳过 / [q]退出", default="n")
        key = answer.strip().lower()[:1]
        if key == "y":
            reviewed[index] = replace(
                change,
                status=ChangeStatus.EXECUTE,
                conflict=ConflictType.NONE,
            )
        elif key == "q":
            typer.echo("已退出；已完成的条目全部在日志里，可撤销。", err=True)
            journal.mark_finished(plan.batch_id, "aborted")
            return None
        elif key == "s":
            skip_all = True
            reviewed[index] = replace(
                change,
                status=ChangeStatus.SKIP,
                error_kind="ask_skipped",
                notes=(*change.notes, "skipped by user (s)"),
            )
        else:
            reviewed[index] = replace(
                change,
                status=ChangeStatus.SKIP,
                error_kind="ask_skipped",
                notes=(*change.notes, "skipped by user"),
            )
    del options
    return replace(plan, changes=tuple(reviewed))


@app.command()
def apply(
    batch_id: str = typer.Argument(..., help="Batch id printed by `plan`."),
    db: Path | None = typer.Option(
        None, "--db", help="Journal database (default: %LOCALAPPDATA%)."
    ),
    yes: bool = typer.Option(False, "--yes", help="Skip the YES prompt (tests/CI)."),
    limit: int | None = typer.Option(None, "--limit", help="Only the first N operations."),
    only_rule: str | None = typer.Option(None, "--only-rule", help="Only this rule id."),
    allow_unc: bool = typer.Option(False, "--allow-unc", help="Allow UNC/network paths."),
    clear_readonly: bool = typer.Option(
        False,
        "--clear-readonly",
        help="Clear the read-only bit before operating (warned separately).",
    ),
) -> None:
    """Execute a previously previewed batch. This is the only command that writes files."""
    journal = _open_journal(db or _default_db(), protect_dir=db is None)
    try:
        plan = journal.load_plan(batch_id)
        if plan is None:
            typer.echo(f"未知批次 {batch_id!r}：请先运行 plan。", err=True)
            raise typer.Exit(code=2)

        options = ExecutionOptions(
            limit=limit,
            only_rule=only_rule,
            clear_readonly=clear_readonly,
            allow_unc=allow_unc,
        )
        gate: GateResult = evaluate(plan, journal, options)
        if not gate.ok:
            typer.echo("整批拒绝执行（门禁未通过）：", err=True)
            for problem in gate.problems:
                typer.echo(f"  - {problem.render()}", err=True)
            raise typer.Exit(code=3)

        count, directories, trash, policy = _describe_plan(plan)
        typer.echo(f"将执行 {count} 条，涉及 {directories} 个目录，其中 trash {trash} 条。")
        typer.echo(f"冲突策略：{policy}")
        if clear_readonly:
            typer.echo("注意：--clear-readonly 会清除源文件的只读属性。", err=True)

        if not yes:
            answer = typer.prompt("确认执行请输入 YES")
            if answer.strip().upper() != "YES":
                typer.echo("已取消，没有修改任何文件。", err=True)
                raise typer.Exit(code=1)

        reviewed = _ask_review(plan, journal, options)
        if reviewed is None:
            raise typer.Exit(code=1)

        executor = Executor(
            journal,
            options,
            on_event=lambda change, outcome: typer.echo(
                f"  {change.seq:>4} {outcome.state.value:<10} "
                f"{change.src} -> {outcome.final_dst or '-'}"
                + (f"  [{outcome.error_kind}] {outcome.error}" if outcome.error else ""),
            ),
        )
        report = executor.run(reviewed)
    except BatchAlreadyAppliedError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=4) from exc
    except JournalError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    finally:
        journal.close()

    counts = report.counts
    typer.echo("")
    typer.echo(
        f"完成：ok={counts['ok']} failed={counts['failed']} "
        f"skipped={counts['skipped']} interrupted={counts['interrupted']}",
    )
    if report.cancelled:
        typer.echo("已取消：已完成的部分都在日志里，可撤销。", err=True)
    if report.fused:
        typer.echo("熔断：连续失败过多，已暂停。请检查磁盘/权限后重试。", err=True)
    if counts["failed"]:
        raise typer.Exit(code=1)


__all__ = ["app"]
