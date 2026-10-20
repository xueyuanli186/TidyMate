"""Rule loading: all-or-nothing validation with line numbers.

Every rejection case here exists because "skip the bad rule and carry on" is forbidden.
If a rule file has one typo, the whole file must fail and say where.
"""

from __future__ import annotations

import textwrap

import pytest

from tidymate_core.rules.errors import RuleError, RuleLoadError
from tidymate_core.rules.loader import load_rules_from_text
from tidymate_core.rules.models import ConflictPolicy, RuleOp

MINIMAL = """
rules:
  - id: images
    when:
      ext: [".jpg"]
    action:
      op: move
      template: "Sorted/{ext_nodot}/{stem}{ext}"
"""


def errors_of(text: str) -> list[RuleError]:
    with pytest.raises(RuleLoadError) as info:
        load_rules_from_text(textwrap.dedent(text))
    return list(info.value.errors)


def test_minimal_rule_loads() -> None:
    ruleset = load_rules_from_text(textwrap.dedent(MINIMAL))
    assert len(ruleset) == 1
    rule = ruleset.rules[0]
    assert rule.id == "images"
    assert rule.enabled is True
    assert rule.priority == 0
    assert rule.action.op is RuleOp.MOVE
    assert rule.action.conflict is ConflictPolicy.SKIP


def test_full_example_loads() -> None:
    text = """
    rules:
      - id: images-by-year
        enabled: true
        priority: 10
        when:
          path_glob: "**/Downloads/**"
          path_regex: "(?i)download"
          ext: [".jpg", ".jpeg", ".png", ".heic"]
          size: ">=1MB"
          mtime: ">=2024-01-01"
          name_regex: "^IMG_\\\\d{4}"
        action:
          op: move
          template: "Sorted/{year}/{ext_nodot}/{stem}{ext}"
          conflict: rename
    """
    ruleset = load_rules_from_text(textwrap.dedent(text))
    rule = ruleset.rules[0]
    assert rule.priority == 10
    assert rule.when.size is not None
    assert rule.when.size.value_bytes == 1024 * 1024
    assert rule.when.extensions == frozenset({".jpg", ".jpeg", ".png", ".heic"})
    assert rule.action.conflict is ConflictPolicy.RENAME


def test_empty_rules_list_is_allowed() -> None:
    assert len(load_rules_from_text("rules: []")) == 0


def test_missing_id_is_rejected() -> None:
    errors = errors_of(
        """
        rules:
          - when: {ext: [".jpg"]}
            action: {op: move, template: "x/{stem}"}
        """,
    )
    assert any("id" in error.field for error in errors)


def test_missing_when_is_rejected() -> None:
    errors = errors_of(
        """
        rules:
          - id: a
            action: {op: move, template: "x/{stem}"}
        """,
    )
    assert any(error.field.endswith(".when") for error in errors)


def test_missing_action_is_rejected() -> None:
    errors = errors_of(
        """
        rules:
          - id: a
            when: {ext: [".jpg"]}
        """,
    )
    assert any(error.field.endswith(".action") for error in errors)


def test_empty_when_is_rejected() -> None:
    errors = errors_of(
        """
        rules:
          - id: a
            when: {}
            action: {op: move, template: "x/{stem}"}
        """,
    )
    assert any("at least one condition" in error.message for error in errors)


def test_wrong_priority_type_is_rejected() -> None:
    errors = errors_of(
        """
        rules:
          - id: a
            priority: high
            when: {ext: [".jpg"]}
            action: {op: move, template: "x/{stem}"}
        """,
    )
    assert any("priority must be an integer" in error.message for error in errors)


def test_boolean_priority_is_rejected() -> None:
    errors = errors_of(
        """
        rules:
          - id: a
            priority: true
            when: {ext: [".jpg"]}
            action: {op: move, template: "x/{stem}"}
        """,
    )
    assert any("priority must be an integer" in error.message for error in errors)


def test_wrong_enabled_type_is_rejected() -> None:
    errors = errors_of(
        """
        rules:
          - id: a
            enabled: "yes"
            when: {ext: [".jpg"]}
            action: {op: move, template: "x/{stem}"}
        """,
    )
    assert any("enabled must be true or false" in error.message for error in errors)


def test_ext_as_string_is_rejected() -> None:
    errors = errors_of(
        """
        rules:
          - id: a
            when: {ext: ".jpg"}
            action: {op: move, template: "x/{stem}"}
        """,
    )
    assert any("ext must be a non-empty list" in error.message for error in errors)


