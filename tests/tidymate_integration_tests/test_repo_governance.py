"""Repository governance contract tests.

These encode stage-0 acceptance criteria as executable checks: required files exist, every
YAML file parses, the CI workflow keeps its required shape, the issue forms keep the fields
we promised to ask for, and the PR template keeps the human-review gate for write logic.

They are intentionally schema-light: GitHub's full workflow schema is not validated here
(that would need a network call or a vendored schema), only the properties that matter to
this project's safety story.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

REQUIRED_PATHS = (
    "README.md",
    "pyproject.toml",
    ".editorconfig",
    ".gitignore",
    ".gitattributes",
    "src/tidymate_core/__init__.py",
    "src/tidymate_cli/main.py",
    "src/tidymate_app/main.py",
    "tests/tidymate_core_tests/test_smoke.py",
    "tests/tidymate_integration_tests/test_repo_governance.py",
    "scripts/make-sandbox.ps1",
    "scripts/make_dist.py",
    "scripts/version.py",
    "scripts/apply_labels.py",
    "scripts/check_forbidden_apis.py",
    "build/build_msi.py",
    "build/wix/README.md",
    ".github/workflows/ci.yml",
    ".github/workflows/release.yml",
    ".github/labels.yml",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/ISSUE_TEMPLATE/bug_report.yml",
    ".github/ISSUE_TEMPLATE/feature_request.yml",
    ".github/ISSUE_TEMPLATE/config.yml",
    "docs/SECURITY.md",
    "docs/ROADMAP.md",
    "docs/CONTRIBUTING.md",
    "docs/SPONSORS.md",
    "docs/validation/STAGE-0.md",
)

YAML_FILES = (
    ".github/workflows/ci.yml",
    ".github/workflows/release.yml",
    ".github/labels.yml",
    ".github/ISSUE_TEMPLATE/bug_report.yml",
    ".github/ISSUE_TEMPLATE/feature_request.yml",
    ".github/ISSUE_TEMPLATE/config.yml",
)

LABEL_NAMES = {
    "P0",
    "P1",
    "P2",
    "bug",
    "enhancement",
    "documentation",
    "good first issue",
    "help wanted",
    "security",
    "windows",
}

# GitHub issue-form item types.
FORM_ITEM_TYPES = {"markdown", "input", "textarea", "dropdown", "checkboxes"}


def _load_yaml(path: Path) -> Any:
    """Load with BaseLoader: keeps scalars as strings (YAML 1.1 `on:` stays a key)."""
    return yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)  # noqa: S506


@pytest.mark.parametrize("relative", REQUIRED_PATHS)
def test_required_file_exists(repo_root: Path, relative: str) -> None:
    path = repo_root / relative
    assert path.is_file(), f"missing {relative}"
    assert path.stat().st_size > 0, f"{relative} is empty"


@pytest.mark.parametrize("relative", YAML_FILES)
def test_yaml_parses(repo_root: Path, relative: str) -> None:
    assert _load_yaml(repo_root / relative) is not None


def test_ci_workflow_shape(repo_root: Path) -> None:
    ci = _load_yaml(repo_root / ".github/workflows/ci.yml")
    assert ci["name"] == "CI"

    triggers = ci["on"]
    assert triggers["push"]["branches"] == ["main"]
    assert "pull_request" in triggers

    jobs = ci["jobs"]
    assert {"lint", "test", "safety", "package"} <= set(jobs)
    assert jobs["test"]["runs-on"] == "windows-latest"
    assert jobs["package"]["needs"]  # must not run before lint/test/safety

    upload_steps = [
        step
        for step in jobs["package"]["steps"]
        if str(step.get("uses", "")).startswith("actions/upload-artifact")
    ]
    assert len(upload_steps) == 1
    with_block = upload_steps[0]["with"]
    assert with_block["name"] == "TidyMate-${{ steps.version.outputs.version }}-windows"
    assert with_block["retention-days"] == "14"
    assert "dist/TidyMate-*-windows.zip" in with_block["path"]


def test_ci_runs_the_forbidden_delete_scan(repo_root: Path) -> None:
    ci = _load_yaml(repo_root / ".github/workflows/ci.yml")
    commands = " ".join(str(step.get("run", "")) for step in ci["jobs"]["safety"]["steps"])
    assert "check_forbidden_apis.py" in commands
    assert "make-sandbox.ps1" in commands


def test_release_workflow_shape(repo_root: Path) -> None:
    release = _load_yaml(repo_root / ".github/workflows/release.yml")
    assert release["on"]["push"]["tags"] == ["v*"]
    assert release["permissions"]["contents"] == "write"
    build_steps = release["jobs"]["build"]["steps"]
    joined = " ".join(str(step.get("run", "")) for step in build_steps)
    assert "--assert-tag" in joined, "release must refuse a tag/version mismatch"


def test_labels_cover_the_required_set(repo_root: Path) -> None:
    labels = yaml.safe_load((repo_root / ".github/labels.yml").read_text(encoding="utf-8"))
    assert isinstance(labels, list)
    names = {str(entry["name"]) for entry in labels}
    assert names == LABEL_NAMES
    for entry in labels:
        assert len(str(entry["color"])) == 6
        assert entry["description"]


@pytest.mark.parametrize(
    "relative",
    [".github/ISSUE_TEMPLATE/bug_report.yml", ".github/ISSUE_TEMPLATE/feature_request.yml"],
)
def test_issue_form_items_are_well_formed(repo_root: Path, relative: str) -> None:
    form = yaml.safe_load((repo_root / relative).read_text(encoding="utf-8"))
    assert form["name"]
    assert form["description"]
    assert form["body"]
    for item in form["body"]:
        assert item["type"] in FORM_ITEM_TYPES, item
        if item["type"] != "markdown":
            assert item["id"], item


def test_bug_form_asks_the_required_questions(repo_root: Path) -> None:
    form = yaml.safe_load(
        (repo_root / ".github/ISSUE_TEMPLATE/bug_report.yml").read_text(encoding="utf-8"),
    )
    items = {item["id"]: item for item in form["body"] if item["type"] != "markdown"}
    required_fields = {
        "tidymate_version",
        "windows_version",
        "rules_file",
        "batch_id",
        "expected",
        "actual",
        "dry_run",
    }
    assert required_fields <= set(items)

    for field in required_fields:
        validations = items[field].get("validations") or {}
        assert validations.get("required") is True, f"{field} must be required"


def test_pr_template_forces_human_review_for_write_logic(repo_root: Path) -> None:
    template = (repo_root / ".github/PULL_REQUEST_TEMPLATE.md").read_text(encoding="utf-8")
    assert "是否触碰文件移动" in template
    assert "人工 review" in template
    # The self-check list must include the delete-API and dry-run items.
    for needle in ("永久删除", "--apply", "跳过（skip）"):
        assert needle in template


def test_gitignore_covers_runtime_and_build_output(repo_root: Path) -> None:
    text = (repo_root / ".gitignore").read_text(encoding="utf-8")
    for needle in ("*.db", "bin/", "obj/", "sandbox", "dist/", "__pycache__"):
        assert needle.lower() in text.lower(), f".gitignore must cover {needle}"


def test_editorconfig_declares_strict_mode_mapping(repo_root: Path) -> None:
    text = (repo_root / ".editorconfig").read_text(encoding="utf-8")
    assert "TreatWarningsAsErrors" in text
    assert "mypy" in text


def test_powershell_scripts_are_51_safe(repo_root: Path) -> None:
    """A BOM-less .ps1 with non-ASCII text is mis-decoded by Windows PowerShell 5.1.

    That is not hypothetical: it silently shifted the parser and broke the whole script
    during stage 0. Either keep the file ASCII-only or give it a UTF-8 BOM.
    """
    for path in sorted((repo_root / "scripts").glob("*.ps1")):
        raw = path.read_bytes()
        if any(byte >= 0x80 for byte in raw):
            assert raw.startswith(b"\xef\xbb\xbf"), (
                f"{path.name} contains non-ASCII text but has no UTF-8 BOM; "
                "Windows PowerShell 5.1 will mis-decode it"
            )
