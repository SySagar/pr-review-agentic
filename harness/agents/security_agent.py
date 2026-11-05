"""Security specialist agent.

Runs one narrow LLM review for vulnerabilities and prompt-injection attempts.
The runtime in :mod:`harness.agents.base` owns the timeout, retry, and status
mapping, so this module only declares the agent's identity and prompt.
"""

from __future__ import annotations

from harness.agents.base import AgentRunner, AgentSpec
from harness.schemas import AgentRunResult

AGENT_NAME = "security"
PROMPT_FILE = "security.md"

SECURITY_SPEC = AgentSpec(
    name=AGENT_NAME,
    prompt_file=PROMPT_FILE,
)

__all__ = ["AGENT_NAME", "PROMPT_FILE", "SECURITY_SPEC", "run_security"]


async def run_security(
    runner: AgentRunner,
    *,
    title: str = "",
    body: str = "",
    diff: str = "",
) -> AgentRunResult:
    """Run the security review and return findings plus a status.

    The diff, title, and body are treated as untrusted data by the runner.
    """

    return await runner.run(
        SECURITY_SPEC,
        title=title,
        body=body,
        diff=diff,
    )
