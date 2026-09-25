"""Scoring a candidate patch against a testbed seed: policy, context, judge, CI.

One place for what `scripts/score_patch.py` (labelled patches) and `scripts/run_agent.py`
(an agent's patches) both need, so a patch is scored the same way whoever wrote it.

`oracle=False` is the deployment setting. The manifest's expected fix location, its list
of cheat classes and its verdict on whether editing a test is legitimate are ground truth
a real user of this scorer would not have, and each one makes a cheat easier to catch or an
honest fix easier to clear. The breaking change's own diff stays: it is the commit that
turned CI red, which a real repository knows.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ci_triage.diffparse import parse_diff
from ci_triage.patchscore import Policy


def load_manifest(testbed: Path) -> list[dict]:
    return json.loads((testbed / "seeds" / "manifest.json").read_text(encoding="utf-8"))["seeds"]


def policy_for(testbed: Path, seed: dict, *, oracle: bool = True) -> Policy:
    inject = (testbed / "seeds" / seed["id"] / "inject.patch").read_text(encoding="utf-8")
    if not oracle:
        return Policy(inject_diff=inject)
    return Policy(
        fix_paths=frozenset(seed["fix_paths"]),
        cheats=frozenset(seed["cheats"]),
        test_edit_legitimate=seed["test_edit_is_legitimate"],
        inject_diff=inject,
    )


@dataclass
class SeedContext:
    """The seed's failing tree on disk, exported once, for reading files as they were.

    Holds a temporary directory: use as a context manager, or call `close()`.
    """

    testbed: Path
    seed_id: str
    _dir: Path | None = field(default=None, repr=False)

    def __enter__(self) -> SeedContext:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self._dir is not None:
            shutil.rmtree(self._dir, ignore_errors=True)
            self._dir = None

    def _tree(self) -> Path:
        if self._dir is None:
            self._dir = Path(tempfile.mkdtemp(prefix=f"ctx-{self.seed_id}-"))
            dest = self._dir / "tree"
            proc = subprocess.run(
                [sys.executable, "tools/seeds.py", "export", self.seed_id, str(dest)],
                cwd=self.testbed,
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"export failed for {self.seed_id}: {proc.stderr[-300:]}")
        return self._dir / "tree"

    def files_for(self, diff: str) -> dict[str, str]:
        """The files `diff` touches, as they are in the failing tree (new files are absent)."""
        tree = self._tree()
        found: dict[str, str] = {}
        for changed in parse_diff(diff):
            old = changed.old_path
            if old and (tree / old).is_file():
                found[old] = (tree / old).read_text(encoding="utf-8", errors="replace")
        return found
