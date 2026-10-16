from __future__ import annotations

from harness.schemas import AgentOutput, AgentRunResult, FinalReview, Finding


def build_finding(**overrides) -> Finding:
    data = {
        "file": "auth.py",
        "line": 12,
        "severity": "high",
        "confidence": 0.8,
        "issue": "Query built with an f-string.",
        "suggested_fix": "Use a parameterized query.",
    }
    data.update(overrides)
    return Finding.model_validate(data)


def build_agent_output(**overrides) -> AgentOutput:
    data = {"findings": [build_finding()]}
    data.update(overrides)
    return AgentOutput.model_validate(data)


def build_agent_run_result(**overrides) -> AgentRunResult:
    data = {
        "agent": "security",
        "status": "finished",
        "findings": [build_finding()],
        "error": None,
        "duration_ms": 1234,
    }
    data.update(overrides)
    return AgentRunResult.model_validate(data)


def build_final_review(**overrides) -> FinalReview:
    data = {
        "verdict": "comment",
        "summary": "Looks reasonable.",
        "blocking": [],
        "should_fix": [],
        "final_points": [],
    }
    data.update(overrides)
    return FinalReview.model_validate(data)
