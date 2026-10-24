"""Unit tests for tools/ci/changelog_lib.py (E03-T11, CI-REL-001/CI-REL-002).

Fixture corpus per ticket "Test plan": feat, fix, perf, refactor, `!`,
BREAKING footer, revert, merge commits, non-conventional.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.changelog_lib import (
    Bump,
    Category,
    build_changelog_update,
    check_changelog_fragment,
    check_security_wording,
    is_pr_exempt,
    parse_commit,
)


def test_parse_commit_feat_maps_to_features_and_minor() -> None:
    c = parse_commit("abc1234", "feat(chart-engine): add volume pane")
    assert c.is_conventional
    assert c.category == Category.FEATURES
    assert c.bump == Bump.MINOR
    assert c.scope == "chart-engine"


def test_parse_commit_fix_maps_to_fixes_and_patch() -> None:
    c = parse_commit("abc1234", "fix(oms-execution): correct rounding")
    assert c.category == Category.FIXES
    assert c.bump == Bump.PATCH


def test_parse_commit_perf_maps_to_performance_and_patch() -> None:
    c = parse_commit("abc1234", "perf(chart-engine): batch buffer uploads")
    assert c.category == Category.PERFORMANCE
    assert c.bump == Bump.PATCH


def test_parse_commit_refactor_has_no_category_or_bump() -> None:
    c = parse_commit("abc1234", "refactor(backend-platform): extract helper")
    assert c.is_conventional
    assert c.category is None
    assert c.bump == Bump.NONE


def test_parse_commit_bang_forces_breaking_major() -> None:
    c = parse_commit("abc1234", "feat(auth-rbac)!: drop legacy session cookie")
    assert c.breaking
    assert c.bump == Bump.MAJOR
    assert c.category == Category.BREAKING


def test_parse_commit_breaking_change_footer_forces_major() -> None:
    msg = "feat(auth-rbac): rotate session keys\n\nBREAKING CHANGE: old sessions are invalidated"
    c = parse_commit("abc1234", msg)
    assert c.breaking
    assert c.bump == Bump.MAJOR
    assert c.breaking_detail == "old sessions are invalidated"


def test_parse_commit_revert_without_breaking_has_no_bump() -> None:
    c = parse_commit("abc1234", "revert: feat(chart-engine): add volume pane")
    assert c.is_conventional
    assert c.bump == Bump.NONE
    assert c.category is None


def test_parse_commit_merge_commit_is_excluded() -> None:
    c = parse_commit("abc1234", "Merge pull request #42 from feat/foo")
    assert c.is_merge
    assert not c.is_conventional


def test_parse_commit_non_conventional_is_rejected() -> None:
    c = parse_commit("abc1234", "wip fixes")
    assert not c.is_conventional
    assert c.category is None


def test_build_changelog_update_highest_bump_wins() -> None:
    commits = [
        parse_commit("s1", "fix(oms-execution): a"),
        parse_commit("s2", "feat(auth-rbac)!: b"),
        parse_commit("s3", "feat(chart-engine): c"),
    ]
    update = build_changelog_update(commits)
    assert update.bump == Bump.MAJOR
    assert update.triggering_breaking_commits == ["s2"]
    assert len(update.entries[Category.FEATURES]) == 1
    assert len(update.entries[Category.BREAKING]) == 1
    assert len(update.entries[Category.FIXES]) == 1


def test_build_changelog_update_ignores_merge_and_non_conventional() -> None:
    commits = [
        parse_commit("s1", "Merge pull request #1 from x"),
        parse_commit("s2", "wip"),
    ]
    update = build_changelog_update(commits)
    assert update.bump == Bump.NONE
    assert not update.has_entries()


def test_is_pr_exempt_true_for_docs_chore_ci() -> None:
    assert is_pr_exempt("docs: fix typo in sitemap")
    assert is_pr_exempt("chore(infra-devops): bump deps")
    assert is_pr_exempt("ci: tighten timeout")


def test_is_pr_exempt_false_for_feat() -> None:
    assert not is_pr_exempt("feat(chart): add volume pane")


def test_check_changelog_fragment_conventional_title_passes() -> None:
    result = check_changelog_fragment("feat(chart): add volume pane", "")
    assert result.ok


def test_check_changelog_fragment_docs_only_is_exempt() -> None:
    result = check_changelog_fragment("docs: fix typo in sitemap", "")
    assert result.ok


def test_check_changelog_fragment_non_conventional_without_footer_fails() -> None:
    result = check_changelog_fragment("wip fixes", "no footer here")
    assert not result.ok
    assert result.error_code == "CI-REL-001"


def test_check_changelog_fragment_non_conventional_with_footer_passes() -> None:
    body = "Some PR description.\n\nChangelog: adds a new volume pane to the chart\n"
    result = check_changelog_fragment("wip fixes", body)
    assert result.ok


def test_check_security_wording_flags_exploit_language() -> None:
    result = check_security_wording(
        ["- Hardened API-key decryption path", "- Fixed exploit in the payload parser"]
    )
    assert not result.ok
    assert len(result.violations) == 1


def test_check_security_wording_clean_lines_pass() -> None:
    result = check_security_wording(["- Hardened API-key decryption path against timing side-channel"])
    assert result.ok
    assert result.violations == []


# --- #4435: `Changelog-Security:` footer (07 §3) -----------------------------------------------

_SEC_FOOTER = "Changelog-Security: Hardened the key path against a timing side channel"
_SEC_LINE = "- Hardened the key path against a timing side channel"


def _update(message: str):
    return build_changelog_update([parse_commit("abc1234def", message)])


def test_security_footer_becomes_a_security_bullet_ending_with_the_pr_number() -> None:
    update = _update(f"fix(auth-rbac): compare keys in constant time (#77)\n\nBody.\n\n{_SEC_FOOTER}\n")
    assert update.entries == {Category.SECURITY: [f"{_SEC_LINE} (#77)"]}


def test_security_footer_replaces_the_type_bullet_so_the_subject_is_not_published() -> None:
    update = _update(f"fix(auth-rbac): constant-time compare (#77)\n\n{_SEC_FOOTER}")
    assert Category.FIXES not in update.entries
    assert update.bump == Bump.PATCH  # the type still decides the semver bump


def test_security_footer_keeps_the_breaking_bullet_of_a_breaking_commit() -> None:
    update = _update(f"fix(auth-rbac)!: rotate the token format (#78)\n\n{_SEC_FOOTER}")
    assert set(update.entries) == {Category.SECURITY, Category.BREAKING}
    assert update.bump == Bump.MAJOR


def test_security_footer_without_a_pr_number_ends_with_the_short_sha() -> None:
    update = _update(f"fix(auth-rbac): compare keys in constant time\n\n{_SEC_FOOTER}")
    assert update.entries[Category.SECURITY] == [f"{_SEC_LINE} (abc1234)"]


def test_security_footer_that_already_ends_with_the_pr_number_is_not_doubled() -> None:
    update = _update("fix(auth-rbac): x (#77)\n\nChangelog-Security: Hardened a path (#77)")
    assert update.entries[Category.SECURITY] == ["- Hardened a path (#77)"]


def test_security_footer_with_exploit_detail_is_refused_at_the_pr_and_ignored_at_the_sync() -> None:
    footer = "Changelog-Security: Fixed it, payload in the finding"
    result = check_changelog_fragment("fix(auth-rbac): x", footer)
    assert not result.ok and result.error_code == "CI-REL-001"
    update = _update(f"fix(auth-rbac): x (#7)\n\n{footer}")
    assert update.entries == {Category.FIXES: ["- **auth-rbac**: x (#7)"]}


def test_a_clean_security_footer_passes_the_fragment_check_for_a_free_form_title() -> None:
    assert check_changelog_fragment("wip", _SEC_FOOTER).ok
