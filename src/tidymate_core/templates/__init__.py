"""Templates: parsing, variable whitelist, rendering, illegal character detection.

Stage 0: package placeholder only. Per iron rule 6 this layer *rejects* anything outside
the whitelist; it never guesses. "Sanitisation" here means producing a suggested name for
the report only, never a path that gets written to disk.
"""

from __future__ import annotations

__all__: list[str] = []
