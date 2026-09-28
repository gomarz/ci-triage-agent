import argparse

from .config import load_settings
from .github import cache_payload, fetch_runs, parse_run


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Fetch workflow-run metadata into the cache.")
    parser.add_argument("--repo", help="owner/name. Default: TARGET_REPO.")
    parser.add_argument(
        "--include-passing",
        action="store_true",
        help="Cache every completed run, not just failures. Flake detection needs the passes.",
    )
    parser.add_argument(
        "--pages", type=int, default=1, help="Pages of 100 runs to fetch. Default 1."
    )
    args = parser.parse_args(argv)

    settings = load_settings()
    if not settings.github_token:
        raise SystemExit("GITHUB_TOKEN is not set. Copy .env.example to .env and fill it in.")
    repo = args.repo or settings.target_repo
    if "/" not in repo:
        raise SystemExit("No repository: pass --repo owner/name or set TARGET_REPO.")

    payloads = fetch_runs(
        repo, settings.github_token, include_passing=args.include_passing, pages=args.pages
    )
    for payload in payloads:
        cache_payload(payload)

    runs = [parse_run(p) for p in payloads]
    failed = sum(r.triageable for r in runs)
    print(f"Fetched {len(runs)} runs ({failed} failed) from {repo} into {settings.data_dir}")


if __name__ == "__main__":
    main()
