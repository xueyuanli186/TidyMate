"""Scan configuration and its validation.

Defaults encode the project's stance, not convenience:

* ``follow_symlinks=False`` - a junction loop must not be able to walk the whole disk
  (iron rule 8);
* ``max_depth``/``max_file_size`` are opt-in limits, never silent truncation;
* every root must be absolute, because a relative root makes the report unreproducible.
"""

from __future__ import annotations

import ntpath
from dataclasses import dataclass

from tidymate_core.safety import paths


@dataclass(frozen=True, slots=True)
class ScanConfig:
    """Everything the scanner needs to know before it touches a directory."""

    roots: tuple[str, ...]
    exclude_dirs: tuple[str, ...] = ()
    exclude_hidden: bool = False
    exclude_system: bool = False
    follow_symlinks: bool = False
    max_depth: int | None = None
    max_file_size: int | None = None
    measure_memory: bool = False
    #: Ask the OS for alternate data streams on every regular file. Costs one extra
    #: handle per file, so benchmarks may turn it off; the dry-run path keeps it on
    #: because a stream that vanishes on move is data loss (iron rule 8).
    detect_alternate_streams: bool = True

    def __post_init__(self) -> None:
        if not self.roots:
            raise ValueError("ScanConfig.roots must contain at least one root")
        for root in self.roots:
            if not isinstance(root, str) or not root:
                raise ValueError(f"invalid root: {root!r}")
            if not ntpath.isabs(paths.from_extended(root)):
                raise ValueError(f"scan roots must be absolute paths, got {root!r}")
        for pattern in self.exclude_dirs:
            if not isinstance(pattern, str) or not pattern.strip():
                raise ValueError(f"invalid exclude_dirs entry: {pattern!r}")
        if self.max_depth is not None and self.max_depth < 0:
            raise ValueError("max_depth must be >= 0 or None")
        if self.max_file_size is not None and self.max_file_size <= 0:
            raise ValueError("max_file_size must be > 0 or None")

    @property
    def normalized_roots(self) -> tuple[str, ...]:
        """Roots with canonical separators and casing (order preserved, duplicates kept)."""
        return tuple(paths.normalize(root) for root in self.roots)

    @property
    def excluded_absolute(self) -> frozenset[str]:
        """``exclude_dirs`` entries that are absolute paths, lower-cased for comparison."""
        return frozenset(
            paths.normalize(pattern).casefold()
            for pattern in self.exclude_dirs
            if ntpath.isabs(paths.from_extended(pattern))
        )

    @property
    def excluded_globs(self) -> tuple[str, ...]:
        """``exclude_dirs`` entries that are name globs (lower-cased)."""
        return tuple(
            pattern.casefold()
            for pattern in self.exclude_dirs
            if not ntpath.isabs(paths.from_extended(pattern))
        )
