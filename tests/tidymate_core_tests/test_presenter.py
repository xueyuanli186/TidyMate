"""Presenter tests: GUI logic without Qt."""

from __future__ import annotations

import textwrap
from pathlib import Path

from tidymate_app.presenter import (
    TABLE_HEADERS,
    export,
    is_conflict_row,
    run_dry_run,
    summary_text,
    table_rows,
)

RULES = """
rules:
  - id: images
    when: {ext: [".jpg"]}
    action: {op: move, template: "flat/{name}"}
"""


def test_missing_inputs_are_reported() -> None:
    assert run_dry_run("", "r.yaml", "out").error == "请先选择要整理的目录"
    assert run_dry_run("C:\\x", "", "out").error == "请先选择规则文件"
    assert run_dry_run("C:\\x", "r.yaml", "").error == "请先选择目标根目录"


def test_missing_directory_is_reported(tmp_path: Path) -> None:
    outcome = run_dry_run(str(tmp_path / "nope"), "r.yaml", "out")
    assert outcome.plan is None
    assert "目录不存在" in (outcome.error or "")


def test_invalid_rules_are_reported_not_raised(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    rules = tmp_path / "rules.yaml"
    rules.write_text("rules: nope\n", encoding="utf-8")

    outcome = run_dry_run(str(root), str(rules), str(tmp_path / "out"))
    assert outcome.plan is None
    assert "rules" in (outcome.error or "")


def test_successful_dry_run_produces_rows(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.jpg").write_bytes(b"x")
    (root / "b.txt").write_text("y", encoding="utf-8")
    rules = tmp_path / "rules.yaml"
    rules.write_text(textwrap.dedent(RULES), encoding="utf-8")

    outcome = run_dry_run(str(root), str(rules), str(tmp_path / "out"))
    assert outcome.plan is not None
    plan = outcome.plan

    rows = table_rows(plan)
    assert len(rows) == len(plan.changes)
    assert all(len(row) == len(TABLE_HEADERS) for row in rows)
    assert rows[0][1] == "execute"


def test_summary_text_contains_the_counters(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.jpg").write_bytes(b"x")
    rules = tmp_path / "rules.yaml"
    rules.write_text(textwrap.dedent(RULES), encoding="utf-8")

    outcome = run_dry_run(str(root), str(rules), str(tmp_path / "out"))
    assert outcome.plan is not None
    text = summary_text(outcome.plan)
    assert "扫描 1" in text
    assert outcome.plan.plan_hash[:12] in text


def test_conflict_and_reject_rows_are_marked(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "x").mkdir(parents=True)
    (root / "y").mkdir(parents=True)
    (root / "x" / "same.jpg").write_bytes(b"a")
    (root / "y" / "same.jpg").write_bytes(b"b")
    rules = tmp_path / "rules.yaml"
    rules.write_text(textwrap.dedent(RULES), encoding="utf-8")

    outcome = run_dry_run(str(root), str(rules), str(tmp_path / "out"))
    assert outcome.plan is not None
    plan = outcome.plan
    conflict_index = next(
        index for index, change in enumerate(plan.changes) if change.conflict.value != "none"
    )
    assert is_conflict_row(plan, conflict_index) is True
    assert is_conflict_row(plan, 0) is False
    assert is_conflict_row(plan, 999) is False


def test_export_writes_both_files(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.jpg").write_bytes(b"x")
    rules = tmp_path / "rules.yaml"
    rules.write_text(textwrap.dedent(RULES), encoding="utf-8")

    outcome = run_dry_run(str(root), str(rules), str(tmp_path / "out"))
    assert outcome.plan is not None
    plan_path, report_path = export(outcome.plan, str(tmp_path / "reports"))
    assert Path(plan_path).is_file()
    assert Path(report_path).is_file()
