"""Template validation (static only): whitelist, braces, path shape, illegal characters."""

from __future__ import annotations

import pytest

from tidymate_core.rules.template import (
    ALLOWED_VARIABLES,
    TemplateError,
    parse_template,
)


def test_example_template_is_valid() -> None:
    spec = parse_template("Sorted/{year}/{ext_nodot}/{stem}{ext}")
    assert spec.variables == ("year", "ext_nodot", "stem", "ext")


def test_variables_keep_source_order_and_duplicates() -> None:
    spec = parse_template("{year}/{year}/{stem}")
    assert spec.variables == ("year", "year", "stem")


def test_spaces_and_dashes_are_legal_in_literal_text() -> None:
    assert parse_template("My Files/{year}/Screenshot - {stem}{ext}").variables == (
        "year",
        "stem",
        "ext",
    )


def test_every_whitelisted_variable_is_accepted() -> None:
    for variable in ALLOWED_VARIABLES:
        assert parse_template("x/{" + variable + "}").variables == (variable,)


def test_unknown_variable_is_rejected() -> None:
    with pytest.raises(TemplateError, match="unknown template variable"):
        parse_template("Sorted/{bogus}")


def test_empty_placeholder_is_rejected() -> None:
    with pytest.raises(TemplateError, match="empty"):
        parse_template("Sorted/{}")


def test_uppercase_variable_is_rejected() -> None:
    with pytest.raises(TemplateError):
        parse_template("Sorted/{Year}")


def test_unbalanced_braces_are_rejected() -> None:
    with pytest.raises(TemplateError, match="unbalanced"):
        parse_template("Sorted/{year")


def test_nested_braces_are_rejected() -> None:
    with pytest.raises(TemplateError):
        parse_template("Sorted/{{year}}")


def test_empty_template_is_rejected() -> None:
    with pytest.raises(TemplateError, match="must not be empty"):
        parse_template("   ")


def test_absolute_template_is_rejected() -> None:
    with pytest.raises(TemplateError, match="relative"):
        parse_template("/Sorted/{year}")


def test_drive_qualified_template_is_rejected() -> None:
    with pytest.raises(TemplateError, match="relative"):
        parse_template("C:/Sorted/{year}")


def test_parent_segment_is_rejected() -> None:
    with pytest.raises(TemplateError, match="segment"):
        parse_template("Sorted/../../{year}")


def test_double_separator_is_rejected() -> None:
    with pytest.raises(TemplateError, match="segment"):
        parse_template("Sorted//{year}")


def test_backslash_separator_is_rejected() -> None:
    with pytest.raises(TemplateError, match="separator"):
        parse_template("Sorted\\{year}")


@pytest.mark.parametrize("char", list('<>:"|?*'))
def test_illegal_filename_character_is_rejected(char: str) -> None:
    with pytest.raises(TemplateError, match="legal Windows filename"):
        parse_template(f"Sorted/bad{char}name/{{year}}")


def test_control_character_is_rejected() -> None:
    with pytest.raises(TemplateError, match="control character"):
        parse_template("Sorted/bad\x01name/{year}")


def test_non_string_is_rejected() -> None:
    with pytest.raises(TemplateError, match="must be a string"):
        parse_template(42)  # type: ignore[arg-type]
