"""Qt smoke tests, run head-less via the offscreen platform.

Skipped when the optional PySide6 extra is not installed, which keeps CI light: the GUI is
verified on a machine that opts into ``pip install -e ".[gui]"``.
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from tidymate_app.main_window import MainWindow

RULES = """
rules:
  - id: images
    when: {ext: [".jpg"]}
    action: {op: move, template: "flat/{name}"}
"""


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def window(qapp: QApplication) -> MainWindow:  # noqa: ARG001 - ensures QApplication exists
    return MainWindow()


def test_execute_button_is_disabled_with_stage_label(window: MainWindow) -> None:
    assert window.execute_enabled is False
    assert "阶段 5" in window.execute_button.text()


def test_read_only_banner_is_visible(window: MainWindow) -> None:
    assert "只读" in window.banner.text()


def test_export_is_disabled_until_a_plan_exists(window: MainWindow) -> None:
    assert window.export_button.isEnabled() is False


def test_loading_a_plan_fills_the_table(window: MainWindow, tmp_path: Path) -> None:
    from tidymate_app.presenter import run_dry_run

    root = tmp_path / "root"
    root.mkdir()
    (root / "a.jpg").write_bytes(b"x")
    (root / "b.jpg").write_bytes(b"y")
    rules = tmp_path / "rules.yaml"
    rules.write_text(textwrap.dedent(RULES), encoding="utf-8")

    outcome = run_dry_run(str(root), str(rules), str(tmp_path / "out"))
    assert outcome.plan is not None

    window._load_plan(outcome.plan)

    assert window.table.rowCount() == len(outcome.plan.changes)
    assert window.table.columnCount() == 7
    assert window.export_button.isEnabled() is True
    assert window.execute_enabled is False


def test_conflict_rows_are_highlighted(window: MainWindow, tmp_path: Path) -> None:
    from tidymate_app.presenter import run_dry_run

    root = tmp_path / "root"
    (root / "x").mkdir(parents=True)
    (root / "y").mkdir(parents=True)
    (root / "x" / "same.jpg").write_bytes(b"a")
    (root / "y" / "same.jpg").write_bytes(b"b")
    rules = tmp_path / "rules.yaml"
    rules.write_text(textwrap.dedent(RULES), encoding="utf-8")

    outcome = run_dry_run(str(root), str(rules), str(tmp_path / "out"))
    assert outcome.plan is not None
    window._load_plan(outcome.plan)

    highlighted = [
        row
        for row in range(window.table.rowCount())
        if window.table.item(row, 4).background().color().name() != "#000000"
    ]
    assert highlighted, "conflict rows must be visually marked"
