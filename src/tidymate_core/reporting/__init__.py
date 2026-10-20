"""Reporting: dry-run report, error report, statistics.

Stage 0: package placeholder only. Every number produced here will be derived from a SQL
aggregation over the journal (never from an in-memory counter), so reported totals can be
reproduced from the database (iron rule 10).
"""

from __future__ import annotations

__all__: list[str] = []
