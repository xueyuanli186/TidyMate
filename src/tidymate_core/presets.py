"""Preset rule library and the user's rule directory (stage 10).

Presets ship read-only inside the installation (``presets/``); the user's editable copies
live in ``%LOCALAPPDATA%\\TidyMate\\rules``. Both are plain YAML parsed by the same strict
loader, so a preset cannot use a condition the engine does not understand.

Metadata lives in leading comment lines so the file stays 100% compatible with the rules
loader and with hand editing::

    # name: 下载目录整理
    # description: 把下载目录里的文件按类型归类
    # author: TidyMate Team
    # version: 1.0
    # tags: [下载, 整理]
    # icon: download
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_META_LINE = re.compile(r"^#\s*(?P<key>[a-zA-Z_]+)\s*:\s*(?P<value>.*)$")


@dataclass(frozen=True, slots=True)
class PresetInfo:
    """One preset rule file and its display metadata."""

    preset_id: str
    name: str
    description: str
    tags: tuple[str, ...]
    icon: str
    path: Path


def presets_root() -> Path:
    """Directory holding the read-only presets (works frozen and from source)."""
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base = Path(__file__).resolve().parents[2]
    return base / "presets"


def user_rules_dir() -> Path:
    """Editable rule directory; created on demand."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "TidyMate" / "rules"


def parse_metadata(text: str) -> dict[str, str]:
    """Read the leading ``# key: value`` block."""
    metadata: dict[str, str] = {}
    for line in text.splitlines():
        if line.strip() and not line.startswith("#"):
            break
        match = _META_LINE.match(line)
        if match:
            metadata[match.group("key").lower()] = match.group("value").strip()
    return metadata


def _info(path: Path) -> PresetInfo:
    text = path.read_text(encoding="utf-8")
    meta = parse_metadata(text)
    raw_tags = meta.get("tags", "").strip().strip("[]")
    tags = tuple(tag.strip() for tag in raw_tags.split(",") if tag.strip())
    return PresetInfo(
        preset_id=path.stem,
        name=meta.get("name", path.stem),
        description=meta.get("description", ""),
        tags=tags,
        icon=meta.get("icon", "file"),
        path=path,
    )


def list_presets() -> list[PresetInfo]:
    """All shipped presets, sorted by file name."""
    root = presets_root()
    if not root.is_dir():
        return []
    return [_info(path) for path in sorted(root.glob("*.yaml"))]


def find_preset(preset_id: str) -> PresetInfo | None:
    """Look up a preset by id (file stem) or by its display name."""
    for preset in list_presets():
        if preset.preset_id == preset_id or preset.name == preset_id:
            return preset
    return None


def list_user_rules() -> list[Path]:
    """Every ``*.yaml`` in the user rule directory."""
    root = user_rules_dir()
    if not root.is_dir():
        return []
    return sorted(root.glob("*.yaml"))


def copy_preset(preset_id: str, *, suffix: str = "") -> Path:
    """Copy a preset into the user directory and return the new path.

    ``suffix`` is appended to the file stem; the GUI uses `` - 副本`` for "duplicate and
    customise". An existing file is never overwritten (the copy gets a numeric suffix
    instead).
    """
    preset = find_preset(preset_id)
    if preset is None:
        raise FileNotFoundError(f"unknown preset {preset_id!r}")
    target_dir = user_rules_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{preset.preset_id}{suffix}"
    target = target_dir / f"{stem}.yaml"
    counter = 2
    while target.exists():
        target = target_dir / f"{stem} ({counter}).yaml"
        counter += 1
    target.write_text(preset.path.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def install_presets_if_missing() -> list[Path]:
    """First-run convenience: put a copy of every preset in the user directory.

    Existing files are left alone, so a user's edits are never overwritten by an upgrade.
    """
    created: list[Path] = []
    target_dir = user_rules_dir()
    for preset in list_presets():
        target = target_dir / f"{preset.preset_id}.yaml"
        if target.exists():
            continue
        target_dir.mkdir(parents=True, exist_ok=True)
        target.write_text(preset.path.read_text(encoding="utf-8"), encoding="utf-8")
        created.append(target)
    return created


__all__ = [
    "PresetInfo",
    "copy_preset",
    "find_preset",
    "install_presets_if_missing",
    "list_presets",
    "list_user_rules",
    "parse_metadata",
    "presets_root",
    "user_rules_dir",
]
