"""Path normalisation, extended prefixes, UNC and ancestry.

These are pure string functions, so every Windows detail can be asserted on any host.
"""

from __future__ import annotations

import pytest

from tidymate_core.safety import paths


def test_normalize_uppercases_drive_letter() -> None:
    assert paths.normalize("c:\\data\\file.txt") == "C:\\data\\file.txt"


def test_normalize_collapses_dot_segments() -> None:
    assert paths.normalize("C:\\data\\sub\\..\\file.txt") == "C:\\data\\file.txt"


def test_normalize_keeps_root_separator() -> None:
    assert paths.normalize("C:\\") == "C:\\"


def test_normalize_strips_trailing_separator() -> None:
    assert paths.normalize("C:\\data\\") == "C:\\data"


def test_normalize_makes_relative_paths_absolute() -> None:
    result = paths.normalize("relative\\file.txt")
    assert paths.is_absolute(result)
    assert result.endswith("relative\\file.txt")


@pytest.mark.parametrize("bad", ["", ".", ".."])
def test_normalize_rejects_degenerate_input(bad: str) -> None:
    with pytest.raises(ValueError):
        paths.normalize(bad)


def test_to_extended_prepends_prefix() -> None:
    assert paths.to_extended("C:\\data\\a.txt") == "\\\\?\\C:\\data\\a.txt"


def test_to_extended_is_idempotent() -> None:
    once = paths.to_extended("C:\\data\\a.txt")
    assert paths.to_extended(once) == once


def test_to_extended_rejects_relative_path() -> None:
    with pytest.raises(ValueError):
        paths.to_extended("data\\a.txt")


def test_to_extended_converts_unc_to_unc_prefix() -> None:
    assert paths.to_extended("\\\\server\\share\\a.txt") == "\\\\?\\UNC\\server\\share\\a.txt"


def test_from_extended_roundtrip_drive() -> None:
    original = "C:\\data\\a.txt"
    assert paths.from_extended(paths.to_extended(original)) == original


def test_from_extended_roundtrip_unc() -> None:
    original = "\\\\server\\share\\a.txt"
    assert paths.from_extended(paths.to_extended(original)) == original


def test_is_unc_true_for_share_path() -> None:
    assert paths.is_unc("\\\\server\\share\\a.txt") is True


def test_is_unc_false_for_extended_path() -> None:
    assert paths.is_unc("\\\\?\\C:\\a.txt") is False


def test_is_unc_false_for_local_path() -> None:
    assert paths.is_unc("C:\\a.txt") is False


def test_is_long_path_boundary_is_exclusive() -> None:
    exact = "C:\\" + ("a" * (paths.MAX_PATH - 3))
    assert len(exact) == paths.MAX_PATH
    assert paths.is_long_path(exact) is False
    assert paths.is_long_path(exact + "b") is True


def test_is_ancestor_or_self_detects_self() -> None:
    assert paths.is_ancestor_or_self("C:\\data\\a.txt", "C:\\data\\a.txt") is True


def test_is_ancestor_or_self_detects_parent() -> None:
    assert paths.is_ancestor_or_self("C:\\data", "C:\\data\\sub\\a.txt") is True


def test_is_ancestor_or_self_respects_segment_boundaries() -> None:
    assert paths.is_ancestor_or_self("C:\\data", "C:\\database\\a.txt") is False


def test_is_ancestor_or_self_is_case_insensitive() -> None:
    assert paths.is_ancestor_or_self("c:\\DATA", "C:\\data\\a.txt") is True


def test_is_ancestor_or_self_handles_drive_root() -> None:
    assert paths.is_ancestor_or_self("C:\\", "C:\\anything\\a.txt") is True


def test_is_ancestor_or_self_false_for_unrelated_drive() -> None:
    assert paths.is_ancestor_or_self("D:\\data", "C:\\data\\a.txt") is False


def test_strip_trailing_separator_keeps_root() -> None:
    assert paths.strip_trailing_separator("C:\\") == "C:\\"
    assert paths.strip_trailing_separator("C:\\data\\") == "C:\\data"
