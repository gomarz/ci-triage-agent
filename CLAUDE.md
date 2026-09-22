# ci-triage-agent

Agentic triage for CI failures: ingest, cluster, propose verified fixes.

## The loop

1. **Ingest** — fetch GitHub Actions runs and job logs. *Built.*
2. **Cluster** — group failures by root cause. *Built.*
3. **Classify** — regression / flake / environment / infrastructure. *Not built.*
4. **Propose and verify** — patch, re-run, score. *Not built.*

Stage 4 is the point of the project. Grouping failures is a solved
commercial problem (Datadog CI Visibility, BuildPulse, Trunk). Adversarial
verification is not: an agent asked to make a failing test pass will delete
the assertion, and the cheat-rate metric exists to catch exactly that.

## Corpus

`robotframework/robotframework`, chosen for failure volume. Cached under
`data/` (gitignored, ~20MB, re-fetchable):

```
data/raw/runs/{run_id}.json         run metadata
data/raw/jobs/{run_id}.json         job manifest
data/raw/logs/{run_id}/{job_id}.txt raw log text, timestamps intact
```

251 job logs across 55 runs. 65,532 failures extracted at 100% coverage
against Robot's own tally. 473 cause signatures, 261 roots. The largest
root resolves 57,155 failures across 6,397 tests to one missing artifact
file.

## Commands

```
poetry install                               # once; .venv is in-project, Python 3.12
poetry run pytest tests -q
poetry run ruff check . && poetry run ruff format --check .

python scripts/check_log_availability.py     # survey cache before fetching
python scripts/fetch_logs.py                 # resumable; skips cached
python scripts/peek_failure.py --groups      # what the runner actually ran
python scripts/cluster_preview.py --roots    # root clusters + rule breakdown
python scripts/cluster_preview.py --root-sig SIG   # inspect one root
```

`GITHUB_TOKEN` with `actions:read` is required for anything that fetches.

## Three signature levels

- `root_sig` — what broke. Coarsest. Merges differently-worded symptoms.
- `cause_sig` — exact match on the normalized message.
- `case_sig` — message plus test identity.

Root extraction is a ladder (`failed-reason`, `exception`, `diff`,
`first-line`, `unclassified`) and every failure records which rule derived
it. `first-line` is the weakest and accounts for ~45% of distinct roots.
That number is the measured gap deterministic rules can't close, and it is
the justification for a model call — not decoration.

## Gotchas that cost real time

Each of these was found by being wrong first. Don't rediscover them.

**The logs endpoint 302s to a signed blob URL.** The httpx client must set
`follow_redirects=True` or every log comes back empty and looks like a data
problem. See `logs.build_client`.

**Windows-runner logs are CRLF.** Python's translating writer turns those
into CRLFLF, doubling every line. `cache_log` writes with `newline=""`;
`read_log` repairs older caches.

**`##[group]` labels are commands, not step names.** They cannot be joined
against the API's `failed_steps`. Post-job cleanup also gets absorbed into
the final group, so "last group" is teardown, never the failure. Anchor on
`##[error]` instead.

**Robot's separator is 100 dashes; unittest's is 70.** Splitting on `-{70,}`
shreds nested unittest tracebacks. `extract._RULE` requires 90+.

**The unit of aggregation is the job, not the run.** A matrix run has many
jobs, each with its own tally. Summing jobs while comparing against one
job's tally reported 764% coverage.

**Path scrubbing is a trade-off, not a win.** Collapsing whole paths to
`<PATH>` put 94% of the corpus in one cluster. Roots keep the basename
(`scrub_paths(keep_basename=True)`); cause signatures don't.

**Don't name a module-level function `test_*`.** pytest collects imported
names, so `test_signature` was collected as a test. It's `case_signature`.

**Machine Python is 3.14, but the Poetry venv is pinned to 3.12; CI runs 3.11 and 3.12.** `Path.read_text(newline=)`
is 3.13+. Passing locally means nothing.

## Conventions

- ruff: `select = ["E", "F", "I", "UP", "B"]`, line-length 100. `E501` and
  `E402` are on — keep imports at the top of test files.
- Comments explain *why*, not what. If a line is load-bearing for a
  non-obvious reason, say so in the comment.
- Tests use fixtures trimmed from real cached logs, not invented strings.
  Separator widths and message shapes have to match production.
- Deterministic before probabilistic. Regexes parse logs faster and cheaper
  than a model; the model is for the semantic leap regexes can't make.

## Next

Classification. `FailureCategory` exists in `models.py` and nothing sets it.
Rule-based first — the top roots map cleanly (`FileNotFoundError` on a build
artifact → INFRASTRUCTURE, a missing module → ENVIRONMENT, an assertion
change → REGRESSION).

After that, verification needs a target repo we can actually push to.
`robotframework/robotframework` can't be pushed to and its suite takes 12
minutes. A small repo with deliberately seeded failures gives ground truth,
which is what makes cheat-rate measurable rather than aspirational.
