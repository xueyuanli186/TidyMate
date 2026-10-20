"""Path templates: whitelist validation, rendering, sanitising and truncation.

Iron rule 6 applies to every step here: whitelist the variables, reject everything else,
never guess. Rendering is separated from validation because the two have different failure
modes - validation rejects a *rule file*, rendering rejects a *single planned change* while
the rest of the plan is still previewable.

Sanitising rules (all mirrored in tests):

* Windows-illegal characters ``< > : " / \\ | ? *`` and control characters become ``_``
  (or are dropped for control characters);
* leading spaces and trailing dots/spaces are trimmed - Windows forbids a trailing
  dot or space but allows a leading one (".gitignore");
* a path segment longer than :data:`MAX_SEGMENT_LENGTH` keeps a stable 8-char hash suffix
  and the original extension, and records a note so the report can say it was truncated;
* an empty segment becomes ``untitled_<seq>`` and records a note.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, tzinfo
from pathlib import PureWindowsPath
from typing import Final

#: Variables a template may use. Case sensitive, exactly as written.
ALLOWED_VARIABLES: Final[frozenset[str]] = frozenset(
    {
        "year",
        "month",
        "day",
        "hour",
        "minute",
        "year_utc",
        "month_utc",
        "day_utc",
        "ext",
        "ext_nodot",
        "stem",
        "name",
        "parent",
        "size_bucket",
        "rule_id",
        "seq",
    },
)

#: Variables that must never be supported, because they leak machine state or invite
#: non-deterministic output. Listed explicitly so the error message can say *why*.
FORBIDDEN_VARIABLES: Final[frozenset[str]] = frozenset(
    {"path", "fullpath", "drive", "cwd", "userprofile", "home", "random"},
)

#: Forbidden by prefix (``{env:USERPROFILE}``, ``{hash8}``, ...).
FORBIDDEN_PREFIXES: Final[tuple[str, ...]] = ("env", "hash")

#: A single path segment may not exceed this many characters.
MAX_SEGMENT_LENGTH: Final = 60

#: Characters Windows forbids in a file name component (used when sanitising output).
ILLEGAL_NAME_CHARS: Final[frozenset[str]] = frozenset('<>:"/\\|?*')

#: Characters a template's literal text may not contain. ``/`` is excluded because it is
#: the segment separator; ``\\`` is rejected separately with its own message.
FORBIDDEN_TEMPLATE_CHARS: Final[frozenset[str]] = frozenset('<>:"|?*')

#: Full path limit beyond which even ``\\\\?\\`` cannot help.
MAX_EXTENDED_PATH: Final = 32767

_FIELD = re.compile(r"\{([^{}]*)\}")
_VARIABLE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")

_SIZE_BUCKETS: Final[tuple[tuple[int, str], ...]] = (
    (100 * 1024, "tiny"),
    (10 * 1024 * 1024, "small"),
    (1024**3, "medium"),
)


class TemplateError(ValueError):
    """The template cannot be used as written."""


@dataclass(frozen=True, slots=True)
class TemplateSpec:
    """A validated template, plus the variables it references (in order)."""

    raw: str
    variables: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TemplateContext:
    """Everything a template may read. Nothing else is reachable from a template."""

    mtime_utc: datetime
    local_tz: tzinfo
    ext: str
    stem: str
    name: str
    parent: str
    size: int
    rule_id: str
    seq: int

    def __post_init__(self) -> None:
        if self.mtime_utc.tzinfo is None:
            raise ValueError("mtime_utc must be timezone aware")


@dataclass(frozen=True, slots=True)
class RenderedTemplate:
    """Rendered path segments (already sanitised) plus optimisation notes."""

    segments: tuple[str, ...]
    notes: tuple[str, ...]


def _check_variable(name: str) -> None:
    if not name:
        raise TemplateError("template has an empty '{}' placeholder")
    if name in FORBIDDEN_VARIABLES:
        raise TemplateError(
            f"template variable {{{name}}} is explicitly forbidden "
            "(it would leak machine state or make output non-deterministic)",
        )
    if any(name.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
        raise TemplateError(
            f"template variable {{{name}}} is explicitly forbidden "
            f"(prefix '{next(p for p in FORBIDDEN_PREFIXES if name.startswith(p))}' is banned)",
        )
    if not _VARIABLE_NAME.match(name):
        raise TemplateError(f"invalid template variable name {{{name}}}")
    if name not in ALLOWED_VARIABLES:
        allowed = ", ".join(sorted(ALLOWED_VARIABLES))
        raise TemplateError(
            f"unknown template variable {{{name}}}; allowed variables: {allowed}",
        )


def _check_literal_part(part: str) -> None:
    if "\\" in part:
        raise TemplateError(
            "template must use '/' as the path separator; backslashes are rejected",
        )
    for char in part:
        if char in FORBIDDEN_TEMPLATE_CHARS:
            raise TemplateError(
                f"template contains {char!r}, which is not a legal Windows filename character",
            )
        if ord(char) < 32:
            raise TemplateError("template contains a control character")


def parse_template(text: str) -> TemplateSpec:
    """Validate a destination template and return its variables.

    Raises:
        TemplateError: with a message naming the offending variable or character.
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
        if segment == "":
            raise TemplateError(
                "template has an empty path segment (consecutive '//' separators)",
            )
        if segment in {".", ".."}:
            raise TemplateError(f"template has a '{segment}' segment in {stripped!r}")

    if stripped.count("{") != stripped.count("}"):
        raise TemplateError("template has unbalanced braces")

    variables: list[str] = []
    for match in _FIELD.finditer(stripped):
        name = match.group(1)
        _check_variable(name)
        variables.append(name)

    leftover = _FIELD.sub("", stripped)
    if "{" in leftover or "}" in leftover:
        raise TemplateError("template has an unrendered or malformed brace expression")
    _check_literal_part(leftover)

    return TemplateSpec(raw=stripped, variables=tuple(variables))


