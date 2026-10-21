"""TidyMate CLI entry point.

Stage 5-6 adds the first write-capable command, ``apply``. It is deliberately hard to
invoke by accident: a batch must have a stored preview with the same ``plan_hash``, every
gate must pass, and the user types ``YES`` (``--yes`` exists for tests and CI and skips the
typing prompt only - never a gate).
"""

from __future__ import annotations

import contextlib
import os
from dataclasses import replace
from pathlib import Path

import typer

from tidymate_core import presets
from tidymate_core._version import __version__
from tidymate_core.execution import (
    ExecutionOptions,
    Executor,
    GateResult,
    Undoer,
    evaluate,
    verify_batch,
    write_reports,
)
from tidymate_core.journal import (
    BatchAlreadyAppliedError,
    BatchAlreadyUndoneError,
    Journal,
    JournalError,
)
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
    del version
    # First run: copy the shipped presets into the user rule directory so they can be
    # edited. Existing files are never overwritten.
    with contextlib.suppress(OSError):
        presets.install_presets_if_missing()


@app.command()
def status(
    db: Path | None = typer.Option(None, "--db", help="Journal database."),
) -> None:
    """Report the build capabilities and the most recent batch (SQL aggregation)."""
    typer.echo(f"tidymate {__version__}")
    typer.echo("stage           : 7-9 (journal + undo + error reports)")
    typer.echo(
        "scanner         : streaming os.scandir, long-path aware, ADS/OneDrive/reparse aware"
    )
    typer.echo("rules           : YAML, all-or-nothing validation, regex timeout 200 ms")
    typer.echo("planning        : templates, conflicts, ancestor/blacklist checks, plan_hash")
    typer.echo("journal         : SQLite (WAL, busy_timeout 5000), write-ahead per operation")
    typer.echo("write commands  : apply / undo (gated, journaled, recycle-bin only)")
    typer.echo("network         : disabled (no network dependency is installed)")
    db_path = db or _default_db()
    if not db_path.exists():
        typer.echo("batches         : none yet")
        return
    journal = _open_journal(db_path, protect_dir=db is None)
    try:
        latest = journal.latest_batch()
        if latest is None:
            typer.echo("batches         : none yet")
            return
        if journal.batch_status(latest) == "running":
            recovered = journal.recover(latest)
            journal.mark_finished(latest, "partial")
            typer.echo(f"recovered       : {recovered} interrupted operation(s) marked partial")
        stats = journal.refresh_stats(latest)
        typer.echo(
            f"latest batch    : {latest} [{journal.batch_status(latest)}] "
            f"total={stats['total']} ok={stats['ok']} failed={stats['failed']} "
            f"skipped={stats['skipped']} undo={stats['undo_ok']}/{stats['undo_total']}",
        )
    finally:
        journal.close()


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
        journal.record_preview(
            result,
            roots=(str(root),),
            rules_file=str(rules_path),
            rules_hash=__import__("hashlib").sha256(rules_path.read_bytes()).hexdigest(),
            conflict_policy=conflict.value if conflict is not None else None,
            app_version=__version__,
        )
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
        report_paths = write_reports(
            journal,
            plan.batch_id,
            (db or _default_db()).parent / "reports",
        )
        attempts = 0
        while report.fused and not yes and attempts < 2:
            answer = typer.prompt(
                "连续失败过多，已暂停。继续执行剩余条目？[y/N]",
                default="n",
            )
            if answer.strip().lower() not in {"y", "yes"}:
                break
            attempts += 1
            follow = Executor(journal, options, on_event=executor._on_event).run(reviewed)
            report.outcomes.extend(follow.outcomes)
            report.fused = follow.fused
            report.cancelled = report.cancelled or follow.cancelled
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
    if report_paths is not None:
        typer.echo(f"errors.md : {report_paths.markdown}")
        typer.echo(f"errors.json: {report_paths.json}")
    if counts["failed"]:
        raise typer.Exit(code=1)


