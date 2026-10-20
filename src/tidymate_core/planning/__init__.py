"""Planning: build the change plan, intra-batch conflict and ancestor detection.

Stage 0: package placeholder only. Planning is where dry-run lives: it must be able to
produce a complete plan without any write access at all.
"""

from __future__ import annotations

__all__: list[str] = []
