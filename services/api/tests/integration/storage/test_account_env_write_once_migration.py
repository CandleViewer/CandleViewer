"""Integration: `0040_account_env_write_once` (#2333) on real Postgres 16.

An account's `env` never changes once the row exists, whatever the role, the replication mode, the
account's kind or the column an UPDATE names; an insert takes any environment; the guard is the last
BEFORE UPDATE row trigger on `exchange_accounts`; the downgrade lifts the rule and keeps 0039's
`trg_ea_env_in_use`, and the upgrade restores it, with no row changed either way. `testcontainers`
in CI; the offline render is `tests/unit/migrations/test_0040_account_env_write_once.py`.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import errors as pgerr
from psycopg import sql
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_REV, _PREV = "0040_account_env_write_once", "0039_trade_groups"
_TEMPLATE = "env_write_once_template"

Conn = psycopg.Connection[tuple[Any, ...]]


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT,
        env={**os.environ, "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg")},
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def _conn(dsn: str) -> Conn:
    return psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True)


def _database(dsn: str, name: str) -> str:
    return f"{dsn.rsplit('/', 1)[0]}/{name}"


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    """Head, plus an untouched copy of it that `_fresh` clones per test."""
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        assert _alembic(dsn, "upgrade", "head").returncode == 0
        with _conn(_database(dsn, "postgres")) as c:
            c.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                    sql.Identifier(_TEMPLATE), sql.Identifier(dsn.rsplit("/", 1)[1])
                )
            )
        yield dsn


def _fresh(dsn: str) -> str:
    name = f"ew_{uuid.uuid4().hex[:12]}"
    with _conn(_database(dsn, "postgres")) as c:
        c.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                sql.Identifier(name), sql.Identifier(_TEMPLATE)
            )
        )
    return _database(dsn, name)


def _account(c: Conn, env: str = "demo", parent: str | None = None) -> str:
    """A main account, or a sub-account of `parent` (in the parent's environment)."""
    account = str(uuid.uuid4())
    c.execute(
        "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, parent_account_id, "
        "label) VALUES (%s, 'bybit', %s, %s, %s, %s, %s)",
        (account, env, "main" if parent is None else "sub", str(uuid.uuid4().int % 10**15),
         parent, f"acct {account[:8]}"),
    )  # fmt: skip
    return account


def _env_of(c: Conn, account: str) -> str:
    row = c.execute("SELECT env::text FROM exchange_accounts WHERE id = %s", (account,)).fetchone()
    assert row is not None
    return str(row[0])


@pytest.mark.parametrize(
    ("start", "change"), [("demo", "live"), ("live", "demo"), ("demo", "testnet")]
)
def test_an_account_never_changes_its_environment(pg_dsn: str, start: str, change: str) -> None:
    """C-2.11: a demo key can never become live through its account (#2333), even for an account
    in no group or definition, which `trg_ea_env_in_use` alone left open."""
    with _conn(_fresh(pg_dsn)) as c:
        account = _account(c, start)
        with pytest.raises(pgerr.CheckViolation) as exc:
            c.execute("UPDATE exchange_accounts SET env = %s WHERE id = %s", (change, account))
        assert exc.value.diag.constraint_name == "trg_ea_env_write_once"
        assert _env_of(c, account) == start


def test_a_main_account_with_a_sub_account_never_changes_its_environment(pg_dsn: str) -> None:
    """At 0039 a main account with a sub-account could move and leave the sub-account behind, in
    the other environment (`trg_ea_env_parent` checks the child's row only). Now it is refused."""
    with _conn(_fresh(pg_dsn)) as c:
        main = _account(c)
        child = _account(c, parent=main)
        with pytest.raises(pgerr.CheckViolation) as exc:
            c.execute("UPDATE exchange_accounts SET env = 'live' WHERE id = %s", (main,))
        assert exc.value.diag.constraint_name == "trg_ea_env_write_once"
        assert (_env_of(c, main), _env_of(c, child)) == ("demo", "demo")


def test_a_sub_account_never_changes_its_environment(pg_dsn: str) -> None:
    """A sub-account is refused too: `trg_ea_env_parent` (0017) sorts before the write-once guard
    and refuses first, with SQLSTATE 23514 and no constraint name."""
    with _conn(_fresh(pg_dsn)) as c:
        child = _account(c, parent=_account(c))
        with pytest.raises(pgerr.CheckViolation) as exc:
            c.execute("UPDATE exchange_accounts SET env = 'live' WHERE id = %s", (child,))
        assert exc.value.sqlstate == "23514"
        assert _env_of(c, child) == "demo"


@pytest.mark.parametrize("env", ["live", "demo", "testnet"])
def test_an_insert_takes_any_environment_and_other_columns_still_change(
    pg_dsn: str, env: str
) -> None:
    with _conn(_fresh(pg_dsn)) as c:
        account = _account(c, env)
        c.execute("UPDATE exchange_accounts SET env = env, label = 'renamed' WHERE id = %s",
                  (account,))  # fmt: skip
        c.execute("UPDATE exchange_accounts SET is_enabled = false WHERE id = %s", (account,))
        row = c.execute(
            "SELECT env::text, label, is_enabled FROM exchange_accounts WHERE id = %s", (account,)
        ).fetchone()
        assert row == (env, "renamed", False)


def test_the_guard_is_the_last_before_update_row_trigger(pg_dsn: str) -> None:
    """Same-event BEFORE triggers fire in name order, so one sorting after the guard could rewrite
    NEW after the check (0024's precedent). The guard is whole-row, `ENABLE ALWAYS`, and last.
    tgtype 19 = ROW | BEFORE | UPDATE."""
    with _conn(_fresh(pg_dsn)) as c:
        order = c.execute(
            "SELECT tgname, tgenabled::text, pg_get_triggerdef(oid) FROM pg_trigger "
            "WHERE tgrelid = 'exchange_accounts'::regclass AND NOT tgisinternal "
            'AND tgtype & 19 = 19 ORDER BY tgname COLLATE "C"'
        ).fetchall()
    assert [row[0] for row in order] == [
        "trg_ea_env_in_use", "trg_ea_env_parent", "trg_ea_env_write_once",
    ]  # fmt: skip
    assert order[-1][1:] == (
        "A",
        "CREATE TRIGGER trg_ea_env_write_once BEFORE UPDATE ON public.exchange_accounts "
        "FOR EACH ROW EXECUTE FUNCTION ea_env_write_once()",
    )


def test_env_rewritten_behind_another_column_is_refused(pg_dsn: str) -> None:
    """The guard reads every UPDATE, not only one naming `env`: an earlier-sorting trigger that
    rewrites NEW.env on a label change still meets it (a `BEFORE UPDATE OF env` guard would not
    fire). The rogue trigger exists only in this test's own database."""
    with _conn(_fresh(pg_dsn)) as c:
        c.execute(
            "CREATE FUNCTION test_flip_env() RETURNS trigger LANGUAGE plpgsql AS "
            "$F$ BEGIN NEW.env := 'live'; RETURN NEW; END $F$"
        )
        c.execute(
            "CREATE TRIGGER trg_ea_aa_flip BEFORE UPDATE ON exchange_accounts "
            "FOR EACH ROW EXECUTE FUNCTION test_flip_env()"
        )
        account = _account(c)
        with pytest.raises(pgerr.CheckViolation) as exc:
            c.execute("UPDATE exchange_accounts SET label = 'renamed' WHERE id = %s", (account,))
        assert exc.value.diag.constraint_name == "trg_ea_env_write_once"
        assert _env_of(c, account) == "demo"


def test_the_rule_holds_under_the_replica_role(pg_dsn: str) -> None:
    """`ENABLE ALWAYS`: a session that replays changes cannot move an account either."""
    with _conn(_fresh(pg_dsn)) as c, c.transaction():
        account = _account(c)
        c.execute("SET LOCAL session_replication_role = replica")
        with pytest.raises(pgerr.CheckViolation) as exc:
            c.execute("UPDATE exchange_accounts SET env = 'live' WHERE id = %s", (account,))
        assert exc.value.diag.constraint_name == "trg_ea_env_write_once"
        raise psycopg.Rollback


def _guards(c: Conn) -> list[tuple[str, str]]:
    """The environment triggers on `exchange_accounts`, by name, with `tgenabled`."""
    return [
        (str(name), str(enabled))
        for name, enabled in c.execute(
            "SELECT tgname, tgenabled::text FROM pg_trigger "
            "WHERE tgrelid = 'exchange_accounts'::regclass AND tgname LIKE 'trg_ea_env_%' "
            "ORDER BY tgname"
        ).fetchall()
    ]


def test_the_round_trip_lifts_and_restores_the_rule(pg_dsn: str) -> None:
    """C-5.5: the downgrade drops only the trigger and its function, so 0039's `trg_ea_env_in_use`
    and 0017's `trg_ea_env_parent` stay; the upgrade brings them back; no row changes either way."""
    dsn = _fresh(pg_dsn)
    with _conn(dsn) as c:
        account = _account(c)
    downgraded = _alembic(dsn, "downgrade", _PREV)
    assert downgraded.returncode == 0, downgraded.stderr
    with _conn(dsn) as c:
        assert _guards(c) == [("trg_ea_env_in_use", "A"), ("trg_ea_env_parent", "O")]
        assert c.execute("SELECT to_regprocedure('ea_env_write_once()')").fetchone() == (None,)
        assert _env_of(c, account) == "demo"
    upgraded = _alembic(dsn, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr
    with _conn(dsn) as c:
        assert _guards(c) == [
            ("trg_ea_env_in_use", "A"), ("trg_ea_env_parent", "O"), ("trg_ea_env_write_once", "A"),
        ]  # fmt: skip
        assert _env_of(c, account) == "demo"
        with pytest.raises(pgerr.CheckViolation) as exc:
            c.execute("UPDATE exchange_accounts SET env = 'live' WHERE id = %s", (account,))
        assert exc.value.diag.constraint_name == "trg_ea_env_write_once"
