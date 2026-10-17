"""Execution and position stores, without a database (E29-T01 #845 slice 3/3).

The ports are pinned to `0029_oms_core` (columns, CHECK vocabularies, numeric scales), the
statements are compiled and inspected (account scoping, dedupe, upsert, stops of 0, the partial
index predicates), and the control flow runs over the scripted unit of work of
`test_orders_store.py`. Postgres behaviour is `tests/integration/storage/test_orders_store_pg.py`.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import fields
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast, get_args

import pytest
from sqlalchemy import CheckConstraint, Numeric, Table
from sqlalchemy.exc import IntegrityError

from candleviewer.db import models
from candleviewer.storage.repositories import executions_sqlalchemy as ex
from candleviewer.storage.repositories import positions_sqlalchemy as pos
from candleviewer.storage.repositories.executions import ExecType, ExecutionRow, NewExecution
from candleviewer.storage.repositories.orders import (
    OrderConstraintError,
    OrderNotFoundError,
    OrderSide,
    TpslMode,
)
from candleviewer.storage.repositories.positions import (
    NewPositionSnapshot,
    PositionRow,
    PositionSide,
    PositionSnapshotRow,
    PositionState,
    SnapshotReason,
)
from tests.unit.storage.test_orders_store import _ASYNCPG, _CAP, _leaky, _Rel, _Result, _sql

T0 = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
ACCOUNT, ORDER = uuid.UUID(int=1), uuid.UUID(int=2)


def _fill(**over: Any) -> NewExecution:
    base: dict[str, Any] = {
        "exchange_account_id": ACCOUNT, "exec_id": "E1", "symbol": "BTCUSDT", "side": "Buy",
        "exec_qty": Decimal("0.010"), "exec_price": Decimal("63099.80"),
        "exec_value": Decimal("630.998"), "exec_type": "Trade", "is_maker": False, "exec_ts": T0,
    }  # fmt: skip
    return NewExecution(**(base | over))


def _state(**over: Any) -> PositionState:
    base: dict[str, Any] = {"exchange_account_id": ACCOUNT, "symbol": "BTCUSDT", "size": Decimal(1)}
    return PositionState(**(base | over))


def _snap(**over: Any) -> NewPositionSnapshot:
    base: dict[str, Any] = {"exchange_account_id": ACCOUNT, "symbol": "BTCUSDT", "size": Decimal(0)}
    return NewPositionSnapshot(**(base | {"reason": "ws_push"} | over))


# -- ports: pinned to the 0029 schema -----------------------------------------------------------

_PORTS: list[tuple[Callable[..., object], type, Table, set[str]]] = [
    (_fill, ExecutionRow, models.executions, {"id", "recv_ts"}),
    (_state, PositionRow, models.positions, {"id", "recv_ts", "updated_at"}),
    (_snap, PositionSnapshotRow, models.position_snapshots, {"id", "snap_ts"}),
]


@pytest.mark.parametrize(("new", "row", "table", "assigned"), _PORTS)
def test_rows_hold_every_column_and_inputs_all_but_what_is_assigned(
    new: Callable[..., object], row: type, table: Table, assigned: set[str]
) -> None:
    columns = {c.name for c in table.columns}
    assert {f.name for f in fields(row)} == columns
    assert columns - {f.name for f in fields(cast(Any, new()))} == assigned


_NUMERIC = [
    pytest.param(new, column, id=f"{table.name}.{column.name}")
    for new, row, table, _ in _PORTS
    for column in table.columns
    if isinstance(column.type, Numeric)
    and column.name in {f.name for f in fields(cast(Any, row.__base__))}
]


@pytest.mark.parametrize(("new", "column"), _NUMERIC)
def test_every_numeric_column_takes_its_own_scale_and_refuses_what_it_would_round(
    new: Callable[..., object], column: Any
) -> None:
    """The table is the oracle: numeric(38,18), `fee_rate` (18,10) and `leverage` (10,2)."""
    whole, scale = column.type.precision - column.type.scale, column.type.scale
    nines = "9" * whole + "." + "9" * scale  # strings: Decimal arithmetic rounds to 28 digits
    for good in (Decimal(f"1E-{scale}"), Decimal(nines), Decimal(f"-{nines}")):
        new(**{column.name: good})
    for bad in (Decimal(f"1E-{scale + 1}"), Decimal(f"1E{whole}"), 0.5, Decimal("NaN")):
        with pytest.raises((TypeError, ValueError), match=f"^{column.name} "):
            new(**{column.name: bad})


@pytest.mark.parametrize(("new", "name"), [(_fill, "exec_ts"), (_state, "exchange_updated_ts")])
def test_a_naive_exchange_time_is_refused(new: Callable[..., object], name: str) -> None:
    with pytest.raises(ValueError, match=f"^{name} must be a timezone-aware"):
        new(**{name: datetime(2026, 10, 16)})


@pytest.mark.parametrize(
    ("literal", "table", "check"),
    [(ExecType, models.executions, "ex_type"), (OrderSide, models.executions, "ex_side"),
     (PositionSide, models.positions, "pos_side"), (TpslMode, models.positions, "pos_tpslmode"),
     (SnapshotReason, models.position_snapshots, "psnap_reason")],
)  # fmt: skip
def test_literals_mirror_their_checks(literal: Any, table: Table, check: str) -> None:
    checks = [c for c in table.constraints if isinstance(c, CheckConstraint)]
    (sql,) = (str(c.sqltext) for c in checks if str(c.name).endswith(check))
    assert set(get_args(literal)) == set(re.findall(r"'(\w+)'", sql))


# -- statements ---------------------------------------------------------------------------------

_STATEMENTS: dict[Any, dict[str, Any]] = {
    ex: {
        "insert_statement": ex.insert_statement(_fill(order_id=ORDER)),
        "get_statement": ex.get_statement(ACCOUNT, "E1"),
    },
    pos: {
        "upsert_statement": pos.upsert_statement(_state()),
        "list_open_statement": pos.list_open_statement(ACCOUNT),
        "list_unprotected_statement": pos.list_unprotected_statement(ACCOUNT),
        "append_statement": pos.append_statement(_snap()),
    },
}


@pytest.mark.parametrize("module", [ex, pos], ids=["executions", "positions"])
def test_every_statement_but_the_inserts_is_account_scoped(module: Any) -> None:
    built = _STATEMENTS[module]
    assert {n for n in vars(module) if n.endswith("_statement")} == set(built)  # none dodges
    for name, stmt in built.items():
        own = r"\b(executions|positions|position_snapshots)\.exchange_account_id = \$"
        assert (re.search(own, _sql(stmt)) is not None) is (name not in module.UNSCOPED), name
    assert module.UNSCOPED <= {"insert_statement", "upsert_statement", "append_statement"}


def test_an_execution_insert_dedupes_on_ux_exec_id_and_scopes_its_order() -> None:
    sql = _sql(_STATEMENTS[ex]["insert_statement"])
    conflict = " ON CONFLICT (exchange_account_id, exec_id) DO NOTHING"
    assert sql.endswith(conflict + " RETURNING executions.order_id")
    owned = "WHERE orders.exchange_account_id = $1::UUID AND orders.id = $2::UUID), $3::UUID, "
    assert "VALUES (gen_random_uuid(), (SELECT orders.id \nFROM orders \n" + owned in sql
    assert "SELECT" not in _sql(ex.insert_statement(_fill()))  # no order: NULL, as asked


def test_a_position_upsert_takes_every_state_column_and_stamps_now() -> None:
    sql = _sql(_STATEMENTS[pos]["upsert_statement"])
    key = ("exchange_account_id", "symbol", "position_idx")
    head, update = sql.split(f" ON CONFLICT ({', '.join(key)}) DO UPDATE SET ")
    assert head.startswith("INSERT INTO positions (id, exchange_account_id, symbol, position_idx, ")
    assert "VALUES (gen_random_uuid(), $1::UUID, " in head
    state = [f"{f.name} = excluded.{f.name}" for f in fields(PositionState) if f.name not in key]
    stamps = ["recv_ts = now()", "updated_at = now()"]
    assert set(update.split(" RETURNING ")[0].split(", ")) == {*state, *stamps}


@pytest.mark.parametrize(
    ("given", "bound"),
    [(Decimal(0), None), (Decimal("-1"), None), (None, None), (Decimal("1E-18"), Decimal("1E-18"))],
)
def test_a_stop_of_zero_or_less_is_bound_as_null(given: Decimal | None, bound: object) -> None:
    """The exchange's 0 means none: stored as 0, `ix_pos_no_sl` would miss the position (C-2.6)."""
    stops = {"take_profit": given, "stop_loss": given, "trailing_stop": given}
    params = pos.upsert_statement(_state(**stops)).compile(dialect=_ASYNCPG).params
    assert {name: params[name] for name in stops} == dict.fromkeys(stops, bound)


