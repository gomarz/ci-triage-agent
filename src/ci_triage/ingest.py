from .config import load_settings
from .github import cache_payload, fetch_failed_runs, parse_run


def main() -> None:
    settings = load_settings()
    if not settings.github_token:
        raise SystemExit("GITHUB_TOKEN is not set. Copy .env.example to .env and fill it in.")

    payloads = fetch_failed_runs(settings.target_repo, settings.github_token)
    for payload in payloads:
        cache_payload(payload)

    runs = [parse_run(p) for p in payloads]
    print(f"Fetched {len(runs)} failed runs from {settings.target_repo}")


if __name__ == "__main__":
    main()
