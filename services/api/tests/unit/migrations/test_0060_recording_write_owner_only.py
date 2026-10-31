"""`0060_recording_write_owner_only` (E16-S01 #484, G-04): the offline render of both directions.

The upgrade revokes the Manager's `recording:write` and nothing else; the downgrade restores that
one grant. The revision's id and parent are read from its file, so a re-parent at merge (C-5.3)
changes nothing here. Real Postgres is CI's: the `migrations` job's round trip (C-5.5), and
`tests/integration/auth/test_0001_identity_migration.py`, which holds the seeded `role_permissions`
at head equal to 22's `x-permissions`."""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from functools import cache
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_VERSIONS = _ROOT / "candleviewer" / "migrations" / "versions"
_REVOKE = (
    "DELETE FROM role_permissions WHERE role_id IN (SELECT id FROM roles WHERE name = 'manager') "
    "AND permission_id IN (SELECT id FROM permissions WHERE code = 'recording:write');"
)
_GRANT = (
    "INSERT INTO role_permissions (role_id, permission_id) SELECT r.id, p.id FROM roles r, "
    "permissions p WHERE r.name = 'manager' AND p.code = 'recording:write' ON CONFLICT DO NOTHING;"
)
_DDL = re.compile(r"\b(?:CREATE|ALTER|DROP|TRUNCATE|GRANT|REVOKE|COMMENT)\b")


def _ids(path: Path) -> tuple[str, str]:
    """The `revision` and `down_revision` string literals a version file assigns."""
    found: dict[str, str] = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                found[node.target.id] = node.value.value
    return found["revision"], found["down_revision"]


[_FILE] = sorted(_VERSIONS.glob("*_recording_write_owner_only.py"))
_REV, _PREV = _ids(_FILE)


def _alembic(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#484)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ}, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return r.stdout


def _own(sql: str) -> str:
    """The revision's own statements, whitespace collapsed: the render without its `--` comments
    and alembic's `alembic_version` bookkeeping."""
    kept = [s for s in sql.split(";") if "alembic_version" not in s]
    return " ".join(re.sub(r"--[^\n]*", "", ";".join(kept)).split())


@cache
def _up() -> str:
    return _own(_alembic("upgrade", f"{_PREV}:{_REV}", "--sql"))


@cache
def _down() -> str:
    return _own(_alembic("downgrade", f"{_REV}:{_PREV}", "--sql"))


def test_upgrade_revokes_recording_write_from_the_manager_and_nothing_else() -> None:
    assert _up().count("DELETE FROM") == 1
    assert _REVOKE in _up()
    assert "INSERT INTO" not in _up() and "UPDATE " not in _up()


def test_downgrade_restores_the_managers_grant_and_deletes_nothing() -> None:
    assert _down().count("INSERT INTO") == 1
    assert _GRANT in _down()
    assert "DELETE FROM" not in _down() and "UPDATE " not in _down()


def test_neither_direction_touches_the_permission_row_another_role_or_the_schema() -> None:
    """The vocabulary keeps `recording:write` (the Owner holds it through 0001's every-permission
    grant), the Owner's and the Viewer's rows are never named, and the revision is data only."""
    for sql in (_up(), _down()):
        assert "DELETE FROM permissions" not in sql
        assert "'owner'" not in sql and "'viewer'" not in sql
        assert _DDL.search(sql) is None, sql
