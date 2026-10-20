"""Execution: move / rename / copy / trash executors with a per-item state machine.

Stage 0: package placeholder only, and deliberately empty of any write call. When this
module is implemented, ``trash`` must go through send2trash and nothing here may call a
permanent-delete API (see ``tidymate_core.safety.forbidden_apis``, enforced in CI).
"""

from __future__ import annotations

__all__: list[str] = []
