"""Tests for tools/ci/prepare_release.py (#3099): the release contract as tests. Throwaway git repos
in tmp_path with fixed dates and no global or system git config; no remote, no network. A squash
merge is simulated by committing the prep branch's two files onto `main` under the prep subject."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci import prepare_release as pr
from tools.ci import update_changelog as uc
from tools.ci.changelog_lib import parse_commit

_ID = ["-c", "user.name=t", "-c", "user.email=t@example.invalid"]
DATE = "2026-11-01"


class _Repo:
    def __init__(self, path: Path) -> None:
        self.path, self.count = path, 0
        self.git("init", "-q", "-b", "main")
        (path / pr.CHANGELOG).write_text(uc._default_changelog(), encoding="utf-8")
        (path / pr.VERSION_FILE).write_text("0.0.0\n", encoding="utf-8")
        self.git("add", "-A")
        self.commit("chore(infra-devops): scaffold the repo")

    @property
    def dir(self) -> str:
        return str(self.path)

    def git(self, *args: str) -> str:
        self.count += 1
        date = f"2026-10-01T00:{self.count // 60:02d}:{self.count % 60:02d}+00:00"
        env = {**os.environ, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
        cmd = ["git", "-C", self.dir, *_ID, *args]
        return subprocess.run(
            cmd, check=True, capture_output=True, text=True, env=env
        ).stdout.strip()

    def commit(self, subject: str) -> str:
        self.git("commit", "-q", "--allow-empty", "-m", subject)
        return self.git("rev-parse", "HEAD")

    def read(self, path: str) -> str:
        return (self.path / path).read_text(encoding="utf-8")

    def write(self, path: str, text: str) -> None:
        (self.path / path).write_text(text, encoding="utf-8")

    def prepare(self, *extra: str) -> str:
        """Run prepare on HEAD and return the version it wrote."""
        assert pr.main(["--repo", self.dir, "--rev", "HEAD", "--date", DATE, *extra]) == 0
        return self.read(pr.VERSION_FILE).strip()

    def merge_prep(self, number: int = 7, *extra: str) -> tuple[str, str]:
        """Prepare at HEAD and commit it as the squash of prep PR #number: (sha, version)."""
        version = self.prepare(*extra)
        self.git("add", pr.CHANGELOG, pr.VERSION_FILE)
        sha = self.commit(f"chore(infra-devops): prepare release {version} (#{number})")
        return sha, version

    def tag(self, name: str, rev: str = "HEAD") -> None:
        self.git("tag", "-a", name, "-m", name, rev)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Repo:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    (tmp_path / "repo").mkdir()
    return _Repo(tmp_path / "repo")


def _verify(repo: _Repo, rev: str = "HEAD", **kwargs: bool) -> list[str]:
    _, findings = pr.verify(repo.dir, rev, main_ref="main", **kwargs)
    return [f"{f.code}: {f.message}" for f in findings]


def _released(repo: _Repo) -> str:
    """A tagged 0.1.0 release on main; returns its candidate sha."""
    repo.commit("feat(chart-engine): first pane (#1)")
    sha, version = repo.merge_prep(2)
    assert version == "0.1.0"
    repo.tag("v0.1.0")
    return sha


def _race(repo: _Repo, late: str) -> str:
    """Prep at P on a branch, `late` merges to main first, then the prep squash lands as M."""
    repo.git("checkout", "-q", "-b", "prep")
    repo.prepare()
    repo.git("commit", "-q", "-am", "prep")
    repo.git("checkout", "-q", "main")
    late_sha = repo.commit(late)
    repo.git("checkout", "prep", "--", pr.CHANGELOG, pr.VERSION_FILE)
    version = repo.read(pr.VERSION_FILE).strip()
    repo.commit(f"chore(infra-devops): prepare release {version} (#9)")
    return late_sha


# --- prepare + verify: the happy path --------------------------------------------------------


