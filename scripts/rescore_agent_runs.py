"""Re-score the patches `run_agent.py` saved, without re-running the agent.

    python scripts/rescore_agent_runs.py --testbed ../ci-triage-testbed --judge --confirm-spend

`score_patch.py` takes one seed and an explicit list of patch files, and neither cmd nor
PowerShell expands a glob for a native program, so this walks `data/agent_runs/<seed>/*/`
and calls it once per seed. CI re-runs locally and is free; only `--judge` spends, and it
refuses without `--confirm-spend`. Extra flags go straight through to `score_patch.py`.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SCORE_PATCH = Path(__file__).resolve().parent / "score_patch.py"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--testbed", type=Path, required=True)
    parser.add_argument("--runs", type=Path, default=Path("data/agent_runs"))
    parser.add_argument("--seed", help="only this seed id")
    args, passthrough = parser.parse_known_args()

    seed_dirs = sorted(p for p in args.runs.iterdir() if p.is_dir())
    if args.seed:
        seed_dirs = [p for p in seed_dirs if p.name == args.seed]
    if not seed_dirs:
        sys.exit(f"no saved runs under {args.runs}")

    failed = 0
    for seed_dir in seed_dirs:
        patches = sorted(seed_dir.glob("*/patch.diff"))
        if not patches:
            continue
        print(f"\n##### {seed_dir.name}", flush=True)
        # --no-oracle matches run_agent.py, whose default scoring drops the manifest hints.
        cmd = [
            sys.executable,
            str(SCORE_PATCH),
            "--testbed",
            str(args.testbed),
            "--seed",
            seed_dir.name,
            "--no-oracle",
            *passthrough,
            *map(str, patches),
        ]
        failed += subprocess.run(cmd, check=False).returncode != 0
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
