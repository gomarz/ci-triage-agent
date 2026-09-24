"""Decide what kind of failed job a log is, and parse it accordingly.

The corpus is not all Robot acceptance runs. Of the failed jobs cached from
robotframework/robotframework:

    robot         per-test FAIL: blocks under Robot's 100-character rule
    unittest      per-test ERROR:/FAIL: blocks under unittest's 70-character rule
    crash         died on an import error or bad flag before any test reported
    unrecognized  none of the above

Order matters. A Robot log can embed unittest blocks in a failure message
(Robot runs the unit tests as one of its own tests), so Robot goes first and
the nested blocks stay part of that one failure. unittest goes before crash
because a unittest run that reports failures contains tracebacks too.

"unrecognized" is a bucket rather than an error. A job that is not a test run
at all (one cached job is GitHub's Copilot review bot) stays visible in the
counts instead of being forced through a parser it does not fit or silently
dropped.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from ci_triage.crash import extract_crash
from ci_triage.extract import RunTally, TestFailure, extract_failures, parse_tally
from ci_triage.logs import diagnostic_body, has_error_marker
from ci_triage.unittest_extract import extract_unittest_failures, parse_unittest_tally


class JobShape(StrEnum):
    CLEAN = "clean"
    ROBOT = "robot"
    UNITTEST = "unittest"
    CRASH = "crash"
    UNRECOGNIZED = "unrecognized"


class ParsedJob(BaseModel):
    shape: JobShape
    failures: list[TestFailure] = Field(default_factory=list)
    #: The runner's own failure count, when it prints one. Crashes have none.
    tally: RunTally | None = None


def parse_job(text: str) -> ParsedJob:
    """Classify a raw job log and extract its failures."""
    if not has_error_marker(text):
        return ParsedJob(shape=JobShape.CLEAN)

    body = diagnostic_body(text)

    failures = extract_failures(body)
    if failures:
        return ParsedJob(shape=JobShape.ROBOT, failures=failures, tally=parse_tally(body))

    failures = extract_unittest_failures(body)
    if failures:
        return ParsedJob(
            shape=JobShape.UNITTEST, failures=failures, tally=parse_unittest_tally(body)
        )

    crash = extract_crash(body)
    if crash:
        return ParsedJob(shape=JobShape.CRASH, failures=[crash])

    return ParsedJob(shape=JobShape.UNRECOGNIZED)
