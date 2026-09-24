"""Parse Robot Framework acceptance output into individual test failures.

Robot delimits each failure with a 100-character rule. unittest, which runs
nested inside some of these suites, uses a 70-character rule for its own
tracebacks. Requiring 90+ keeps a nested unittest traceback intact instead
of shredding it into fragments.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from ci_triage.normalize import case_signature, cause_signature, normalize
from ci_triage.roots import root_cause, root_signature

#: Robot's separators are exactly 100 chars; unittest's are 70.
_RULE = re.compile(r"^[-=]{90,}$", re.MULTILINE)

_FAIL_HEAD = re.compile(r"^FAIL: (.+)$", re.MULTILINE)

#: Trailing suite summary, not part of any one failure.
_SUMMARY = re.compile(r"^Run suite .+ with (?P<total>\d+) tests? in .+$", re.MULTILINE)
_TALLY = re.compile(
    r"^(?P<total>\d+) tests?, (?P<passed>\d+) passed, (?P<failed>\d+) failed$",
    re.MULTILINE,
)


class TestFailure(BaseModel):
    """One failing test, extracted from acceptance output."""

    test_id: str
    message: str
    #: Coarsest: what actually went wrong, shared across differently-worded
    #: symptoms of one cause.
    root_sig: str
    #: Exact-match on the full message.
    cause_sig: str
    #: Message plus test identity.
    case_sig: str
    #: Which ladder rule derived root_sig. "unclassified" means none did.
    root_rule: str
    #: "test" for one failing test, "job" for a job that died before any test
    #: ran. A job-level record has no test identity, so its case_sig is the
    #: cause identity: the same crash in two runs is the same recurring failure.
    scope: str = "test"

    @classmethod
    def build(cls, test_id: str, message: str, scope: str = "test") -> TestFailure:
        """Derive every signature from a test id and its failure message."""
        return cls(
            test_id=test_id,
            message=message,
            root_sig=root_signature(message),
            root_rule=root_cause(message)[1],
            cause_sig=cause_signature(message),
            case_sig=case_signature(test_id, message),
            scope=scope,
        )

    @property
    def root(self) -> str:
        """The extracted root-cause sentence, for display."""
        return root_cause(self.message)[0]

    @property
    def headline(self) -> str:
        """First meaningful line of the message, for display."""
        for line in normalize(self.message).splitlines():
            if line:
                return line
        return ""


class RunTally(BaseModel):
    """Robot's own count of what happened, when it's present."""

    total: int
    passed: int
    failed: int


def parse_tally(text: str) -> RunTally | None:
    """Robot's final count.

    A job can print several summaries (unit tests, then acceptance), so the
    last one is the job's verdict. Taking the first reported 0 failures for
    runs that plainly had some.
    """
    matches = list(_TALLY.finditer(text))
    if not matches:
        return None
    match = matches[-1]
    return RunTally(
        total=int(match["total"]),
        passed=int(match["passed"]),
        failed=int(match["failed"]),
    )


def extract_failures(text: str) -> list[TestFailure]:
    """Pull every FAIL: block out of a failure region.

    Blocks are split on Robot's rule, then each chunk is checked for a
    FAIL: header. Chunks without one are suite chatter or the trailing
    summary and get dropped.

    A log with no Robot rule at all has no Robot failures. unittest prints
    the same "FAIL:" header, and without a rule to split on the whole log is
    one chunk: the first unittest failure would swallow everything after it
    as its message (up to 146 KB in the cached corpus) and count as one
    Robot failure.
    """
    if not _RULE.search(text):
        return []

    failures: list[TestFailure] = []

    for chunk in _RULE.split(text):
        head = _FAIL_HEAD.search(chunk)
        if not head:
            continue

        test_id = head.group(1).strip()
        body = chunk[head.end() :]

        # The suite summary trails the final failure in the same chunk.
        cut = _SUMMARY.search(body)
        if cut:
            body = body[: cut.start()]

        message = body.strip()
        if not message:
            continue

        failures.append(TestFailure.build(test_id, message))

    return failures
