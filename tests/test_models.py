from datetime import UTC, datetime

from ci_triage.models import Conclusion, Failure, FailureCategory, Run


def _run(conclusion: Conclusion) -> Run:
    return Run(
        id="1",
        repo="gomarz/SS-armaa",
        workflow="build",
        branch="main",
        commit_sha="abc123",
        conclusion=conclusion,
        started_at=datetime.now(UTC),
    )


def test_successful_run_is_not_failed():
    assert _run(Conclusion.SUCCESS).failed is False


def test_non_success_conclusions_count_as_failed():
    for conclusion in (Conclusion.FAILURE, Conclusion.CANCELLED, Conclusion.TIMED_OUT):
        assert _run(conclusion).failed is True


def test_failures_start_untriaged():
    failure = Failure(run_id="1", job_name="test")
    assert failure.category is FailureCategory.UNTRIAGED
    assert failure.signature is None
