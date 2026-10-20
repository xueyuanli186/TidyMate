"""PySide6 GUI entry point.

PySide6 is an optional extra (``pip install -e ".[gui]"``) so Core, the CLI and the test
suite stay installable on a bare Python. The import is lazy for the same reason: a missing
Qt install must produce a clear message, not an import crash at package load time.

Stage 4 scope: dry-run preview only. The execute button is present but disabled.
"""

from __future__ import annotations

EXIT_CONFIG = 78


def main() -> int:
    """Return a process exit code; never raises on a missing optional dependency."""
    try:
        import PySide6  # noqa: F401  (import probe only)
    except ImportError:
        print(
            'PySide6 is not installed.\nInstall the GUI extra first:  pip install -e ".[gui]"',
        )
        return EXIT_CONFIG

    from tidymate_app.main_window import main as run_window

    return run_window()


if __name__ == "__main__":
    raise SystemExit(main())
