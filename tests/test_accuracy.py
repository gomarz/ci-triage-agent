"""Classifier scoring: verdict rules, per-seed roll-up, then a cache built from real logs."""

from __future__ import annotations

import json

import pytest

from ci_triage.accuracy import (
    ScoredFailure,
    Verdict,
    judge,
    score_corpus,
    seed_results,
    tally,
)
from ci_triage.classify import Classification
from ci_triage.models import FailureCategory as C

FLAKY_TEST = "tests.test_cart.CartTests.test_unique_skus"
SEED = "seed/s05-unique-skus-order"
RUNS = [(1, "unittest_verbose_pass.txt"), (2, "unittest_verbose_flaky_fail.txt")]


@pytest.mark.parametrize(
    ("expected", "predicted", "verdict"),
    [
        (C.REGRESSION, C.REGRESSION, Verdict.CORRECT),
        (C.REGRESSION, C.FLAKE, Verdict.WRONG),
        # Not an error: it leaves the failure for the model.
        (C.REGRESSION, C.UNTRIAGED, Verdict.ABSTAINED),
    ],
)
def test_judge(expected, predicted, verdict):
    assert judge(expected, predicted) is verdict


def _scored(seed, run, expected, wording, history, rule="r"):
    return ScoredFailure(
        seed_id=seed,
        run_id=run,
        job_id=run,
        test_id="t (m.C.t)",
        expected=expected,
        by_wording=Classification(category=wording, rule=rule),
        with_history=Classification(category=history, rule=rule),
    )


def test_a_seed_is_one_unit_however_many_failures_it_has():
    rows = [_scored("a", i, C.REGRESSION, C.REGRESSION, C.REGRESSION) for i in range(5)]
    rows.append(_scored("b", 9, C.ENVIRONMENT, C.UNTRIAGED, C.UNTRIAGED))
    results = seed_results(rows)

    assert [(r.seed_id, r.runs, r.failures) for r in results] == [("a", 5, 5), ("b", 1, 1)]
    assert tally(results, history=True) == {Verdict.CORRECT: 1, Verdict.ABSTAINED: 1}


def test_history_and_wording_are_scored_separately():
    [result] = seed_results([_scored("s", 1, C.FLAKE, C.REGRESSION, C.FLAKE)])
    assert result.wording_verdict is Verdict.WRONG
    assert result.history_verdict is Verdict.CORRECT


def _manifest(tmp_path, seeds):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"seeds": seeds}), encoding="utf-8")
    return path


def _seed(seed_id="s05-unique-skus-order", tests=(FLAKY_TEST,), category="flake"):
    return {"id": seed_id, "category": category, "failing_tests": list(tests)}


def test_scores_the_flake_from_real_logs(make_cache, tmp_path):
    data = make_cache(RUNS, branch=SEED)
    score = score_corpus(
        data, _manifest(tmp_path, [_seed(), _seed("s01-other", ["x.y"], "regression")])
    )

    [result] = seed_results(score.failures)
    # The wording says regression; only the passing run of the same commit says flake.
    assert result.by_wording.category is C.REGRESSION
    assert result.wording_verdict is Verdict.WRONG
    assert result.with_history.category is C.FLAKE
    assert result.history_verdict is Verdict.CORRECT
    assert score.extraction_mismatches == []
    assert score.unobserved == ["s01-other"]


def test_the_passing_run_is_not_scored(make_cache, tmp_path):
    score = score_corpus(make_cache(RUNS, branch=SEED), _manifest(tmp_path, [_seed()]))
    assert {f.run_id for f in score.failures} == {2}


def test_extraction_that_disagrees_with_the_manifest_is_reported(make_cache, tmp_path):
    manifest = _manifest(tmp_path, [_seed(tests=["tests.test_cart.CartTests.test_other"])])
    score = score_corpus(make_cache(RUNS, branch=SEED), manifest)
    assert score.extraction_mismatches == ["s05-unique-skus-order run 2"]


def test_branches_that_are_not_seeds_are_ignored(make_cache, tmp_path):
    score = score_corpus(make_cache(RUNS, branch="main"), _manifest(tmp_path, [_seed()]))
    assert score.failures == []
    assert score.unobserved == ["s05-unique-skus-order"]
