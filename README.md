# ci-triage-agent

An agentic service that ingests CI failures from GitHub Actions, clusters them
by root cause, and proposes verified fixes.

**Status:** Ingestion, clustering and rule-based classification are built and
measured against a real corpus. The agent loop is not. See [Roadmap](#roadmap).

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
|Failed jobs by shape|Robot 180, unittest 53, crash 17, unrecognized 1|
|Failures extracted|65,598|
|Coverage vs the runner's own tally|Robot 99.99% (65,495 of 65,503), unittest 100% (86 of 86)|
|Distinct cause signatures|492|
|Distinct root causes|266|
|Largest root|57,155 failures across 6,397 tests → one missing artifact|

A failed job is not always a Robot run. Unit-test jobs get their own parser, and
a job that dies on an import error before any test reports is recorded as one
job-level failure. A log that fits none of these is counted as unrecognized
rather than dropped.

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

### Classification

Each root gets a category: regression, environment or infrastructure. Rules read
the extracted root sentence, first match wins, and each result names its rule.
They fire only on a strong indicator (a missing module, a missing build artifact,
an actual-against-expected mismatch). Anything ambiguous stays untriaged rather
than getting a plausible guess, because a wrong category would send the fix
proposal down the wrong path.

109 of 266 roots (41%) are classified. The share of failures looks higher (98%)
but is mostly one root: a single missing artifact behind 57,155 failures.
Category accuracy has not been measured against labels, which is what the eval
harness is for.

Flake is not assigned. It needs the same test failing in one run and passing in
another, and every run in the corpus is a failure.

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
  classify: regression / environment / infrastructure  ← built (flake: needs passing runs)
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
* \[x] Rule-based failure classification (flake detection needs passing runs)
* \[ ] Eval harness and labeled failure corpus
* \[ ] Agent loop with tool calls and step/cost budget
* \[ ] Sandboxed test execution on Fargate
* \[ ] CDK infrastructure
* \[ ] OpenTelemetry tracing per agent step

## Development

Requires Python 3.11+ and [Poetry](https://python-poetry.org/docs/#installation) 2.x.

```bash
poetry env use 3.12     # optional: CI runs 3.11 and 3.12
poetry install
poetry run ruff check . && poetry run pytest
```

Use `poetry run <cmd>` or `poetry env activate` for the commands below.

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
