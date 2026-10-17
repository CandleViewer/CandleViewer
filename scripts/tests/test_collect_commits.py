"""Tests for tools/ci/collect_commits.py (#2341): "since the last tag" means since the nearest
FINAL v* tag reachable from the revision. Throwaway git repos in tmp_path with fixed dates and
no global or system git config; the shallow clone uses a local file:// URL, so no network."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci import collect_commits as cc

_ID = ["-c", "user.name=t", "-c", "user.email=t@example.invalid"]


class _Repo:
    def __init__(self, path: Path) -> None:
        self.path, self.count = path, 0
        self.git("init", "-q", "-b", "main")

    def git(self, *args: str, env: dict[str, str] | None = None) -> str:
        cmd = ["git", "-C", str(self.path), *_ID, *args]
        done = subprocess.run(cmd, check=True, capture_output=True, text=True, env=env)
        return done.stdout.strip()

    def commit(self, subject: str) -> str:
        self.count += 1
        date = f"2026-10-01T00:{self.count:02d}:00+00:00"
        env = {**os.environ, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
        self.git("commit", "-q", "--allow-empty", "-m", subject, env=env)
        return self.git("rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Repo:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    (tmp_path / "repo").mkdir()
    return _Repo(tmp_path / "repo")


def _shas(repo: _Repo, **kwargs: str) -> list[str]:
    return [c["sha"] for c in cc.commits_since_last_tag(repo=str(repo.path), **kwargs)]


def test_no_tags_returns_all_commits_newest_first(repo: _Repo) -> None:
    first, second = repo.commit("feat(chart): a"), repo.commit("fix(chart): b\n\nbody")
    got = cc.commits_since_last_tag(repo=str(repo.path))
    assert [c["sha"] for c in got] == [second, first]
    assert got[0]["message"] == "fix(chart): b\n\nbody"


def test_tag_at_head_parent_returns_only_head(repo: _Repo) -> None:
    repo.commit("feat(chart): a")
    repo.git("tag", "v0.1.0")
    head = repo.commit("fix(chart): b")
    assert _shas(repo) == [head]


def test_tagged_head_returns_nothing_unless_that_tag_is_excluded(repo: _Repo) -> None:
    repo.commit("feat(chart): a")
    repo.git("tag", "v0.1.0")
    head = repo.commit("fix(chart): b")
    repo.git("tag", "-a", "v0.1.1", "-m", "v0.1.1")
    assert _shas(repo) == []
    assert _shas(repo, exclude="v0.1.1") == [head]


def test_patch_branch_ignores_a_newer_tag_that_is_not_an_ancestor(repo: _Repo) -> None:
    base = repo.commit("feat(chart): a")
    repo.git("tag", "v0.1.0")
    repo.commit("feat(chart): b")
    repo.git("tag", "v0.2.0")
    repo.git("checkout", "-q", "-b", "patch", base)
    repo.commit("fix(chart): cherry-picked")
    repo.git("tag", "v0.1.1")
    head = repo.commit("fix(chart): next")
    repo.git("checkout", "-q", "main")
    assert cc.last_final_tag("patch", str(repo.path)) == "v0.1.1"
    assert _shas(repo, rev="patch") == [head]


def test_pre_release_tags_are_not_final(repo: _Repo) -> None:
    repo.commit("feat(chart): a")
    repo.git("tag", "v0.1.0")
    rc = repo.commit("feat(chart): b")
    repo.git("tag", "v0.2.0-rc.1")
    head = repo.commit("fix(chart): c")
    assert _shas(repo) == [head, rc]


def test_shallow_clone_and_unknown_revision_are_refused(repo: _Repo, tmp_path: Path) -> None:
    repo.commit("feat(chart): a")
    repo.commit("fix(chart): b")
    clone = tmp_path / "shallow"
    repo.git("clone", "-q", "--depth", "1", f"file://{repo.path}", str(clone))
    with pytest.raises(cc.CollectCommitsError, match="shallow"):
        cc.commits_since_last_tag(repo=str(clone))
    for rev in ("no-such-rev", "--output=x"):
        with pytest.raises(cc.CollectCommitsError, match="revision"):
            cc.commits_since_last_tag(rev, str(repo.path))


def test_cli_writes_json_and_exits_1_on_error(repo: _Repo, tmp_path: Path) -> None:
    repo.commit("feat(chart): a")
    repo.git("tag", "v0.1.0")
    head = repo.commit("fix(chart): b")
    out = tmp_path / "commits.json"
    assert cc.main(["--repo", str(repo.path), "--exclude", "v9.9.9", "--out", str(out)]) == 0
    assert [c["sha"] for c in json.loads(out.read_text(encoding="utf-8"))] == [head]
    assert cc.main(["--repo", str(repo.path), "--rev", "no-such-rev"]) == 1
