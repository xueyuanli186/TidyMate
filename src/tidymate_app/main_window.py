"""Minimal PySide6 dry-run window.

Scope of this stage: pick a directory, pick a rule file, run a dry-run, see the table with
conflict rows highlighted, export the report. The execute button exists but is **disabled**
and says so, because stage 5 owns execution.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tidymate_app.presenter import (
    TABLE_HEADERS,
    DryRunOutcome,
    export,
    is_conflict_row,
    run_dry_run,
    summary_text,
    table_rows,
)
from tidymate_core.planning import Plan

_CONFLICT_BACKGROUND = QColor("#ffe0e0")
_REJECT_BACKGROUND = QColor("#fff2d9")


class MainWindow(QMainWindow):  # type: ignore[misc]
    """The whole GUI for this stage, in one widget tree."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("TidyMate - Dry-run 预览（阶段 4）")
        self.resize(1180, 720)

        self._plan: Plan | None = None
        self._build_ui()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        form = QGridLayout()
        self.root_edit = QLineEdit()
        self.root_edit.setPlaceholderText("要整理的目录，例如 D:\\Downloads")
        self.rules_edit = QLineEdit()
        self.rules_edit.setPlaceholderText("规则文件 rules.yaml")
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("目标根目录，模板以此为基准")

        form.addWidget(QLabel("源目录"), 0, 0)
        form.addWidget(self.root_edit, 0, 1)
        form.addWidget(self._browse_button(self.root_edit, directory=True), 0, 2)
        form.addWidget(QLabel("规则文件"), 1, 0)
        form.addWidget(self.rules_edit, 1, 1)
        form.addWidget(self._browse_button(self.rules_edit, directory=False), 1, 2)
        form.addWidget(QLabel("目标根目录"), 2, 0)
        form.addWidget(self.output_edit, 2, 1)
        form.addWidget(self._browse_button(self.output_edit, directory=True), 2, 2)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        self.dry_run_button = QPushButton("Dry-run 预览")
        self.dry_run_button.clicked.connect(self._on_dry_run)
        self.export_button = QPushButton("导出报告")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._on_export)
        self.execute_button = QPushButton("执行（阶段 5 开放）")
        self.execute_button.setEnabled(False)
        self.execute_button.setToolTip("本阶段不允许修改任何文件。执行器在阶段 5 交付。")

        buttons.addWidget(self.dry_run_button)
        buttons.addWidget(self.export_button)
        buttons.addStretch(1)
        buttons.addWidget(self.execute_button)
        layout.addLayout(buttons)

        self.banner = QLabel("本阶段只读：不会创建、移动或删除任何文件。")
        self.banner.setStyleSheet("color:#8a6d3b;background:#fcf8e3;padding:6px;")
        layout.addWidget(self.banner)

        self.table = QTableWidget(0, len(TABLE_HEADERS))
        self.table.setHorizontalHeaderLabels(list(TABLE_HEADERS))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table, stretch=1)

        self.status_label = QLabel("选择目录与规则后执行 Dry-run。")
        self.statusBar().addWidget(self.status_label)

    def _browse_button(self, target: QLineEdit, *, directory: bool) -> QPushButton:
        button = QPushButton("浏览…")
        if directory:
            button.clicked.connect(lambda: self._pick_directory(target))
        else:
            button.clicked.connect(lambda: self._pick_file(target))
        return button

    def _pick_directory(self, target: QLineEdit) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "选择目录", target.text() or "")
        if chosen:
            target.setText(chosen)

    def _pick_file(self, target: QLineEdit) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            "选择规则文件",
            target.text() or "",
            "YAML (*.yaml *.yml);;所有文件 (*)",
        )
        if chosen:
            target.setText(chosen)

    # -------------------------------------------------------------- actions
    def _on_dry_run(self) -> None:
        outcome: DryRunOutcome = run_dry_run(
            self.root_edit.text().strip(),
            self.rules_edit.text().strip(),
            self.output_edit.text().strip(),
        )
        if outcome.plan is None:
            self._show_error(outcome.error or "未知错误")
            return
        self._load_plan(outcome.plan)

    def _on_export(self) -> None:
        if self._plan is None:
            return
        chosen = QFileDialog.getExistingDirectory(self, "选择报告输出目录")
        if not chosen:
            return
        try:
            plan_path, report_path = export(self._plan, chosen)
        except Exception as exc:  # surface any write refusal to the user
            self._show_error(str(exc))
            return
        self.status_label.setText(f"已导出：{plan_path} / {report_path}")

    def _load_plan(self, plan: Plan) -> None:
        self._plan = plan
        rows = table_rows(plan)
        self.table.setRowCount(len(rows))
        for row_index, cells in enumerate(rows):
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if is_conflict_row(plan, row_index):
                    change = plan.changes[row_index]
                    background = (
                        _REJECT_BACKGROUND
                        if change.status.value == "reject"
                        else _CONFLICT_BACKGROUND
                    )
                    item.setBackground(background)
                self.table.setItem(row_index, column, item)
        self.table.resizeColumnsToContents()
        self.export_button.setEnabled(True)
        self.status_label.setText(summary_text(plan))

    def _show_error(self, message: str) -> None:
        self.status_label.setText("失败：" + message.splitlines()[0])
        QMessageBox.critical(self, "TidyMate", message)

    # ------------------------------------------------------------ properties
    @property
    def plan(self) -> Plan | None:
        """The plan currently displayed (used by tests)."""
        return self._plan

    @property
    def execute_enabled(self) -> bool:
        """Always False in this stage; exposed so a test can assert it."""
        return bool(self.execute_button.isEnabled())


def main(argv: list[str] | None = None) -> int:
    """Start the Qt event loop."""
    app = QApplication(list(argv) if argv is not None else [])
    window = MainWindow()
    window.show()
    return int(app.exec())


__all__ = ["MainWindow", "main"]
