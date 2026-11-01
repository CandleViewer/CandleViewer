"""The edit hook `.claude/hooks/pre_edit_guard.py` (#4014, C-5.4).

Run as a subprocess on a throwaway git repository whose `origin/main` holds an applied QuestDB DDL
file, its lock, an applied Alembic revision and SQL files outside the DDL directory, with the tool's
JSON on stdin. An edit of an applied file is blocked (exit 2, the reason on stderr); a new file, the
lock beside the DDL files and a SQL file elsewhere pass, one under `backend/db/` included; the hook
passes on input it cannot read. Hermetic: no global or system git config, no network.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / ".claude" / "hooks" / "pre_edit_guard.py"
DDL = "backend/db/questdb"
REVISIONS = "services/api/candleviewer/migrations/versions"
STATECHART = "services/api/candleviewer/statechart"
APPLIED_DDL = f"{DDL}/0001_core.sql"
APPLIED_REVISION = f"{REVISIONS}/0001_initial.py"
OTHER_SQL = "infra/scripts/pg_bootstrap.sql"
NEAR_MISS_SQL = "backend/db/seeds/example.sql"  # under `backend/db/`, beside the DDL directory
IMPORT = "import xstate_statemachine as xs\n"
IDENTITY = {"NAME": "t", "EMAIL": "t@example.invalid"}


def _env(project: Path, tmp_path: Path) -> dict[str, str]:
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "CLAUDE_PROJECT_DIR": str(project)}
    env |= {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    for role in ("AUTHOR", "COMMITTER"):
        env |= {f"GIT_{role}_{key}": value for key, value in IDENTITY.items()}
    return env


def _git(project: Path, env: dict[str, str], *args: str) -> None:
    subprocess.run(  # noqa: S603 - a fixed argv, no shell
        ["git", "-C", str(project), *args],  # noqa: S607
        env=env,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A repo on branch `work` whose `origin/main` ref holds the applied files and two SQL files."""
    root = tmp_path / "project"
    for name in (APPLIED_DDL, f"{DDL}/lockfile.json", APPLIED_REVISION, OTHER_SQL, NEAR_MISS_SQL):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text("applied\n", encoding="utf-8")
    env = _env(root, tmp_path)
    _git(root, env, "init", "-q", "-b", "work")
    _git(root, env, "add", "-A")
    _git(root, env, "commit", "-q", "-m", "the applied files")
    _git(root, env, "update-ref", "refs/remotes/origin/main", "HEAD")
    return root


def _run(
    project: Path, tool_input: dict[str, str] | None = None, stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    payload = stdin if stdin is not None else json.dumps({"tool_input": tool_input})
    return subprocess.run(  # noqa: S603 - the repo's own hook, a fixed argv
        [sys.executable, str(HOOK)],
        input=payload,
        env=_env(project, project.parent),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _edit(path: Path | str) -> dict[str, str]:
    return {"file_path": str(path), "old_string": "applied", "new_string": "changed"}


def test_hook_blocks_an_edit_of_an_applied_questdb_ddl_file_and_names_c_5_4(project: Path) -> None:
    done = _run(project, _edit(project / APPLIED_DDL))
    assert done.returncode == 2
    assert "C-5.4" in done.stderr and f"{DDL}/lockfile.json" in done.stderr


def test_hook_passes_a_new_questdb_ddl_file(project: Path) -> None:
    done = _run(project, _edit(project / DDL / "0002_new.sql"))
    assert (done.returncode, done.stderr) == (0, "")


def test_hook_passes_an_edit_of_the_lock_file(project: Path) -> None:
    done = _run(project, _edit(project / DDL / "lockfile.json"))
    assert (done.returncode, done.stderr) == (0, "")


@pytest.mark.parametrize("sql", [OTHER_SQL, NEAR_MISS_SQL], ids=["elsewhere", "beside-the-ddl"])
def test_hook_passes_an_edit_of_a_sql_file_outside_the_ddl_directory(
    project: Path, sql: str
) -> None:
    done = _run(project, _edit(project / sql))
    assert (done.returncode, done.stderr) == (0, "")


def test_hook_blocks_an_edit_of_an_applied_alembic_revision(project: Path) -> None:
    done = _run(project, _edit(project / APPLIED_REVISION))
    assert done.returncode == 2
    assert "C-5.4" in done.stderr and "alembic revision" in done.stderr


def test_hook_passes_a_new_alembic_revision(project: Path) -> None:
    done = _run(project, _edit(project / REVISIONS / "0002_second.py"))
    assert (done.returncode, done.stderr) == (0, "")


def test_hook_recognises_a_questdb_path_outside_the_project_directory(
    project: Path, tmp_path: Path
) -> None:
    done = _run(project, _edit(tmp_path / "another-clone" / APPLIED_DDL))
    assert done.returncode == 2 and "C-5.4" in done.stderr


@pytest.mark.parametrize("applied", [APPLIED_DDL, APPLIED_REVISION], ids=["questdb", "alembic"])
def test_hook_recognises_a_path_under_a_worktree_of_the_project(
    project: Path, applied: str
) -> None:
    done = _run(project, _edit(project / ".claude" / "worktrees" / "feature" / applied))
    assert done.returncode == 2 and "C-5.4" in done.stderr


@pytest.mark.parametrize("applied", [APPLIED_DDL, APPLIED_REVISION], ids=["questdb", "alembic"])
def test_hook_normalises_the_path_before_matching(project: Path, applied: str) -> None:
    """The directory rules read the path after its separators and its `.` and `..` segments are
    resolved as text: a file is the same file however its path is spelled, in the project or in a
    worktree of it. A new file spelled the long way round still passes."""
    folder, name = applied.rsplit("/", 1)
    parent = folder.rsplit("/", 1)[1]
    for base in (str(project), f"{project}/.claude/worktrees/feature"):
        for spelled in (
            f"{base}/./{applied}",
            f"{base}//{folder}//{name}",
            f"{base}/{folder}/../{parent}/{name}",
            f"{base}/elsewhere/../{applied}",
        ):
            done = _run(project, _edit(spelled))
            assert done.returncode == 2 and "C-5.4" in done.stderr, spelled
    new = f"{project}/{folder}/../{parent}/9999_new{Path(name).suffix}"
    assert _run(project, _edit(new)).returncode == 0, new


@pytest.mark.parametrize("stdin", ["", "not json"], ids=["empty", "not-json"])
def test_hook_passes_unreadable_input(project: Path, stdin: str) -> None:
    done = _run(project, stdin=stdin)
    assert (done.returncode, done.stderr) == (0, "")


def test_hook_still_blocks_a_statechart_import_outside_the_package(project: Path) -> None:
    edit = {
        "file_path": str(project / "services/api/candleviewer/oms/orders.py"),
        "content": IMPORT,
    }
    done = _run(project, edit)
    assert done.returncode == 2 and "xstate_statemachine" in done.stderr


@pytest.mark.parametrize(
    ("module", "exit_code"),
    [(f"{STATECHART}/factory.py", 0), ("services/api/candleviewer/oms/orders.py", 2)],
    ids=["in-the-package", "outside-it"],
)
def test_hook_reads_the_statechart_rule_through_a_worktree_path(
    project: Path, module: str, exit_code: int
) -> None:
    path = project / ".claude" / "worktrees" / "feature" / module
    assert _run(project, {"file_path": str(path), "content": IMPORT}).returncode == exit_code
