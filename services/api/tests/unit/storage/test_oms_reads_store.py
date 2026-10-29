"""The OMS read store without a database (E29-T07 #915, PR 1): every statement compiled and
inspected (the scope held in SQL, the environment, the partial-index predicates, the keyset), and
the control flow run over the scripted unit of work of `test_orders_store.py`: a named account
outside the scope reads no row, an empty scope or an empty state set reads none either. Postgres
behaviour is `tests/integration/storage/test_oms_reads_pg.py`."""

from __future__ import annotations

import re
import uuid
from dataclasses import fields
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import pytest

from candleviewer.storage.repositories import oms_reads_sqlalchemy as mod
from candleviewer.storage.repositories.accounts import GrantScope, OwnerScope
from candleviewer.storage.repositories.executions import ExecutionRow
from candleviewer.storage.repositories.oms_reads import (
    NON_TERMINAL_STATES,
    ExecutionQuery,
    Keyset,
    OrderDetail,
    OrderQuery,
    PositionOutOfScope,
    PositionQuery,
)
from candleviewer.storage.repositories.orders import AccountsOutOfScope, OutOfScope
from candleviewer.storage.repositories.positions import PositionRow
from tests.unit.storage.test_orders_store import (
    ACCOUNT,
    ORDER,
    USER,
    _event_row,
    _order_row,
    _Rel,
    _Result,
    _scoped_row,
    _sql,
)

T0 = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
FOREIGN, GROUP, POSITION = uuid.UUID(int=9), uuid.UUID(int=4), uuid.UUID(int=6)
_GRANT = GrantScope(USER, frozenset({ACCOUNT}))
_OWNER = OwnerScope(USER)
_AFTER = Keyset(T0, ORDER)
_EVERY = OrderQuery(
    accounts=(ACCOUNT,), symbol="BTCUSDT", states=frozenset({"accepted", "filled"}),
    intents=frozenset({"entry"}), trade_group_id=GROUP, open_only=True, since=T0, until=T0,
)  # fmt: skip
_FILLS = ExecutionQuery(
    accounts=(ACCOUNT,), symbol="BTCUSDT", order_id=ORDER, trade_group_id=GROUP, since=T0, until=T0
)
_STATEMENTS: dict[str, Any] = {
    "orders_statement": mod.orders_statement(_GRANT, _EVERY, "demo", (ACCOUNT,), _AFTER, 101),
    "executions_statement": mod.executions_statement(
        _GRANT, _FILLS, "demo", (ACCOUNT,), _AFTER, 101
    ),
    "order_fills_statement": mod.order_fills_statement(ACCOUNT, ORDER),
    "positions_statement": mod.positions_statement(_GRANT, PositionQuery(), "demo", (ACCOUNT,)),
    "position_statement": mod.position_statement(_GRANT, POSITION, "demo"),
    "position_holder_statement": mod.position_holder_statement(POSITION),
}
_VIEW = "uaa.can_view AND NOT uaa.frozen)"


def test_every_statement_but_two_holds_the_viewing_scope_and_the_environment() -> None:
    """C-12.4 in the query layer: each statement that serves rows holds the grant's viewing
    predicate and the process's environment; the two `UNSCOPED` ones are pinned."""
    own = {n for n, v in vars(mod).items() if getattr(v, "__module__", None) == mod.__name__}
    assert {n for n in own if n.endswith("_statement")} == set(_STATEMENTS)  # none dodges
    assert mod.UNSCOPED == {"order_fills_statement", "position_holder_statement"}
    for name, stmt in _STATEMENTS.items():
        sql = _sql(stmt)
        scoped = _VIEW in sql and "exchange_accounts.env = " in sql
        assert scoped is (name not in mod.UNSCOPED), name
        assert "can_trade" not in sql, name  # a read never needs the trade grant
    assert "executions.exchange_account_id = " in _sql(_STATEMENTS["order_fills_statement"])


def test_an_owner_scope_is_its_live_owner_role_never_every_row() -> None:
    sql = _sql(mod.orders_statement(_OWNER, OrderQuery(), "live", (ACCOUNT,), None, 10))
    assert "roles.name = " in sql and "user_roles.user_id = " in sql
    assert "exchange_accounts.env = " in sql


def test_the_order_list_renders_its_filters_its_keyset_and_newest_first() -> None:
    sql = _sql(_STATEMENTS["orders_statement"])
    assert "orders.state IN ('accepted')" in sql  # `filled` is no open state: open_only drops it
    assert "orders.intent IN ('entry')" in sql
    assert "trade_group_legs.trade_group_id = " in sql
    assert "orders.created_ts >= " in sql and "orders.created_ts < " in sql
    assert re.search(r"\(orders\.created_ts, orders\.id\) < \(\$\d+::TIMESTAMP WITH TIME ZONE", sql)
    assert re.search(
        r"ORDER BY orders.created_ts DESC, orders.id DESC \s+LIMIT \$\d+::INTEGER$", sql
    )


def test_open_only_alone_is_the_non_terminal_set_held_and_untracked_included() -> None:
    query = OrderQuery(open_only=True)
    assert query.wanted_states() == NON_TERMINAL_STATES
    assert {"held", "untracked", "unknown"} <= NON_TERMINAL_STATES
    assert not {"filled", "cancelled", "rejected", "expired", "killed"} & NON_TERMINAL_STATES
    assert OrderQuery().wanted_states() is None
    assert OrderQuery(open_only=True, states=frozenset({"filled"})).wanted_states() == frozenset()


