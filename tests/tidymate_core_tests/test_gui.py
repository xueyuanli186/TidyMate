"""Qt tests for the stage-8 window, run head-less via the offscreen platform.

Skipped when the optional PySide6 extra is not installed. The window must reuse the same
gate/executor/undo objects as the CLI; these tests assert observable behaviour (files moved,
files restored), not internal calls.
"""

from __future__ import annotations

import os
import textwrap
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from tidymate_app.main_window import MainWindow

RULES = """
rules:
  - id: images
    when: {ext: [".jpg"]}
    action: {op: move, template: "flat/{name}", conflict: skip}
"""


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    existing = QApplication.instance()
    if existing is None:
        return QApplication([])
    return cast("QApplication", existing)


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path) -> Iterator[MainWindow]:
    # Explicit teardown matters: letting Qt destroy widgets while coverage is flushing
    # its data at interpreter exit crashes the process with 0xC0000409 on Windows.
    main_window = MainWindow(db_path=tmp_path / "journal.db")
    yield main_window
    main_window.close()
    main_window.deleteLater()
    qapp.processEvents()


def prepare(window: MainWindow, tmp_path: Path, *, files: int = 1) -> Path:
    root = tmp_path / "root"
    root.mkdir(exist_ok=True)
    for index in range(files):
        (root / f"photo-{index}.jpg").write_bytes(b"x")
    rules = tmp_path / "rules.yaml"
    rules.write_text(textwrap.dedent(RULES), encoding="utf-8")
    window.root_edit.setText(str(root))
    window.rules_edit.setText(str(rules))
    window.output_edit.setText(str(tmp_path / "out"))
    return root


def test_execute_and_undo_buttons_start_disabled(window: MainWindow) -> None:
    assert window.execute_enabled is False
    assert window.undo_enabled is False
    assert "确认" in window.banner.text()


def test_loading_a_plan_fills_the_table_and_enables_execution(
    window: MainWindow,
    tmp_path: Path,
) -> None:
    prepare(window, tmp_path)
    window._on_dry_run()

    assert window.plan is not None
    assert window.table.rowCount() == 1
    assert window.table.columnCount() == 7
    assert window.export_button.isEnabled() is True
    assert window.execute_enabled is True
    assert window.undo_enabled is False


def test_dry_run_records_the_preview_for_the_gate(window: MainWindow, tmp_path: Path) -> None:
    prepare(window, tmp_path)
    window._on_dry_run()
    assert window.plan is not None

    stored = window._journal.load_plan(window.plan.batch_id)
    assert stored is not None
    assert stored.plan_hash == window.plan.plan_hash


def test_confirming_execution_moves_files_then_undo_restores_them(
    window: MainWindow,
    tmp_path: Path,
) -> None:
    root = prepare(window, tmp_path)
    window._on_dry_run()
    window._confirm = lambda *_args, **_kwargs: True  # type: ignore[method-assign]

    window._on_execute()

    assert not (root / "photo-0.jpg").exists(), "execution must move the file"
    assert (tmp_path / "out" / "flat" / "photo-0.jpg").exists()
    assert window.undo_enabled is True
    assert "执行完成" in window.status_label.text()

    window._on_undo()

    assert (root / "photo-0.jpg").exists(), "undo must restore the file"
    assert "撤销完成" in window.status_label.text()


def test_declining_the_confirmation_changes_nothing(window: MainWindow, tmp_path: Path) -> None:
    root = prepare(window, tmp_path)
    window._on_dry_run()
    window._confirm = lambda *_args, **_kwargs: False  # type: ignore[method-assign]

    window._on_execute()

    assert (root / "photo-0.jpg").exists()
    assert "已取消" in window.status_label.text()


def test_undo_preview_can_be_cancelled(window: MainWindow, tmp_path: Path) -> None:
    root = prepare(window, tmp_path)
    window._on_dry_run()
    window._confirm = lambda *_args, **_kwargs: True  # type: ignore[method-assign]
    window._on_execute()

    window._confirm = lambda *_args, **_kwargs: False  # type: ignore[method-assign]
    window._on_undo()

    assert not (root / "photo-0.jpg").exists(), "the file stays at the destination"
    assert "已取消撤销" in window.status_label.text()


def test_conflict_rows_are_highlighted(window: MainWindow, tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "x").mkdir(parents=True)
    (root / "y").mkdir(parents=True)
    (root / "x" / "same.jpg").write_bytes(b"a")
    (root / "y" / "same.jpg").write_bytes(b"b")
    rules = tmp_path / "rules.yaml"
    rules.write_text(textwrap.dedent(RULES), encoding="utf-8")
    window.root_edit.setText(str(root))
    window.rules_edit.setText(str(rules))
    window.output_edit.setText(str(tmp_path / "out"))

    window._on_dry_run()

    def background_name(row: int) -> str:
        item = window.table.item(row, 4)
        assert item is not None
        return item.background().color().name()

    highlighted = [
        row for row in range(window.table.rowCount()) if background_name(row) != "#000000"
    ]
    assert highlighted, "conflict rows must be visually marked"


def test_execution_without_a_plan_is_a_no_op(window: MainWindow) -> None:
    window._on_execute()
    window._on_undo()
    assert window.plan is None
    assert window.undo_enabled is False
