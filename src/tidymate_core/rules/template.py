"""Destination template validation (static only - rendering is a later stage).

Iron rule 6: whitelist the variables, reject everything else, never guess.

This module does the *checks*: variable names, brace balance, path shape and illegal
filename characters. It deliberately does not produce a path - rendering needs a file
entry, a clock and a conflict policy, and belongs to the planning stage.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

#: Variables a template may use. Anything else is a rule-file error.
ALLOWED_VARIABLES: Final[frozenset[str]] = frozenset(
    {
        "year",
        "month",
        "day",
        "hour",
        "minute",
        "second",
        "ext",
        "ext_nodot",
        "stem",
        "name",
        "size",
        "rule_id",
    },
)

#: Characters Windows forbids in a file name component.
ILLEGAL_NAME_CHARS: Final[frozenset[str]] = frozenset('<>:"|?*')

_FIELD = re.compile(r"\{([^{}]*)\}")
_VARIABLE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")


class TemplateError(ValueError):
    """The template cannot be used as written."""


@dataclass(frozen=True, slots=True)
class TemplateSpec:
    """A validated template, plus the variables it references (in order)."""

    raw: str
    variables: tuple[str, ...]


def _check_literal_part(part: str) -> None:
    if "\\" in part:
        raise TemplateError(
            "template must use '/' as the path separator; backslashes are rejected",
        )
    for char in part:
        if char in ILLEGAL_NAME_CHARS:
            raise TemplateError(
                f"template contains {char!r}, which is not a legal Windows filename character",
            )
        if ord(char) < 32:
            raise TemplateError("template contains a control character")


def parse_template(text: str) -> TemplateSpec:
    """Validate a destination template and return its variables.

    Rules enforced:

    * non-empty after stripping;
    * relative path only (no leading ``/``/``\\``, no drive letter);
    * ``/`` separators only, no ``..`` segment;
    * balanced braces, every ``{...}`` a whitelisted variable name;
    * literal text free of Windows-illegal filename characters.

    Raises:
        TemplateError: with a message explaining exactly what is wrong.
    """
    if not isinstance(text, str):
        raise TemplateError(f"template must be a string, got {type(text).__name__}")
    stripped = text.strip()
    if not stripped:
        raise TemplateError("template must not be empty")

    if stripped.startswith(("/", "\\")):
        raise TemplateError("template must be relative, but starts with a path separator")
    if _DRIVE_PREFIX.match(stripped):
        raise TemplateError("template must be relative, but looks like an absolute drive path")

    segments = stripped.split("/")
    for segment in segments:
        if segment in {"", ".", ".."}:
            raise TemplateError(
                f"template has an empty, '.' or '..' segment in {stripped!r}",
            )

    if stripped.count("{") != stripped.count("}"):
        raise TemplateError("template has unbalanced braces")

    variables: list[str] = []
    for match in _FIELD.finditer(stripped):
        name = match.group(1)
        if not name:
            raise TemplateError("template has an empty '{}' placeholder")
        if not _VARIABLE_NAME.match(name):
            raise TemplateError(f"invalid template variable name {name!r}")
        if name not in ALLOWED_VARIABLES:
            allowed = ", ".join(sorted(ALLOWED_VARIABLES))
            raise TemplateError(
                f"unknown template variable {name!r}; allowed variables: {allowed}",
            )
        variables.append(name)

    leftover = _FIELD.sub("", stripped)
    if "{" in leftover or "}" in leftover:
        raise TemplateError("template has an unrendered or malformed brace expression")
    _check_literal_part(leftover)

    return TemplateSpec(raw=stripped, variables=tuple(variables))
