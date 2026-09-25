# ci-triage-agent

Agentic triage for CI failures: ingest, cluster, propose verified fixes.

## The loop

1. **Ingest** — fetch GitHub Actions runs and job logs. *Built.*
2. **Cluster** — group failures by root cause. *Built.*
3. **Classify** — regression / flake / environment / infrastructure. *Rules
   built; flake detected from run history (`flake.py`), which only the
   testbed corpus has.*
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

251 job logs across 55 runs, every one a failed job. By shape (`jobs.py`):
180 Robot, 53 unittest, 17 crash, 1 unrecognized. 65,598 failures
extracted: Robot 65,495 of the 65,503 it reported (99.99%), unittest 86 of
86, plus 17 job-level crashes. 492 cause signatures, 266 roots. The largest
root resolves 57,155 failures across 6,397 tests to one missing artifact
file.

Parsing is per shape. Robot goes first, then unittest, then crash; whatever
matches none is `unrecognized` and stays in the counts. A crash is one
record per job (`scope="job"`, `test_id="<job>"`) taken from the first
traceback, since later ones are consequences.

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
python scripts/cluster_preview.py --unparsed # failed jobs no parser recognized
python scripts/cluster_preview.py --classify # category per root, by rule
```

`GITHUB_TOKEN` with `actions:read` is required for anything that fetches.

## Second corpus: the testbed

`gomarz/ci-triage-testbed` is a small repo with a green `main` and six seeded
failures on `seed/*` branches, each with a known category and fix (ground truth
in that repo's `seeds/manifest.json`). It lives in its own data directory so
its logs never mix into the Robot counts above. Every script reads `DATA_DIR`
(default `data`; a relative path resolves from the working directory):

```
export DATA_DIR=data/testbed
python -m ci_triage.ingest --repo gomarz/ci-triage-testbed --include-passing
python scripts/fetch_logs.py --all-runs      # passing runs too, jobs fetched whole
python scripts/cluster_preview.py --roots
python scripts/flake_preview.py              # tests that passed and failed on one commit
python scripts/score_classifier.py --manifest ../ci-triage-testbed/seeds/manifest.json
```

Ingest defaults are unchanged: failures only, one page of 100, `TARGET_REPO`.
`--pages N` reads further back. The runs listing returns each run's **latest
attempt only**, so a re-run failure shows up as a pass and its first attempt is
lost from the cache (`/runs/{id}/attempts/{n}` would recover it; not built).
The 9 cached runs of the s05 commit are 5 failed and 4 passed, all from
separate dispatches.

## Three signature levels

- `root_sig` — what broke. Coarsest. Merges differently-worded symptoms.
- `cause_sig` — exact match on the normalized message.
- `case_sig` — message plus test identity.

Root extraction is a ladder (`failed-reason`, `exception`, `diff`,
`first-line`, `unclassified`) and every failure records which rule derived
it. `first-line` is the weakest and accounts for ~45% of distinct roots.
That number is the measured gap deterministic rules can't close, and it is
the justification for a model call — not decoration.

## Classification

`classify.py` maps a root sentence to a `FailureCategory` by ordered rules,
first match wins, and every result names its rule. It fires only on a strong
indicator; anything ambiguous stays `UNTRIAGED` for the model. A confident
wrong category would send stage 4 down the wrong proposal type.

Report it by roots, not occurrences: one missing artifact is 57,155 of 65,598
failures. 109 of 266 roots (41%) are classified: 19 infrastructure, 57
regression, 33 environment. That is coverage. The Robot corpus has no labels,
so accuracy is measured on the testbed instead (below).

`should be` is not a mismatch signal: Robot uses it for "captured stderr
should be empty" and inside its own status wrapper.

No rule assigns FLAKE, because no root sentence can: `Lists differ` is a
regression on a changed commit and a flake on an unchanged one. History does.
`flake.find_flakes` looks for a test that passed in one job and failed in
another of the same (commit, workflow, job name), reading verbose unittest's
per-test result lines. `classify(failure, flaky=True)` takes that verdict and
it outranks the root rules. Job name is in the key so a matrix cell that fails
only on Windows is not a flake. `python scripts/flake_preview.py` reports it.

On the testbed it finds exactly one: s05's `test_unique_skus`, failing 5 of 9
runs of one commit, which wording alone calls a regression. On the Robot corpus
it finds none, and the reason is measurable: 53 jobs have per-test results, in
53 groups, none with a second job to compare. What it cannot see: Robot logs
(not parsed), a failure that was re-run and passed (only the latest attempt is
cached), and a test that prints to stdout mid-result-line (left out, not
guessed). See `classify.FLAKE_LIMITS` and the `flake.py` docstring.

**Accuracy on the testbed** (`scripts/score_classifier.py --manifest
../ci-triage-testbed/seeds/manifest.json`, with `DATA_DIR=data/testbed`). Six
seeds, one row each, because one seed is one cause. UNTRIAGED is an abstention,
not an error, so there are two numbers: how often it answers and how often an
answer is right.

| | correct | wrong | abstained | right when it answers |
|---|---|---|---|---|
| root rules alone | 4 | 1 | 1 | 4/5 |
| with run history | 5 | 0 | 1 | 5/5 |

The wrong one is s05, the flake, called a regression by its wording. The
abstention is s02, a `TypeError` from a refactor that missed one caller, which
no rule matches: the case the model call is for. Treat this as a check that the
pipeline works end to end, not a benchmark. The seeds were written by someone
who had read the rules, six cases give no confidence interval worth quoting, and
the labels are the author's judgement (s06, an intended change with a stale
test, is labelled regression).

## Gotchas that cost real time

Each of these was found by being wrong first. Don't rediscover them.

**The logs endpoint 302s to a signed blob URL.** The httpx client must set
`follow_redirects=True` or every log comes back empty and looks like a data
problem. See `logs.build_client`. (It was imported by both fetch scripts for
weeks without ever being committed; a fresh checkout could not fetch anything.)

**Windows-runner logs are CRLF.** Python's translating writer turns those
into CRLFLF, doubling every line. `cache_log` writes with `newline=""`;
`read_log` repairs older caches.

**`##[group]` labels are commands, not step names.** They cannot be joined
against the API's `failed_steps`. Post-job cleanup also gets absorbed into
the final group, so "last group" is teardown, never the failure. Anchor on
`##[error]` instead.

**Robot's separator is 100 dashes; unittest's is 70.** Splitting on `-{70,}`
shreds nested unittest tracebacks. `extract._RULE` requires 90+.

**unittest prints `FAIL:` too.** With no Robot rule in the log,
`extract_failures` used to see one chunk, and the first unittest `FAIL:` swallowed
the rest of the log (up to 146 KB) as a single "Robot failure". 37 jobs
were counted that way, and the extras hid an 8-failure shortfall inside a
rounded "100%". `extract_failures` now returns nothing without a 90+
rule.

**Verbose unittest prints every failure twice.** Once inline while it runs
(`name (id) ... ERROR`), once as a block between two 70-character rules. Only
the block has the traceback. A block ends at the next rule, not the next
`Traceback`: chained exceptions put two inside one block.

**Compare coverage like for like.** Extracted failures from jobs that printed
a tally against the tallies, nothing else. Comparing all extracted failures to
the tallied subset is what let the 37 extras through.

**Robot capitalises only the first word.** "Setup failed:" but "Parent suite
setup failed:". The wrapper regex matched only the capitalised form, so 959
failures kept a wrapper as their root with the real cause on the next line.

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

Verification needs a target repo we can actually push to.
`robotframework/robotframework` can't be pushed to and its suite takes 12
minutes. A small repo with deliberately seeded failures gives ground truth,
which is what makes cheat-rate measurable rather than aspirational. The same
repo can measure classification accuracy: seed a known missing dependency, a
known assertion change, a known flake, and check the category.

Flake detection and the accuracy check are built. Stage 4 is next: the seeds'
manifest already lists the correct fix files and the cheats to look for.
Separately, six seeds are too few to say anything about accuracy; more seeds,
ideally written without reading `classify.py`, would. Recovering re-run attempts
(`/runs/{id}/attempts/{n}`) would stop a re-run failure from vanishing.
