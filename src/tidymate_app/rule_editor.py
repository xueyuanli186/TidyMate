"""Visual rule editor (stage 10, part 2).

Left: the form (basic info, condition rows, action, template, conflict policy).
Right: a live preview rebuilt 300 ms after the last edit, using the same ``build_plan``
the CLI uses - the preview is a real dry-run, not a mock.

The template field has an "insert variable" menu fed by the loader's whitelist, so a
non-programmer cannot invent a variable the engine will reject.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from functools import partial
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from tidymate_app.rule_draft import (
    FIELD_LABELS,
    OPERATORS,
    Condition,
    RuleDraft,
    build_preview,
    draft_to_yaml,
)
from tidymate_core import presets
from tidymate_core.rules import ALLOWED_VARIABLES
from tidymate_core.rules.errors import RuleLoadError

_CONFLICT_HINTS = {
    "skip": "如果目标已存在同名文件，跳过不动。",
    "rename": "如果冲突，自动加序号，如 (1) (2)。",
    "ask": "遇到冲突时逐条询问。",
}


def _slug(name: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", name.strip()).strip("-")
    return cleaned or "rule"


class ConditionWidget(QWidget):
    """One editable condition row."""

    changed = Signal()

    def __init__(self, condition: Condition | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)

        self.field = QComboBox()
        for field_id, label in FIELD_LABELS.items():
            self.field.addItem(label, field_id)
        self.operator = QComboBox()
        self.value = QLineEdit()
        self.value2 = QLineEdit()
        self.value2.setVisible(False)
        remove = QPushButton("×")
        remove.setFixedWidth(28)
        remove.setToolTip("删除这条条件")

        row.addWidget(self.field, 2)
        row.addWidget(self.operator, 2)
        row.addWidget(self.value, 3)
        row.addWidget(self.value2, 2)
        row.addWidget(remove)

        self.field.currentIndexChanged.connect(self._sync_operators)
        self.operator.currentIndexChanged.connect(self._sync_value_ui)
        self.value.textChanged.connect(self.changed)
        self.value2.textChanged.connect(self.changed)
        remove.clicked.connect(self._remove)

        if condition is not None:
            index = self.field.findData(condition.field)
            if index >= 0:
                self.field.setCurrentIndex(index)
            self._sync_operators()
            op_index = self.operator.findData(condition.operator)
            if op_index >= 0:
                self.operator.setCurrentIndex(op_index)
            self.value.setText(condition.value)
            self.value2.setText(condition.value2)
        else:
            self._sync_operators()

    def _remove(self) -> None:
        self.setParent(None)
        self.deleteLater()
        self.changed.emit()

    def _sync_operators(self) -> None:
        field_id = str(self.field.currentData())
        self.operator.blockSignals(True)
        self.operator.clear()
        for label, code in OPERATORS[field_id]:
            self.operator.addItem(label, code)
        self.operator.blockSignals(False)
        self._sync_value_ui()
        self.changed.emit()

    def _sync_value_ui(self) -> None:
        field_id = str(self.field.currentData())
        operator = str(self.operator.currentData())
        two = (field_id == "size" and operator == "range") or (
            field_id == "mtime" and operator == "between"
        )
        self.value2.setVisible(two)
        placeholders = {
            "ext": (".jpg, .png", ""),
            "size": ("10MB", "100MB"),
            "mtime": ("2026-01-01", "2026-12-31"),
            "name": ("报告", ""),
            "path": ("Downloads", ""),
            "parent": ("Downloads", ""),
        }
        first, second = placeholders.get(field_id, ("", ""))
        if field_id == "mtime" and operator == "last":
            first = "30（天）"
        self.value.setPlaceholderText(first)
        self.value2.setPlaceholderText(second)

    def to_condition(self) -> Condition:
        condition = Condition(
            field=str(self.field.currentData()),
            operator=str(self.operator.currentData()),
            value=self.value.text().strip(),
            value2=self.value2.text().strip() if self.value2.isVisible() else "",
        )
        if condition.field == "mtime" and condition.operator == "last":
            condition.value = condition.value or "30"
        return condition


class RuleEditorDialog(QDialog):
    """Form + live preview. Never writes files unless the user clicks save."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        draft: RuleDraft | None = None,
        root: str = "",
        out_root: str = "",
        on_saved: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("TidyMate - 规则编辑器")
        self.resize(1180, 720)
        self._draft = draft or RuleDraft()
        self._on_saved = on_saved
        self._condition_widgets: list[ConditionWidget] = []

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self._refresh)

        self._build_ui(root, out_root)
        self._load_draft(self._draft)
        self._timer.start()

    # ------------------------------------------------------------------ UI
    def _build_ui(self, root: str, out_root: str) -> None:
        outer = QHBoxLayout(self)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例如：下载目录按类型整理")
        self.desc_edit = QLineEdit()
        self.priority_spin = QSpinBox()
        self.priority_spin.setRange(0, 9999)
        self.priority_spin.setValue(10)
        self.enabled_check = QCheckBox("启用")
        self.enabled_check.setChecked(True)
        form.addRow("规则名称 *", self.name_edit)
        form.addRow("规则描述", self.desc_edit)
        form.addRow("优先级", self.priority_spin)
        form.addRow("", self.enabled_check)
        left_layout.addLayout(form)

        left_layout.addWidget(QLabel("匹配条件（全部满足）"))
        self.conditions_host = QWidget()
        self.conditions_layout = QVBoxLayout(self.conditions_host)
        self.conditions_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.conditions_host)
        scroll.setMinimumHeight(180)
        left_layout.addWidget(scroll, stretch=2)

        add_row = QHBoxLayout()
        add_button = QPushButton("＋ 添加条件")
        add_button.clicked.connect(lambda: self._add_condition())
        add_row.addWidget(add_button)
        add_row.addStretch(1)
        left_layout.addLayout(add_row)

        action_form = QFormLayout()
        self.op_combo = QComboBox()
        for label, code in (
            ("移动到新位置", "move"),
            ("重命名", "rename"),
            ("复制到新位置", "copy"),
            ("送入回收站", "trash"),
        ):
            self.op_combo.addItem(label, code)
        self.template_edit = QLineEdit()
        self.template_edit.setPlaceholderText("例如：Pictures/{year}/{name}")
        insert = QToolButton()
        insert.setText("插入变量")
        menu = QMenu(insert)
        for variable in ALLOWED_VARIABLES:
            menu.addAction("{" + variable + "}", partial(self._insert_variable, variable))
        insert.setMenu(menu)
        insert.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        template_row = QHBoxLayout()
        template_row.addWidget(self.template_edit, 1)
        template_row.addWidget(insert)
        template_widget = QWidget()
        template_widget.setLayout(template_row)
        self.conflict_combo = QComboBox()
        for label, code in (
            ("跳过已有文件", "skip"),
            ("自动改名", "rename"),
            ("逐个询问", "ask"),
        ):
            self.conflict_combo.addItem(label, code)
        self.conflict_hint = QLabel()
        self.conflict_hint.setStyleSheet("color:#666;")
        action_form.addRow("操作", self.op_combo)
        action_form.addRow("目标模板", template_widget)
        action_form.addRow("冲突策略", self.conflict_combo)
        action_form.addRow("", self.conflict_hint)
        left_layout.addLayout(action_form)

        paths = QFormLayout()
        self.root_edit = QLineEdit(root)
        self.root_edit.setPlaceholderText("预览用的源目录")
        self.out_edit = QLineEdit(out_root)
        self.out_edit.setPlaceholderText("目标根目录")
        browse_root = QPushButton("浏览…")
        browse_root.clicked.connect(lambda: self._pick(self.root_edit))
        browse_out = QPushButton("浏览…")
        browse_out.clicked.connect(lambda: self._pick(self.out_edit))
        root_row = QHBoxLayout()
        root_row.addWidget(self.root_edit, 1)
        root_row.addWidget(browse_root)
        out_row = QHBoxLayout()
        out_row.addWidget(self.out_edit, 1)
        out_row.addWidget(browse_out)
        root_widget = QWidget()
        root_widget.setLayout(root_row)
        out_widget = QWidget()
        out_widget.setLayout(out_row)
        paths.addRow("预览目录", root_widget)
        paths.addRow("目标根目录", out_widget)
        left_layout.addLayout(paths)

        left.setMinimumWidth(560)
        outer.addWidget(left, 3)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.summary_label = QLabel("填写条件后这里会显示预览。")
        self.summary_label.setWordWrap(True)
        right_layout.addWidget(self.summary_label)
        self.preview_table = QTableWidget(0, 3)
        self.preview_table.setHorizontalHeaderLabels(["原路径", "新路径", "状态"])
        self.preview_table.horizontalHeader().setStretchLastSection(True)
        self.preview_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        right_layout.addWidget(self.preview_table, stretch=1)
        outer.addWidget(right, 2)

        buttons = QHBoxLayout()
        save = QPushButton("保存规则")
        save.clicked.connect(self._save)
        save_as = QPushButton("另存为…")
        save_as.clicked.connect(lambda: self._save(save_as=True))
        close = QPushButton("关闭")
        close.clicked.connect(self.reject)
        buttons.addStretch(1)
        buttons.addWidget(save)
        buttons.addWidget(save_as)
        buttons.addWidget(close)
        left_layout.addLayout(buttons)

        self.name_edit.textChanged.connect(self._schedule)
        self.desc_edit.textChanged.connect(self._schedule)
        self.priority_spin.valueChanged.connect(self._schedule)
        self.enabled_check.toggled.connect(self._schedule)
        self.op_combo.currentIndexChanged.connect(self._sync_action_ui)
        self.template_edit.textChanged.connect(self._schedule)
        self.conflict_combo.currentIndexChanged.connect(self._sync_action_ui)
        self.root_edit.textChanged.connect(self._schedule)
        self.out_edit.textChanged.connect(self._schedule)
        self._sync_action_ui()

    def _pick(self, target: QLineEdit) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "选择目录", target.text() or "")
        if chosen:
            target.setText(chosen)

    def _load_draft(self, draft: RuleDraft) -> None:
        self.name_edit.setText(draft.name)
        self.desc_edit.setText(draft.description)
        self.priority_spin.setValue(draft.priority)
        self.enabled_check.setChecked(draft.enabled)
        self.template_edit.setText(draft.template)
        index = self.op_combo.findData(draft.op)
        if index >= 0:
            self.op_combo.setCurrentIndex(index)
        index = self.conflict_combo.findData(draft.conflict)
        if index >= 0:
            self.conflict_combo.setCurrentIndex(index)
        for condition in draft.conditions or [Condition()]:
            self._add_condition(condition)

    def _sync_action_ui(self) -> None:
        op = str(self.op_combo.currentData())
        is_trash = op == "trash"
        self.template_edit.setEnabled(not is_trash)
        self.conflict_combo.setEnabled(not is_trash)
        self.conflict_hint.setText(_CONFLICT_HINTS.get(str(self.conflict_combo.currentData()), ""))
        self._schedule()

    def _insert_variable(self, variable: str) -> None:
        self.template_edit.insert("{" + variable + "}")
        self.template_edit.setFocus()

    def _add_condition(self, condition: Condition | None = None) -> None:
        widget = ConditionWidget(condition, self.conditions_host)
        widget.changed.connect(self._schedule)
        self._condition_widgets.append(widget)
        self.conditions_layout.addWidget(widget)
        self._schedule()

    # -------------------------------------------------------------- preview
    def _schedule(self) -> None:
        self._timer.start()

    def collect(self) -> RuleDraft:
        """Read the form into a draft (conditions with an empty value are ignored)."""
        conditions = []
        for widget in self._condition_widgets:
            condition = widget.to_condition()
            if condition.value.strip():
                conditions.append(condition)
        return RuleDraft(
            name=self.name_edit.text().strip(),
            description=self.desc_edit.text().strip(),
            priority=self.priority_spin.value(),
            enabled=self.enabled_check.isChecked(),
            conditions=conditions,
            op=str(self.op_combo.currentData()),
            template=self.template_edit.text().strip(),
            conflict=str(self.conflict_combo.currentData()),
        )

    def _refresh(self) -> None:
        draft = self.collect()
        self._draft = draft
        root = self.root_edit.text().strip()
        out_root = self.out_edit.text().strip()
        if not root or not out_root:
            self.summary_label.setText("填写「预览目录」和「目标根目录」后显示实时预览。")
            self.preview_table.setRowCount(0)
            return
        try:
            plan = build_preview(draft, root, out_root)
        except (RuleLoadError, ValueError, OSError) as exc:
            self.summary_label.setText(f"规则暂不可用：{exc}")
            self.preview_table.setRowCount(0)
            return

        stats = plan.stats
        self.summary_label.setText(
            f"扫描 {stats.total_scanned} · 匹配 {stats.matched} · "
            f"将执行 {stats.will_execute} · 冲突 {stats.conflicts} · 拒绝 {stats.rejected}",
        )
        rows = plan.changes[:200]
        self.preview_table.setRowCount(len(rows))
        self._preview_rows = rows
        for row_index, change in enumerate(rows):
            items = [
                QTableWidgetItem(change.src),
                QTableWidgetItem(change.dst or "-"),
                QTableWidgetItem(
                    "冲突" if change.conflict.value != "none" else change.status.value,
                ),
            ]
            color = None
            if change.conflict.value != "none":
                color = QColor("#ffe0e0")
            elif change.status.value == "reject":
                color = QColor("#fff2d9")
            for column, item in enumerate(items):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if color is not None:
                    item.setBackground(color)
                self.preview_table.setItem(row_index, column, item)
        self.preview_table.resizeColumnToContents(0)

    # ----------------------------------------------------------------- save
    def _save(self, *, save_as: bool = False) -> None:
        draft = self.collect()
        if not draft.name:
            QMessageBox.warning(self, "无法保存", "请先填写规则名称。")
            return
        default_dir = str(presets.user_rules_dir())
        if save_as:
            chosen, _ = QFileDialog.getSaveFileName(
                self,
                "另存为",
                str(Path(default_dir) / f"{_slug(draft.name)}.yaml"),
                "YAML (*.yaml)",
            )
            if not chosen:
                return
            target = Path(chosen)
        else:
            target = presets.user_rules_dir() / f"{_slug(draft.name)}.yaml"
            if target.exists():
                answer = QMessageBox.question(
                    self,
                    "覆盖规则？",
                    f"{target.name} 已存在，覆盖它？",
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(draft_to_yaml(draft), encoding="utf-8")
        self.summary_label.setText(f"已保存：{target}")
        if self._on_saved is not None:
            self._on_saved(target)


__all__ = ["ConditionWidget", "RuleEditorDialog"]
