"""Planned-change data model for dry-run previews.

Nothing here writes, moves or deletes. A :class:`Plan` is a *description* of what a later
stage would do, with every reason it might not happen recorded next to the entry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class ChangeStatus(StrEnum):
    """What would happen to this entry if ``--apply`` existed today."""

    EXECUTE = "execute"
    SKIP = "skip"
    REJECT = "reject"
    #: A step that was attempted on paper and cannot be completed (e.g. every fallback
    #: name for a ``conflict: rename`` is taken). Distinct from ``reject``: the input was
    #: valid, the environment refused it.
    FAILED = "failed"


class ConflictType(StrEnum):
    """Why an entry cannot simply proceed."""

    NONE = "none"
    EXISTS_ON_DISK = "exists_on_disk"
    INTRA_BATCH = "intra_batch"
    NEEDS_REVIEW = "needs_review"


class RejectReason(StrEnum):
    """Hard refusals. These are never "temporarily skipped"."""

    BLACKLIST = "blacklist"
    ANCESTOR = "ancestor"
    SPECIAL_FILE = "special_file"
    RESERVED_NAME = "reserved_name"
    PATH_TOO_LONG = "path_too_long"
    ILLEGAL_TARGET = "illegal_target"
    TEMPLATE_ERROR = "template_error"


@dataclass(frozen=True, slots=True)
class PlannedChange:
    """One source file and the destination the rules would send it to."""

    seq: int
    src: str
    dst: str | None
    op: str | None
    rule_id: str | None
    status: ChangeStatus
    conflict: ConflictType = ConflictType.NONE
    reason: RejectReason | None = None
    flags: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    size: int = 0
    #: Machine-readable sub-reason for skips the executor must not silently perform:
    #: ``"ads"``, ``"onedrive_placeholder"`` or ``"rename_exhausted"``.
    error_kind: str | None = None

    @property
    def is_executable(self) -> bool:
        """True only for entries that would actually be acted on."""
        return self.status is ChangeStatus.EXECUTE and self.conflict is ConflictType.NONE


@dataclass(frozen=True, slots=True)
class PlanStats:
    """Numbers that must reconcile with the per-entry list (iron rule 10)."""

    total_scanned: int
    matched: int
    will_execute: int
    will_skip: int
    rejected: int
    conflicts: int
    conflicts_exists: int
    conflicts_intra: int
    conflicts_review: int
    bytes_freed: int
    bytes_added: int
    by_rule: dict[str, int] = field(default_factory=dict)
    #: Entries that could not be planned at all (``ChangeStatus.FAILED``).
    failed: int = 0
    #: Skipped because an NTFS alternate data stream would be lost on move.
    ads_skipped: int = 0
    #: Skipped because the file is a OneDrive/cloud placeholder that is not hydrated.
    onedrive_skipped: int = 0


@dataclass(frozen=True, slots=True)
class Plan:
    """A complete, reproducible dry-run plan."""

    batch_id: str
    created_at: datetime
    output_root: str
    rules_source: str
    changes: tuple[PlannedChange, ...]
    stats: PlanStats
    plan_hash: str
    warnings: tuple[str, ...] = ()

    def executable(self) -> tuple[PlannedChange, ...]:
        """Entries that would be executed (used by every report renderer)."""
        return tuple(change for change in self.changes if change.is_executable)

    def with_conflict(self) -> tuple[PlannedChange, ...]:
        """Entries with any conflict flag."""
        return tuple(change for change in self.changes if change.conflict is not ConflictType.NONE)

    def rejected(self) -> tuple[PlannedChange, ...]:
        """Entries refused outright."""
        return tuple(change for change in self.changes if change.status is ChangeStatus.REJECT)

    def failed(self) -> tuple[PlannedChange, ...]:
        """Entries that could not be planned even after every fallback."""
        return tuple(change for change in self.changes if change.status is ChangeStatus.FAILED)

    def skipped_with_kind(self, kind: str) -> tuple[PlannedChange, ...]:
        """Skipped entries carrying one machine-readable ``error_kind``."""
        return tuple(
            change
            for change in self.changes
            if change.status is ChangeStatus.SKIP and change.error_kind == kind
        )
