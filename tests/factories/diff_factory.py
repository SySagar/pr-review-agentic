"""Factories for diff parsing tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from harness.diff_models import DiffFile, DiffInfo

DIFF_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "diffs"


def read_diff_fixture(name: str) -> str:
    """Return the text of a patch fixture under ``tests/fixtures/diffs``."""

    return (DIFF_FIXTURES / name).read_text(encoding="utf-8")


def build_diff_file(
    *,
    path: str = "app/main.py",
    additions: int = 0,
    deletions: int = 0,
    changed_lines: tuple[int, ...] = (),
) -> DiffFile:
    return DiffFile(
        path=path,
        additions=additions,
        deletions=deletions,
        changed_lines=frozenset(changed_lines),
    )


def build_diff_info(
    *,
    files: tuple[DiffFile, ...] = (),
    dropped_files: tuple[str, ...] = (),
    additions: int | None = None,
    deletions: int | None = None,
) -> DiffInfo:
    data: dict[str, Any] = {
        "files": files,
        "dropped_files": dropped_files,
        "additions": sum(file.additions for file in files) if additions is None else additions,
        "deletions": sum(file.deletions for file in files) if deletions is None else deletions,
    }
    return DiffInfo(**data)
