from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from ci_triage.logs import read_log

LOG_FIXTURES = Path(__file__).parent / "fixtures" / "logs"


@pytest.fixture
def log() -> Callable[[str], str]:
    """Load a log fixture the way production does, timestamps intact.

    The fixtures are line ranges cut from real cached logs, so they carry the
    runner's timestamps and separator widths. Going through read_log keeps
    line endings the same as a fresh cache read, whatever git did to them.
    """

    def load(name: str) -> str:
        return read_log(LOG_FIXTURES / name)

    return load
