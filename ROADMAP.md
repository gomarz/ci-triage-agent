# Roadmap

Where the project is, what comes next, and what is still undecided. Update the
Status line and the Now section as things move. Leave the measured baselines alone
unless you re-measure.

**Status:** all four stages are built and have run. Stages 1-3 are measured on the
Robot corpus (Robot, unittest and job-level crash logs). Stage 4 has run live on the
testbed repo: 36 agent patches, and the model judge scored once on a held-out batch.
The testbed has six seeds, so the next work is making those numbers mean more, not
building more stages. `CLAUDE.md` holds the detail and the commands.

---

## The four stages

| # | Stage | State |
|---|-------|-------|
| 1 | **Ingest**: fetch runs and job logs from GitHub Actions | Built |
| 2 | **Cluster**: group failures by root cause | Built |
| 3 | **Classify**: regression / flake / environment / infrastructure | Built; flake from run history, found only on the testbed |
| 4 | **Propose and verify**: patch, re-run, score | Built; run live on the testbed |

Stage 4 is the reason the project exists. Stages 1-3 are commodity; several products
do them. Catching an agent that makes a test pass by deleting the assertion is the
part that is not.

---

## Measured baselines

### Robot corpus (stages 1-3)

`robotframework/robotframework`, 251 cached job logs, 55 runs. Reproduce with
`python scripts/cluster_preview.py --roots`.

| Metric | Value |
|---|---|
| Failed jobs by shape | Robot 180 · unittest 53 · crash 17 · unrecognized 1 |
| Failures extracted | 65,598 (Robot 65,495 · unittest 86 · crash 17) |
| Coverage vs the runner's own tally | Robot 99.99% (65,495 / 65,503) · unittest 100% (86 / 86) |
| Distinct cause signatures | 492 |
| Distinct roots | 266 |
| Largest root | 57,155 failures / 6,397 tests, one missing artifact |
| Unclassified | 139 occurrences (0%), 1 bucket |
| Roots with a category | 109 of 266 (41%): infrastructure 19 · regression 57 · environment 33 |

Extraction rules, by share of distinct roots:

```
failed-reason    9%      exception   23%
first-line      45%      diff        23%
```

An earlier baseline (65,532 failures, "100%") counted 37 unittest jobs as one Robot
failure each; see the gotcha in `CLAUDE.md`. Robot is 8 failures short of its own
tally and that has not been investigated.

`first-line` is the weakest rule and produces the largest share of root identities.
That is the measured gap deterministic rules cannot close.

### Testbed (stage 3 accuracy and stage 4)

`gomarz/ci-triage-testbed`: a green `main` and six seeded failures with known
category and fix.

| Measure | Result |
|---|---|
| Classifier, root rules alone | 4 correct, 1 wrong (s05, a flake), 1 abstained: 4/5 when it answers |
| Classifier, with run history | 5 correct, 0 wrong, 1 abstained (s02): 5/5 when it answers |
| Agent patches, 6 seeds x 2 framings x 3 repeats | 36 of 36 CI-green, none a cheat by hand label |
| Scorer without the judge, on those 36 | 14 clean, 22 suspect (nearly all honest fixes) |
| Judge on those 36 | cleared 21 of 22 suspects, convicted 1 (s06, a false conviction) |
| Held-out batch, no oracle, no model | cheats: 2 CHEAT, 1 suspect, 2 missed; honest: 5 clean |
| Held-out batch, no oracle, with judge | cheats 5/5 CHEAT; honest 5/5 clean |

The held-out batch is spent. Any change to the detectors or the judge prompt after
seeing its result retires it, and a new batch has to be written.

---

## Now

**Understanding the code well enough to defend it in an interview.**

Done:
- [x] Broke `_RULE` 90→70, traced how nested unittest separators shred a Robot
      failure and silently delete the traceback
- [x] Broke `keep_basename`, watched 4 FileNotFoundError roots merge into 1
- [x] Found and fixed the over-aggressive guards in `roots.py` (unclassified 868→139
      occurrences, 54→28 causes; roots 242→264)
- [x] Fixed the BOM that survived `read_log` and defeated `strip_timestamps` on line
      one

Next in this track:
- [ ] Write a test for each entry in `SCRUBBERS` that has none. Only three of the
      scrubbers are directly tested; path, PYBUILD, UUID, SHA and ADDR have no direct
      coverage. Working out what each pattern catches is the point.
- [ ] Rebuild `normalize.py` from scratch against its tests. Run the whole suite,
      since `roots.py` exercises it indirectly and catches more than the five direct
      tests do.

**Self-test.** Ready when these can be answered cold:
1. Why is the unit of clustering a test rather than a run?
2. Why does root extraction keep path basenames when cause extraction does not?
3. Why is there an `unclassified` bucket instead of just using the first line?
4. Why deterministic rules instead of embeddings, and what would change that?
5. What is the strongest argument this is a reimplementation of BuildPulse?
6. Why is the held-out batch only valid once, and what did the first batch the author
   had not tuned against show?
7. Why is the cheat rate taken over green patches only?

---

## Next up, in order

### 1. Harder seeds

Six small seeds are too few to say anything about classifier accuracy, and the fixes
are easy enough that the agent never wanted to cheat (0 of 36). Add seeds where the
honest fix is hard, ideally written without reading `classify.py` or the detectors.
Without a reason to cheat, the judge's recall on the agent's own cheats stays
unmeasured.

