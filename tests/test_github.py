import json
from pathlib import Path

import pytest

from ci_triage.github import parse_run
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
