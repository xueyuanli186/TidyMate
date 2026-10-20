"""Safety: path normalisation, long paths, blacklists and static guards.

Three kinds of guard live here, all of them *mechanical* rather than aspirational:

* :mod:`tidymate_core.safety.paths` - the only place that knows about ``\\\\?\\`` prefixes;
* :mod:`tidymate_core.safety.forbidden_apis` - bans permanent-delete calls (iron rule 3);
* :mod:`tidymate_core.safety.readonly_guard` - bans *all* write calls in the read-only
  stages (iron rule 2: nothing writes unless ``--apply`` says so).
"""

from __future__ import annotations

from tidymate_core.safety import paths
from tidymate_core.safety.paths import (
    MAX_PATH,
    from_extended,
    is_ancestor_or_self,
    is_long_path,
    is_unc,
    normalize,
    path_length,
    to_extended,
)

__all__ = [
    "MAX_PATH",
    "from_extended",
    "is_ancestor_or_self",
    "is_long_path",
    "is_unc",
    "normalize",
    "path_length",
    "paths",
    "to_extended",
]
