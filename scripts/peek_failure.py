"""Print the actual failure region from cached logs.

Anchors on ##[error] rather than step names, because the ##[group] labels
in a raw job log are commands, not the step names the API reports.

Usage:
    python scripts/peek_failure.py                  # error regions, 3 runs
    python scripts/peek_failure.py --groups         # what steps actually ran
    python scripts/peek_failure.py --run 33650007649 --before 80
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ci_triage.config import load_settings  # noqa: E402
from ci_triage.logs import failure_regions, group_inventory, read_log  # noqa: E402

LOGS = load_settings().data_dir / "raw" / "logs"

RULE = "=" * 78


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", help="Specific run id. Default: newest cached.")
    parser.add_argument("--count", type=int, default=3, help="How many runs to show.")
    parser.add_argument("--before", type=int, default=40, help="Lines before each error.")
    parser.add_argument("--after", type=int, default=5, help="Lines after each error.")
    parser.add_argument(
        "--groups",
        action="store_true",
        help="List the ##[group] labels instead of failure regions.",
    )
    parser.add_argument(
        "--teardown",
        action="store_true",
        help="Include post-job cleanup, normally dropped as noise.",
    )
    args = parser.parse_args()

    dirs = sorted(LOGS.glob("*"), key=lambda p: p.name, reverse=True)
    if args.run:
        dirs = [d for d in dirs if d.name == args.run]
    if not dirs:
        print(f"No cached logs under {LOGS}", file=sys.stderr)
        return 1

    shown = 0
    for run_dir in dirs:
        if shown >= args.count:
            break

        for log_path in sorted(run_dir.glob("*.txt")):
            text = read_log(log_path)

            print(RULE)
            print(f"run {run_dir.name}  job {log_path.stem}  ({len(text):,} chars)")
            print(RULE)

            if args.groups:
                for i, (label, count) in enumerate(group_inventory(text)):
                    print(f"  {i:>3}  {count:>6} lines  {label}")
                print()
                shown += 1
                break

            regions = failure_regions(
                text,
                before=args.before,
                after=args.after,
                include_teardown=args.teardown,
            )
            if not regions:
                print("  no ##[error] markers found; try --groups\n")
                shown += 1
                break

            for i, (label, lines) in enumerate(regions, 1):
                print(f"--- region {i}/{len(regions)}: {label[:70]}")
                print("\n".join(lines))
                print()

            shown += 1
            break

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
