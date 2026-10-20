"""Plan construction: scan, match, render, validate, detect conflicts.

This is the heart of the dry-run. It reads the file system (``exists`` checks, directory
listing) and writes nothing. Every entry ends up in exactly one visible state:
``execute``, ``skip`` or ``reject`` - never silently dropped (iron rule 10).

Ordering is deterministic: entries are sorted by normalised path before sequence numbers
are assigned, so two runs over the same tree produce the same plan and the same hash.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, replace
from datetime import UTC, datetime, tzinfo
from pathlib import PureWindowsPath

from tidymate_core.planning.conflicts import ConflictIndex
from tidymate_core.planning.models import (
    ChangeStatus,
    ConflictType,
    Plan,
    PlannedChange,
    PlanStats,
    RejectReason,
)
from tidymate_core.planning.targets import (
    TargetError,
    build_target,
    conflicts_on_disk,
)
from tidymate_core.rules.engine import RuleSet
from tidymate_core.rules.models import ConflictPolicy, Rule, RuleOp
from tidymate_core.rules.template import TemplateContext, TemplateError, render_template
from tidymate_core.safety import paths
from tidymate_core.scanning import FileEntry, ScanConfig, scan
from tidymate_core.scanning.models import ErrorFlags, utc_now

_SPECIAL_FLAGS: tuple[ErrorFlags, ...] = (
    ErrorFlags.LONG_PATH,
    ErrorFlags.REPARSE_POINT,
    ErrorFlags.READ_ONLY,
    ErrorFlags.SYSTEM,
    ErrorFlags.HIDDEN,
    ErrorFlags.UNC,
    ErrorFlags.OFFLINE,
    ErrorFlags.ADS,
    ErrorFlags.ONEDRIVE_PLACEHOLDER,
)

#: Human guidance attached to the two "do not touch this yet" skip kinds. The text is
#: part of the report contract, not a log line: users act on it.
ADS_GUIDANCE = (
    "NTFS alternate data stream present (e.g. Zone.Identifier): moving the file can "
    "drop the stream. Inspect it with Sysinternals Streams (streams -s <file>) and "
    "decide whether to clear it (streams -d <file>) before organising."
)
ONEDRIVE_GUIDANCE = (
    "OneDrive/cloud placeholder not fully downloaded: moving it can leave a 0-byte "
    "placeholder and corrupt the original. In the OneDrive client choose "
    '"Always keep on this device", wait for the download to finish, then re-run.'
)


@dataclass(frozen=True, slots=True)
class PlanRequest:
    """Everything needed to preview a run. No output path is written here."""

    scan: ScanConfig
    rules: RuleSet
    output_root: str
    created_at: datetime | None = None
    local_tz: tzinfo | None = None
    now: datetime | None = None
    #: Pre-scanned entries. ``None`` means "run the scan" (the normal path). Tests use
    #: this to inject entries whose OS attributes cannot be produced on demand, e.g. a
    #: OneDrive placeholder - Windows refuses to set ``RECALL_ON_DATA_ACCESS`` by hand.
    entries: tuple[FileEntry, ...] | None = None


def _system_local_tz() -> tzinfo:
    local = datetime.now().astimezone().tzinfo
    return local if local is not None else UTC


def _entry_flags(entry: FileEntry) -> tuple[str, ...]:
    return tuple((flag.name or "").lower() for flag in _SPECIAL_FLAGS if entry.error_flags & flag)


def _special_reason(entry: FileEntry) -> str | None:
    """Return why a special file is refused, or ``None`` for an ordinary file."""
    if entry.is_read_only:
        return "read-only file: skipped by default (iron rule 8)"
    if entry.error_flags & ErrorFlags.SYSTEM:
        return "system-flagged file: skipped by default (iron rule 8)"
    if entry.is_reparse_point:
        return "reparse point / link: skipped by default (iron rule 8)"
    if entry.is_long_path:
        return f"source path is {entry.path_length} characters (>260): skipped by default"
    return None


def _make_change(
    entry: FileEntry,
    rule: Rule,
    seq: int,
    *,
    dst: str | None = None,
    status: ChangeStatus = ChangeStatus.EXECUTE,
    conflict: ConflictType = ConflictType.NONE,
    reason: RejectReason | None = None,
    notes: tuple[str, ...] = (),
    error_kind: str | None = None,
) -> PlannedChange:
    return PlannedChange(
        seq=seq,
        src=entry.full_path,
        dst=dst,
        op=rule.action.op.value,
        rule_id=rule.id,
        status=status,
        conflict=conflict,
        reason=reason,
        flags=_entry_flags(entry),
        notes=notes,
        size=entry.size,
        error_kind=error_kind,
    )


def _next_available(target: str, *, now: datetime) -> str | None:
    """Find a free destination name, degrading in two documented steps.

    1. ``name (2).ext`` ... ``name (999).ext``;
    2. ``name_yyyyMMdd-HHmmss_ffffff.ext`` (the timestamp comes from the plan's
       ``created_at``, so two dry-runs over the same tree still hash identically);
    3. give up and return ``None`` - the caller marks the entry ``failed``.
    """
    target_path = PureWindowsPath(target)
    stem, extension = str(target_path.with_suffix("")), target_path.suffix
    for index in range(2, 1000):
        candidate = f"{stem} ({index}){extension}"
        if not conflicts_on_disk(candidate):
            return candidate

    stamp = now.astimezone(UTC).strftime("%Y%m%d-%H%M%S_%f")
    fallback = f"{stem}_{stamp}{extension}"
    if not conflicts_on_disk(fallback):
        return fallback
    return None


def _plan_one(
    seq: int,
    entry: FileEntry,
    request: PlanRequest,
    local_tz: tzinfo,
    created: datetime,
) -> PlannedChange | None:
    rule = request.rules.match(entry, now=request.now)
    if rule is None:
        return None

    # ADS and cloud placeholders are *skips*, not rejects: the file is fine where it is,
    # and a move is what would damage it. The executor must never touch these (stage 5).
    if entry.has_alternate_streams:
        streams = ", ".join(entry.alternate_streams)
        detail = f"alternate data stream(s): {streams}"
        if entry.is_onedrive_placeholder:
            detail += "; the file is also a cloud placeholder"
        return _make_change(
            entry,
            rule,
            seq,
            status=ChangeStatus.SKIP,
            error_kind="ads",
            notes=(detail, ADS_GUIDANCE),
        )
    if entry.is_onedrive_placeholder:
        return _make_change(
            entry,
            rule,
            seq,
            status=ChangeStatus.SKIP,
            error_kind="onedrive_placeholder",
            notes=(
                "cloud placeholder attributes (OFFLINE / RECALL_ON_OPEN / "
                "RECALL_ON_DATA_ACCESS): the file is not fully local",
                ONEDRIVE_GUIDANCE,
            ),
        )

    special = _special_reason(entry)
    if special is not None:
        return _make_change(
            entry,
            rule,
            seq,
            status=ChangeStatus.REJECT,
            reason=RejectReason.SPECIAL_FILE,
            notes=(special,),
        )

    if rule.action.op is RuleOp.TRASH:
        return _make_change(entry, rule, seq, dst=None)

    context = TemplateContext(
        mtime_utc=entry.mtime_utc,
        local_tz=local_tz,
        ext=entry.ext,
        stem=entry.stem,
        name=entry.name,
        parent=PureWindowsPath(entry.full_path).parent.name,
        size=entry.size,
        rule_id=rule.id,
        seq=seq,
    )
    try:
        rendered = render_template(rule.action.template, context)
    except TemplateError as exc:
        return _make_change(
            entry,
            rule,
            seq,
            status=ChangeStatus.REJECT,
            reason=RejectReason.TEMPLATE_ERROR,
            notes=(str(exc),),
        )

    notes = list(rendered.notes)
    try:
        target = build_target(request.output_root, rendered.segments)
    except TargetError as exc:
        try:
            reason = RejectReason(exc.reason)
        except ValueError:  # pragma: no cover - TargetError.reason is always one of these
            reason = RejectReason.ILLEGAL_TARGET
        return _make_change(
            entry,
            rule,
            seq,
            status=ChangeStatus.REJECT,
            reason=reason,
            notes=(str(exc),),
        )

    if paths.is_ancestor_or_self(target.display, entry.full_path):
        return _make_change(
            entry,
            rule,
            seq,
            dst=target.display,
            status=ChangeStatus.REJECT,
            reason=RejectReason.ANCESTOR,
            notes=(f"target {target.display!r} is the source itself or one of its ancestors",),
        )

    if target.requires_extended:
        notes.append(f"long target path ({target.length} chars); requires the \\\\?\\ form")

    if conflicts_on_disk(target.display):
        if rule.action.conflict is ConflictPolicy.SKIP:
            return _make_change(
                entry,
                rule,
                seq,
                dst=target.display,
                status=ChangeStatus.SKIP,
                conflict=ConflictType.EXISTS_ON_DISK,
                notes=tuple(notes),
            )
        if rule.action.conflict is ConflictPolicy.ASK:
            return _make_change(
                entry,
                rule,
                seq,
                dst=target.display,
                status=ChangeStatus.SKIP,
                conflict=ConflictType.NEEDS_REVIEW,
                notes=(*notes, "conflict policy 'ask': needs a human decision"),
            )
        candidate = _next_available(target.display, now=created)
        if candidate is None:
            return _make_change(
                entry,
                rule,
                seq,
                dst=target.display,
                status=ChangeStatus.FAILED,
                conflict=ConflictType.EXISTS_ON_DISK,
                error_kind="rename_exhausted",
                notes=(
                    *notes,
                    "rename exhausted: 'name (2..999)' and the timestamp fallback are "
                    "both taken; resolve the destination by hand",
                ),
            )
        notes.append(
            f"renamed to avoid an existing file: {PureWindowsPath(candidate).name}",
        )
        return _make_change(
            entry,
            rule,
            seq,
            dst=candidate,
            status=ChangeStatus.EXECUTE,
            notes=tuple(notes),
        )

    return _make_change(entry, rule, seq, dst=target.display, notes=tuple(notes))


def mark_intra_batch(changes: list[PlannedChange]) -> tuple[PlannedChange, ...]:
    """Mark later claimants of an already-claimed destination."""
    index = ConflictIndex()
    result: list[PlannedChange] = []
    for change in changes:
        if change.dst is None or change.status is not ChangeStatus.EXECUTE:
            result.append(change)
            continue
        first = index.claim(change.dst, change.seq)
        if first is None:
            result.append(change)
            continue
        result.append(
            replace(
                change,
                status=ChangeStatus.SKIP,
                conflict=ConflictType.INTRA_BATCH,
                notes=(*change.notes, f"same destination as seq {first}"),
            ),
        )
    return tuple(result)


def change_to_dict(change: PlannedChange) -> dict[str, object]:
    return {
        "seq": change.seq,
        "src": change.src,
        "dst": change.dst,
        "op": change.op,
        "rule_id": change.rule_id,
        "status": change.status.value,
        "conflict": change.conflict.value,
        "reason": change.reason.value if change.reason is not None else None,
        "error_kind": change.error_kind,
        "flags": list(change.flags),
        "notes": list(change.notes),
        "size": change.size,
    }


def stats_to_dict(stats: PlanStats) -> dict[str, object]:
    return {
        "total_scanned": stats.total_scanned,
        "matched": stats.matched,
        "will_execute": stats.will_execute,
        "will_skip": stats.will_skip,
        "rejected": stats.rejected,
        "conflicts": stats.conflicts,
        "conflicts_exists": stats.conflicts_exists,
        "conflicts_intra": stats.conflicts_intra,
        "conflicts_review": stats.conflicts_review,
        "bytes_freed": stats.bytes_freed,
        "bytes_added": stats.bytes_added,
        "failed": stats.failed,
        "ads_skipped": stats.ads_skipped,
        "onedrive_skipped": stats.onedrive_skipped,
        "by_rule": dict(sorted(stats.by_rule.items())),
    }


def compute_plan_hash(changes: tuple[PlannedChange, ...], stats: PlanStats) -> str:
    """Hash of the *content* of a plan: no timestamp, no batch id, no machine state."""
    payload = {
        "changes": [change_to_dict(change) for change in changes],
        "stats": stats_to_dict(stats),
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _build_stats(
    scanned: int,
    changes: tuple[PlannedChange, ...],
) -> PlanStats:
    by_rule = Counter(change.rule_id for change in changes if change.rule_id is not None)
    return PlanStats(
        total_scanned=scanned,
        matched=len(changes),
        will_execute=sum(1 for change in changes if change.is_executable),
        will_skip=sum(1 for change in changes if change.status is ChangeStatus.SKIP),
        rejected=sum(1 for change in changes if change.status is ChangeStatus.REJECT),
        failed=sum(1 for change in changes if change.status is ChangeStatus.FAILED),
        ads_skipped=sum(
            1
            for change in changes
            if change.status is ChangeStatus.SKIP and change.error_kind == "ads"
        ),
        onedrive_skipped=sum(
            1
            for change in changes
            if change.status is ChangeStatus.SKIP and change.error_kind == "onedrive_placeholder"
        ),
        conflicts=sum(1 for change in changes if change.conflict is not ConflictType.NONE),
        conflicts_exists=sum(
            1 for change in changes if change.conflict is ConflictType.EXISTS_ON_DISK
        ),
        conflicts_intra=sum(1 for change in changes if change.conflict is ConflictType.INTRA_BATCH),
        conflicts_review=sum(
            1 for change in changes if change.conflict is ConflictType.NEEDS_REVIEW
        ),
        bytes_freed=sum(
            change.size
            for change in changes
            if change.op == RuleOp.TRASH.value and change.is_executable
        ),
        bytes_added=sum(
            change.size
            for change in changes
            if change.op == RuleOp.COPY.value and change.is_executable
        ),
        by_rule=dict(sorted(by_rule.items())),
    )


def build_plan(request: PlanRequest) -> Plan:
    """Scan, match and build the complete dry-run plan."""
    created = request.created_at or utc_now()
    local_tz = request.local_tz or _system_local_tz()

    scan_errors: tuple[str, ...] = ()
    if request.entries is not None:
        entries = sorted(request.entries, key=lambda entry: entry.normalized_path.casefold())
    else:
        result = scan(request.scan)
        entries = sorted(result.entries, key=lambda entry: entry.normalized_path.casefold())
        scan_errors = tuple(error.message for error in result.errors)

    changes: list[PlannedChange] = []
    for seq, entry in enumerate(entries, start=1):
        change = _plan_one(seq, entry, request, local_tz, created)
        if change is not None:
            changes.append(change)

    marked = mark_intra_batch(changes)
    stats = _build_stats(len(entries), marked)
    plan_hash = compute_plan_hash(marked, stats)

    return Plan(
        batch_id=f"dryrun-{created.astimezone().strftime('%Y%m%d-%H%M%S')}",
        created_at=created,
        output_root=paths.normalize(request.output_root),
        rules_source=request.rules.source,
        changes=marked,
        stats=stats,
        plan_hash=plan_hash,
        warnings=tuple(request.rules.warnings) + scan_errors,
    )