def test_ext_without_dot_is_rejected() -> None:
    errors = errors_of(
        """
        rules:
          - id: a
            when: {ext: ["jpg"]}
            action: {op: move, template: "x/{stem}"}
        """,
    )
    assert any("must start with '.'" in error.message for error in errors)


def test_duplicate_rule_id_is_rejected() -> None:
    errors = errors_of(
        """
        rules:
          - id: same
            when: {ext: [".jpg"]}
            action: {op: move, template: "a/{stem}"}
          - id: same
            when: {ext: [".png"]}
            action: {op: move, template: "b/{stem}"}
        """,
    )
    assert any("duplicate rule id" in error.message for error in errors)


def test_uncompilable_regex_is_rejected() -> None:
    errors = errors_of(
        """
        rules:
          - id: a
            when: {name_regex: "("}
            action: {op: move, template: "x/{stem}"}
        """,
    )
    assert any("invalid regular expression" in error.message for error in errors)


def test_catastrophic_regex_is_rejected() -> None:
    errors = errors_of(
        """
        rules:
          - id: a
            when: {name_regex: "(a+)+"}
            action: {op: move, template: "x/{stem}"}
        """,
    )
    assert any("nested quantifiers" in error.message for error in errors)


def test_invalid_size_expression_is_rejected() -> None:
    errors = errors_of(
        """
        rules:
          - id: a
            when:
              ext: [".jpg"]
              size: ">=1XB"
            action: {op: move, template: "x/{stem}"}
        """,
    )
    assert any("invalid size expression" in error.message for error in errors)


def test_size_error_points_at_the_size_line() -> None:
    text = """rules:
  - id: a
    when:
      ext: [".jpg"]
      size: ">=1XB"
    action: {op: move, template: "x/{stem}"}
"""
    with pytest.raises(RuleLoadError) as info:
        load_rules_from_text(text)
    size_errors = [error for error in info.value.errors if error.field.endswith(".size")]
    assert size_errors
    assert size_errors[0].line == 5, size_errors[0].render()


def test_invalid_time_expression_is_rejected() -> None:
    errors = errors_of(
        """
        rules:
          - id: a
            when:
              ext: [".jpg"]
              mtime: "yesterday"
            action: {op: move, template: "x/{stem}"}
        """,
    )
    assert any("invalid time expression" in error.message for error in errors)


def test_invalid_op_is_rejected() -> None:
    errors = errors_of(
        """
        rules:
          - id: a
            when: {ext: [".jpg"]}
            action: {op: explode, template: "x/{stem}"}
        """,
    )
    assert any("not one of move/rename/copy/trash" in error.message for error in errors)


def test_invalid_conflict_is_rejected() -> None:
    errors = errors_of(
        """
        rules:
          - id: a
            when: {ext: [".jpg"]}
            action: {op: move, template: "x/{stem}", conflict: overwrite}
        """,
    )
    assert any("not one of skip/rename/ask" in error.message for error in errors)


def test_empty_template_is_rejected() -> None:
    errors = errors_of(
        """
        rules:
          - id: a
            when: {ext: [".jpg"]}
            action: {op: move, template: "   "}
        """,
    )
    assert any("template is required" in error.message for error in errors)


def test_template_with_unknown_variable_is_rejected() -> None:
    errors = errors_of(
        """
        rules:
          - id: a
            when: {ext: [".jpg"]}
            action: {op: move, template: "x/{bogus}"}
        """,
    )
    assert any("unknown template variable" in error.message for error in errors)


def test_trash_does_not_require_a_template() -> None:
    ruleset = load_rules_from_text(
        textwrap.dedent(
            """
            rules:
              - id: junk
                when: {ext: [".tmp"]}
                action: {op: trash}
            """,
        ),
    )
    assert ruleset.rules[0].action.op is RuleOp.TRASH
    assert ruleset.rules[0].action.template == ""


def test_unknown_rule_key_is_rejected() -> None:
    errors = errors_of(
        """
        rules:
          - id: a
            prioirty: 5
            when: {ext: [".jpg"]}
            action: {op: move, template: "x/{stem}"}
        """,
    )
    assert any("unknown rule key" in error.message for error in errors)


def test_unknown_when_key_is_rejected() -> None:
    errors = errors_of(
        """
        rules:
          - id: a
            when:
              ext: [".jpg"]
              sizee: ">=1MB"
            action: {op: move, template: "x/{stem}"}
        """,
    )
    assert any("unknown condition" in error.message for error in errors)


