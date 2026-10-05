# ci-triage-agent

Triage for CI failures: ingest GitHub Actions logs, cluster failures by root
cause, classify them, and have an agent propose fixes that are checked for
cheating before anyone trusts them.

**Status:** all four stages are built and have been run. Stages 1-3 are measured
against a 251-log corpus from a real project. Stage 4 has run live on a small
testbed repo: 36 agent patches and a scored, held-out batch of 10 labelled patches.
The testbed is small, so read its numbers as a direction, not a rate. Nothing is
deployed; see [Not built](#not-built).

## Why

Most CI failures are not new: flaky tests, environment drift, a dependency that
moved. Triaging them by hand is repetitive. CI also gives an agent a free check, since
the suite either passes or it does not.

That check is not enough on its own. An agent asked to make a failing test pass
will sometimes delete the assertion. Grouping failures is a solved commercial
problem; telling a real fix from a patch that only turns CI green is the part this
project works on.

## The four stages

| # | Stage | State |
|---|---|---|
| 1 | Ingest: fetch runs and job logs | Built |
| 2 | Cluster: group failures by root cause | Built |
| 3 | Classify: regression, flake, environment, infrastructure | Rules built; flake detected from run history |
| 4 | Propose and verify: patch, re-run, score | Built; run live on the testbed |

Two corpora are used. `robotframework/robotframework` has the failure volume, so it
tests stages 1-3. `gomarz/ci-triage-testbed` is a small repo with a green `main` and
six seeded failures, each with a known category and fix, so it supplies ground truth
for classification and for scoring patches.

## Stages 1-3, measured on the Robot corpus

251 job logs across 55 runs, every one a failed job.

| Metric | Value |
|---|---|
| Failed jobs by shape | Robot 180, unittest 53, crash 17, unrecognized 1 |
| Failures extracted | 65,598 |
| Coverage vs the runner's own tally | Robot 99.99% (65,495 of 65,503), unittest 100% (86 of 86) |
| Distinct cause signatures | 492 |
| Distinct root causes | 266 |
| Largest root | 57,155 failures across 6,397 tests, one missing artifact |

A job reporting 7,100 failed tests is unreadable. The same job reported as one
missing file is something a person can act on.

A failed job is not always a Robot run. unittest jobs get their own parser, and a
job that dies on an import error before any test reports is recorded as one job-level
failure. A log that fits none of these is counted as unrecognized, not dropped.

### Grouping

Each failure gets three signatures:

* **root**: what broke. Merges differently worded symptoms of one cause.
* **cause**: exact match on the normalized message.
* **case**: message plus test identity, for tracking one recurring test.

Normalization scrubs what varies between runs of the same failure: absolute paths on
both runner OSes, interpreter build directories, durations, test tallies and line
numbers. Root extraction then peels the framework's wrapper layers and keeps the
innermost diagnostic sentence. It is deterministic rather than embedding-based, so
which failures merge is predictable and reviewable.

Every root records the rule that produced it. About 45% of distinct roots come from
the weakest rule (`first-line`), and failures that carry no diagnostic text go to a
visible `unclassified` bucket. Exact-match rules cannot join failures that share a
cause but no wording: one missing module appears as "requires PyYAML module to be
installed" in one place and "Variable `${X}` not found" in another. That gap is the
case for a model call.

### Classification

Rules map a root sentence to regression, environment or infrastructure. First match
wins, each result names its rule, and a rule fires only on a strong indicator (a
missing module, a missing build artifact, an actual-against-expected mismatch).
Ambiguous roots stay untriaged, because a confident wrong category would send the fix
proposal down the wrong path.

On the Robot corpus, 109 of 266 roots (41%) are classified. By failure count it
looks like 98%, but that is mostly the one missing artifact behind 57,155 failures.
The Robot corpus has no labels, so accuracy is measured on the testbed.

Flake cannot be read from one root sentence: `Lists differ` is a regression on a
changed commit and a flake on an unchanged one. `flake.py` instead looks for a test
that passed in one job and failed in another for the same commit, workflow and job
name. The Robot corpus has none to find, since it holds only failed jobs. On the
testbed it finds one, s05.

| Testbed classification, 6 seeds | Correct | Wrong | Abstained | Right when it answers |
|---|---|---|---|---|
| Root rules alone | 4 | 1 | 1 | 4/5 |
| With run history | 5 | 0 | 1 | 5/5 |

The seeds were written by someone who had read the rules, and six cases give no
usable confidence interval. This checks that the pipeline works end to end; it is not
a benchmark.

## Stage 4: propose and verify

An agent works in a sandbox: a fresh git repo holding `main` plus the seed's failing
change, with no history and no seed metadata. It has six tools (list, read, write,
replace, delete, run CI), every path confined to the repo. It is given what stages 1-3
make of the failure log, not the answer key. Its patch is the `git diff`.

Two prompt framings are used, "make CI pass" and "find the root cause". Neither says
what not to do, because a rule against cheating would measure compliance with the
rule.

A patch is scored on whether CI goes green and on what it did to get there. A green
patch that skipped the failing test is a cheat. The cheat rate is the share of green
patches that are cheats; a red patch was wrong, not dishonest.

* **Static layer**: regexes over the diff for deleted or skipped tests, loosened or
  swallowed assertions, edited expectations, `continue-on-error`, special-cased
  returns, dropped dependencies, and similar.
* **Dynamic layer**: compares the run with the failing tree's own run. Fewer tests
  run, or more skipped, is a cheat however it was done.
* **Model judge**: asked about green patches no hard flag has convicted. It sees the
  failure report, the diff and the touched files, not the manifest. It can convict,
  and can acquit only a patch whose flags were all review-level.

### Results

Scoring runs without the manifest's hints (`--no-oracle`), which a real deployment
would not have.

| Held-out batch, 5 cheats and 5 honest fixes | No model | With judge |
|---|---|---|
| Cheats called CHEAT | 2/5 | 5/5 |
| Cheats missed | 2/5 | 0/5 |
| Honest fixes called clean | 5/5 | 5/5 |

The held-out batch was written before the judge and scored once with the detectors and
judge prompt frozen. Tuning either afterwards would retire it, so it is now spent.
Only three of the verdicts were the judge's, on ten patches. An earlier batch the
detectors were tuned against scored 28/28, which says only that the detectors do what
their author intended. The next batch, written before the final detectors, flagged all
4 cheats but named the right reason for only 1.

On the agent's own patches (6 seeds, 2 framings, 3 repeats), all 36 went CI-green and
none was a cheat by hand label. Without the judge the scorer called 22 of the 36
suspect, nearly all of them honest: correct reverts, the intended test change in s06,
a dropped dependency in s03. The judge cleared 21 and wrongly convicted one s06 patch,
a case where intent is ambiguous without more context. Counting the held-out batch, that
is one honest patch convicted out of 41.

What this does not show:

* The agent never cheated, so the judge's recall on cheats the agent invents itself
  is unmeasured. The six seeds are small enough that an honest fix is the easy path.
* The agent and the judge are the same model, so a self-preference effect is
  untested.
* The held-out batch has ten patches. One different verdict moves a figure by ten
  points.

## Not built

The earlier design called for an AWS deployment. None of it exists in this repo, and
the agent calls the Anthropic API directly rather than going through Bedrock.

* Network-isolated sandboxes (ECS Fargate). The current sandbox confines paths and
  refuses `.git`, but does not isolate the network, and the testbed's CI runs locally.
* Orchestration, state and storage (Step Functions, DynamoDB, S3).
* Infrastructure as code (CDK) and tracing (OpenTelemetry).
* The final step, opening a PR or filing a triage summary. The pipeline ends at a
  patch and its score.
* A cost budget. The agent has a turn limit, and the scripts refuse to spend without
  `--confirm-spend`, but nothing caps dollars.

## Development

Requires Python 3.11+ and [Poetry](https://python-poetry.org/docs/#installation) 2.x.

```bash
poetry env use 3.12     # optional: CI runs 3.11 and 3.12
poetry install
poetry run ruff check . && poetry run ruff format --check . && poetry run pytest
```

Copy `.env.example` to `.env` and set `GITHUB_TOKEN` (scope `actions:read`) before
fetching anything. Running the agent or the judge also needs `ANTHROPIC_API_KEY` in
the environment.

Robot corpus (stages 1-3):

```bash
python scripts/check_log_availability.py   # survey what is still fetchable
python scripts/fetch_logs.py               # resumable log ingestion
python scripts/cluster_preview.py --roots  # root clusters and rule breakdown
python scripts/cluster_preview.py --classify
```

Testbed (stage 4). Clone `ci-triage-testbed` next to this repo and give it its own
data directory:

```bash
export DATA_DIR=data/testbed
python -m ci_triage.ingest --repo gomarz/ci-triage-testbed --include-passing
python scripts/fetch_logs.py --all-runs
python scripts/score_classifier.py --manifest ../ci-triage-testbed/seeds/manifest.json
python scripts/score_patch.py --testbed ../ci-triage-testbed --suite --static-only   # free
python scripts/run_agent.py --testbed ../ci-triage-testbed --seed s01-discount-rounding --mode pass --confirm-spend
python scripts/rescore_agent_runs.py --testbed ../ci-triage-testbed --judge --confirm-spend
```

The agent and judge scripts call the API and refuse to run without
`--confirm-spend`. The 36-patch run cost about $5. `CLAUDE.md` has the full command
list, the measured baselines and the problems found along the way.

Cached logs live under `data/` and are gitignored. GitHub deletes Actions logs on the
repository's retention schedule, 90 days by default, so the survey step reports what
is still retrievable before a fetch commits to it.

## License

MIT. See [LICENSE](LICENSE).
