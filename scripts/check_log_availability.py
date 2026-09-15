"""Report what's actually retrievable from the cached runs.

Run this before the full log fetch. GitHub deletes Actions logs on the
repo's retention schedule (90 days by default), so a cache of the 100 most
recent *failed* runs can easily reach back past the cutoff. Knowing the
usable count first is the difference between a 20-minute fetch and finding
out at run 60 that the tail is empty.

Usage:
    python scripts/check_log_availability.py [--probe N]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ci_triage.logs import LogsExpired, build_client, fetch_job_log, fetch_jobs  # noqa: E402
from ci_triage.models import Run  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "raw" / "runs"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--probe",
        type=int,
        default=8,
        help="How many runs to actually hit the API for. 0 skips the probe.",
    )
    args = parser.parse_args()

    files = sorted(CACHE.glob("*.json"))
    if not files:
        print(f"No cached runs under {CACHE}", file=sys.stderr)
        return 1

    runs: list[Run] = []
    unparsed: list[tuple[str, str]] = []
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        try:
            runs.append(Run.from_payload(payload))
        except Exception as exc:  # noqa: BLE001 - report, don't abort the survey
            unparsed.append((path.name, str(exc).splitlines()[0]))

    print(f"cached runs:     {len(files)}")
    print(f"parsed:          {len(runs)}")
    if unparsed:
        print(f"failed to parse: {len(unparsed)}")
        for name, err in unparsed[:5]:
            print(f"    {name}: {err}")

    print("\nconclusions:")
    for value, count in Counter(r.conclusion.value for r in runs).most_common():
        print(f"    {value:<18} {count}")

    print("\nworkflows:")
    for value, count in Counter(r.workflow_name for r in runs).most_common(10):
        print(f"    {count:>4}  {value}")

    triageable = [r for r in runs if r.triageable]
    print(f"\ntriageable:      {len(triageable)}")

    if not triageable:
        return 0

    dated = sorted(triageable, key=lambda r: r.created_at)
    now = datetime.now(UTC)
    oldest, newest = dated[0], dated[-1]
    print(f"oldest:          {oldest.created_at:%Y-%m-%d}  ({(now - oldest.created_at).days}d ago)")
    print(f"newest:          {newest.created_at:%Y-%m-%d}  ({(now - newest.created_at).days}d ago)")

    within_90 = [r for r in dated if (now - r.created_at).days <= 90]
    print(f"within 90 days:  {len(within_90)} of {len(triageable)}")

    if args.probe <= 0:
        return 0

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("\nGITHUB_TOKEN not set; skipping live probe.", file=sys.stderr)
        return 0

    # Probe newest-first: if the recent end is already expired, nothing older
    # will work either and there's no point walking the whole list.
    sample = list(reversed(dated))[: args.probe]
    print(f"\nprobing {len(sample)} runs, newest first:")

    available = 0
    with build_client(token) as client:
        for run in sample:
            age = (now - run.created_at).days
            try:
                jobs = fetch_jobs(client, run.repo, run.id)
            except Exception as exc:  # noqa: BLE001
                print(f"    {run.id}  {age:>4}d  jobs call failed: {exc}")
                continue

            failed_jobs = [j for j in jobs if j.triageable]
            if not failed_jobs:
                print(f"    {run.id}  {age:>4}d  {len(jobs)} jobs, none failed")
                continue

            job = failed_jobs[0]
            try:
                text = fetch_job_log(client, run.repo, job.id)
            except LogsExpired as exc:
                print(f"    {run.id}  {age:>4}d  EXPIRED  ({exc})")
                continue

            available += 1
            print(
                f"    {run.id}  {age:>4}d  OK  {len(failed_jobs)}/{len(jobs)} jobs failed, "
                f"{len(text):>8} bytes, steps={job.failed_steps}"
            )

    print(f"\nlogs retrievable: {available} of {len(sample)} probed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
