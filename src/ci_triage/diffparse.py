"""Read a unified diff into files and changed line blocks.

Just enough for the patch scorer: which files a patch touches, whether each was
added, deleted or modified, and for modified files the changed blocks, kept as
(removed lines, added lines) pairs. A block is a run of `-` lines followed by a
run of `+` lines with no context between them, which is how a one-line edit
appears, so a detector can ask "what did this line become".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_HEADER = re.compile(r"^diff --git a/(?P<old>\S+) b/(?P<new>\S+)$")


@dataclass
class Change:
    removed: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)


@dataclass
class FileDiff:
    old_path: str | None
    new_path: str | None
    changes: list[Change] = field(default_factory=list)

    @property
    def path(self) -> str:
        return self.new_path or self.old_path or ""

    @property
    def status(self) -> str:
        if self.old_path is None:
            return "added"
        if self.new_path is None:
            return "deleted"
        return "modified"

    @property
    def added(self) -> list[str]:
        return [line for change in self.changes for line in change.added]

    @property
    def removed(self) -> list[str]:
        return [line for change in self.changes for line in change.removed]


def parse_diff(text: str) -> list[FileDiff]:
    """Files in a `git diff` / `git format-patch` style unified diff."""
    files: list[FileDiff] = []
    current: FileDiff | None = None
    change: Change | None = None
    in_hunk = False

    for line in text.splitlines():
        header = _HEADER.match(line)
        if header:
            current = FileDiff(header["old"], header["new"])
            files.append(current)
            change, in_hunk = None, False
            continue
        if current is None:
            continue

        if not in_hunk:
            if line.startswith("new file mode"):
                current.old_path = None
            elif line.startswith("deleted file mode"):
                current.new_path = None
            elif line.startswith("@@"):
                in_hunk = True
            continue

        if line.startswith("@@"):
            change = None
        elif line.startswith("-"):
            if change is None or change.added:
                change = Change()
                current.changes.append(change)
            change.removed.append(line[1:])
        elif line.startswith("+"):
            if change is None:
                change = Change()
                current.changes.append(change)
            change.added.append(line[1:])
        elif line.startswith("\\"):
            continue  # "\ No newline at end of file"
        else:
            change = None  # context line ends the block
    return files
