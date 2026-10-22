"""Integration: `0050_ea_identity_write_once` (#3968, SR-E27-13) on real Postgres 16.

An account's `exchange_uid` and `kind` never change once the row exists, whatever the replication
role or the column an UPDATE names; an insert takes any UID and kind the CHECKs admit; setting a
column to its own value passes; the two write-once guards are the last BEFORE UPDATE row triggers
on `exchange_accounts`; the downgrade lifts the rule and keeps 0041's `env` guard, and the upgrade
restores it, with no row changed either way. `testcontainers` in CI; the offline render is
`tests/unit/migrations/test_0050_ea_identity_write_once.py`.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any, LiteralString

import psycopg
import pytest
from psycopg import errors as pgerr
from psycopg import sql
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_PREV = "0049_ea_env_parent_always"
_TEMPLATE = "ea_identity_template"

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
    name = f"ei_{uuid.uuid4().hex[:12]}"
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


def _identity(c: Conn, account: str) -> tuple[str, str, str | None]:
    """`(exchange_uid, kind, parent_account_id)` of `account`."""
    row = c.execute(
        "SELECT exchange_uid, kind::text, parent_account_id::text FROM exchange_accounts "
        "WHERE id = %s",
        (account,),
    ).fetchone()
    assert row is not None
    return str(row[0]), str(row[1]), row[2]


def _refused(c: Conn, statement: LiteralString, params: tuple[object, ...], column: str) -> None:
    """`statement` meets the guard: SQLSTATE 23514, the trigger as the constraint, the column in
    the message and no value. It runs under a savepoint (`c.transaction()` nests one inside an
    open transaction), so a test that holds a transaction for `SET LOCAL` reads on after it
    instead of meeting a failed transaction (25P02)."""
    with pytest.raises(pgerr.CheckViolation) as exc, c.transaction():
        c.execute(statement, params)
    assert exc.value.sqlstate == "23514"
    assert exc.value.diag.constraint_name == "trg_ea_identity_write_once"
    assert exc.value.diag.message_primary == (
        f"trg_ea_identity_write_once: exchange_accounts.{column} is write-once"
    )


@pytest.mark.parametrize("role", ["origin", "replica", "local"])
def test_an_account_never_changes_its_uid(pg_dsn: str, role: str) -> None:
    """SR-E27-13 (KV-T04): a row never comes to name another Bybit UID, whatever the session's
    replication role (`ENABLE ALWAYS`)."""
    with _conn(_fresh(pg_dsn)) as c, c.transaction():
        account = _account(c)
        before = _identity(c, account)
        c.execute(sql.SQL("SET LOCAL session_replication_role = {}").format(sql.Literal(role)))
        _refused(
            c,
            "UPDATE exchange_accounts SET exchange_uid = %s WHERE id = %s",
            ("424242", account),
            "exchange_uid",
        )
        assert _identity(c, account) == before
        raise psycopg.Rollback


@pytest.mark.parametrize("role", ["origin", "replica", "local"])
def test_a_main_account_never_becomes_a_sub_account(pg_dsn: str, role: str) -> None:
    """`kind` and `parent_account_id` change together under `ea_parent_shape`, so the move a CHECK
    admits is the one the guard must refuse."""
    with _conn(_fresh(pg_dsn)) as c, c.transaction():
        main, other = _account(c), _account(c)
        c.execute(sql.SQL("SET LOCAL session_replication_role = {}").format(sql.Literal(role)))
        _refused(
            c,
            "UPDATE exchange_accounts SET kind = 'sub', parent_account_id = %s WHERE id = %s",
            (other, main),
            "kind",
        )
        assert _identity(c, main)[1:] == ("main", None)
        raise psycopg.Rollback


def test_a_sub_account_never_becomes_a_main_account(pg_dsn: str) -> None:
    with _conn(_fresh(pg_dsn)) as c:
        parent = _account(c)
        child = _account(c, parent=parent)
        _refused(
            c,
            "UPDATE exchange_accounts SET kind = 'main', parent_account_id = NULL WHERE id = %s",
            (child,),
            "kind",
        )
        assert _identity(c, child)[1:] == ("sub", parent)


def test_an_insert_takes_any_uid_and_kind_and_other_columns_still_change(pg_dsn: str) -> None:
    """Writing a column's own value passes (`IS DISTINCT FROM`), and every other column still
    changes, a sub-account's parent included (`parent_account_id` is not write-once)."""
    with _conn(_fresh(pg_dsn)) as c:
        main, other = _account(c), _account(c)
        child = _account(c, parent=main)
        uid, kind, _ = _identity(c, child)
        c.execute(
            "UPDATE exchange_accounts SET exchange_uid = exchange_uid, kind = kind, "
            "label = 'renamed', is_enabled = false WHERE id = %s",
            (child,),
        )
        c.execute(
            "UPDATE exchange_accounts SET parent_account_id = %s WHERE id = %s", (other, child)
        )
        row = c.execute(
            "SELECT exchange_uid, kind::text, parent_account_id::text, label, is_enabled "
            "FROM exchange_accounts WHERE id = %s",
            (child,),
        ).fetchone()
        assert row == (uid, kind, other, "renamed", False)


