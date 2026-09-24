"""Tests built from real robotframework/robotframework failure output.

The fixtures are trimmed from actual cached logs rather than invented, so
the separator widths, path shapes, and message formats are the ones the
parser will meet in production.
"""

from __future__ import annotations

import pytest

from ci_triage.extract import extract_failures, parse_tally
from ci_triage.roots import (
    UNCLASSIFIED,
    root_cause,
    root_cause_text,
    root_rule,
    root_signature,
)

RULE = "-" * 100
END = "=" * 100

_YAML = "Using YAML variable files requires PyYAML module to be installed."

_WIN_YAML_FAIL = (
    r"Processing variable file 'D:\a\robotframework\atest\variables\valid2.yaml'"
    f" failed: {_YAML}"
)
_NIX_YAML_FAIL = (
    f"Processing variable file '/home/runner/work/robotframework/atest/valid2.yaml' failed: {_YAML}"
)

CASCADE_WINDOWS = f"""FAIL: Robot.Variables.Yaml Variable File.Import Variables keyword
Status of 'Import Variables keyword' should have been PASS but it was FAIL.

Error message:
Setup failed:
{_WIN_YAML_FAIL}
{RULE}
{END}
Run suite 'Robot' with 7041 tests in 12 minutes 4 seconds 253 milliseconds.

FAILED
7041 tests, 6469 passed, 572 failed
"""

CASCADE_LINUX = f"""FAIL: Robot.Variables.Yaml Variable File.Import Variables keyword
Status of 'Import Variables keyword' should have been PASS but it was FAIL.

Error message:
Setup failed:
{_NIX_YAML_FAIL}
{RULE}
"""

NESTED_UNITTEST = f"""FAIL: Robot.External.Unit Tests.Unit Tests
Unit tests failed with RC 1:
{"=" * 70}
ERROR: test_show_completion_exits_cleanly (test_confargsparser.TestConfargsParser)
{"-" * 70}
Traceback (most recent call last):
  File "/home/runner/work/rf/utest/test_confargsparser.py", line 138, in test_sc
    raise CliUsageError("unknown option")
confargs.exceptions.CliUsageError: unknown option '--show-completion'
{"-" * 70}
Ran 2434 tests in 13.339s

FAILED (errors=1)
{END}
Run suite 'Robot' with 7108 tests in 12 minutes 42 seconds 258 milliseconds.

FAILED
7108 tests, 7107 passed, 1 failed
"""

# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------


def test_extracts_one_failure_per_block():
    assert len(extract_failures(CASCADE_WINDOWS)) == 1


def test_same_cause_matches_across_platforms():
    """Absolute paths differ by runner OS; the cause must not."""
    windows = extract_failures(CASCADE_WINDOWS)[0]
    linux = extract_failures(CASCADE_LINUX)[0]
    assert windows.cause_sig == linux.cause_sig


def test_nested_unittest_rules_do_not_split_the_block():
    """unittest rules are 70 chars, Robot's are 100. Only Robot's may split."""
    failures = extract_failures(NESTED_UNITTEST)
    assert len(failures) == 1
    assert "Traceback" in failures[0].message
    assert "CliUsageError" in failures[0].message


def test_summary_is_not_part_of_the_message():
    failure = extract_failures(CASCADE_WINDOWS)[0]
    assert "Run suite" not in failure.message
    assert "6469 passed" not in failure.message


def test_tally_parsed():
    tally = parse_tally(CASCADE_WINDOWS)
    assert (tally.total, tally.passed, tally.failed) == (7041, 6469, 572)


def test_no_tally_returns_none():
    assert parse_tally("nothing here") is None


def test_tally_takes_the_last_summary():
    """A job printing unit-test then acceptance summaries reports the latter."""
    text = "10 tests, 10 passed, 0 failed\nlater\n7108 tests, 7107 passed, 1 failed"
    assert parse_tally(text).failed == 1


# --------------------------------------------------------------------------
# Root causes
# --------------------------------------------------------------------------


def test_root_merges_setup_failure_and_log_mismatch():
    """One missing dependency surfaces two ways; the root must be one."""
    setup = f"Setup failed:\n{_NIX_YAML_FAIL}"
    mismatch = (
        f"Wrong log message: '{_NIX_YAML_FAIL}'"
        " does not match 'Error in file 'x.robot' on line 5: something else'"
    )
    assert root_signature(setup) == root_signature(mismatch)


def test_root_merges_across_platforms():
    assert root_signature(f"Setup failed:\n{_WIN_YAML_FAIL}") == root_signature(
        f"Setup failed:\n{_NIX_YAML_FAIL}"
    )