@app.command("list-batches")
def list_batches(
    db: Path | None = typer.Option(None, "--db"),
    limit: int = typer.Option(20, "--limit"),
) -> None:
    """List recent batches with the SQL-aggregated counters."""
    journal = _open_journal(db or _default_db(), protect_dir=db is None)
    try:
        rows = journal.list_batches(limit)
    finally:
        journal.close()
    if not rows:
        typer.echo("还没有任何批次。先运行 `plan`。")
        return
    header = (
        f"{'batch_id':<26} {'mode':<7} {'status':<12} "
        f"{'total':>5} {'ok':>4} {'failed':>6} {'undo':>5}"
    )
    typer.echo(header)
    for row in rows:
        typer.echo(
            f"{row['batch_id']!s:<26} {row['mode']!s:<7} {row['status']!s:<12} "
            f"{row['total']!s:>5} {row['ok']!s:>4} {row['failed']!s:>6} "
            f"{row['undo_ok']!s}/{row['undo_total']!s}",
        )


@app.command("show-batch")
def show_batch(
    batch_id: str,
    db: Path | None = typer.Option(None, "--db"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Show one batch: counters from SQL plus every operation row."""
    journal = _open_journal(db or _default_db(), protect_dir=db is None)
    try:
        batch = journal.batch_row(batch_id)
        if batch is None:
            typer.echo(f"未知批次 {batch_id!r}", err=True)
            raise typer.Exit(code=2)
        stats = journal.agg_stats(batch_id)
        rows = journal.operations(batch_id)
    finally:
        journal.close()
    if as_json:
        typer.echo(
            __import__("json").dumps(
                {"batch": batch, "summary": stats, "operations": rows},
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
        )
        return
    typer.echo(f"batch   : {batch_id}")
    typer.echo(f"mode    : {batch['mode']}   status: {batch['status']}")
    typer.echo(f"summary : {stats}")
    for row in rows:
        typer.echo(
            f"  {row['seq']:>4} {row['op']!s:<6} {row['state']!s:<12} "
            f"{row['src']} -> {row['final_dst'] or row['dst'] or '-'}"
            + (f"  [{row['error_kind']}] {row['error']}" if row["error"] else ""),
        )


@app.command()
def undo(
    batch_id: str,
    db: Path | None = typer.Option(None, "--db"),
    yes: bool = typer.Option(False, "--yes", help="Skip the YES prompt (tests/CI)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Only show what would be rolled back."),
) -> None:
    """Roll a batch back. Dry-run by default; never overwrites."""
    journal = _open_journal(db or _default_db(), protect_dir=db is None)
    report_paths = None
    try:
        if journal.load_plan(batch_id) is None:
            typer.echo(f"未知批次 {batch_id!r}", err=True)
            raise typer.Exit(code=2)
        undoer = Undoer(
            journal,
            on_event=lambda _row, outcome: typer.echo(
                f"  {outcome.seq:>4} {outcome.state:<12} {outcome.src} -> {outcome.dst or '-'}"
                + (f"  [{outcome.error_kind}] {outcome.error}" if outcome.error else ""),
            ),
        )
        preview = undoer.run(batch_id, dry_run=True)
        typer.echo(f"将回滚 {len(preview.outcomes)} 条（降序，逐条校验 size/mtime）。")
        blocked = [o for o in preview.outcomes if o.error_kind]
        for outcome in blocked:
            typer.echo(f"  ! seq {outcome.seq}: {outcome.error_kind} - {outcome.error}")
        if dry_run:
            for outcome in preview.outcomes:
                typer.echo(f"  {outcome.seq:>4} {outcome.state:<12} {outcome.src}")
            return
        if not yes:
            answer = typer.prompt("确认撤销请输入 YES")
            if answer.strip().upper() != "YES":
                typer.echo("已取消，没有修改任何文件。", err=True)
                raise typer.Exit(code=1)
        report = undoer.run(batch_id)
        report_paths = write_reports(
            journal,
            batch_id,
            (db or _default_db()).parent / "reports",
        )
        typer.echo(
            f"撤销完成：undone={report.undone} failed={report.failed} status={report.status}",
        )
    except BatchAlreadyUndoneError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=4) from exc
    except JournalError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    finally:
        journal.close()
    if report_paths is not None:
        typer.echo(f"errors.md : {report_paths.markdown}")
    if report.failed:
        raise typer.Exit(code=1)


@app.command()
def verify(
    batch_id: str,
    db: Path | None = typer.Option(None, "--db"),
    sample: int | None = typer.Option(None, "--sample", help="Only check the first N rows."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Check the file system against the journal (evidence for undo)."""
    journal = _open_journal(db or _default_db(), protect_dir=db is None)
    try:
        problems = verify_batch(journal, batch_id, sample=sample)
    finally:
        journal.close()
    if as_json:
        typer.echo(
            __import__("json").dumps(
                [{"seq": p.seq, "code": p.code, "message": p.message} for p in problems],
                ensure_ascii=False,
                indent=2,
            ),
        )
    else:
        for problem in problems:
            typer.echo(problem.render())
        typer.echo(f"verify: {len(problems)} inconsistency(ies)")
    if problems:
        raise typer.Exit(code=1)


@app.command("list-presets")
def list_presets_command() -> None:
    """List the rule presets shipped with TidyMate."""
    entries = presets.list_presets()
    if not entries:
        typer.echo(f"没有找到预置规则（{presets.presets_root()}）。")
        return
    typer.echo(f"{'id':<28} {'名称':<18} 标签")
    for preset in entries:
        typer.echo(f"{preset.preset_id:<28} {preset.name:<18} {', '.join(preset.tags)}")


@app.command("list-rules")
def list_rules_command() -> None:
    """List the user's editable rule files."""
    paths = presets.list_user_rules()
    typer.echo(f"规则目录：{presets.user_rules_dir()}")
    if not paths:
        typer.echo("还没有自定义规则。用 `use-preset <name>` 复制一条开始修改。")
        return
    for path in paths:
        meta = presets.parse_metadata(path.read_text(encoding="utf-8"))
        typer.echo(f"{path.name:<32} {meta.get('name', path.stem)}")


@app.command("use-preset")
def use_preset(
    name: str = typer.Argument(..., help="Preset id or display name."),
    root: Path = typer.Argument(..., help="Directory to scan."),
    out_root: Path = typer.Option(..., "--out-root", "-o"),
    db: Path | None = typer.Option(None, "--db"),
    yes: bool = typer.Option(False, "--yes", help="Skip the first-run prompt."),
) -> None:
    """Copy a preset into the user rule directory and preview it against a directory."""
    preset = presets.find_preset(name)
    if preset is None:
        typer.echo(f"未知预置规则 {name!r}；用 `list-presets` 查看可用项。", err=True)
        raise typer.Exit(code=2)

    target = presets.user_rules_dir() / f"{preset.preset_id}.yaml"
    if not target.exists():
        target = presets.copy_preset(preset.preset_id)
    typer.echo(f"规则文件：{target}")

    db_path = db or _default_db()
    if not db_path.exists() and not yes:
        typer.echo(FIRST_RUN_BANNER)
        answer = typer.prompt("输入 YES 表示你已在测试目录演练或已备份")
        if answer.strip().upper() != "YES":
            typer.echo("已取消（没有扫描、没有写日志）。", err=True)
            raise typer.Exit(code=1)

    journal = _open_journal(db_path, protect_dir=db is None)
    try:
        try:
            ruleset = load_rules(target)
        except RuleLoadError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from exc
        request = PlanRequest(
            scan=ScanConfig(roots=(str(root),)),
            rules=ruleset,
            output_root=str(out_root),
        )
        result = build_plan(request)
        journal.record_preview(
            result,
            roots=(str(root),),
            rules_file=str(target),
            app_version=__version__,
        )
    finally:
        journal.close()

    typer.echo(render_table(result, limit=40))
    typer.echo("")
    typer.echo(f"dry-run only: no files were modified.  batch={result.batch_id}")


__all__ = ["app"]
