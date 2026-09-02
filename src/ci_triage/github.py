import json
from pathlib import Path

import httpx

from .models import Run

RAW_DIR = Path("data/raw/runs")


def cache_payload(payload: dict, raw_dir: Path = RAW_DIR) -> Path:
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


def fetch_failed_runs(repo: str, token: str) -> list[dict]:
    response = httpx.get(
        f"https://api.github.com/repos/{repo}/actions/runs",
        params={"status": "failure", "per_page": 100},
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    return response.json()["workflow_runs"]