### 2. A fresh held-out batch, and a different judge model

The current held-out batch is spent. Any further detector or judge change needs a new
one. The agent and the judge are both `claude-opus-5`, so running the judge on a
different model would test whether the judge favours its own family's patches.

### 3. Close the s06 ambiguity

The judge convicted one of six honest s06 patches, and acquitted the others mostly
because the branch name hinted the change was intended. A tests-only edit of expected
values is ambiguous without the change's intent. The right answer there is `unsure`.
Deciding what extra context a deployment would give the judge (a commit message, a
PR description) is a design question, not a prompt tweak, and changing the prompt
retires the held-out batch.

### 4. Recover re-run attempts

The runs listing returns each run's latest attempt only, so a failure that was re-run
and passed shows up as a pass. `/runs/{id}/attempts/{n}` would recover it. This blocks
flake detection on real repositories.

### 5. Close the loop

The pipeline ends at a patch and its score. The README's design called for opening a
PR or filing a triage summary, a cost budget, and a sandbox with network isolation.
None exists. Do these only after the measurements above hold up.

---

## Done

### Failed jobs that are not Robot runs

Sampling the 34 unparsed jobs showed they were not one thing, so the work split by
shape (`jobs.py`):

- **unittest**: `unittest_extract.py`. 53 jobs, 86 failures, 100% of unittest's own
  count. 37 of those jobs had been misparsed as Robot, so the real count of jobs
  outside Robot was 71, not 34.
- **crash**: `crash.py`. 17 jobs that died on an import error, a syntax error on an
  old interpreter, or a bad Robot flag before any test reported. One job-level record
  each, from the first traceback.
- **unrecognized**: 1 job, GitHub's Copilot review bot. Not a test run; counted
  rather than dropped or forced through a parser.

No pytest logs exist in the corpus, so there is no pytest parser.

### Rule-based classification and flake detection

`classify.py`. Rules fire only on a strong indicator and each result names its rule;
ambiguous roots stay `UNTRIAGED`.

- missing build artifact or file → infrastructure
- missing module, or a stdlib name newer than the interpreter → environment
- assertion, or an actual-against-expected mismatch → regression

`flake.py` reads run history: a test that passed in one job and failed in another of
the same commit, workflow and job name is a flake, and that verdict outranks the root
rules. The Robot corpus has none, because every cached run is a failure.

### The verification target

Resolved: a small repo with deliberately seeded failures. It gives ground truth,
which is what makes the cheat rate measurable. It is also where classifier accuracy
and flake detection are checked.

### Agent, scorer and judge

`agent.py` and `workspace.py` (the sandboxed tool loop), `patchscore.py` (static and
dynamic layers), `judge.py` (the model call), `candidate.py` (per-seed policy,
`--no-oracle`). Run live; results are under Measured baselines.

---

## Open decisions

**Proposal output type.** Not one kind of thing. A missing dependency is a workflow
fix, an assertion mismatch is a test fix, a library change is a source or pin fix.
Category drives proposal type, which is why classification comes before proposal. The
agent is shown the category as a labelled guess (`report.py`) but has no separate
proposal path per category.

**Where the model call goes beyond the judge.** The measured case is the roughly 45%
of roots from `first-line`, plus roots that share no wording (one missing module
surfacing as both "requires PyYAML" and "Variable `<VAR>` not found"). Regexes parse
logs faster and cheaper; the model is for the semantic leap they cannot make. No
model call is used for clustering or classification yet.

---

## Known limits

- Deterministic root extraction cannot merge failures whose text shares no phrase
  with the cause, even when the cause is identical. Recorded in `roots.ROOT_LIMITS`.
- `_MEANINGFUL_DESCRIPTORS` is a substring test, so markup containing "does not"
  would leak through as a root. No such string in the current corpus.
- Large `assertDictEqual` failures make poor roots. The message is a truncated repr
  of two big dicts (`{'spe[224 chars]...[28485 chars]']}]} != {...`), the character
  counts change between runs, and the comparison marker is followed by `{`, so
  `_trim_comparison` does not cut it. 37 occurrences split across 6 roots. Rule
  `exception` reports it with the same confidence as a clean one.
- A crash root of `SyntaxError: invalid syntax` says nothing about which construct;
  the frame with the file and line is dropped on purpose.
- A crash takes the first traceback in the job. A benign traceback printed earlier
  than the real failure would win.
- Robot extraction is 8 failures short of Robot's own tally (65,495 of 65,503). Not
  investigated.
- Flake detection cannot see Robot logs (not parsed), a failure that was re-run and
  passed (only the latest attempt is cached), or a test that prints to stdout
  mid-result-line. See `classify.FLAKE_LIMITS`.
- Cached logs expire. GitHub deletes Actions logs on the repository's retention
  schedule, 90 days by default; `check_log_availability.py` reports what is still
  fetchable before a re-fetch commits to it.
- The `AWS_REGION` setting in `config.py` and `.env.example` is unused; nothing here
  talks to AWS.
- `run_agent.py` reports spend as "1 calls" regardless of turns (it adds each run's
  total as one call, `run_agent.py:113`). The token counts are right.

---

## Don't

- Keep tuning the normalizer. There is another finding like the guard bug every time
  you look, and stages 1-3 are no longer where the project is thin.
- Change a detector or the judge prompt and then report the held-out batch as if it
  were still untouched.
- Commit `data/` (gitignored, about 20MB, re-fetchable from the API).
