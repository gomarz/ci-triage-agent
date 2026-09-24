"""Classification, against root sentences taken from the cached corpus."""

from __future__ import annotations

import pytest

from ci_triage.classify import NO_ROOT, UNMATCHED, classify, classify_root
from ci_triage.jobs import parse_job
from ci_triage.models import FailureCategory

ENV = FailureCategory.ENVIRONMENT
INFRA = FailureCategory.INFRASTRUCTURE
REGRESSION = FailureCategory.REGRESSION
UNTRIAGED = FailureCategory.UNTRIAGED


@pytest.mark.parametrize(
    ("root", "category", "rule"),
    [
        # The largest root in the corpus: 57,155 failures.
        (
            "FileNotFoundError: [Errno 2] No such file or directory: '<PATH>/<ARTIFACT>'",
            INFRA,
            "missing-artifact",
        ),
        ("Source file '<PATH>/<ARTIFACT>' does not exist.", INFRA, "missing-artifact"),
        ("File '<PATH>/screenshot_1.jpg' does not exist.", INFRA, "missing-artifact"),
        (
            "'<PATH>/signal-tests.txt' was not created in <DURATION>.",
            INFRA,
            "file-not-created-in-time",
        ),
        ("ModuleNotFoundError: No module named 'typing_extensions'", ENV, "missing-module"),
        (
            "robot.errors.DataError: Markdown format requires 'markdown' module to be installed.",
            ENV,
            "missing-module",
        ),
        (
            "Using YAML variable files requires PyYAML module to be installed.",
            ENV,
            "missing-module",
        ),
        (
            "ImportError: cannot import name 'TypeAliasType' from 'typing' (<PATH>/typing.py)",
            ENV,
            "stdlib-name-missing",
        ),
        ("AssertionError: DataError not raised", REGRESSION, "assertion"),
        ("1 != 252", REGRESSION, "mismatch"),
        ("Lists are different:", REGRESSION, "mismatch"),
        ("Lengths are different: 0 != 1", REGRESSION, "mismatch"),
        ("Attribute 'source' exists and has value '<PATH>/Telnet.py'.", REGRESSION, "mismatch"),
        (
            "'<p>Module test library.</p>' does not contain '<a href=\"#Keyword\" title=\"",
            REGRESSION,
            "mismatch",
        ),
    ],
)
def test_rules(root, category, rule):
    result = classify_root(root)

    assert result.category == category
    assert result.rule == rule


@pytest.mark.parametrize(
    "root",
    [
        # Robot's wording for "captured stderr should be empty". The stderr held
        # a SyntaxError from an interpreter too old for the code: environment,
        # not a regression, and not something "should be" can tell apart.
        "SyntaxError: invalid syntax' should be empty.",
        # Robot's wrapper sentence. Says a test failed, not why.
        "Status of 'Resource with '*.rst' extension' should have been PASS but it was FAIL.",
        # The process under test printed nothing: the run is suspect, not the check.
        "'' does not contain 'Output: NONE",
        # Could be a code error or an old interpreter; the root cannot say which.
        "SyntaxError: invalid syntax",
        # Wrapper text with nothing beneath it.
        "Running tests failed.",
        "NameError: name 'BlockProcessor' is not defined",
    ],
)
def test_ambiguous_roots_stay_untriaged(root):
    result = classify_root(root)

    assert result.category == UNTRIAGED
    assert result.rule == UNMATCHED


def test_empty_root_is_untriaged_with_its_own_rule():
    assert classify_root("") == classify_root("   ")
    assert classify_root("").rule == NO_ROOT
    assert classify_root("").category == UNTRIAGED


def test_missing_module_beats_comparison_wording():
    """A message can be both. The module is the cause."""
    root = "Markdown format requires 'markdown' module to be installed. != expected"

    assert classify_root(root).rule == "missing-module"


@pytest.mark.parametrize(
    ("fixture", "category", "rule"),
    [
        ("crash_cascade.txt", ENV, "missing-module"),
        ("crash_typealias_linux.txt", ENV, "stdlib-name-missing"),
        ("unittest_three_errors.txt", ENV, "missing-module"),
        ("unittest_fail.txt", REGRESSION, "assertion"),
        # The project's own module lacks a name: could be code or environment.
        ("crash_import_error.txt", UNTRIAGED, UNMATCHED),
    ],
)
def test_classify_failures_from_real_logs(log, fixture, category, rule):
    failure = parse_job(log(fixture)).failures[0]

    result = classify(failure)

    assert (result.category, result.rule) == (category, rule)
