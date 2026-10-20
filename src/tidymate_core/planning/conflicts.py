"""Destination conflict detection.

Two independent questions:

1. **Is something already on disk?** A read-only ``exists`` check.
2. **Do two planned changes target the same place?** A pure in-memory map.

Identity is computed the way NTFS compares names: Unicode NFC, case-insensitive, trailing
dots and spaces ignored. That is why ``Report.pdf`` and ``report.pdf`` collide here even
though they are different strings - on Windows they are the same file, and a plan that
pretends otherwise would fail at execution time.

The first change for an identity keeps it; every later one is marked ``INTRA_BATCH`` and
skipped. "First" means lowest ``seq``, which is stable because entries are sorted before
sequencing.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field


def conflict_key(path: str) -> str:
    """Return the Windows-equivalent identity of a destination path."""
    normalized = unicodedata.normalize("NFC", path)
    return normalized.rstrip(" .").casefold()


@dataclass(slots=True)
class ConflictIndex:
    """Map of conflict identity to the sequence numbers that claim it."""

    _claims: dict[str, list[int]] = field(default_factory=dict)

    def claim(self, path: str, seq: int) -> int | None:
        """Register *seq* as claiming *path*.

        Returns the sequence number of the earlier claim when this is a duplicate, or
        ``None`` when the path was still free.
        """
        key = conflict_key(path)
        existing = self._claims.get(key)
        if existing:
            existing.append(seq)
            return existing[0]
        self._claims[key] = [seq]
        return None

    def duplicates(self) -> dict[str, list[int]]:
        """Return only the identities with more than one claimant."""
        return {key: list(seqs) for key, seqs in self._claims.items() if len(seqs) > 1}

    def __len__(self) -> int:
        return len(self._claims)
