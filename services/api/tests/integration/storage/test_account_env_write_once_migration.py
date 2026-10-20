"""Integration: `0040_account_env_write_once` (#2333) on real Postgres 16.

An account's `env` never changes once the row exists, whatever the role or the replication mode;
an insert takes any environment; the downgrade lifts the rule and the upgrade restores it.
`testcontainers` in CI; the offline render is `tests/unit/migrations/test_0039_*`.
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


def _account(c: Conn, env: str = "demo") -> str:
    account = str(uuid.uuid4())
    c.execute(
        "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label) "
        "VALUES (%s, 'bybit', %s, 'main', %s, %s)",
        (account, env, str(uuid.uuid4().int % 10**15), f"acct {account[:8]}"),
    )
    return account


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
        assert c.execute("SELECT env::text FROM exchange_accounts WHERE id = %s",
                         (account,)).fetchone() == (start,)  # fmt: skip


@pytest.mark.parametrize("env", ["live", "demo", "testnet"])
def test_an_insert_takes_any_environment_and_other_columns_still_change(
    pg_dsn: str, env: str
) -> None:
    with _conn(_fresh(pg_dsn)) as c:
        account = _account(c, env)
        c.execute("UPDATE exchange_accounts SET env = env, label = 'renamed' WHERE id = %s",
                  (account,))  # fmt: skip
        assert c.execute("SELECT env::text, label FROM exchange_accounts WHERE id = %s",
                         (account,)).fetchone() == (env, "renamed")  # fmt: skip


def test_the_rule_holds_under_the_replica_role(pg_dsn: str) -> None:
    """`ENABLE ALWAYS`: a session that replays changes cannot move an account either."""
    with _conn(_fresh(pg_dsn)) as c, c.transaction():
        account = _account(c)
        c.execute("SET LOCAL session_replication_role = replica")
        with pytest.raises(pgerr.CheckViolation) as exc:
            c.execute("UPDATE exchange_accounts SET env = 'live' WHERE id = %s", (account,))
        assert exc.value.diag.constraint_name == "trg_ea_env_write_once"
        raise psycopg.Rollback


def test_the_round_trip_lifts_and_restores_the_rule(pg_dsn: str) -> None:
    """C-5.5: the downgrade drops only the trigger and its function; the upgrade brings them back,
    and the accounts that existed keep their environment."""
    dsn = _fresh(pg_dsn)
    with _conn(dsn) as c:
        account = _account(c)
    assert _alembic(dsn, "downgrade", _PREV).returncode == 0
    with _conn(dsn) as c:
        assert c.execute(
            "SELECT count(*) FROM pg_trigger WHERE tgname = 'trg_ea_env_write_once'"
        ).fetchone() == (0,)
        assert c.execute("SELECT to_regprocedure('ea_env_write_once()')").fetchone() == (None,)
    upgraded = _alembic(dsn, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr
    with _conn(dsn) as c:
        assert c.execute(
            "SELECT tgenabled::text FROM pg_trigger WHERE tgname = 'trg_ea_env_write_once'"
        ).fetchone() == ("A",)
        with pytest.raises(pgerr.CheckViolation):
            c.execute("UPDATE exchange_accounts SET env = 'live' WHERE id = %s", (account,))
