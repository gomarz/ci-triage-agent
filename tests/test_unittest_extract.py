"""unittest failure parsing, against blocks cut from real cached job logs."""

from __future__ import annotations

from ci_triage.extract import extract_failures
from ci_triage.logs import strip_timestamps
from ci_triage.unittest_extract import extract_unittest_failures, parse_unittest_tally


def test_one_failure_per_block(log):
    failures = extract_unittest_failures(strip_timestamps(log("unittest_three_errors.txt")))

    assert [f.test_id for f in failures] == [
        "test_linkify_urls (test_markdown.TestLinkifyUrls.test_linkify_urls)",
        "test_no_urls (test_markdown.TestLinkifyUrls.test_no_urls)",
        "test_url_that_should_not_be_touched "
        "(test_markdown.TestLinkifyUrls.test_url_that_should_not_be_touched)",
    ]


def test_blocks_do_not_bleed_into_each_other(log):
    failures = extract_unittest_failures(strip_timestamps(log("unittest_three_errors.txt")))

    for failure in failures:
        assert failure.message.startswith("Traceback (most recent call last):")
        assert failure.message.count("Traceback (most recent call last):") == 1
        # The 70-dash rule and the "Ran N tests" footer belong to no failure.
        assert "Ran 2389 tests" not in failure.message
        assert "=" * 70 not in failure.message


def test_inline_result_line_is_not_a_failure(log):
    """Verbose mode prints "name (id) ... ERROR" while the test runs.

    Counting that line as well as the summary block would double every failure.
    """
    text = strip_timestamps(log("unittest_chained_error.txt"))
    assert "test_show_completion_exits_cleanly (" in text
    assert text.count("... ERROR") == 1

    assert len(extract_unittest_failures(text)) == 1


def test_chained_exception_stays_in_one_block(log):
    failures = extract_unittest_failures(strip_timestamps(log("unittest_chained_error.txt")))

    assert len(failures) == 1
    message = failures[0].message
    assert message.count("Traceback (most recent call last):") == 2
    assert "During handling of the above exception" in message
    # The exception that propagated is the last one, not the CliUsageError
    # that started the chain.
    assert failures[0].root == "robot.errors.DataError: unknown option '--show-completion'"


def test_fail_header_and_footer(log):
    failures = extract_unittest_failures(strip_timestamps(log("unittest_fail.txt")))

    assert len(failures) == 1
    assert failures[0].test_id == "test_roundtrip_from_python (test_libdoc.TestJson)"
    assert failures[0].scope == "test"
    assert "FAILED (failures=1)" not in failures[0].message
    assert failures[0].message.rstrip().endswith("'version': '0.1'}")


def test_log_without_blocks_yields_nothing():
    assert extract_unittest_failures("Ran 10 tests in 0.1s\n\nOK\n") == []


def test_unittest_output_is_not_a_robot_failure(log):
    """Regression: the Robot extractor once claimed this log as one failure.

    unittest prints the same "FAIL:" header. With no 100-character rule to
    split on, the whole log was a single chunk and the first FAIL: swallowed
    everything after it as its message.
    """
    assert extract_failures(strip_timestamps(log("unittest_fail.txt"))) == []


def test_tally_matches_blocks(log):
    for name, total, failed in [
        ("unittest_three_errors.txt", 2389, 3),
        ("unittest_chained_error.txt", 2457, 1),
        ("unittest_fail.txt", 2393, 1),
    ]:
        text = strip_timestamps(log(name))
        tally = parse_unittest_tally(text)

        assert tally is not None
        assert (tally.total, tally.failed) == (total, failed)
        assert len(extract_unittest_failures(text)) == failed


def test_tally_sums_repeated_runs(log):
    """A job can run unittest twice; both runs print blocks, so both count."""
    text = strip_timestamps(log("unittest_three_errors.txt") + log("unittest_fail.txt"))

    tally = parse_unittest_tally(text)

    assert (tally.total, tally.failed) == (2389 + 2393, 3 + 1)


def test_tally_ignores_outcomes_that_print_no_block():
    # Format from CPython's unittest.runner. Skips and expected failures are
    # counted by unittest but never get an ERROR:/FAIL: block.
    text = "Ran 50 tests in 1.0s\n\nFAILED (failures=2, skipped=3, expected failures=1)\n"

    assert parse_unittest_tally(text).failed == 2


def test_tally_absent():
    assert parse_unittest_tally("nothing here") is None
