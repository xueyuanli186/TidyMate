"""Preset library and "my rules" browser (stage 10, part 2).

The library shows the eight shipped presets as cards; "use" copies one into the user rule
directory. The second tab lists the user's own files with duplicate / export / delete
(delete goes to the recycle bin, never a permanent unlink).
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from send2trash import send2trash

from tidymate_app.rule_draft import RuleDraft
from tidymate_app.rule_editor import RuleEditorDialog
from tidymate_core import presets


class PresetCard(QFrame):
    """One preset card."""

    def __init__(self, info: presets.PresetInfo, dialog: LibraryDialog) -> None:
        super().__init__()
        self._info = info
        self._dialog = dialog
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)

        title = QLabel(f"<b>{info.name}</b>")
        title.setWordWrap(True)
        description = QLabel(info.description)
        description.setWordWrap(True)
        tags = QLabel(" ".join(f"#{tag}" for tag in info.tags))
        tags.setStyleSheet("color:#666;")
        layout.addWidget(title)
        layout.addWidget(description)
        layout.addWidget(tags)
        layout.addStretch(1)

        buttons = QHBoxLayout()
        preview = QPushButton("预览")
        preview.clicked.connect(lambda: self._dialog.show_preview(info))
        use = QPushButton("使用此方案")
        use.clicked.connect(lambda: self._dialog.use_preset(info, duplicate=False))
        custom = QPushButton("复制并自定义")
        custom.clicked.connect(lambda: self._dialog.use_preset(info, duplicate=True))
        buttons.addWidget(preview)
        buttons.addWidget(use)
        buttons.addWidget(custom)
        layout.addLayout(buttons)


class LibraryDialog(QDialog):
    """Tabs: preset library / my rules."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        on_saved: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("TidyMate - 规则库")
        self.resize(980, 680)
        self._on_saved = on_saved
        self._cards: list[PresetCard] = []

        tabs = QTabWidget()
        tabs.addTab(self._build_presets_tab(), "预置规则")
        tabs.addTab(self._build_my_rules_tab(), "我的规则")
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)

    def _build_presets_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        search_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索规则名称、描述或标签…")
        self.search_edit.textChanged.connect(self._filter_cards)
        self.tag_combo = QLineEdit()
        self.tag_combo.setPlaceholderText("按标签筛选，如：下载")
        self.tag_combo.textChanged.connect(self._filter_cards)
        search_row.addWidget(self.search_edit, 2)
        search_row.addWidget(self.tag_combo, 1)
        layout.addLayout(search_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        self._grid = QGridLayout(host)
        layout.addWidget(scroll, stretch=1)
        scroll.setWidget(host)

        for index, info in enumerate(presets.list_presets()):
            card = PresetCard(info, self)
            self._cards.append(card)
            self._grid.addWidget(card, index // 2, index % 2)
        return page

    def _filter_cards(self) -> None:
        text = self.search_edit.text().strip().casefold()
        tag = self.tag_combo.text().strip().casefold()
        for card in self._cards:
            info = card._info  # the card is a private helper of this dialog
            haystack = f"{info.name} {info.description} {' '.join(info.tags)}".casefold()
            visible = (not text or text in haystack) and (not tag or tag in haystack)
            card.setVisible(visible)

    def show_preview(self, info: presets.PresetInfo) -> None:
        """Read-only preview: metadata plus the exact YAML."""
        dialog = QDialog(self)
        dialog.setWindowTitle(f"预览 - {info.name}")
        dialog.resize(760, 620)
        layout = QVBoxLayout(dialog)
        header = QLabel(
            f"<b>{info.name}</b><br>{info.description}<br>"
            f"<span style='color:#666'>{' '.join('#' + t for t in info.tags)}</span>",
        )
        header.setWordWrap(True)
        layout.addWidget(header)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(info.path.read_text(encoding="utf-8"))
        layout.addWidget(text, stretch=1)
        buttons = QHBoxLayout()
        use = QPushButton("使用此方案")
        use.clicked.connect(partial(self._use_from_preview, dialog, info))
        close = QPushButton("关闭")
        close.clicked.connect(dialog.reject)
        buttons.addStretch(1)
        buttons.addWidget(use)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        dialog.exec()

    def _use_from_preview(self, dialog: QDialog, info: presets.PresetInfo) -> None:
        dialog.accept()
        self.use_preset(info, duplicate=False)

    def use_preset(self, info: presets.PresetInfo, *, duplicate: bool) -> None:
        """Copy the preset into the user directory and open the editor."""
        try:
            if duplicate:
                target = presets.copy_preset(info.preset_id, suffix=" - 副本")
            else:
                target = presets.user_rules_dir() / f"{info.preset_id}.yaml"
                if not target.exists():
                    target = presets.copy_preset(info.preset_id)
        except OSError as exc:
            QMessageBox.critical(self, "复制失败", str(exc))
            return
        draft = RuleDraft(
            name=info.name + (" - 副本" if duplicate else ""),
            description=info.description,
            template="",
        )
        editor = RuleEditorDialog(
            self,
            draft=draft,
            on_saved=self._on_saved,
        )
        editor.setWindowTitle(f"TidyMate - {target.name}")
        editor.exec()
        self._refresh_rules()

    def _build_my_rules_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.rules_label = QLabel()
        self.rules_label.setWordWrap(True)
        layout.addWidget(self.rules_label)
        self.rules_list = QWidget()
        self.rules_layout = QVBoxLayout(self.rules_list)
        self.rules_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.rules_list)
        layout.addWidget(scroll, stretch=1)
        self._refresh_rules()
        return page

    def _refresh_rules(self) -> None:
        while self.rules_layout.count():
            item = self.rules_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        paths = presets.list_user_rules()
        self.rules_label.setText(f"规则目录：{presets.user_rules_dir()}（{len(paths)} 个文件）")
        for path in paths:
            row = QWidget()
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            meta = presets.parse_metadata(path.read_text(encoding="utf-8"))
            label = meta.get("name", path.stem)
            name = QLabel(f"<b>{label}</b>  <span style='color:#666'>{path.name}</span>")
            line.addWidget(name, 1)
            duplicate = QPushButton("复制")
            duplicate.clicked.connect(lambda _=False, p=path: self._duplicate(p))
            export = QPushButton("导出")
            export.clicked.connect(lambda _=False, p=path: self._export(p))
            delete = QPushButton("删除")
            delete.clicked.connect(lambda _=False, p=path: self._delete(p))
            line.addWidget(duplicate)
            line.addWidget(export)
            line.addWidget(delete)
            self.rules_layout.addWidget(row)
        self.rules_layout.addStretch(1)

    def _duplicate(self, path: Path) -> None:
        target = presets.user_rules_dir() / f"{path.stem} - 副本.yaml"
        counter = 2
        while target.exists():
            target = presets.user_rules_dir() / f"{path.stem} - 副本 ({counter}).yaml"
            counter += 1
        target.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        self._refresh_rules()

    def _export(self, path: Path) -> None:
        chosen, _ = QFileDialog.getSaveFileName(self, "导出规则", path.name, "YAML (*.yaml)")
        if not chosen:
            return
        Path(chosen).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

    def _delete(self, path: Path) -> None:
        answer = QMessageBox.question(
            self,
            "删除规则？",
            f"{path.name} 会被送入回收站（可还原），继续？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            send2trash(str(path))
        except OSError as exc:
            QMessageBox.critical(self, "删除失败", str(exc))
            return
        self._refresh_rules()


__all__ = ["LibraryDialog", "PresetCard"]
