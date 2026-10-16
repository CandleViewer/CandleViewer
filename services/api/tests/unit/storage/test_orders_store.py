"""Order store port and Postgres adapter, without a database (E29-T01 #845 slice 2/3).

The port is pinned to `0029_oms_core` (enums, CHECK vocabularies, `ix_orders_open`, the column
lists); the adapter's statements are compiled and inspected (account scoping, one-statement create,
row lock, `seq` assignment, redaction before binding), and its control flow and error mapping run
over a scripted unit of work. Real-database behaviour is `tests/integration/storage/
test_orders_store_pg.py`.
"""

from __future__ import annotations

import json
import re
import traceback
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import fields
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast, get_args

import pytest
from sqlalchemy import CheckConstraint
from sqlalchemy.dialects.postgresql import asyncpg
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError

from candleviewer.db import models
from candleviewer.storage.errors import StorageQueryFailed
from candleviewer.storage.repositories import orders as port
from candleviewer.storage.repositories import orders_sqlalchemy as mod
from candleviewer.storage.repositories.exchange_payload import REDACTED
from candleviewer.storage.repositories.orders import (
    EVENT_FIELDS,
    MAX_EVENT_PAGE,
    OPEN_STATES,
    NewOrder,
    NewOrderEvent,
    OrderConstraintError,
    OrderEventRow,
    OrderNotFoundError,
    OrderRow,
    require_aware,
    require_money,
)

T0 = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
ACCOUNT, ORDER = uuid.UUID(int=1), uuid.UUID(int=2)
LINK = "cvl-0TLr6mSAQFGvyfsJ0nLDCh-d0hb-00en"  # the #845 Gherkin id
_MAC = "9f" * 32  # synthetic 64-hex shape, digits and letters


def _new_order(**over: Any) -> NewOrder:
    base: dict[str, Any] = {
        "id": ORDER, "exchange_account_id": ACCOUNT, "order_link_id": LINK, "symbol": "BTCUSDT",
        "side": "Buy", "intent": "entry", "order_type": "Limit", "qty": Decimal("0.010"),
        "price": Decimal("63099.80"), "stop_loss": Decimal("62000"), "state": "pending_submit",
    }  # fmt: skip
    return NewOrder(**(base | over))


def _event(**over: Any) -> NewOrderEvent:
    base: dict[str, Any] = {"kind": "local_create", "source": "local", "event_ts": T0}
    return NewOrderEvent(**(base | over))


# -- port: pinned to the 0029 schema ------------------------------------------------------------


@pytest.mark.parametrize(
    ("literal", "enum"),
    [(port.OrderState, models.order_state), (port.OrderIntent, models.order_intent),
     (port.OrderEventKind, models.order_event_kind)],
)  # fmt: skip
def test_enum_literals_mirror_the_database_types(literal: Any, enum: Any) -> None:
    assert get_args(literal) == tuple(enum.enums)


@pytest.mark.parametrize(
    ("literal", "table", "check"),
    [
        (port.OrderSide, models.orders, "ord_side"),
        (port.OrderType, models.orders, "ord_type"),
        (port.TimeInForce, models.orders, "ord_tif"),
        (port.TriggerBy, models.orders, "ord_trigby"),
        (port.TpslMode, models.orders, "ord_tpslmode"),
        (port.IdempotencyState, models.orders, "ord_idem"),
        (port.OrderEventSource, models.order_events, "oe_source"),
    ],
)
def test_text_literals_mirror_their_checks(literal: Any, table: Any, check: str) -> None:
    constraint = next(
        c for c in table.constraints if isinstance(c, CheckConstraint) and c.name.endswith(check)
    )
    assert set(get_args(literal)) == set(re.findall(r"'(\w+)'", str(constraint.sqltext)))


def test_open_states_are_the_ix_orders_open_predicate() -> None:
    index = next(i for i in models.orders.indexes if i.name == "ix_orders_open")
    predicate = str(index.dialect_options["postgresql"]["where"])
    assert set(OPEN_STATES) == set(re.findall(r"'(\w+)'", predicate))