def test_the_fill_list_takes_its_group_from_its_leg_else_its_orders() -> None:
    sql = _sql(_STATEMENTS["executions_statement"])
    assert "coalesce(executions.trade_group_leg_id, filled_order.trade_group_leg_id)" in sql
    assert re.search(r"\(executions\.exec_ts, executions\.id\) < \(", sql)
    assert "ORDER BY executions.exec_ts DESC, executions.id DESC" in sql


def test_open_positions_render_the_partial_index_predicate() -> None:
    sql = _sql(_STATEMENTS["positions_statement"])
    assert "positions.size > 0" in sql
    shut = _sql(mod.positions_statement(_GRANT, PositionQuery(open_only=False), "demo", (ACCOUNT,)))
    assert "positions.size > 0" not in shut


# -- the store's control flow -----------------------------------------------------------------


def _store(*script: _Result | BaseException) -> tuple[mod.SqlAlchemyOmsReads, _Rel]:
    rel = _Rel(*script)
    return mod.SqlAlchemyOmsReads(cast(Any, rel)), rel


def _fill_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {f.name: None for f in fields(ExecutionRow)}
    row |= {"id": uuid.UUID(int=7), "exchange_account_id": ACCOUNT, "exec_id": "E1"}
    row |= {"symbol": "BTCUSDT", "side": "Buy", "exec_qty": Decimal(1), "exec_ts": T0}
    return row | {"trade_group_id": GROUP} | over


def _position_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {f.name: None for f in fields(PositionRow)}
    return row | {"id": POSITION, "exchange_account_id": ACCOUNT, "symbol": "BTCUSDT"} | over


async def test_orders_settle_the_accounts_then_read_them_in_one_unit_of_work() -> None:
    store, rel = _store(
        _Result([{"id": ACCOUNT}]), _Result([_order_row() | {"trade_group_id": GROUP}])
    )
    [listed] = await store.orders(_GRANT, OrderQuery(), environment="demo", after=None, limit=5)
    assert (listed.order.id, listed.trade_group_id) == (ORDER, GROUP)
    assert len(rel.units) == 1 and len(rel.statements) == 2


async def test_a_named_account_outside_the_scope_reads_no_row() -> None:
    """SR-E29-13: the whole request is refused before any row is read."""
    store, rel = _store(_Result([{"id": ACCOUNT}]))
    with pytest.raises(AccountsOutOfScope):
        await store.orders(
            _GRANT, OrderQuery(accounts=(ACCOUNT, FOREIGN)), environment="demo", after=None, limit=5
        )
    with pytest.raises(AccountsOutOfScope):
        await mod.SqlAlchemyOmsReads(cast(Any, _Rel(_Result([])))).positions(
            _GRANT, PositionQuery(accounts=(FOREIGN,)), environment="demo"
        )
    assert len(rel.statements) == 1  # the accounts' settle alone


async def test_an_empty_scope_or_state_set_reads_nothing_more() -> None:
    store, rel = _store(_Result([]))
    assert await store.orders(_GRANT, OrderQuery(), environment="demo", after=None, limit=5) == ()
    store, rel = _store(_Result([{"id": ACCOUNT}]))
    terminal = OrderQuery(open_only=True, states=frozenset({"filled"}))
    assert await store.orders(_GRANT, terminal, environment="demo", after=None, limit=5) == ()
    assert len(rel.statements) == 1
    store, rel = _store(_Result([]))
    assert (
        await store.executions(_GRANT, ExecutionQuery(), environment="demo", after=None, limit=5)
        == ()
    )
    store, rel = _store(_Result([]))
    assert await store.positions(_GRANT, PositionQuery(), environment="demo") == ()
    with pytest.raises(ValueError, match="limit"):
        await store.orders(_GRANT, OrderQuery(), environment="demo", after=None, limit=0)


async def test_fills_and_positions_map_their_rows() -> None:
    store, _ = _store(_Result([{"id": ACCOUNT}]), _Result([_fill_row()]))
    [fill] = await store.executions(
        _GRANT, ExecutionQuery(), environment="demo", after=None, limit=5
    )
    assert (fill.execution.exec_id, fill.trade_group_id) == ("E1", GROUP)
    store, _ = _store(_Result([{"id": ACCOUNT}]), _Result([_position_row()]))
    [position] = await store.positions(_GRANT, PositionQuery(), environment="demo")
    assert position.id == POSITION


async def test_an_order_in_scope_comes_with_its_events_and_fills() -> None:
    store, rel = _store(
        _Result([_scoped_row()]),
        _Result([_event_row() | {"order_link_id": "L"}]),
        _Result([_fill_row(order_id=ORDER)]),
    )
    found = await store.order(_GRANT, ORDER, environment="demo", events=True)
    assert isinstance(found, OrderDetail)
    assert (found.scoped.trade_group_id, len(found.events), len(found.executions)) == (GROUP, 1, 1)
    store, rel = _store(_Result([_scoped_row()]), _Result([]))
    found = await store.order(_GRANT, ORDER, environment="demo", events=False)
    assert isinstance(found, OrderDetail) and found.events == () and len(rel.statements) == 2


async def test_an_order_or_position_outside_the_scope_names_only_its_holder() -> None:
    store, _ = _store(_Result([{"holder": FOREIGN, "id": None}]))
    assert await store.order(_GRANT, ORDER, environment="demo", events=True) == OutOfScope(FOREIGN)
    store, _ = _store(_Result([]), _Result(scalar=FOREIGN))
    assert await store.position(_GRANT, POSITION, environment="demo") == PositionOutOfScope(FOREIGN)
    store, _ = _store(_Result([_position_row()]))
    found = await store.position(_GRANT, POSITION, environment="demo")
    assert isinstance(found, PositionRow) and found.id == POSITION
