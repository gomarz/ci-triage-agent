"""Extract the failure from a job that died before any test reported.

Some failed jobs never reach a test runner: a driver script hits an
ImportError, or Robot rejects a command-line flag. There is nothing to split
into per-test records. The job itself is the failure, so this yields at most
one record per job.

The root is the first error in the log, not the last. A crash cascades: in
one cached job a missing module raised in run.py, raised again when rebot.py
imported the same package, and then a third traceback fired because the
output file the first run should have written did not exist. Only the first
is the cause.
"""

from __future__ import annotations

import re

from ci_triage.extract import TestFailure

#: Job-level records have no test to name.
JOB_ID = "<job>"

_TRACEBACK = re.compile(r"^Traceback \(most recent call last\):$", re.MULTILINE)

#: Robot's own error line. Robot prints it for problems it reports without a
#: traceback, such as an option it does not recognise.
_ROBOT_ERROR = re.compile(r"^\[ ERROR \] (?P<message>.+)$", re.MULTILINE)


def _exception_line(text: str) -> tuple[int, str] | None:
    """Position and text of the exception ending the first traceback.

    Frames, code lines and position markers are all indented, so the exception
    is the first line back at column zero. Only that line is kept: frames
    differ by interpreter version (3.13 adds ^^^^ markers) and would give the
    same crash a different signature on each Python in the matrix.
    """
    match = _TRACEBACK.search(text)
    if not match:
        return None
    for line in text[match.end() :].splitlines():
        if line and not line[0].isspace():
            return match.start(), line.strip()
    return None


def extract_crash(text: str) -> TestFailure | None:
    """The job-level failure in timestamp-stripped log text, if there is one.

    None means the log holds no Python traceback and no Robot error line.
    The runner's own "Process completed with exit code 1" is deliberately not
    enough: it says a step failed, not why.
    """
    candidates: list[tuple[int, str]] = []

    exception = _exception_line(text)
    if exception:
        candidates.append(exception)

    robot = _ROBOT_ERROR.search(text)
    if robot:
        candidates.append((robot.start(), robot["message"].strip()))

    if not candidates:
        return None

    _, message = min(candidates)
    return TestFailure.build(JOB_ID, message, scope="job")
