"""Job-level crashes, from logs where no test ever reported."""

from __future__ import annotations

from ci_triage.crash import JOB_ID, extract_crash
from ci_triage.logs import strip_timestamps


def _crash(log, name):
    return extract_crash(strip_timestamps(log(name)))


def test_import_error_is_the_job_failure(log):
    failure = _crash(log, "crash_import_error.txt")

    assert failure.test_id == JOB_ID
    assert failure.scope == "job"
    assert failure.message.startswith("ImportError: cannot import name 'assert_in'")
    assert failure.root_rule == "exception"


def test_cascade_takes_the_first_error(log):
    """One missing module raised three tracebacks. Only the first is the cause.

    The second repeats it when rebot.py imports the same package. The third,
    a FileNotFoundError, is a consequence: the output file the first run
    should have written never existed.
    """
    text = strip_timestamps(log("crash_cascade.txt"))
    assert text.count("Traceback (most recent call last):") == 3
    assert "FileNotFoundError" in text

    failure = extract_crash(text)

    assert failure.root == "ModuleNotFoundError: No module named 'confargs'"


def test_frames_are_left_out_of_the_message(log):
    """Frames differ by interpreter (3.13 adds ^^^^ markers) and by checkout
    path, and would give one crash a different signature per matrix entry."""
    failure = _crash(log, "crash_cascade.txt")

    assert "File " not in failure.message
    assert "\n" not in failure.message


def test_robot_error_line_without_a_traceback(log):
    failure = _crash(log, "crash_cli_usage.txt")

    assert failure.message == "unknown option '--variable-file'"
    assert failure.root_rule == "first-line"


def test_runner_exit_code_alone_is_not_a_crash(log):
    """A step failing says nothing about why. This log is a review bot that
    could not get its model: no Python traceback, no Robot error line."""
    assert _crash(log, "unrecognized_bot.txt") is None


def test_same_crash_on_two_platforms_is_one_failure(log):
    """One ImportError from a Windows and a Linux matrix job.

    The interpreter paths differ (C:\\hostedtoolcache\\...\\Lib\\typing.py
    against /opt/hostedtoolcache/.../python3.11/typing.py). A job-level record
    has no test to tell it apart, so every signature has to agree or the
    recurrence is invisible.
    """
    windows = _crash(log, "crash_typealias_windows.txt")
    linux = _crash(log, "crash_typealias_linux.txt")

    assert windows.message != linux.message
    assert windows.cause_sig == linux.cause_sig
    assert windows.case_sig == linux.case_sig
    assert windows.root_sig == linux.root_sig
