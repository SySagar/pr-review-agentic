"""Performance specialist agent.

Runs one narrow LLM review for efficiency and logic problems. The runtime in
:mod:`harness.agents.base` owns the timeout, retry, and status mapping.
"""

from __future__ import annotations

from harness.agents.base import AgentRunner, AgentSpec
from harness.schemas import AgentRunResult

AGENT_NAME = "performance"
PROMPT_FILE = "performance.md"

PERFORMANCE_SPEC = AgentSpec(
    name=AGENT_NAME,
    prompt_file=PROMPT_FILE,
)

__all__ = ["AGENT_NAME", "PERFORMANCE_SPEC", "PROMPT_FILE", "run_performance"]


async def run_performance(
    runner: AgentRunner,
    *,
    title: str = "",
    body: str = "",
    diff: str = "",
) -> AgentRunResult:
    """Run the performance review and return findings plus a status.

    The diff, title, and body are treated as untrusted data by the runner.
    """

    return await runner.run(
        PERFORMANCE_SPEC,
        title=title,
        body=body,
        diff=diff,
    )
