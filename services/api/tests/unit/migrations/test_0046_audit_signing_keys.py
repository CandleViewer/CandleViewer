"""`0046_audit_signing_keys` (#889 S4): offline render, plan-doc parity, guards, classification.
Real Postgres: `tests/integration/storage/test_audit_signing_keys_pg.py`."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from functools import cache
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
_REV = "0046_audit_signing_keys"
_FILE = _ROOT / "candleviewer" / "migrations" / "versions" / f"{_REV}.py"
#: Read from the revision itself, so a re-parent edits only that file and its lockfile entry.
_PREV: str = re.findall(r'^down_revision.*"(\w+)"$', _FILE.read_text(encoding="utf-8"), re.M)[0]
_UP, _DOWN = f"{_PREV}:{_REV}", f"{_REV}:{_PREV}"


def _alembic(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#889)
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
    """The first ```sql block of Sec.3.1.5b, to its fence: the table, its index and comments."""
    section = _DOC.read_text(encoding="utf-8").split("#### 3.1.5b ", 1)[1]
    ddl = _norm(section.split("```sql", 1)[1].split("```", 1)[0])
    assert ddl.startswith("CREATE TABLE audit_signing_keys (")
    assert ddl.endswith("IS 'SECRET: the row''s DEK wrapped under the KEK of (env, kek_version)';")
    assert ddl in _up()


def test_upgrade_adds_the_guard_then_revokes_delete_under_a_bounded_lock_wait() -> None:
    assert _in_order(
        _up(),
        [
            "SET LOCAL lock_timeout = '5s';",
            "CREATE TABLE audit_signing_keys (",
            "CREATE UNIQUE INDEX ux_ask_active ON audit_signing_keys (env) "
            "WHERE status = 'active';",
            "CREATE FUNCTION audit_signing_keys_write_once_check() RETURNS trigger "
            "LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $BODY$",
            "CREATE TRIGGER trg_audit_signing_keys_write_once BEFORE UPDATE ON audit_signing_keys "
            "FOR EACH ROW EXECUTE FUNCTION audit_signing_keys_write_once_check();",
            "ALTER TABLE audit_signing_keys ENABLE ALWAYS TRIGGER "
            "trg_audit_signing_keys_write_once;",
            "IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_app') "
            "THEN EXECUTE 'REVOKE DELETE ON audit_signing_keys FROM cv_app';",
            "SET LOCAL lock_timeout = DEFAULT;",
        ],
    )


def test_downgrade_locks_refuses_while_any_row_exists_then_drops_table_and_function() -> None:
    sql = _down()
    assert _in_order(
        sql,
        [
            "SET LOCAL lock_timeout = '5s';",
            "LOCK TABLE audit_signing_keys IN SHARE MODE;",
            "IF EXISTS (SELECT 1 FROM audit_signing_keys) THEN",
            "RAISE EXCEPTION '0046_audit_signing_keys downgrade refused: "
            "audit_signing_keys holds rows.",
            "DROP TABLE audit_signing_keys;",
            "DROP FUNCTION audit_signing_keys_write_once_check();",
            "SET LOCAL lock_timeout = DEFAULT;",
        ],
    )
    assert "Fix forward" in sql and "(C-5.2)" in sql


def test_the_table_is_listed_for_ci_mig_006() -> None:
    """CI-MIG-006 warns the reviewer of a migration that names the table (#3935)."""
    listed = (_ROOT.parents[1] / "tools" / "ci" / "security-sensitive-tables.txt").read_text()
    entries = {s for line in listed.splitlines() if (s := line.strip()) and not s.startswith("#")}
    assert "audit_signing_keys" in entries  # as migration_lint.py reads the list
