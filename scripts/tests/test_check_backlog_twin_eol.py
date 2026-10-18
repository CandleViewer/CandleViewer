"""#3495: scripts/check_backlog_twin_eol.py fails unless every backlog twin blob is LF.

validate.py --check reads a twin's CRLF line endings as LF (#3454), so it cannot see a CRLF blob.
The git CLI never commits one under the repo's .gitattributes (`* text=auto eol=lf`); a commit made
without git's clean filter can, such as a web-editor or contents-API commit. Each case builds a
scratch repo with the real .gitattributes and plants such a blob with `git hash-object --no-filters`
and `git update-index`, the way that commit stores it."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_backlog_twin_eol as mod  # path shim above, same as sibling tests

ROOT = Path(__file__).resolve().parents[2]
BACKLOG = "docs/plan/backlog"
TWIN = f"{BACKLOG}/E17.json"
LF = b'[\n  {\n    "key": "E17-T01"\n  }\n]'  # json.dump(indent=2) writes no final newline
# A blob committed past the clean filter -> the line endings `git ls-files --eol` names for it.
BAD = {
    "crlf": (LF.replace(b"\n", b"\r\n"), "crlf"),
    "mixed": (LF.replace(b"\n", b"\r\n", 1), "mixed"),
    "lone-cr": (LF.replace(b"\n", b"\r"), "-text"),  # a lone CR makes the blob binary to git
    "cr-crlf": (LF.replace(b"\n", b"\r\r\n"), "-text"),
    "one-line": (b"[]", "none"),  # an empty twin: validate.py writes `[]`, no newline
}


@pytest.fixture(autouse=True)
def _scratch_git(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """git sees only the scratch repos: no hook's GIT_DIR or index, no user or system config, and
    no repository above tmp_path."""
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))


def _git(repo: Path, *args: str, stdin: bytes | None = None) -> str:
    done = subprocess.run(["git", *args], cwd=repo, input=stdin, capture_output=True, check=True)
    return done.stdout.decode("utf-8")


def _repo(tmp_path: Path) -> Path:
    """The real .gitattributes, two LF twins, and a one-line JSON under _tools/: no twin, i/none."""
    repo = tmp_path / "repo"
    (repo / BACKLOG / "_tools").mkdir(parents=True)
    _git(repo, "init", "-q")
    (repo / ".gitattributes").write_bytes((ROOT / ".gitattributes").read_bytes())
    (repo / TWIN).write_bytes(LF)
    (repo / BACKLOG / "all-tickets.json").write_bytes(LF + b"\n")
    (repo / BACKLOG / "_tools" / "published.json").write_bytes(b"[]")
    _git(repo, "add", "-A")
    return repo


def _plant(repo: Path, blob: bytes) -> None:
    """Stage `blob` as E17.json past git's clean filter, as a web or API commit stores it; the work
    tree gets the same bytes, as a checkout of that commit writes them."""
    (repo / TWIN).write_bytes(blob)
    sha = _git(repo, "hash-object", "-w", "--no-filters", "--stdin", stdin=blob).strip()
    _git(repo, "update-index", "--add", "--cacheinfo", f"100644,{sha},{TWIN}")


def _run(repo: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = mod.main(["--repo-root", str(repo)])
    return code, capsys.readouterr().out


def test_lf_twins_pass_and_json_below_the_backlog_is_no_twin(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ok = "TWIN-EOL ok: all 2 docs/plan/backlog/*.json blobs are committed as LF\n"
    assert _run(_repo(tmp_path), capsys) == (0, ok)


def test_the_git_cli_commits_crlf_and_mixed_twins_as_lf(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    for name in ("crlf", "mixed"):
        (repo / TWIN).write_bytes(BAD[name][0])
        _git(repo, "add", TWIN)
        assert mod.index_eols(repo)[TWIN] == "lf", name
    assert _run(repo, capsys)[0] == 0


@pytest.mark.parametrize("name", sorted(BAD))
def test_a_twin_blob_committed_past_the_clean_filter_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], name: str
) -> None:
    repo = _repo(tmp_path)
    blob, eol = BAD[name]
    _plant(repo, blob)
    code, out = _run(repo, capsys)
    assert code == 1
    assert out.splitlines()[0] == f"TWIN-EOL {TWIN}: the committed blob is i/{eol}, not i/lf"
    assert "all-tickets.json" not in out and "_tools" not in out
    assert "AGENTS.md section 3a" in out and "git add --renormalize docs/plan/backlog" in out


@pytest.mark.parametrize("name", ["crlf", "mixed"])
def test_renormalize_restages_a_crlf_twin_blob_as_lf(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], name: str
) -> None:
    repo = _repo(tmp_path)
    _plant(repo, BAD[name][0])
    _git(repo, "add", "--renormalize", BACKLOG)
    assert _run(repo, capsys)[0] == 0


@pytest.mark.parametrize("name", sorted(BAD))
def test_a_resaved_twin_restages_as_lf(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], name: str
) -> None:
    repo = _repo(tmp_path)
    _plant(repo, BAD[name][0])
    (repo / TWIN).write_bytes(LF)  # what the AGENTS.md section 3a recipe writes
    _git(repo, "add", TWIN)
    assert _run(repo, capsys)[0] == 0


def test_a_resaved_empty_twin_stays_none_and_the_hint_says_what_fixes_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    with (repo / TWIN).open("w", encoding="utf-8", newline="\n") as fh:  # AGENTS.md section 3a
        json.dump([], fh, ensure_ascii=False, indent=2)
    _git(repo, "add", TWIN)
    code, out = _run(repo, capsys)
    assert code == 1
    assert out.startswith(f"TWIN-EOL {TWIN}: the committed blob is i/none, not i/lf\n")
    assert "an empty twin (`[]`) stays i/none however it is saved: add its kind=Epic row" in out


def test_no_twin_fails_as_a_gate_that_checks_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    _git(repo, "rm", "-q", "--cached", TWIN, f"{BACKLOG}/all-tickets.json")
    code, out = _run(repo, capsys)
    assert code == 1
    assert out.startswith("TWIN-EOL no tracked file matches :(glob)docs/plan/backlog/*.json")


def test_git_failing_or_a_missing_root_is_an_internal_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "plain").mkdir()  # no repository in it or above it (GIT_CEILING_DIRECTORIES)
    codes = [mod.main(["--repo-root", str(tmp_path / name)]) for name in ("plain", "missing")]
    lines = capsys.readouterr().err.splitlines()
    assert codes == [2, 2]
    assert lines[0].startswith("TWIN-EOL internal error: git ls-files failed: fatal: not a git")
    assert lines[1].startswith("TWIN-EOL internal error: ")


def test_a_twin_path_that_is_not_utf8_is_an_internal_error_not_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repo(tmp_path)
    sha = _git(repo, "hash-object", "-w", "--stdin", stdin=LF).strip()
    name = os.fsdecode(b"E\xff.json")  # git keeps a path's raw bytes; the index needs no file
    _git(repo, "update-index", "--add", "--cacheinfo", f"100644,{sha},{BACKLOG}/{name}")
    assert mod.main(["--repo-root", str(repo)]) == 2
    err = capsys.readouterr().err
    assert err.startswith("TWIN-EOL internal error: git ls-files lists a path that is not UTF-8: ")


def test_this_checkout_s_twin_blobs_are_lf_and_the_only_ones_checked(
    capsys: pytest.CaptureFixture[str],
) -> None:
    eols = mod.index_eols(ROOT)
    names = {Path(path).name for path in eols}
    assert {Path(path).parent.as_posix() for path in eols} == {BACKLOG}  # no _tools/, schema/
    assert names == {path.name for path in (ROOT / BACKLOG).glob("*.json")}
    assert "all-tickets.json" in names and len(names) > 1
    assert mod.main([]) == 0
    assert capsys.readouterr().out.startswith(f"TWIN-EOL ok: all {len(names)} ")


def test_every_pr_runs_the_check_as_a_gates_step() -> None:
    """test_pr_yml_gates.py pins the step's lane wiring; this pins what it runs."""
    pr = yaml.safe_load((ROOT / ".github/workflows/pr.yml").read_text(encoding="utf-8"))
    (step,) = [s for s in pr["jobs"]["gates"]["steps"] if s.get("id") == "backlog-twin-eol"]
    assert step["run"] == "python scripts/check_backlog_twin_eol.py"
