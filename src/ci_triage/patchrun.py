"""Run a candidate patch through the testbed's CI and read the result.

The testbed owns how CI is run (`tools/seeds.py try`, which applies the patch to
the seed's failing tree and runs the workflow's steps), so this only calls it and
parses the JSON it prints. That keeps the two repos joined by a command-line
contract instead of an import, and lets the same scorer work against real CI
later by swapping this function.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from ci_triage.patchscore import CiResult


def try_patch(
    testbed: Path, seed_id: str, patch: Path | None, *, runs: int = 12, timeout: int = 900
) -> CiResult:
    """CI outcome for `patch` on `seed_id`; with patch None, the failing tree itself.

    A flaky seed is run `runs` times under different hash seeds and counts as
    green when nearly all pass (the testbed decides the bar).
    """
    command = [sys.executable, "tools/seeds.py", "try", seed_id, "--runs", str(runs)]
    if patch is not None:
        command.insert(4, str(patch.resolve()))
    proc = subprocess.run(
        command, cwd=testbed, capture_output=True, text=True, timeout=timeout, check=False
    )
    if proc.returncode != 0:
        raise RuntimeError(f"testbed try failed for {seed_id}: {proc.stderr.strip()[-500:]}")
    return CiResult.model_validate(json.loads(proc.stdout.strip().splitlines()[-1]))