def test_the_position_reads_render_the_partial_index_predicates_with_literals() -> None:
    where = "WHERE positions.exchange_account_id = $1::UUID AND positions.size > 0"
    order = " ORDER BY positions.symbol, positions.position_idx"
    assert _sql(_STATEMENTS[pos]["list_open_statement"]).endswith(where + order)
    unprotected = _sql(_STATEMENTS[pos]["list_unprotected_statement"])
    assert unprotected.endswith(where + " AND positions.stop_loss IS NULL" + order)


# -- control flow over a scripted unit of work --------------------------------------------------

_EXEC_ROW: dict[str, Any] = {c.name: None for c in ex.EXECUTION_COLUMNS} | {"exec_id": "E1"}
_POSITION_ROW: dict[str, Any] = {c.name: None for c in pos.POSITION_COLUMNS} | {"size": Decimal(1)}
_SNAPSHOT_ROW: dict[str, Any] = {c.name: None for c in pos.SNAPSHOT_COLUMNS} | {"id": 7}


async def test_an_insert_reports_stored_or_duplicate_and_refuses_another_accounts_order() -> None:
    rel = _Rel(
        _Result([SimpleNamespace(order_id=ORDER)]), _Result(),
        _Result([SimpleNamespace(order_id=None)]), _Result([SimpleNamespace(order_id=None)]),
    )  # fmt: skip
    store = ex.SqlAlchemyExecutionStore(cast(Any, rel))
    assert [await store.insert(_fill(order_id=ORDER)), await store.insert(_fill())] == [True, False]
    with pytest.raises(OrderNotFoundError):  # the scoped subquery bound NULL: rolled back
        await store.insert(_fill(order_id=ORDER))
    assert (await store.insert(_fill()), rel.commits) == (True, 2)


