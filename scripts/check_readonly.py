"""CI entry point: product code must stay write-free in the read-only stages.

Companion to ``check_forbidden_apis.py``:

* that one bans *permanent deletion* everywhere, forever (iron rule 3);
* this one bans *every* write call inside ``tidymate_core`` while the project is read-only
  (iron rule 2). It will be relaxed only when the executor stage adds an explicitly
  allowed module.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from tidymate_core.safety.readonly_guard import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(repo_root=REPO_ROOT))
