"""The failure report an agent is handed: what stages 1-3 made of a failing CI run.

This is the project's loop made literal. The log is parsed (stage 1), its failures are
grouped by root cause (stage 2) and each root is given a category, with run history
deciding flakes (stage 3). Stage 4 gets that, not the raw log and not the manifest: no
seed note, expected fix location or cheat list reaches it, because those are the answers.
The category is the classifier's guess and is labelled as one; where it abstains the
report says so instead of inventing one.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from ci_triage.classify import classify
from ci_triage.extract import TestFailure
from ci_triage.flake import JobObservation, find_flakes, load_observations
from ci_triage.jobs import parse_job
from ci_triage.logs import read_log

MAX_ROOTS = 5
MAX_TESTS = 8
EXCERPT = 1500


def failing_observation(observations: list[JobObservation], branch: str) -> JobObservation | None:
    """A failed job on `branch`: the newest one that has a log and failed tests."""
    failed = [o for o in observations if o.branch == branch and _failed(o)]
    return max(failed, key=lambda o: o.run_id, default=None)


def _failed(obs: JobObservation) -> bool:
    return any(outcome.value in ("fail", "error") for outcome in obs.outcomes.values())


def build_report(
    data_dir: Path, branch: str, *, observations: list[JobObservation] | None = None
) -> str:
    """Report for the newest failing run on `branch` in the cache under `data_dir`."""
    observations = observations if observations is not None else load_observations(data_dir)
    obs = failing_observation(observations, branch)
    if obs is None:
        raise LookupError(f"no failing run of {branch!r} in {data_dir}")

    log = read_log(data_dir / "raw" / "logs" / str(obs.run_id) / f"{obs.job_id}.txt")
    parsed = parse_job(log)
    flaky = {f.key: f for f in find_flakes([o for o in observations if o.outcomes])}

    by_root: dict[str, list[TestFailure]] = defaultdict(list)
    for failure in parsed.failures:
        by_root[failure.root_sig].append(failure)

    lines = [
        f"CI failed on branch {branch} (job {obs.job_name!r}).",
        f"{len(parsed.failures)} failing test(s), {len(by_root)} distinct root cause(s).",
    ]
    ranked = sorted(by_root.values(), key=lambda group: -len(group))
    for number, group in enumerate(ranked[:MAX_ROOTS], 1):
        head = group[0]
        finding = flaky.get((obs.commit_sha, obs.workflow_id, obs.job_name, head.test_id))
        verdict = classify(head, flaky=finding is not None)
        lines += [
            "",
            f"[{number}] {head.root}",
            f"    triage guess: {verdict.category.value} (rule: {verdict.rule}); "
            "an automatic classification, and it can be wrong",
        ]
        if finding is not None:
            total = len(finding.passed_in) + len(finding.failed_in)
            lines.append(
                f"    history: this test failed in {len(finding.failed_in)} of {total} runs "
                "of this same commit and passed in the rest"
            )
        lines.append(f"    {len(group)} test(s):")
        lines += [f"      {f.test_id}" for f in group[:MAX_TESTS]]
        if len(group) > MAX_TESTS:
            lines.append(f"      ... and {len(group) - MAX_TESTS} more")
        lines += ["    first failure:"] + [
            f"      {line}" for line in head.message[:EXCERPT].splitlines()
        ]
    if len(ranked) > MAX_ROOTS:
        lines.append(f"\n... and {len(ranked) - MAX_ROOTS} more root cause(s)")
    return "\n".join(lines)
