"""Deterministic cleanup of agent findings before the judge sees them.

Normalizes paths, merges duplicates, drops findings outside the changed lines
(critical ones survive with a note), and ranks the survivors. No LLM call.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable, Mapping

from harness.diff_models import DiffInfo
from harness.schemas import Finding

logger = logging.getLogger(__name__)

__all__ = ["OUTSIDE_DIFF_NOTE", "filter_findings", "normalize_path"]

OUTSIDE_DIFF_NOTE = "Reported outside the changed lines; verify manually."

# Lower number means higher priority when ranking.
_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def normalize_path(path: str) -> str:
    """Strip Git/Windows prefixes and repeated slashes from a finding path."""

    value = re.sub(r"/+", "/", path.strip().replace("\\", "/"))
    while value.startswith("./"):
        value = value[2:]
    return value[2:] if value.startswith(("a/", "b/")) else value


def filter_findings(findings: Iterable[Finding], diff: DiffInfo) -> list[Finding]:
    """Normalize, deduplicate, line-verify, and rank findings in one pass."""

    changed: Mapping[str, frozenset[int]] = {
        normalize_path(path): lines for path, lines in diff.changed_lines.items()
    }
    resolve = _path_resolver(changed)
    total = 0

    # Same file and line is an overlap. File-level findings only merge when the
    # issue text also matches, so unrelated findings are not combined.
    best: dict[tuple[object, ...], Finding] = {}
    for raw in findings:
        total += 1
        finding = raw.model_copy(update={"file": resolve(raw.file)})
        key = (finding.file, finding.line, finding.line is None and finding.issue.casefold())
        current = best.get(key)
        if current is None or _preference(finding) > _preference(current):
            best[key] = finding

    kept: list[Finding] = []
    for finding in best.values():
        lines = changed.get(finding.file)
        in_diff = lines is not None and (finding.line is None or finding.line in lines)
        if in_diff:
            kept.append(finding)
        elif finding.severity == "critical":
            kept.append(_with_outside_note(finding))
        else:
            logger.debug("dropping out-of-diff finding: %s:%s", finding.file, finding.line)

    logger.info("filtered findings: input=%d kept=%d", total, len(kept))
    return sorted(
        kept,
        key=lambda finding: (
            _SEVERITY_ORDER[finding.severity],
            -finding.confidence,
            finding.file,
            finding.line or 0,
        ),
    )


def _path_resolver(known: Mapping[str, frozenset[int]]) -> Callable[[str], str]:
    """Return a function that maps absolute or prefixed paths onto the diff."""

    ordered = sorted(known, key=lambda path: (-len(path), path))

    def resolve(path: str) -> str:
        normalized = normalize_path(path)
        if normalized in known:
            return normalized
        match = next(
            (candidate for candidate in ordered if normalized.endswith("/" + candidate)),
            None,
        )
        return match or normalized.lstrip("/")

    return resolve


def _preference(finding: Finding) -> tuple[object, ...]:
    """Rank for choosing a duplicate's survivor: critical first, then confidence."""

    return (-_SEVERITY_ORDER[finding.severity], finding.confidence, finding.issue)


def _with_outside_note(finding: Finding) -> Finding:
    if OUTSIDE_DIFF_NOTE in finding.issue:
        return finding
    issue = f"{finding.issue.rstrip()} (Note: {OUTSIDE_DIFF_NOTE})"
    return finding.model_copy(update={"issue": issue})
