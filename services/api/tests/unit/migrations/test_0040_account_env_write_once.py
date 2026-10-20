"""`0040_account_env_write_once` (#2333): offline render, plan-doc parity, the trigger's shape, the
downgrade, and the model guard (the API never patches `env`).
Real Postgres: `tests/integration/storage/test_account_env_write_once_migration.py`."""

from __future__ import annotations

import dataclasses
import os
import re
import subprocess
import sys
from functools import cache
from pathlib import Path

from candleviewer.storage.repositories.accounts import ExchangeAccountPatch

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
_REV, _PREV = "0040_account_env_write_once", "0039_trade_groups"
_UP, _DOWN = f"{_PREV}:{_REV}", f"{_REV}:{_PREV}"


def _alembic(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#2333)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ}, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return r.stdout


def _norm(sql: str) -> str:
    flat = " ".join(re.sub(r"--[^\n]*", "", sql).split())
    return flat.replace("( ", "(").replace(" )", ")")


@cache
def _up() -> str:
    return _norm(_alembic("upgrade", _UP, "--sql"))


@cache
def _down() -> str:
    return _norm(_alembic("downgrade", _DOWN, "--sql"))


def _doc_block() -> str:
    """Sec.3.2.1's third ```sql block (the first two are 0017's and 0031's)."""
    section = _DOC.read_text(encoding="utf-8").split("#### 3.2.1 ", 1)[1].split("#### 3.2.2 ")[0]
    return section.split("```sql")[3].split("```", 1)[0]


def test_revision_chains_onto_0039() -> None:
    assert f"{_PREV} -> {_REV}" in _alembic("history", "-r", _UP)


def test_upgrade_is_the_plan_doc_ddl_verbatim_under_a_bounded_lock_wait() -> None:
    sql = _up()
    block = _norm(_doc_block())
    assert block in sql
    assert sql.index("SET LOCAL lock_timeout = '5s';") < sql.index(block)
    assert sql.index(block) < sql.index("SET LOCAL lock_timeout = DEFAULT;")


def test_any_change_of_env_is_refused_by_a_trigger_the_replica_role_cannot_switch_off() -> None:
    """C-2.11: an account never moves between environments once it exists (#2333)."""
    sql = _up()
    assert "CREATE TRIGGER trg_ea_env_write_once BEFORE UPDATE OF env ON exchange_accounts" in sql
    assert "ALTER TABLE exchange_accounts ENABLE ALWAYS TRIGGER trg_ea_env_write_once;" in sql
    assert "IF NEW.env IS DISTINCT FROM OLD.env THEN" in sql
    assert "RETURN NEW;" in sql and "INSERT" not in sql.split("CREATE TRIGGER", 1)[1]


def test_the_refusal_names_its_trigger_and_never_a_value() -> None:
    sql = _up()
    assert "SET search_path = pg_catalog, pg_temp" in sql and "SECURITY DEFINER" not in sql
    raised = re.findall(r"RAISE EXCEPTION '([^']*)'(.*?);", sql)
    assert raised == [
        (
            "trg_ea_env_write_once: exchange_accounts.env is write-once",
            " USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_ea_env_write_once'",
        )
    ]


def test_the_upgrade_ships_only_the_trigger_and_its_function() -> None:
    sql = _up()
    assert sql.count("CREATE FUNCTION") == 1 and sql.count("CREATE TRIGGER") == 1
    for absent in (
        "CREATE TABLE",
        "DROP ",
        "GRANT ",
        "REVOKE ",
        "IF NOT EXISTS",
        "UPDATE exchange",
    ):
        assert absent not in sql


def test_downgrade_drops_the_trigger_then_its_function_under_a_bounded_lock_wait() -> None:
    sql = _down()
    steps = [
        "SET LOCAL lock_timeout = '5s';",
        "DROP TRIGGER trg_ea_env_write_once ON exchange_accounts;",
        "DROP FUNCTION ea_env_write_once();",
        "SET LOCAL lock_timeout = DEFAULT;",
    ]
    positions = [sql.index(step) for step in steps]
    assert positions == sorted(positions)


def test_the_api_never_patches_env() -> None:
    """The model guard #2333 asks for: an account patch has no `env` to carry."""
    names = {f.name for f in dataclasses.fields(ExchangeAccountPatch)}
    assert "env" not in names and names == {"label", "is_enabled", "position_mode", "margin_mode"}
