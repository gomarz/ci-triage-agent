"""Score the classifier against the testbed's labelled seeds.

    DATA_DIR=data/testbed python scripts/score_classifier.py \
        --manifest ../ci-triage-testbed/seeds/manifest.json

One row per seed, since one seed is one cause. See ci_triage.accuracy for why
abstaining is not counted as wrong, and for what this score cannot claim.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ci_triage.accuracy import Verdict, score_corpus, seed_results, tally  # noqa: E402
from ci_triage.config import load_settings  # noqa: E402

RULE = "=" * 78


def _cell(classification, verdict: Verdict) -> str:
    mark = {Verdict.CORRECT: "ok", Verdict.WRONG: "WRONG", Verdict.ABSTAINED: "abstain"}[verdict]
    return f"{classification.category.value} ({classification.rule}) [{mark}]"


def _summary(name: str, counts) -> None:
    total = sum(counts.values())
    answered = counts[Verdict.CORRECT] + counts[Verdict.WRONG]
    right = f"{counts[Verdict.CORRECT]}/{answered}" if answered else "n/a"
    print(
        f"  {name:<14} correct {counts[Verdict.CORRECT]}  wrong {counts[Verdict.WRONG]}"
        f"  abstained {counts[Verdict.ABSTAINED]}   answers {answered}/{total}, right {right}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True, help="testbed seeds/manifest.json")
    args = parser.parse_args()

    score = score_corpus(load_settings().data_dir, args.manifest)
    if not score.failures:
        print("No failures on seed/* branches in the cache.", file=sys.stderr)
        return 1
    results = seed_results(score.failures)

    print(RULE)
    for r in results:
        print(
            f"\n{r.seed_id}   expected {r.expected.value}   ({r.runs} runs, {r.failures} failures)"
        )
        print(f"  wording alone: {_cell(r.by_wording, r.wording_verdict)}")
        print(f"  with history:  {_cell(r.with_history, r.history_verdict)}")

    print(f"\n{RULE}\nper seed ({len(results)} seeds):\n")
    _summary("wording alone", tally(results, history=False))
    _summary("with history", tally(results, history=True))

    if score.unobserved:
        print(f"\nseeds with no cached failing run, not scored: {', '.join(score.unobserved)}")
    if score.extraction_mismatches:
        print("\nextracted failing tests differ from the manifest (score may be unreliable):")
        for item in score.extraction_mismatches:
            print(f"  {item}")
    else:
        print("\nextraction: failing tests match the manifest in every scored run")
    print("\nlabels were written by someone who had read the rules: a check, not a benchmark.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
