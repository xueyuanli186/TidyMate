"""Scanning: traversal, exclusion filters, error tolerance.

Public surface:

* :class:`~tidymate_core.scanning.config.ScanConfig` - roots and filters
* :class:`~tidymate_core.scanning.models.FileEntry` - one discovered file
* :class:`~tidymate_core.scanning.models.ScanError` - one failure or documented skip
* :class:`~tidymate_core.scanning.models.ScanStats` - counters (never fudged)
* :func:`~tidymate_core.scanning.walker.iter_scan` - streaming walk
* :func:`~tidymate_core.scanning.walker.scan` - materialised convenience wrapper

This package is read-only by construction: it opens directories and stats files, and it
must never create, modify or delete anything. ``tests/.../test_readonly_guard.py``
enforces that mechanically.
"""

from __future__ import annotations

from tidymate_core.scanning.cancel import CancelToken
from tidymate_core.scanning.config import ScanConfig
from tidymate_core.scanning.models import (
    ErrorFlags,
    FileAttributes,
    FileEntry,
    ScanError,
    ScanErrorKind,
    ScanResult,
    ScanStats,
)
from tidymate_core.scanning.walker import iter_scan, scan

__all__ = [
    "CancelToken",
    "ErrorFlags",
    "FileAttributes",
    "FileEntry",
    "ScanConfig",
    "ScanError",
    "ScanErrorKind",
    "ScanResult",
    "ScanStats",
    "iter_scan",
    "scan",
]
