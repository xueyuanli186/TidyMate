"""Execution: move / rename / copy / trash with a per-item state machine.

Stage 5-6: this package is the only place in the product allowed to write. It still never
deletes permanently - ``trash`` goes through ``send2trash``, enforced by the static scan in
``scripts/check_forbidden_apis.py``.
"""

from __future__ import annotations

from tidymate_core.execution.executor import Executor
from tidymate_core.execution.gate import GateProblem, GateResult, evaluate
from tidymate_core.execution.models import (
    ExecutionOptions,
    ExecutionReport,
    OperationOutcome,
    OutcomeState,
)

__all__ = [
    "ExecutionOptions",
    "ExecutionReport",
    "Executor",
    "GateProblem",
    "GateResult",
    "OperationOutcome",
    "OutcomeState",
    "evaluate",
]
