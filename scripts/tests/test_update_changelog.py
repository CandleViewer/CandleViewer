"""Integration-style tests for tools/ci/update_changelog.py — acceptance
scenario "A feature merge lands in the Unreleased changelog" (E03-T11).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci import update_changelog as uc
from tools.ci.changelog_lib import ParsedCommit, parse_commit
from tools.ci.finalize_changelog import finalize
from tools.ci.update_changelog import _default_changelog, apply_update


def test_apply_update_adds_feature_bullet_under_unreleased_features() -> None:
    commits = [parse_commit("deadbee", "feat(chart): add volume pane")]
    new_text, changed = apply_update(_default_changelog(), commits)
    assert changed
    features_idx = new_text.index("### Features")
    fixes_idx = new_text.index("### Fixes")
    section = new_text[features_idx:fixes_idx]
    assert "add volume pane" in section
    assert "(deadbee)" in section


def test_apply_update_no_changelog_worthy_commits_is_noop() -> None:
    commits = [parse_commit("s1", "refactor(backend-platform): extract helper")]
    original = _default_changelog()
    new_text, changed = apply_update(original, commits)
    assert not changed
    assert new_text == original


def test_apply_update_appends_to_existing_entries_without_duplicating_headings() -> None:
    base = _default_changelog()
    commits1 = [parse_commit("s1", "feat(chart): add volume pane")]
    text1, _ = apply_update(base, commits1)
    commits2 = [parse_commit("s2", "feat(chart): add heatmap pane")]
    text2, changed2 = apply_update(text1, commits2)
    assert changed2
    assert text2.count("### Features") == 1
    assert "add volume pane" in text2
    assert "add heatmap pane" in text2


def test_apply_update_from_commits_json_round_trip(tmp_path: Path) -> None:
    commits_path = tmp_path / "commits.json"
    commits_path.write_text(
        json.dumps([{"sha": "abc1234", "message": "fix(oms-execution): correct rounding"}]),
        encoding="utf-8",
    )
    raw = json.loads(commits_path.read_text(encoding="utf-8"))
    commits = [parse_commit(item["sha"], item["message"]) for item in raw]
    new_text, changed = apply_update(_default_changelog(), commits)
    assert changed
    assert "correct rounding" in new_text


# --- #2341: idempotent merge semantics (docs/plan/07-release-and-prr.md §3) ---------------


def _changelog(unreleased: str, tail: str = "") -> str:
    return f"# Changelog\n\nIntro.\n\n## Unreleased\n{unreleased}{tail}"


def _commit(sha7: str, subject: str) -> ParsedCommit:
    return parse_commit(sha7 + "0" * 33, subject)


def _files(tmp_path: Path, text: str, commits: list[dict[str, str]]) -> tuple[Path, Path]:
    path, raw = tmp_path / "CHANGELOG.md", tmp_path / "commits.json"
    path.write_text(text, encoding="utf-8")
    raw.write_text(json.dumps(commits), encoding="utf-8")
    return path, raw


def test_apply_update_rerun_with_same_commits_is_byte_identical() -> None:
    commits = [_commit("1111111", "feat(chart): add pane (#12)"), _commit("2222222", "fix(ui): x")]
    once, changed = apply_update(_default_changelog(), commits)
    assert changed
    assert apply_update(once, commits) == (once, False)


def test_apply_update_collapses_repeated_entries_in_first_occurrence_order() -> None:
    lines = ["- **a**: one (1111111)", "- **b**: two (2222222)"]
    once, changed = apply_update(_changelog("\n### Features\n" + "\n".join(lines * 72) + "\n"), [])
    assert changed
    assert [ln for ln in once.splitlines() if ln.startswith("- ")] == lines
    assert apply_update(once, []) == (once, False)


def test_apply_update_keeps_hand_written_security_lines_and_warns_every_call(
    capsys: pytest.CaptureFixture[str],
) -> None:
    hand = "- Hardened API-key decryption against a timing side-channel"
    risky = "- Closed the exploit path in session refresh (#41)"
    commits = [_commit("3333333", "feat(chart): add pane")]
    once, _ = apply_update(_changelog(f"\n### Security\n{hand}\n{risky}\n"), commits)
    twice, changed = apply_update(once, commits)
    assert not changed
    assert hand in twice.splitlines() and risky in twice.splitlines()
    apply_update(twice, [])
    assert capsys.readouterr().err.count("WARNING") == 3


def test_apply_update_keeps_a_curated_line_that_kept_its_trailing_sha() -> None:
    text = _changelog("\n### Security\n- Session checks are stricter (abc1234)\n")
    commit = _commit("abc1234", "fix(auth-rbac): tighten check")
    assert apply_update(text, [commit]) == (text, False)


@pytest.mark.parametrize(
    ("existing", "subject", "added"),
    [
        ("- Hardened session handling (#1234)", "fix(auth-rbac): tighten (#1234)", False),
        ("- Earlier work (#2250)", "fix(ui): follow-up to (#2250) (#2287)", True),
        ("- **api**: follow-up to (#20) regression (#21) (bbbbbbb)", "fix(api): x (#20)", True),
        ("- Hardened session handling (#1234).", "fix(auth-rbac): tighten (#1234)", True),
    ],
)
def test_apply_update_counts_only_the_trailing_reference(
    existing: str, subject: str, added: bool
) -> None:
    commit = _commit("4444444", subject)
    new, changed = apply_update(_changelog(f"\n### Security\n{existing}\n"), [commit])
    assert changed is added
    assert (commit.changelog_line() in new.splitlines()) is added


def test_referenced_tokens_reads_only_the_trailing_token() -> None:
    lines = ["- a (#12)", "- b (abc1234)  ", "- c (#3).", "- d (#4) mid-line"]
    assert uc.referenced_tokens(lines) == {"#12", "abc1234"}
    assert uc.is_referenced(_commit("9999999", "fix(x): y (#3) (#12)"), {"#12"})


@pytest.mark.parametrize(
    "body",
    ["\n### Chores\n- tidy (1111111)\n", "\n### Fixes\n- ok (1111111)\nprose\n", "\n- orphan\n"],
)
def test_unknown_content_in_unreleased_fails_loudly(body: str, tmp_path: Path) -> None:
    text = _changelog(body)
    with pytest.raises(uc.ChangelogFormatError, match=r"line \d+"):
        apply_update(text, [])
    with pytest.raises(uc.ChangelogFormatError):
        finalize(text, "0.1.0", "2026-10-20")
    path, raw = _files(tmp_path, text, [])
    assert uc.main(["--commits-json", str(raw), "--changelog", str(path)]) == 1
    assert path.read_text(encoding="utf-8") == text


def test_cli_preview_writes_nothing_and_appends_a_fenced_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    line = "- **docs**: explain ``` fences (5555555)"
    text = _changelog(f"\n### Features\n{line}\n{line}\n")
    path, raw = _files(tmp_path, text, [{"sha": "6" * 40, "message": "fix(ui): wrap"}])
    summary = tmp_path / "summary.md"
    summary.write_text("earlier step\n", encoding="utf-8")
    argv = ["--commits-json", str(raw), "--changelog", str(path), "--preview", "--summary"]
    assert uc.main([*argv, str(summary)]) == 0
    assert path.read_text(encoding="utf-8") == text
    out = capsys.readouterr().out
    for want in ("## Unreleased", "pending: 1", "duplicates collapsed: 1", "security warnings: 0"):
        assert want in out
    md = summary.read_text(encoding="utf-8")
    assert md.startswith("earlier step\n") and "\n````markdown\n" in md
    assert md.rstrip().endswith("\n````")


def test_cli_warns_on_a_large_backlog_and_on_exploit_wording(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    raw = [{"sha": f"{n:07x}" + "0" * 33, "message": f"fix(ui): fix {n}"} for n in range(301)]
    text = _changelog("\n### Security\n- Stopped an exploit at 100%\n")
    path, commits = _files(tmp_path, text, raw)
    assert uc.main(["--commits-json", str(commits), "--changelog", str(path), "--preview"]) == 0
    out = capsys.readouterr().out
    assert "::warning::301 changelog entries are pending" in out
    assert "::warning::Security changelog line may contain exploit detail: " in out
    assert "an exploit at 100%25" in out


def test_cli_since_last_tag_syncs_once_then_is_a_no_op(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    revs: list[str] = []

    def fake(rev: str) -> list[dict[str, str]]:
        revs.append(rev)
        return [{"sha": "7" * 40, "message": "feat(chart): add pane (#7)"}]

    monkeypatch.setattr(uc, "commits_since_last_tag", fake)
    monkeypatch.setattr(uc, "last_final_tag", lambda rev: None)
    path = tmp_path / "CHANGELOG.md"
    assert uc.main(["--since-last-tag", "--changelog", str(path)]) == 0
    first = path.read_bytes()
    assert b"- **chart**: add pane (#7) (7777777)\n" in first
    assert uc.main(["--since-last-tag", "--rev", "abc", "--changelog", str(path)]) == 0
    assert path.read_bytes() == first and revs == ["HEAD", "abc"]

    def shallow(rev: str) -> list[dict[str, str]]:
        raise uc.CollectCommitsError("shallow clone")

    monkeypatch.setattr(uc, "commits_since_last_tag", shallow)
    assert uc.main(["--since-last-tag", "--changelog", str(path)]) == 1
    assert path.read_bytes() == first


def test_finalize_on_duplicated_input_yields_each_entry_once() -> None:
    line = "- **a**: one (1111111)"
    text = _changelog(f"\n### Features\n{line}\n{line}\n{line}\n")
    _, body = finalize(text, "0.1.0", "2026-10-20")
    assert body.splitlines().count(line) == 1


@pytest.mark.parametrize("released", ["- **a**: one (abc1234)", "- One shipped (#77)"])
def test_commit_released_in_a_version_section_is_not_readded(
    released: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    commit = {"sha": "abc1234" + "0" * 33, "message": "feat(a): one (#76) (#77)"}
    text = _changelog("\n### Features\n", f"\n## 0.1.0 — 2026-10-20\n\n### Features\n{released}\n")
    assert apply_update(text, [parse_commit(commit["sha"], commit["message"])]) == (text, False)
    path, raw = _files(tmp_path, text, [commit])
    assert uc.main(["--commits-json", str(raw), "--changelog", str(path), "--preview"]) == 0
    assert "pending: 0" in capsys.readouterr().out


def test_header_text_never_counts_as_a_reference() -> None:
    text = "# Changelog\n\n- Shipped one (#77)\n\n## Unreleased\n\n### Features\n"
    commit = _commit("abc1234", "feat(a): one (#77)")
    new, changed = apply_update(text, [commit])
    assert changed and commit.changelog_line() in new.splitlines()
