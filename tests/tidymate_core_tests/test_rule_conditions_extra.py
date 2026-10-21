"""Conditions added for the visual rule builder.

The builder needs four things the text format did not have: ``parent``, ``parent_contains``,
``path_contains``, and upper bounds for size/time ("range" and "between"). These tests pin
both the loader and the matcher, because a condition that loads but never matches is worse
than one that fails loudly.
"""

from __future__ import annotations

import textwrap
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from tidymate_core.rules.loader import load_rules_from_text
from tidymate_core.rules.matcher import matches
from tidymate_core.rules.models import When
from tidymate_core.scanning.models import FileEntry
from tidymate_core.scanning.walker import build_entry

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)


def make_entry(
    root: Path,
    name: str,
    *,
    size: int = 10,
    mtime: datetime = NOW,
) -> FileEntry:
    path = root / name
    path.write_bytes(b"x" * size)
    fake = SimpleNamespace(
        st_size=size,
        st_mtime=mtime.timestamp(),
        st_file_attributes=0,
    )
    return build_entry(str(root), name, cast("Any", fake), link_count=1)


def rules(when: str) -> When:
    text = textwrap.dedent(
        f"""
        rules:
          - id: t
            when: {when}
            action: {{ op: move, template: "x/{{name}}" }}
        """,
    )
    loaded = load_rules_from_text(text)
    return loaded.rules[0].when


def test_parent_matches_only_the_immediate_directory(tmp_path: Path) -> None:
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    entry = make_entry(downloads, "a.jpg")
    assert matches(entry, rules('{ parent: "Downloads" }'), now=NOW)
    assert not matches(entry, rules('{ parent: "downloads2" }'), now=NOW)
    assert matches(entry, rules('{ parent: "downloads" }'), now=NOW), "case-insensitive"


def test_parent_contains(tmp_path: Path) -> None:
    folder = tmp_path / "2026-国庆照片"
    folder.mkdir()
    entry = make_entry(folder, "a.jpg")
    assert matches(entry, rules('{ parent_contains: "国庆" }'), now=NOW)
    assert not matches(entry, rules('{ parent_contains: "春节" }'), now=NOW)


def test_path_contains_is_case_insensitive(tmp_path: Path) -> None:
    folder = tmp_path / "Projects"
    folder.mkdir()
    entry = make_entry(folder, "Report.PDF")
    assert matches(entry, rules('{ path_contains: "projects" }'), now=NOW)
    assert not matches(entry, rules('{ path_contains: "archive" }'), now=NOW)


def test_size_range_uses_two_bounds(tmp_path: Path) -> None:
    folder = tmp_path / "inbox"
    folder.mkdir()
    entry = make_entry(folder, "a.bin", size=2048)
    when = rules('{ size: ">=1KB", size_max: "<=4KB" }')
    assert matches(entry, when, now=NOW)
    assert not matches(entry, rules('{ size: ">=1KB", size_max: "<=1KB" }'), now=NOW)


def test_mtime_between_uses_two_bounds(tmp_path: Path) -> None:
    folder = tmp_path / "inbox"
    folder.mkdir()
    old = NOW - timedelta(days=3)
    entry = make_entry(folder, "a.txt", mtime=old)
    when = rules('{ mtime: ">=2026-10-15", mtime_before: "<=2026-10-20" }')
    assert matches(entry, when, now=NOW)
    assert not matches(entry, rules('{ mtime: ">=2026-10-19" }'), now=NOW)


def test_loader_rejects_unknown_condition_still() -> None:
    from tidymate_core.rules.errors import RuleLoadError

    with pytest.raises(RuleLoadError):
        load_rules_from_text(
            'rules:\n  - id: t\n    when: { parennt: "x" }\n'
            '    action: { op: move, template: "x/{name}" }\n',
        )
