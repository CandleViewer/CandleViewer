"""Unit tests for tools/ci/release_semver.py (E03-T11, CI-REL-002)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.changelog_lib import Bump
from tools.ci.release_semver import Version, check_1_0_0_guard, compute_next_version


def test_version_parse_accepts_v_prefix() -> None:
    assert Version.parse("v1.2.3") == Version(1, 2, 3)


def test_version_parse_rejects_invalid() -> None:
    with pytest.raises(ValueError):
        Version.parse("not-a-version")


def test_patch_bump_pre_1_0() -> None:
    result = compute_next_version(Version(0, 3, 1), Bump.PATCH)
    assert result.ok
    assert result.next_version == Version(0, 3, 2)


def test_minor_bump_pre_1_0() -> None:
    result = compute_next_version(Version(0, 3, 1), Bump.MINOR)
    assert result.ok
    assert result.next_version == Version(0, 4, 0)


@pytest.mark.parametrize(
    ("current", "expected"),
    [(Version(0, 0, 0), Version(0, 1, 0)), (Version(0, 9, 3), Version(0, 10, 0))],
)
def test_compute_next_version_pre_1_0_breaking_change_bumps_minor(
    current: Version, expected: Version
) -> None:
    """C-15.5 (#3099): pre-1.0 a breaking change bumps MINOR, never to 1.0.0 by itself."""
    result = compute_next_version(current, Bump.MAJOR)
    assert result.ok
    assert result.next_version == expected


@pytest.mark.parametrize("bump", [Bump.PATCH, Bump.MINOR, Bump.MAJOR])
def test_compute_next_version_pre_1_0_with_declaration_gives_exactly_1_0_0(bump: Bump) -> None:
    result = compute_next_version(Version(0, 9, 4), bump, allow_1_0_0=True)
    assert result.ok
    assert result.next_version == Version(1, 0, 0)


def test_compute_next_version_declaration_flag_with_no_bump_keeps_the_version() -> None:
    assert compute_next_version(Version(0, 9, 4), Bump.NONE, allow_1_0_0=True).next_version == (
        Version(0, 9, 4)
    )


def test_check_1_0_0_guard_1_0_0_without_flag_fails_ci_rel_002_with_the_kept_message() -> None:
    result = check_1_0_0_guard(Version(0, 9, 4), Version(1, 0, 0))
    assert not result.ok
    assert result.error_code == "CI-REL-002"
    assert result.reason is not None and "1.0.0 requires explicit" in result.reason


def test_check_1_0_0_guard_1_0_0_with_flag_passes() -> None:
    assert check_1_0_0_guard(Version(0, 9, 4), Version(1, 0, 0), allow_1_0_0=True).ok


@pytest.mark.parametrize("version", [Version(2, 0, 0), Version(1, 0, 1), Version(1, 1, 0)])
def test_check_1_0_0_guard_other_major_on_a_0_x_base_fails_even_with_the_flag(
    version: Version,
) -> None:
    result = check_1_0_0_guard(Version(0, 3, 0), version, allow_1_0_0=True)
    assert not result.ok
    assert result.error_code == "CI-REL-002"


def test_check_1_0_0_guard_post_1_0_base_and_0_x_versions_pass() -> None:
    assert check_1_0_0_guard(Version(1, 4, 2), Version(2, 0, 0)).ok
    assert check_1_0_0_guard(Version(0, 3, 0), Version(0, 4, 0)).ok


def test_major_bump_post_1_0_does_not_need_the_guard() -> None:
    result = compute_next_version(Version(1, 4, 2), Bump.MAJOR)
    assert result.ok
    assert result.next_version == Version(2, 0, 0)


def test_no_bump_returns_current_version_unchanged() -> None:
    result = compute_next_version(Version(0, 3, 1), Bump.NONE)
    assert result.ok
    assert result.next_version == Version(0, 3, 1)
