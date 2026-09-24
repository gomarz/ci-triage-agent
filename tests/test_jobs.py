"""Shape detection: which parser a failed job's log belongs to."""

from __future__ import annotations

import pytest

from ci_triage.jobs import JobShape, parse_job

RULE = "-" * 100
END = "=" * 100


def _stamped(body: str) -> str:
    """Prefix each line the way the Actions runner does."""
    return "\n".join(
        f"2026-06-30T18:00:00.{i:07d}Z {line}" for i, line in enumerate(body.splitlines())
    )


#: A Robot job that embeds unittest output in one of its own failure messages,
#: as the real suite does when it runs the unit tests as an acceptance test.
ROBOT_WITH_NESTED_UNITTEST = _stamped(
    f"""FAIL: Robot.External.Unit Tests.Unit Tests
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
{RULE}
{END}
Run suite 'Robot' with 7108 tests in 12 minutes 42 seconds 253 milliseconds.

FAILED
7108 tests, 7107 passed, 1 failed
##[error]Process completed with exit code 1.
Post job cleanup.
"""
)


@pytest.mark.parametrize(
    ("name", "shape"),
    [
        ("unittest_three_errors.txt", JobShape.UNITTEST),
        ("unittest_chained_error.txt", JobShape.UNITTEST),
        # Previously misfiled as Robot: see test_unittest_extract.
        ("unittest_fail.txt", JobShape.UNITTEST),
        ("crash_import_error.txt", JobShape.CRASH),
        ("crash_cascade.txt", JobShape.CRASH),
        ("crash_cli_usage.txt", JobShape.CRASH),
        ("unrecognized_bot.txt", JobShape.UNRECOGNIZED),
    ],
)
def test_shape(log, name, shape):
    assert parse_job(log(name)).shape == shape


def test_log_without_a_runner_error_is_clean():
    text = "2026-06-30T18:00:00.0000000Z Ran 3 tests in 0.1s\n"

    job = parse_job(text)

    assert job.shape == JobShape.CLEAN
    assert job.failures == []


def test_nested_unittest_stays_inside_the_robot_failure():
    """Robot goes first: the unittest block is part of that one failure."""
    job = parse_job(ROBOT_WITH_NESTED_UNITTEST)

    assert job.shape == JobShape.ROBOT
    assert len(job.failures) == 1
    assert job.failures[0].test_id == "Robot.External.Unit Tests.Unit Tests"
    assert (job.tally.total, job.tally.failed) == (7108, 1)


def test_unittest_job_carries_its_own_tally(log):
    job = parse_job(log("unittest_three_errors.txt"))

    assert len(job.failures) == job.tally.failed == 3


def test_crash_has_one_job_level_failure_and_no_tally(log):
    job = parse_job(log("crash_cascade.txt"))

    assert [f.scope for f in job.failures] == ["job"]
    assert job.tally is None


def test_unrecognized_job_has_no_failures(log):
    assert parse_job(log("unrecognized_bot.txt")).failures == []
