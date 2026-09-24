"""Fetch and cache logs for the failing jobs of every cached run.

Resumable by design: anything already on disk is skipped, so an interrupted
run costs nothing to restart. Expired logs are recorded rather than retried,
since GitHub never brings them back.

Layout written:
    data/raw/jobs/{run_id}.json      job manifest (id, name, conclusion, failed steps)
    data/raw/logs/{run_id}/{job_id}.txt   raw log text, timestamps intact

Usage:
    python scripts/fetch_logs.py [--limit N] [--all-jobs] [--all-runs]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ci_triage.config import load_settings  # noqa: E402
from ci_triage.logs import LogsExpired, build_client, fetch_job_log, fetch_jobs  # noqa: E402
from ci_triage.models import Run  # noqa: E402

RAW = load_settings().data_dir / "raw"
RUNS = RAW / "runs"
JOBS = RAW / "jobs"
LOGS = RAW / "logs"


def load_runs() -> list[Run]:
    runs = []
    for path in sorted(RUNS.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        try:
            runs.append(Run.from_payload(payload))
        except Exception as exc:  # noqa: BLE001
            print(f"  skip {path.name}: {exc}", file=sys.stderr)
    # Newest first: the recent end is the part guaranteed to still have logs.
    return sorted(runs, key=lambda r: r.created_at, reverse=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="Stop after N runs. 0 = all.")
    parser.add_argument(
        "--all-jobs",
        action="store_true",
        help="Fetch logs for every job, not just the failing ones.",
    )
    parser.add_argument(
        "--all-runs",
        action="store_true",
        help="Include runs that did not fail. Their jobs are fetched whole: there are no "
        "failing jobs to filter to, and the passing test lines are the point.",
    )
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("GITHUB_TOKEN not set", file=sys.stderr)
        return 1

    runs = [r for r in load_runs() if args.all_runs or r.triageable]
    if args.limit:
        runs = runs[: args.limit]
    print(f"{len(runs)} runs to process\n")

    fetched = skipped = expired = errored = 0
    total_bytes = 0
    started = time.monotonic()

    with build_client(token) as client:
        for i, run in enumerate(runs, 1):
            manifest = JOBS / f"{run.id}.json"

            if manifest.exists():
                jobs_data = json.loads(manifest.read_text(encoding="utf-8"))
            else:
                try:
                    jobs = fetch_jobs(client, run.repo, run.id)
                except httpx.HTTPError as exc:
                    print(f"[{i}/{len(runs)}] {run.id}  jobs call failed: {exc}")
                    errored += 1
                    continue
                jobs_data = [j.model_dump() for j in jobs]
                manifest.parent.mkdir(parents=True, exist_ok=True)
                manifest.write_text(json.dumps(jobs_data, indent=2), encoding="utf-8")

            everything = args.all_jobs or not run.triageable
            wanted = [
                j for j in jobs_data if everything or j["conclusion"] in ("failure", "timed_out")
            ]
            if not wanted:
                print(f"[{i}/{len(runs)}] {run.id}  no jobs to fetch")
                continue

            for job in wanted:
                path = LOGS / str(run.id) / f"{job['id']}.txt"
                if path.exists():
                    skipped += 1
                    continue

                try:
                    text = fetch_job_log(client, run.repo, job["id"])
                except LogsExpired:
                    # Record the gap so a later pass doesn't retry it forever.
                    path.parent.mkdir(parents=True, exist_ok=True)
                    (path.parent / f"{job['id']}.expired").touch()
                    expired += 1
                    print(f"[{i}/{len(runs)}] {run.id}  {job['name'][:40]:<40} EXPIRED")
                    continue
                except httpx.HTTPError as exc:
                    errored += 1
                    print(f"[{i}/{len(runs)}] {run.id}  {job['name'][:40]:<40} ERROR {exc}")
                    continue

                path.parent.mkdir(parents=True, exist_ok=True)
                # newline="" so CRLF from Windows runners isn't doubled to CRLFLF
                with path.open("w", encoding="utf-8", newline="") as handle:
                    handle.write(text)
                fetched += 1
                total_bytes += len(text)
                print(
                    f"[{i}/{len(runs)}] {run.id}  {job['name'][:40]:<40} "
                    f"{len(text):>8} B  steps={job['failed_steps']}"
                )

    elapsed = time.monotonic() - started
    print(
        f"\nfetched {fetched}, skipped {skipped}, expired {expired}, errored {errored}"
        f"\n{total_bytes / 1_048_576:.1f} MB in {elapsed:.0f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
