"""Rule set evaluation: priority ordering and first-match semantics.

Two behaviours are deliberate and tested:

* rules are evaluated in ascending ``priority`` (smaller number wins), with file order as
  the tie-breaker;
* ``first_match_only`` (default) stops at the first enabled match, so a file can never be
  claimed by two rules at once in a single pass.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime

from tidymate_core.rules.matcher import matches
from tidymate_core.rules.models import Rule
from tidymate_core.scanning.models import FileEntry, utc_now


@dataclass(slots=True)
class RuleSet:
    """A validated, priority-ordered collection of rules.

    ``warnings`` is shared with the compiled regexes: a regex that times out appends to it
    at match time. A timeout is not a crash and not a match; it must still be visible.
    """

    rules: tuple[Rule, ...]
    first_match_only: bool = True
    source: str = "<rules>"
    warnings: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.rules)

    def __iter__(self) -> Iterator[Rule]:
        return iter(self.rules)

    @property
    def enabled_rules(self) -> tuple[Rule, ...]:
        """Only the rules that may fire."""
        return tuple(rule for rule in self.rules if rule.enabled)

    def match(self, entry: FileEntry, *, now: datetime | None = None) -> Rule | None:
        """Return the first matching enabled rule, or ``None``."""
        moment = now if now is not None else utc_now()
        for rule in self.rules:
            if rule.enabled and matches(entry, rule.when, now=moment):
                return rule
        return None

    def match_all(
        self,
        entry: FileEntry,
        *,
        now: datetime | None = None,
    ) -> tuple[Rule, ...]:
        """Return every matching enabled rule in priority order.

        Ignores ``first_match_only`` on purpose: this is the "show me what else would have
        claimed this file" query used by reports and conflict diagnosis.
        """
        moment = now if now is not None else utc_now()
        return tuple(
            rule for rule in self.rules if rule.enabled and matches(entry, rule.when, now=moment)
        )
