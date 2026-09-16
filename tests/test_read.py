"""
Tests reading functionality.
"""

from __future__ import annotations

from ci_triage.logs import read_log, strip_timestamps


def test_bom_does_not_survive_the_read(tmp_path):
    path = tmp_path / "log.txt"
    path.write_bytes(
        b"\xef\xbb\xbf2026-06-17T14:02:10.5834905Z first line\r\n"
        b"2026-06-17T14:02:11.0000000Z second line\r\n"
    )
    cleaned = strip_timestamps(read_log(path))
    assert cleaned.splitlines()[0] == "first line"