def test_rows_and_inserts_follow_the_table_columns() -> None:
    order_cols = [c.name for c in models.orders.columns]
    assert [f.name for f in fields(OrderRow)] == order_cols
    assert list(EVENT_FIELDS) == [c.name for c in models.order_events.columns]
    assert [f.name for f in fields(OrderEventRow)][2] == "order_link_id"
    left_to_the_database = set(order_cols) - {f.name for f in fields(NewOrder)}
    assert left_to_the_database == {
        "leaves_qty", "created_ts", "submitted_ts", "last_reconciled_at", "reject_code",
        "reject_message", "submit_attempts", "idempotency_state",
    }  # fmt: skip


@pytest.mark.parametrize(
    "value",
    [Decimal("0.000000000000000001"), Decimal("63099.80"), Decimal("-0.5"), Decimal("0E-40"),
     Decimal("99999999999999999999.999999999999999999"), Decimal("1.000000000000000000000000")],
)  # fmt: skip
def test_require_money_accepts_what_numeric_38_18_holds_exactly(value: Decimal) -> None:
    require_money("qty", value)


@pytest.mark.parametrize(
    ("value", "error"),
    [
        (0.1, TypeError), (1, TypeError), ("1", TypeError), (Decimal("NaN"), ValueError),
        (Decimal("sNaN"), ValueError), (Decimal("Infinity"), ValueError),
        (Decimal("1E-19"), ValueError), (Decimal("63099.8000000000000000001"), ValueError),
        (Decimal("1E+20"), ValueError), (Decimal("-100000000000000000000"), ValueError),
    ],
)  # fmt: skip
def test_require_money_refuses_what_the_column_would_change(value: Any, error: type) -> None:
    with pytest.raises(error, match=r"^price ") as exc:
        require_money("price", value)
    assert str(value) not in str(exc.value)  # the column only: a value is P1 (21 Sec.12)


def test_require_aware_refuses_only_a_naive_datetime() -> None:
    require_aware("event_ts", datetime(2026, 10, 16, tzinfo=timezone(timedelta(hours=-3))))
    with pytest.raises(ValueError, match="event_ts must be a timezone-aware"):
        require_aware("event_ts", datetime(2026, 10, 16))


