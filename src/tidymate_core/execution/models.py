"""Execution data model: options, per-operation outcomes, batch report.

Nothing here performs I/O; it is the vocabulary shared by the gate, the executor and the
CLI, and it is what gets written to the journal and printed to the user.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class OutcomeState(StrEnum):
    """Final state of one operation. ``ok`` is only written after the file system agrees."""

    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True, slots=True)
class ExecutionOptions:
    """Knobs that change *how much* runs, never *whether* safety checks run."""

    limit: int | None = None
    only_rule: str | None = None
    clear_readonly: bool = False
    allow_unc: bool = False
    #: Stop after this many consecutive failures (circuit breaker).
    fuse_after: int = 5

    def __post_init__(self) -> None:
        if self.limit is not None and self.limit < 1:
            raise ValueError("limit must be >= 1")
        if self.fuse_after < 1:
            raise ValueError("fuse_after must be >= 1")


@dataclass(frozen=True, slots=True)
class OperationOutcome:
    """What actually happened to one planned change."""

    seq: int
    state: OutcomeState
    src: str
    dst: str | None = None
    final_dst: str | None = None
    error: str | None = None
    error_kind: str | None = None
    cross_volume: bool | None = None


@dataclass(slots=True)
class ExecutionReport:
    """Everything one ``apply`` run learned, in sequence order."""

    batch_id: str
    outcomes: list[OperationOutcome] = field(default_factory=list)
    cancelled: bool = False
    fused: bool = False
    fatal: str | None = None

    @property
    def counts(self) -> dict[str, int]:
        """Count outcomes by state, including zero-valued keys."""
        result = {state.value: 0 for state in OutcomeState}
        for outcome in self.outcomes:
            result[outcome.state.value] += 1
        return result

    @property
    def ok(self) -> int:
        """Number of operations that really happened."""
        return self.counts[OutcomeState.OK.value]

    def failures(self) -> list[OperationOutcome]:
        """Every failed outcome, for the error summary."""
        return [outcome for outcome in self.outcomes if outcome.state is OutcomeState.FAILED]
