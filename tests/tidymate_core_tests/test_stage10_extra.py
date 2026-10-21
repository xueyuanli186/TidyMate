"""Extra coverage for the rule builder's condition matrix and the library actions."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from tidymate_app.library_dialog import LibraryDialog
from tidymate_app.rule_draft import Condition, RuleDraft, condition_lines, draft_to_yaml
from tidymate_core.rules import load_rules_from_text


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    existing = QApplication.instance()
    if existing is None:
        return QApplication([])
    from typing import cast

    return cast("QApplication", existing)


@pytest.mark.parametrize(
    "condition",
    [
        Condition("ext", "not_in", ".tmp"),
        Condition("ext", "equals", "jpg"),
        Condition("size", "gt", "10MB"),
        Condition("size", "lt", "1KB"),
        Condition("size", "eq", "0B"),
        Condition("size", "range", "1MB", "2MB"),
        Condition("mtime", "before", "2026-01-01"),
        Condition("mtime", "after", "2026-01-01"),
        Condition("mtime", "between", "2026-01-01", "2026-12-31"),
        Condition("mtime", "last", "30"),
        Condition("name", "startswith", "IMG_"),
        Condition("name", "endswith", ".bak"),
        Condition("name", "regex", "^a.*b$"),
        Condition("path", "contains", "Downloads"),
        Condition("path", "regex", "Downloads.*"),
        Condition("parent", "equals", "Desktop"),
        Condition("parent", "contains", "照片"),
    ],
)
def test_every_condition_shape_loads(condition: Condition) -> None:
    yaml = draft_to_yaml(RuleDraft(name="x", conditions=[condition]))
    loaded = load_rules_from_text(yaml)
    assert loaded.rules[0].when is not None
    assert condition_lines(condition)


def test_duplicate_export_and_delete(
    qapp: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qapp
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    from tidymate_core import presets

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    target = presets.copy_preset("photos-by-year")
    dialog = LibraryDialog()

    dialog._duplicate(target)
    assert (presets.user_rules_dir() / "photos-by-year - 副本.yaml").exists()

    export_target = tmp_path / "exported.yaml"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_a, **_k: (str(export_target), ""))
    dialog._export(target)
    assert export_target.exists()

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_a, **_k: QMessageBox.StandardButton.Yes,
    )
    dialog._delete(target)
    assert not target.exists()
    dialog.close()
