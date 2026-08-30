"""Core domain models.

These describe what we ingest from CI, independent of any particular provider.
Kept deliberately small until ingestion is real.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Conclusion(StrEnum):
    """Terminal state of a CI run."""

    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


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

    id: str
    repo: str
    workflow: str
    branch: str
    commit_sha: str
    conclusion: Conclusion
    started_at: datetime
    url: str | None = None

    @property
    def failed(self) -> bool:
        return self.conclusion is not Conclusion.SUCCESS


class Failure(BaseModel):
    """A single failing job or step within a run."""

    run_id: str
    job_name: str
    step_name: str | None = None
    log_excerpt: str = ""
    category: FailureCategory = FailureCategory.UNTRIAGED
    signature: str | None = Field(
        default=None,
        description="Normalized fingerprint used to group recurring failures.",
    )
