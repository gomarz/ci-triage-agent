from datetime import UTC, datetime

from ci_triage.models import Conclusion, Failure, FailureCategory, Run


# The helper exists so each test doesn't repeat sixteen lines
# but it also means every model change breaks every test using it.
# That's the cost of shared fixtures, and it's usually worth paying.
# The alternative is that model drift goes unnoticed, which is worse.
def _run(conclusion: Conclusion) -> Run:
    now = datetime.now(UTC)
    return Run(
        id=1,
        repo="gomarz/SS-armaa",
        head_repo="gomarz/SS-armaa",
        workflow_id=1,
        workflow_name="build",
        event="push",
        status="completed",
        jobs_url="https://api.github.com/x/jobs",
        logs_url="https://api.github.com/x/logs",
        branch="main",
        run_attempt=1,
        commit_sha="abc123",
        conclusion=conclusion,
        created_at=now,
        run_started_at=now,
    )


def test_successful_run_is_not_failed():
    assert _run(Conclusion.SUCCESS).triageable is False


def test_triageable_conclusions():
    """Cancelled and skipped runs are not failures worth triaging: a human
    killed the first and the second never executed."""
    for conclusion in (Conclusion.FAILURE, Conclusion.TIMED_OUT):
        assert _run(conclusion).triageable is True
    for conclusion in (Conclusion.SUCCESS, Conclusion.CANCELLED, Conclusion.SKIPPED):
        assert _run(conclusion).triageable is False


def test_failures_start_untriaged():
    failure = Failure(run_id=1, job_id=2, job_name="test")
    assert failure.category is FailureCategory.UNTRIAGED
    assert failure.signature is None
