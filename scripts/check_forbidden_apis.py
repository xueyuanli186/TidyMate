"""CI entry point for the permanent-delete scanner (iron rule 3).

The implementation lives in Core (so it is unit tested and covered by pytest); this file
only wires it to the repository root.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from tidymate_core.safety.forbidden_apis import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(repo_root=REPO_ROOT))
