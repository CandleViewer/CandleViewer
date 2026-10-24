"""Integration (E42-Q01, #962): the AUDIT-10M loader on a migrated Postgres 16, at 600 rows.

Audit rows can never be removed (C-5.7), so each test loads into a database of its own, cloned
from the migrated `test` one and named for tests. In each mode the loader loads (its own rows
number `rows`), a second load changes nothing while another audit row is present (which pins the
own-rows predicate), the chain trigger is enabled after it, and the other mode is refused; a chained
load's range verifies with the app's own verify. A bulk load that fails, or whose connection is
closed mid-transaction as a killed loader's is, leaves the trigger on and no row of its own, as a
second connection reads them. Needs Docker (testcontainers); CI `integration` runs it.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from typing import Any

import psycopg
import pytest
from psycopg import sql

from candleviewer.audit.query import AuditQueryService
from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from tests.fixtures.admin import audit_10m
from tests.fixtures.admin.audit_10m import OWN_LABEL, load_audit_10m
from tests.fixtures.admin.seed import FixtureCheckError
from tests.integration import _refused

pytestmark = pytest.mark.integration

pg_dsn = _refused.pg_dsn  # the module-scoped Postgres 16, migrated; its database is named `test`
_ROWS, _SIZE = 600, 250  # three batches, the last one short
_OWN = "SELECT count(*) FROM audit_log WHERE actor_label ~ %s"
_ALL = "SELECT count(*) FROM audit_log"
_GUARD = (
    "SELECT tgenabled::text FROM pg_trigger"
    " WHERE tgrelid = 'audit_log'::regclass AND tgname = 'trg_audit_chain'"
)
#: Another writer's audit row, appended through the chain trigger.
_OTHER = (
    "INSERT INTO audit_log (record_id, actor_label, action)"
    " VALUES (gen_random_uuid(), 'fixture-chain', 'orders.submit')"
)


def _rows(dsn: str, query: str, *params: Any) -> list[tuple[Any, ...]]:
    with psycopg.connect(dsn) as conn:
        return conn.execute(query, params).fetchall()


@pytest.fixture
def fresh(pg_dsn: str) -> str:
    """The psycopg DSN of a migrated database of the test's own, named for tests: a template
    database has no other connection while it is copied, so the copy goes through `postgres`."""
    server, template = pg_dsn.replace("postgresql+asyncpg", "postgresql").rsplit("/", 1)
    name = f"audit10m_{uuid.uuid4().hex[:12]}_test"
    with psycopg.connect(f"{server}/postgres", autocommit=True) as conn:
        conn.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                sql.Identifier(name), sql.Identifier(template)
            )
        )
    return f"{server}/{name}"


@pytest.mark.parametrize("chained", [True, False], ids=["chained", "bulk"])
def test_a_load_is_idempotent_leaves_the_trigger_on_and_refuses_the_other_mode(
    fresh: str, chained: bool
) -> None:
    with psycopg.connect(fresh, autocommit=True) as conn:
        conn.execute(_OTHER)
    assert load_audit_10m(fresh, _ROWS, _SIZE, chained=chained) == _ROWS
    assert _rows(fresh, _OWN, OWN_LABEL) == [(_ROWS,)]
    assert _rows(fresh, _GUARD) == [("O",)]
    assert load_audit_10m(fresh, _ROWS, _SIZE, chained=chained) == _ROWS  # the other row is there
    assert _rows(fresh, _ALL) == [(_ROWS + 1,)]
    loaded, asked = ("chained", "bulk") if chained else ("bulk", "chained")
    with pytest.raises(FixtureCheckError, match=f"loaded {loaded}, and this call asks for {asked}"):
        load_audit_10m(fresh, _ROWS, _SIZE, chained=not chained)
    assert _rows(fresh, _ALL) == [(_ROWS + 1,)]


async def test_a_chained_loads_range_verifies_with_the_apps_own_verify(fresh: str) -> None:
    await asyncio.to_thread(load_audit_10m, fresh, _ROWS, _SIZE)
    [(first, last)] = _rows(fresh, "SELECT min(id), max(id) FROM audit_log")
    relational = SqlAlchemyRelationalRepository(
        fresh.replace("postgresql://", "postgresql+asyncpg://")
    )
    service = AuditQueryService(SqlAlchemyAuditRepository(relational))
    try:
        result = await service.verify(from_id=first, to_id=last)
    finally:
        service.close()
        await relational.dispose()
    assert (result.verified, result.entries_checked) == (True, _ROWS)


class _Killed(psycopg.Connection[Any]):
    """A connection that closes itself, sending no COMMIT or ROLLBACK, just before it would send a
    statement holding `armed`, as a killed loader's does: the server rolls its transaction back.
    With `raises` set it raises that instead and stays up, as an interrupt does."""

    armed = ""
    raises: BaseException | None = None

    def execute(self, query: Any, params: Any = None, **kwargs: Any) -> Any:
        if self.armed and self.armed in str(query):
            if self.raises is not None:
                raise self.raises
            self.close()
        return super().execute(query, params, **kwargs)


def _killed_at(
    marker: str, raises: BaseException | None = None
) -> Callable[[str], psycopg.Connection[Any]]:
    """The loader's `connect_test_database`, its connection dying (or raising) at the statement
    with `marker`."""

    def connect(dsn: str) -> psycopg.Connection[Any]:
        conn = _Killed.connect(dsn, autocommit=True)
        conn.armed, conn.raises = marker, raises
        return conn

    return connect


def _left_behind(dsn: str) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
    """What a second connection reads: the chain trigger's state and the loader's own rows."""
    return _rows(dsn, _GUARD), _rows(dsn, _OWN, OWN_LABEL)


def test_a_bulk_load_killed_mid_transaction_leaves_the_trigger_on_and_no_row(
    fresh: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The second batch's insert is the statement it dies at: DISABLE and the first batch are in.
    monkeypatch.setattr(
        audit_10m, "connect_test_database", _killed_at("generate_series(250::bigint")
    )
    with pytest.raises(psycopg.OperationalError):
        load_audit_10m(fresh, _ROWS, _SIZE, chained=False)
    assert _left_behind(fresh) == ([("O",)], [(0,)])


def test_a_bulk_load_interrupted_mid_transaction_leaves_the_trigger_on_and_no_row(
    fresh: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B3's re-check N2: a `KeyboardInterrupt` at the second batch, DISABLE and the first batch in,
    on a connection that is still up: the transaction's exit rolls back on the server."""
    monkeypatch.setattr(
        audit_10m,
        "connect_test_database",
        _killed_at("generate_series(250::bigint", KeyboardInterrupt()),
    )
    with pytest.raises(KeyboardInterrupt):
        load_audit_10m(fresh, _ROWS, _SIZE, chained=False)
    assert _left_behind(fresh) == ([("O",)], [(0,)])


def test_a_bulk_load_whose_insert_fails_leaves_the_trigger_on_and_no_row(fresh: str) -> None:
    with psycopg.connect(fresh, autocommit=True) as conn:  # the first batch is dated before it
        conn.execute(
            "ALTER TABLE audit_log ADD CONSTRAINT fx_first_batch_only"
            " CHECK (event_ts < '2026-06-02T00:00:00Z')"
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        load_audit_10m(fresh, _ROWS, _SIZE, chained=False)
    assert _left_behind(fresh) == ([("O",)], [(0,)])
