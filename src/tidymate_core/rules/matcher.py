"""Condition evaluation.

``path_glob`` is translated to a regular expression instead of using :mod:`fnmatch`,
because the two behave differently in ways that matter here:

* in ``fnmatch``, ``*`` crosses directory separators; in a rule, ``*.txt`` should not match
  ``sub/dir/a.txt``;
* ``**`` must mean "any depth", otherwise ``**/Downloads/**`` is impossible to express.

The translated pattern is matched case-insensitively, because NTFS is.
"""

from __future__ import annotations

import re
from datetime import datetime

from tidymate_core.rules.models import When
from tidymate_core.scanning.models import FileEntry

_WINDOWS_SEPARATOR = "\\"


def glob_to_regex(pattern: str) -> str:
    """Translate a Windows-style glob into a regular expression source.

    * ``**`` -> any characters, including separators;
    * ``*``  -> any characters except a separator;
    * ``?``  -> exactly one character except a separator;
    * ``/``  is accepted as a separator alias for ``\\``.

    A ``**`` followed by a separator also matches zero directories, so ``**/Downloads/**``
    matches ``C:\\Downloads\\a.txt`` as well as ``C:\\Users\\me\\Downloads\\a.txt``.
    """
    normalized = pattern.replace("/", _WINDOWS_SEPARATOR)
    out: list[str] = []
    index = 0
    length = len(normalized)
    while index < length:
        char = normalized[index]
        if char == "*":
            if index + 1 < length and normalized[index + 1] == "*":
                out.append(".*")
                index += 2
                if index < length and normalized[index] == _WINDOWS_SEPARATOR:
                    # "**\" also matches zero directory levels
                    out.append("\\\\?")
                    index += 1
                continue
            out.append(r"[^\\]*")
            index += 1
            continue
        if char == "?":
            out.append(r"[^\\]")
            index += 1
            continue
        out.append(re.escape(char))
        index += 1
    # Anchored on purpose: path_glob matches the whole absolute path, so "*.txt" does not
    # accidentally match "C:\data\a.txt" through a substring search. Use "**/*.txt" for
    # "any depth", which is also what the rule examples teach.
    return "^(?:" + "".join(out) + ")$"


def matches(entry: FileEntry, when: When, *, now: datetime | None = None) -> bool:
    """Return True when *entry* satisfies **all** conditions in *when*."""
    if when.path_glob_regex is not None and not when.path_glob_regex.search(
        entry.normalized_path,
    ):
        return False
    if when.path_regex is not None and not when.path_regex.search(entry.normalized_path):
        return False
    if when.extensions and entry.ext not in when.extensions:
        return False
    if when.size is not None and not when.size.matches(entry.size):
        return False
    if when.mtime is not None and not when.mtime.matches(entry.mtime_utc, now=now):
        return False
    return when.name_regex is None or bool(when.name_regex.search(entry.name))
