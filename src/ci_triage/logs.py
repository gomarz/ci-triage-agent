"""Job and log ingestion for GitHub Actions.

Additive to github.py, which handles workflow-run metadata. The split is
deliberate: run metadata is one cheap paginated call, while logs are one
call per job against a redirect-backed blob store with its own failure
modes (expiry, rate limits, large bodies).

On locating failures: the ##[group] labels in a raw job log are the
*commands* the runner executed, not the step names the API reports, so
they cannot be joined against Job.failed_steps. Post-job cleanup also runs
after the last group opens and gets absorbed into it, which makes "last
group" teardown noise rather than the failure. ##[error] markers are the
one anchor the runner emits at the actual point of failure.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import httpx

from ci_triage.models import Job

logger = logging.getLogger(__name__)

#: GitHub prefixes every log line with an ISO8601 timestamp to 7 decimal places.
_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z ?", re.MULTILINE)

#: Actions workflow commands that delimit step output in raw job logs.
_GROUP_START = re.compile(r"^##\[group\](.*)$", re.MULTILINE)

#: The runner's failure marker.
_ERROR = re.compile(r"^##\[error\](.*)$", re.MULTILINE)

#: Everything from here on is teardown, not failure.
_POST_JOB = re.compile(r"^Post job cleanup\.?$", re.MULTILINE)


class LogsExpired(Exception):
    """Raised when GitHub has already deleted the logs for a job."""


def fetch_jobs(client: httpx.Client, repo: str, run_id: int) -> list[Job]:
    """Fetch every job for a run, following pagination."""
    jobs: list[Job] = []
    page = 1

    while True:
        response = client.get(
            f"/repos/{repo}/actions/runs/{run_id}/jobs",
            params={"per_page": 100, "page": page, "filter": "latest"},
        )
        response.raise_for_status()
        body = response.json()

        batch = body.get("jobs", [])
        jobs.extend(Job.from_payload(job) for job in batch)

        if len(jobs) >= body.get("total_count", 0) or not batch:
            break
        page += 1

    return jobs


def fetch_job_log(client: httpx.Client, repo: str, job_id: int) -> str:
    """Download the raw log text for one job.

    The endpoint answers 302 with a signed blob URL, so the client must be
    built with follow_redirects=True. Expired logs answer 410.
    """
    response = client.get(f"/repos/{repo}/actions/jobs/{job_id}/logs")

    if response.status_code in (404, 410):
        raise LogsExpired(f"job {job_id}: logs unavailable ({response.status_code})")

    response.raise_for_status()
    return response.text


def cache_log(root: Path, run_id: int, job_id: int, text: str) -> Path:
    """Persist raw log text, mirroring the layout of data/raw/runs/.

    newline="" is load-bearing on Windows. Logs from Windows runners already
    contain CRLF, and the default translating writer turns those into CRLFLF,
    which doubles every line and corrupts any line-based analysis downstream.
    """
    path = root / "data" / "raw" / "logs" / str(run_id) / f"{job_id}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    return path


def read_log(path: Path) -> str:
    """Read a cached log, normalizing line endings.

    Repairs CRLFLF from caches written before cache_log set newline="",
    so existing data doesn't need re-fetching.
    """
    # newline="" on the reader, not read_text(newline=...), which is 3.13+
    # and would pass locally while failing on the 3.11 CI matrix.
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        raw = handle.read()
    return raw.replace("\r\r\n", "\n").replace("\r\n", "\n").replace("\r", "\n")


def strip_timestamps(text: str) -> str:
    """Remove the per-line ISO8601 prefix GitHub adds to raw logs."""
    return _TS.sub("", text)


def group_inventory(text: str) -> list[tuple[str, int]]:
    """List the ##[group] labels in order with their line counts.

    Diagnostic: shows what the runner actually executed, which is how you
    find the step that matters when names don't line up.
    """
    body = strip_timestamps(text)
    matches = list(_GROUP_START.finditer(body))

    inventory = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        chunk = body[match.end() : end]
        inventory.append((match.group(1).strip(), chunk.count("\n")))
    return inventory


def failure_regions(
    text: str,
    before: int = 40,
    after: int = 5,
    include_teardown: bool = False,
) -> list[tuple[str, list[str]]]:
    """Extract the log lines around each ##[error] marker.

    Returns (marker_text, lines) per error. Overlapping windows are merged
    so a cluster of errors at the end of a suite yields one region rather
    than twenty near-identical ones.

    Teardown is dropped by default: everything after "Post job cleanup" is
    the runner unwinding, and its errors are consequences rather than causes.
    """
    body = strip_timestamps(text)

    if not include_teardown:
        cut = _POST_JOB.search(body)
        if cut:
            body = body[: cut.start()]

    lines = body.split("\n")
    error_idx = [i for i, line in enumerate(lines) if line.startswith("##[error]")]
    if not error_idx:
        return []

    # Merge windows that touch, keeping the first marker as the label.
    windows: list[tuple[int, int, str]] = []
    for idx in error_idx:
        start, end = max(0, idx - before), min(len(lines), idx + after + 1)
        if windows and start <= windows[-1][1]:
            prev_start, _, label = windows[-1]
            windows[-1] = (prev_start, end, label)
        else:
            windows.append((start, end, lines[idx][len("##[error]") :].strip()))

    return [(label, lines[start:end]) for start, end, label in windows]


def diagnostic_body(text: str) -> str:
    """Everything the job emitted before teardown began.

    Used instead of a fixed window around ##[error]: Robot's FAIL: blocks are
    self-delimiting, and a run where thousands of tests fail spans far more
    lines than any window worth choosing. Clipping it silently undercounts,
    which looks like clean data rather than a bug.
    """
    body = strip_timestamps(text)
    cut = _POST_JOB.search(body)
    return body[: cut.start()] if cut else body


def has_error_marker(text: str) -> bool:
    """Whether the runner flagged a failure at all."""
    return bool(_ERROR.search(strip_timestamps(text)))
