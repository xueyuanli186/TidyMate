"""Rules: model, strict YAML loading, matching.

Public surface:

* :func:`~tidymate_core.rules.loader.load_rules` / ``load_rules_from_text`` - all-or-nothing
  validation with YAML line numbers;
* :class:`~tidymate_core.rules.engine.RuleSet` - priority-ordered matching;
* :class:`~tidymate_core.rules.models.Rule` - one validated rule;
* :class:`~tidymate_core.rules.errors.RuleLoadError` - every problem at once.

Nothing in this package executes an action. ``op`` / ``template`` / ``conflict`` are
validated data for the planning stage; no file is moved, renamed, copied or deleted here.
"""

from __future__ import annotations

from tidymate_core.rules.engine import RuleSet
from tidymate_core.rules.errors import RuleError, RuleLoadError
from tidymate_core.rules.loader import load_rules, load_rules_from_text
from tidymate_core.rules.matcher import glob_to_regex, matches
from tidymate_core.rules.models import Action, ConflictPolicy, Rule, RuleOp, When
from tidymate_core.rules.regex_safe import (
    DEFAULT_TIMEOUT_MS,
    CatastrophicPatternError,
    RegexCompileError,
    SafeRegex,
)
from tidymate_core.rules.size_expr import SizeCondition, parse_size_expression
from tidymate_core.rules.template import (
    ALLOWED_VARIABLES,
    TemplateError,
    TemplateSpec,
    parse_template,
)
from tidymate_core.rules.time_expr import TimeCondition, parse_time_expression

__all__ = [
    "ALLOWED_VARIABLES",
    "DEFAULT_TIMEOUT_MS",
    "Action",
    "CatastrophicPatternError",
    "ConflictPolicy",
    "RegexCompileError",
    "Rule",
    "RuleError",
    "RuleLoadError",
    "RuleOp",
    "RuleSet",
    "SafeRegex",
    "SizeCondition",
    "TemplateError",
    "TemplateSpec",
    "TimeCondition",
    "When",
    "glob_to_regex",
    "load_rules",
    "load_rules_from_text",
    "matches",
    "parse_size_expression",
    "parse_template",
    "parse_time_expression",
]
