# Roadmap

Where the project is, what's next, and what's still undecided. Update the
Status line and the Now section as things move; leave the measured baseline
alone unless you re-measure.

**Status:** stages 1 and 2 built and measured, across Robot, unittest and
job-level crash logs. Stage 3 not started.

---

## The four stages

| # | Stage | State |
|---|-------|-------|
| 1 | **Ingest** — fetch runs and job logs from GitHub Actions | Built |
| 2 | **Cluster** — group failures by root cause | Built |
| 3 | **Classify** — regression / flake / environment / infrastructure | Not started |
| 4 | **Propose and verify** — patch, re-run, score | Not started |

Stage 4 is the reason the project exists. Stages 1–3 are commodity; several
products do them. Adversarial verification — catching an agent that makes a
test pass by deleting the assertion — is the part that isn't.

---

## Measured baseline

Against `robotframework/robotframework`, 251 cached job logs, 55 runs.
Reproduce with `python scripts/cluster_preview.py --roots`.

| Metric | Value |
|---|---|
| Failed jobs by shape | Robot 180 · unittest 53 · crash 17 · unrecognized 1 |
| Failures extracted | 65,598 (Robot 65,495 · unittest 86 · crash 17) |
| Coverage vs the runner's own tally | Robot 99.99% (65,495 / 65,503) · unittest 100% (86 / 86) |
| Distinct cause signatures | 492 |
| Distinct roots | 267 |
| Largest root | 57,155 failures / 6,397 tests → one missing artifact |
| Unclassified | 139 occ (0%), 1 bucket |

Extraction rules, by share of distinct roots:

```
failed-reason    9%      exception   23%
first-line      46%      diff        22%
```

The earlier baseline (65,532 failures, "100%") counted 37 unittest jobs as
one Robot failure each. See the gotcha in `CLAUDE.md`. Robot is 8 failures
short of its own tally; not yet investigated.

`first-line` is the weakest rule and produces the largest share of root
identities — the measured gap deterministic rules can't close (see
`CLAUDE.md`).

---

## Now

**Understanding the code well enough to defend it in an interview.**

Done:
- [x] Broke `_RULE` 90→70, traced how nested unittest separators shred a
      Robot failure and silently delete the traceback
- [x] Broke `keep_basename`, watched 4 FileNotFoundError roots merge into 1
- [x] Found and fixed the over-aggressive guards in `roots.py`
      (unclassified 868→139 occ, 54→28 causes; roots 242→264)
- [x] Fixed the BOM that survived `read_log` and defeated `strip_timestamps`
      on line one

Next in this track:
- [ ] Write a test for each entry in `SCRUBBERS` that has none. Only three
      of the scrubbers are directly tested; path, PYBUILD, UUID, SHA and
      ADDR have no direct coverage. Working out what each pattern catches
      is the point.
- [ ] Rebuild `normalize.py` from scratch against its tests. Run the *whole*
      suite, since `roots.py` exercises it indirectly and catches more than
      the five direct tests do.

**Self-test.** Ready when these can be answered cold:
1. Why is the unit of clustering a test rather than a run?
2. Why does root extraction keep path basenames when cause extraction doesn't?
3. Why is there an `unclassified` bucket instead of just using the first line?
4. Why deterministic rules instead of embeddings, and what would change that?
5. What's the strongest argument this is a reimplementation of BuildPulse?

---

## Next up, in order

### Done: failed jobs that aren't Robot runs

Was "unittest / pytest parser". Sampling the 34 unparsed jobs showed they
were not one thing, so the work split by shape (`jobs.py`):

- **unittest** — `unittest_extract.py`. 53 jobs, 86 failures, 100% of
  unittest's own count. 37 of those jobs had been misparsed as Robot (see the
  `CLAUDE.md` gotcha), so the real count of jobs outside Robot was 71, not 34.
- **crash** — `crash.py`. 17 jobs that died on an import error, a syntax
  error on an old interpreter, or a bad Robot flag before any test reported.
  One job-level record each, from the first traceback.
- **unrecognized** — 1 job, GitHub's Copilot review bot. Not a test run;
  counted rather than dropped or forced through a parser.

No pytest logs exist in the corpus, so there is no pytest parser.

### 1. Classification

`FailureCategory` has existed in `models.py` since the scaffold and nothing
sets it. Rule-based first — the top roots map cleanly:

- `FileNotFoundError` on a build artifact → INFRASTRUCTURE
- missing module / dependency → ENVIRONMENT
- assertion or error-message change → REGRESSION
- same test passing and failing across runs of one commit → FLAKE

Classification is what turns a cluster list into something actionable, and
it's what stage 4 keys its proposal type off.

### 2. Verification target

Stage 4 can't be built without somewhere to actually run tests.
`robotframework/robotframework` can't be pushed to and its suite takes 12
minutes. See Open decisions.

### 3. Agent loop and eval harness

Fix proposal, then scoring on two axes: **fix rate** (did the suite pass)
and **cheat rate** (did the patch weaken or delete the assertion). High fix
rate with high cheat rate is a failure.

---

## Open decisions

**Verification target.** Three candidates:
- Small sandbox repo with deliberately seeded failures — gives ground truth,
  which is what makes cheat rate measurable rather than aspirational
- ArmaA — owned, pushable, but Java while everything here is Python
- Run only the failing subset of Robot's suite locally in a container

Leaning sandbox repo. Decide before writing any stage 4 code; it determines
the shape of everything downstream.

**Proposal output type.** Not one kind of thing. A missing dependency is a
workflow fix, an assertion mismatch is a test fix, a library change is a
source or pin fix. Category drives proposal type, which is why stage 3
comes first.

**Where the model call goes.** Not decided. The measured case is the ~46%
of roots coming from `first-line`, plus root causes that share no wording
(one missing module surfacing as both "requires PyYAML" and "Variable
`<VAR>` not found"). Regexes parse logs faster and cheaper; the model is
for the semantic leap they can't make.

---

## Known limits

- Deterministic root extraction cannot merge failures whose text shares no
  phrase with the cause, even when the cause is identical. Recorded in
  `roots.ROOT_LIMITS`.
- `_MEANINGFUL_DESCRIPTORS` is a substring test, so markup containing "does
  not" would leak through as a root. No such string in the current corpus.
- Large `assertDictEqual` failures make poor roots. The message is a
  truncated repr of two big dicts (`{'spe[224 chars]...[28485 chars]']}]} != {...`),
  the char counts change between runs, and the comparison marker is followed
  by `{`, so `_trim_comparison` doesn't cut it. 37 occurrences split across
  6 roots. Rule `exception` reports it with the same confidence as a clean
  one.
- A crash root of `SyntaxError: invalid syntax` says nothing about which
  construct; the frame with the file and line is dropped on purpose.
- A crash takes the first traceback in the job. A benign traceback printed
  earlier than the real failure would win.
- Robot extraction is 8 failures short of Robot's own tally (65,495 of
  65,503). Not investigated.
- Cached logs expire. GitHub deletes Actions logs on the repo's retention
  schedule, 90 days by default; `check_log_availability.py` reports what's
  still fetchable before a re-fetch commits to it.

---

## Don't

- Keep tuning the normalizer. There is another finding like the guard bug
  every time you look, and the resume claims a four-stage loop of which one
  and a half exist. Thin versions of all four beat deep versions of two.
- Commit `data/` (gitignored, ~20MB, re-fetchable from the API).
