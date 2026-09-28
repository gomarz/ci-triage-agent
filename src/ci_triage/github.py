import json
from pathlib import Path

import httpx

from .config import load_settings
from .models import Run

PAGE_SIZE = 100


def cache_payload(payload: dict, raw_dir: Path | None = None) -> Path:
    raw_dir = raw_dir or load_settings().data_dir / "raw" / "runs"
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{payload['id']}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def parse_run(payload: dict) -> Run:
    run = Run(
        id=payload["id"],
        repo=payload["repository"]["full_name"],
        head_repo=payload["head_repository"]["full_name"],
        workflow_id=payload["workflow_id"],
        workflow_name=payload["name"],
        event=payload["event"],
        status=payload["status"],
        jobs_url=payload["jobs_url"],
        logs_url=payload["logs_url"],
        branch=payload["head_branch"],
        commit_sha=payload["head_sha"],
        run_attempt=payload["run_attempt"],
        previous_attempt_url=payload["previous_attempt_url"],
        conclusion=payload["conclusion"],
        created_at=payload["created_at"],
        run_started_at=payload["run_started_at"],
        api_url=payload["url"],
    )
    return run


def fetch_runs(
    repo: str, token: str, *, include_passing: bool = False, pages: int = 1
) -> list[dict]:
    """Workflow runs for `repo`, newest first, up to `pages` pages of 100.

    Failures only by default, which is what triage needs. Flake detection needs
    the same commit to have both failed and passed, so include_passing asks for
    every completed run instead ("completed" is the status filter for that;
    in-progress runs have no conclusion and would not parse).

    The endpoint returns each run's latest attempt only. Re-running a failed run
    replaces its failure with the new result in this listing, and the earlier
    attempt is reachable only through /runs/{id}/attempts/{n}. Runs that were
    re-run therefore look like clean passes here.
    """
    status = "completed" if include_passing else "failure"
    payloads: list[dict] = []
    for page in range(1, pages + 1):
        response = httpx.get(
            f"https://api.github.com/repos/{repo}/actions/runs",
            params={"status": status, "per_page": PAGE_SIZE, "page": page},
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        batch = response.json()["workflow_runs"]
        payloads.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
    return payloads
