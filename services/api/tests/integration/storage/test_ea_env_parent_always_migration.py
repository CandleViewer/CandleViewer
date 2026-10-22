"""Integration: `0049_ea_env_parent_always` (#3962) on real Postgres 16.

A sub-account stays in its parent account's environment whatever the session's replication role or
`search_path`, on an INSERT and on an UPDATE that re-parents it; the refusal names the trigger; the
rule itself is 0017's; the downgrade restores 0017's function and the plain `ENABLE`, and the
upgrade brings the guard back, with no row changed either way. `testcontainers` in CI; the offline
render is `tests/unit/migrations/test_0049_ea_env_parent_always.py`.
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
_PREV = "0048_account_default_binding"
_TEMPLATE = "ea_env_parent_template"

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
    name = f"ep_{uuid.uuid4().hex[:12]}"
    with _conn(_database(dsn, "postgres")) as c:
        c.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                sql.Identifier(name), sql.Identifier(_TEMPLATE)
            )
        )
    return _database(dsn, name)


def _insert(c: Conn, env: str, parent: str | None = None) -> str:
    """A main account, or a sub-account of `parent` in `env`."""
    account = str(uuid.uuid4())
    c.execute(
        "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, parent_account_id, "
        "label) VALUES (%s, 'bybit', %s, %s, %s, %s, %s)",
        (account, env, "main" if parent is None else "sub", str(uuid.uuid4().int % 10**15),
         parent, f"acct {account[:8]}"),
    )  # fmt: skip
    return account


def _accounts(c: Conn) -> int:
    row = c.execute("SELECT count(*) FROM exchange_accounts").fetchone()
    assert row is not None
    return int(row[0])


def _state(c: Conn) -> tuple[str, list[str] | None]:
    """The trigger's `tgenabled` and its function's `proconfig`."""
    row = c.execute(
        "SELECT t.tgenabled::text, p.proconfig FROM pg_trigger t "
        "JOIN pg_proc p ON p.oid = t.tgfoid "
        "WHERE t.tgrelid = 'exchange_accounts'::regclass AND t.tgname = 'trg_ea_env_parent'"
    ).fetchone()
    assert row is not None
    return str(row[0]), row[1]


def test_the_guard_fires_always_and_pins_its_search_path(pg_dsn: str) -> None:
    with _conn(_fresh(pg_dsn)) as c:
        assert _state(c) == ("A", ["search_path=pg_catalog, pg_temp"])


@pytest.mark.parametrize("role", ["origin", "replica"])
def test_a_sub_account_outside_its_parents_environment_is_refused_by_name(
    pg_dsn: str, role: str
) -> None:
    """C-2.11 (SEC-2333-04): a replaying session no longer slips a cross-environment sub-account
    past the guard; the refusal names the trigger, never an environment."""
    with _conn(_fresh(pg_dsn)) as c, c.transaction():
        parent = _insert(c, "demo")
        c.execute(sql.SQL("SET LOCAL session_replication_role = {}").format(sql.Literal(role)))
        with pytest.raises(pgerr.CheckViolation) as exc:
            _insert(c, "live", parent=parent)
        assert exc.value.diag.constraint_name == "trg_ea_env_parent"
        message = exc.value.diag.message_primary or ""
        assert message.startswith("trg_ea_env_parent:") and "live" not in message
        raise psycopg.Rollback


@pytest.mark.parametrize("role", ["origin", "replica"])
def test_a_sub_account_in_its_parents_environment_is_kept(pg_dsn: str, role: str) -> None:
    with _conn(_fresh(pg_dsn)) as c, c.transaction():
        parent = _insert(c, "live")
        c.execute(sql.SQL("SET LOCAL session_replication_role = {}").format(sql.Literal(role)))
        child = _insert(c, "live", parent=parent)
        row = c.execute(
            "SELECT env::text, parent_account_id::text FROM exchange_accounts WHERE id = %s",
            (child,),
        ).fetchone()
        assert row == ("live", parent)
        raise psycopg.Rollback


def test_a_sub_account_of_no_existing_parent_is_refused_as_before(pg_dsn: str) -> None:
    """0017's rule: a parent that does not exist has no environment to share."""
    with _conn(_fresh(pg_dsn)) as c:
        before = _accounts(c)
        with pytest.raises(pgerr.CheckViolation) as exc:
            _insert(c, "demo", parent=str(uuid.uuid4()))
        assert exc.value.diag.constraint_name == "trg_ea_env_parent"
        assert _accounts(c) == before


def test_re_parenting_a_sub_account_into_another_environment_is_refused(pg_dsn: str) -> None:
    with _conn(_fresh(pg_dsn)) as c:
        child = _insert(c, "demo", parent=_insert(c, "demo"))
        other = _insert(c, "live")
        with pytest.raises(pgerr.CheckViolation) as exc:
            c.execute(
                "UPDATE exchange_accounts SET parent_account_id = %s WHERE id = %s", (other, child)
            )
        assert exc.value.diag.constraint_name == "trg_ea_env_parent"


def test_a_session_search_path_cannot_redirect_the_parent_read(pg_dsn: str) -> None:
    """The function reads `public.exchange_accounts` on a pinned path: a session schema holding a
    look-alike table, first on its `search_path`, cannot make a live parent read as demo."""
    with _conn(_fresh(pg_dsn)) as c, c.transaction():
        parent = _insert(c, "live")
        c.execute("CREATE SCHEMA shadow")
        c.execute("CREATE TABLE shadow.exchange_accounts (id uuid, env text)")
        c.execute("INSERT INTO shadow.exchange_accounts VALUES (%s, 'demo')", (parent,))
        c.execute("SET LOCAL search_path = shadow, public")
        with pytest.raises(pgerr.CheckViolation) as exc:
            c.execute(
                "INSERT INTO public.exchange_accounts (id, exchange, env, kind, exchange_uid, "
                "parent_account_id, label) VALUES (%s, 'bybit', 'demo', 'sub', '42', %s, 'x')",
                (str(uuid.uuid4()), parent),
            )
        assert exc.value.diag.constraint_name == "trg_ea_env_parent"
        raise psycopg.Rollback


def test_the_round_trip_restores_0017s_guard_then_the_upgrade(pg_dsn: str) -> None:
    """C-5.5: the downgrade sets 0017's function back (no pinned path, no constraint name) and the
    plain `ENABLE`, under which a replaying session skips the guard again: a rollback-only path.
    The upgrade restores the guard. No row changes either way."""
    dsn = _fresh(pg_dsn)
    with _conn(dsn) as c:
        child = _insert(c, "demo", parent=_insert(c, "demo"))
        before = _accounts(c)
    downgraded = _alembic(dsn, "downgrade", _PREV)
    assert downgraded.returncode == 0, downgraded.stderr
    with _conn(dsn) as c:
        assert _state(c) == ("O", None)
        assert _accounts(c) == before
        with pytest.raises(pgerr.CheckViolation) as exc:
            _insert(c, "live", parent=child)
        assert exc.value.diag.constraint_name is None
    upgraded = _alembic(dsn, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr
    with _conn(dsn) as c, c.transaction():
        assert _state(c) == ("A", ["search_path=pg_catalog, pg_temp"])
        assert _accounts(c) == before
        c.execute("SET LOCAL session_replication_role = replica")
        with pytest.raises(pgerr.CheckViolation) as exc:
            _insert(c, "live", parent=child)
        assert exc.value.diag.constraint_name == "trg_ea_env_parent"
        raise psycopg.Rollback
