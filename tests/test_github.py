import json
from pathlib import Path

import pytest

from ci_triage import github
from ci_triage.github import cache_payload, fetch_runs, parse_run
from ci_triage.models import Conclusion

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def runs_payload():
    with open(FIXTURES / "runs.json", encoding="utf-8") as f:
        return json.load(f)["workflow_runs"]


def test_parses_core_fields(runs_payload):
    run = parse_run(runs_payload[0])
    assert run.id == 33328240167
    assert run.repo == "robotframework/robotframework"
    assert run.workflow_name == "Acceptance tests (CPython + PyPy)"


def test_converts_conclusion_to_enum(runs_payload):
    run = parse_run(runs_payload[0])
    assert run.conclusion is Conclusion.FAILURE
    assert run.triageable is True


def test_fork_run_has_different_head_repo(runs_payload):
    run = parse_run(runs_payload[1])
    assert run.repo == "robotframework/robotframework"
    assert run.head_repo == "Vinni82/robotframework"


class _Response:
    def __init__(self, runs):
        self._runs = runs

    def raise_for_status(self):
        pass

    def json(self):
        return {"workflow_runs": self._runs}


@pytest.fixture
def fake_get(monkeypatch):
    """Replace httpx.get; each call returns the next page and is recorded."""
    calls, pages = [], []

    def get(url, params, headers):
        calls.append(params)
        return _Response(pages[len(calls) - 1])

    monkeypatch.setattr(github.httpx, "get", get)
    return calls, pages


def test_fetch_runs_asks_for_failures_by_default(fake_get):
    calls, pages = fake_get
    pages.append([{"id": 1}])
    fetch_runs("o/r", "tok")
    assert calls[0]["status"] == "failure"


def test_fetch_runs_include_passing_asks_for_completed(fake_get):
    calls, pages = fake_get
    pages.append([{"id": 1}])
    fetch_runs("o/r", "tok", include_passing=True)
    assert calls[0]["status"] == "completed"


def test_fetch_runs_stops_at_a_short_page(fake_get):
    calls, pages = fake_get
    pages.extend([[{"id": i} for i in range(100)], [{"id": 100}]])
    assert len(fetch_runs("o/r", "tok", pages=5)) == 101
    assert [c["page"] for c in calls] == [1, 2]


def test_fetch_runs_stops_at_the_page_limit(fake_get):
    calls, pages = fake_get
    pages.extend([[{"id": i} for i in range(100)]] * 3)
    assert len(fetch_runs("o/r", "tok", pages=2)) == 200
    assert len(calls) == 2


def test_cache_payload_writes_under_the_given_directory(tmp_path):
    path = cache_payload({"id": 7}, tmp_path / "runs")
    assert path == tmp_path / "runs" / "7.json"
