"""Render the rule editor and preset library to PNG (offscreen, for docs)."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication

from tidymate_app.library_dialog import LibraryDialog
from tidymate_app.rule_draft import Condition, RuleDraft
from tidymate_app.rule_editor import RuleEditorDialog

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="tidymate-shot-"))
    inbox = base / "Downloads"
    inbox.mkdir()
    for name in ("假期照片.jpg", "发票.pdf", "安装包.exe", "资料.zip"):
        (inbox / name).write_bytes(b"x" * 2048)

    app = QApplication([])

    draft = RuleDraft(
        name="下载目录按类型整理",
        description="把下载目录里的图片、文档、压缩包和安装包分门别类",
        conditions=[
            Condition("ext", "in", ".jpg, .png"),
            Condition("parent", "equals", "Downloads"),
            Condition("size", "gt", "1KB"),
        ],
        template="Pictures/{year}/{name}",
        conflict="rename",
    )
    editor = RuleEditorDialog(draft=draft, root=str(inbox), out_root=str(base / "Sorted"))
    editor.resize(1180, 760)
    editor.show()
    app.processEvents()
    editor._refresh()
    app.processEvents()
    editor.grab().save(str(REPO / "docs" / "images" / "rule-editor.png"))

    library = LibraryDialog()
    library.resize(1000, 720)
    library.show()
    app.processEvents()
    library.grab().save(str(REPO / "docs" / "images" / "preset-library.png"))

    editor.close()
    library.close()
    app.processEvents()
    print("wrote docs/images/rule-editor.png and docs/images/preset-library.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
