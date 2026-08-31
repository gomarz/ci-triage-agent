from .models import Run


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
    print(run)
    return run