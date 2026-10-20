"""The read-only guard: product code must not contain write calls in stages 1-2.

This is the mechanical proof of "此阶段只读". If someone adds ``Path.write_text`` to
``tidymate_core`` before the executor stage, CI fails.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from tidymate_core.safety import readonly_guard
from tidymate_core.safety.readonly_guard import scan_source, scan_tree


def _write(tmp_path: Path, source: str) -> Path:
    target = tmp_path / "sample.py"
    target.write_text(textwrap.dedent(source), encoding="utf-8")
    return target


def test_product_code_has_no_write_calls(repo_root: Path) -> None:
    calls = scan_tree(repo_root / "src" / "tidymate_core")
    assert calls == [], "\n".join(call.render() for call in calls)


def test_main_reports_success_for_clean_tree(repo_root: Path) -> None:
    assert readonly_guard.main([], repo_root=repo_root) == 0


def test_detects_path_write_text(tmp_path: Path) -> None:
    target = _write(tmp_path, "p.write_text('x')\n")
    assert [call.api for call in scan_source(target)] == [".write_text(...)"]


def test_detects_path_write_bytes(tmp_path: Path) -> None:
    target = _write(tmp_path, "p.write_bytes(b'x')\n")
    assert scan_source(target)[0].api == ".write_bytes(...)"


def test_detects_open_in_write_mode(tmp_path: Path) -> None:
    target = _write(tmp_path, "open(p, 'w')\n")
    assert "open(mode='w')" in scan_source(target)[0].api


def test_detects_open_with_keyword_mode(tmp_path: Path) -> None:
    target = _write(tmp_path, "open(p, mode='a')\n")
    assert "open(mode='a')" in scan_source(target)[0].api


def test_allows_open_in_read_mode(tmp_path: Path) -> None:
    target = _write(tmp_path, "open(p, 'r')\nopen(q)\n")
    assert scan_source(target) == []


def test_detects_shutil_move(tmp_path: Path) -> None:
    target = _write(tmp_path, "import shutil\nshutil.move(a, b)\n")
    assert scan_source(target)[0].api == "shutil.move(...)"


def test_detects_os_rename(tmp_path: Path) -> None:
    target = _write(tmp_path, "import os\nos.rename(a, b)\n")
    assert scan_source(target)[0].api == "os.rename(...)"


def test_detects_send2trash(tmp_path: Path) -> None:
    target = _write(tmp_path, "from send2trash import send2trash\nsend2trash(p)\n")
    assert scan_source(target)[0].api == "send2trash(...)"


def test_str_replace_is_not_a_write(tmp_path: Path) -> None:
    target = _write(tmp_path, "text = 'a'\ntext = text.replace('a', 'b')\n")
    assert scan_source(target) == []


def test_main_returns_one_on_violation(tmp_path: Path) -> None:
    package = tmp_path / "src" / "tidymate_core"
    package.mkdir(parents=True)
    (package / "bad.py").write_text("p.write_text('x')\n", encoding="utf-8")
    (tmp_path / "src" / "tidymate_core" / "__init__.py").write_text("", encoding="utf-8")
    assert readonly_guard.main([], repo_root=tmp_path) == 1


def test_syntax_errors_are_ignored(tmp_path: Path) -> None:
    target = _write(tmp_path, "def broken(:\n")
    assert scan_source(target) == []
