"""Tests built from real robotframework/robotframework failure output.

The fixtures are trimmed from actual cached logs rather than invented, so
the separator widths, path shapes, and message formats are the ones the
parser will meet in production.
"""

from __future__ import annotations

import pytest

from ci_triage.normalize import case_signature, cause_signature, normalize

_STATUS = "Status of {name!r} should have been PASS but it was FAIL."


def _wrapped(name: str, error: str) -> str:
    """A failure as Robot reports it: status wrapper above the real message."""
    return f"{_STATUS.format(name=name)}\n\nError message:\n{error}"


_YAML = "Using YAML variable files requires PyYAML module to be installed."


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Ran 2434 tests in 13.339s", "Ran <N> tests in <DURATION>"),
        ("failed on line 96 of the file", "failed on line <N> of the file"),
        ("7041 tests, 6469 passed, 572 failed", "<COUNTS>"),
        ("using python3.8 interpreter", "using <PYVER> interpreter"),
        ("session b8c6527b-9219-431f-89c0-872a62cd1c97 failed", "session <UUID> failed"),
        ("commit 9f2a1c4d8e7b3a5f6c0d1e2f3a4b5c6d7e8f9a0b", "commit <SHA>"),
        ("output.xml 2026-06-17T14", "<ARTIFACT> 2026-06-17T14"),
        ("object at 0x00000217B6DB53D0", "object at <ADDR>"),
        ("results/Python-3.11.16-Linux/output/o", "results/<PYBUILD>/output/o"),
        ("50.10s", "<DURATION>"),
        ("pid (3449)", "pid <N>"),
        (
            "Status of 'Integers' should have been PASS but it was FAIL.",
            "Status of <TEST> should have been PASS but it was FAIL.",
        ),
        ("before\n......\nafter", "before\n\nafter"),
    ],
)
def test_scrubbers(raw, expected):
    assert normalize(raw) == expected


def test_same_cause_different_tests_diverge_on_case_sig():
    assert cause_signature(_YAML) == cause_signature(_YAML)
    assert case_signature("Suite.A", _YAML) != case_signature("Suite.B", _YAML)


def test_signature_is_stable_across_calls():
    message = "Variable '${X}' not found."
    assert cause_signature(message) == cause_signature(message)


def test_status_wrapper_collapses_cascades():
    """Robot's status line embeds the test name; a shared root cause must
    still produce one signature across the tests it takes down."""
    error = "Taking screenshots is not supported on this platform."
    a = _wrapped("Set Screenshot Directory", error)
    b = _wrapped("Each Screenshot Gets Separate Index", error)
    assert cause_signature(a) == cause_signature(b)


def test_status_wrapper_does_not_over_collapse():
    """Different underlying errors stay separate despite the shared wrapper."""
    a = _wrapped("A", "Screenshots unsupported.")
    b = _wrapped("B", "Variable '${X}' not found.")
    assert cause_signature(a) != cause_signature(b)
