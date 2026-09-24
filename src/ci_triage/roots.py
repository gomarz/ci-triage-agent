"""Isolate the innermost error signal from a failure message.

The exact-match signature in normalize.py groups identical failures. It
cannot group failures that share a root cause but read differently, which
is most of a real cascade: one missing dependency surfaces as a setup
error in one test, an unmatched log message in another, and a missing
variable in a third.

This module peels the wrapper layers Robot adds and keeps only the deepest
diagnostic sentence, so those variants collapse to one root.

It is a ladder of rules, tried in order of specificity, and it deliberately
stops rather than guessing. Failures whose text shares no phrase with the
real cause will not merge, and no rule here can fix that. See ROOT_LIMITS.
"""

from __future__ import annotations

import re

from ci_triage.normalize import _digest, normalize

#: Which ladder rule produced a root. Recorded so a report can say how a
#: grouping was derived rather than presenting every root with equal
#: confidence.
FALLBACK_RULE = "first-line"
UNCLASSIFIED = "unclassified"

#: Text this short, or with no run of letters in it, carries no diagnostic
#: content. Robot glob patterns ("*", "ComposerError*") reach here from the
#: expected side of a comparison. The check applies to every rule, not just
#: the fallback: a meaningless string is no more useful for being labelled
#: "failed-reason" than for being labelled a guess.
_MIN_ROOT_LEN = 12
_HAS_LETTERS = re.compile(r"[A-Za-z]{3}")

#: A fallback line opening with a quote or a list bullet is the payload of a
#: content comparison (HTML fragments, changelog excerpts), not a description
#: of what went wrong. Matched against the FIRST line only: skipping just the
#: opening line hands the next line of the same payload back as a root.
_QUOTED_PAYLOAD = re.compile(r"^['\"*\-]\s*\S")

_MEANINGFUL_DESCRIPTORS = ("!=", "does not", "was not", "not found")


def _is_meaningful(text: str) -> bool:
    """Whether an extracted root says anything about what broke."""
    text = text.strip()
    if any(w in text for w in _MEANINGFUL_DESCRIPTORS):
        return True
    return len(text) >= _MIN_ROOT_LEN and bool(_HAS_LETTERS.search(text))


#: Layers Robot wraps around the real error. Each carries no diagnostic
#: content of its own; the cause is always below them.
_WRAPPERS: list[re.Pattern[str]] = [
    re.compile(
        r"^Status of <TEST> should have been (?:PASS|FAIL) but it was (?:PASS|FAIL)\.[ \t]*$",
        re.MULTILINE,
    ),
    re.compile(r"^Error message:[ \t]*$", re.MULTILINE),
    # Robot capitalises only the first word: "Setup failed:" but
    # "Parent suite setup failed:" and "Suite teardown failed:".
    re.compile(
        r"^(?:(?:Parent suite|Suite) )?(?:[Ss]etup|[Tt]eardown) failed:[ \t]*$", re.MULTILINE
    ),
    re.compile(r"^Several failures occurred:[ \t]*$", re.MULTILINE),
    re.compile(r"^\d+\)[ \t]+", re.MULTILINE),
]

#: "<something> failed: <reason>" — the reason is what matters. Robot emits
#: this for variable files, output processing, and imports. The first match
#: wins: in a "does not match" comparison the actual comes before the
#: expected, and the actual is what happened.
_FAILED_REASON = re.compile(r"\bfailed:[ \t]+(\S[^\n]*)")

#: A raised exception. The last one is the one that propagated.
_EXCEPTION = re.compile(
    r"^([A-Za-z_][\w.]*(?:Error|Exception|Failure))(?:\([^)]*\))?:[ \t]+(.+)$",
    re.MULTILINE,
)

#: Robot compares actual against expected on one line. Everything from the
#: comparison marker on is the expectation, not what happened, and letting it
#: through splits one root cause across every test that expected something
#: different.
_COMPARISON = re.compile(r"\s*(?:'\s*)?(?:does not match|!=)\s*(?:'|$)")

#: Unified-diff payload lines, excluding the ---/+++/@@ furniture.
_DIFF_LINE = re.compile(r"^[-+](?![-+@])(.+)$", re.MULTILINE)

