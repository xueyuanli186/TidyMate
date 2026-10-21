"""Offscreen tests for the visual rule editor and the preset library."""

from __future__ import annotations

import os
from pathlib import Path
from typing import cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from tidymate_app.library_dialog import LibraryDialog
from tidymate_app.rule_editor import RuleEditorDialog
from tidymate_core import presets
from tidymate_core.rules import load_rules


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    existing = QApplication.instance()
    if existing is None:
        return QApplication([])
    return cast("QApplication", existing)


@pytest.fixture
def inbox(tmp_path: Path) -> Path:
    root = tmp_path / "Downloads"
    root.mkdir()
    (root / "a.jpg").write_bytes(b"x")
    (root / "b.pdf").write_bytes(b"x")
    return root


def test_editor_preview_updates_within_debounce(
    qapp: QApplication,
    inbox: Path,
    tmp_path: Path,
) -> None:
    del qapp
    dialog = RuleEditorDialog(root=str(inbox), out_root=str(tmp_path / "out"))
    assert dialog.preview_table.rowCount() == 0
    dialog._condition_widgets[0].value.setText(".jpg")
    QTest.qWait(450)
    assert dialog.preview_table.rowCount() == 1
    item = dialog.preview_table.item(0, 0)
    assert item is not None
    assert item.text().endswith("a.jpg")
    dialog.close()


def test_editor_saves_a_loadable_rule(
    qapp: QApplication,
    inbox: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qapp
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    dialog = RuleEditorDialog(root=str(inbox), out_root=str(tmp_path / "out"))
    dialog.name_edit.setText("图片整理")
    dialog.template_edit.setText("Pictures/{year}/{name}")
    dialog._condition_widgets[0].value.setText(".jpg")
    dialog._save()
    target = presets.user_rules_dir() / "图片整理.yaml"
    assert target.exists()
    loaded = load_rules(target)
    assert loaded.rules[0].when.extensions == frozenset({".jpg"})
    dialog.close()


def test_library_lists_all_presets(qapp: QApplication) -> None:
    dialog = LibraryDialog()
    assert len(dialog._cards) == 8
    dialog.search_edit.setText("照片")
    qapp.processEvents()
    visible = [card for card in dialog._cards if not card.isHidden()]
    assert len(visible) == 1
    dialog.close()
