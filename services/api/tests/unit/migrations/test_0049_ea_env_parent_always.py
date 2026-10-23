"""`0049_ea_env_parent_always` (#3962): offline render, two-way plan-doc parity, the guard's shape,
and a downgrade that restores 0017's function verbatim. The store's typed error:
`tests/unit/storage/test_accounts_store_sqlalchemy.py`. Real Postgres:
`tests/integration/storage/test_ea_env_parent_always_migration.py`."""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from functools import cache
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
_VERSIONS = _ROOT / "candleviewer" / "migrations" / "versions"
_REV, _PREV = "0049_ea_env_parent_always", "0048_account_default_binding"
_UP, _DOWN = f"{_PREV}:{_REV}", f"{_REV}:{_PREV}"
_LOCK, _RESET = "SET LOCAL lock_timeout = '5s';", "SET LOCAL lock_timeout = DEFAULT;"
#: Alembic's version stamp, each way.
_STAMP_UP = (
    "UPDATE alembic_version SET version_num='0049_ea_env_parent_always' "
    "WHERE alembic_version.version_num = '0048_account_default_binding'"
)
_STAMP_DOWN = (
    "UPDATE alembic_version SET version_num='0048_account_default_binding' "
    "WHERE alembic_version.version_num = '0049_ea_env_parent_always'"
)


def _alembic(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#3962)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ}, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return r.stdout


def _norm(sql: str) -> str:
    flat = " ".join(re.sub(r"--[^\n]*", "", sql).split())
    return flat.replace("( ", "(").replace(" )", ")")


def _statements(sql: str) -> list[str]:
    """`sql` cut at every `;`, blanks dropped (alembic ends each `op.execute` with one more `;`).
    A function body is cut too, the same way on both sides of a comparison."""
    return [part.strip() for part in sql.split(";") if part.strip()]


@cache
def _up() -> str:
    return _norm(_alembic("upgrade", _UP, "--sql"))


@cache
def _down() -> str:
    return _norm(_alembic("downgrade", _DOWN, "--sql"))


def _doc_block() -> str:
    """Sec.3.2.1's fifth ```sql block (the first four are 0017's, 0031's, 0041's and 0048's)."""
    section = _DOC.read_text(encoding="utf-8").split("#### 3.2.1 ", 1)[1].split("#### 3.2.2 ")[0]
    return section.split("```sql")[5].split("```", 1)[0]


def _function_of_0017() -> str:
    """0017's `ea_env_parent_check()`, as its revision created it."""
    spec = importlib.util.spec_from_file_location(
        "rev_0017", _VERSIONS / "0017_exchange_accounts_api_keys.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sql: str = module._TYPES_AND_ACCOUNTS
    start = sql.index("CREATE FUNCTION ea_env_parent_check()")
    return sql[start : sql.index("END $$;", start) + len("END $$;")]


def test_revision_chains_onto_0048() -> None:
    assert f"{_PREV} -> {_REV}" in _alembic("history", "-r", _UP)


def test_upgrade_is_exactly_the_plan_doc_ddl_under_a_bounded_lock_wait() -> None:
    """Two-way parity: inside the bounded lock wait the upgrade runs the doc's block and nothing
    else, and the block holds nothing the upgrade does not run; outside it, only the transaction
    and alembic's version stamp."""
    before, rest = _up().split(_LOCK, 1)
    ddl, after = rest.split(_RESET, 1)
    assert _statements(ddl) == _statements(_norm(_doc_block()))
    assert _statements(before) == ["BEGIN"]
    assert _statements(after) == [_STAMP_UP, "COMMIT"]


def test_the_parent_guard_fires_whatever_the_replication_role() -> None:
    """C-2.11 (SEC-2333-04): a session under `session_replication_role = replica` meets the guard
    too, as it meets 0024's, 0039's and 0041's."""
    assert "ALTER TABLE exchange_accounts ENABLE ALWAYS TRIGGER trg_ea_env_parent;" in _up()


def test_the_function_is_replaced_in_place_with_the_same_rule_and_the_guards_shape() -> None:
    """The trigger keeps pointing at the function, so it is replaced in place: `search_path`
    pinned, the table schema-qualified, the environments compared as text, a sub-account whose
    parent's environment differs, or whose parent does not exist, refused as before."""
    sql = _up()
    assert (
        "CREATE OR REPLACE FUNCTION ea_env_parent_check() RETURNS trigger LANGUAGE plpgsql "
        "SET search_path = pg_catalog, pg_temp AS $BODY$"
    ) in sql
    assert "SECURITY DEFINER" not in sql and "CREATE TRIGGER" not in sql
    assert "IF NEW.parent_account_id IS NOT NULL THEN" in sql
    assert (
        "SELECT p.env::text INTO parent_env FROM public.exchange_accounts p "
        "WHERE p.id = NEW.parent_account_id;"
    ) in sql
    assert "IF parent_env IS DISTINCT FROM NEW.env::text THEN" in sql


def test_the_refusal_names_its_trigger_and_never_a_value() -> None:
    raised = re.findall(r"RAISE EXCEPTION '([^']*)'(.*?);", _up())
    assert raised == [
        (
            "trg_ea_env_parent: a sub-account is outside its parent account environment",
            " USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_ea_env_parent'",
        )
    ]


def test_downgrade_restores_0017s_function_verbatim_and_the_plain_enable() -> None:
    """Rollback only: the function as 0017 created it (no pinned path, the values in its message),
    the trigger back to a plain `ENABLE`, under a bounded lock wait, and nothing else."""
    original = _norm(_function_of_0017()).replace(
        "CREATE FUNCTION ea_env_parent_check()", "CREATE OR REPLACE FUNCTION ea_env_parent_check()"
    )
    assert _statements(_down()) == [
        "BEGIN",
        _LOCK.rstrip(";"),
        *_statements(original),
        "ALTER TABLE exchange_accounts ENABLE TRIGGER trg_ea_env_parent",
        _RESET.rstrip(";"),
        _STAMP_DOWN,
        "COMMIT",
    ]
