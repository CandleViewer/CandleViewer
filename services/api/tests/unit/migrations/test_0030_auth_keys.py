"""`0030_auth_keys` (#2152 S2): offline render, plan-doc parity, guards, classification.
Real Postgres: `tests/integration/storage/test_auth_keys_pg.py`."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from functools import cache
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
_REV, _PREV = "0030_auth_keys", "0029_oms_core"
_UP, _DOWN = f"{_PREV}:{_REV}", f"{_REV}:{_PREV}"


def _alembic(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#2152)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ}, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return r.stdout


def _norm(sql: str) -> str:
    """Drop `--` comments and collapse whitespace, so layout never matters."""
    return " ".join(re.sub(r"--[^\n]*", "", sql).split())


@cache
def _up() -> str:
    return _norm(_alembic("upgrade", _UP, "--sql"))


@cache
def _down() -> str:
    return _norm(_alembic("downgrade", _DOWN, "--sql"))


def _in_order(sql: str, steps: list[str]) -> bool:
    positions = [sql.index(step) for step in steps]  # a step that is missing raises ValueError
    return positions == sorted(positions)


def test_upgrade_ddl_is_the_plan_doc_ddl_verbatim() -> None:
    """The first ```sql block of Sec.3.1.5a, to its fence."""
    section = _DOC.read_text(encoding="utf-8").split("#### 3.1.5a ", 1)[1]
    ddl = _norm(section.split("```sql", 1)[1].split("```", 1)[0])
    assert ddl.startswith("CREATE TABLE auth_keys (") and ddl.endswith("set_updated_at();")
    assert ddl in _up()


def test_upgrade_adds_the_guards_then_revokes_delete_under_a_bounded_lock_wait() -> None:
    assert _in_order(
        _up(),
        [
            "SET LOCAL lock_timeout = '5s';",
            "CREATE TRIGGER trg_auth_keys_touch BEFORE UPDATE ON auth_keys",
            "CREATE FUNCTION auth_keys_write_once_check() RETURNS trigger LANGUAGE plpgsql "
            "SET search_path = pg_catalog, pg_temp AS $BODY$",
            "CREATE TRIGGER trg_auth_keys_write_once BEFORE UPDATE ON auth_keys "
            "FOR EACH ROW EXECUTE FUNCTION auth_keys_write_once_check();",
            "ALTER TABLE auth_keys ENABLE ALWAYS TRIGGER trg_auth_keys_write_once;",
            "IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_app') "
            "THEN EXECUTE 'REVOKE DELETE ON auth_keys FROM cv_app';",
            "SET LOCAL lock_timeout = DEFAULT;",
        ],
    )


def test_downgrade_locks_refuses_while_any_row_exists_then_drops_table_and_function() -> None:
    sql = _down()
    assert _in_order(
        sql,
        [
            "SET LOCAL lock_timeout = '5s';",
            "LOCK TABLE auth_keys IN SHARE MODE;",
            "IF EXISTS (SELECT 1 FROM auth_keys) THEN",
            "RAISE EXCEPTION '0030_auth_keys downgrade refused: auth_keys holds rows.",
            "DROP TABLE auth_keys;",
            "DROP FUNCTION auth_keys_write_once_check();",
            "SET LOCAL lock_timeout = DEFAULT;",
        ],
    )
    assert "Fix forward" in sql and "(C-5.2)" in sql


def test_auth_keys_is_on_the_ci_mig_006_list() -> None:
    """Informational: CI-MIG-006 only warns, and only on a quoted name (`op.add_column("auth_keys",
    ...)`), not in raw SQL. Every revision is reviewed by the CODEOWNERS rule on `migrations/`."""
    listed = (_ROOT.parents[1] / "tools" / "ci" / "security-sensitive-tables.txt").read_text()
    assert "auth_keys" in listed.split()
