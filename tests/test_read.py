"""
Tests reading functionality.
"""

from __future__ import annotations

from ci_triage.logs import cache_log, log_path, read_log, strip_timestamps


def test_cache_log_writes_under_the_corpus_root_and_keeps_crlf(tmp_path):
    path = cache_log(tmp_path, 11, 22, "first line\r\nsecond line\r\n")
    assert path == log_path(tmp_path, 11, 22) == tmp_path / "raw" / "logs" / "11" / "22.txt"
    # A translating writer would turn each CRLF into CRLFLF and double every line.
    assert path.read_bytes() == b"first line\r\nsecond line\r\n"
    assert read_log(path) == "first line\nsecond line\n"


def test_bom_does_not_survive_the_read(tmp_path):
    path = tmp_path / "log.txt"
    path.write_bytes(
        b"\xef\xbb\xbf2026-06-17T14:02:10.5834905Z first line\r\n"
        b"2026-06-17T14:02:11.0000000Z second line\r\n"
    )
    cleaned = strip_timestamps(read_log(path))
    assert cleaned.splitlines()[0] == "first line"
