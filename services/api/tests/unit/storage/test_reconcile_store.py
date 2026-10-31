"""The reconciliation pass's own reads and its watermark write (E29-T06 #914 PR 2b; 24
Sec.8.5 step 1 and `gap_from`; 21 Sec.3.2.1, Sec.3.3.6, Sec.3.3.11): each statement filters on the
account (C-12.4) with bound values, and the store's control flow over a scripted unit of work."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import fields
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from sqlalchemy.engine import Dialect, make_url
from sqlalchemy.sql.elements import TextClause

from candleviewer.storage.repositories import reconcile_sqlalchemy as mod
from candleviewer.storage.repositories.orders import OrderRow
from candleviewer.storage.repositories.recorded_stops_sqlalchemy import STOP_FIELDS

ACCOUNT = UUID(int=0xA1)
_ASYNCPG: Dialect = make_url("postgresql+asyncpg://").get_dialect()()
AT = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)


def _sql(stmt: Any) -> str:
    return str(stmt.compile(dialect=_ASYNCPG, compile_kwargs={"render_postcompile": True}))


def _bound(stmt: Any) -> list[Any]:
    return list(stmt.compile(dialect=_ASYNCPG).params.values())


class _Result:
    def __init__(self, rows: Sequence[Any] = ()) -> None:
        self.rows = list(rows)

    def mappings(self) -> _Result:
        return self

    def scalars(self) -> list[Any]:
        return [row[0] for row in self.rows]

    def first(self) -> Any:
        return self.rows[0] if self.rows else None

    def __iter__(self) -> Any:
        return iter(self.rows)


class _Rel:
    """A scripted relational repository: records each statement, replays canned results."""

    def __init__(self, *script: _Result) -> None:
        self.script, self.statements, self.commits = list(script), list[Any](), 0

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        async def execute(stmt: Any, params: Any = None) -> _Result:
            if isinstance(stmt, TextClause):  # the store's statement cap
                return _Result()
            self.statements.append(stmt)
            return self.script.pop(0)

        async def commit() -> None:
            self.commits += 1

        yield SimpleNamespace(session=SimpleNamespace(execute=execute), commit=commit)


def _store(rel: _Rel) -> mod.SqlAlchemyReconcileStore:
    return mod.SqlAlchemyReconcileStore(cast(Any, rel), statement_timeout_ms=2000)


# --- The statements ------------------------------------------------------------------------------


def test_every_statement_is_scoped_to_the_account() -> None:
    """C-12.4: no statement reads or writes another account's row."""
    texts = {
        "stored": _sql(mod.stored_statement(ACCOUNT, ["e1"])),
        "live": _sql(mod.live_for_account_statement(ACCOUNT)),
        "last": _sql(mod.last_reconciled_statement(ACCOUNT)),
        "advance": _sql(mod.advance_statement(ACCOUNT, AT)),
    }
    assert "executions.exchange_account_id = $" in texts["stored"]
    assert "recorded_stops.exchange_account_id = $" in texts["live"]
    for name in ("last", "advance"):
        assert "exchange_accounts.id = $" in texts[name]
        assert "exchange_accounts.deleted_at IS NULL" in texts[name]
    assert ACCOUNT in _bound(mod.stored_statement(ACCOUNT, ["e1"]))


def test_stored_asks_about_each_id_once_as_one_bound_array() -> None:
    stmt = mod.stored_statement(ACCOUNT, ["e2", "e1", "e2"])
    assert "executions.exec_id = ANY ($" in _sql(stmt)
    assert ["e1", "e2"] in _bound(stmt)


def test_live_for_account_reads_pending_and_in_force_rows_oldest_first() -> None:
    sql = _sql(mod.live_for_account_statement(ACCOUNT))
    assert "recorded_stops.status IN ('in_force', 'pending')" in sql
    assert sql.rstrip().endswith("ORDER BY recorded_stops.created_at, recorded_stops.id")


def test_the_watermark_only_moves_forward() -> None:
    sql = _sql(mod.advance_statement(ACCOUNT, AT))
    assert "SET last_reconciled_at=greatest(coalesce(exchange_accounts.last_reconciled_at" in sql
    assert "RETURNING exchange_accounts.id" in sql


# --- The store over a scripted unit of work ------------------------------------------------------


def _order_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {f.name: None for f in fields(OrderRow)}
    return row | {"id": UUID(int=1), "exchange_account_id": ACCOUNT, "order_link_id": "l1"} | over


async def test_unfinished_for_reads_the_sweeps_statement_for_one_account() -> None:
    rel = _Rel(_Result([_order_row()]))
    rows = await _store(rel).unfinished_for(ACCOUNT)
    assert [r.order_link_id for r in rows] == ["l1"]
    sql = _sql(rel.statements[0])
    assert "'held'" in sql and "'untracked'" in sql
    assert mod.MAX_UNFINISHED in _bound(rel.statements[0])


async def test_stored_answers_the_ids_held_and_reads_nothing_for_none() -> None:
    rel = _Rel(_Result([("e1",)]))
    store = _store(rel)
    assert await store.stored(ACCOUNT, ["e1", "e2"]) == frozenset({"e1"})
    assert await store.stored(ACCOUNT, []) == frozenset()
    assert len(rel.statements) == 1
    with pytest.raises(ValueError, match="at most"):
        await store.stored(ACCOUNT, [f"e{n}" for n in range(mod.MAX_ASKED + 1)])


async def test_live_for_account_maps_each_row() -> None:
    row = dict.fromkeys(STOP_FIELDS) | {"id": UUID(int=5), "exchange_account_id": ACCOUNT}
    rel = _Rel(_Result([row]))
    [stop] = await _store(rel).live_for_account(ACCOUNT)
    assert (stop.id, stop.exchange_account_id) == (UUID(int=5), ACCOUNT)


async def test_last_reconciled_answers_the_mark_or_none() -> None:
    rel = _Rel(_Result([(AT,)]), _Result([(None,)]), _Result([]))
    store = _store(rel)
    assert [await store.last_reconciled(ACCOUNT) for _ in range(3)] == [AT, None, None]


async def test_advance_commits_only_what_the_accounts_row_took() -> None:
    rel = _Rel(_Result([(ACCOUNT,)]), _Result([]))
    store = _store(rel)
    assert await store.advance(ACCOUNT, AT) is True
    assert await store.advance(ACCOUNT, AT) is False  # deleted or unknown: nothing committed
    assert rel.commits == 1
    with pytest.raises(ValueError, match="aware"):
        await store.advance(ACCOUNT, AT.replace(tzinfo=None))
