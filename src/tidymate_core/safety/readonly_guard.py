"""Static guard: product code must not write to disk, with one reviewed exception.

Stages 1-2 were fully read-only. Stages 3-4 added a single, narrow write path - exporting
``plan.json`` and ``report.md`` - because a dry-run that cannot be exported is not
reviewable. That exception lives in exactly one module and is listed in
:data:`ALLOWED_MODULES`; everything else stays write-free, and the executor stage will add
its own reviewed entry when it lands.

The guard parses the AST rather than grepping text, which keeps ``str.replace`` and
``dict.update`` out of the results while still catching ``Path.write_text`` and
``shutil.move``. It scans product code only (``src/tidymate_core``): test fixtures and the
sandbox script legitimately create files.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

#: Product code that must stay write-free. Narrow on purpose.
DEFAULT_ROOTS: tuple[str, ...] = ("src/tidymate_core",)

#: Files allowed to write, keyed by path relative to ``src/``. Every entry is a reviewed
#: exception; adding one without an explanation in the PR is a rejection.
ALLOWED_MODULES: frozenset[str] = frozenset(
    {
        # stages 3-4: dry-run artifacts only, confined to the plan's output root
        "tidymate_core/planning/artifacts.py",
    },
)

_WRITE_MODE_CHARS = frozenset("wax+")

_PATH_METHODS = frozenset(
    {"write_text", "write_bytes", "unlink", "mkdir", "makedirs", "touch", "rmdir"},
)
_OS_FUNCTIONS = frozenset(
    {
        "remove",
        "unlink",
        "rename",
        "renames",
        "replace",
        "mkdir",
        "makedirs",
        "rmdir",
        "removedirs",
        "truncate",
    },
)
_SHUTIL_FUNCTIONS = frozenset({"copy", "copy2", "copyfile", "copytree", "move", "rmtree"})


@dataclass(frozen=True, slots=True)
class WriteCall:
    """One write-capable call found in product code."""

    path: str
    lineno: int
    api: str

    def render(self) -> str:
        """Return a single-line, CI-friendly description."""
        return f"{self.path}:{self.lineno}: {self.api}"


def _literal_mode(call: ast.Call) -> str | None:
    if len(call.args) >= 2:
        candidate = call.args[1]
        if isinstance(candidate, ast.Constant) and isinstance(candidate.value, str):
            return candidate.value
    for keyword in call.keywords:
        if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
            value = keyword.value.value
            if isinstance(value, str):
                return value
    return None


def _classify(call: ast.Call) -> str | None:
    """Return the write API name for *call*, or ``None`` when it only reads."""
    func = call.func
    if isinstance(func, ast.Name):
        if func.id == "open":
            mode = _literal_mode(call)
            if mode is not None and any(char in mode for char in _WRITE_MODE_CHARS):
                return f"open(mode={mode!r})"
            return None
        if func.id == "send2trash":
            return "send2trash(...)"
        return None

    if not isinstance(func, ast.Attribute):
        return None

    attribute = func.attr
    owner = func.value
    owner_name = owner.id if isinstance(owner, ast.Name) else ""

    if attribute == "send2trash":
        return f"{owner_name}.send2trash(...)" if owner_name else "send2trash(...)"
    if attribute in _PATH_METHODS:
        return f".{attribute}(...)"
    if owner_name == "os" and attribute in _OS_FUNCTIONS:
        return f"os.{attribute}(...)"
    if owner_name == "shutil" and attribute in _SHUTIL_FUNCTIONS:
        return f"shutil.{attribute}(...)"
    return None


def scan_source(path: Path, *, display_root: Path | None = None) -> list[WriteCall]:
    """Return every write-capable call inside one Python file."""
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    shown = str(path)
    if display_root is not None:
        try:
            shown = path.relative_to(display_root).as_posix()
        except ValueError:
            shown = str(path)

    calls: list[WriteCall] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            api = _classify(node)
            if api is not None:
                calls.append(WriteCall(path=shown, lineno=node.lineno, api=api))
    return calls


def scan_tree(root: Path) -> list[WriteCall]:
    """Scan every ``.py`` file under *root*."""
    if not root.exists():
        return []
    calls: list[WriteCall] = []
    for path in sorted(root.rglob("*.py")):
        if any(part in {"__pycache__", ".git", ".venv", "dist"} for part in path.parts):
            continue
        relative = path.relative_to(root.parent).as_posix() if root.parent else path.as_posix()
        if relative in ALLOWED_MODULES:
            continue
        calls.extend(scan_source(path, display_root=root.parent))
    return calls


def main(argv: list[str] | None = None, *, repo_root: Path | None = None) -> int:
    """CI entry point. Returns 0 when product code is read-only."""
    args = list(sys.argv[1:] if argv is None else argv)
    base = repo_root if repo_root is not None else Path.cwd()
    roots = [base / raw for raw in (args or list(DEFAULT_ROOTS))]

    calls: list[WriteCall] = []
    for root in roots:
        calls.extend(scan_tree(root))

    if calls:
        print("WRITE CALLS FOUND IN READ-ONLY PRODUCT CODE (iron rule 2):")  # noqa: T201
        for call in calls:
            print(f"  {call.render()}")  # noqa: T201
        print(  # noqa: T201
            "\nStages 1-2 must not create, modify or delete anything. "
            "If a later stage needs a write, add the module to ALLOWED_MODULES "
            "in that stage's reviewed PR.",
        )
        return 1
    scanned = sum(1 for root in roots for _ in root.rglob("*.py"))
    print(f"OK: no write calls in {scanned} product files.")  # noqa: T201
    return 0
