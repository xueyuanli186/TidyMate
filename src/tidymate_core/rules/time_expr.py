"""Time expressions such as ``>=2024-01-01``, ``last-30d`` or ``older-than-1y``.

Two rules that matter and are easy to get wrong:

* **Everything compares in UTC.** A naive date in a rule file means "midnight UTC", not
  "midnight wherever the user happens to be". Display-side localisation is a reporting
  concern, not a matching one.
* **Relative windows are anchored to an explicit ``now``.** Callers pass the moment in, so
  tests are deterministic and a long scan does not drift its own reference point.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

_COMPARATORS: dict[str, Callable[[datetime, datetime], bool]] = {
    "<": lambda left, right: left < right,
    "<=": lambda left, right: left <= right,
    ">": lambda left, right: left > right,
    ">=": lambda left, right: left >= right,
    "==": lambda left, right: left == right,
    "!=": lambda left, right: left != right,
}

_ABSOLUTE = re.compile(
    r"^\s*(?P<op><=|>=|==|!=|<|>)\s*"
    r"(?P<date>\d{4}-\d{2}-\d{2})"
    r"(?:[T ](?P<time>\d{2}:\d{2}(?::\d{2})?)(?P<tz>Z|[+-]\d{2}:?\d{2})?)?\s*$",
)

_RELATIVE = re.compile(
    r"^\s*(?P<mode>last|older-than)-(?P<count>\d+)(?P<unit>[dwmy])\s*$",
    re.IGNORECASE,
)

#: Approximate durations. Deliberately fixed (30-day month, 365-day year) so a rule means
#: the same thing in February and in March. Documented, not hidden.
UNIT_SECONDS: dict[str, int] = {
    "d": 86_400,
    "w": 7 * 86_400,
    "m": 30 * 86_400,
    "y": 365 * 86_400,
}


@dataclass(frozen=True, slots=True)
class TimeCondition:
    """A parsed mtime comparison, either absolute or relative to ``now``."""

    op: str
    raw: str
    reference_utc: datetime | None = None
    relative_delta: timedelta | None = None

    def __post_init__(self) -> None:
        if (self.reference_utc is None) == (self.relative_delta is None):
            raise ValueError("TimeCondition needs exactly one of reference_utc/relative_delta")
        if self.reference_utc is not None and self.reference_utc.tzinfo is None:
            raise ValueError("reference_utc must be timezone aware")

    def threshold(self, *, now: datetime | None = None) -> datetime:
        """Return the absolute UTC instant this condition compares against."""
        if self.relative_delta is not None:
            moment = now if now is not None else datetime.now(tz=UTC)
            if moment.tzinfo is None:
                raise ValueError("now must be timezone aware")
            return moment - self.relative_delta
        # __post_init__ guarantees exactly one of the two fields is set.
        return cast("datetime", self.reference_utc)

    def matches(self, mtime_utc: datetime, *, now: datetime | None = None) -> bool:
        """Return True when *mtime_utc* satisfies the comparison."""
        if mtime_utc.tzinfo is None:
            raise ValueError("mtime_utc must be timezone aware; compare in UTC, display local")
        return _COMPARATORS[self.op](mtime_utc, self.threshold(now=now))

    def __str__(self) -> str:
        return self.raw.strip()


def parse_time_expression(text: str) -> TimeCondition:
    """Parse an absolute or relative time expression.

    Accepted forms::

        >=2024-01-01              # midnight UTC on that day
        <2024-06-01T12:30:00Z     # explicit instant
        ==2024-01-01T00:00:00+08:00
        last-30d                  # mtime within the last 30 days
        older-than-1y             # mtime older than 365 days

    Raises:
        ValueError: on anything else, including a bare date with no operator.
    """
    if not isinstance(text, str):
        raise ValueError(f"time expression must be a string, got {type(text).__name__}")

    relative = _RELATIVE.match(text)
    if relative is not None:
        count = int(relative.group("count"))
        if count <= 0:
            raise ValueError(f"relative time expression must use a positive count: {text!r}")
        unit = relative.group("unit").lower()
        delta = timedelta(seconds=count * UNIT_SECONDS[unit])
        mode = relative.group("mode").lower()
        op = ">=" if mode == "last" else "<"
        return TimeCondition(op=op, raw=text, relative_delta=delta)

    absolute = _ABSOLUTE.match(text)
    if absolute is None:
        raise ValueError(
            f"invalid time expression {text!r}: expected e.g. '>=2024-01-01' or 'last-30d'",
        )

    date_part = absolute.group("date")
    time_part = absolute.group("time") or "00:00:00"
    if time_part.count(":") == 1:
        time_part += ":00"
    zone = absolute.group("tz") or "+00:00"
    if zone == "Z":
        zone = "+00:00"
    elif ":" not in zone:
        zone = zone[:3] + ":" + zone[3:]

    try:
        parsed = datetime.fromisoformat(f"{date_part}T{time_part}{zone}")
    except ValueError as exc:
        raise ValueError(f"invalid date or time in {text!r}: {exc}") from exc

    return TimeCondition(
        op=absolute.group("op"),
        raw=text,
        reference_utc=parsed.astimezone(UTC),
    )
