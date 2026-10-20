"""TidyMate core.

Pure logic only: no UI toolkit, no network client, no CLI framework. Everything in this
package must be importable and testable off a bare CPython 3.12+ install.
"""

from __future__ import annotations

from tidymate_core._version import __version__

__all__ = ["__version__"]
