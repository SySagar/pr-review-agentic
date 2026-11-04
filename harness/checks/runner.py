"""Single entry point for the deterministic validation checks.

Aggregates ruff, AST, and PR-level checks into one list of findings. Non-Python
files are skipped and a ruff failure is reported as a finding, never raised.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from pathlib import Path

from harness.checks.ast_checks import run_ast_checks
from harness.checks.pr_checks import check_pr_description, check_tests_touched
from harness.checks.ruff_check import RuffRunner, run_ruff_check
from harness.diff_models import DiffInfo
from harness.schemas import Finding

logger = logging.getLogger(__name__)

__all__ = ["run_checks"]


def run_checks(
    diff: DiffInfo,
    *,
    pr_body: str | None = "",
    sources: Mapping[str, str] | None = None,
    repo_root: Path | None = None,
    ruff_runner: RuffRunner | None = None,
) -> list[Finding]:
    """Run every deterministic validation rule against ``diff``.

    Args:
        diff: Parsed diff facts, including changed lines per file.
        pr_body: The pull-request description; ``None`` or blank is flagged.
        sources: Optional in-memory source text keyed by repo-relative path.
        repo_root: Optional checkout root used to read files for AST checks.
        ruff_runner: Optional subprocess boundary used by tests.

    Returns:
        All findings from ruff, AST, and PR-level checks in a stable order.
    """

    paths = [file.path for file in diff.files]
    python_paths = [path for path in paths if path.endswith(".py")]
    text_sources = _load_sources(python_paths, sources, repo_root)

    findings: list[Finding] = []
    # Run ruff on changed Python files and convert its JSON diagnostics to findings.
    findings.extend(
        run_ruff_check(
            python_paths,
            cwd=repo_root or Path.cwd(),
            runner=ruff_runner,
        )
    )
    # Run AST checks on the changed lines of Python files and convert their diagnostics to findings.
    findings.extend(run_ast_checks(text_sources, diff.changed_lines))

    # Run PR-level checks that don't require parsing Python files.
    findings.extend(check_tests_touched(paths))
    findings.extend(check_pr_description(pr_body, fallback_file=paths[0] if paths else ""))

    logger.info(
        "validation checks: files=%d python=%d findings=%d",
        len(paths),
        len(python_paths),
        len(findings),
    )
    return findings


def _load_sources(
    python_paths: Sequence[str],
    sources: Mapping[str, str] | None,
    repo_root: Path | None,
) -> dict[str, str]:
    """Resolve source text from ``sources`` first, then from ``repo_root``."""

    loaded: dict[str, str] = {}
    for path in python_paths:
        if sources is not None and path in sources:
            loaded[path] = sources[path]
            continue
        if repo_root is None:
            continue
        try:
            loaded[path] = (repo_root / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("could not read %s for AST checks: %s", path, exc)
    return loaded