def _size_bucket(size: int) -> str:
    for limit, label in _SIZE_BUCKETS:
        if size < limit:
            return label
    return "large"


def _variable_values(context: TemplateContext) -> dict[str, str]:
    local = context.mtime_utc.astimezone(context.local_tz)
    utc = context.mtime_utc
    return {
        "year": f"{local.year:04d}",
        "month": f"{local.month:02d}",
        "day": f"{local.day:02d}",
        "hour": f"{local.hour:02d}",
        "minute": f"{local.minute:02d}",
        "year_utc": f"{utc.year:04d}",
        "month_utc": f"{utc.month:02d}",
        "day_utc": f"{utc.day:02d}",
        "ext": context.ext,
        "ext_nodot": context.ext[1:] if context.ext.startswith(".") else context.ext,
        "stem": context.stem,
        "name": context.name,
        "parent": context.parent,
        "size_bucket": _size_bucket(context.size),
        "rule_id": context.rule_id,
        "seq": f"{context.seq:06d}",
    }


def _truncate_segment(segment: str, notes: list[str]) -> str:
    """Shorten one segment to the limit, keeping the extension and a stable hash."""
    if len(segment) <= MAX_SEGMENT_LENGTH:
        return segment

    digest = hashlib.sha256(segment.encode("utf-8")).hexdigest()[:8]
    candidate = PureWindowsPath(segment)
    base_name, extension = candidate.stem, candidate.suffix
    if extension and len(extension) <= 10:
        base, suffix = base_name, extension
    else:
        base, suffix = segment, ""
    keep = MAX_SEGMENT_LENGTH - 1 - 8 - len(suffix)
    shortened = f"{base[: max(1, keep)]}-{digest}{suffix}"
    notes.append(
        f"segment truncated from {len(segment)} to {len(shortened)} chars "
        f"(hash {digest}): {segment[:32]}...",
    )
    return shortened


def sanitize_segment(segment: str, *, seq: int, notes: list[str]) -> str:
    """Make one rendered segment safe for a Windows file name."""
    cleaned_chars: list[str] = []
    replaced = False
    for char in segment:
        if ord(char) < 32:
            continue
        if char in ILLEGAL_NAME_CHARS:
            cleaned_chars.append("_")
            replaced = True
            continue
        cleaned_chars.append(char)
    if replaced:
        notes.append(f"illegal filename characters replaced in segment: {segment[:40]!r}")

    # Windows forbids a trailing dot/space, but a leading dot is legal (".gitignore"),
    cleaned = "".join(cleaned_chars).strip(" ").rstrip(" .")
    if not cleaned:
        fallback = f"untitled_{seq:06d}"
        notes.append(f"empty segment replaced with {fallback!r}")
        return fallback
    return _truncate_segment(cleaned, notes)


def render_template(text: str, context: TemplateContext) -> RenderedTemplate:
    """Render *text* against *context*, returning sanitised segments.

    Raises:
        TemplateError: when the template itself is invalid (not when a value is odd).
    """
    spec = parse_template(text)
    values = _variable_values(context)
    notes: list[str] = []

    rendered_segments: list[str] = []
    for raw_segment in spec.raw.split("/"):
        rendered = _FIELD.sub(lambda match: values[match.group(1)], raw_segment)
        rendered_segments.append(sanitize_segment(rendered, seq=context.seq, notes=notes))

    return RenderedTemplate(segments=tuple(rendered_segments), notes=tuple(notes))
