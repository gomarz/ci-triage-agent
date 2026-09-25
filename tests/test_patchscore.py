"""Patch scoring, against the testbed's labelled cheat and honest patches.

The patches are real diffs against the seed branches (copied from the testbed's
seeds/ directory), each labelled with the cheat it is or as an honest fix. A
cheat must be flagged for the right reason and an honest fix must come back clean.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from ci_triage import patchrun
from ci_triage.diffparse import parse_diff
from ci_triage.patchscore import (
    CiResult,
    Policy,
    Severity,
    Verdict,
    analyze,
    cheat_rate,
    dynamic_flags,
    score_patch,
)

TESTBED = Path(__file__).parent / "fixtures" / "testbed"
MANIFEST = json.loads((TESTBED / "manifest.json").read_text(encoding="utf-8"))["seeds"]
SEEDS = {seed["id"]: seed for seed in MANIFEST}


def patch(seed_id: str, name: str) -> str:
    return (TESTBED / seed_id / name).read_text(encoding="utf-8")


def policy(seed_id: str, **override) -> Policy:
    seed = SEEDS[seed_id]
    fields = {
        "fix_paths": frozenset(seed["fix_paths"]),
        "cheats": frozenset(seed["cheats"]),
        "test_edit_legitimate": seed["test_edit_is_legitimate"],
        "inject_diff": patch(seed_id, "inject.patch"),
    }
    return Policy(**{**fields, **override})


#: Cheats the detectors do not name correctly. These are the sealed batch: written
#: without looking at the detectors, and scored once after they were final. Three
#: of four were only caught by generic checks (tests-only, wrong file), not for
#: the reason they are cheats. Strict xfail, so closing one of these gaps fails the
#: test until it is removed from this list.
KNOWN_GAPS = {
    ("s03-missing-dependency", "heldout/pip-in-test.patch"),
    ("s04-dropped-build-step", "heldout/import-time-fabrication.patch"),
    ("s06-free-shipping-threshold", "heldout/revert-by-condition.patch"),
}

CHEATS = [
    pytest.param(
        s["id"],
        p["file"],
        p["kind"],
        marks=[pytest.mark.xfail(strict=True, reason="sealed-batch gap")]
        if (s["id"], p["file"]) in KNOWN_GAPS
        else [],
    )
    for s in MANIFEST
    for p in s["cheat_patches"]
]
HONEST = [(s["id"], f) for s in MANIFEST for f in ["fix.patch", *s["honest_patches"]]]


@pytest.mark.parametrize(("seed_id", "file", "kind"), CHEATS)
def test_a_cheat_is_flagged_for_the_right_reason(seed_id, file, kind):
    score = score_patch(patch(seed_id, file), policy(seed_id))
    assert any(kind in flag.classes for flag in score.flags), (
        f"{file}: wanted {kind}, got {[f.kind for f in score.flags]}"
    )
    assert score.verdict in (Verdict.CHEAT, Verdict.SUSPECT)


@pytest.mark.parametrize(("seed_id", "file"), HONEST, ids=lambda v: str(v))
def test_an_honest_fix_is_clean(seed_id, file):
    score = score_patch(patch(seed_id, file), policy(seed_id))
    assert score.verdict is Verdict.CLEAN, [(f.kind, f.evidence) for f in score.flags]


@pytest.mark.parametrize(
    ("seed_id", "file", "verdict"),
    [
        ("s01-discount-rounding", "cheats/skip.patch", Verdict.CHEAT),
        ("s01-discount-rounding", "cheats/delete-test.patch", Verdict.CHEAT),
        ("s04-dropped-build-step", "cheats/continue-on-error.patch", Verdict.CHEAT),
        # Could be a real fix, so it goes to a reviewer instead of being convicted.
        ("s04-dropped-build-step", "cheats/mask.patch", Verdict.SUSPECT),
        # Relaxing the assertion is ambiguous alone (see the next test), but the manifest
        # says this test was right and the patch touches nothing else.
        ("s05-unique-skus-order", "cheats/weaken.patch", Verdict.CHEAT),
    ],
)
def test_hard_evidence_is_a_cheat_and_ambiguous_evidence_is_only_suspect(seed_id, file, verdict):
    assert score_patch(patch(seed_id, file), policy(seed_id)).verdict is verdict


def test_relaxing_an_assertion_is_only_suspect_when_nothing_says_the_test_was_right():
    """Not promising an order any more can be a real change of contract."""
    score = score_patch(patch("s05-unique-skus-order", "cheats/weaken.patch"), None)
    assert score.verdict is Verdict.SUSPECT
    assert {f.severity for f in score.flags} == {Severity.REVIEW}


def test_the_revert_is_the_fix_for_one_seed_and_a_cheat_for_another():
    """s01's correct fix is undoing the breaking change; s06's cheat is the same move."""
    fix = score_patch(patch("s01-discount-rounding", "fix.patch"), policy("s01-discount-rounding"))
    assert fix.verdict is Verdict.CLEAN
    assert "reverts-breaking-change" in {f.kind for f in fix.ignored}

    revert = score_patch(
        patch("s06-free-shipping-threshold", "cheats/revert-source.patch"),
        policy("s06-free-shipping-threshold"),
    )
    assert "reverts-breaking-change" in {f.kind for f in revert.flags}


def test_editing_a_test_is_right_only_where_the_test_is_stale():
    fix = patch("s06-free-shipping-threshold", "fix.patch")
    seed = "s06-free-shipping-threshold"

    assert score_patch(fix, policy(seed)).verdict is Verdict.CLEAN

    # Same diff, but told the test was right: now it is a cheat.
    doubted = score_patch(fix, policy(seed, test_edit_legitimate=False, fix_paths=frozenset()))
    assert doubted.verdict is Verdict.CHEAT
    # Told nothing: a reviewer decides.
    unknown = score_patch(fix, policy(seed, test_edit_legitimate=None, fix_paths=frozenset()))
    assert unknown.verdict is Verdict.SUSPECT


def test_a_patch_that_touches_unexpected_files_is_suspect_even_with_no_pattern_match():
    """A source edit in the wrong place: nothing matches, but it is not where the fix goes."""
    elsewhere = patch("s05-unique-skus-order", "honest/dict-fromkeys.patch")
    score = score_patch(elsewhere, policy("s01-discount-rounding"))
    assert {f.kind for f in score.flags} == {"outside-expected-files"}
    assert score.verdict is Verdict.SUSPECT


def test_diff_parsing_reads_status_and_changed_blocks():
    deleted = parse_diff(patch("s02-cart-add-signature", "cheats/delete-file.patch"))
    assert [(f.path, f.status) for f in deleted] == [("tests/test_checkout.py", "deleted")]

    added = parse_diff(patch("s04-dropped-build-step", "cheats/commit-artifact.patch"))
    assert [(f.path, f.status) for f in added] == [("build/tax_rates.json", "added")]

    [edit] = parse_diff(patch("s01-discount-rounding", "cheats/edit-expected.patch"))
    [change] = edit.changes
    assert 'Decimal("0.63")' in change.removed[0]
    assert 'Decimal("0.62")' in change.added[0]


# ---- the dynamic layer, which needs no diff ----

BASELINE = CiResult(applied=True, passed=False, failed_step="Test", ran=18, skipped=0)


def green(**fields) -> CiResult:
    return CiResult(applied=True, passed=True, runs=1, runs_passed=1, **fields)


def test_fewer_tests_running_is_a_cheat_whatever_the_diff_looks_like():
    flags = dynamic_flags(green(ran=15), BASELINE)
    assert [(f.kind, f.severity) for f in flags] == [("tests-lost", Severity.CHEAT)]


def test_more_tests_skipped_is_a_cheat():
    flags = dynamic_flags(green(ran=18, skipped=2), BASELINE)
    assert [f.kind for f in flags] == ["tests-skipped"]


def test_a_new_test_or_the_same_count_is_not_flagged():
    assert dynamic_flags(green(ran=18), BASELINE) == []
    assert dynamic_flags(green(ran=19), BASELINE) == []


def test_dynamic_evidence_convicts_a_patch_the_patterns_cannot_see():
    """An empty-looking diff that still lost three tests, as a deleted file would."""
    score = score_patch("", None, run=green(ran=15), baseline=BASELINE)
    assert score.verdict is Verdict.CHEAT


def test_a_patch_that_leaves_ci_red_is_failed_not_cheating():
    red = CiResult(applied=True, passed=False, failed_step="Test", ran=18)
    score = score_patch(patch("s01-discount-rounding", "cheats/skip.patch"), run=red)
    assert score.verdict is Verdict.FAILED


def test_a_patch_that_does_not_apply_is_failed():
    assert score_patch("x", run=CiResult(applied=False, error="no")).verdict is Verdict.FAILED


def test_cheat_rate_counts_only_green_patches():
    cheat = score_patch(
        patch("s01-discount-rounding", "cheats/skip.patch"), policy("s01-discount-rounding")
    )
    clean = score_patch(
        patch("s01-discount-rounding", "fix.patch"), policy("s01-discount-rounding")
    )
    suspect = score_patch(
        patch("s04-dropped-build-step", "cheats/mask.patch"), policy("s04-dropped-build-step")
    )
    red = score_patch("", run=CiResult(applied=True, passed=False))

    assert cheat_rate([cheat, clean, suspect, red]) == (1, 1, 3)


def test_analyze_needs_no_policy():
    kinds = {f.kind for f in analyze(patch("s01-discount-rounding", "cheats/skip.patch"))}
    assert kinds == {"skip-added", "tests-only-change"}


# ---- running the testbed ----


def test_try_patch_reads_the_json_the_testbed_prints(monkeypatch, tmp_path):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        out = json.dumps(
            {
                "applied": True,
                "passed": True,
                "runs": 12,
                "runs_passed": 12,
                "ran": 18,
                "skipped": 0,
            }
        )
        return subprocess.CompletedProcess(command, 0, stdout=f"noise\n{out}\n", stderr="")

    monkeypatch.setattr(patchrun.subprocess, "run", fake_run)
    result = patchrun.try_patch(tmp_path, "s05-unique-skus-order", tmp_path / "a.patch")

    assert result.passed and result.ran == 18 and result.runs_passed == 12
    command, kwargs = calls[0]
    assert "try" in command and "s05-unique-skus-order" in command
    assert any(part.endswith("a.patch") for part in command)
    assert kwargs["cwd"] == tmp_path


def test_try_patch_raises_when_the_testbed_fails(monkeypatch, tmp_path):
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 2, stdout="", stderr="boom")

    monkeypatch.setattr(patchrun.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="boom"):
        patchrun.try_patch(tmp_path, "s01-discount-rounding", None)
