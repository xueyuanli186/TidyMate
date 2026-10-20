"""Planning: build the change plan, detect conflicts, render the dry-run report.

Public surface:

* :func:`~tidymate_core.planning.planner.build_plan` - scan + match + validate, read-only
* :class:`~tidymate_core.planning.models.Plan` - the reproducible plan
* :func:`~tidymate_core.planning.report.render_table` / ``render_markdown`` / ``plan_to_json``
* :func:`~tidymate_core.planning.artifacts.write_artifacts` - the only writer, confined to
  the output root

No function in this package moves, renames, copies or deletes a file. The executor stage
owns that, and only after an explicit ``--apply``.
"""

from __future__ import annotations

from tidymate_core.planning.artifacts import (
    ArtifactError,
    ArtifactPaths,
    write_artifacts,
)
from tidymate_core.planning.conflicts import ConflictIndex, conflict_key
from tidymate_core.planning.models import (
    ChangeStatus,
    ConflictType,
    Plan,
    PlannedChange,
    PlanStats,
    RejectReason,
)
from tidymate_core.planning.planner import PlanRequest, build_plan, compute_plan_hash
from tidymate_core.planning.report import (
    plan_to_dict,
    plan_to_json,
    render_markdown,
    render_table,
    stats_lines,
)
from tidymate_core.planning.targets import (
    MAX_TARGET_LENGTH,
    RESERVED_NAMES,
    TargetError,
    TargetPath,
    build_target,
    conflicts_on_disk,
    is_reserved_name,
)

__all__ = [
    "MAX_TARGET_LENGTH",
    "RESERVED_NAMES",
    "ArtifactError",
    "ArtifactPaths",
    "ChangeStatus",
    "ConflictIndex",
    "ConflictType",
    "Plan",
    "PlanRequest",
    "PlanStats",
    "PlannedChange",
    "RejectReason",
    "TargetError",
    "TargetPath",
    "build_plan",
    "build_target",
    "compute_plan_hash",
    "conflict_key",
    "conflicts_on_disk",
    "is_reserved_name",
    "plan_to_dict",
    "plan_to_json",
    "render_markdown",
    "render_table",
    "stats_lines",
    "write_artifacts",
]
