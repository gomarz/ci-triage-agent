"""Parse unittest's failure report into individual test failures.

After a run, unittest prints one block per failing test:

    ======================================================================
    ERROR: test_name (module.Class.test_name)
    ----------------------------------------------------------------------
    Traceback (most recent call last):
      ...
    SomeError: what happened

and closes with a footer:

    ----------------------------------------------------------------------
    Ran 2389 tests in 9.018s

    FAILED (errors=3)

Two things make this easy to get wrong:

* In verbose mode every test also prints an inline result while it runs,
  "test_name (module.Class.test_name) ... ERROR". That line and the block
  header both contain the word, but only the block carries the traceback.
  The header is matched between two 70-character rules, which the inline
  line never is.
* A block ends at the next rule, not at the next "Traceback" line. Chained
  exceptions ("During handling of the above exception...") put two tracebacks
  inside one block.

The rule is 70 characters, Robot's is 100. extract.py depends on that gap to
keep unittest output nested inside a Robot failure in one piece.
"""

from __future__ import annotations

import re

from ci_triage.extract import RunTally, TestFailure
from ci_triage.models import Outcome

_BLOCK = re.compile(
    r"^={70}\n(?P<kind>ERROR|FAIL): (?P<test_id>[^\n]+)\n-{70}\n",
    re.MULTILINE,
)

#: The rule that closes the last block also opens the "Ran N tests" footer,
#: so a block ends at whichever of the two comes first.
_FOOTER = re.compile(r"^-{70}\nRan \d+ tests? in ", re.MULTILINE)

_TALLY = re.compile(
    r"^Ran (?P<total>\d+) tests? in [\d.]+s\n\n(?:OK|FAILED)(?: \((?P<detail>[^)\n]*)\))?$",
    re.MULTILINE,
)
_COUNT = re.compile(r"^(?:failures|errors)=(?P<n>\d+)$")


def extract_unittest_failures(text: str) -> list[TestFailure]:
    """Pull every ERROR:/FAIL: block out of timestamp-stripped log text."""
    heads = list(_BLOCK.finditer(text))
    stops = sorted([h.start() for h in heads] + [f.start() for f in _FOOTER.finditer(text)])

    failures: list[TestFailure] = []
    for head in heads:
        end = next((s for s in stops if s > head.start()), len(text))
        message = text[head.end() : end].strip()
        failures.append(TestFailure.build(head["test_id"].strip(), message))
    return failures


def parse_unittest_tally(text: str) -> RunTally | None:
    """unittest's own count, to check extraction against.

    A job can run unittest more than once and each run prints blocks, so the
    counts are summed. Robot takes the last summary because its runs nest.
    Only failures and errors are counted: they are the two outcomes that
    print a block. Skips and expected failures do not, so "passed" here is
    total minus failed.
    """
    matches = list(_TALLY.finditer(text))
    if not matches:
        return None

    total = failed = 0
    for match in matches:
        total += int(match["total"])
        for part in (match["detail"] or "").split(", "):
            count = _COUNT.match(part)
            if count:
                failed += int(count["n"])
    return RunTally(total=total, passed=total - failed, failed=failed)


#: Verbose mode prints "name (id) ... result" as each test finishes. A test with
#: a docstring puts its first line between the id and the result. The id is
#: kept as printed, "name (module.Class.name)", because that is also how the
#: FAIL:/ERROR: block headers spell it, so outcomes join against failures.
_INLINE = re.compile(
    r"^(?P<test_id>\S+ \([^)\n]+\))(?:\n[^\n]*?)? \.\.\. "
    r"(?P<result>ok|FAIL|ERROR|skipped\b[^\n]*|expected failure|unexpected success)$",
    re.MULTILINE,
)

#: An expected failure is the outcome the author asked for, so it is a pass here;
#: an unexpected success makes the run fail, so it is not.
_OUTCOME = {
    "ok": Outcome.PASS,
    "expected failure": Outcome.PASS,
    "FAIL": Outcome.FAIL,
    "unexpected success": Outcome.FAIL,
    "ERROR": Outcome.ERROR,
}

_SEVERITY = [Outcome.ERROR, Outcome.FAIL, Outcome.PASS, Outcome.SKIP]


def extract_unittest_outcomes(text: str) -> dict[str, Outcome]:
    """What every test did, from a verbose run's inline result lines.

    Only verbose output has them; a quiet run prints dots and yields nothing.
    A test that writes to stdout mid-line loses its result to that output and is
    left out, not guessed. If a job runs a test twice, the worse outcome wins,
    so a repeat cannot hide a failure.
    """
    outcomes: dict[str, Outcome] = {}
    for match in _INLINE.finditer(text):
        result = match["result"]
        outcome = _OUTCOME.get(result, Outcome.SKIP if result.startswith("skipped") else None)
        if outcome is None:
            continue
        test_id = match["test_id"]
        seen = outcomes.get(test_id)
        if seen is None or _SEVERITY.index(outcome) < _SEVERITY.index(seen):
            outcomes[test_id] = outcome
    return outcomes
