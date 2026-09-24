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
