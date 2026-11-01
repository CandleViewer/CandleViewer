"""Unit tests for tools/ci/verify_questdb_ddl_lock.py (#4014, C-5.4).

The check pins the bytes of every applied `backend/db/questdb/*.sql` file in
`backend/db/questdb/lockfile.json` and compares the tree with the merge base. The pure `verify`
runs on `tmp_path` trees; the base loader runs on a real throwaway git repository, hermetic: no
global or system git config, a fixed identity, `main` as the base branch. No network.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.ci import verify_questdb_ddl_lock as gate  # noqa: E402 - the repo root comes first

DDL = "backend/db/questdb"
LOCK = f"{DDL}/lockfile.json"
CORE = b"CREATE TABLE trades (ts TIMESTAMP, price DOUBLE) TIMESTAMP(ts) PARTITION BY DAY WAL;\n"
MORE = b"ALTER TABLE trades ADD COLUMN side SYMBOL;\n"
FILES = {"0001_core.sql": CORE, "0002_more.sql": MORE}
HEX = "a" * 64
DUPLICATE_KEY = '{"files": {"0001_a.sql": {"sha256": "H"}, "0001_a.sql": {"sha256": "H"}}}'.replace(
    "H", HEX
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _lock_of(files: dict[str, bytes]) -> dict[str, str]:
    return {name: _sha(data) for name, data in files.items()}


def _write_lock(root: Path, lock: dict[str, str]) -> None:
    path = root / LOCK
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = {name: {"sha256": sha} for name, sha in lock.items()}
    path.write_text(json.dumps({"files": entries}), encoding="utf-8")


def _write_tree(root: Path, files: dict[str, bytes]) -> Path:
    ddl = root / DDL
    ddl.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (ddl / name).write_bytes(data)
    return ddl


def _found(findings: list[gate.Violation]) -> list[tuple[str, str]]:
    return sorted((f.code, f.file) for f in findings)


@pytest.fixture
def tree(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """The applied files on disk and their lock; the merge base holds the same bytes."""
    return _write_tree(tmp_path, FILES), _lock_of(FILES)


def test_verify_clean_tree_returns_no_findings(tree: tuple[Path, dict[str, str]]) -> None:
    ddl, lock = tree
    assert gate.verify(lock, ddl, None) == []
    assert gate.verify(lock, ddl, dict(lock)) == []


def test_verify_edited_locked_file_reports_a_changed_hash(
    tree: tuple[Path, dict[str, str]],
) -> None:
    ddl, lock = tree
    (ddl / "0001_core.sql").write_bytes(CORE + b"-- edited\n")
    assert _found(gate.verify(lock, ddl, None)) == [("CI-QDB-LOCK-001", "0001_core.sql")]


def test_verify_new_file_without_an_entry_reports_unlisted(
    tree: tuple[Path, dict[str, str]],
) -> None:
    ddl, lock = tree
    (ddl / "0003_new.sql").write_bytes(b"SELECT 1;\n")
    assert _found(gate.verify(lock, ddl, dict(lock))) == [("CI-QDB-LOCK-002", "0003_new.sql")]


def test_verify_listed_file_missing_on_disk_reports_missing(
    tree: tuple[Path, dict[str, str]],
) -> None:
    ddl, lock = tree
    (ddl / "0002_more.sql").unlink()
    assert _found(gate.verify(lock, ddl, None)) == [("CI-QDB-LOCK-003", "0002_more.sql")]


def test_verify_renamed_file_reports_missing_and_unlisted_and_changed_against_the_base(
    tree: tuple[Path, dict[str, str]],
) -> None:
    ddl, lock = tree
    (ddl / "0002_more.sql").rename(ddl / "0002_renamed.sql")
    assert _found(gate.verify(lock, ddl, dict(lock))) == [
        ("CI-QDB-LOCK-002", "0002_renamed.sql"),
        ("CI-QDB-LOCK-003", "0002_more.sql"),
        ("CI-QDB-LOCK-004", "0002_more.sql"),
    ]


def test_verify_edit_with_its_own_entry_rewritten_reports_changed_against_the_merge_base(
    tree: tuple[Path, dict[str, str]],
) -> None:
    ddl, base = tree
    edited = CORE + b"-- edited together with its entry\n"
    (ddl / "0001_core.sql").write_bytes(edited)
    lock = base | {"0001_core.sql": _sha(edited)}
    assert gate.verify(lock, ddl, None) == []  # self-consistent: only the merge base shows it
    assert _found(gate.verify(lock, ddl, base)) == [("CI-QDB-LOCK-004", "0001_core.sql")]


def test_verify_delete_of_an_applied_file_and_its_entry_reports_changed_against_the_merge_base(
    tree: tuple[Path, dict[str, str]],
) -> None:
    ddl, base = tree
    (ddl / "0002_more.sql").unlink()
    lock = {name: sha for name, sha in base.items() if name != "0002_more.sql"}
    assert gate.verify(lock, ddl, None) == []
    assert _found(gate.verify(lock, ddl, base)) == [("CI-QDB-LOCK-004", "0002_more.sql")]


def test_verify_new_file_with_its_entry_passes_against_the_merge_base(
    tree: tuple[Path, dict[str, str]],
) -> None:
    ddl, base = tree
    new = b"ALTER TABLE trades ADD COLUMN qty DOUBLE;\n"
    (ddl / "0003_new.sql").write_bytes(new)
    assert gate.verify(base | {"0003_new.sql": _sha(new)}, ddl, base) == []


@pytest.mark.parametrize(
    ("rewrite_entry", "codes"),
    [(False, ["CI-QDB-LOCK-001", "CI-QDB-LOCK-004"]), (True, ["CI-QDB-LOCK-004"])],
    ids=["entry-kept", "entry-rewritten"],
)
def test_verify_comment_only_edit_of_an_applied_file_is_refused(
    tree: tuple[Path, dict[str, str]], rewrite_entry: bool, codes: list[str]
) -> None:
    ddl, base = tree
    edited = CORE + b"-- a comment changes no statement\n"
    (ddl / "0001_core.sql").write_bytes(edited)
    lock = base | ({"0001_core.sql": _sha(edited)} if rewrite_entry else {})
    assert _found(gate.verify(lock, ddl, base)) == [(c, "0001_core.sql") for c in codes]


@pytest.mark.parametrize(
    ("rewrite_entry", "codes"),
    [(False, ["CI-QDB-LOCK-001", "CI-QDB-LOCK-004"]), (True, ["CI-QDB-LOCK-004"])],
    ids=["entry-kept", "entry-rewritten"],
)
def test_verify_line_ending_change_of_an_applied_file_is_refused(
    tree: tuple[Path, dict[str, str]], rewrite_entry: bool, codes: list[str]
) -> None:
    ddl, base = tree
    crlf = CORE.replace(b"\n", b"\r\n")
    (ddl / "0001_core.sql").write_bytes(crlf)
    lock = base | ({"0001_core.sql": _sha(crlf)} if rewrite_entry else {})
    assert _found(gate.verify(lock, ddl, base)) == [(c, "0001_core.sql") for c in codes]


@pytest.mark.parametrize("replacement", ["symlink", "directory"])
def test_verify_symlinked_ddl_file_is_refused(
    tree: tuple[Path, dict[str, str]], tmp_path: Path, replacement: str
) -> None:
    ddl, base = tree
    (ddl / "0002_more.sql").unlink()
    if replacement == "symlink":  # the same bytes, behind a link that leaves the directory
        (tmp_path / "elsewhere.sql").write_bytes(MORE)
        (ddl / "0002_more.sql").symlink_to(tmp_path / "elsewhere.sql")
    else:
        (ddl / "0002_more.sql").mkdir()
    assert _found(gate.verify(base, ddl, base)) == [("CI-QDB-LOCK-005", "0002_more.sql")]
    assert _found(gate.verify(base, ddl, None)) == [("CI-QDB-LOCK-005", "0002_more.sql")]


def test_ddl_files_lists_only_the_top_level_sql_files_by_name(
    tree: tuple[Path, dict[str, str]],
) -> None:
    ddl, _ = tree
    (ddl / "nested").mkdir()
    (ddl / "nested" / "0003_nested.sql").write_bytes(b"SELECT 3;\n")
    (ddl / "0004_UPPER.SQL").write_bytes(b"SELECT 4;\n")
    (ddl / "0005_link.sql").symlink_to("0001_core.sql")
    (ddl / "0006_dir.sql").mkdir()
    (ddl / "lockfile.json").write_text("{}", encoding="utf-8")
    assert list(gate.ddl_files(ddl)) == [*FILES, "0005_link.sql", "0006_dir.sql"]


def test_render_names_an_unusual_file_on_one_line(tree: tuple[Path, dict[str, str]]) -> None:
    ddl, lock = tree
    (ddl / "0003_odd\nname.sql").write_bytes(b"SELECT 1;\n")
    (finding,) = gate.verify(lock, ddl, None)
    line = gate.render(finding)
    assert "\n" not in line
    assert line.startswith("CI-QDB-LOCK-002 ['0003_odd\\nname.sql']: ")


# --- The malformed lock -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "{",
        "[]",
        json.dumps({"files": []}),
        json.dumps({"files": {"0001_a.sql": "not an object"}}),
        json.dumps({"files": {"0001_a.sql": {}}}),
        json.dumps({"files": {"0001_a.sql": {"sha256": HEX[:63]}}}),
        json.dumps({"files": {"0001_a.sql": {"sha256": HEX.upper()}}}),
        json.dumps({"files": {"sub/0001_a.sql": {"sha256": HEX}}}),
        json.dumps({"files": {"0001_a.txt": {"sha256": HEX}}}),
        DUPLICATE_KEY,
    ],
    ids=[
        "not-json",
        "not-an-object",
        "files-not-an-object",
        "entry-not-an-object",
        "entry-without-a-hash",
        "short-hash",
        "uppercase-hash",
        "key-with-a-path",
        "key-not-sql",
        "duplicate-key",
    ],
)
def test_load_lock_refuses_a_malformed_lock(tmp_path: Path, text: str) -> None:
    path = tmp_path / "lockfile.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(gate.LockError):
        gate.load_lock(path)


def test_load_lock_refuses_a_missing_lock(tmp_path: Path) -> None:
    with pytest.raises(gate.LockError):
        gate.load_lock(tmp_path / "lockfile.json")


# --- The base loader, on a real throwaway repository ------------------------------------------


@pytest.fixture
def git_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No global or system git config and a fixed identity, for the tests and the check's git."""
    identity = {"NAME": "t", "EMAIL": "t@example.invalid"}
    env = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(tmp_path)}
    for role in ("AUTHOR", "COMMITTER"):
        env |= {f"GIT_{role}_{key}": value for key, value in identity.items()}
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)  # noqa: S603, S607


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


