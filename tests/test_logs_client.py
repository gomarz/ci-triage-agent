import httpx
import pytest

from ci_triage.logs import LogsExpired, build_client, fetch_job_log

BLOB = "https://blob.example.net/signed/log.txt?sig=abc"


def _client(handler):
    return build_client("tok", transport=httpx.MockTransport(handler))


def test_log_endpoint_redirect_is_followed_without_the_token():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "api.github.com":
            return httpx.Response(302, headers={"Location": BLOB})
        return httpx.Response(200, text="line one\nline two\n")

    text = fetch_job_log(_client(handler), "o/r", 42)

    assert text == "line one\nline two\n"
    assert seen[0].headers["Authorization"] == "Bearer tok"
    assert "Authorization" not in seen[1].headers


@pytest.mark.parametrize("status", [404, 410])
def test_missing_or_expired_logs_raise(status):
    with pytest.raises(LogsExpired):
        fetch_job_log(_client(lambda request: httpx.Response(status)), "o/r", 42)
