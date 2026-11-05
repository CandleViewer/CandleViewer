"""The backup roles' grants revision (ADR-0041 section 1, #3319 B1a; 21 Sec.1.1 "Backup roles"):
offline render, the NOLOGIN guard before any grant, the exact grant and revoke sets, no role,
password or runtime-role text, the lock bracket, the single head, the lockfile, the plan row and
the bootstrap that creates the roles.

The revision's id and parent are read from its file, so the provisional number and the parent it
is re-parented onto at merge (C-5.3) change nothing here. Real Postgres: the `migrations` CI job's
round trip and `tests/integration/storage/test_backup_roles_pg.py` (C-5.5)."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from functools import cache
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_REPO = _ROOT.parents[1]
_DOC = _REPO / "docs" / "plan" / "21-database-schema.md"
_BOOTSTRAP = _REPO / "infra" / "scripts" / "pg_bootstrap.sql"
_VERSIONS = _ROOT / "candleviewer" / "migrations" / "versions"
_LOCKFILE = _ROOT / "candleviewer" / "migrations" / "lockfile.json"
_LOCK_ON, _LOCK_OFF = (
    "SET LOCAL lock_timeout = '5s';",
    "SET LOCAL lock_timeout = DEFAULT;",
)
_DDL = re.compile(r"\b(?:CREATE|ALTER|DROP|DO|COMMENT|REVOKE|LOCK|GRANT)\b")
_GUARD = "IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_backup') THEN"
_OWNER_GUARD = "IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_owner') THEN"
_DEFAULTS = "ALTER DEFAULT PRIVILEGES FOR ROLE cv_owner IN SCHEMA public"


def _ids(path: Path) -> tuple[str, str]:
    """The `revision` and `down_revision` string literals a version file assigns."""
    found: dict[str, str] = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                found[node.target.id] = node.value.value
    return found["revision"], found["down_revision"]


[_FILE] = sorted(_VERSIONS.glob("*_backup_role_grants.py"))
_REV, _PREV = _ids(_FILE)


def _alembic(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#3319)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ}, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return r.stdout


def _norm(sql: str) -> str:
    """Drop `--` comments and collapse whitespace."""
    return " ".join(re.sub(r"--[^\n]*", "", sql).split())


@cache
def _up() -> str:
    return _norm(_alembic("upgrade", f"{_PREV}:{_REV}", "--sql"))


@cache
def _down() -> str:
    return _norm(_alembic("downgrade", f"{_REV}:{_PREV}", "--sql"))


def _statements(sql: str) -> list[str]:
    """The grant statements the DO blocks execute, in order, quotes stripped, the default
    privileges' prefix written `<defaults>`."""
    found = re.findall(r"EXECUTE (format\('[^']*'|'[^']*')", sql)
    return [s.strip("'").replace(_DEFAULTS, "<defaults>") for s in found]


def _in_order(sql: str, steps: list[str]) -> bool:
    missing = [step for step in steps if step not in sql]
    assert not missing, f"not in the rendered SQL: {missing}"
    positions = [sql.index(step) for step in steps]
    return positions == sorted(positions)


def test_the_upgrade_refuses_a_cv_restore_that_can_log_in_before_any_grant() -> None:
    refuse = (
        "IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_restore' AND rolcanlogin) THEN "
        "RAISE EXCEPTION '0066_backup_role_grants: cv_restore can log in;"
    )
    assert _in_order(_up(), [_LOCK_ON, refuse, _GUARD, "GRANT", _LOCK_OFF])
    assert _up().count("RAISE EXCEPTION") == 1 and "RAISE" not in _down()


def test_the_upgrade_grants_cv_backup_read_only_and_the_future_tables() -> None:
    assert _statements(_up()) == [
        "format('GRANT CONNECT ON DATABASE %I TO cv_backup",
        "GRANT USAGE ON SCHEMA public TO cv_backup",
        "GRANT SELECT ON ALL TABLES IN SCHEMA public TO cv_backup",
        "GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO cv_backup",
        "<defaults> GRANT SELECT ON TABLES TO cv_backup",
        "<defaults> GRANT SELECT ON SEQUENCES TO cv_backup",
    ]
    assert "format('GRANT CONNECT ON DATABASE %I TO cv_backup', current_database())" in _up()
    assert _in_order(_up(), [_GUARD, "GRANT CONNECT", _OWNER_GUARD, _DEFAULTS])


def test_the_downgrade_revokes_exactly_what_the_upgrade_granted_defaults_first() -> None:
    assert _statements(_down()) == [
        "<defaults> REVOKE SELECT ON SEQUENCES FROM cv_backup",
        "<defaults> REVOKE SELECT ON TABLES FROM cv_backup",
        "REVOKE SELECT ON ALL SEQUENCES IN SCHEMA public FROM cv_backup",
        "REVOKE SELECT ON ALL TABLES IN SCHEMA public FROM cv_backup",
        "REVOKE USAGE ON SCHEMA public FROM cv_backup",
        "format('REVOKE CONNECT ON DATABASE %I FROM cv_backup",
    ]
    mirrored = {
        re.sub(r"(^|[ '])GRANT ", r"\1REVOKE ", s).replace(" TO ", " FROM ")
        for s in _statements(_up())
    }
    assert mirrored == set(_statements(_down()))
    assert _in_order(_down(), [_LOCK_ON, _GUARD, _OWNER_GUARD, _LOCK_OFF])