@pytest.fixture
def repo(tmp_path: Path, git_env: None) -> Path:
    """`main` holds the two applied files and their lock; HEAD is on `main`."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _write_tree(root, FILES)
    _write_lock(root, _lock_of(FILES))
    _commit(root, "the applied files")
    return root


def test_load_base_reads_only_the_top_level_sql_files_at_the_merge_base(repo: Path) -> None:
    ddl = repo / DDL
    (ddl / "nested").mkdir()
    (ddl / "nested" / "0003_nested.sql").write_bytes(b"SELECT 3;\n")
    (ddl / "0004_UPPER.SQL").write_bytes(b"SELECT 4;\n")
    (ddl / "0005_link.sql").symlink_to("0001_core.sql")
    (ddl / "notes.md").write_bytes(b"not DDL\n")
    _commit(repo, "files the base loader skips")
    _git(repo, "switch", "-q", "-c", "feature")  # the merge base is this commit
    (ddl / "0001_core.sql").write_bytes(CORE + b"-- edited on the branch\n")
    _commit(repo, "the branch edits an applied file")
    _git(repo, "switch", "-q", "main")
    (ddl / "0002_more.sql").write_bytes(MORE + b"-- edited on main after the branch point\n")
    _commit(repo, "main moves on")
    _git(repo, "switch", "-q", "feature")
    assert gate.load_base("main", ddl, repo) == _lock_of(FILES)


@pytest.mark.parametrize("ref", ["no-such-ref", "unrelated"])
def test_load_base_with_an_unresolvable_ref_fails_closed(repo: Path, ref: str) -> None:
    if ref == "unrelated":  # a ref that shares no history with HEAD has no merge base
        _git(repo, "switch", "-q", "--orphan", ref)
        _git(repo, "commit", "-q", "--allow-empty", "-m", "unrelated history")
        _git(repo, "switch", "-q", "main")
    with pytest.raises(gate.LockError):
        gate.load_base(ref, repo / DDL, repo)


def test_load_base_without_the_directory_at_the_merge_base_is_empty(
    tmp_path: Path, git_env: None
) -> None:
    root = tmp_path / "bare"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / "README.md").write_bytes(b"no DDL yet\n")
    _commit(root, "before the first DDL file")
    assert gate.load_base("main", root / DDL, root) == {}


def _no_git(*args: object, **kwargs: object) -> None:
    raise AssertionError("git ran for a ref it should have refused")


@pytest.mark.parametrize("ref", ["-x", "--all", "--help"])
def test_load_base_refuses_a_ref_that_starts_with_a_dash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ref: str
) -> None:
    monkeypatch.setattr(gate.subprocess, "run", _no_git)
    with pytest.raises(gate.LockError):
        gate.load_base(ref, tmp_path / DDL, tmp_path)


@pytest.mark.parametrize(
    "ref", ["", "a b", "a..b", "a\nb", "a\x00b", "main^{/x}", "HEAD@{1}", ":/x", "main~1"]
)
def test_load_base_refuses_a_ref_outside_the_conservative_character_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ref: str
) -> None:
    monkeypatch.setattr(gate.subprocess, "run", _no_git)
    with pytest.raises(gate.LockError):
        gate.load_base(ref, tmp_path / DDL, tmp_path)


def test_load_base_refuses_a_ddl_directory_outside_the_repository(repo: Path) -> None:
    with pytest.raises(gate.LockError):
        gate.load_base("main", repo.parent, repo)


# --- main -------------------------------------------------------------------------------------


def _edit_file_and_its_entry(repo: Path) -> None:
    edited = CORE + b"-- edited together with its entry\n"
    (repo / DDL / "0001_core.sql").write_bytes(edited)
    _write_lock(repo, _lock_of(FILES) | {"0001_core.sql": _sha(edited)})


def _bad_hash(repo: Path) -> None:
    _write_lock(repo, _lock_of(FILES) | {"0001_core.sql": "not-a-hash"})


#: case -> (prepare the repo, extra options, the exit code, what the run prints)
MAIN_CASES: dict[str, tuple[Callable[[Path], object], list[str], int, str]] = {
    "clean": (lambda repo: None, [], 0, "OK:"),
    "finding": (_edit_file_and_its_entry, [], 1, "CI-QDB-LOCK-004"),
    "missing-lock": (lambda repo: (repo / LOCK).unlink(), [], 2, "CI-QDB-LOCK-000"),
    "malformed-lock": (lambda repo: (repo / LOCK).write_text("{"), [], 2, "CI-QDB-LOCK-000"),
    "bad-hash": (_bad_hash, [], 2, "CI-QDB-LOCK-000"),
    "unresolvable-base": (lambda repo: None, ["--base-ref", "no-such-ref"], 2, "CI-QDB-LOCK-000"),
    "missing-directory": (lambda repo: None, ["--ddl-dir", "no/such/dir"], 2, "CI-QDB-LOCK-000"),
}


@pytest.mark.parametrize("case", MAIN_CASES)
def test_main_exits_0_when_clean_1_on_a_finding_and_2_on_an_internal_error(
    repo: Path, capsys: pytest.CaptureFixture[str], case: str
) -> None:
    prepare, extra, exit_code, marker = MAIN_CASES[case]
    prepare(repo)
    assert gate.main(["--repo-root", str(repo), "--base-ref", "main", *extra]) == exit_code
    out, err = capsys.readouterr()
    if exit_code == 0:
        assert out.startswith(marker) and err == ""
    else:
        assert out == "" and marker in err


def test_main_has_no_option_that_rewrites_the_lock(
    repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLUMNS", "200")  # argparse wraps help at the terminal width
    with pytest.raises(SystemExit) as stop:
        gate.main(["--help"])
    assert stop.value.code == 0
    flags = set(re.findall(r"(?<![\w-])--[a-z][a-z-]*", capsys.readouterr().out))
    options = {"--lockfile", "--ddl-dir", "--repo-root", "--base-ref", "--no-base-check", "--help"}
    assert flags == options
    before = (repo / LOCK).read_bytes()
    (repo / DDL / "0001_core.sql").write_bytes(CORE + b"-- edit\n")
    assert gate.main(["--repo-root", str(repo), "--base-ref", "main"]) == 1
    assert (repo / LOCK).read_bytes() == before
    with pytest.raises(SystemExit) as refused:
        gate.main(["--repo-root", str(repo), "--update"])
    assert refused.value.code == 2
    assert (repo / LOCK).read_bytes() == before


def test_main_with_no_base_check_skips_the_merge_base_comparison(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _edit_file_and_its_entry(repo)
    args = ["--repo-root", str(repo), "--base-ref", "no-such-ref"]
    assert gate.main(args) == 2
    assert gate.main([*args, "--no-base-check"]) == 0
    assert "skipped" in capsys.readouterr().out


def test_committed_lock_lists_every_shipped_ddl_file_with_the_hash_of_its_bytes() -> None:
    ddl = ROOT / DDL
    lock = gate.load_lock(ROOT / LOCK)
    shipped = {path.name: _sha(path.read_bytes()) for path in sorted(ddl.glob("*.sql"))}
    assert shipped, "the DDL directory holds no file"
    assert lock == shipped
    assert gate.verify(lock, ddl, None) == []
