"""ScanConfig validation: bad configuration fails before any path is touched."""

from __future__ import annotations

import pytest

from tidymate_core.scanning.config import ScanConfig


def test_roots_are_required() -> None:
    with pytest.raises(ValueError, match="at least one root"):
        ScanConfig(roots=())


def test_root_must_be_absolute() -> None:
    with pytest.raises(ValueError, match="absolute"):
        ScanConfig(roots=("relative\\dir",))


def test_root_must_not_be_empty_string() -> None:
    with pytest.raises(ValueError):
        ScanConfig(roots=("",))


def test_max_depth_must_not_be_negative() -> None:
    with pytest.raises(ValueError, match="max_depth"):
        ScanConfig(roots=("C:\\data",), max_depth=-1)


def test_max_file_size_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_file_size"):
        ScanConfig(roots=("C:\\data",), max_file_size=0)


def test_exclude_dirs_must_not_be_blank() -> None:
    with pytest.raises(ValueError, match="exclude_dirs"):
        ScanConfig(roots=("C:\\data",), exclude_dirs=("   ",))


def test_exclusions_split_into_absolute_and_globs() -> None:
    config = ScanConfig(
        roots=("C:\\data",),
        exclude_dirs=("node_modules", "*.tmp", "C:\\data\\private"),
    )
    assert config.excluded_globs == ("node_modules", "*.tmp")
    assert config.excluded_absolute == frozenset({"c:\\data\\private"})


def test_normalized_roots_preserve_order_and_casing() -> None:
    config = ScanConfig(roots=("c:\\first\\", "D:\\second"))
    assert config.normalized_roots == ("C:\\first", "D:\\second")


def test_follow_symlinks_defaults_to_false() -> None:
    assert ScanConfig(roots=("C:\\data",)).follow_symlinks is False


def test_measure_memory_defaults_to_false() -> None:
    assert ScanConfig(roots=("C:\\data",)).measure_memory is False
