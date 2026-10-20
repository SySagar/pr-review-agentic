"""Unit tests for unified-diff parsing and noise filtering."""

from __future__ import annotations

import logging

import pytest

from harness.constants import DEFAULT_NOISE_PATTERNS
from harness.diff_utils import filter_noise, is_noise_path, parse_diff, prepare_diff
from tests.factories import build_diff_file, read_diff_fixture


def test_parse_modified_file_maps_added_and_removed_lines() -> None:
    """The parser tracks new-file line numbers and both counts."""
    files = parse_diff(read_diff_fixture("simple.patch"))

    assert len(files) == 1
    file = files[0]
    assert file.path == "app/greet.py"
    assert file.additions == 1
    assert file.deletions == 1
    assert file.changed_lines == frozenset({2})


def test_parse_new_file_uses_the_new_path() -> None:
    files = parse_diff(read_diff_fixture("new_file.patch"))

    file = files[0]
    assert file.path == "pkg/new_mod.py"
    assert file.additions == 3
    assert file.deletions == 0
    assert file.changed_lines == frozenset({1, 2, 3})


def test_parse_rename_uses_the_new_path() -> None:
    files = parse_diff(read_diff_fixture("rename.patch"))

    file = files[0]
    assert file.path == "pkg/new_name.py"
    assert file.additions == 1
    assert file.deletions == 1


def test_parse_deleted_file_uses_the_old_path() -> None:
    files = parse_diff(read_diff_fixture("deleted.patch"))

    file = files[0]
    assert file.path == "pkg/removed.py"
    assert file.additions == 0
    assert file.deletions == 2
    assert file.changed_lines == frozenset()


def test_missing_newline_marker_is_ignored() -> None:
    """``\\ No newline at end of file`` must not affect counts or lines."""
    files = parse_diff(read_diff_fixture("no_newline.patch"))

    file = files[0]
    assert file.additions == 1
    assert file.deletions == 1
    assert file.changed_lines == frozenset({1})


def test_empty_diff_has_no_files() -> None:
    assert parse_diff("") == []
    assert prepare_diff("").is_empty


def test_malformed_hunk_header_is_logged_and_skipped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A bad ``@@`` header is reported instead of crashing the parser."""
    caplog.set_level(logging.WARNING)

    files = parse_diff(read_diff_fixture("malformed.patch"))

    assert len(files) == 1
    assert files[0].additions == 0
    assert any("malformed hunk header" in record.getMessage() for record in caplog.records)


def test_prepare_diff_drops_noise_files_and_counts_only_kept_lines() -> None:
    """Lockfiles are noise and do not contribute to the kept totals."""
    info = prepare_diff(read_diff_fixture("noise.patch"))

    assert [file.path for file in info.files] == ["app/real.py"]
    assert info.dropped_files == ("uv.lock",)
    assert info.additions == 1
    assert info.deletions == 0


def test_custom_noise_patterns_are_honored() -> None:
    """Callers can replace the default noise policy."""
    info = prepare_diff(
        read_diff_fixture("simple.patch"),
        noise_patterns=("app/*",),
    )

    assert info.is_empty
    assert info.dropped_files == ("app/greet.py",)


def test_filter_noise_returns_kept_and_dropped_paths() -> None:
    noise = build_diff_file(path="uv.lock")
    code = build_diff_file(path="app/main.py")

    kept, dropped = filter_noise([noise, code])

    assert kept == [code]
    assert dropped == ["uv.lock"]


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("uv.lock", True),
        ("package-lock.json", True),
        ("app/generated/models.py", False),
        ("app/main.py", False),
        ("assets/logo.png", True),
        ("vendor/lib/helpers.py", True),
    ],
)
def test_noise_path_matcher(path: str, expected: bool) -> None:
    assert is_noise_path(path) is expected


def test_shared_noise_patterns_are_exposed_globally() -> None:
    assert DEFAULT_NOISE_PATTERNS == tuple(DEFAULT_NOISE_PATTERNS)
    assert "uv.lock" in DEFAULT_NOISE_PATTERNS
    assert "*.png" in DEFAULT_NOISE_PATTERNS


def test_prepare_diff_logs_a_summary(caplog: pytest.LogCaptureFixture) -> None:
    """Operators get a metadata-only summary without raw diff content."""
    caplog.set_level(logging.INFO)

    prepare_diff(read_diff_fixture("noise.patch"))

    summaries = [
        record.getMessage() for record in caplog.records if "prepared diff" in record.getMessage()
    ]
    assert summaries == ["prepared diff: files=1 dropped_noise=1 additions=1 deletions=0"]
