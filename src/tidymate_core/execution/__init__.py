"""Execution: move / rename / copy / trash, and the matching undo engine.

Stage 5-6 introduced the executor; stage 7-9 add the undo engine, error reports and
``verify``. This package is the only place in the product allowed to write. It still never
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
from tidymate_core.execution.reports import ReportPaths, render_json, render_markdown, write_reports
from tidymate_core.execution.undo import Undoer, UndoOutcome, UndoReport
from tidymate_core.execution.verify import VerifyProblem, verify_batch

__all__ = [
    "ExecutionOptions",
    "ExecutionReport",
    "Executor",
    "GateProblem",
    "GateResult",
    "OperationOutcome",
    "OutcomeState",
    "ReportPaths",
    "UndoOutcome",
    "UndoReport",
    "Undoer",
    "VerifyProblem",
    "evaluate",
    "render_json",
    "render_markdown",
    "verify_batch",
    "write_reports",
]
