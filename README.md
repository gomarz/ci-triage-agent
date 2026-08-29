# ci-triage-agent

An agentic service that ingests CI failures from GitHub Actions, clusters recurring ones, and proposes fixes.

**Status:** Started August 2026. Scaffolding and tooling only — no ingestion or agent loop yet. See [Roadmap](#roadmap) for what's actually built.

## Why

Most CI failures aren't new. They're the same handful of problems recurring: a flaky test, a timeout under load, an environment drift, a dependency that moved. Triaging them by hand is repetitive work that a machine should be doing, and unlike most LLM applications, this one has a free automatic verifier — you can run the test suite and find out objectively whether a proposed fix worked.

That verifier is the whole design premise. An agent that proposes patches without one is guessing. An agent that can run the suite, check the result, and retry within a budget is doing engineering.

## How it will work

```
GitHub Actions run fails
        ↓
  ingest: fetch run metadata + logs        ← in progress
        ↓
  parse: extract failure signature
        ↓
  cluster: group against known failures
        ↓
  classify: real regression / flake / environment
        ↓
  agent loop: reproduce → patch → run tests → verify   (budgeted, sandboxed)
        ↓
  report: open a PR or file a triage summary
```

### Planned architecture

| Concern | Choice |
|---|---|
| Agent execution | ECS Fargate, network-isolated task per run |
| Orchestration | Step Functions |
| State | DynamoDB |
| Log/artifact storage | S3 |
| Model access | Amazon Bedrock |
| Infrastructure as code | AWS CDK (Python) |
| Tracing | OpenTelemetry → CloudWatch |

Test execution is sandboxed with no network egress. The agent is patching and running untrusted code, so task-level isolation is a requirement rather than a nicety.

## The hard part

An agent asked to make a failing test pass will happily delete the assertion. Measuring and preventing that is the interesting problem here, not the patching itself.

The plan is an eval set built from real broken commits in open-source Java and Python repos, scored on two axes:

- **Fix rate** — did the suite pass afterward?
- **Cheat rate** — did the patch weaken or remove the assertion instead of fixing the code?

A high fix rate with a high cheat rate is a failure, not a success.

## Roadmap

- [x] Project scaffolding, lint, tests, CI
- [ ] GitHub Actions ingestion — fetch runs, download logs, persist
- [ ] Failure signature extraction and clustering
- [ ] Eval harness and labeled failure corpus
- [ ] Agent loop with tool calls and step/cost budget
- [ ] Sandboxed test execution on Fargate
- [ ] CDK infrastructure
- [ ] OpenTelemetry tracing per agent step

## Development

Requires Python 3.11+.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

ruff check .
pytest
```

Copy `.env.example` to `.env` and fill in a GitHub token with `actions:read` before running ingestion.

## License

MIT — see [LICENSE](LICENSE).
