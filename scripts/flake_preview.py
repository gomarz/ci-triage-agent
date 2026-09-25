"""List flaky tests: passed and failed on one commit, in one workflow and job.

Needs a corpus with several runs of the same commit and verbose unittest output
(the testbed, not the Robot corpus). See ci_triage.flake for what it cannot see.

    DATA_DIR=data/testbed python scripts/flake_preview.py
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ci_triage.classify import classify, classify_root  # noqa: E402
from ci_triage.config import load_settings  # noqa: E402
from ci_triage.flake import find_flakes, load_observations  # noqa: E402
from ci_triage.jobs import parse_job  # noqa: E402
from ci_triage.logs import read_log  # noqa: E402

RULE = "=" * 78


def main() -> int:
    data_dir = load_settings().data_dir
    observations = load_observations(data_dir)
    if not observations:
        print(f"No cached jobs with logs under {data_dir}", file=sys.stderr)
        return 1

    usable = [o for o in observations if o.outcomes]
    groups: dict[tuple, list] = defaultdict(list)
    for obs in usable:
        groups[(obs.commit_sha, obs.workflow_id, obs.job_name)].append(obs)
    comparable = {k: v for k, v in groups.items() if len(v) >= 2}
    findings = find_flakes(usable)

    print(RULE)
    print(f"jobs with logs: {len(observations)}   with per-test results: {len(usable)}")
    print(f"commit/workflow/job groups: {len(groups)}   with 2+ jobs to compare: {len(comparable)}")
    print(f"flaky tests: {len(findings)}")
    print(RULE)

    for finding in findings:
        commit = finding.commit_sha[:7]
        runs = len(finding.passed_in) + len(finding.failed_in)
        print(f"\n{finding.test_id}")
        print(
            f"  commit {commit}   job {finding.job_name!r}   "
            f"failed {len(finding.failed_in)} of {runs} ({finding.failure_rate:.0%})"
        )

        # What the wording alone would have said, for the first failing job.
        failed_obs = next(o for o in usable if o.job_id == finding.failed_in[0])
        log_path = data_dir / "raw" / "logs" / str(failed_obs.run_id) / f"{failed_obs.job_id}.txt"
        log = read_log(log_path)
        failure = next((f for f in parse_job(log).failures if f.test_id == finding.test_id), None)
        if failure is None:
            continue
        without, with_history = classify_root(failure.root), classify(failure, flaky=True)
        print(f"  root: {failure.root[:90]}")
        print(f"  by wording alone: {without.category.value} ({without.rule})")
        print(f"  with history:     {with_history.category.value} ({with_history.rule})")

    flaky_groups = {(f.commit_sha, f.workflow_id, f.job_name) for f in findings}
    steady = len(comparable.keys() - flaky_groups)
    print(f"\ncomparable groups where no test changed outcome: {steady}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