async def test_the_reads_and_writes_map_their_rows() -> None:
    executions = ex.SqlAlchemyExecutionStore(cast(Any, _Rel(_Result([_EXEC_ROW]), _Result())))
    assert await executions.get(ACCOUNT, "E1") == ExecutionRow(**_EXEC_ROW)
    assert await executions.get(ACCOUNT, "E2") is None
    rel = _Rel(
        _Result([_POSITION_ROW]), _Result([_POSITION_ROW] * 2), _Result(), _Result([_SNAPSHOT_ROW])
    )
    positions = pos.SqlAlchemyPositionStore(cast(Any, rel))
    assert await positions.upsert(_state()) == PositionRow(**_POSITION_ROW)
    assert len(await positions.list_open(ACCOUNT)) == 2
    assert await positions.list_unprotected(ACCOUNT) == ()
    assert await positions.append(_snap()) == PositionSnapshotRow(**_SNAPSHOT_ROW)
    assert rel.commits == 2


_EXEC, _POS = ex.SqlAlchemyExecutionStore, pos.SqlAlchemyPositionStore
_CALLS: dict[str, tuple[type[Any], Callable[[Any], Awaitable[object]], list[_Result]]] = {
    "insert": (_EXEC, lambda s: s.insert(_fill()), [_Result([SimpleNamespace(order_id=None)])]),
    "get": (_EXEC, lambda s: s.get(ACCOUNT, "E1"), [_Result()]),
    "upsert": (_POS, lambda s: s.upsert(_state()), [_Result([_POSITION_ROW])]),
    "list_open": (_POS, lambda s: s.list_open(ACCOUNT), [_Result()]),
    "list_unprotected": (_POS, lambda s: s.list_unprotected(ACCOUNT), [_Result()]),
    "append": (_POS, lambda s: s.append(_snap()), [_Result([_SNAPSHOT_ROW])]),
}


@pytest.mark.parametrize("call", sorted(_CALLS))
async def test_every_call_is_one_capped_unit_of_work_whose_refusal_is_named(call: str) -> None:
    """The `CappedStore` base: the cap precedes the call's statements, and a violation leaves as
    the named constraint without a commit (24 Sec.8.2 S7, C-12.6)."""
    store, run, script = _CALLS[call]
    rel = _Rel(*script)
    await run(store(cast(Any, rel), statement_timeout_ms=150))
    assert [(str(unit[0][0]), unit[0][1]) for unit in rel.units] == [(_CAP, {"timeout": "150"})]
    failing = _Rel(_leaky(IntegrityError, "23514", "ex_qty"))
    with pytest.raises(OrderConstraintError, match="ex_qty"):
        await run(store(cast(Any, failing)))
    assert failing.commits == 0