@pytest.mark.parametrize(
    "over",
    [{"qty": 0.01}, {"price": Decimal("NaN")}, {"stop_loss": Decimal("1E-19")},
     {"cum_exec_qty": Decimal("Infinity")}, {"exchange_updated_ts": datetime(2026, 10, 16)}],
)  # fmt: skip
def test_new_order_refuses_floats_non_finite_rounded_money_and_naive_times(
    over: dict[str, Any],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        _new_order(**over)


def test_new_order_event_refuses_a_naive_event_time() -> None:
    with pytest.raises(ValueError, match="event_ts"):
        _event(event_ts=datetime(2026, 10, 16))


def test_constraint_error_names_the_constraint_only() -> None:
    err = OrderConstraintError("ux_orders_link")
    assert err.constraint == "ux_orders_link" and str(err) == (
        "order write violates constraint 'ux_orders_link'"
    )


# -- adapter: statements ------------------------------------------------------------------------


def _sql(stmt: Any) -> str:
    return str(stmt.compile(dialect=asyncpg.dialect(), compile_kwargs={"render_postcompile": True}))


def _bound(stmt: Any) -> list[Any]:
    """The bound values (a CTE's inserts bind anonymous names)."""
    return list(stmt.compile(dialect=asyncpg.dialect()).params.values())


_SECRET_EVENT = _event(payload={"headers": {"X-BAPI-SIGN": _MAC}, "result": {"orderId": "o-1"}})
_STATEMENTS: dict[str, Any] = {
    "create_statement": mod.create_statement(_new_order(), _SECRET_EVENT),
    "get_statement": mod.get_statement(ACCOUNT, ORDER),
    "get_by_link_statement": mod.get_by_link_statement(ACCOUNT, LINK),
    "list_open_statement": mod.list_open_statement(ACCOUNT, "BTCUSDT"),
    "link_taken_statement": mod.link_taken_statement(LINK),
    "lock_statement": mod.lock_statement(ACCOUNT, ORDER),
    "append_statement": mod.append_statement(ACCOUNT, ORDER, _SECRET_EVENT),
    "list_events_statement": mod.list_events_statement(ACCOUNT, ORDER, 3, 50),
}


def test_the_statement_set_is_pinned() -> None:
    # Self-discovering, so a builder added later cannot dodge the scoping test below.
    assert {n for n in vars(mod) if n.endswith("_statement")} == set(_STATEMENTS)


@pytest.mark.parametrize("name", sorted(_STATEMENTS))
def test_every_statement_but_create_and_the_id_check_is_account_scoped(name: str) -> None:
    scoped = "orders.exchange_account_id = $" in _sql(_STATEMENTS[name])
    assert scoped is (name not in mod.UNSCOPED)


def test_only_the_insert_and_the_rule_5_id_check_are_unscoped() -> None:
    assert mod.UNSCOPED == {"create_statement", "link_taken_statement"}
    assert _sql(_STATEMENTS["link_taken_statement"]).startswith("SELECT EXISTS (SELECT")


def test_create_writes_the_order_and_its_first_event_in_one_statement() -> None:
    sql = _sql(_STATEMENTS["create_statement"])
    assert sql.startswith("WITH inserted_order AS \n(INSERT INTO orders (")
    assert "first_event AS \n(INSERT INTO order_events (" in sql
    assert "(SELECT inserted_order.id \nFROM inserted_order)" in sql
    assert "VALUES ((SELECT inserted_order.id \nFROM inserted_order), 0, $" in sql  # seq 0
    assert "(SELECT inserted_order.state \nFROM inserted_order)" in sql  # to_state
    assert sql.count("INSERT INTO") == 2 and "from_state" not in sql
    bound = _bound(_STATEMENTS["create_statement"])
    for value in (LINK, Decimal("62000"), Decimal("0.010"), "local_create", "pending_submit"):
        assert value in bound


@pytest.mark.parametrize("name", ["create_statement", "append_statement"])
def test_payloads_are_redacted_before_they_are_bound(name: str) -> None:
    bound = _bound(_STATEMENTS[name])
    assert {"headers": REDACTED, "result": {"orderId": "o-1"}} in bound
    assert _MAC not in json.dumps(bound, default=str)


def test_list_open_renders_the_open_states_as_literals_for_the_partial_index() -> None:
    sql = _sql(_STATEMENTS["list_open_statement"])
    assert "orders.state IN ('accepted', 'partially_filled', 'pending_amend', " in sql
    assert "orders.symbol = $" in sql and sql.endswith("ORDER BY orders.created_ts, orders.id")
    assert "orders.symbol" not in _sql(mod.list_open_statement(ACCOUNT, None)).split("WHERE")[1]


def test_reads_select_the_column_allow_lists() -> None:
    assert [c.name for c in mod.ORDER_COLUMNS] == [f.name for f in fields(OrderRow)]
    assert [c.name for c in mod.EVENT_COLUMNS] == list(EVENT_FIELDS)
    for name in ("get_statement", "list_open_statement", "list_events_statement"):
        assert "*" not in _sql(_STATEMENTS[name])


def test_append_locks_the_order_and_takes_the_next_seq_of_that_order() -> None:
    assert _sql(_STATEMENTS["lock_statement"]).endswith("FOR NO KEY UPDATE")
    sql = _sql(_STATEMENTS["append_statement"])
    assert "coalesce(max(prior.seq) + $" in sql and "WHERE prior.order_id = $" in sql
    columns = sql.split(" VALUES ")[0]
    assert "from_state" not in columns and "to_state" not in columns
    assert "local_create" in _bound(_STATEMENTS["append_statement"])


def test_list_events_pages_by_seq_inside_the_account() -> None:
    sql = _sql(_STATEMENTS["list_events_statement"])
    assert "JOIN orders ON orders.id = order_events.order_id" in sql
    assert "order_events.seq > $" in sql and "ORDER BY order_events.seq \n LIMIT $" in sql
    assert 50 in _bound(_STATEMENTS["list_events_statement"])


# -- adapter: control flow over a scripted unit of work -----------------------------------------


class _Result:
    def __init__(self, rows: Sequence[Any] = (), scalar: Any = None) -> None:
        self.rows, self.scalar = rows, scalar

    def mappings(self) -> _Result:
        return self

    def first(self) -> Any:
        return self.rows[0] if self.rows else None

    def one(self) -> Any:
        assert len(self.rows) == 1
        return self.rows[0]

    def scalar_one(self) -> Any:
        return self.scalar

    def scalar_one_or_none(self) -> Any:
        return self.scalar

    def __iter__(self) -> Any:
        return iter(self.rows)


class _Rel:
    """Scripted `SqlAlchemyRelationalRepository`: records statements, replays canned results."""

    def __init__(self, *script: _Result | Exception) -> None:
        self.script: list[_Result | Exception] = list(script)
        self.statements: list[Any] = []
        self.commits = 0

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        async def execute(stmt: Any) -> _Result:
            self.statements.append(stmt)
            step = self.script.pop(0)
            if isinstance(step, Exception):
                raise step
            return step

        async def commit() -> None:
            self.commits += 1

        yield SimpleNamespace(session=SimpleNamespace(execute=execute), commit=commit)


def _store(rel: _Rel) -> mod.SqlAlchemyOrderStore:
    return mod.SqlAlchemyOrderStore(cast(Any, rel))  # structural fake


def _order_row(**over: Any) -> dict[str, Any]:
    row = {f.name: None for f in fields(OrderRow)}
    row |= {"id": ORDER, "exchange_account_id": ACCOUNT, "order_link_id": LINK, "qty": Decimal(1)}
    return row | over


def _event_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {name: None for name in EVENT_FIELDS}
    return row | {"id": 7, "order_id": ORDER, "seq": 1, "kind": "ack", "payload": {}} | over


async def test_create_maps_the_returned_row_and_commits_once() -> None:
    rel = _Rel(_Result([_order_row(stop_loss=Decimal("62000"), tpsl_mode="Partial")]))
    row = await _store(rel).create(_new_order(), _event())
    assert (row.order_link_id, row.stop_loss, row.tpsl_mode) == (LINK, Decimal("62000"), "Partial")
    assert (rel.commits, len(rel.statements)) == (1, 1)


async def test_reads_map_rows_and_absence() -> None:
    rel = _Rel(
        _Result([_order_row()]), _Result(), _Result([_order_row(), _order_row()]), _Result(),
        _Result(scalar=True), _Result([_event_row(seq=4, order_link_id=LINK)]),
    )  # fmt: skip
    store = _store(rel)
    assert (await store.get(ACCOUNT, ORDER)) == OrderRow(**_order_row())
    assert await store.get_by_link_id(ACCOUNT, LINK) is None
    assert len(await store.list_open(ACCOUNT, symbol="BTCUSDT")) == 2
    assert await store.list_open(ACCOUNT) == ()
    assert await store.link_id_taken(LINK) is True
    (event,) = await store.list_for_order(ACCOUNT, ORDER, after_seq=3, limit=1)
    assert (event.seq, rel.commits) == (4, 0)


async def test_append_outside_the_account_is_not_found_and_writes_nothing() -> None:
    rel = _Rel(_Result(scalar=None))
    with pytest.raises(OrderNotFoundError):
        await _store(rel).append(ACCOUNT, ORDER, _event(kind="ack", source="rest"))
    assert (len(rel.statements), rel.commits) == (1, 0)


async def test_append_returns_the_stored_event_with_its_order_link_id() -> None:
    rel = _Rel(_Result(scalar=LINK), _Result([_event_row(seq=3, kind="ack")]))
    got = await _store(rel).append(ACCOUNT, ORDER, _event(kind="ack", source="rest"))
    assert (got.order_link_id, got.seq, got.kind, rel.commits) == (LINK, 3, "ack", 1)
    assert "FOR NO KEY UPDATE" in _sql(rel.statements[0])
    assert _sql(rel.statements[1]).startswith("INSERT INTO order_events")


@pytest.mark.parametrize(("after_seq", "limit"), [(-2, 1), (0, 0), (0, MAX_EVENT_PAGE + 1)])
async def test_list_for_order_refuses_an_unbounded_or_negative_page(
    after_seq: int, limit: int
) -> None:
    rel = _Rel()
    with pytest.raises(ValueError, match=r"after_seq .* limit"):
        await _store(rel).list_for_order(ACCOUNT, ORDER, after_seq=after_seq, limit=limit)
    assert rel.statements == []


class _Driver(Exception):
    def __init__(self, constraint_name: str) -> None:
        super().__init__("driver")
        self.constraint_name = constraint_name


class _PgError(Exception):
    """What the asyncpg wrapper raises: `sqlstate` here, the constraint name on `__cause__`."""

    def __init__(self, sqlstate: Any, *, cause: str | None = None, message: str = "pg") -> None:
        super().__init__(message)
        self.sqlstate = sqlstate
        if cause is not None:
            self.__cause__ = _Driver(cause)


_P1 = "63099.80"  # a bound P1 value (21 Sec.12) the driver error would render


def _leaky(error: type[DBAPIError], sqlstate: Any, cause: str | None = None) -> DBAPIError:
    detail = f"violates a constraint\nDETAIL:  Failing row contains ({_P1})"
    return error(
        "INSERT INTO orders", {"price": _P1}, _PgError(sqlstate, cause=cause, message=detail)
    )


_WRITES: dict[str, Callable[[mod.SqlAlchemyOrderStore], Awaitable[object]]] = {
    "create": lambda store: store.create(_new_order(), _event()),
    "append": lambda store: store.append(ACCOUNT, ORDER, _event(kind="ack", source="rest")),
}


def _script(write: str, error: DBAPIError) -> _Rel:
    return _Rel(error) if write == "create" else _Rel(_Result(scalar=LINK), error)


@pytest.mark.parametrize("write", sorted(_WRITES))
@pytest.mark.parametrize(
    ("sqlstate", "name"),
    [("23505", "ux_orders_link"), ("23514", "ord_cum"), ("23503", "orders_parent_order_id_fkey")],
)
async def test_a_named_violation_becomes_the_constraint_and_leaks_nothing(
    write: str, sqlstate: str, name: str
) -> None:
    leaky = _leaky(IntegrityError, sqlstate, name)
    assert _P1 in "".join(traceback.format_exception(leaky))  # control: the raw error leaks
    rel = _script(write, leaky)
    with pytest.raises(OrderConstraintError) as err:
        await _WRITES[write](_store(rel))
    assert (err.value.constraint, rel.commits) == (name, 0)
    assert (err.value.__cause__, err.value.__suppress_context__) == (None, True)
    assert _P1 not in "".join(traceback.format_exception(err.value))


@pytest.mark.parametrize("write", sorted(_WRITES))
@pytest.mark.parametrize(
    ("error", "sqlstate", "cause", "reported"),
    [
        (IntegrityError, "23502", "not_null", "23502"),  # not a constraint this store maps
        (IntegrityError, "23514", None, "23514"),  # a named violation without a name: no guess
        (OperationalError, "40001", None, "40001"),
        (OperationalError, 40001, None, None),  # an int is not a SQLSTATE
    ],
)
async def test_any_other_database_error_keeps_only_its_sqlstate(
    write: str, error: type[DBAPIError], sqlstate: Any, cause: str | None, reported: str | None
) -> None:
    rel = _script(write, _leaky(error, sqlstate, cause))
    with pytest.raises(StorageQueryFailed) as err:
        await _WRITES[write](_store(rel))
    assert (err.value.sqlstate, rel.commits) == (reported, 0)
    assert (err.value.__cause__, err.value.__suppress_context__) == (None, True)
    assert _P1 not in "".join(traceback.format_exception(err.value))


def test_a_violation_named_on_the_driver_error_itself_is_read_too() -> None:
    orig = _PgError("23505")
    cast(Any, orig).constraint_name = "ux_orders_exch_id"
    assert mod._violated_constraint(DBAPIError("stmt", {}, orig)) == "ux_orders_exch_id"
