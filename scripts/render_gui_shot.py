"""Render the GUI offscreen and save a PNG, so the layout can be reviewed without a screen."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication

from tidymate_app.main_window import MainWindow
from tidymate_app.presenter import run_dry_run

ROOT = Path(sys.argv[1])
RULES = Path(sys.argv[2])
OUT = Path(sys.argv[3])
SHOT = Path(sys.argv[4])

app = QApplication([])
window = MainWindow()
window.resize(1180, 720)

outcome = run_dry_run(str(ROOT), str(RULES), str(OUT))
if outcome.plan is None:
    raise SystemExit(f"dry-run failed: {outcome.error}")

window.root_edit.setText(str(ROOT))
window.rules_edit.setText(str(RULES))
window.output_edit.setText(str(OUT))
window._load_plan(outcome.plan)
window.show()
app.processEvents()

SHOT.parent.mkdir(parents=True, exist_ok=True)
saved = window.grab().save(str(SHOT), "PNG")
print(
    f"rows={window.table.rowCount()} "
    f"execute_enabled={window.execute_enabled} "
    f"saved={saved} path={SHOT}",
)
window.close()
