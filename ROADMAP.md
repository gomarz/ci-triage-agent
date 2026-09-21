# Roadmap

Where the project is, what's next, and what's still undecided. Update the
Status line and the Now section as things move; leave the measured baseline
alone unless you re-measure.

**Status:** stages 1 and 2 built and measured. Stage 3 not started.

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
| Failures extracted | 65,532 |
| Coverage vs Robot's own tally | 100% |
| Distinct cause signatures | 473 |
| Distinct roots | 264 |
| Largest root | 57,155 failures / 6,397 tests → one missing artifact |
| Unclassified | 139 occ (0%), 1 bucket |

Extraction rules, by share of distinct roots:

```
failed-reason    9%      exception   23%
first-line      46%      diff        23%
```

`first-line` is the weakest rule and produces the largest share of root
identities. That number is the honest measure of where deterministic rules
run out, and the argument for a model call at stage 3 or 4.

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

### 1. unittest / pytest parser

34 cached jobs fail with no Robot `FAIL:` blocks — unit test and lint jobs.
They're currently dropped, so the corpus is smaller than it looks. List them
with `cluster_preview.py --unparsed`.

Write this one by hand. The Robot parser sits next to it as a reference, but
deciding what's analogous and what isn't is where the understanding lives.

Design constraint already known: unittest uses the same `FAIL:` marker Robot
does, and its separator is 70 chars where Robot's is 100. In these logs
unittest's `FAIL:` is top-level, so disambiguation has to come from
something other than the marker.

### 2. Classification

`FailureCategory` has existed in `models.py` since the scaffold and nothing
sets it. Rule-based first — the top roots map cleanly:

- `FileNotFoundError` on a build artifact → INFRASTRUCTURE
- missing module / dependency → ENVIRONMENT
- assertion or error-message change → REGRESSION
- same test passing and failing across runs of one commit → FLAKE

Classification is what turns a cluster list into something actionable, and
it's what stage 4 keys its proposal type off.

### 3. Verification target

Stage 4 can't be built without somewhere to actually run tests.
`robotframework/robotframework` can't be pushed to and its suite takes 12
minutes. See Open decisions.

### 4. Agent loop and eval harness

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
- 34 jobs unparsed pending the unittest parser.
- Cached logs expire. GitHub deletes Actions logs on the repo's retention
  schedule, 90 days by default; `check_log_availability.py` reports what's
  still fetchable before a re-fetch commits to it.

---

## Don't

- Keep tuning the normalizer. There is another finding like the guard bug
  every time you look, and the resume claims a four-stage loop of which one
  and a half exist. Thin versions of all four beat deep versions of two.
- Let Claude Code author the unittest parser. Rubber duck, not author.
- Commit `data/` (gitignored, ~20MB, re-fetchable from the API).
