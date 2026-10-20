"""Destination path construction and per-target validation.

Everything here is pure string/path logic plus read-only ``exists`` checks. No file is
created, moved or deleted.

Rules enforced on a destination:

* it must live under ``output_root`` (templates are relative, and the joiner refuses
  anything that escapes);
* it must not hit the hard-coded blacklist;
* its file name must not be a Windows reserved device name;
* a full path longer than 260 characters requires the ``\\\\?\\`` form; longer than 32767
  is not executable at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tidymate_core.safety import paths
from tidymate_core.safety.blacklist import check_blacklisted

#: Windows reserved device names, with or without an extension.
RESERVED_NAMES: frozenset[str] = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)},
)

#: Beyond this, no Win32 path API works, even with the extended prefix.
MAX_TARGET_LENGTH = 32767


class TargetError(ValueError):
    """The destination cannot be used; ``reason`` names the category."""

    def __init__(self, message: str, *, reason: str) -> None:
        self.reason = reason
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class TargetPath:
    """A validated destination path, in display and extended form."""

    display: str
    extended: str
    length: int
    requires_extended: bool
    too_long: bool


def is_reserved_name(name: str) -> bool:
    """True for ``CON``, ``NUL``, ``COM1``... including ``CON.txt`` forms."""
    stem = name.split(".")[0].rstrip(" ")
    return stem.casefold() in RESERVED_NAMES


def join_under_root(output_root: str, segments: tuple[str, ...]) -> str:
    """Join sanitised segments under *output_root*, refusing to escape it.

    Raises:
        TargetError: when a segment contains a separator or ``..``.
    """
    root = paths.normalize(output_root)
    current = root
    for segment in segments:
        if not segment:
            raise TargetError("empty path segment", reason="illegal_target")
        if segment in {".", ".."} or "\\" in segment or "/" in segment:
            raise TargetError(
                f"segment {segment!r} would escape the output root",
                reason="illegal_target",
            )
        current = paths.join(current, segment)
    return paths.normalize(current)


def build_target(output_root: str, segments: tuple[str, ...]) -> TargetPath:
    """Build and validate the destination path for one change.

    Raises:
        TargetError: with ``reason`` set to ``blacklist``, ``reserved_name`` or
            ``path_too_long``.
    """
    display = join_under_root(output_root, segments)

    if not paths.is_ancestor_or_self(paths.normalize(output_root), display):
        raise TargetError(
            f"target {display!r} is not under the output root",
            reason="illegal_target",
        )

    blacklisted = check_blacklisted(display)
    if blacklisted is not None:
        raise TargetError(
            f"target is inside a protected location: {blacklisted}",
            reason="blacklist",
        )

    if is_reserved_name(segments[-1] if segments else ""):
        raise TargetError(
            f"target file name {segments[-1]!r} is a reserved Windows device name",
            reason="reserved_name",
        )

    length = paths.path_length(display)
    if length > MAX_TARGET_LENGTH:
        raise TargetError(
            f"target path is {length} characters, beyond the {MAX_TARGET_LENGTH} limit",
            reason="path_too_long",
        )

    requires_extended = length > paths.MAX_PATH
    return TargetPath(
        display=display,
        extended=paths.to_extended(display),
        length=length,
        requires_extended=requires_extended,
        too_long=False,
    )


def conflicts_on_disk(target: str) -> bool:
    """Read-only check: does something already exist at *target*?

    Uses the extended form so destinations beyond MAX_PATH are still checked, and never
    creates anything.
    """
    return Path(paths.to_extended(target)).exists()
