"""#3099: tools/ci/release_run.py, the release run's GitHub steps (07 §4, release.yml).

A fake REST API in memory stands in for `gh api` (no network): each step is idempotent, so a
re-run on the same candidate creates no second tag, issue, release or comment, and a tag is never
moved. The two local steps run on scratch git repos in tmp_path.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci import release_run as rr  # noqa: E402

REPO = "owner/repo"
C = "c" * 40
OTHER = "d" * 40


class FakeGitHub:
    """Just enough of the REST API: tags/refs, commits, issues, comments and releases."""

    def __init__(self, verified: bool = True) -> None:
        self.verified = verified
        self.refs: dict[str, dict[str, str]] = {}  # "refs/tags/vX" -> object
        self.tag_objects: dict[str, dict[str, str]] = {}
        self.issues: list[dict[str, Any]] = []
        self.comments: dict[int, list[dict[str, Any]]] = {}
        self.releases: list[dict[str, Any]] = []
        self.writes: list[tuple[str, str]] = []
        self.fail_ref_create: str | None = None

    def __call__(self, method: str, path: str, payload: dict[str, Any] | None) -> Any:
        route, _, query = path.partition("?")
        page = int(dict(p.split("=") for p in query.split("&") if p).get("page", "1"))
        parts = route.split("/")
        assert parts[:3] == ["repos", "owner", "repo"], path
        rest = parts[3:]
        if method != "GET":
            self.writes.append((method, "/".join(rest)))
        if method == "GET" and rest[0] == "commits":
            return {"commit": {"verification": {"verified": self.verified}}}
        if method == "GET" and rest[:3] == ["git", "matching-refs", "tags"]:
            prefix = "refs/tags/" + rest[3]
            return [{"ref": r, "object": o} for r, o in self.refs.items() if r.startswith(prefix)]
        if method == "GET" and rest[:2] == ["git", "tags"]:
            return self.tag_objects[rest[2]]
        if method == "POST" and rest == ["git", "tags"]:
            assert payload is not None
            sha = f"{len(self.tag_objects):040x}"
            self.tag_objects[sha] = {"object": {"type": "commit", "sha": payload["object"]}}
            return {"sha": sha}
        if method == "POST" and rest == ["git", "refs"]:
            assert payload is not None
            if self.fail_ref_create is not None:
                self.refs[payload["ref"]] = {"type": "commit", "sha": self.fail_ref_create}
                raise rr.RunError("Reference already exists")
            assert payload["ref"] not in self.refs
            self.refs[payload["ref"]] = {"type": "tag", "sha": payload["sha"]}
            return {}
        if rest == ["issues"]:
            if method == "GET":
                return self.issues[(page - 1) * 100 : page * 100]
            assert payload is not None
            issue = {**payload, "number": 100 + len(self.issues), "user": {"login": rr.BOT}}
            self.issues.append(issue)
            return issue
        if rest[0] == "issues" and rest[-1] == "comments":
            number = int(rest[1])
            if method == "GET":
                return self.comments.get(number, [])[(page - 1) * 100 : page * 100]
            assert payload is not None
            comment = {"id": 900 + len(self.comments.get(number, [])), "user": {"login": rr.BOT}}
            self.comments.setdefault(number, []).append({**comment, **payload})
            return comment
        if rest[:2] == ["issues", "comments"] and method == "PATCH":
            assert payload is not None
            for comment in (c for cs in self.comments.values() for c in cs):
                if comment["id"] == int(rest[2]):
                    comment.update(payload)
            return {}
        if rest == ["releases"]:
            if method == "GET":
                return self.releases[(page - 1) * 100 : page * 100]
            assert payload is not None
            release = {**payload, "id": 700 + len(self.releases)}
            self.releases.append(release)
            return release
        if rest[0] == "releases" and method == "PATCH":
            assert payload is not None
            (release,) = [r for r in self.releases if r["id"] == int(rest[1])]
            release.update(payload)
            return release
        raise AssertionError(f"unexpected {method} {path}")


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    monkeypatch.setenv("GITHUB_RUN_ID", "42")


# --- verified ---------------------------------------------------------------------------------


def test_verified_candidate_passes(capsys: pytest.CaptureFixture[str]) -> None:
    assert rr.main(["verified", "--candidate", C], api=FakeGitHub()) == 0
    assert capsys.readouterr().out == "verified=true\n"


def test_unverified_candidate_is_refused_ci_rel_005(capsys: pytest.CaptureFixture[str]) -> None:
    assert rr.main(["verified", "--candidate", C], api=FakeGitHub(verified=False)) == 1
    out = capsys.readouterr().out
    assert out.startswith("::error::CI-REL-005: cccccc") and "not GitHub-verified" in out


@pytest.mark.parametrize("candidate", ["C" * 40, "c" * 39, "main", "-c", "c" * 41])
def test_a_candidate_that_is_not_40_lowercase_hex_is_refused(candidate: str) -> None:
    with pytest.raises(SystemExit):
        rr.main(["verified", "--candidate", candidate], api=FakeGitHub())


def test_a_malformed_repository_slug_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo/../x")
    assert rr.main(["verified", "--candidate", C], api=FakeGitHub()) == 1


# --- tag ------------------------------------------------------------------------------------------


def test_tag_is_created_once_and_a_rerun_is_a_no_op(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeGitHub()
    assert rr.main(["tag", "--candidate", C, "--version", "0.1.0"], api=api) == 0
    assert rr.main(["tag", "--candidate", C, "--version", "0.1.0"], api=api) == 0
    out = capsys.readouterr().out.splitlines()
    assert out == ["tag=v0.1.0 (created)", "tag=v0.1.0 (already at the candidate)"]
    assert [w for w in api.writes if w[1].startswith("git/")] == [
        ("POST", "git/tags"),
        ("POST", "git/refs"),
    ]
    assert rr.tag_target(api, REPO, "v0.1.0") == C  # annotated: peeled to the candidate


def test_tag_pointing_elsewhere_is_never_moved(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeGitHub()
    api.refs["refs/tags/v0.1.0"] = {"type": "commit", "sha": OTHER}
    assert rr.main(["tag", "--candidate", C, "--version", "0.1.0"], api=api) == 1
    assert "never moved" in capsys.readouterr().out
    assert api.writes == [] and api.refs["refs/tags/v0.1.0"]["sha"] == OTHER


def test_tag_prefix_matches_are_not_the_tag() -> None:
    api = FakeGitHub()
    api.refs["refs/tags/v0.1.10"] = {"type": "commit", "sha": OTHER}
    assert rr.ensure_tag(api, REPO, "0.1.1", C) is True
    assert rr.tag_target(api, REPO, "v0.1.1") == C


def test_tag_race_won_by_a_concurrent_run_of_the_same_candidate_is_fine() -> None:
    api = FakeGitHub()
    api.fail_ref_create = C
    assert rr.ensure_tag(api, REPO, "0.1.0", C) is False


def test_tag_race_lost_to_another_commit_fails() -> None:
    api = FakeGitHub()
    api.fail_ref_create = OTHER
    with pytest.raises(rr.RunError, match="already exists"):
        rr.ensure_tag(api, REPO, "0.1.0", C)


# --- checklist ------------------------------------------------------------------------------------


def test_checklist_issue_is_found_or_created_once(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeGitHub()
    assert rr.main(["checklist", "--version", "0.1.0"], api=api) == 0
    assert rr.main(["checklist", "--version", "0.1.0"], api=api) == 0
    assert capsys.readouterr().out.splitlines() == ["issue=100", "issue=100"]
    (issue,) = api.issues
    assert issue["title"] == "[Release]: v0.1.0 checklist"
    assert issue["labels"] == ["type/release", "priority/p1-high"]
    assert "CI-REL-004" in issue["body"] and "/owner/repo/actions/runs/42" in issue["body"]


def test_checklist_ignores_a_same_titled_issue_someone_else_opened() -> None:
    # Anyone may open an issue from the release-checklist form, labels included; the PRR gate
    # is ticked on the checklist issue, so only the automation's own issue counts.
    api = FakeGitHub()
    forged = {"number": 7, "title": "[Release]: v0.1.0 checklist", "user": {"login": "someone"}}
    api.issues.append(forged)
    pr = {"number": 8, "title": forged["title"], "user": {"login": rr.BOT}, "pull_request": {}}
    api.issues.append(pr)
    number, created = rr.ensure_checklist(api, REPO, "0.1.0")
    assert created and number not in (7, 8)


def test_checklist_lookup_pages_through_every_release_issue() -> None:
    api = FakeGitHub()
    api.issues += [{"number": i, "title": f"x{i}", "user": {"login": rr.BOT}} for i in range(150)]
    api.issues.append(
        {"number": 999, "title": "[Release]: v0.2.0 checklist", "user": {"login": rr.BOT}}
    )
    assert rr.ensure_checklist(api, REPO, "0.2.0") == (999, False)


# --- draft ----------------------------------------------------------------------------------------


def test_draft_release_body_is_the_version_section_and_a_rerun_creates_no_second(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    api = FakeGitHub()
    notes = tmp_path / "section.md"
    notes.write_text("## 0.1.0 — 2026-11-02\n\n### Fixes\n\n- a fix (#1)\n", encoding="utf-8")
    argv = ["draft", "--candidate", C, "--version", "0.1.0", "--notes-file", str(notes)]
    assert rr.main(argv, api=api) == 0
    assert rr.main(argv, api=api) == 0
    assert capsys.readouterr().out.splitlines() == ["release=700 (created)", "release=700 (kept)"]
    (release,) = api.releases
    assert release["body"] == notes.read_text(encoding="utf-8")
    assert (release["tag_name"], release["target_commitish"], release["draft"]) == (
        "v0.1.0",
        C,
        True,
    )


def test_draft_rerun_rewrites_a_drifted_body(tmp_path: Path) -> None:
    api = FakeGitHub()
    api.releases.append(
        {"id": 5, "tag_name": "v0.1.0", "name": "v0.1.0", "body": "x", "draft": True}
    )
    assert rr.ensure_draft(api, REPO, "0.1.0", C, "## 0.1.0\n") == (5, "updated")
    assert api.releases[0]["body"] == "## 0.1.0\n"


def test_draft_on_a_published_release_refuses_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A re-dispatch on a shipped candidate must fail before the asset uploads (C-15.7): the old
    # shape returned "published, left alone" with exit 0 and the run went on to --clobber.
    api = FakeGitHub()
    api.releases.append(
        {"id": 5, "tag_name": "v0.1.0", "name": "v0.1.0", "body": "## 0.1.0\n", "draft": False}
    )
    notes = tmp_path / "section.md"
    notes.write_text("other\n", encoding="utf-8")
    argv = ["draft", "--candidate", C, "--version", "0.1.0", "--notes-file", str(notes)]
    assert rr.main(argv, api=api) == 1
    out = capsys.readouterr().out
    assert (
        out.startswith("::error::CI-REL-005: release v0.1.0 is published") and "release=" not in out
    )
    assert api.writes == [] and api.releases[0]["body"] == "## 0.1.0\n"


def test_draft_refuses_empty_notes(tmp_path: Path) -> None:
    notes = tmp_path / "section.md"
    notes.write_text("\n", encoding="utf-8")
    argv = ["draft", "--candidate", C, "--version", "0.1.0", "--notes-file", str(notes)]
    assert rr.main(argv, api=FakeGitHub()) == 1


def test_release_body_past_the_api_limit_is_cut_on_a_line_with_a_pointer() -> None:
    notes = "".join(f"- entry {i} (#{i})\n" for i in range(12_000))
    body = rr.release_body("0.1.0", notes)
    assert len(body) <= rr.MAX_RELEASE_BODY
    assert body.endswith("CHANGELOG.md at `v0.1.0`._\n")
    kept = body.split("\n_Cut")[0]
    assert notes.startswith(kept) and kept.endswith(")\n")
    assert rr.release_body("0.1.0", "short\n") == "short\n"


# --- comment --------------------------------------------------------------------------------------


def test_sbom_diff_comment_is_posted_once_and_edited_in_place(tmp_path: Path) -> None:
    api = FakeGitHub()
    diff = tmp_path / "sbom-diff.md"
    diff.write_text("### api\n- + `a@1`\n", encoding="utf-8")
    argv = ["comment", "--issue", "100", "--version", "0.1.0", "--body-file", str(diff)]
    assert rr.main(argv, api=api) == 0
    assert rr.main(argv, api=api) == 0
    diff.write_text("### api\n- + `b@2`\n", encoding="utf-8")
    assert rr.main(argv, api=api) == 0
    (comment,) = api.comments[100]
    assert comment["body"] == rr.comment_marker("0.1.0") + "\n### api\n- + `b@2`\n"
    assert [w[0] for w in api.writes] == ["POST", "PATCH"]


def test_sbom_diff_comment_never_edits_someone_elses_comment() -> None:
    api = FakeGitHub()
    marker = rr.comment_marker("0.1.0")
    api.comments[100] = [{"id": 1, "body": marker + "\nforged", "user": {"login": "someone"}}]
    assert rr.upsert_comment(api, REPO, 100, "0.1.0", "diff\n") == "created"
    assert api.comments[100][0]["body"] == marker + "\nforged"


def test_long_sbom_diff_comment_is_cut_with_a_pointer_to_the_asset() -> None:
    api = FakeGitHub()
    text = "".join(f"- + `pkg{i}@1.0.0`\n" for i in range(10_000))
    rr.upsert_comment(api, REPO, 100, "0.1.0", text)
    body = api.comments[100][0]["body"]
    assert len(body) <= rr.MAX_COMMENT + 100 and body.endswith("`sbom-diff.md`._\n")


# --- local steps: previous-tag and untagged -------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_DATE": "2026-11-01T00:00:00Z",
        "GIT_COMMITTER_DATE": "2026-11-01T00:00:00Z",
    }
    cmd = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    cmd += ["-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", *args]
    return subprocess.run(cmd, check=True, capture_output=True, text=True, env=env).stdout.strip()


def _repo(tmp_path: Path, changelog: str) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    _git(repo, "add", "CHANGELOG.md")
    _git(repo, "commit", "-q", "-m", "chore(infra-devops): prepare release 0.1.0")
    return repo


SECTIONED = "# Changelog\n\n## Unreleased\n\n## 0.1.0 — 2026-11-01\n\n### Fixes\n\n- f (#1)\n"


def test_previous_tag_excludes_the_candidates_own_tag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path, SECTIONED)
    _git(repo, "tag", "v0.0.1")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "fix: x")
    _git(repo, "tag", "-a", "v0.1.0", "-m", "v0.1.0")
    _git(repo, "tag", "v0.1.1-rc.1")
    argv = ["previous-tag", "--repo", str(repo), "--rev", "HEAD", "--exclude", "v0.1.0"]
    assert rr.main(argv) == 0
    assert (
        rr.main(["previous-tag", "--repo", str(repo), "--rev", "HEAD~1", "--exclude", "v0.0.1"])
        == 0
    )
    assert capsys.readouterr().out.splitlines() == ["previous=v0.0.1", "previous="]


def test_untagged_names_the_topmost_section_without_a_tag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path, SECTIONED)
    summary = tmp_path / "summary.md"
    argv = ["untagged", "--repo", str(repo), "--changelog", str(repo / "CHANGELOG.md")]
    assert rr.main([*argv, "--summary", str(summary)]) == 0
    assert "Untagged candidate:** `## 0.1.0` has no tag `v0.1.0`" in summary.read_text("utf-8")
    _git(repo, "tag", "v0.1.0")
    assert rr.main(argv) == 0
    assert capsys.readouterr().out.splitlines() == ["untagged=0.1.0", "untagged="]


def test_untagged_without_a_version_section_names_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path, "# Changelog\n\n## Unreleased\n")
    summary = tmp_path / "summary.md"
    argv = ["untagged", "--repo", str(repo), "--changelog", str(repo / "CHANGELOG.md")]
    assert rr.main([*argv, "--summary", str(summary)]) == 0
    assert capsys.readouterr().out == "untagged=\n" and not summary.exists()


def test_gh_api_sends_the_payload_on_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen["cmd"], seen["input"] = cmd, kwargs.get("input")
        return subprocess.CompletedProcess(cmd, 0, stdout='{"ok": true}', stderr="")

    monkeypatch.setattr(rr.subprocess, "run", fake_run)
    assert rr.gh_api("POST", "repos/o/r/issues", {"title": "t"}) == {"ok": True}
    assert seen["cmd"][-2:] == ["--input", "-"] and json.loads(seen["input"]) == {"title": "t"}


def test_gh_api_failure_is_a_run_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="HTTP 404")

    monkeypatch.setattr(rr.subprocess, "run", fake_run)
    with pytest.raises(rr.RunError, match="HTTP 404"):
        rr.gh_api("GET", "repos/o/r/commits/x")
