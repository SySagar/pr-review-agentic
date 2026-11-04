"""Tests for the deterministic finding filter."""

from __future__ import annotations

import pytest

from harness.filter import OUTSIDE_DIFF_NOTE, filter_findings, normalize_path
from tests.factories import build_diff_file, build_diff_info, build_finding


def _diff(*paths_and_lines: tuple[str, tuple[int, ...]]):
    return build_diff_info(
        files=tuple(
            build_diff_file(path=path, changed_lines=lines) for path, lines in paths_and_lines
        )
    )


def test_empty_input_returns_empty_list():
    """An empty finding list stays empty after filtering."""
    assert filter_findings([], _diff(("app/main.py", (10,)))) == []


def test_duplicate_findings_collapse_to_the_highest_confidence():
    """Duplicate findings on the same line keep only the strongest match."""
    findings = [
        build_finding(file="app/main.py", line=12, confidence=0.6, issue="Weak duplicate."),
        build_finding(file="app/main.py", line=12, confidence=0.9, issue="Strong duplicate."),
    ]

    result = filter_findings(findings, _diff(("app/main.py", (12,))))

    assert len(result) == 1
    assert result[0].confidence == 0.9
    assert result[0].issue == "Strong duplicate."


def test_critical_duplicate_beats_non_critical_with_higher_confidence():
    """A critical duplicate wins over a less severe duplicate even with lower confidence."""
    findings = [
        build_finding(file="app/main.py", line=12, severity="high", confidence=0.9),
        build_finding(file="app/main.py", line=12, severity="critical", confidence=0.4),
    ]

    result = filter_findings(findings, _diff(("app/main.py", (12,))))

    assert len(result) == 1
    assert result[0].severity == "critical"


def test_same_file_different_lines_are_not_duplicates():
    """Findings on different changed lines remain separate instead of collapsing together."""
    findings = [
        build_finding(file="app/main.py", line=12),
        build_finding(file="app/main.py", line=13),
    ]

    result = filter_findings(findings, _diff(("app/main.py", (12, 13))))

    assert {finding.line for finding in result} == {12, 13}


def test_low_confidence_out_of_diff_finding_is_removed():
    """Low-severity findings outside the diff are discarded as irrelevant."""
    findings = [build_finding(file="app/main.py", line=99, severity="low")]

    assert filter_findings(findings, _diff(("app/main.py", (12,)))) == []


def test_critical_out_of_diff_finding_survives_with_a_visible_note():
    """Critical findings outside the diff are kept, but clearly flagged for manual review."""
    findings = [build_finding(file="app/main.py", line=99, severity="critical")]

    result = filter_findings(findings, _diff(("app/main.py", (12,))))

    assert len(result) == 1
    assert OUTSIDE_DIFF_NOTE in result[0].issue


def test_out_of_diff_note_is_not_added_twice():
    """The outside-diff note is only appended once even after repeated filtering."""
    finding = build_finding(file="app/main.py", line=99, severity="critical")
    diff = _diff(("app/main.py", (12,)))

    once = filter_findings([finding], diff)
    twice = filter_findings(once, diff)

    assert twice[0].issue.count(OUTSIDE_DIFF_NOTE) == 1


def test_finding_for_an_unchanged_file_is_removed():
    """Findings tied to files not in the patch are discarded."""
    findings = [build_finding(file="other.py", line=1, severity="high")]

    assert filter_findings(findings, _diff(("app/main.py", (12,)))) == []


def test_file_level_finding_is_kept_when_the_file_changed():
    """File-level findings remain valid when the whole file is part of the diff."""
    findings = [build_finding(file="app/main.py", line=None, severity="medium")]

    result = filter_findings(findings, _diff(("app/main.py", (12,))))

    assert len(result) == 1


def test_unrelated_file_level_findings_are_not_merged():
    """Different file-level issues are kept distinct even when they share the same file."""
    findings = [
        build_finding(file="app/main.py", line=None, issue="Missing tests."),
        build_finding(file="app/main.py", line=None, issue="Missing changelog."),
    ]

    result = filter_findings(findings, _diff(("app/main.py", (12,))))

    assert len(result) == 2


def test_absolute_and_prefixed_paths_are_resolved_to_the_diff_path():
    """Absolute and Git-prefixed paths are normalized to the repo-relative diff path."""
    findings = [
        build_finding(
            file="/home/runner/work/repo/app/main.py",
            line=12,
            issue="Absolute path.",
        ),
        build_finding(file="b/app/main.py", line=13, issue="Git prefix."),
    ]

    result = filter_findings(findings, _diff(("app/main.py", (12, 13))))

    assert {finding.file for finding in result} == {"app/main.py"}
    assert len(result) == 2


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("./app/main.py", "app/main.py"),
        ("a/app/main.py", "app/main.py"),
        ("b/app/main.py", "app/main.py"),
        ("app\\main.py", "app/main.py"),
        ("app//main.py", "app/main.py"),
        ("  app/main.py  ", "app/main.py"),
    ],
)
def test_normalize_path(raw: str, expected: str):
    """Path normalization collapses common diff prefixes and separators into a stable form."""
    assert normalize_path(raw) == expected


def test_output_is_ranked_by_severity_then_confidence_then_location():
    """The final output order prioritizes severity, then confidence, then file and line."""
    findings = [
        build_finding(file="b.py", line=1, severity="low", confidence=0.9),
        build_finding(file="a.py", line=5, severity="critical", confidence=0.5),
        build_finding(file="a.py", line=6, severity="high", confidence=0.6),
        build_finding(file="a.py", line=7, severity="high", confidence=0.8),
    ]

    result = filter_findings(findings, _diff(("a.py", (5, 6, 7)), ("b.py", (1,))))

    assert [(finding.severity, finding.file, finding.line) for finding in result] == [
        ("critical", "a.py", 5),
        ("high", "a.py", 7),
        ("high", "a.py", 6),
        ("low", "b.py", 1),
    ]


def test_order_is_stable_across_calls():
    """Repeated filtering produces the same ordering on repeated runs."""
    findings = [
        build_finding(file="a.py", line=3, severity="medium", confidence=0.5),
        build_finding(file="a.py", line=1, severity="medium", confidence=0.5),
        build_finding(file="a.py", line=2, severity="critical", confidence=0.5),
    ]
    diff = _diff(("a.py", (1, 2, 3)))

    first = filter_findings(findings, diff)
    second = filter_findings(findings, diff)

    assert first == second
