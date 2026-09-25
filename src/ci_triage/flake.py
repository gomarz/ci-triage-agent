"""Find flaky tests: the same test passing and failing on one commit.

A flake is not a property of a failure message. "AssertionError: Lists differ"
is a regression when the code changed and a flake when it did not, and nothing
in the log says which. The only evidence is history: on one commit, in one
workflow and job, the test failed in one run and passed in another. Nothing
about the code differed between those runs, so the difference was the run.

Observations are grouped by (commit, workflow, job name). The job name is part
of the key because a matrix has one job per cell, and a test that fails only on
Windows is not flaky for passing on Linux. Comparing across workflows is what
the earlier corpus could not avoid: its commits with several runs were different
workflows, which is why nothing there could be called a flake.

Limits, all of which make a flake go unseen rather than be invented:

* Only verbose unittest prints a result for every test, so only that shape
  yields outcomes. Robot logs are not read here.
* The runs listing keeps each run's latest attempt (see github.fetch_runs), so
  a failure that was re-run and passed is cached as a pass and never compared.
* A test needs to appear in at least one passing and one failing job of a group.
  A test that always fails on a commit is not flaky on it, and one commit with
  a single run cannot show anything.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from pydantic import BaseModel, Field

from ci_triage.logs import diagnostic_body, read_log
from ci_triage.models import Job, Outcome, Run
from ci_triage.unittest_extract import extract_unittest_outcomes

#: The rule name classification reports for a failure that history shows is flaky.
FLAKE_RULE = "same-commit-pass-and-fail"

_FAILED = frozenset({Outcome.FAIL, Outcome.ERROR})


class JobObservation(BaseModel):
    """What every test did in one job of one run."""

    run_id: int
    job_id: int
    job_name: str
    commit_sha: str
    workflow_id: int
    run_attempt: int = 1
    outcomes: dict[str, Outcome] = Field(default_factory=dict)


class FlakeFinding(BaseModel):
    """One test that both passed and failed on one commit."""

    commit_sha: str
    workflow_id: int
    job_name: str
    test_id: str
    passed_in: list[int]
    failed_in: list[int]

    @property
    def failure_rate(self) -> float:
        return len(self.failed_in) / (len(self.passed_in) + len(self.failed_in))

    @property
    def key(self) -> tuple[str, int, str, str]:
        return (self.commit_sha, self.workflow_id, self.job_name, self.test_id)


def find_flakes(observations: list[JobObservation]) -> list[FlakeFinding]:
    """Tests that passed in one job and failed in another of the same group.

    Most-failing first, so the flakes most likely to be real (many failures
    against few passes) are listed above a single fluke.
    """
    groups: dict[tuple[str, int, str], list[JobObservation]] = defaultdict(list)
    for obs in observations:
        groups[(obs.commit_sha, obs.workflow_id, obs.job_name)].append(obs)

    findings: list[FlakeFinding] = []
    for (commit, workflow, job_name), jobs in groups.items():
        if len(jobs) < 2:
            continue
        passed: dict[str, list[int]] = defaultdict(list)
        failed: dict[str, list[int]] = defaultdict(list)
        for obs in jobs:
            for test_id, outcome in obs.outcomes.items():
                if outcome is Outcome.PASS:
                    passed[test_id].append(obs.job_id)
                elif outcome in _FAILED:
                    failed[test_id].append(obs.job_id)
        for test_id in sorted(passed.keys() & failed.keys()):
            findings.append(
                FlakeFinding(
                    commit_sha=commit,
                    workflow_id=workflow,
                    job_name=job_name,
                    test_id=test_id,
                    passed_in=sorted(passed[test_id]),
                    failed_in=sorted(failed[test_id]),
                )
            )
    return sorted(findings, key=lambda f: (-len(f.failed_in), f.test_id))


def load_observations(data_dir: Path) -> list[JobObservation]:
    """Every cached job that has a log, with the outcomes its log shows.

    Jobs whose log holds no per-test result lines come back with empty outcomes,
    not dropped, so a caller can report how much of the cache it could not use.
    """
    raw = data_dir / "raw"
    observations: list[JobObservation] = []
    for run_path in sorted((raw / "runs").glob("*.json")):
        run = Run.from_payload(json.loads(run_path.read_text(encoding="utf-8")))
        manifest = raw / "jobs" / f"{run.id}.json"
        if not manifest.exists():
            continue
        for job in map(Job.model_validate, json.loads(manifest.read_text(encoding="utf-8"))):
            log = raw / "logs" / str(run.id) / f"{job.id}.txt"
            if not log.exists():
                continue
            observations.append(
                JobObservation(
                    run_id=run.id,
                    job_id=job.id,
                    job_name=job.name,
                    commit_sha=run.commit_sha,
                    workflow_id=run.workflow_id,
                    run_attempt=run.run_attempt,
                    outcomes=extract_unittest_outcomes(diagnostic_body(read_log(log))),
                )
            )
    return observations
