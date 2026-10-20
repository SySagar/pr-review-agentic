"""Minimal diff facts used by the review pipeline - defines the data objects that represent a changed file and a parsed diff."""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["DiffFile", "DiffInfo"]


@dataclass(frozen=True)
class DiffFile:
    """One changed file in a unified diff. Tells about the path, additions, deletions, and changed lines."""

    path: str
    additions: int = 0
    deletions: int = 0
    changed_lines: frozenset[int] = field(default_factory=frozenset)


@dataclass(frozen=True)
class DiffInfo:
    """Reviewable files after parsing and noise filtering."""

    files: tuple[DiffFile, ...] = ()
    dropped_files: tuple[str, ...] = ()
    additions: int = 0
    deletions: int = 0

    @property
    def is_empty(self) -> bool:
        """returns true if the diff has no reviewable files"""
        return not self.files

    @property
    def changed_lines(self) -> dict[str, frozenset[int]]:
        """Return a mapping of file paths to the set of changed line numbers."""
        return {file.path: file.changed_lines for file in self.files}
