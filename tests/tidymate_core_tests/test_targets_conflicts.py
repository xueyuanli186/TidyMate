"""Destination validation and conflict identity."""

from __future__ import annotations

from pathlib import Path

import pytest

from tidymate_core.planning.conflicts import ConflictIndex, conflict_key
from tidymate_core.planning.targets import (
    MAX_TARGET_LENGTH,
    TargetError,
    build_target,
    is_reserved_name,
)


def test_build_target_under_root(tmp_path: Path) -> None:
    target = build_target(str(tmp_path), ("Sorted", "2024", "a.jpg"))
    assert target.display == str(tmp_path / "Sorted" / "2024" / "a.jpg")
    assert target.requires_extended is False
    assert target.extended.startswith("\\\\?\\")


def test_segment_with_separator_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(TargetError, match="escape"):
        build_target(str(tmp_path), ("a\\b",))


def test_parent_segment_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(TargetError):
        build_target(str(tmp_path), ("..", "evil"))


def test_empty_segment_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(TargetError):
        build_target(str(tmp_path), ("",))


@pytest.mark.parametrize("name", ["CON", "con", "NUL.txt", "COM1", "lpt9.log"])
def test_reserved_device_names_are_rejected(tmp_path: Path, name: str) -> None:
    assert is_reserved_name(name) is True
    with pytest.raises(TargetError, match="reserved"):
        build_target(str(tmp_path), (name,))


@pytest.mark.parametrize("name", ["console.txt", "com0", "lpt10.txt", "null"])
def test_ordinary_names_are_not_reserved(name: str) -> None:
    assert is_reserved_name(name) is False


def test_blacklisted_target_is_rejected() -> None:
    with pytest.raises(TargetError, match="protected"):
        build_target(r"C:\Windows", ("Temp", "a.txt"))


def test_long_target_requires_extended_prefix(tmp_path: Path) -> None:
    deep = tuple(["d" * 55] * 6)
    target = build_target(str(tmp_path), deep)
    assert target.length > 260
    assert target.requires_extended is True


def test_path_beyond_hard_limit_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(TargetError, match="beyond"):
        build_target(str(tmp_path), ("x" * (MAX_TARGET_LENGTH + 10),))


def test_conflict_key_is_case_insensitive() -> None:
    assert conflict_key(r"C:\out\Report.pdf") == conflict_key(r"C:\out\report.pdf")


def test_conflict_key_ignores_trailing_dots_and_spaces() -> None:
    assert conflict_key(r"C:\out\a.pdf. ") == conflict_key(r"C:\out\a.pdf")


def test_conflict_key_normalises_unicode() -> None:
    # e + combining acute vs precomposed e-acute are the same NTFS name.
    composed = "caf\u00e9.pdf"
    decomposed = "cafe\u0301.pdf"
    assert conflict_key(composed) == conflict_key(decomposed)


def test_index_detects_duplicate_claims() -> None:
    index = ConflictIndex()
    assert index.claim(r"C:\out\a.txt", 1) is None
    assert index.claim(r"C:\OUT\A.TXT", 2) == 1
    assert index.duplicates() == {conflict_key(r"C:\out\a.txt"): [1, 2]}


def test_index_reports_no_duplicates_for_distinct_paths() -> None:
    index = ConflictIndex()
    index.claim(r"C:\out\a.txt", 1)
    index.claim(r"C:\out\b.txt", 2)
    assert index.duplicates() == {}
    assert len(index) == 2
