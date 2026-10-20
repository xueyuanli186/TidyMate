"""PyInstaller entry point for the windowed GUI executable."""

from __future__ import annotations

import sys

from tidymate_app.main import main

if __name__ == "__main__":
    sys.exit(main())
