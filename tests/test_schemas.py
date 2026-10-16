from __future__ import annotations

import pytest
from pydantic import ValidationError

from harness.schemas import (
    AgentOutput,
    AgentRunResult,
    AgentStatus,
    FinalReview,
    Finding,
    Severity,
    Verdict,
)
from tests.factories.schema_factory import (
    build_agent_output,
    build_agent_run_result,
    build_final_review,
    build_finding,
)


@pytest.mark.parametrize(
    "enum_type, value",
    [
        (Severity, "critical"),
        (AgentStatus, "not_finished"),
        (Verdict, "request_changes"),
    ],
)
def test_enums_round_trip_from_strings(enum_type, value: str) -> None:
    """Ensure each enum accepts its string value and round-trips to the same member."""
    member = enum_type(value)

    assert member.value == value
    assert enum_type(member.value) is member
    assert enum_type(member) is member


def test_finding_accepts_valid_data() -> None:
    """Accept a valid finding payload and populate the expected fields."""
    finding = build_finding()

    assert finding.file == "auth.py"
    assert finding.line == 12
    assert finding.severity is Severity.high
    assert finding.confidence == 0.8
    assert finding.suggested_fix == "Use a parameterized query."


def test_finding_allows_missing_line_and_empty_suggested_fix() -> None:
    """Allow optional line numbers and blank fixes when the finding is otherwise valid."""
    finding = build_finding(line=None, suggested_fix="")

    assert finding.line is None
    assert finding.suggested_fix == ""


@pytest.mark.parametrize("confidence", [0.0, 0.5, 1.0])
def test_finding_accepts_confidence_boundaries(confidence: float) -> None:
    """Accept the minimum, midpoint, and maximum valid confidence values."""
    assert build_finding(confidence=confidence).confidence == confidence


@pytest.mark.parametrize("confidence", [-0.01, 1.01, -1, 2])
def test_finding_rejects_confidence_outside_zero_to_one(confidence: float) -> None:
    """Reject confidence values that fall outside the allowed range."""
    with pytest.raises(ValidationError):
        build_finding(confidence=confidence)


@pytest.mark.parametrize(
    "missing_field",
    ["file", "severity", "confidence", "issue"],
)
def test_finding_requires_core_fields(missing_field: str) -> None:
    """Require each core finding field to be present before validation succeeds."""
    data = {
        "file": "auth.py",
        "severity": "high",
        "confidence": 0.8,
        "issue": "Problem.",
    }
    del data[missing_field]

    with pytest.raises(ValidationError):
        Finding.model_validate(data)


def test_finding_rejects_unknown_severity() -> None:
    """Reject severities that are not part of the allowed enum."""
    with pytest.raises(ValidationError):
        build_finding(severity="blocker")


def test_agent_output_defaults_to_empty_findings() -> None:
    """Default AgentOutput instances should start with an empty findings list."""
    assert AgentOutput().findings == []


def test_agent_output_parses_nested_findings() -> None:
    """Validate nested finding data from a JSON-like payload."""
    output = build_agent_output(
        findings=[
            {
                "file": "auth.py",
                "line": 14,
                "severity": "critical",
                "confidence": 0.9,
                "issue": "Predictable token.",
                "suggested_fix": "Use secrets.token_urlsafe(32).",
            }
        ]
    )

    assert len(output.findings) == 1
    assert output.findings[0].severity is Severity.critical


def test_agent_run_result_carries_status_and_findings() -> None:
    """Confirm agent results keep their status, findings, and timing metadata."""
    result = build_agent_run_result(
        agent="security",
        status="finished",
        findings=[build_finding()],
        duration_ms=1234,
    )

    assert result.status is AgentStatus.finished
    assert result.findings[0].file == "auth.py"
    assert result.error is None
    assert result.duration_ms == 1234


@pytest.mark.parametrize("status", ["finished", "not_finished", "failed", "skipped"])
def test_agent_run_result_accepts_every_status(status: str) -> None:
    """Allow each valid agent status value through the schema."""
    assert AgentRunResult(agent="security", status=status).status.value == status


@pytest.mark.parametrize("status", ["running", "done", ""])
def test_agent_run_result_rejects_invalid_status(status: str) -> None:
    """Reject status values that are not defined in the enum."""
    with pytest.raises(ValidationError):
        AgentRunResult(agent="security", status=status)


def test_agent_run_result_requires_status() -> None:
    """Require an agent status to be supplied for every result."""
    with pytest.raises(ValidationError):
        AgentRunResult(agent="security")


def test_agent_run_result_defaults() -> None:
    """Use empty defaults when a result only includes the minimum required fields."""
    result = AgentRunResult(agent="performance", status=AgentStatus.skipped)

    assert result.findings == []
    assert result.error is None
    assert result.duration_ms is None


def test_final_review_defaults_and_lists() -> None:
    """Ensure default review objects have empty lists for each review section."""
    review = build_final_review(verdict="comment", summary="Looks reasonable.")

    assert review.verdict is Verdict.comment
    assert review.blocking == []
    assert review.should_fix == []
    assert review.final_points == []


def test_final_review_with_findings_and_points() -> None:
    """Validate a full review body with blocking findings and final guidance."""
    review = build_final_review(
        verdict=Verdict.request_changes,
        summary="One blocking issue.",
        blocking=[build_finding(severity="critical", confidence=0.95)],
        should_fix=[build_finding(severity="medium", confidence=0.6)],
        final_points=["Fix the injection."],
    )

    assert review.verdict is Verdict.request_changes
    assert review.blocking[0].severity is Severity.critical
    assert review.should_fix[0].severity is Severity.medium
    assert review.final_points == ["Fix the injection."]


def test_final_review_rejects_unknown_verdict() -> None:
    """Reject verdicts that are not in the allowed enum."""
    with pytest.raises(ValidationError):
        FinalReview(verdict="merge", summary="No.")


def test_model_dump_uses_json_safe_enum_values() -> None:
    """Ensure model_dump(mode='json') emits JSON-safe string values for enums."""
    result = AgentRunResult(agent="security", status="finished", findings=[build_finding()])

    dumped = result.model_dump(mode="json")

    assert dumped["status"] == "finished"
    assert dumped["findings"][0]["severity"] == "high"


def test_json_round_trip() -> None:
    """Verify a review model survives a JSON dump and restore cycle without data loss."""
    review = FinalReview(
        verdict="approve",
        summary="Clean.",
        final_points=["Ship it."],
    )

    restored = FinalReview.model_validate_json(review.model_dump_json())

    assert restored == review
