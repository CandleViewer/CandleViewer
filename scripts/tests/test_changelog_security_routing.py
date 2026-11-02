"""#3347: commits route to the changelog's Security section (docs/plan/07-release-and-prr.md §3).

A `Changelog-Security:` footer or a `security` PR label on a `feat`/`fix`/`perf` commit; the
footer wins; a wording-guard failure fails the sync and writes nothing. Fixtures only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci import update_changelog as uc
from tools.ci.changelog_lib import Category, build_changelog_update, parse_commit

_SHA = "abc1234" + "0" * 33
_FOOTER = "Changelog-Security: Hardened the session check against replayed tokens"
_LABELS = [{"number": 7, "labels": [{"name": "security"}, {"name": "area/auth-rbac"}]}]


def _entries(message: str, labels: tuple[str, ...] = ()) -> dict[Category, list[str]]:
    return build_changelog_update([parse_commit(_SHA, message, labels)]).entries


def test_parse_commit_security_footer_routes_footer_text_to_security() -> None:
    entries = _entries(f"fix(auth-rbac): check the session (#7)\n\n{_FOOTER}")
    expected = "- Hardened the session check against replayed tokens (#7)"
    assert entries == {Category.SECURITY: [expected]}


@pytest.mark.parametrize("kind", ["fix", "feat", "perf"])
def test_parse_commit_security_label_routes_generated_line_to_security(kind: str) -> None:
    entries = _entries(f"{kind}(auth-rbac): check the session (#7)", ("security",))
    assert entries == {Category.SECURITY: ["- **auth-rbac**: check the session (#7) (abc1234)"]}


def test_parse_commit_security_label_on_other_types_is_ignored() -> None:
    assert _entries("refactor(auth-rbac): split a helper (#7)", ("security",)) == {}


def test_parse_commit_footer_and_label_footer_wins() -> None:
    entries = _entries(f"fix(auth-rbac): check the session (#7)\n\n{_FOOTER}", ("security",))
    expected = "- Hardened the session check against replayed tokens (#7)"
    assert entries == {Category.SECURITY: [expected]}


def test_parse_commit_labelled_subject_failing_guard_stays_under_fixes() -> None:
    commit = parse_commit(_SHA, "fix(api): cap the request payload size (#7)", ("security",))
    assert commit.category == Category.FIXES and commit.security_label_skipped


@pytest.mark.parametrize("labels", [(), ("security",)])
def test_parse_commit_revert_is_unchanged(labels: tuple[str, ...]) -> None:
    commit = parse_commit(_SHA, 'revert: "fix(a): x (#6)" (#7)', labels)
    assert commit.category is None and _entries(commit.subject_line, labels) == {}


def _write(tmp_path: Path, commits: list[dict[str, str]]) -> tuple[Path, Path, Path]:
    path, raw, labels = (tmp_path / n for n in ("CHANGELOG.md", "commits.json", "labels.json"))
    path.write_text(uc._default_changelog(), encoding="utf-8")
    raw.write_text(json.dumps(commits), encoding="utf-8")
    labels.write_text(json.dumps(_LABELS), encoding="utf-8")
    return path, raw, labels


def test_sync_guard_failure_on_footer_fails_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A neutral marker-pattern example: the guard refuses the word, not any real detail.
    message = "fix(auth-rbac): x (#7)\n\nChangelog-Security: Fixed it, see the exploit steps"
    path, raw, _ = _write(tmp_path, [{"sha": _SHA, "message": message}])
    before = path.read_bytes()
    assert uc.main(["--commits-json", str(raw), "--changelog", str(path)]) == 1
    assert path.read_bytes() == before
    out = capsys.readouterr().out
    assert "::error::Security changelog wording check failed" in out and "abc1234" in out


def test_sync_guard_failure_on_existing_security_line_fails(tmp_path: Path) -> None:
    path, raw, _ = _write(tmp_path, [{"sha": _SHA, "message": "fix(a): y (#8)"}])
    text = path.read_text(encoding="utf-8").replace(
        "### Security", "### Security\n- Fixed it, payload in the notes (#5)"
    )
    path.write_text(text, encoding="utf-8")
    assert uc.main(["--commits-json", str(raw), "--changelog", str(path)]) == 1
    assert path.read_text(encoding="utf-8") == text
    assert uc.main(["--commits-json", str(raw), "--changelog", str(path), "--preview"]) == 0


def test_sync_golden_render_of_a_mixed_unreleased_section(tmp_path: Path) -> None:
    commits = [
        {"sha": "1111111" + "0" * 33, "message": "feat(chart-engine): add a pane (#1)"},
        {"sha": "2222222" + "0" * 33, "message": "fix(ingestion): resync on a gap (#2)"},
        {"sha": "3333333" + "0" * 33, "message": "perf(order-flow): pool buffers (#3)"},
        {"sha": "4444444" + "0" * 33, "message": "feat(oms-execution)!: new intent shape (#4)"},
        {
            "sha": "5555555" + "0" * 33,
            "message": f"fix(auth-rbac): check a session (#5)\n\n{_FOOTER}",
        },
        {"sha": "6666666" + "0" * 33, "message": "fix(auth-rbac): refuse a stale grant (#7)"},
        {"sha": "7777777" + "0" * 33, "message": 'revert: "fix(a): z (#6)" (#8)'},
        {"sha": "8888888" + "0" * 33, "message": "docs(docs): reword a page (#9)"},
    ]
    path, raw, labels = _write(tmp_path, commits)
    argv = ["--commits-json", str(raw), "--changelog", str(path), "--pr-labels-json", str(labels)]
    assert uc.main(argv) == 0
    assert path.read_text(encoding="utf-8") == (
        "# Changelog\n\nAll notable changes to CandleViewer are documented here.\n\n"
        "## Unreleased\n\n"
        "### Breaking Changes\n- **oms-execution**: new intent shape (#4) (4444444)\n\n"
        "### Features\n- **chart-engine**: add a pane (#1) (1111111)\n\n"
        "### Fixes\n- **ingestion**: resync on a gap (#2) (2222222)\n\n"
        "### Performance\n- **order-flow**: pool buffers (#3) (3333333)\n\n"
        "### Security\n"
        "- Hardened the session check against replayed tokens (#5)\n"
        "- **auth-rbac**: refuse a stale grant (#7) (6666666)\n\n"
    )
    assert uc.main(argv) == 0  # idempotent: a second sync changes nothing


def test_parse_commit_security_label_on_breaking_commit_stays_under_breaking() -> None:
    entries = _entries("fix(auth-rbac)!: check the session (#7)", ("security",))
    assert entries == {Category.BREAKING: ["- **auth-rbac**: check the session (#7) (abc1234)"]}


def test_parse_commit_empty_footer_with_label_routes_to_security() -> None:
    commit = parse_commit(
        _SHA, "fix(auth-rbac): check the session (#7)\n\nChangelog-Security:", ("security",)
    )
    assert commit.category == Category.SECURITY and commit.security_rejected == ""


def test_parse_two_pr_numbers_uses_the_last() -> None:
    raw = [{"sha": _SHA, "message": "fix(auth-rbac): port (#3) to the gate (#7)"}]
    (commit,) = uc._parse(raw, {3: frozenset(), 7: frozenset({"security"})})
    assert commit.category == Category.SECURITY


def test_sync_labelled_subject_failing_guard_warns(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    commits = [{"sha": _SHA, "message": "fix(api): cap the request payload size (#7)"}]
    path, raw, labels = _write(tmp_path, commits)
    argv = ["--commits-json", str(raw), "--changelog", str(path), "--pr-labels-json", str(labels)]
    assert uc.main(argv) == 0
    out = capsys.readouterr().out
    assert "::warning::commit abc1234 is labelled security" in out
    assert "### Fixes\n- **api**: cap the request payload size (#7) (abc1234)" in path.read_text(
        encoding="utf-8"
    )


def test_sync_pr_number_missing_from_labels_file_warns(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path, raw, labels = _write(tmp_path, [{"sha": _SHA, "message": "fix(a): y (#8)"}])
    argv = ["--commits-json", str(raw), "--changelog", str(path), "--pr-labels-json", str(labels)]
    assert uc.main([*argv, "--preview"]) == 0
    out = capsys.readouterr().out
    assert "::warning::1 pending commit(s) have a PR number missing" in out and "abc1234" in out


@pytest.mark.parametrize("content", ["not json", '[{"number": 7}]', "[7]"])
def test_sync_malformed_labels_file_reports_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], content: str
) -> None:
    path, raw, labels = _write(tmp_path, [{"sha": _SHA, "message": "fix(a): y (#8)"}])
    labels.write_text(content, encoding="utf-8")
    argv = ["--commits-json", str(raw), "--changelog", str(path), "--pr-labels-json", str(labels)]
    assert uc.main(argv) == 1
    assert capsys.readouterr().out.startswith("::error::")


def test_sync_refused_footer_error_names_the_unblock_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    message = "fix(auth-rbac): x (#7)\n\nChangelog-Security: Fixed it, see the exploit steps"
    path, raw, _ = _write(tmp_path, [{"sha": _SHA, "message": message}])
    assert uc.main(["--commits-json", str(raw), "--changelog", str(path)]) == 1
    assert "ending with that commit's (#N) or (sha7)" in capsys.readouterr().out
