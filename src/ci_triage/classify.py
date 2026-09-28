"""Assign a category to a failure from its extracted root cause.

Stage 3. The category decides what kind of fix stage 4 should propose: a
missing dependency is a workflow or pin change, an expectation mismatch is a
test or source change, a missing build artifact is neither.

Rules read the root sentence, tried in order, first match wins, and every
result names the rule that produced it, as root extraction does. They fire
only on a strong indicator. A failure no rule is sure about stays UNTRIAGED
instead of getting a plausible guess: a wrong category sends stage 4 down the
wrong proposal type, while UNTRIAGED leaves the failure for the model.

No rule here assigns FLAKE, because no root sentence can: "Lists differ" is a
regression on a changed commit and a flake on an unchanged one. A flake is a
test that passes and fails on the same commit, which is history, found by
flake.find_flakes. classify(failure, flaky=True) takes that verdict, and it
outranks every rule below since it is direct evidence and they are wording.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from ci_triage.extract import TestFailure
from ci_triage.flake import FLAKE_RULE
from ci_triage.models import FailureCategory

UNMATCHED = "unmatched"
NO_ROOT = "no-root"

FLAKE_LIMITS = """\
Flake detection needs the same test failing in one run and passing in another
on the same commit, in the same workflow and job. The Robot corpus has 100
runs, every one a failure on attempt 1, and its commits with several runs are
different workflows, so it holds no flake evidence. The testbed corpus does:
see flake.py for what it can and cannot see.
"""

_Rule = tuple[str, FailureCategory, re.Pattern[str]]

#: Ordered. A missing module is checked before the comparison rules because a
#: message can be both ("Markdown format requires 'markdown' module to be
#: installed") and the cause is the module, not the mismatch.
_RULES: list[_Rule] = [
    (
        "missing-module",
        FailureCategory.ENVIRONMENT,
        re.compile(r"ModuleNotFoundError: No module named|requires .{1,60} module to be installed"),
    ),
    (
        # A name the standard library gained in a later Python. The job ran on
        # an interpreter older than the code supports.
        "stdlib-name-missing",
        FailureCategory.ENVIRONMENT,
        re.compile(r"ImportError: cannot import name '\w+' from 'typing(?:_extensions)?'"),
    ),
    (
        # The step that should have produced this file did not. The artifact
        # is the symptom; the cause is upstream, in the build or the runner.
        "missing-artifact",
        FailureCategory.INFRASTRUCTURE,
        re.compile(
            r"FileNotFoundError: \[Errno 2\] No such file or directory"
            r"|^(?:Source )?[Ff]ile '.+' does not exist\.$"
        ),
    ),
    (
        # A test waited a bounded time for a file a subprocess should have
        # written. Slower evidence than a missing file, so it is named apart.
        "file-not-created-in-time",
        FailureCategory.INFRASTRUCTURE,
        re.compile(r"^'.+' was not created in "),
    ),
    (
        "assertion",
        FailureCategory.REGRESSION,
        re.compile(r"^AssertionError\b"),
    ),
    (
        # Actual against expected, in Robot's phrasings. An empty actual
        # ("'' does not contain ...") is excluded: the process under test
        # printed nothing, which points at the run, not at the assertion.
        # "should be" is deliberately absent. It is how Robot words a check
        # that captured stderr is empty, so "SyntaxError: ... should be empty"
        # is an interpreter problem, and "Status of X should have been PASS"
        # is a wrapper that says nothing about the cause.
        "mismatch",
        FailureCategory.REGRESSION,
        re.compile(
            r"^(?!'' )"
            r".*(?: != |are different|does not (?:contain|match|start with|end with)"
            r"|exists and has value)"
        ),
    ),
]


class Classification(BaseModel):
    category: FailureCategory
    #: Which rule decided it, so a report can show how it was derived.
    rule: str


def classify_root(root: str) -> Classification:
    """Category for one extracted root sentence."""
    root = root.strip()
    if not root:
        return Classification(category=FailureCategory.UNTRIAGED, rule=NO_ROOT)

    for name, category, pattern in _RULES:
        if pattern.search(root):
            return Classification(category=category, rule=name)

    return Classification(category=FailureCategory.UNTRIAGED, rule=UNMATCHED)


def classify(failure: TestFailure, *, flaky: bool = False) -> Classification:
    """Category for one failure. Same root, same category, by construction.

    `flaky` is history's verdict (see flake.find_flakes) and overrides the root
    rules: an assertion that failed and passed on one commit is a flake, whatever
    the wording says.
    """
    if flaky:
        return Classification(category=FailureCategory.FLAKE, rule=FLAKE_RULE)
    return classify_root(failure.root)
