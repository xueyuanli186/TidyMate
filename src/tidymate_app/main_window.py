"""PySide6 window: preview, execute, undo (stage 8).

The window is deliberately thin. It never re-implements safety logic:

* execution goes through ``gate.evaluate`` + ``Executor`` (the same objects the CLI uses);
* undo goes through ``Undoer``, first as a dry-run preview, then for real;
* both actions require an explicit confirmation dialog.

The execute button used to be disabled in stage 4; it is now enabled only when a plan with
executable entries is loaded.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QColor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
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

from tidymate_app import execution_bridge
from tidymate_app.presenter import (
    TABLE_HEADERS,
    DryRunOutcome,
    export,
    is_conflict_row,
    run_dry_run,
    summary_text,
    table_rows,
)
from tidymate_core.journal import BatchAlreadyAppliedError, Journal, JournalError
from tidymate_core.planning import Plan

_CONFLICT_BACKGROUND = QColor("#ffe0e0")
_REJECT_BACKGROUND = QColor("#fff2d9")


class MainWindow(QMainWindow):
    """The whole GUI for this stage, in one widget tree."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle("TidyMate - 预览 / 执行 / 撤销（阶段 8）")
        self.resize(1180, 760)

        self._plan: Plan | None = None
        self._journal: Journal = execution_bridge.open_journal(db_path)
        self._last_executed_batch: str | None = None
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
        self.execute_button = QPushButton("执行…")
        self.execute_button.setEnabled(False)
        self.execute_button.setToolTip("执行前会校验门禁并要求二次确认。")
        self.execute_button.clicked.connect(self._on_execute)
        self.undo_button = QPushButton("撤销…")
        self.undo_button.setEnabled(False)
        self.undo_button.setToolTip("先预览将回滚的条目，再要求二次确认。")
        self.undo_button.clicked.connect(self._on_undo)

        buttons.addWidget(self.dry_run_button)
        buttons.addWidget(self.export_button)
        buttons.addStretch(1)
        buttons.addWidget(self.execute_button)
        buttons.addWidget(self.undo_button)
        layout.addLayout(buttons)

        self.banner = QLabel("预览不会修改任何文件；执行与撤销都会先弹确认框，删除只进回收站。")
        self.banner.setStyleSheet("color:#31708f;background:#d9edf7;padding:6px;")
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

    def _on_execute(self) -> None:
        if self._plan is None:
            return
        summary = execution_bridge.describe_apply(self._plan)
        if summary.count == 0:
            self._show_error("这个计划没有可执行的条目（全部被跳过或拒绝）。")
            return
        preflight = execution_bridge.preflight(self._plan, self._journal)
        if not preflight.ok:
            details = "\n".join(problem.render() for problem in preflight.problems)
            QMessageBox.critical(self, "整批拒绝执行", f"门禁未通过：\n{details}")
            self.status_label.setText("执行被门禁拒绝，没有修改任何文件。")
            return

        text = (
            f"将执行 {summary.count} 条，涉及 {summary.directories} 个目录，"
            f"其中 trash {summary.trash} 条。\n冲突策略：{summary.policy}"
        )
        if not self._confirm("确认执行", text, "我已备份，或已在测试目录演练过"):
            self.status_label.setText("已取消执行，没有修改任何文件。")
            return

        try:
            _, report = execution_bridge.run_apply(self._plan, self._journal)
        except BatchAlreadyAppliedError as exc:
            self._show_error(str(exc))
            return
        if report is None:  # pragma: no cover - gate already passed
            self._show_error("执行器没有返回结果")
            return
        counts = report.counts
        self._last_executed_batch = self._plan.batch_id
        self.execute_button.setEnabled(False)
        self.undo_button.setEnabled(True)
        self.status_label.setText(
            f"执行完成：ok={counts['ok']} failed={counts['failed']} "
            f"skipped={counts['skipped']}；可撤销。",
        )
        self.banner.setText("已执行。撤销会先预览再确认；失败项请查看错误报告。")

    def _on_undo(self) -> None:
        batch_id = self._last_executed_batch or (self._plan.batch_id if self._plan else None)
        if batch_id is None:
            return
        try:
            preview = execution_bridge.undo_preview(self._journal, batch_id)
        except JournalError as exc:
            self._show_error(str(exc))
            return
        if not preview.outcomes:
            self._show_error("这个批次没有可回滚的条目（可能已经撤销过）。")
            return
        failed_ids = [outcome for outcome in preview.outcomes if outcome.error_kind is not None]
        lines = [
            f"将回滚 {len(preview.outcomes)} 条（按 seq 降序，逐条校验 size/mtime）。",
        ]
        if failed_ids:
            lines.append(f"预检发现 {len(failed_ids)} 条无法回滚，将在报告中单列：")
            lines.extend(
                f"  seq {outcome.seq}: {outcome.error_kind} - {outcome.error}"
                for outcome in failed_ids[:10]
            )
        if not self._confirm("确认撤销", "\n".join(lines), "我已确认这些条目可以回滚"):
            self.status_label.setText("已取消撤销，没有修改任何文件。")
            return

        report = execution_bridge.run_undo(self._journal, batch_id)
        self.undo_button.setEnabled(False)
        self.execute_button.setEnabled(False)
        self.status_label.setText(
            f"撤销完成：undone={report.undone} failed={report.failed}；详情见错误报告。",
        )
        self.banner.setText("已撤销。如需再次整理，请重新 Dry-run。")

    def _confirm(self, title: str, text: str, checkbox_text: str) -> bool:
        """Second confirmation with an explicit checklist box."""
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(text)
        check = QCheckBox(checkbox_text)
        box.setCheckBox(check)
        accept = box.addButton("确认", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() is accept and check.isChecked()

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
        self.execute_button.setEnabled(any(change.is_executable for change in plan.changes))
        self.status_label.setText(summary_text(plan))
        try:
            execution_bridge.record_preview(
                self._journal,
                plan,
                self.rules_edit.text().strip(),
                self.root_edit.text().strip(),
            )
        except JournalError as exc:
            self.banner.setText(f"预览已生成，但无法写入日志：{exc}（执行按钮将不可用）")
            self.execute_button.setEnabled(False)

    def _show_error(self, message: str) -> None:
        self.status_label.setText("失败：" + message.splitlines()[0])
        QMessageBox.critical(self, "TidyMate", message)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override
        self._journal.close()
        super().closeEvent(event)

    # ------------------------------------------------------------ properties
    @property
    def plan(self) -> Plan | None:
        """The plan currently displayed (used by tests)."""
        return self._plan

    @property
    def execute_enabled(self) -> bool:
        """True when a plan with executable entries is loaded."""
        return bool(self.execute_button.isEnabled())

    @property
    def undo_enabled(self) -> bool:
        """True after an execution, when a batch can be rolled back."""
        return bool(self.undo_button.isEnabled())


def main(argv: list[str] | None = None) -> int:
    """Start the Qt event loop."""
    app = QApplication(list(argv) if argv is not None else [])
    window = MainWindow()
    window.show()
    return int(app.exec())


__all__ = ["MainWindow", "main"]
