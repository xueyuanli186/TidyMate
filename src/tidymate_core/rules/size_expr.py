"""Size expressions such as ``>=1MB`` or ``==0B``.

Binary units are used (1 KB = 1024 B), because that is what file sizes mean on Windows and
what users expect from a file organiser. The unit is case-insensitive.

Decimal amounts are converted with :class:`decimal.Decimal` so ``1.5KB`` is exactly 1536
bytes rather than "1536 or maybe 1535".
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

#: Binary multipliers. 1 KB = 1024 B.
UNIT_MULTIPLIERS: dict[str, int] = {
    "b": 1,
    "kb": 1024,
    "mb": 1024**2,
    "gb": 1024**3,
    "tb": 1024**4,
}

_COMPARATORS: dict[str, Callable[[int, int], bool]] = {
    "<": lambda left, right: left < right,
    "<=": lambda left, right: left <= right,
    ">": lambda left, right: left > right,
    ">=": lambda left, right: left >= right,
    "==": lambda left, right: left == right,
    "!=": lambda left, right: left != right,
}

_EXPRESSION = re.compile(
    r"^\s*(?P<op><=|>=|==|!=|<|>)\s*(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>b|kb|mb|gb|tb)?\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class SizeCondition:
    """A parsed size comparison."""

    op: str
    value_bytes: int
    raw: str

    def matches(self, size: int) -> bool:
        """Return True when *size* satisfies the comparison."""
        return _COMPARATORS[self.op](size, self.value_bytes)

    def __str__(self) -> str:
        return f"{self.op}{self.value_bytes}B"


def parse_size_expression(text: str) -> SizeCondition:
    """Parse ``<op><amount><unit>``, raising :class:`ValueError` on anything else.

    Deliberately strict: no bare numbers, no missing operator, no "MB" vs "MiB" guessing.
    A rule file with a typo must fail loudly at load time (iron rule 6).
    """
    if not isinstance(text, str):
        raise ValueError(f"size expression must be a string, got {type(text).__name__}")
    match = _EXPRESSION.match(text)
    if match is None:
        raise ValueError(
            f"invalid size expression {text!r}: expected '<op><number><unit>', "
            "e.g. '>=1MB', '<500KB', '==0B'",
        )
    unit = (match.group("unit") or "b").lower()
    try:
        amount = Decimal(match.group("number"))
    except InvalidOperation as exc:  # pragma: no cover - regex already guarantees digits
        raise ValueError(f"invalid number in size expression {text!r}") from exc
    value = int(amount * UNIT_MULTIPLIERS[unit])
    return SizeCondition(op=match.group("op"), value_bytes=value, raw=text)
