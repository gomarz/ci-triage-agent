"""Flake detection: pure grouping logic, then a cache built from real log fixtures."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

from ci_triage import extract
from ci_triage.classify import classify
from ci_triage.flake import FLAKE_RULE, JobObservation, find_flakes, load_observations
from ci_triage.models import FailureCategory, Outcome

FIXTURES = Path(__file__).parent / "fixtures"
TEST_ID = "test_unique_skus (tests.test_cart.CartTests.test_unique_skus)"
P, F = Outcome.PASS, Outcome.FAIL


def obs(job_id, outcome, *, commit="c1", workflow=1, name="test", test="t (m.C.t)"):
    return JobObservation(
        run_id=job_id,
        job_id=job_id,
        job_name=name,
        commit_sha=commit,
        workflow_id=workflow,
        outcomes={test: outcome},
    )


def test_pass_and_fail_on_one_commit_is_a_flake():
    [finding] = find_flakes([obs(1, P), obs(2, F), obs(3, P)])
    assert finding.passed_in == [1, 3]
    assert finding.failed_in == [2]
    assert round(finding.failure_rate, 2) == 0.33


def test_an_error_counts_as_a_failure():
    assert len(find_flakes([obs(1, P), obs(2, Outcome.ERROR)])) == 1


def test_always_failing_is_not_flaky():
    assert find_flakes([obs(1, F), obs(2, F)]) == []


def test_always_passing_is_not_flaky():
    assert find_flakes([obs(1, P), obs(2, P)]) == []


def test_a_skip_is_neither_a_pass_nor_a_failure():
    assert find_flakes([obs(1, Outcome.SKIP), obs(2, F)]) == []


def test_a_single_job_shows_nothing():
    assert find_flakes([obs(1, F)]) == []


def test_different_commits_are_a_change_not_a_flake():
    assert find_flakes([obs(1, P, commit="a"), obs(2, F, commit="b")]) == []


def test_different_workflows_are_not_compared():
    """The Robot corpus's repeated commits were this: unit tests and acceptance tests."""
    assert find_flakes([obs(1, P, workflow=1), obs(2, F, workflow=2)]) == []


def test_matrix_cells_are_not_compared():
    """Failing on Windows only is a platform difference, not a flake."""
    assert find_flakes([obs(1, P, name="linux"), obs(2, F, name="windows")]) == []


def test_most_failing_first():
    a = [obs(1, P, test="a (m.C.a)"), obs(2, F, test="a (m.C.a)"), obs(3, P, test="a (m.C.a)")]
    b = [obs(1, P, test="b (m.C.b)"), obs(2, F, test="b (m.C.b)"), obs(3, F, test="b (m.C.b)")]
    merged = [
        JobObservation(**{**x.model_dump(), "outcomes": {**x.outcomes, **y.outcomes}})
        for x, y in zip(a, b, strict=True)
    ]
    assert [f.test_id for f in find_flakes(merged)] == ["b (m.C.b)", "a (m.C.a)"]


def _cache(tmp_path: Path, runs: list[tuple[int, str]]) -> Path:
    """A data dir holding one run and one job per (run id, log fixture), all on one commit."""
    template = json.loads((FIXTURES / "runs.json").read_text(encoding="utf-8"))["workflow_runs"][0]
    raw = tmp_path / "raw"
    for run_id, fixture in runs:
        payload = copy.deepcopy(template)
        payload.update(id=run_id, head_sha="7f2b215", workflow_id=99, run_attempt=1)
        (raw / "runs").mkdir(parents=True, exist_ok=True)
        (raw / "runs" / f"{run_id}.json").write_text(json.dumps(payload), encoding="utf-8")

        job = {"id": run_id * 10, "run_id": run_id, "name": "test", "conclusion": "failure"}
        (raw / "jobs").mkdir(exist_ok=True)
        (raw / "jobs" / f"{run_id}.json").write_text(json.dumps([job]), encoding="utf-8")

        log_dir = raw / "logs" / str(run_id)
        log_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURES / "logs" / fixture, log_dir / f"{run_id * 10}.txt")
    return tmp_path


def test_finds_the_flake_in_a_cache_built_from_real_logs(tmp_path):
    data = _cache(
        tmp_path,
        [(1, "unittest_verbose_pass.txt"), (2, "unittest_verbose_flaky_fail.txt")],
    )
    observations = load_observations(data)

    assert [len(o.outcomes) for o in observations] == [18, 18]
    [finding] = find_flakes(observations)
    assert finding.test_id == TEST_ID
    assert (finding.passed_in, finding.failed_in) == ([10], [20])


def test_two_passing_runs_of_a_commit_have_no_flake(tmp_path):
    data = _cache(tmp_path, [(1, "unittest_verbose_pass.txt"), (2, "unittest_verbose_pass.txt")])
    assert find_flakes(load_observations(data)) == []


def test_jobs_without_a_log_are_left_out(tmp_path):
    data = _cache(tmp_path, [(1, "unittest_verbose_pass.txt")])
    (data / "raw" / "logs" / "1" / "10.txt").unlink()
    assert load_observations(data) == []


def test_history_overrides_the_wording():
    failure = extract.TestFailure.build(
        TEST_ID, "AssertionError: Lists differ: ['pear'] != ['apple']"
    )

    assert classify(failure).category is FailureCategory.REGRESSION
    flaky = classify(failure, flaky=True)
    assert (flaky.category, flaky.rule) == (FailureCategory.FLAKE, FLAKE_RULE)