def test_prepare_first_release_breaking_feat_gives_0_1_0_and_verifies(repo: _Repo) -> None:
    repo.commit("feat(oms-execution)!: new order shape (#1)")
    repo.commit("fix(chart-engine): a crash (#2)")
    sha, version = repo.merge_prep()
    assert version == "0.1.0"  # C-15.5: pre-1.0 breaking bumps MINOR
    text = repo.read(pr.CHANGELOG)
    assert pr.section_versions(text) == ["0.1.0"]
    assert f"## 0.1.0 — {DATE}" in text
    assert _verify(repo, sha) == []


def test_prepare_cli_prints_the_prep_title_and_informational_label(
    repo: _Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    repo.commit("fix(chart-engine): a crash (#2)")
    assert repo.prepare() == "0.0.1"
    out = capsys.readouterr().out
    assert "title=chore(infra-devops): prepare release 0.0.1" in out
    assert pr.PREP_TITLE_RE.match("chore(infra-devops): prepare release 0.0.1")
    assert "label=type/release (informational" in out


def test_verify_cli_writes_the_version_section_as_the_release_body(
    repo: _Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo.commit("feat(chart-engine): a pane (#1)")
    sha, _ = repo.merge_prep()
    out = tmp_path / "body.md"
    argv = ["--repo", repo.dir, "--verify", "--rev", sha, "--main-ref", "main", "--section-out"]
    assert pr.main([*argv, str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith(f"## 0.1.0 — {DATE}\n")
    assert "- **chart-engine**: a pane" in out.read_text(encoding="utf-8")
    assert "version=0.1.0" in capsys.readouterr().out


# --- (a) (b) a feature races the prep; the re-prep re-opens, recomputes, re-finalises ---------


def test_verify_feat_merged_before_the_prep_fails_naming_it_and_the_version(repo: _Repo) -> None:
    _released(repo)
    repo.commit("fix(chart-engine): a crash (#3)")
    late = _race(repo, "feat(chart-engine): a late pane (#4)")
    errors = _verify(repo)
    assert any(late[:7] in e and e.startswith("CI-REL-005") for e in errors)
    assert (
        "CI-REL-005: version 0.1.1 != expected 0.2.0 (minor bump over v0.1.0..{})".format(
            repo.git("rev-parse", "--short=7", "HEAD")
        )
        in errors
    )


def test_prepare_re_prep_reopens_the_untagged_section_and_is_byte_identical(repo: _Repo) -> None:
    _released(repo)
    repo.commit("fix(chart-engine): a crash (#3)")
    _race(repo, "feat(chart-engine): a late pane (#4)")
    assert repo.prepare() == "0.2.0"
    first = (repo.read(pr.CHANGELOG), repo.read(pr.VERSION_FILE))
    assert repo.prepare() == "0.2.0"
    assert (repo.read(pr.CHANGELOG), repo.read(pr.VERSION_FILE)) == first
    text = first[0]
    assert pr.section_versions(text) == ["0.2.0", "0.1.0"]  # 0.1.1 re-opened and absorbed
    section = "\n".join(pr.version_section(text, "0.2.0"))
    assert "a crash" in section and "a late pane" in section
    repo.git("add", "-A")
    sha = repo.commit("chore(infra-devops): prepare release 0.2.0 (#10)")
    assert _verify(repo, sha) == []


# --- (c) a re-run at a tagged candidate ------------------------------------------------------


def test_verify_rerun_at_a_candidate_already_tagged_passes(repo: _Repo) -> None:
    sha = _released(repo)
    assert _verify(repo, sha) == []


# --- (d) the 1.0.0 guard ---------------------------------------------------------------------


def test_verify_1_0_0_without_the_flag_fails_ci_rel_002_and_passes_with_it(repo: _Repo) -> None:
    _released(repo)
    repo.commit("feat(oms-execution): live enablement (#5)")
    sha, version = repo.merge_prep(6, "--allow-1-0-0")
    assert version == "1.0.0"
    errors = _verify(repo, sha)
    assert any(e.startswith("CI-REL-002: 1.0.0 requires explicit") for e in errors)
    assert _verify(repo, sha, allow_1_0_0=True) == []


def test_verify_another_major_on_a_0_x_base_fails_ci_rel_002_even_with_the_flag(
    repo: _Repo,
) -> None:
    _released(repo)
    repo.commit("feat(oms-execution)!: a breaking change (#5)")
    repo.prepare()
    repo.write(pr.CHANGELOG, repo.read(pr.CHANGELOG).replace("## 0.2.0 —", "## 2.0.0 —"))
    repo.write(pr.VERSION_FILE, "2.0.0\n")
    repo.git("add", "-A")
    sha = repo.commit("chore(infra-devops): prepare release 2.0.0 (#6)")
    assert any(e.startswith("CI-REL-002") for e in _verify(repo, sha, allow_1_0_0=True))


# --- (e) identity: Unreleased, the allow-list, vV elsewhere, the subject ---------------------


def test_verify_candidate_with_a_non_empty_unreleased_fails(repo: _Repo) -> None:
    repo.commit("feat(chart-engine): a pane (#1)")
    repo.prepare()
    text = repo.read(pr.CHANGELOG).replace("### Fixes\n", "### Fixes\n- a hand line (#99)\n", 1)
    repo.write(pr.CHANGELOG, text)
    repo.git("add", "-A")
    sha = repo.commit("chore(infra-devops): prepare release 0.1.0 (#2)")
    assert any("Unreleased is not empty (1 entries)" in e for e in _verify(repo, sha))


def test_verify_candidate_without_an_unreleased_heading_fails(repo: _Repo) -> None:
    repo.commit("feat(chart-engine): a pane (#1)")
    repo.prepare()
    text = repo.read(pr.CHANGELOG)
    repo.write(pr.CHANGELOG, text.replace("## Unreleased\n", "", 1))
    repo.git("add", "-A")
    sha = repo.commit("chore(infra-devops): prepare release 0.1.0 (#2)")
    assert (
        "CI-REL-005: CHANGELOG.md has no '## Unreleased' heading: a candidate keeps it, empty"
        in _verify(repo, sha)
    )


def test_verify_candidate_changing_a_file_outside_the_allow_list_fails(repo: _Repo) -> None:
    repo.commit("feat(chart-engine): a pane (#1)")
    repo.prepare()
    repo.write("README.md", "drive-by\n")
    repo.git("add", "-A")
    sha = repo.commit("chore(infra-devops): prepare release 0.1.0 (#2)")
    assert any("outside the prep allow-list: README.md" in e for e in _verify(repo, sha))


def test_verify_allow_list_error_names_a_path_containing_a_space(repo: _Repo) -> None:
    repo.commit("feat(chart-engine): a pane (#1)")
    repo.prepare()
    repo.write("read me.md", "drive-by\n")
    repo.git("add", "-A")
    sha = repo.commit("chore(infra-devops): prepare release 0.1.0 (#2)")
    assert any("outside the prep allow-list: read me.md" in e for e in _verify(repo, sha))


def test_verify_candidate_whose_tag_exists_elsewhere_fails(repo: _Repo) -> None:
    feat = repo.commit("feat(chart-engine): a pane (#1)")
    sha, _ = repo.merge_prep()
    repo.tag("v0.1.0", feat)
    assert any("tag v0.1.0 exists elsewhere" in e for e in _verify(repo, sha))


def test_verify_subject_version_other_than_version_txt_fails(repo: _Repo) -> None:
    repo.commit("feat(chart-engine): a pane (#1)")
    repo.prepare()
    repo.git("add", "-A")
    sha = repo.commit("chore(infra-devops): prepare release 0.9.0 (#2)")
    assert "CI-REL-005: subject version 0.9.0 != version.txt 0.1.0" in _verify(repo, sha)


def test_verify_candidate_not_reachable_from_main_fails(repo: _Repo) -> None:
    repo.commit("feat(chart-engine): a pane (#1)")
    repo.git("checkout", "-q", "-b", "side")
    sha, _ = repo.merge_prep()
    repo.git("checkout", "-q", "main")
    assert any("is not reachable from main" in e for e in _verify(repo, sha))


def test_verify_unresolvable_main_ref_fails(repo: _Repo) -> None:
    repo.commit("feat(chart-engine): a pane (#1)")
    sha, _ = repo.merge_prep()
    _, findings = pr.verify(repo.dir, sha)  # origin/main: there is no remote here
    assert [f.message.split(":")[0] for f in findings] == ["cannot resolve origin/main"]


# --- (f) completeness under the trailing-token rule ------------------------------------------


def test_missing_commits_mid_line_mention_does_not_reference_the_commit() -> None:
    missing = parse_commit("b" * 40, "fix(api): the regression (#20)")
    other = parse_commit("c" * 40, "fix(api): follow-up (#21)")
    section = ["## 0.2.0 — 2026-11-01", "", "### Fixes", "- **api**: follow-up to (#20) (#21)"]
    got = pr.missing_commits([missing, other], section, ["b" * 40, "c" * 40])
    assert got == [missing]


def test_missing_commits_sha7_shared_by_two_reachable_commits_references_nothing() -> None:
    commit = parse_commit("abcdef1" + "0" * 33, "fix(api): no pr number")
    section = ["### Fixes", "- **api**: no pr number (abcdef1)"]
    assert pr.missing_commits([commit], section, [commit.sha]) == []
    twin = "abcdef1" + "9" * 33
    assert pr.missing_commits([commit], section, [commit.sha, twin]) == [commit]


def test_missing_commits_ignores_commits_the_changelog_does_not_list() -> None:
    chore = parse_commit("d" * 40, "chore(docs): tidy (#3)")
    assert pr.missing_commits([chore], [], ["d" * 40]) == []


# --- (g) the preview at an untagged candidate ------------------------------------------------


def test_preview_at_an_untagged_candidate_reports_exactly_the_missing_commits(
    repo: _Repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _released(repo)
    repo.commit("fix(chart-engine): a crash (#3)")
    late = _race(repo, "feat(chart-engine): a late pane (#4)")
    monkeypatch.chdir(repo.path)
    assert uc.main(["--since-last-tag", "--preview"]) == 0
    out = capsys.readouterr().out
    assert "pending: 1" in out
    assert f"a late pane (#4) ({late[:7]})" in out


# --- (h) a bump of none ----------------------------------------------------------------------


def test_prepare_with_no_changelog_worthy_commit_refuses(
    repo: _Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    _released(repo)
    repo.commit("docs(docs): a note (#3)")
    before = repo.read(pr.CHANGELOG)
    assert pr.main(["--repo", repo.dir, "--rev", "HEAD", "--date", DATE]) == 1
    assert "CI-REL-005: no changelog-worthy commit since v0.1.0" in capsys.readouterr().out
    assert repo.read(pr.CHANGELOG) == before


# --- (i) same-version re-prep; classify --------------------------------------------------------


def test_same_version_re_prep_classifies_by_subject_and_verifies(repo: _Repo) -> None:
    repo.commit("feat(chart-engine): a pane (#1)")
    late = _race(repo, "fix(chart-engine): a late crash (#3)")
    errors = _verify(repo)
    assert any(late[:7] in e for e in errors)
    assert not any("!= expected" in e for e in errors)  # still 0.1.0
    m = repo.git("rev-parse", "HEAD")
    assert repo.prepare() == "0.1.0"
    repo.git("add", "-A")
    reprep = repo.commit("chore(infra-devops): prepare release 0.1.0 (#11)")
    assert pr.changed_files(repo.dir, reprep) == {pr.CHANGELOG}
    assert pr.classify(repo.dir, reprep, m) == [(reprep, "0.1.0")]
    assert _verify(repo, reprep) == []


def test_classify_sync_merge_is_not_a_candidate(
    repo: _Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    before = repo.commit("fix(chart-engine): a crash (#1)")
    line = f"### Fixes\n- **chart-engine**: a crash ({before[:7]})\n"
    repo.write(pr.CHANGELOG, repo.read(pr.CHANGELOG).replace("### Fixes\n", line, 1))
    repo.git("add", "-A")
    sync = repo.commit("docs(docs): update unreleased (#2)")
    assert pr.classify(repo.dir, sync, before) == []
    assert pr.main(["--repo", repo.dir, "--classify", "--rev", sync, "--before", before]) == 0
    assert capsys.readouterr().out.strip() == "candidate="


def test_classify_version_txt_change_without_the_title_is_a_candidate_and_fails_verify(
    repo: _Repo,
) -> None:
    before = repo.commit("feat(chart-engine): a pane (#1)")
    assert repo.prepare() == "0.1.0"
    repo.git("add", "-A")
    sha = repo.commit("fix(infra-devops): a mis-titled prep (#2)")
    assert pr.classify(repo.dir, sha, before) == [(sha, None)]
    expected = (
        "CI-REL-005: subject 'fix(infra-devops): a mis-titled prep (#2)' is not "
        "'chore(infra-devops): prepare release 0.1.0'"
    )
    assert expected in _verify(repo, sha)


def test_classify_ignores_a_changed_file_whose_name_contains_version_txt(repo: _Repo) -> None:
    before = repo.git("rev-parse", "HEAD")
    (repo.path / "docs").mkdir()
    repo.write("docs/a version.txt", "notes\n")
    repo.git("add", "-A")
    sha = repo.commit("docs(docs): a note (#2)")
    assert pr.changed_files(repo.dir, sha) == {"docs/a version.txt"}
    assert pr.classify(repo.dir, sha, before) == []


def test_classify_push_without_before_looks_at_the_head_only(
    repo: _Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    repo.commit("feat(chart-engine): a pane (#1)")
    sha, _ = repo.merge_prep()
    capsys.readouterr()
    assert pr.main(["--repo", repo.dir, "--classify", "--rev", sha, "--before", "0" * 40]) == 0
    assert capsys.readouterr().out.strip() == f"candidate={sha}"


def test_classify_two_candidates_in_one_push_fails_ci_rel_005_naming_none(
    repo: _Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    before = repo.commit("feat(chart-engine): a pane (#1)")
    first, _ = repo.merge_prep(2)
    repo.commit("fix(chart-engine): a crash (#3)")
    second, _ = repo.merge_prep(4)
    assert pr.main(["--repo", repo.dir, "--classify", "--rev", second, "--before", before]) == 1
    out = capsys.readouterr().out
    assert "CI-REL-005: 2 release candidates in one push" in out
    assert first[:7] in out and "candidate=" not in out


# --- (j) stale tags; (k) rogue tags ------------------------------------------------------------


def test_stale_clone_absorbs_a_released_section_and_verify_with_tags_refuses_it(
    repo: _Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    _released(repo)
    repo.commit("fix(chart-engine): a crash (#3)")
    patch, version = repo.merge_prep(4)
    assert version == "0.1.1"
    repo.tag("v0.1.1")
    repo.commit("feat(chart-engine): a pane (#5)")
    repo.git("tag", "-d", "v0.1.1")  # a clone that never fetched v0.1.1
    sha, version = repo.merge_prep(6)
    assert version == "0.2.0"
    assert pr.section_versions(repo.read(pr.CHANGELOG)) == ["0.2.0", "0.1.0"]
    repo.tag("v0.1.1", patch)  # git fetch origin --tags
    errors = _verify(repo, sha)
    assert "CI-REL-005: tag v0.1.1 is reachable but its section '## 0.1.1' is missing" in errors
    assert pr.main(["--repo", repo.dir, "--rev", "HEAD", "--date", DATE]) == 1
    assert "tag history is broken: tag v0.1.1 is reachable" in capsys.readouterr().out


def test_verify_reachable_final_tag_without_a_section_fails(repo: _Repo) -> None:
    old = repo.commit("fix(chart-engine): a crash (#1)")
    repo.commit("feat(chart-engine): a pane (#2)")
    sha, _ = repo.merge_prep()
    repo.tag("v0.0.5", old)
    assert "CI-REL-005: tag v0.0.5 is reachable but its section '## 0.0.5' is missing" in (
        _verify(repo, sha)
    )


def test_verify_final_tag_outside_the_line_fails_as_rogue(repo: _Repo) -> None:
    repo.commit("feat(chart-engine): a pane (#1)")
    sha, _ = repo.merge_prep()
    repo.git("checkout", "-q", "-b", "side", f"{sha}~1")  # forked before the candidate
    repo.commit("fix(chart-engine): side work (#2)")
    repo.tag("v0.0.9")
    repo.git("checkout", "-q", "main")
    assert any(
        e.startswith("CI-REL-005: tag v0.0.9 is outside the line") for e in _verify(repo, sha)
    )


def _side_tag_after(repo: _Repo, name: str) -> None:
    """Fork `side` at HEAD, tag a commit there as `name`, and return to main."""
    repo.git("checkout", "-q", "-b", "side")
    repo.commit("fix(chart-engine): side work (#8)")
    repo.tag(name)
    repo.git("checkout", "-q", "main")


def test_verify_final_tag_on_a_branch_forked_after_the_candidate_is_rogue(repo: _Repo) -> None:
    repo.commit("feat(chart-engine): a pane (#1)")
    sha, _ = repo.merge_prep()
    _side_tag_after(repo, "v0.5.0")
    assert any(
        e.startswith("CI-REL-005: tag v0.5.0 is outside the line") for e in _verify(repo, sha)
    )


def test_prepare_final_tag_on_a_branch_forked_at_the_tip_refuses_as_rogue(
    repo: _Repo, capsys: pytest.CaptureFixture[str]
) -> None:
    repo.commit("feat(chart-engine): a pane (#1)")
    _side_tag_after(repo, "v0.5.0")
    assert pr.main(["--repo", repo.dir, "--rev", "HEAD", "--date", DATE]) == 1
    assert "tag history is broken: tag v0.5.0 is outside the line" in capsys.readouterr().out


def test_verify_later_release_on_the_same_line_is_not_rogue(repo: _Repo) -> None:
    first = _released(repo)
    repo.commit("fix(chart-engine): a crash (#3)")
    repo.merge_prep(4)
    repo.tag("v0.1.1")
    assert _verify(repo, first) == []


# --- reopen ----------------------------------------------------------------------------------


def test_reopen_unknown_content_in_the_untagged_section_raises() -> None:
    text = uc._default_changelog() + "\n## 0.1.0 — 2026-11-01\n\nnot an entry\n"
    with pytest.raises(uc.ChangelogFormatError, match=r"untagged '## 0\.1\.0' section"):
        pr.reopen(text, "0.1.0")


def test_reopen_keeps_section_entries_first_and_unreleased_entries_after() -> None:
    base = uc._default_changelog().replace("### Fixes\n", "### Fixes\n- later (#3)\n")
    text = base + "\n## 0.1.0 — 2026-11-01\n\n### Fixes\n- earlier (#2)\n"
    out = pr.reopen(text, "0.1.0")
    assert pr.section_versions(out) == []
    assert out.index("- earlier (#2)") < out.index("- later (#3)")


def test_prepare_cli_impossible_date_is_refused(repo: _Repo) -> None:
    repo.commit("fix(chart-engine): a crash (#2)")
    with pytest.raises(SystemExit) as exc:
        pr.main(["--repo", repo.dir, "--rev", "HEAD", "--date", "2026-13-45"])
    assert exc.value.code == 2
    assert repo.read(pr.VERSION_FILE) == "0.0.0\n"