def test_unknown_action_key_is_rejected() -> None:
    errors = errors_of(
        """
        rules:
          - id: a
            when: {ext: [".jpg"]}
            action: {op: move, template: "x/{stem}", dest: "y"}
        """,
    )
    assert any("unknown action key" in error.message for error in errors)


def test_unknown_top_level_key_is_rejected() -> None:
    errors = errors_of(
        """
        rules: []
        rulez: []
        """,
    )
    assert any("unknown top-level key" in error.message for error in errors)


def test_duplicate_yaml_key_is_rejected() -> None:
    errors = errors_of(
        """
        rules:
          - id: a
            when:
              ext: [".jpg"]
              ext: [".png"]
            action: {op: move, template: "x/{stem}"}
        """,
    )
    assert any("duplicate key" in error.message for error in errors)


def test_top_level_must_be_a_mapping() -> None:
    errors = errors_of(
        """
        - id: a
        """,
    )
    assert any("top level must be a mapping" in error.message for error in errors)


def test_rules_must_be_a_list() -> None:
    errors = errors_of("rules: nope")
    assert any("'rules' must be a list" in error.message for error in errors)


def test_first_match_only_defaults_to_true() -> None:
    assert load_rules_from_text("rules: []").first_match_only is True


def test_first_match_only_can_be_disabled() -> None:
    assert load_rules_from_text("first_match_only: false\nrules: []").first_match_only is False


def test_camel_case_alias_is_accepted() -> None:
    assert load_rules_from_text("firstMatchOnly: false\nrules: []").first_match_only is False


def test_both_first_match_spellings_is_an_error() -> None:
    errors = errors_of("first_match_only: true\nfirstMatchOnly: true\nrules: []")
    assert any("only one of" in error.message for error in errors)


def test_rules_are_sorted_by_priority() -> None:
    ruleset = load_rules_from_text(
        textwrap.dedent(
            """
            rules:
              - id: late
                priority: 30
                when: {ext: [".c"]}
                action: {op: move, template: "a/{stem}"}
              - id: early
                priority: 10
                when: {ext: [".a"]}
                action: {op: move, template: "b/{stem}"}
              - id: middle
                priority: 20
                when: {ext: [".b"]}
                action: {op: move, template: "c/{stem}"}
            """,
        ),
    )
    assert [rule.id for rule in ruleset.rules] == ["early", "middle", "late"]


def test_equal_priority_keeps_file_order() -> None:
    ruleset = load_rules_from_text(
        textwrap.dedent(
            """
            rules:
              - id: first
                priority: 5
                when: {ext: [".a"]}
                action: {op: move, template: "a/{stem}"}
              - id: second
                priority: 5
                when: {ext: [".b"]}
                action: {op: move, template: "b/{stem}"}
            """,
        ),
    )
    assert [rule.id for rule in ruleset.rules] == ["first", "second"]


def test_disabled_rule_is_kept_but_not_enabled() -> None:
    ruleset = load_rules_from_text(
        textwrap.dedent(
            """
            rules:
              - id: off
                enabled: false
                when: {ext: [".jpg"]}
                action: {op: move, template: "a/{stem}"}
            """,
        ),
    )
    assert len(ruleset) == 1
    assert ruleset.enabled_rules == ()


def test_error_report_includes_source_name() -> None:
    with pytest.raises(RuleLoadError) as info:
        load_rules_from_text("rules: nope", source="my-rules.yaml")
    assert "my-rules.yaml" in str(info.value)
    assert "nothing was loaded" in str(info.value)


def test_all_errors_are_collected_at_once() -> None:
    errors = errors_of(
        """
        rules:
          - id: a
            priority: high
            when: {ext: ["jpg"]}
            action: {op: explode, template: ""}
        """,
    )
    assert len(errors) >= 3


def test_yaml_1_1_boolean_words_stay_strings() -> None:
    # `off`/`on`/`yes`/`no` are booleans in YAML 1.1. Treating them as such would turn
    # `id: off` into False and produce a nonsense error message for a valid id.
    ruleset = load_rules_from_text(
        textwrap.dedent(
            """
            rules:
              - id: off
                when: {ext: [".jpg"]}
                action: {op: move, template: "x/{stem}"}
            """,
        ),
    )
    assert ruleset.rules[0].id == "off"


def test_enabled_rejects_yaml_1_1_spellings() -> None:
    errors = errors_of(
        """
        rules:
          - id: a
            enabled: no
            when: {ext: [".jpg"]}
            action: {op: move, template: "x/{stem}"}
        """,
    )
    assert any("enabled must be true or false" in error.message for error in errors)
