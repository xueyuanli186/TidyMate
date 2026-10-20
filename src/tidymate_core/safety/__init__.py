"""Safety: hard-coded blacklist, special-file detection, path normalisation, long paths.

Stage 0: only :mod:`tidymate_core.safety.forbidden_apis` exists. It is a *static source
scanner* that fails CI if a permanent-delete API appears anywhere in the repository. That
is the enforcement arm of iron rule 3, and it is the one piece of safety code that had to
land in stage 0 rather than later.
"""

from __future__ import annotations

__all__: list[str] = []