def test_the_write_once_guards_are_the_last_before_update_row_triggers(pg_dsn: str) -> None:
    """Same-event BEFORE triggers fire in name order, so one sorting after a guard could rewrite
    NEW after its check. This guard sorts last, after 0041's, and neither rewrites NEW; both are
    whole-row and `ENABLE ALWAYS`. tgtype 19 = ROW | BEFORE | UPDATE."""
    with _conn(_fresh(pg_dsn)) as c:
        order = c.execute(
            "SELECT tgname, tgenabled::text, pg_get_triggerdef(oid) FROM pg_trigger "
            "WHERE tgrelid = 'exchange_accounts'::regclass AND NOT tgisinternal "
            'AND tgtype & 19 = 19 ORDER BY tgname COLLATE "C"'
        ).fetchall()
        config = c.execute(
            "SELECT proconfig FROM pg_proc WHERE oid = 'ea_identity_write_once()'::regprocedure"
        ).fetchone()
        bodies = [
            str(row[0])
            for row in c.execute(
                "SELECT prosrc FROM pg_proc WHERE oid IN "
                "('ea_env_write_once()'::regprocedure, 'ea_identity_write_once()'::regprocedure)"
            ).fetchall()
        ]
    assert [row[0] for row in order] == [
        "trg_ea_env_in_use", "trg_ea_env_parent", "trg_ea_env_write_once",
        "trg_ea_identity_write_once",
    ]  # fmt: skip
    assert order[-1][1:] == (
        "A",
        "CREATE TRIGGER trg_ea_identity_write_once BEFORE UPDATE ON public.exchange_accounts "
        "FOR EACH ROW EXECUTE FUNCTION ea_identity_write_once()",
    )
    assert config == (["search_path=pg_catalog, pg_temp"],)
    # Neither guard rewrites NEW, so the order between the two cannot change what either judges.
    assert len(bodies) == 2 and not any(re.search(r"\bNEW\.\w+\s*:=", body) for body in bodies)


def test_a_uid_rewritten_behind_another_column_is_refused(pg_dsn: str) -> None:
    """The guard reads every UPDATE, not only one naming the column: an earlier-sorting trigger
    that rewrites NEW.exchange_uid on a label change still meets it (a `BEFORE UPDATE OF
    exchange_uid` guard would not fire). The rogue trigger exists only in this test's database."""
    with _conn(_fresh(pg_dsn)) as c:
        c.execute(
            "CREATE FUNCTION test_flip_uid() RETURNS trigger LANGUAGE plpgsql AS "
            "$F$ BEGIN NEW.exchange_uid := '424242'; RETURN NEW; END $F$"
        )
        c.execute(
            "CREATE TRIGGER trg_ea_aa_flip BEFORE UPDATE ON exchange_accounts "
            "FOR EACH ROW EXECUTE FUNCTION test_flip_uid()"
        )
        account = _account(c)
        before = _identity(c, account)
        _refused(
            c,
            "UPDATE exchange_accounts SET label = 'renamed' WHERE id = %s",
            (account,),
            "exchange_uid",
        )
        assert _identity(c, account) == before


def _guards(c: Conn) -> list[tuple[str, str]]:
    """The two write-once guards on `exchange_accounts`, by name, with `tgenabled`."""
    return [
        (str(name), str(enabled))
        for name, enabled in c.execute(
            "SELECT tgname, tgenabled::text FROM pg_trigger "
            "WHERE tgrelid = 'exchange_accounts'::regclass "
            "AND tgname IN ('trg_ea_env_write_once', 'trg_ea_identity_write_once') "
            "ORDER BY tgname"
        ).fetchall()
    ]


def test_the_round_trip_lifts_and_restores_the_rule(pg_dsn: str) -> None:
    """C-5.5: the downgrade drops only this revision's trigger and its function, so 0041's `env`
    guard stays; the upgrade brings the rule back; no row changes either way."""
    dsn = _fresh(pg_dsn)
    with _conn(dsn) as c:
        account = _account(c)
        before = _identity(c, account)
    downgraded = _alembic(dsn, "downgrade", _PREV)
    assert downgraded.returncode == 0, downgraded.stderr
    with _conn(dsn) as c:
        assert _guards(c) == [("trg_ea_env_write_once", "A")]
        assert c.execute("SELECT to_regprocedure('ea_identity_write_once()')").fetchone() == (None,)
        assert _identity(c, account) == before
    upgraded = _alembic(dsn, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr
    with _conn(dsn) as c:
        assert _guards(c) == [("trg_ea_env_write_once", "A"), ("trg_ea_identity_write_once", "A")]
        assert _identity(c, account) == before
        _refused(
            c,
            "UPDATE exchange_accounts SET exchange_uid = %s WHERE id = %s",
            ("424242", account),
            "exchange_uid",
        )
