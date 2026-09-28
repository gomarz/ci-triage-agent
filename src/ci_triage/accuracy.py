"""Score the classifier against labelled failures.

The testbed's seeded branches are the labels: every failure in a run of
`seed/<id>` has the category `<id>` was seeded with. Each failure is classified
twice, by wording alone and with run history, so the score shows what history
adds instead of folding it into one number.

The classifier is allowed to abstain (UNTRIAGED), and an abstention is not a
wrong answer: a confident wrong category sends stage 4 down the wrong proposal
type, while UNTRIAGED leaves the failure for the model. So there are three
verdicts, and "accuracy" is reported as two numbers, how often it answers and
how often an answer is right.

The unit is the seed, not the run or the failure. One cause can fail in many
runs (s05 in five) and many tests (s04 in six); counting those would let one
easy cause dominate, the same trap as reporting classification by occurrence.

Caveat that no code here can remove: the seeds were written by someone who had
read the classifier's rules. That makes the score a check that the pipeline
works end to end on known cases, not an estimate of accuracy on failures nobody
designed.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel

from ci_triage.classify import Classification, classify
from ci_triage.flake import find_flakes, load_observations
from ci_triage.jobs import parse_job
from ci_triage.logs import read_log
from ci_triage.models import FailureCategory

SEED_BRANCH_PREFIX = "seed/"


class Verdict(StrEnum):
    CORRECT = "correct"
    WRONG = "wrong"
    #: UNTRIAGED. Not an error: it hands the failure to the model.
    ABSTAINED = "abstained"


def judge(expected: FailureCategory, predicted: FailureCategory) -> Verdict:
    if predicted is FailureCategory.UNTRIAGED:
        return Verdict.ABSTAINED
    return Verdict.CORRECT if predicted is expected else Verdict.WRONG


class ScoredFailure(BaseModel):
    seed_id: str
    run_id: int
    job_id: int
    test_id: str
    expected: FailureCategory
    by_wording: Classification
    with_history: Classification


class SeedResult(BaseModel):
    seed_id: str
    expected: FailureCategory
    runs: int
    failures: int
    #: The most common answer over this seed's failures, per method.
    by_wording: Classification
    with_history: Classification

    @property
    def wording_verdict(self) -> Verdict:
        return judge(self.expected, self.by_wording.category)

    @property
    def history_verdict(self) -> Verdict:
        return judge(self.expected, self.with_history.category)


class CorpusScore(BaseModel):
    failures: list[ScoredFailure]
    #: Seeds in the manifest with no cached failing run to score.
    unobserved: list[str]
    #: Runs whose extracted failing tests differ from the manifest's list, so a
    #: wrong category is not blamed on the classifier when extraction was at fault.
    extraction_mismatches: list[str]


def _modal(items: list[Classification]) -> Classification:
    counts = Counter((c.category, c.rule) for c in items)
    (category, rule), _ = counts.most_common(1)[0]
    return Classification(category=category, rule=rule)


def seed_results(failures: list[ScoredFailure]) -> list[SeedResult]:
    by_seed: dict[str, list[ScoredFailure]] = defaultdict(list)
    for f in failures:
        by_seed[f.seed_id].append(f)
    return [
        SeedResult(
            seed_id=seed_id,
            expected=rows[0].expected,
            runs=len({r.run_id for r in rows}),
            failures=len(rows),
            by_wording=_modal([r.by_wording for r in rows]),
            with_history=_modal([r.with_history for r in rows]),
        )
        for seed_id, rows in sorted(by_seed.items())
    ]


def tally(results: list[SeedResult], *, history: bool) -> Counter[Verdict]:
    return Counter(r.history_verdict if history else r.wording_verdict for r in results)


def _dotted(test_id: str) -> str:
    """The module.Class.test path unittest prints in parentheses after the name."""
    return test_id[test_id.rindex("(") + 1 : -1] if "(" in test_id else test_id


def _matches(extracted: set[str], expected: set[str]) -> bool:
    """A manifest id is the dotted path, or the module for an import failure."""
    dotted = {_dotted(t) for t in extracted}
    wanted = {e if e in dotted else f"unittest.loader._FailedTest.{e}" for e in expected}
    return dotted == wanted


def score_corpus(data_dir: Path, manifest: Path) -> CorpusScore:
    """Classify every failure on a seed branch and compare with the manifest."""
    seeds = {s["id"]: s for s in json.loads(manifest.read_text(encoding="utf-8"))["seeds"]}
    observations = load_observations(data_dir)
    flaky = {f.key for f in find_flakes([o for o in observations if o.outcomes])}

    failures: list[ScoredFailure] = []
    mismatches: list[str] = []
    for obs in observations:
        if not obs.branch.startswith(SEED_BRANCH_PREFIX):
            continue
        seed = seeds.get(obs.branch.removeprefix(SEED_BRANCH_PREFIX))
        if seed is None:
            continue
        log = read_log(data_dir / "raw" / "logs" / str(obs.run_id) / f"{obs.job_id}.txt")
        found = parse_job(log).failures
        if not found:
            continue  # a passing run of a seed branch: nothing to classify

        if not _matches({f.test_id for f in found}, set(seed["failing_tests"])):
            mismatches.append(f"{seed['id']} run {obs.run_id}")
        expected = FailureCategory(seed["category"])
        for failure in found:
            is_flaky = (obs.commit_sha, obs.workflow_id, obs.job_name, failure.test_id) in flaky
            failures.append(
                ScoredFailure(
                    seed_id=seed["id"],
                    run_id=obs.run_id,
                    job_id=obs.job_id,
                    test_id=failure.test_id,
                    expected=expected,
                    by_wording=classify(failure),
                    with_history=classify(failure, flaky=is_flaky),
                )
            )

    observed = {f.seed_id for f in failures}
    return CorpusScore(
        failures=failures,
        unobserved=sorted(seeds.keys() - observed),
        extraction_mismatches=mismatches,
    )