#: Applied on top of normalize() for roots only. Coarser than the cause
#: signature on purpose: a root should merge variants that a fine-grained
#: view keeps apart.
ROOT_SCRUBBERS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\$\{[^}]*\}"), "<VAR>"),
    (re.compile(r"\[Errno \d+\]"), "[Errno <N>]"),
    (re.compile(r"\bRC \d+\b"), "RC <N>"),
]

#: What this approach cannot do, recorded so it isn't rediscovered later.
ROOT_LIMITS = """\
Deterministic root extraction merges failures that share wording. It cannot
merge failures whose text has no phrase in common with the cause, even when
the cause is identical. A missing PyYAML module surfaces both as "requires
PyYAML module to be installed" and as "Variable <VAR> not found", and
nothing short of domain knowledge or a model connects those two strings.
Expect partial collapse, and measure it rather than assuming it.
"""


def strip_wrappers(message: str) -> str:
    """Remove Robot's non-diagnostic framing lines."""
    for pattern in _WRAPPERS:
        message = pattern.sub("", message)
    return message.strip()


def _trim_comparison(text: str) -> str:
    """Drop the expected half of an actual-vs-expected line."""
    split = _COMPARISON.split(text, maxsplit=1)
    if len(split) == 1:
        return text.strip()
    # Only strip the dangling quote left behind by the removed comparison.
    return split[0].strip().rstrip("'\"").strip()


def root_cause(message: str) -> tuple[str, str]:
    """Extract the deepest diagnostic sentence, and say which rule found it.

    Ladder, most specific first. The first rule that matches wins. The
    returned rule name matters: "first-line" means nothing recognisable
    matched and the result is a guess, which a report should not present
    with the same confidence as an extracted exception.

    keep_basename is on because "no such file: output.xml" and "no such
    file: some_test.robot" are different problems, and full path scrubbing
    makes them identical.
    """
    body = strip_wrappers(normalize(message, keep_basename=True))

    # Each rule falls through rather than returning junk, so a glob captured
    # by the reason rule still gets a chance at the exception rule below it.
    for match in _FAILED_REASON.finditer(body):
        candidate = _trim_comparison(match.group(1))
        if _is_meaningful(candidate):
            return candidate, "failed-reason"

    exceptions = _EXCEPTION.findall(body)
    for name, detail in reversed(exceptions):
        candidate = f"{name}: {_trim_comparison(detail)}"
        if _is_meaningful(candidate):
            return candidate, "exception"

    # A diff carries its signal in the changed lines, not the prose above.
    diff_lines = _DIFF_LINE.findall(body)
    if diff_lines and "different" in body:
        candidate = "\n".join(line.strip() for line in diff_lines)
        if _is_meaningful(candidate):
            return candidate, "diff"

    for line in body.splitlines():
        candidate = _trim_comparison(line)
        if not candidate:
            continue
        if _QUOTED_PAYLOAD.match(candidate):
            if any(w in candidate for w in _MEANINGFUL_DESCRIPTORS):
                return candidate, FALLBACK_RULE
            # The message opens with compared content, so the whole message
            # is content. Later lines belong to the same payload.
            return "", UNCLASSIFIED
        if _is_meaningful(candidate):
            return candidate, FALLBACK_RULE
        return "", UNCLASSIFIED

    return "", UNCLASSIFIED


def root_cause_text(message: str) -> str:
    """The root sentence alone. See root_cause() for the rule that found it."""
    return root_cause(message)[0]


def root_rule(message: str) -> str:
    """Which ladder rule derived this root."""
    return root_cause(message)[1]


def root_signature(message: str) -> str:
    """Fingerprint the root cause, coarser than cause_signature.

    Everything unclassified shares one signature on purpose: a single
    visible "we could not extract a root" bucket is more useful than a
    scatter of meaningless ones.
    """
    text, rule = root_cause(message)
    if rule == UNCLASSIFIED:
        return _digest(UNCLASSIFIED)
    for pattern, replacement in ROOT_SCRUBBERS:
        text = pattern.sub(replacement, text)
    return _digest(text)
