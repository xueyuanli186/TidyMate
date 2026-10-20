"""PyInstaller entry point for the CLI executable.

Kept outside ``src`` so the package itself stays importable and testable; PyInstaller only
needs something with a ``__main__`` body.
"""

from __future__ import annotations

import sys

from tidymate_cli.main import app

if __name__ == "__main__":
    sys.exit(app())
