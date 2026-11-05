"""Deterministic validation agent.

The validation agent is the only specialist that does not need an LLM: every
v1 convention rule is checkable in code through :func:`harness.checks.run_checks`.
That keeps a normal review at two model calls (security and performance) before
the judge.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from pathlib import Path

from harness.checks.ruff_check import RuffRunner
from harness.checks.runner import run_checks
from harness.diff_models import DiffInfo
from harness.schemas import AgentRunResult, AgentStatus
from harness.utils import describe_error, elapsed_ms

logger = logging.getLogger(__name__)

AGENT_NAME = "validation"

__all__ = ["AGENT_NAME", "run_validation"]


async def run_validation(
    diff: DiffInfo,
    *,
    pr_body: str | None = "",
    sources: Mapping[str, str] | None = None,
    repo_root: Path | None = None,
    ruff_runner: RuffRunner | None = None,
) -> AgentRunResult:
    """Run the deterministic validation rules and return an honest status.

    No LLM is called. The returned result contains every finding produced by
    ruff, the AST checks, the tests-touched check, and the PR-description check.

    Args:
        diff: Parsed and denoised diff facts for the pull request.
        pr_body: The pull-request description; blank or ``None`` is flagged.
        sources: Optional in-memory source keyed by repo-relative path.
        repo_root: Optional checkout root used to read files for AST checks.
        ruff_runner: Optional subprocess boundary used by tests.

    Returns:
        ``finished`` with the deterministic findings when the checks complete,
        or ``failed`` with a bounded error if the check runner raises.
    """

    started = time.perf_counter()
    logger.debug("agent %s starting (deterministic)", AGENT_NAME)

    try:
        findings = run_checks(
            diff,
            pr_body=pr_body,
            sources=sources,
            repo_root=repo_root,
            ruff_runner=ruff_runner,
        )
    except Exception as exc:  # noqa: BLE001 - no agent failure may escape
        error = describe_error(exc, prefix="validation checks failed")
        logger.error("agent %s status=failed error=%s", AGENT_NAME, error)
        return AgentRunResult(
            agent=AGENT_NAME,
            status=AgentStatus.failed,
            findings=[],
            error=error,
            duration_ms=elapsed_ms(started),
        )

    result = AgentRunResult(
        agent=AGENT_NAME,
        status=AgentStatus.finished,
        findings=findings,
        error=None,
        duration_ms=elapsed_ms(started),
    )
    logger.info(
        "agent %s status=finished duration_ms=%d findings=%d",
        AGENT_NAME,
        result.duration_ms or 0,
        len(result.findings),
    )
    return result
