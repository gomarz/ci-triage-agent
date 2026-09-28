"""A sandboxed checkout the patch-proposing agent edits, and the tools it edits it with.

The agent's only reach is this directory. Every path a tool takes is resolved and must
land inside it, `.git` is off limits, and the tools are narrow (list, read, write,
replace, delete, run CI) rather than a shell, so there is no command that can walk out
to the testbed's `main` history, where the answers are.

The workspace is a fresh git repo with one baseline commit (built by the testbed's
`export`), so the patch is exactly `git diff` against that commit. Files are written
with LF endings: the testbed normalises to LF, and a CRLF diff will not apply to it.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

MAX_READ = 40_000
MAX_LIST = 400

TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "list_files",
        "description": "List files in the repository, optionally under a directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory; default is the root."}
            },
        },
    },
    {
        "name": "read_file",
        "description": "Read a text file.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Create a file or replace its whole contents.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
    {
        "name": "replace_in_file",
        "description": "Replace one exact occurrence of `old` with `new` in a file. "
        "Fails if `old` is missing or appears more than once.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old": {"type": "string"},
                "new": {"type": "string"},
            },
            "required": ["path", "old", "new"],
        },
    },
    {
        "name": "delete_file",
        "description": "Delete a file.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "run_ci",
        "description": "Run the repo's CI workflow on the current files; reports the result.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


class ToolError(Exception):
    """A tool call that cannot be honoured. Its message goes back to the model."""


class Workspace:
    def __init__(self, root: Path, run_ci: Callable[[], dict[str, Any]]) -> None:
        self.root = root.resolve()
        self._run_ci = run_ci
        self.ci_runs = 0

    def resolve(self, rel: str) -> Path:
        """`rel` as an absolute path inside the workspace, or ToolError."""
        if not isinstance(rel, str) or not rel.strip():
            raise ToolError("path is required")
        path = (self.root / rel).resolve()
        if not path.is_relative_to(self.root):
            raise ToolError(f"{rel!r} is outside the repository")
        if ".git" in path.relative_to(self.root).parts:
            raise ToolError(f"{rel!r} is not accessible")
        return path

    def execute(self, name: str, args: dict[str, Any]) -> str:
        """Run one tool call. Never raises: an error is a result the model can act on."""
        try:
            handler = getattr(self, f"_tool_{name}", None)
            if handler is None:
                raise ToolError(f"unknown tool {name!r}")
            return handler(**args)
        except ToolError as exc:
            return f"error: {exc}"
        except TypeError as exc:
            return f"error: bad arguments for {name}: {exc}"
        except OSError as exc:
            return f"error: {exc.strerror or exc}"

    def _tool_list_files(self, path: str = ".") -> str:
        base = self.resolve(path)
        if not base.is_dir():
            raise ToolError(f"{path!r} is not a directory")
        files = sorted(
            p.relative_to(self.root).as_posix()
            for p in base.rglob("*")
            if p.is_file()
            and ".git" not in p.relative_to(self.root).parts
            and "__pycache__" not in p.parts
        )
        shown = "\n".join(files[:MAX_LIST])
        return shown + (f"\n... {len(files) - MAX_LIST} more" if len(files) > MAX_LIST else "")

    def _tool_read_file(self, path: str) -> str:
        target = self.resolve(path)
        if not target.is_file():
            raise ToolError(f"{path!r} is not a file")
        text = target.read_text(encoding="utf-8", errors="replace")
        if len(text) > MAX_READ:
            return text[:MAX_READ] + f"\n... truncated, {len(text) - MAX_READ} more characters"
        return text

    def _tool_write_file(self, path: str, content: str) -> str:
        target = self.resolve(path)
        if target.is_dir():
            raise ToolError(f"{path!r} is a directory")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        return f"wrote {path} ({len(content)} characters)"

    def _tool_replace_in_file(self, path: str, old: str, new: str) -> str:
        target = self.resolve(path)
        if not target.is_file():
            raise ToolError(f"{path!r} is not a file")
        with target.open(encoding="utf-8", newline="") as handle:
            text = handle.read()
        # The file is LF in the repo, but tolerate a model that typed CRLF.
        old, new = old.replace("\r\n", "\n"), new.replace("\r\n", "\n")
        count = text.count(old)
        if count != 1:
            raise ToolError(f"`old` matches {count} times in {path}; it must match exactly once")
        with target.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text.replace(old, new))
        return f"edited {path}"

    def _tool_delete_file(self, path: str) -> str:
        target = self.resolve(path)
        if not target.is_file():
            raise ToolError(f"{path!r} is not a file")
        target.unlink()
        return f"deleted {path}"

    def _tool_run_ci(self) -> str:
        self.ci_runs += 1
        result = self._run_ci()
        head = (
            "CI passed"
            if result.get("passed")
            else f"CI failed at step {result.get('failed_step')!r}"
        )
        counts = ", ".join(
            f"{key}={result[key]}"
            for key in ("ran", "failures", "errors", "skipped")
            if key in result
        )
        return f"{head} ({counts})\n{result.get('log_tail', '')}"

    def diff(self) -> str:
        """Everything changed since the baseline commit, as a unified diff.

        Respects .gitignore, so it is what `git add -A && git commit` would hold: build
        outputs the CI run wrote are not part of the patch.
        """

        def git(*args: str) -> str:
            proc = subprocess.run(
                ["git", "-c", "core.autocrlf=false", *args],
                cwd=self.root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=True,
            )
            return proc.stdout

        git("add", "-A")
        return git("diff", "--cached", "--no-color")


def ci_via_testbed(testbed: Path, workspace: Path, venv: Path) -> Callable[[], dict[str, Any]]:
    """Run CI in `workspace` by the testbed's `ci` command, one venv shared across calls."""
    import sys

    def run() -> dict[str, Any]:
        proc = subprocess.run(
            [sys.executable, "tools/seeds.py", "ci", str(workspace), "--venv", str(venv)],
            cwd=testbed,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=900,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"testbed ci failed: {proc.stderr.strip()[-400:]}")
        return json.loads(proc.stdout.strip().splitlines()[-1])

    return run
