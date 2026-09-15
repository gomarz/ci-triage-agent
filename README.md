# ci-triage-agent

An agentic service that ingests CI failures from GitHub Actions, clusters them
by root cause, and proposes verified fixes.

**Status:** Ingestion and clustering are built and measured against a real
corpus. Classification and the agent loop are not. See [Roadmap](#roadmap).

## Why

Most CI failures aren't new. They're recurring problems such as
flaky tests, environment drift, or a dependency that
moved. Triaging them by hand is repetitive work that a machine should be doing,
and unlike most LLM applications, this one has a free automatic verifier — you
can run the test suite and find out objectively whether a proposed fix worked.

That verifier is the whole design premise. An agent that proposes patches
without one is guessing. An agent that can run the suite, check the result, and
retry within a budget is doing engineering.

## What works today

Run metadata and job logs are ingested from the GitHub Actions API and cached
locally. Failures are extracted per test, normalized, and grouped at three
levels of granularity.

Measured against `robotframework/robotframework`, 251 job logs across 55 runs:

|Metric|Value|
|-|-|
|Failures extracted|65,532|
|Coverage vs Robot's own tally|100%|
|Distinct cause signatures|473|
|Distinct root causes|261|
|Largest root|57,155 failures across 6,397 tests → one missing artifact|

That last row is the case for doing this at all. A job reporting 7,100 failed
tests is unreadable. The same job reported as one missing file is actionable.

### How the grouping works

Three signatures per failure:

* **root** — what broke. Merges differently-worded symptoms of one cause.
* **cause** — exact match on the normalized message.
* **case** — message plus test identity, for tracking a specific recurring test.

Normalization scrubs what varies between runs of the same failure: absolute
paths on both runner OSes, interpreter build directories, durations, test
tallies, line numbers. Root extraction then peels the framework's wrapper
layers and keeps the innermost diagnostic sentence.

It is deterministic rather than embedding-based, so which failures merge is
predictable and reviewable rather than a tuned similarity threshold.

### Where it runs out

Every root records which rule derived it, and text carrying no diagnostic
content goes to a visible `unclassified` bucket instead of becoming a fake
cluster. About 45% of distinct roots come from the weakest rule.

Exact-match rules cannot merge failures that share a cause but no wording. One
missing module surfaces both as "requires PyYAML module to be installed" and as
"Variable `${X}` not found"; nothing short of semantic understanding connects
those. That measured gap is where a model call earns its cost, and is the
reason there isn't one yet.

## How it will work

```
GitHub Actions run fails
        ↓
  ingest: fetch run metadata + logs                    ← built
        ↓
  extract: per-test failures, normalized               ← built
        ↓
  cluster: root / cause / case signatures              ← built
        ↓
  classify: regression / flake / environment           ← next
        ↓
  agent loop: reproduce → patch → run tests → verify   (budgeted, sandboxed)
        ↓
  report: open a PR or file a triage summary
```

### Planned architecture

|Concern|Choice|
|-|-|
|Agent execution|ECS Fargate, network-isolated task per run|
|Orchestration|Step Functions|
|State|DynamoDB|
|Log/artifact storage|S3|
|Model access|Amazon Bedrock|
|Infrastructure as code|AWS CDK (Python)|
|Tracing|OpenTelemetry → CloudWatch|

Test execution is sandboxed with no network egress. The agent is patching and
running untrusted code, so task-level isolation is a requirement rather than a
nicety.

## The hard part

An agent asked to make a failing test pass will happily delete the assertion.
Measuring and preventing that is the interesting problem here, not the patching
itself.

The plan is an eval set built from real broken commits, scored on two axes:

* **Fix rate** — did the suite pass afterward?
* **Cheat rate** — did the patch weaken or remove the assertion instead of
fixing the code?

A high fix rate with a high cheat rate is a failure, not a success.

## Roadmap

* \[x] Project scaffolding, lint, tests, CI
* \[x] GitHub Actions ingestion — fetch runs, download logs, persist
* \[x] Failure extraction, normalization, and root-cause clustering
* \[ ] Failure classification
* \[ ] Eval harness and labeled failure corpus
* \[ ] Agent loop with tool calls and step/cost budget
* \[ ] Sandboxed test execution on Fargate
* \[ ] CDK infrastructure
* \[ ] OpenTelemetry tracing per agent step

## Development

Requires Python 3.11+.

```bash
# macOS / Linux
python -m venv .venv \&\& source .venv/bin/activate

# Windows
py -3.12 -m venv .venv \&\& .venv\\Scripts\\activate

pip install -e ".\[dev]"
ruff check . \&\& pytest
```

Copy `.env.example` to `.env` and fill in a GitHub token with `actions:read`
before running ingestion.

```bash
python scripts/check\_log\_availability.py   # survey what's fetchable
python scripts/fetch\_logs.py               # resumable log ingestion
python scripts/cluster\_preview.py --roots  # root clusters and rule breakdown
```

Cached logs live under `data/` and are gitignored. GitHub deletes Actions logs
on the repository's retention schedule, 90 days by default, so the survey step
reports what's still retrievable before a fetch commits to it.

## License

MIT — see [LICENSE](LICENSE).