@pytest.mark.parametrize(
    "wrapper",
    [
        "Setup failed:",
        "Teardown failed:",
        "Suite setup failed:",
        "Suite teardown failed:",
        "Parent suite setup failed:",
        "Parent suite teardown failed:",
    ],
)
def test_every_setup_teardown_wrapper_is_peeled(wrapper):
    """Robot capitalises only the first word, so these are all different strings.

    The real cause is on the line beneath the wrapper.
    """
    missing = "Source file '/tmp/robotatest/Python-3.10.21-Linux/output/output.xml' does not exist."
    message = f"{wrapper}\n{missing}"

    root, rule = root_cause(message)

    assert root == "Source file '<PATH>/<ARTIFACT>' does not exist."
    assert rule == "first-line"


def test_root_merges_variable_names():
    a = "Several failures occurred:\n\n1) Variable '${YAML FILE FROM CLI}' not found."
    b = "Several failures occurred:\n\n1) Variable '${OTHER THING}' not found."
    assert root_signature(a) == root_signature(b)


def test_root_prefers_last_exception_in_traceback():
    message = (
        "Unit tests failed with RC 1:\n"
        "  File '/x/y.py', line 138, in test_x\n"
        "confargs.exceptions.CliUsageError: unknown option '--show-completion'\n"
        "robot.errors.DataError: unknown option '--show-completion'"
    )
    assert root_cause_text(message).startswith("robot.errors.DataError:")


def test_root_keeps_distinct_causes_apart():
    other = "Several failures occurred:\n\n1) Variable '${X}' not found."
    assert root_signature(f"Setup failed:\n{_NIX_YAML_FAIL}") != root_signature(other)


def test_root_uses_diff_payload_not_prose():
    message = (
        "Multiline strings are different:\n--- first\n+++ second\n@@ -1,3 +1,3 @@\n"
        "-[ ERROR ] invalid value 'InVaLid'\n+[ ERROR ] Invalid console marker."
    )
    root = root_cause_text(message)
    assert "different" not in root
    assert "InVaLid" in root


def test_missing_files_do_not_collapse_into_one_root():
    """Full path scrubbing made every FileNotFoundError identical."""
    prefix = "FileNotFoundError: [Errno 2] No such file or directory:"
    artifact = f"{prefix} '/home/runner/a/results/out.dat'"
    testdata = f"{prefix} '/home/runner/a/missing.robot'"
    assert root_signature(artifact) != root_signature(testdata)


def test_same_file_still_merges_across_platforms():
    prefix = "FileNotFoundError: [Errno 2] No such file or directory:"
    win = rf"{prefix} 'D:\a\rf\x\missing.robot'"
    nix = f"{prefix} '/home/runner/rf/y/missing.robot'"
    assert root_signature(win) == root_signature(nix)


def test_meaningless_fallbacks_become_unclassified():
    """A glob or a stray fragment is not a root cause."""
    for junk in ("*", "'# Telnet", "   ", "..."):
        assert root_rule(junk) == UNCLASSIFIED
    assert root_signature("*") == root_signature("'# Telnet")


def test_rules_are_reported():
    reason = "Setup failed:\nProcessing x failed: PyYAML missing."
    assert root_rule(reason) == "failed-reason"
    assert root_rule("Traceback\nValueError: something broke here") == "exception"


def test_glob_from_expected_side_is_not_a_root():
    """Robot globs reach the reason rule from the expected half of a
    comparison; a meaningless capture must not be labelled confidently."""
    message = "Wrong log message: 'x' does not match 'Processing file 'y' failed: *'"
    assert root_cause_text(message) != "*"
    assert root_rule(message) != "failed-reason"


def test_rules_fall_through_to_a_meaningful_one():
    """A junk capture by an earlier rule must not block a later real one."""
    message = "Processing failed: *\nValueError: the actual problem"
    assert root_rule(message) == "exception"
    assert "actual problem" in root_cause_text(message)


def test_quoted_payloads_are_not_roots():
    """Content being compared is not a description of what went wrong."""
    for payload in ("'<p>Some HTML fragment here</p>'", "'# Telnet heading text"):
        assert root_rule(payload) == UNCLASSIFIED


def test_plain_fallback_sentences_still_count():
    assert root_rule("No keyword with name 'Integers' found.") == "first-line"


def test_payload_continuation_lines_are_not_roots():
    """Skipping only the opening quoted line hands back line two of the same
    payload, which is just as meaningless."""
    message = (
        "'<p>The first examples use fenced code blocks</p>\n"
        "plugin. Actual syntax highlighting is provided by the codehilite plugin"
    )
    assert root_rule(message) == UNCLASSIFIED


def test_bullet_payloads_are_not_roots():
    assert root_rule("* Version: 7.5b2.dev1\n* Another line") == UNCLASSIFIED


def test_numeric_assertions_are_roots():
    assert root_rule("1 != 252") != UNCLASSIFIED


def test_quoted_values_with_a_verb_are_roots():
    assert root_rule("'/a/b.html' was not created in 10 seconds.") != UNCLASSIFIED


def test_markup_payloads_stay_unclassified():
    assert root_rule("'<p>Library documentation in <em>Markdown</em>.</p>") == UNCLASSIFIED
