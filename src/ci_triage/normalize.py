"""Turn failure text into a stable fingerprint.

Two failures from the same root cause differ in paths, interpreter versions,
timings, and line numbers. Everything in SCRUBBERS is a token observed to
vary across runs of robotframework/robotframework while the underlying
failure stayed the same. What survives scrubbing is the failure's shape.

Deterministic on purpose. A reviewer can read these rules and predict what
groups with what, which is not true of an embedding threshold tuned until
the cluster count looked reasonable.
"""

from __future__ import annotations

import hashlib
import re

#: Absolute paths, kept separate because root extraction needs the filename
#: while exact-match clustering does not. Collapsing a whole path to <PATH>
#: makes every FileNotFoundError identical regardless of which file was
#: missing, which is how 94% of a corpus lands in one cluster.
PATH_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"[A-Za-z]:\\\\?[^\s'\"]+"),
    re.compile(r"/(?:home|opt|usr|tmp|var|private|github|Users)/[^\s'\":]*"),
]


def _basename(match: re.Match[str]) -> str:
    """Replace a path with <PATH> plus its final component."""
    tail = re.split(r"[\\/]", match.group(0))[-1]
    return f"<PATH>/{tail}" if tail else "<PATH>"


def scrub_paths(text: str, keep_basename: bool = False) -> str:
    for pattern in PATH_PATTERNS:
        text = pattern.sub(_basename if keep_basename else "<PATH>", text)
    return text


#: Ordered: paths are scrubbed before these, or the version and line numbers
#: inside them get replaced first and the path patterns stop matching.
SCRUBBERS: list[tuple[re.Pattern[str], str]] = [
    # Interpreter build dirs leak version and OS into otherwise identical text.
    (re.compile(r"Python-\d+\.\d+(?:\.\d+)?-\w+"), "<PYBUILD>"),
    (re.compile(r"python\d+\.\d+"), "<PYVER>"),
    # Robot's own run summary.
    (re.compile(r"\b\d+ tests?, \d+ passed, \d+ failed\b"), "<COUNTS>"),
    (
        re.compile(
            r"\b\d+ (?:minutes?|seconds?|milliseconds?)"
            r"(?: \d+ (?:minutes?|seconds?|milliseconds?))*"
        ),
        "<DURATION>",
    ),
    (re.compile(r"\b\d+\.\d+s\b"), "<DURATION>"),
    # Traceback and source coordinates.
    (re.compile(r"\bline \d+\b"), "line <N>"),
    (re.compile(r"\bRan \d+ tests?\b"), "Ran <N> tests"),
    # Identifiers that are unique per run by construction.
    (
        re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"),
        "<UUID>",
    ),
    (re.compile(r"\b[0-9a-f]{40}\b"), "<SHA>"),
    (re.compile(r"\b0x[0-9a-fA-F]+\b"), "<ADDR>"),
    (re.compile(r"\bpid \(?\d+\)?"), "pid <N>"),
    # Robot's progress dots carry no information.
    (re.compile(r"^\.+$", re.MULTILINE), ""),
    # Robot wraps every cascading failure in a status line that embeds the
    # test name. Left alone it gives each failure of a shared root cause its
    # own fingerprint, which is how 8 screenshot tests became 8 causes.
    # The diagnostic content is in the "Error message:" body below it.
    (
        re.compile(r"Status of '[^']*' should have been (PASS|FAIL) but it was (PASS|FAIL)\."),
        "Status of <TEST> should have been \\1 but it was \\2.",
    ),
    # Robot reports its own artifacts by interpreter-specific filename.
    (re.compile(r"\b(output|log|report)\.(xml|html)\b"), r"<ARTIFACT>"),
]

_WS = re.compile(r"[ \t]+")
_BLANKS = re.compile(r"\n{3,}")


def normalize(text: str, keep_basename: bool = False) -> str:
    """Apply every scrubber, then collapse whitespace.

    Whitespace collapsing happens last so that scrubbed spans that reduce to
    nothing don't leave ragged gaps that defeat exact-match grouping.

    keep_basename retains the final path component, which root extraction
    needs to tell one missing file from another.
    """
    text = scrub_paths(text, keep_basename=keep_basename)
    for pattern, replacement in SCRUBBERS:
        text = pattern.sub(replacement, text)
    text = _WS.sub(" ", text)
    text = _BLANKS.sub("\n\n", text)
    return "\n".join(line.strip() for line in text.splitlines()).strip()


def _digest(*parts: str) -> str:
    joined = "\n\x00\n".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def cause_signature(message: str) -> str:
    """Fingerprint the failure message alone, ignoring which test hit it.

    This is what collapses a cascade: 572 different tests failing because
    PyYAML is missing all share one cause signature.
    """
    return _digest(normalize(message))


def case_signature(test_id: str, message: str) -> str:
    """Fingerprint a specific test failing a specific way.

    This is what identifies recurrence: the same test failing the same way
    across runs is a persistent problem, not a flake.
    """
    return _digest(test_id.strip(), normalize(message))
