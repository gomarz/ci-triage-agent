"""Score candidate patches against a testbed seed, or score the scorer itself.

    # judge patches an agent proposed for one seed
    python scripts/score_patch.py --testbed ../ci-triage-testbed --seed s01-discount-rounding a.diff

    # check the scorer against the testbed's labelled cheat and honest patches
    python scripts/score_patch.py --testbed ../ci-triage-testbed --suite [--static-only]

The suite is the test of the scorer: every labelled cheat must be caught, for the
right reason, and every honest fix must come back clean. `--static-only` skips
running CI, which shows how much the diff patterns catch without the dynamic
checks (fewer tests run, more skipped).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ci_triage.patchrun import try_patch  # noqa: E402
from ci_triage.patchscore import (  # noqa: E402
    PatchScore,
    Policy,
    Verdict,
    cheat_rate,
    score_patch,
)

RULE = "=" * 78


def load_manifest(testbed: Path) -> list[dict]:
    return json.loads((testbed / "seeds" / "manifest.json").read_text(encoding="utf-8"))["seeds"]


def policy_for(testbed: Path, seed: dict) -> Policy:
    inject = (testbed / "seeds" / seed["id"] / "inject.patch").read_text(encoding="utf-8")
    return Policy(
        fix_paths=frozenset(seed["fix_paths"]),
        cheats=frozenset(seed["cheats"]),
        test_edit_legitimate=seed["test_edit_is_legitimate"],
        inject_diff=inject,
    )


def score_file(
    testbed: Path, seed: dict, patch: Path, *, static_only: bool, baseline
) -> PatchScore:
    text = patch.read_text(encoding="utf-8")
    run = None if static_only else try_patch(testbed, seed["id"], patch)
    return score_patch(text, policy_for(testbed, seed), run=run, baseline=baseline)


def describe(score: PatchScore) -> str:
    kinds = ", ".join(sorted({f.kind for f in score.flags})) or "-"
    ci = ""
    if score.ci is not None:
        ci = "  CI green" if score.green else f"  CI red ({score.ci.failed_step})"
    return f"{score.verdict.value:<8}{ci}  flags: {kinds}"


def run_candidates(args: argparse.Namespace) -> int:
    seed = next((s for s in load_manifest(args.testbed) if s["id"] == args.seed), None)
    if seed is None:
        print(f"unknown seed {args.seed}", file=sys.stderr)
        return 1
    baseline = None if args.static_only else try_patch(args.testbed, seed["id"], None)
    scores = []
    for patch in args.patches:
        score = score_file(
            args.testbed, seed, patch, static_only=args.static_only, baseline=baseline
        )
        scores.append(score)
        print(f"{patch.name}: {describe(score)}")
        for flag in score.flags:
            print(f"    [{flag.severity.value}] {flag.kind} in {flag.path}: {flag.evidence}")
    cheats, suspects, green = cheat_rate(scores)
    print(f"\ngreen patches: {green}   cheats: {cheats}   suspects: {suspects}")
    return 0


def run_suite(args: argparse.Namespace) -> int:
    rows = []  # (seed id, name, label, score)
    for seed in load_manifest(args.testbed):
        baseline = None if args.static_only else try_patch(args.testbed, seed["id"], None)
        folder = args.testbed / "seeds" / seed["id"]
        cases = [("fix.patch", "fix", None)]
        cases += [(f, "honest", None) for f in seed["honest_patches"]]
        cases += [(p["file"], "cheat", p["kind"]) for p in seed["cheat_patches"]]
        for file, label, kind in cases:
            score = score_file(
                args.testbed, seed, folder / file, static_only=args.static_only, baseline=baseline
            )
            rows.append((seed["id"], file, label, kind, score))
            print(f"  {seed['id'][:3]} {file:<34} {label:<7} {describe(score)}")

    tuned = [r for r in rows if not r[1].startswith("heldout/")]
    held = [r for r in rows if r[1].startswith("heldout/")]
    ok = [_report("tuned: batches 1 and 2, used to build the detectors", tuned)]
    ok.append(_report("SEALED HELD-OUT: batch 3, scored after the detectors were final", held))
    return 0 if all(ok) else 1


def _report(title: str, rows: list) -> bool:
    honest = [r for r in rows if r[2] != "cheat"]
    cheats = [r for r in rows if r[2] == "cheat"]
    right_reason = [r for r in cheats if any(r[3] in f.classes for f in r[4].flags)]
    flagged = [r for r in cheats if r[4].verdict is not Verdict.CLEAN]
    hard = [r for r in cheats if r[4].verdict is Verdict.CHEAT]
    false_positive = [r for r in honest if r[4].verdict is not Verdict.CLEAN]

    print(f"\n{RULE}\n{title}: {len(cheats)} cheats, {len(honest)} honest fixes\n")
    print(f"  cheats flagged at all                  {len(flagged)}/{len(cheats)}")
    print(f"  cheats flagged for the right reason    {len(right_reason)}/{len(cheats)}")
    print(f"  cheats called CHEAT (not just suspect) {len(hard)}/{len(cheats)}")
    print(f"  honest fixes wrongly flagged           {len(false_positive)}/{len(honest)}")
    for r in cheats:
        if r not in right_reason:
            print(f"  MISSED  {r[0]} {r[1]}  wanted {r[3]}, got {describe(r[4])}")
    for r in false_positive:
        print(f"  FALSE POSITIVE  {r[0]} {r[1]}  {describe(r[4])}")
    return len(right_reason) == len(cheats) and not false_positive


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--testbed", type=Path, required=True)
    parser.add_argument("--static-only", action="store_true", help="skip CI; diff patterns only")
    parser.add_argument("--suite", action="store_true", help="score the testbed's labelled patches")
    parser.add_argument("--seed")
    parser.add_argument("patches", nargs="*", type=Path)
    args = parser.parse_args()
    if args.suite:
        return run_suite(args)
    if not args.seed or not args.patches:
        parser.error("give --seed and one or more patches, or --suite")
    return run_candidates(args)


if __name__ == "__main__":
    raise SystemExit(main())
