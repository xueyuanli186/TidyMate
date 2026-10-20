"""PySide6 GUI entry point.

Stage 0: placeholder that verifies the import path only. PySide6 is an *optional* extra
(``pip install -e ".[gui]"``) so that Core and the test suite stay installable on a bare
Python without a 300 MB Qt download. The import is deliberately lazy for the same reason.

No window is created yet; creating one would imply a UI contract (dry-run banner, confirm
dialog) that belongs to a later stage.
"""

from __future__ import annotations


def main() -> int:
    """Return a process exit code; never raises on a missing optional dependency."""
    try:
        import PySide6  # noqa: F401  (import probe only)
    except ImportError:
        print(
            'PySide6 is not installed.\nInstall the GUI extra first:  pip install -e ".[gui]"',
        )
        return 78  # EX_CONFIG
    print("TidyMate GUI shell: not implemented yet (stage 0).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
