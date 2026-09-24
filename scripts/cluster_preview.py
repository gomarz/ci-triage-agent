"""Cluster every cached failure and report what groups with what.

Two axes, because they answer different questions:

  cascade    within one run, how many distinct causes are behind the
             failure count? 6895 failures with one cause is a single
             dependency problem, not 6895 problems.

  recurrence across runs, which causes keep coming back? A cause seen in
             one run is noise; one seen in nine is the thing to fix first.

Coverage is reported against each runner's own tally (Robot's, unittest's),
so truncation shows up as a number instead of looking like clean data. It is
compared like for like: only jobs that printed a tally count on either side.

Usage:
    python scripts/cluster_preview.py [--top 15] [--cascades] [--sig SIG]
                                      [--roots] [--root-sig SIG] [--classify]
                                      [--compression] [--unparsed]
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ci_triage.classify import FLAKE_LIMITS, classify
from ci_triage.jobs import JobShape, parse_job
from ci_triage.logs import diagnostic_body, read_log
from ci_triage.models import FailureCategory

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "data" / "raw" / "logs"

RULE = "=" * 78


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=15, help="Clusters to list.")
    parser.add_argument("--cascades", action="store_true", help="Per-run cascade detail.")
    parser.add_argument("--sig", help="Show every occurrence of one cause signature.")
    parser.add_argument("--roots", action="store_true", help="Root causes, coarser than --top.")
    parser.add_argument("--root-sig", dest="root_sig", help="Inspect one root cluster.")
    parser.add_argument(
        "--compression",
        action="store_true",
        help="Per-job failures -> causes -> roots.",
    )
    parser.add_argument(
        "--classify",
        action="store_true",
        help="Category per root cluster, by rule, plus what is left untriaged.",
    )
    parser.add_argument(
        "--unparsed",
        action="store_true",
        help="List failed jobs that no parser recognized.",
    )
    args = parser.parse_args()

    log_files = sorted(LOGS.glob("*/*.txt"))
    if not log_files:
        print(f"No cached logs under {LOGS}", file=sys.stderr)
        return 1

    # Keyed by job, not run. Each log file is one job, and a matrix run has
    # many; summing jobs while comparing against one job's tally is how
    # coverage read 764%.
    clusters: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    roots: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    per_job: dict[tuple[str, str], list] = {}
    shapes: dict[tuple[str, str], JobShape] = {}
    tallies: dict[tuple[str, str], object] = {}
    unrecognized: list[tuple[str, str, int]] = []

    for path in log_files:
        run_id, job_id = path.parent.name, path.stem
        key = (run_id, job_id)
        text = read_log(path)

        parsed = parse_job(text)
        shapes[key] = parsed.shape

        if parsed.shape is JobShape.CLEAN:
            continue

        if parsed.shape is JobShape.UNRECOGNIZED:
            # Counted rather than dropped, so a log that fits no parser shows
            # up here instead of quietly shrinking the corpus.
            unrecognized.append((run_id, job_id, len(diagnostic_body(text).splitlines())))
            continue

        per_job[key] = parsed.failures
        if parsed.tally:
            tallies[key] = parsed.tally
        for failure in parsed.failures:
            clusters[failure.cause_sig][key].append(failure)
            roots[failure.root_sig][key].append(failure)

    total = sum(len(f) for f in per_job.values())
    runs = {run_id for run_id, _ in per_job}
    shape_counts = Counter(shapes.values())

    print(RULE)
    print(f"logs: {len(log_files)}   no error marker: {shape_counts[JobShape.CLEAN]}")
    print(
        "jobs by shape:   "
        + "   ".join(
            f"{shape.value} {shape_counts[shape]}" for shape in JobShape if shape != JobShape.CLEAN
        )
    )
    print(
        f"failures extracted: {total} across {len(runs)} runs"
        f"   distinct causes: {len(clusters)}   distinct roots: {len(roots)}"
    )
    for shape in (JobShape.ROBOT, JobShape.UNITTEST):
        # A parsed job the runner never counted would pad the numerator, so
        # both sides are restricted to jobs that printed a tally.
        counted = [k for k in tallies if shapes[k] == shape]
        if not counted:
            continue
        reported = sum(tallies[k].failed for k in counted)
        extracted = sum(len(per_job[k]) for k in counted)
        print(
            f"{shape.value}: reported {reported}, extracted {extracted}"
            f" -> coverage {100 * extracted / max(reported, 1):.2f}%"
        )
    print(RULE)

    if args.unparsed:
        print("\nfailed jobs no parser recognized:\n")
        for run_id, job_id, lines in unrecognized:
            print(f"  run {run_id}  job {job_id}  {lines:>6} lines")
        print(f"\n  {len(unrecognized)} total.")
        return 0

    if args.sig:
        group = clusters.get(args.sig)
        if not group:
            print(f"no cluster {args.sig}", file=sys.stderr)
            return 1
        sample = next(iter(group.values()))[0]
        occurrences = sum(len(v) for v in group.values())
        sig_runs = {run_id for run_id, _ in group}
        print(f"\ncause {args.sig}")
        print(f"runs: {len(sig_runs)}   jobs: {len(group)}   occurrences: {occurrences}\n")
        print(sample.message[:2000])
        seen = sorted({f.test_id for fs in group.values() for f in fs})
        print(f"\ntests affected ({len(seen)}):")
        for test_id in seen[:40]:
            print(f"    {test_id}")
        if len(seen) > 40:
            print(f"    ... and {len(seen) - 40} more")
        return 0

    if args.root_sig:
        group = roots.get(args.root_sig)
        if not group:
            print(f"no root cluster {args.root_sig}", file=sys.stderr)
            return 1
        members = [f for fs in group.values() for f in fs]
        sample = members[0]
        sig_runs = {run_id for run_id, _ in group}
        print(f"\nroot {args.root_sig}   rule: {sample.root_rule}")
        print(f"runs: {len(sig_runs)}   jobs: {len(group)}   occurrences: {len(members)}")
        print(f"\nextracted root:\n  {sample.root[:400]}\n")
        print("distinct causes beneath:")
        by_cause: dict[str, list] = defaultdict(list)
        for failure in members:
            by_cause[failure.cause_sig].append(failure)
        for cause_sig, items in sorted(by_cause.items(), key=lambda kv: -len(kv[1]))[:10]:
            print(f"  {cause_sig}  {len(items):>6} occ  {items[0].headline[:80]}")
        print(f"\n({len(by_cause)} causes, {len({f.test_id for f in members})} tests)")
        return 0

    if args.compression:
        print("\nper job: failures -> causes -> roots\n")
        for (run_id, job_id), failures in sorted(per_job.items(), key=lambda kv: -len(kv[1])):
            causes = len({f.cause_sig for f in failures})
            root_count = len({f.root_sig for f in failures})
            if len(failures) < 5:
                continue
            print(
                f"  {run_id}/{job_id}  {len(failures):>5} -> {causes:>4} causes"
                f" -> {root_count:>4} roots"
                f"   ({len(failures) / max(root_count, 1):.0f}x)"
            )
        return 0

    if args.roots:
        print("\ntop roots by number of runs affected:\n")
        ranked_roots = sorted(
            roots.items(), key=lambda kv: (-len({r for r, _ in kv[1]}), -len(kv[1]))
        )
        for sig, group in ranked_roots[: args.top]:
            occurrences = sum(len(v) for v in group.values())
            sample = next(iter(group.values()))[0]
            causes = len({f.cause_sig for fs in group.values() for f in fs})
            sig_runs = {run_id for run_id, _ in group}
            print(
                f"  {sig}  {len(sig_runs):>3} runs  {occurrences:>6} occ"
                f"  {causes:>4} causes  [{sample.root_rule}]"
            )
            print(f"      {(sample.root or '(no root extracted)')[:100]}")

        # Occurrences and distinct roots both matter: one collapsed suite can
        # put 87% of occurrences behind a single rule while that rule accounts
        # for a small share of the actual roots found.
        by_rule: dict[str, int] = defaultdict(int)
        rule_roots: dict[str, set] = defaultdict(set)
        for failures in per_job.values():
            for failure in failures:
                by_rule[failure.root_rule] += 1
                rule_roots[failure.root_rule].add(failure.root_sig)
        print("\nextraction rule:      occurrences        distinct roots")
        for rule, count in sorted(by_rule.items(), key=lambda kv: -kv[1]):
            share = 100 * count / max(total, 1)
            n_roots = len(rule_roots[rule])
            root_share = 100 * n_roots / max(len(roots), 1)
            print(
                f"  {rule:<16} {count:>8}  ({share:>2.0f}%)"
                f"      {n_roots:>4}  ({root_share:>2.0f}%)"
            )
        print("\n  (inspect one with --root-sig <signature>)")
        return 0

    if args.classify:
        # Same root, same category, so classify one sample per root.
        by_category: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        by_rule: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
        untriaged: list[tuple[int, str]] = []
        for group in roots.values():
            members = [f for fs in group.values() for f in fs]
            result = classify(members[0])
            for tally in (by_category[result.category], by_rule[(result.category, result.rule)]):
                tally[0] += len(members)
                tally[1] += 1
            if result.category == FailureCategory.UNTRIAGED:
                untriaged.append((len(members), members[0].root or "(no root extracted)"))

        # Roots are the honest denominator. One collapsed suite is most of the
        # occurrences, so an occurrence share mostly reports that one root.
        print("\ncategory        roots            occurrences\n")
        for category, (occ, n_roots) in sorted(by_category.items(), key=lambda kv: -kv[1][1]):
            print(
                f"  {category:<16}{n_roots:>4} ({100 * n_roots / len(roots):>2.0f}%)"
                f"     {occ:>7} ({100 * occ / total:>2.0f}%)"
            )
        print("\nby rule:\n")
        for (category, rule), (occ, n_roots) in sorted(by_rule.items(), key=lambda kv: -kv[1][1]):
            print(f"  {category:<16}{rule:<26}{n_roots:>4} roots  {occ:>7} occ")
        print(f"\nleft for a model, largest first (top {args.top}):\n")
        for occ, root in sorted(untriaged, reverse=True)[: args.top]:
            print(f"  {occ:>6}  {root[:100]}")
        print(f"\n  flake: not assigned. {FLAKE_LIMITS.splitlines()[0]} ...")
        return 0

    if args.cascades:
        print("\ncascade ratio per job (extracted -> distinct causes):\n")
        for (run_id, job_id), failures in sorted(per_job.items(), key=lambda kv: -len(kv[1])):
            causes = {f.cause_sig for f in failures}
            tally = tallies.get((run_id, job_id))
            note = ""
            if tally:
                note = f"  robot said {tally.failed}"
                if len(failures) < tally.failed * 0.9:
                    note += "  [UNDER-EXTRACTED]"
            flag = "  <-- cascade" if len(failures) >= 10 and len(causes) <= 3 else ""
            print(
                f"  {run_id}/{job_id}  {len(failures):>5} extracted -> "
                f"{len(causes):>4} causes{note}{flag}"
            )
        return 0

    # Ranked by distinct runs, not occurrences: one run where the whole suite
    # collapsed would otherwise own every top slot on volume alone.
    print("\ntop causes by number of runs affected:\n")
    ranked = sorted(
        clusters.items(),
        key=lambda kv: (-len({r for r, _ in kv[1]}), -len(kv[1])),
    )
    for sig, group in ranked[: args.top]:
        occurrences = sum(len(v) for v in group.values())
        sample = next(iter(group.values()))[0]
        tests = {f.test_id for fs in group.values() for f in fs}
        sig_runs = {run_id for run_id, _ in group}
        print(
            f"  {sig}  {len(sig_runs):>3} runs  {len(group):>4} jobs  "
            f"{occurrences:>6} occ  {len(tests):>4} tests"
        )
        print(f"      {sample.headline[:100]}")
    print("\n  (inspect one with --sig <signature>)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