@pytest.mark.parametrize("render", [_up, _down], ids=["upgrade", "downgrade"])
def test_no_role_password_or_runtime_role_and_nothing_outside_the_lock_bracket(
    render: object,
) -> None:
    """Passwords and roles are the bootstrap's (ADR-0041); a statement here touches `cv_backup`
    only, never the runtime role, so the guarded-privileges tripwire and its pin are unchanged.
    """
    assert callable(render)
    sql = str(render())
    body = sql.split(_LOCK_ON, 1)[1].split(_LOCK_OFF, 1)[0]  # not alembic's version UPDATE
    absent = [
        "PASSWORD", "CREATE ROLE", "ALTER ROLE", "DROP ROLE", "cv_app", "cv_ro ", "GRANT cv_",
        "WITH GRANT OPTION", "INSERT", "UPDATE", "DELETE", "TRUNCATE",
    ]  # fmt: skip
    assert [text for text in absent if text in body] == []
    assert sql.count("SET LOCAL lock_timeout") == 2
    assert not _DDL.search(sql.split(_LOCK_ON, 1)[0])
    assert not _DDL.search(sql.split(_LOCK_OFF, 1)[1])


def test_the_bootstrap_creates_both_roles_fail_closed_and_cv_restore_nologin() -> None:
    """The roles are created by the superuser bootstrap, not the revision: `cv_backup` logs in
    only with a supplied password, `cv_restore` never at creation, and it is a member of
    `cv_owner`."""
    text = _BOOTSTRAP.read_text(encoding="utf-8")
    assert _in_order(
        text,
        [
            "CREATE ROLE cv_owner LOGIN",
            "\\if :{?backup_pw}",
            "SELECT format('CREATE ROLE cv_backup LOGIN PASSWORD %L', :'backup_pw')",
            "SELECT 'CREATE ROLE cv_backup NOLOGIN'",
            "\\if :{?restore_pw}",
            "SELECT format('CREATE ROLE cv_restore NOLOGIN PASSWORD %L', :'restore_pw')",
            "SELECT 'CREATE ROLE cv_restore NOLOGIN'",
            "GRANT cv_owner TO cv_restore;",
            "\\connect candleviewer",
        ],
    )
    creates = re.findall(r"CREATE ROLE cv_(?:backup|restore) \w+", text)
    assert (
        creates
        == ["CREATE ROLE cv_backup LOGIN", "CREATE ROLE cv_backup NOLOGIN"]
        + ["CREATE ROLE cv_restore NOLOGIN"] * 2
    )
    assert "ALTER ROLE cv_restore" not in text and "cv_backup TO" not in text


def test_the_revision_sits_on_the_single_head() -> None:
    """One revision per PR (C-5.3): it follows the newest revision below its own number, the
    parent it names, and `alembic heads` is one revision: it, or a later one that descends from
    it, so a revision landing after it changes nothing here."""
    assert _FILE.stem == _REV and re.fullmatch(r"\d{4}_backup_role_grants", _REV)
    below = sorted(p.stem for p in _VERSIONS.glob("[0-9][0-9][0-9][0-9]_*.py") if p.stem < _REV)
    assert _PREV == below[-1]
    heads = [line for line in _alembic("heads").splitlines() if line.strip()]
    assert len(heads) == 1 and heads[0].endswith(" (head)")
    head = heads[0].removesuffix(" (head)")
    assert f"-> {_REV}" in _alembic("history", "-r", f"{_PREV}:{head}")


def test_the_lockfile_names_the_revision() -> None:
    entry = json.loads(_LOCKFILE.read_text(encoding="utf-8"))["revisions"][_REV]
    assert entry == {
        "path": str(_FILE.relative_to(_REPO)),
        "sha256": hashlib.sha256(_FILE.read_bytes()).hexdigest(),
        "down_revision": _PREV,
    }


def test_the_plan_names_the_revision_and_the_roles_block_names_both_roles() -> None:
    doc = _DOC.read_text(encoding="utf-8")
    plan = doc.split("### 9.4 ", 1)[1].split("### 9.5 ", 1)[0]
    [row] = [line for line in plan.splitlines() if line.startswith(f"| `{_REV}`")]
    assert "**#3319 B1a**" in row
    roles = doc.split("### 1.1 ", 1)[1].split("### 1.2 ", 1)[0]
    assert "CREATE ROLE cv_backup  LOGIN PASSWORD :'backup_pw';" in roles
    assert "CREATE ROLE cv_restore NOLOGIN PASSWORD :'restore_pw';" in roles
    assert "GRANT cv_owner TO cv_restore;" in roles
    assert f"revision `{_REV}`" in roles
