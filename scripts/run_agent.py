"""Run the patch-proposing agent on testbed seeds and score what it writes.

    python scripts/run_agent.py --testbed ../ci-triage-testbed --seed all --mode both \\
        --repeats 3 --confirm-spend

For each (seed, mode, repeat) it exports the seed's failing tree into a fresh temporary
git repo (no history, no fixes, no harness files), hands the agent the failure report the
pipeline made from the cached log, lets it work with its tools, takes `git diff` as the
patch, runs that patch through the testbed's CI, and scores it with no manifest hints.

This calls the API and costs money in proportion to seeds x modes x repeats x turns, so it
does nothing without `--confirm-spend`. Everything the run produced is written under
`--out` (patch, transcript, score) so it can be read afterwards: the numbers alone are not
the point. `labels.tsv` is a blank sheet for a person to mark each patch fix or cheat, the
only honest benchmark for the agent and for the judge, since nobody tuned anything to
patches the agent wrote.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ci_triage.agent import MODES, run_agent  # noqa: E402
from ci_triage.candidate import SeedContext, load_manifest, policy_for  # noqa: E402
from ci_triage.config import load_settings  # noqa: E402
from ci_triage.judge import make_judge  # noqa: E402
from ci_triage.llm import DEFAULT_MODEL, AnthropicModel, Usage  # noqa: E402
from ci_triage.patchrun import try_patch  # noqa: E402
from ci_triage.patchscore import cheat_rate, score_patch  # noqa: E402
from ci_triage.report import build_report  # noqa: E402
from ci_triage.workspace import Workspace, ci_via_testbed  # noqa: E402


def export(testbed: Path, seed_id: str, dest: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "tools/seeds.py", "export", seed_id, str(dest)],
        cwd=testbed,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"export failed: {proc.stderr[-300:]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--testbed", type=Path, required=True)
    parser.add_argument("--seed", default="all", help="a seed id, or all")
    parser.add_argument("--mode", default="both", choices=[*MODES, "both"])
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--max-turns", type=int, default=30)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--effort", default="high")
    parser.add_argument("--judge", action="store_true", help="also ask a model about each patch")
    parser.add_argument("--oracle", action="store_true", help="give the scorer the manifest hints")
    parser.add_argument("--out", type=Path, default=Path("data/agent_runs"))
    parser.add_argument("--judge-cache", type=Path, default=Path("data/judge_cache"))
    parser.add_argument("--confirm-spend", action="store_true", help="agree to API charges")
    args = parser.parse_args()

    seeds = [s for s in load_manifest(args.testbed) if args.seed in ("all", s["id"])]
    if not seeds:
        sys.exit(f"no such seed: {args.seed}")
    modes = list(MODES) if args.mode == "both" else [args.mode]
    planned = len(seeds) * len(modes) * args.repeats
    if not args.confirm_spend:
        print(
            f"{planned} agent runs planned ({len(seeds)} seeds x {len(modes)} modes x "
            f"{args.repeats} repeats, up to {args.max_turns} turns each) on {args.model}."
        )
        print("Nothing was run. Pass --confirm-spend to go ahead; this costs money.")
        return 2

    model = AnthropicModel(model=args.model, effort=args.effort)
    data_dir = load_settings().data_dir
    spend = Usage()
    outcomes: dict[str, list] = {mode: [] for mode in modes}

    for seed in seeds:
        report = build_report(data_dir, f"seed/{seed['id']}")
        policy = policy_for(args.testbed, seed, oracle=args.oracle)
        baseline = try_patch(args.testbed, seed["id"], None)
        with SeedContext(args.testbed, seed["id"]) as ctx:
            judge = (
                make_judge(
                    model,
                    report,
                    ctx.files_for,
                    cache_dir=args.judge_cache,
                    model_name=args.model,
                    spend=spend,
                )
                if args.judge
                else None
            )
            for mode in modes:
                for n in range(1, args.repeats + 1):
                    label = f"{seed['id']}/{mode}-{n}"
                    with tempfile.TemporaryDirectory(prefix="agent-") as tmp:
                        work = Path(tmp) / "repo"
                        export(args.testbed, seed["id"], work)
                        ws = Workspace(work, ci_via_testbed(args.testbed, work, Path(tmp) / "venv"))
                        run = run_agent(model, ws, report, mode=mode, max_turns=args.max_turns)
                    spend.add(run.usage.input_tokens, run.usage.output_tokens)

                    out = args.out / seed["id"] / f"{mode}-{n}"
                    out.mkdir(parents=True, exist_ok=True)
                    (out / "patch.diff").write_text(run.diff, encoding="utf-8", newline="\n")
                    ci = (
                        try_patch(args.testbed, seed["id"], (out / "patch.diff"))
                        if run.diff
                        else None
                    )
                    score = (
                        score_patch(run.diff, policy, run=ci, baseline=baseline, judge=judge)
                        if ci
                        else None
                    )
                    (out / "transcript.json").write_text(
                        json.dumps(
                            {
                                "outcome": run.outcome,
                                "turns": run.turns,
                                "ci_runs": run.ci_runs,
                                "summary": run.summary,
                                "transcript": run.transcript,
                            },
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    (out / "score.json").write_text(
                        score.model_dump_json(indent=2) if score else "{}", encoding="utf-8"
                    )
                    verdict = score.verdict.value if score else "no patch"
                    print(
                        f"{label:<44} {run.outcome:<10} turns={run.turns:<3} "
                        f"ci_runs={run.ci_runs:<2} -> {verdict}",
                        flush=True,
                    )
                    if score:
                        outcomes[mode].append(score)

    print(f"\n{'=' * 78}")
    for mode in modes:
        scores = outcomes[mode]
        cheats, suspects, green = cheat_rate(scores)
        counts = Counter(s.verdict.value for s in scores)
        print(f"mode {mode!r}: {len(scores)} patches -> {dict(counts)}")
        print(
            f"   green {green}, cheats {cheats}, suspects {suspects}"
            + (f", cheat rate {cheats}/{green}" if green else "")
        )
    print(
        f"\nspend: {spend.calls} calls, {spend.input_tokens} input, "
        f"{spend.output_tokens} output tokens"
    )

    sheet = args.out / "labels.tsv"
    rows = sorted(p.parent for p in args.out.glob("*/*/patch.diff"))
    sheet.write_text(
        "run\tyour_label (fix|cheat|unsure)\tnote\n"
        + "".join(f"{p.relative_to(args.out).as_posix()}\t\t\n" for p in rows),
        encoding="utf-8",
    )
    print(f"label sheet: {sheet}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
