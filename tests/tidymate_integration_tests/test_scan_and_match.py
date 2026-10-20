"""End-to-end: scan a real tree, load a real rule file, match for real.

No file is moved. The test asserts the *decision*, which is all stages 1-2 promise.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from tidymate_core.rules import RuleLoadError, load_rules
from tidymate_core.scanning import ScanConfig, scan

RULES = """
rules:
  - id: downloads-images
    priority: 10
    when:
      path_glob: "**/Downloads/**"
      ext: [".jpg", ".jpeg", ".png"]
      size: ">=1KB"
    action:
      op: move
      template: "Sorted/{year}/{ext_nodot}/{stem}{ext}"
      conflict: rename
  - id: screenshots
    priority: 20
    when:
      name_regex: "(?i)^screenshot"
    action:
      op: move
      template: "Screenshots/{year}-{month}/{name}"
  - id: everything-else-pdf
    priority: 30
    when:
      ext: [".pdf"]
    action:
      op: copy
      template: "Archive/{stem}{ext}"
"""


def test_scan_and_match_end_to_end(tmp_path: Path) -> None:
    root = tmp_path / "root"
    downloads = root / "Downloads"
    documents = root / "Documents"
    downloads.mkdir(parents=True)
    documents.mkdir(parents=True)

    (downloads / "photo.JPG").write_bytes(b"x" * 2048)
    (downloads / "tiny.jpg").write_bytes(b"x" * 10)
    (downloads / "Screenshot 2024-05-01.png").write_bytes(b"y" * 4096)
    (documents / "report.pdf").write_bytes(b"z" * 5000)
    (documents / "notes.txt").write_text("hello", encoding="utf-8")

    rule_file = tmp_path / "rules.yaml"
    rule_file.write_text(textwrap.dedent(RULES), encoding="utf-8")

    result = scan(ScanConfig(roots=(str(root),)))
    ruleset = load_rules(rule_file)

    decisions = {entry.name: ruleset.match(entry) for entry in result.entries}

    photo = decisions["photo.JPG"]
    assert photo is not None
    assert photo.id == "downloads-images"

    screenshot = decisions["Screenshot 2024-05-01.png"]
    assert screenshot is not None
    assert screenshot.id == "downloads-images"  # priority 10 wins over 20

    report = decisions["report.pdf"]
    assert report is not None
    assert report.id == "everything-else-pdf"

    assert decisions["notes.txt"] is None
    assert decisions["tiny.jpg"] is None  # below the 1KB floor


def test_rule_file_parse_errors_stop_the_world(tmp_path: Path) -> None:
    broken = tmp_path / "broken.yaml"
    broken.write_text(
        textwrap.dedent(
            """
            rules:
              - id: a
                when: {ext: ["jpg"]}
                action: {op: move, template: "x/{stem}"}
            """,
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuleLoadError) as info:
        load_rules(broken)
    assert ".jpg" in str(info.value)
    assert "line" in str(info.value)
