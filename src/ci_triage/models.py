"""Core domain models.

These describe what we ingest from CI, independent of any particular provider.
Provider-specific parsing lives in the classmethods, so the rest of the
codebase never touches a raw payload dict.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Conclusion(StrEnum):
    """Terminal state of a CI run or job.

    Covers every value the GitHub Actions API returns. Anything missing here
    becomes a ValidationError at ingest time, which is why the list is
    exhaustive rather than just the interesting cases.
    """

    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    SKIPPED = "skipped"
    NEUTRAL = "neutral"
    STALE = "stale"
    ACTION_REQUIRED = "action_required"
    STARTUP_FAILURE = "startup_failure"


class Outcome(StrEnum):
    """What one test did in one job, as the runner printed it."""

    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"
    SKIP = "skip"


#: Conclusions that represent something worth triaging. A cancelled run was
#: killed by a human, a skipped run never executed, and a startup_failure
#: never produced job logs, so none of them carry a diagnosable signal.
TRIAGEABLE: frozenset[Conclusion] = frozenset({Conclusion.FAILURE, Conclusion.TIMED_OUT})


class FailureCategory(StrEnum):
    """What kind of problem a failure turned out to be.

    UNTRIAGED is the default; everything else is set by classification.
    """

    UNTRIAGED = "untriaged"
    REGRESSION = "regression"
    FLAKE = "flake"
    ENVIRONMENT = "environment"
    INFRASTRUCTURE = "infrastructure"


class Run(BaseModel):
    """One CI workflow run."""

    id: int
    repo: str
    head_repo: str
    workflow_id: int
    workflow_name: str
    event: str
    status: str
    jobs_url: str
    logs_url: str
    branch: str
    run_attempt: int
    previous_attempt_url: str | None = None
    commit_sha: str
    conclusion: Conclusion
    created_at: datetime
    api_url: str | None = None

    @classmethod
    def from_payload(cls, payload: dict) -> Run:
        """Build a Run from a GitHub Actions workflow-run payload.

        Forks are the reason head_repo is separate from repo: a
        pull_request_target run reports the upstream repo in `repository`
        and the fork in `head_repository`. head_repository is absent on
        some older payloads, so it falls back to repository.
        """
        repo = payload["repository"]["full_name"]
        head_repo = (payload.get("head_repository") or {}).get("full_name", repo)

        return cls(
            id=payload["id"],
            repo=repo,
            head_repo=head_repo,
            workflow_id=payload["workflow_id"],
            workflow_name=payload["name"],
            event=payload["event"],
            status=payload["status"],
            jobs_url=payload["jobs_url"],
            logs_url=payload["logs_url"],
            branch=payload["head_branch"],
            run_attempt=payload["run_attempt"],
            previous_attempt_url=payload.get("previous_attempt_url"),
            commit_sha=payload["head_sha"],
            conclusion=payload["conclusion"],
            created_at=payload["created_at"],
            api_url=payload.get("url"),
        )

    @property
    def triageable(self) -> bool:
        """Whether this run failed in a way that produces a diagnosable signal."""
        return self.conclusion in TRIAGEABLE


class Job(BaseModel):
    """One job within a run. Logs are fetched per job, not per run."""

    id: int
    run_id: int
    name: str
    conclusion: Conclusion | None = None
    #: Names of the steps that failed, in execution order.
    failed_steps: list[str] = Field(default_factory=list)

    @classmethod
    def from_payload(cls, payload: dict) -> Job:
        """Build a Job from a GitHub Actions job payload.

        A job with no steps array (queued, or cancelled before start) yields
        an empty failed_steps rather than raising.
        """
        steps = payload.get("steps") or []
        failed = [
            step["name"] for step in steps if step.get("conclusion") in ("failure", "timed_out")
        ]
        return cls(
            id=payload["id"],
            run_id=payload["run_id"],
            name=payload["name"],
            conclusion=payload.get("conclusion"),
            failed_steps=failed,
        )

    @property
    def triageable(self) -> bool:
        return self.conclusion in TRIAGEABLE


class Failure(BaseModel):
    """A single failing job or step within a run."""

    run_id: int
    job_id: int
    job_name: str
    step_name: str | None = None
    log_excerpt: str = ""
    category: FailureCategory = FailureCategory.UNTRIAGED
    signature: str | None = Field(
        default=None,
        description="Normalized fingerprint used to group recurring failures.",
    )
