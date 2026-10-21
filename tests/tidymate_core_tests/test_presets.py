"""Preset library contract: eight loadable files, metadata, safe copying."""

from __future__ import annotations

from pathlib import Path

import pytest

from tidymate_core import presets
from tidymate_core.rules import load_rules

EXPECTED = {
    "downloads-cleanup",
    "photos-by-year",
    "desktop-tidy",
    "large-files-quarantine",
    "duplicates-to-trash",
    "music-collection",
    "documents-by-type",
    "old-files-archive",
}


def test_all_eight_presets_exist_and_load() -> None:
    found = {preset.preset_id for preset in presets.list_presets()}
    assert found == EXPECTED
    for preset in presets.list_presets():
        loaded = load_rules(preset.path)
        assert loaded.rules, preset.path.name
        assert preset.name
        assert preset.name != preset.preset_id
        assert preset.tags


def test_metadata_is_read_from_comments() -> None:
    info = presets.find_preset("downloads-cleanup")
    assert info is not None
    assert info.name == "下载目录整理"
    assert "下载" in info.tags
    assert info.icon == "download"


def test_copy_preset_never_overwrites(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    first = presets.copy_preset("photos-by-year")
    second = presets.copy_preset("photos-by-year")
    assert first != second
    assert first.exists()
    assert second.exists()
    assert "(2)" in second.name


def test_copy_preset_with_suffix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    target = presets.copy_preset("desktop-tidy", suffix=" - 副本")
    assert target.name == "desktop-tidy - 副本.yaml"
    assert target.exists()


def test_install_presets_only_creates_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    created = presets.install_presets_if_missing()
    assert len(created) == len(EXPECTED)
    assert presets.install_presets_if_missing() == []


def test_unknown_preset_is_rejected() -> None:
    with pytest.raises(FileNotFoundError):
        presets.copy_preset("does-not-exist")


def test_parse_metadata_stops_at_the_rules_block() -> None:
    meta = presets.parse_metadata("# name: x\n\nrules:\n  - id: a\n")
    assert meta["name"] == "x"


def test_find_preset_returns_none_for_unknown() -> None:
    assert presets.find_preset("no-such-preset") is None


def test_presets_root_supports_frozen_builds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert presets.presets_root() == tmp_path / "presets"
