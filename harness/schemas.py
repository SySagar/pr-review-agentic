"""Shared Pydantic contracts for agents, review results, and rendering."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class Severity(StrEnum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class AgentStatus(StrEnum):
    finished = "finished"
    not_finished = "not_finished"
    failed = "failed"
    skipped = "skipped"


class Verdict(StrEnum):
    approve = "approve"
    request_changes = "request_changes"
    comment = "comment"


class Finding(BaseModel):
    file: str
    line: int | None = None
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    issue: str
    suggested_fix: str = ""


class AgentOutput(BaseModel):
    findings: list[Finding] = Field(default_factory=list)


class AgentRunResult(BaseModel):
    agent: str
    status: AgentStatus
    findings: list[Finding] = Field(default_factory=list)
    error: str | None = None
    duration_ms: int | None = None


class FinalReview(BaseModel):
    verdict: Verdict
    summary: str
    blocking: list[Finding] = Field(default_factory=list)
    should_fix: list[Finding] = Field(default_factory=list)
    final_points: list[str] = Field(default_factory=list)
