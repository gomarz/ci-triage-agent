from __future__ import annotations

import copy
import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from ci_triage.logs import read_log

FIXTURES = Path(__file__).parent / "fixtures"
LOG_FIXTURES = FIXTURES / "logs"


@pytest.fixture
def log() -> Callable[[str], str]:
    """Load a log fixture the way production does, timestamps intact.

    The fixtures are line ranges cut from real cached logs, so they carry the
    runner's timestamps and separator widths. Going through read_log keeps
    line endings the same as a fresh cache read, whatever git did to them.
    """

    def load(name: str) -> str:
        return read_log(LOG_FIXTURES / name)

    return load


@pytest.fixture
def make_cache(tmp_path: Path) -> Callable[..., Path]:
    """Build a data dir from log fixtures: one run and one job per (run id, fixture).

    All runs share one commit and workflow, so they are comparable, as repeat
    runs of one commit are. A job's id is its run id times ten.
    """

    def build(runs: list[tuple[int, str]], *, branch: str = "main") -> Path:
        template = json.loads((FIXTURES / "runs.json").read_text(encoding="utf-8"))
        template = template["workflow_runs"][0]
        raw = tmp_path / "raw"
        for run_id, fixture in runs:
            payload = copy.deepcopy(template)
            payload.update(
                id=run_id, head_sha="7f2b215", workflow_id=99, run_attempt=1, head_branch=branch
            )
            (raw / "runs").mkdir(parents=True, exist_ok=True)
            (raw / "runs" / f"{run_id}.json").write_text(json.dumps(payload), encoding="utf-8")

            job = {"id": run_id * 10, "run_id": run_id, "name": "test", "conclusion": "failure"}
            (raw / "jobs").mkdir(exist_ok=True)
            (raw / "jobs" / f"{run_id}.json").write_text(json.dumps([job]), encoding="utf-8")

            log_dir = raw / "logs" / str(run_id)
            log_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(LOG_FIXTURES / fixture, log_dir / f"{run_id * 10}.txt")
        return tmp_path

    return build
