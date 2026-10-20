"""Parse Git unified diffs and drop noise.

Only the basic shape is supported: ``diff --git`` blocks, ``---``/``+++`` paths,
and ``@@`` hunks with added, removed, and context lines.

Not handled: chunking, size caps, binary patches, combined/merge diffs, plain
unified diffs without a ``diff --git`` header, and paths containing spaces.
"""

from __future__ import annotations

import fnmatch
import logging
import re

from harness.constants import DEFAULT_NOISE_PATTERNS
from harness.diff_models import DiffFile, DiffInfo

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_NOISE_PATTERNS",
    "DiffFile",
    "DiffInfo",
    "filter_noise",
    "is_noise_path",
    "parse_diff",
    "prepare_diff",
]

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@") # A regex matching unified diff hunk headers


def parse_diff(diff: str) -> list[DiffFile]:
    """Parse a Git diff into per-file additions, deletions, and changed lines."""

    files: list[DiffFile] = []
    path: str | None = None
    additions = deletions = 0
    changed: set[int] = set()
    new_line = 0
    in_hunk = False

    def flush() -> None:
        nonlocal path, additions, deletions, changed, in_hunk
        if path is not None:
            files.append(DiffFile(path, additions, deletions, frozenset(changed)))
        path, additions, deletions, changed, in_hunk = None, 0, 0, set(), False

    for line in diff.splitlines():
        if line.startswith("diff --git "):
            flush()
            continue

        if not in_hunk:
            if line.startswith("--- ") and path is None:
                path = _clean_path(line[4:])
            elif line.startswith("+++ "):
                path = _clean_path(line[4:]) or path
            elif line.startswith("@@"):
                match = _HUNK.match(line)
                if match is None:
                    logger.warning("skipping malformed hunk header")
                    continue
                new_line, in_hunk = int(match.group(1)), True
            continue

        if line.startswith("@@"):
            match = _HUNK.match(line)
            if match is None:
                logger.warning("skipping malformed hunk header")
                in_hunk = False
            else:
                new_line = int(match.group(1))
        elif line.startswith("+"):
            changed.add(new_line)
            additions += 1
            new_line += 1
        elif line.startswith("-"):
            deletions += 1
        elif line.startswith(" ") or line == "":
            new_line += 1

    flush()
    logger.debug(
        "parsed diff: files=%d additions=%d deletions=%d",
        len(files),
        sum(file.additions for file in files),
        sum(file.deletions for file in files),
    )
    return files


def is_noise_path(path: str, patterns: tuple[str, ...] = DEFAULT_NOISE_PATTERNS) -> bool:
    """Return True when a repo-relative path matches a noise pattern."""

    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def filter_noise(
    files: list[DiffFile],
    patterns: tuple[str, ...] = DEFAULT_NOISE_PATTERNS,
) -> tuple[list[DiffFile], list[str]]:
    """Split parsed files into kept files and dropped noise paths."""

    kept = [file for file in files if not is_noise_path(file.path, patterns)]
    dropped = [file.path for file in files if is_noise_path(file.path, patterns)]
    if dropped:
        logger.debug("dropped %d noise file(s): %s", len(dropped), ", ".join(dropped))
    return kept, dropped


def prepare_diff(
    diff: str,
    *,
    noise_patterns: tuple[str, ...] = DEFAULT_NOISE_PATTERNS,
) -> DiffInfo:
    """Parse a diff, drop noise files, and return the reviewable facts."""

    kept, dropped = filter_noise(parse_diff(diff), noise_patterns)
    info = DiffInfo(
        files=tuple(kept),
        dropped_files=tuple(dropped),
        additions=sum(file.additions for file in kept),
        deletions=sum(file.deletions for file in kept),
    )
    logger.info(
        "prepared diff: files=%d dropped_noise=%d additions=%d deletions=%d",
        len(info.files),
        len(info.dropped_files),
        info.additions,
        info.deletions,
    )
    return info


def _clean_path(raw: str) -> str | None:
    value = raw.strip()
    if not value or value == "/dev/null":
        return None
    if value.startswith(("a/", "b/")):
        value = value[2:]
    return value or None
