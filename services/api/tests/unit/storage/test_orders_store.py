"""Order store port and Postgres adapter, without a database (E29-T01 #845).

The port is pinned to `0029_oms_core` (enums, CHECK vocabularies, `ix_orders_open`, the column
lists, the money and time columns `NewOrder` checks); the adapter's statements are compiled and
inspected (account scoping, one-statement create, row lock, `seq` assignment, redaction of
`payload`, `ret_code` and `ret_msg` before binding), and its control flow, statement cap and error
mapping run over a scripted unit of work. Real-database behaviour is `tests/integration/storage/
test_orders_store_pg.py`.
"""

from __future__ import annotations

import asyncio
import json
import re
import socket
import traceback
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager, nullcontext
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast, get_args

import pytest
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import CheckConstraint, DateTime, Numeric, TextClause
from sqlalchemy.engine import Dialect, make_url
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from candleviewer.db import models
from candleviewer.exchange.base.models import ExchangeOrderId
from candleviewer.storage.errors import StorageQueryFailed, StorageTierUnavailable
from candleviewer.storage.repositories import executions_sqlalchemy as ex
from candleviewer.storage.repositories import orders as port
from candleviewer.storage.repositories import orders_sqlalchemy as mod
from candleviewer.storage.repositories.accounts import GrantScope, OwnerScope
from candleviewer.storage.repositories.exchange_payload import MAX_CODE_CHARS, OVERSIZE, REDACTED
from candleviewer.storage.repositories.orders import (
    EVENT_FIELDS,
    MAX_EVENT_PAGE,
    OPEN_STATES,
    FillRefused,
    NewOrder,
    NewOrderEvent,
    OrderConstraintError,
    OrderEventRow,
    OrderNotFoundError,
    OrderRow,
    StaleOrderState,
    require_aware,
    require_lifecycle,
    require_money,
)
from tests.unit.oms.write_ahead_contract import event, fill, step

T0 = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
ACCOUNT, ORDER, USER = uuid.UUID(int=1), uuid.UUID(int=2), uuid.UUID(int=3)
_GRANT = GrantScope(USER, frozenset({ACCOUNT}))
LINK = "cvl-0TLr6mSAQFGvyfsJ0nLDCh-d0hb-00en"  # the #845 Gherkin id
_MAC = "9f" * 32  # synthetic 64-hex shape, digits and letters
_KEY = "DUMMYKEY_" + "Q3w9" * 5  # synthetic, built at run time (SR-145)


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
        (port.OrderProvenance, models.orders, "ord_provenance"),
        (port.OrderEventSource, models.order_events, "oe_source"),
    ],
)
def test_text_literals_mirror_their_checks(literal: Any, table: Any, check: str) -> None:
    constraint = next(
        c
        for c in table.constraints
        if isinstance(c, CheckConstraint) and isinstance(c.name, str) and c.name.endswith(check)
    )
    assert set(get_args(literal)) == set(re.findall(r"'(\w+)'", str(constraint.sqltext)))


def test_open_states_are_the_ix_orders_open_predicate() -> None:
    index = next(i for i in models.orders.indexes if i.name == "ix_orders_open")
    predicate = str(index.dialect_options["postgresql"]["where"])
    assert set(OPEN_STATES) == set(re.findall(r"'(\w+)'", predicate))


@pytest.mark.parametrize("length", [0, 1, port.MAX_EXCHANGE_ORDER_ID_CHARS, 65])
def test_the_longest_exchange_order_id_is_the_adapters(length: int) -> None:
    """The stores mirror the adapter's `ExchangeOrderId` (1 to 64 characters), and no other."""
    text = "x" * length
    try:
        TypeAdapter(ExchangeOrderId).validate_python(text)
        adapter_takes = True
    except ValidationError:
        adapter_takes = False
    try:
        port.require_exchange_order_id(text)
        store_takes = True
    except ValueError:
        store_takes = False
    assert store_takes is adapter_takes is (1 <= length <= 64)


@pytest.mark.parametrize("value", [None, 7, b"x"])
def test_an_exchange_order_id_that_is_not_text_is_refused_naming_no_value(value: Any) -> None:
    with pytest.raises(ValueError) as refused:
        port.require_exchange_order_id(value)
    assert str(refused.value) == "an order id is text of 1 to 64 characters"


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


@pytest.mark.parametrize(("chart", "state", "ok"), [("validated", "pending_submit", True),
                         ("submitted", "accepted", True), ("submitted", "submitted", False),
                         ("held", "accepted", False), (None, "accepted", True)])  # fmt: skip
def test_lifecycle_state_comes_only_with_the_state_it_maps_to(
    chart: Any, state: Any, ok: bool
) -> None:
    """`ord_lifecycle` in code (#847): a chart state and the `order_state` 24 Sec.8.2 maps it to,
    or none; `submitted` names a different state on each side."""
    if ok:
        require_lifecycle(chart, state)
        return
    with pytest.raises(ValueError, match="ord_lifecycle"):
        require_lifecycle(chart, state)


@pytest.mark.parametrize(
    ("terms", "error"),
    [({"side": Decimal(1)}, "only the terms"), ({"price": Decimal("1E-19")}, "price does not fit")],
)
def test_a_step_changes_only_amendable_terms_the_columns_hold(
    terms: dict[str, Decimal], error: str
) -> None:
    with pytest.raises(ValueError, match=error):
        step(_HELD, "accepted", terms=terms)


def test_require_aware_refuses_only_a_naive_datetime() -> None:
    require_aware("event_ts", datetime(2026, 10, 16, tzinfo=timezone(timedelta(hours=-3))))
    with pytest.raises(ValueError, match="event_ts must be a timezone-aware"):
        require_aware("event_ts", datetime(2026, 10, 16))


_WRITTEN = {f.name for f in fields(NewOrder)}
#: The oracle is the table: every numeric(38,18) and timestamptz column a `NewOrder` writes.
_MONEY = [
    c.name
    for c in models.orders.columns
    if isinstance(c.type, Numeric) and c.type.scale == 18 and c.name in _WRITTEN
]
_TIMES = [
    c.name for c in models.orders.columns if isinstance(c.type, DateTime) and c.name in _WRITTEN
]


def test_new_order_checks_every_money_and_time_column_it_writes() -> None:
    assert _MONEY == [
        "qty", "price", "trigger_price", "take_profit", "stop_loss", "cum_exec_qty",
        "cum_exec_value", "avg_price", "fee_paid",
    ]  # fmt: skip
    assert _TIMES == ["exchange_created_ts", "exchange_updated_ts"]


@pytest.mark.parametrize("column", _MONEY)
@pytest.mark.parametrize("bad", [0.01, Decimal("NaN"), Decimal("Infinity"), Decimal("1E-19")])
def test_new_order_refuses_a_float_non_finite_or_rounded_money_value(column: str, bad: Any) -> None:
    with pytest.raises((TypeError, ValueError), match=f"^{column} "):
        _new_order(**{column: bad})


@pytest.mark.parametrize("column", _TIMES)
def test_new_order_refuses_a_naive_exchange_time(column: str) -> None:
    with pytest.raises(ValueError, match=f"^{column} must be a timezone-aware"):
        _new_order(**{column: datetime(2026, 10, 16)})


def test_new_order_event_refuses_a_naive_event_time() -> None:
    with pytest.raises(ValueError, match="event_ts"):
        _event(event_ts=datetime(2026, 10, 16))


def test_constraint_error_names_the_constraint_only() -> None:
    err = OrderConstraintError("ux_orders_link")
    assert err.constraint == "ux_orders_link" and str(err) == (
        "order write violates constraint 'ux_orders_link'"
    )


def test_a_missed_compare_and_set_names_both_of_its_causes() -> None:
    """Another writer moved the state, or only the `cum_exec_qty` a fill's totals came from; the
    message names the order and the state, never a value."""
    moved = f"order {ORDER} moved on from 'accepted' or from the row a fill was built on"
    assert str(StaleOrderState(ORDER, "accepted")) == f"{moved}: nothing was written"


# -- adapter: statements ------------------------------------------------------------------------


_ASYNCPG: Dialect = make_url("postgresql+asyncpg://").get_dialect()()


def _sql(stmt: Any) -> str:
    return str(stmt.compile(dialect=_ASYNCPG, compile_kwargs={"render_postcompile": True}))


def _bound(stmt: Any) -> list[Any]:
    """The bound values (a CTE's inserts bind anonymous names)."""
    return list(stmt.compile(dialect=_ASYNCPG).params.values())


_SECRET_EVENT = _event(
    payload={"headers": {"X-BAPI-SIGN": _MAC}, "result": {"orderId": "o-1"}},
    ret_code="10004",
    ret_msg=f"error sign! origin_string[1760630400000{_KEY}5000]",  # the signed string echoed
)
#: An order row as the write-ahead step reads it (E29-T03), and a step and a fill from it.
_HELD = cast(Any, SimpleNamespace(id=ORDER, exchange_account_id=ACCOUNT, state="accepted"))
_HELD.order_link_id, _HELD.qty = LINK, Decimal("0.3")
_HELD.cum_exec_qty = _HELD.cum_exec_value = _HELD.fee_paid = 0
_RETURNED = event(ret_code="10004", ret_msg=_SECRET_EVENT.ret_msg)  # a reject is its event's
_STEP = step(_HELD, "rejected", _RETURNED, reject_code="10004", reject_message=_RETURNED.ret_msg)
_FILL = fill(_HELD, "E1", "0.1")
_STATEMENTS: dict[str, Any] = {
    "create_statement": mod.create_statement(_new_order(), _SECRET_EVENT),
    "get_statement": mod.get_statement(ACCOUNT, ORDER),
    "get_by_link_statement": mod.get_by_link_statement(ACCOUNT, LINK),
    "get_by_exchange_statement": mod.get_by_exchange_statement(ACCOUNT, "x-1"),
    "list_open_statement": mod.list_open_statement(ACCOUNT, "BTCUSDT"),
    "link_taken_statement": mod.link_taken_statement(LINK),
    "lock_statement": mod.lock_statement(ACCOUNT, ORDER),
    "append_statement": mod.append_statement(ACCOUNT, ORDER, _SECRET_EVENT),
    "list_events_statement": mod.list_events_statement(ACCOUNT, ORDER, 3, 50),
    "transition_statement": mod.transition_statement(_STEP),
    "fill_statement": mod.fill_statement(_FILL),
    "settle_entry_stops_statement": mod.settle_entry_stops_statement(ACCOUNT, ORDER, "void", T0),
    "environment_accounts_statement": mod.environment_accounts_statement("demo"),
    "list_unfinished_statement": mod.list_unfinished_statement([ACCOUNT], 4097),
    "in_scope_statement": mod.in_scope_statement(_GRANT, ORDER, "demo"),
    "accounts_in_scope_statement": mod.accounts_in_scope_statement(_GRANT, "demo", [ACCOUNT]),
}
#: The exit routes' reads (E29-T04 slice 4), scoped by the principal: the grant bound to its user.
_BY_PRINCIPAL = {"in_scope_statement", "accounts_in_scope_statement"}


def test_the_statement_set_is_pinned() -> None:
    # Self-discovering, so a builder added later cannot dodge the scoping test below.
    assert {n for n in vars(mod) if n.endswith("_statement")} == set(_STATEMENTS)


@pytest.mark.parametrize("name", sorted(_STATEMENTS))
def test_every_statement_but_create_and_the_id_check_is_account_scoped(name: str) -> None:
    """The entry-stop settle is scoped by its own table's account (E29-T04)."""
    sql = _sql(_STATEMENTS[name])
    scoped = "orders.exchange_account_id = $" in sql or (
        name == "settle_entry_stops_statement" and "recorded_stops.exchange_account_id = $" in sql
    )
    scoped |= name in _BY_PRINCIPAL and "user_account_access.user_id = $" in sql
    assert scoped is (name not in mod.UNSCOPED)


def test_the_exit_reads_hold_the_owner_or_the_grant_predicate_in_sql() -> None:
    """E29-T04 slice 4 (C-12.4): `scope_clause`, once: a live account of the environment, then a
    live owner role, or a grant among the snapshot's ids whose live row lets it view, unfrozen,
    and trade for the trade flag; the anchor read only for an order with no group (`coalesce`)."""
    live = "exchange_accounts.deleted_at IS NULL AND exchange_accounts.env = $"
    owner = _sql(mod.in_scope_statement(OwnerScope(USER), ORDER, "demo"))
    assert live in owner and "user_account_access" not in owner
    assert "WHERE user_roles.user_id = $" in owner and "roles.name = $" in owner
    grant = _sql(_STATEMENTS["in_scope_statement"])
    assert live in grant and "exchange_accounts.id IN ($" in grant and "user_roles" not in grant
    assert grant.count("user_account_access.can_view AND NOT user_account_access.frozen") == 2
    assert grant.count("user_account_access.can_trade") == 1  # the `can_trade` column alone
    assert "coalesce(trade_groups.created_by, (SELECT idempotency_anchors.created_by" in grant
    assert grant.endswith(") AS scoped ON true")
    nothing = _sql(mod.accounts_in_scope_statement(GrantScope(USER, frozenset()), "demo", ()))
    assert nothing.endswith("WHERE false ORDER BY exchange_accounts.id")


def test_only_the_insert_the_id_check_and_the_hydration_read_are_unscoped() -> None:
    """E29-T04's hydration read takes an environment (`test_oms_system_reads_callers.py`)."""
    hydration = {"environment_accounts_statement", "list_unfinished_statement"}
    assert mod.UNSCOPED == {"create_statement", "link_taken_statement"} | hydration
    assert _sql(_STATEMENTS["link_taken_statement"]).startswith("SELECT EXISTS (SELECT")


def test_the_hydration_read_takes_the_environments_accounts_and_the_unfinished_states() -> None:
    accounts = _sql(_STATEMENTS["environment_accounts_statement"])
    assert accounts.startswith("SELECT exchange_accounts.id \nFROM exchange_accounts \nWHERE")
    assert accounts.endswith("WHERE exchange_accounts.env = $1::exchange_env")  # no other filter
    sql = _sql(_STATEMENTS["list_unfinished_statement"])
    states = ", ".join(f"'{state}'" for state in sorted(port.UNFINISHED_STATES))
    assert f"orders.state IN ({states})" in sql and "'held'" in sql and "'untracked'" in sql
    assert "orders.exchange_account_id = ANY (CAST($1::TEXT[] AS UUID[]))" in sql
    assert sql.endswith("ORDER BY orders.created_ts, orders.id \n LIMIT $2::INTEGER")


async def test_list_unfinished_reads_no_orders_for_no_account_and_nothing_for_no_limit() -> None:
    rel = _Rel(_Result([]))
    assert await _store(rel).list_unfinished("live", limit=10) == ()
    assert len(rel.statements) == 1  # the accounts only
    with pytest.raises(ValueError, match="limit"):
        await _store(rel).list_unfinished("demo", limit=0)
    assert len(rel.units) == 1


def test_get_by_exchange_statement_binds_the_account_and_the_exact_exchange_id() -> None:
    """21 Sec.13.1 row 12: equality on the account and the id alone, whatever the order's state."""
    stmt = _STATEMENTS["get_by_exchange_statement"]
    where = _sql(stmt).split("\nWHERE ", 1)[1]
    assert "orders.exchange_account_id = $1::UUID" in where
    assert "orders.exchange_order_id = $2::VARCHAR" in where
    assert _bound(stmt) == [ACCOUNT, "x-1"]
    assert not any(part in where for part in ("LIKE", "lower(", "orders.state", " OR "))


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
def test_payload_ret_code_and_ret_msg_are_redacted_before_they_are_bound(name: str) -> None:
    bound = _bound(_STATEMENTS[name])
    assert {"headers": REDACTED, "result": {"orderId": "o-1"}} in bound
    assert "10004" in bound and REDACTED in bound  # the code kept, the echoing message replaced
    blob = json.dumps(bound, default=str)
    assert _MAC not in blob and _KEY not in blob


def test_an_overlong_ret_code_is_bound_as_oversize() -> None:
    event = _event(kind="reject", source="rest", ret_code="1" * (MAX_CODE_CHARS + 1))
    assert OVERSIZE in _bound(mod.append_statement(ACCOUNT, ORDER, event))


#: 18 letters alone, built at run time (SR-145): a key the general string rule keeps as a word.
_LETTERS = "".join(chr(ord("A") + 7 * i % 26) for i in range(18))
_REJECTED_TEXT = f"API key {_LETTERS} is invalid."
_AUTH_REJECT = _event(
    kind="reject",
    source="rest",
    ret_code="10003",
    ret_msg=_REJECTED_TEXT,
    payload={"retCode": 10003, "retMsg": _REJECTED_TEXT, "result": {}},
)


@pytest.mark.parametrize("name", ["create_statement", "append_statement"])
def test_a_letters_only_key_in_the_exchange_message_is_never_bound(name: str) -> None:
    """The message rule (21 Sec.3.3.5): `ret_msg` and the payload's message lose a run of letters
    alone, which the general rule would keep as a word; the code and the rest are kept."""
    stmt = (
        mod.create_statement(_new_order(), _AUTH_REJECT)
        if name == "create_statement"
        else mod.append_statement(ACCOUNT, ORDER, _AUTH_REJECT)
    )
    bound = _bound(stmt)
    assert _LETTERS not in json.dumps(bound, default=str)
    assert {"retCode": 10003, "retMsg": REDACTED, "result": {}} in bound
    assert "10003" in bound and REDACTED in bound


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


def test_a_step_is_a_compare_and_set_with_its_reject_redacted() -> None:
    """24 Sec.8.2 S7, S8: the UPDATE holds only on the expected state (a fill's, also only on the
    stored quantity plus its own); the reject echo is never bound (#845 decision 2)."""
    stmt = _STATEMENTS["transition_statement"]
    sql, bound, fill_sql = _sql(stmt), _bound(stmt), _sql(_STATEMENTS["fill_statement"])
    assert sql.startswith("UPDATE orders SET state=$1::order_state, reject_code=$2::VARCHAR, ")
    assert "orders.id = $5::UUID AND orders.state = $6::order_state RETURNING orders.id, " in sql
    assert bound[:3] + bound[5:] == ["rejected", "10004", REDACTED, "accepted"]
    held = "orders.state = $8::order_state AND orders.cum_exec_qty + $9::NUMERIC(38, 18) = $10"
    assert held in fill_sql and "cum_exec_value=$3" in fill_sql


@pytest.mark.parametrize(
    ("given", "stored"),
    [({"reject_code": _KEY}, REDACTED), ({"reject_code": "1" * (MAX_CODE_CHARS + 1)}, OVERSIZE),
     ({"reject_message": _REJECTED_TEXT}, REDACTED)],
)  # fmt: skip
def test_a_reject_is_redacted_like_ret_code_and_ret_msg(given: dict[str, Any], stored: str) -> None:
    """#845 decision 2: `reject_code` takes the string rule within 64 characters, and
    `reject_message` the message rule too (its 18 letters alone pass the string rule)."""
    said = replace(event(), **{_RET[name]: value for name, value in given.items()})
    moved = step(_HELD, "rejected", said, **given)
    assert moved.changes() == {"state": "rejected"} | dict.fromkeys(given, stored)
    assert _bound(mod.transition_statement(moved))[:2] == ["rejected", stored]


#: Each reject column and the event field it is (`OrderTransition`, OM-T03).
_RET = {"reject_code": "ret_code", "reject_message": "ret_msg"}


@pytest.mark.parametrize(
    ("to", "given", "said"),
    [("rejected", {"reject_code": "10004"}, {}),  # the column with no event field
     ("rejected", {"reject_message": "refused"}, {"ret_msg": "said otherwise"}),
     ("rejected", {}, {"ret_code": "10004"}),  # an event field with no column
     ("cancelled", {"reject_code": "10004"}, {"ret_code": "10004"})],  # not into rejected
)  # fmt: skip
def test_the_reject_columns_are_the_events_or_the_step_is_refused(
    to: Any, given: dict[str, Any], said: dict[str, Any]
) -> None:
    """OM-T03: a step into `rejected` names its event's `ret_code` and
    `ret_msg` as its reject columns, and no other step names any, before any statement; so a
    fold of the events rebuilds both columns."""
    with pytest.raises(ValueError, match="reject columns are its event's"):
        step(_HELD, to, replace(event(), **said), **given)


def test_the_bound_reject_columns_are_the_bound_event_fields() -> None:
    """OM-T03: the UPDATE binds the reject columns the event's insert binds as
    `ret_code` and `ret_msg`, each redacted alike (#845 decision 2)."""
    code, text = _KEY, _REJECTED_TEXT
    said_so = event(ret_code=code, ret_msg=text)
    moved = step(_HELD, "rejected", said_so, reject_code=code, reject_message=text)
    said = mod._event_values(moved.event)
    assert _bound(mod.transition_statement(moved))[1:3] == [said["ret_code"], said["ret_msg"]]
    assert (said["ret_code"], said["ret_msg"]) == (REDACTED, REDACTED)


@pytest.mark.parametrize(
    ("source", "expect"),
    [*((s, pytest.raises(ValueError, match="OM-R02")) for s in ("reconcile", "rest", "ws_private")),
     ("local", nullcontext()), ("paper", nullcontext())],
)  # fmt: skip
def test_only_a_step_the_exchange_reported_must_carry_its_message(source: Any, expect: Any) -> None:
    """OM-R02: a `rest`, `ws_private` or `reconcile` step carries what the exchange said (every
    source of the column is listed here, not read off `EXCHANGE_SOURCES`)."""
    with expect:
        step(_HELD, "accepted", event(source=source, payload={}))


#: Steps and fills no store may write; `draft` and `exec` are chart names no step column holds.
_ELSEWHERE = replace(_FILL.execution, exchange_account_id=uuid.UUID(int=9))
_UNWRITABLE: dict[str, tuple[Callable[[], object], type[Exception], str]] = {
    "unknown_state": (lambda: step(_HELD, cast(Any, "draft")), ValueError, "of their columns"),
    "unknown_from_state": (lambda: step(_HELD, "accepted", from_state=cast(Any, "draft")),
                           ValueError, "of their columns"),
    "unknown_kind": (lambda: step(_HELD, "accepted", event(cast(Any, "exec"))),
                     ValueError, "of their columns"),
    "unknown_source": (lambda: step(_HELD, "accepted", event(source=cast(Any, "bybit"))),
                       ValueError, "of their columns"),
    "another_order": (lambda: fill(_HELD, "E1", "0.1", order_id=ACCOUNT),
                      ValueError, "another account or order"),
    "another_account": (lambda: replace(_FILL, execution=_ELSEWHERE),
                        ValueError, "another account or order"),
    "fill_to_another_state": (lambda: fill(_HELD, "E1", "0.1", to_state="cancelled"),
                              ValueError, "partially_filled or filled"),
    "fill_by_another_kind": (lambda: fill(_HELD, "E1", "0.1", event("ack")),
                             ValueError, "partially_filled or filled"),
    "float_totals": (lambda: replace(_FILL.totals, fee_paid=cast(Any, 0.5)),
                     TypeError, "^fee_paid "),
}  # fmt: skip


@pytest.mark.parametrize("built", sorted(_UNWRITABLE))
def test_a_step_or_fill_no_column_holds_is_refused_as_it_is_built(built: str) -> None:
    """OM-T04: every store refuses it alike, before any statement."""
    build, error, match = _UNWRITABLE[built]
    with pytest.raises(error, match=match):
        build()


@pytest.mark.parametrize("state", ["triggered", "unknown", "quarantined", "killed", "held"])
def test_a_step_may_enter_each_state_0034_adds(state: Any) -> None:
    """OM-T04 reads `OrderState`, so each value `0034_order_vocabulary` adds is a step's new state
    like any other (the store checks vocabulary; legality is B1's)."""
    into = _bound(mod.transition_statement(step(_HELD, state)))
    assert (into[0], into[-1]) == (state, "accepted")


@pytest.mark.parametrize(
    ("state", "to_state"),
    [("triggered", "cancelled"), ("unknown", "cancelled"), ("quarantined", "cancelled"),
     ("held", "rejected")],
)  # fmt: skip
def test_a_step_may_leave_each_non_final_state_0034_adds(state: Any, to_state: Any) -> None:
    """Each of them but `killed` is also a step's compare-and-set state, left as B1 leaves it
    (`REMOTE_CANCELLED`, `RECON_FOUND_CANCELLED`, `OPERATOR_RESOLVED`). `killed` is final in B1,
    so no step leaves it (INV-2; 24 Sec.8.2 S6)."""
    out = _bound(mod.transition_statement(step(_HELD, to_state, from_state=state)))
    assert (out[0], out[-1]) == (to_state, state)


def test_a_fill_may_leave_triggered_the_one_added_state_with_an_exec_arm() -> None:
    """28 B1.3: `triggered` takes `EXEC` to `partially_filled` or `filled`, as `submitted` does."""
    triggered = cast(Any, SimpleNamespace(**(vars(_HELD) | {"state": "triggered"})))
    bound = _bound(mod.fill_statement(fill(triggered, "E1", "0.1")))
    assert bound[0] == "partially_filled" and bound.count("triggered") == 1


@pytest.mark.parametrize(
    ("kind", "source", "from_state", "to_state"),
    [("kill", "local", "pending_submit", "killed"),
     ("adopt", "reconcile", "untracked", "accepted")],
)  # fmt: skip
def test_a_step_may_carry_each_event_kind_0034_adds(
    kind: Any, source: Any, from_state: str, to_state: Any
) -> None:
    """B1's `KILL` from `validated` and `ADOPT` from `untracked`, in their persisted states."""
    moved = step(_HELD, to_state, event(kind, source=source), from_state=from_state)
    assert kind in _bound(mod.append_statement(ACCOUNT, ORDER, moved.event))


@pytest.mark.parametrize(
    ("qty", "paper", "reason"),
    [("0.09", False, "above_qty"), ("0.3", True, "paper_mismatch"),
     ("0.1", False, "state_mismatch")],
)  # fmt: skip
def test_a_fill_its_locked_order_cannot_take_is_refused(qty: str, paper: bool, reason: str) -> None:
    """OM-T04: `_FILL` takes 0.1 to `partially_filled` on a live order of a held `qty`."""
    with pytest.raises(FillRefused, match=reason) as err:
        _FILL.check(Decimal(qty), paper)
    assert (err.value.order_id, err.value.reason) == (ORDER, reason)


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
    """Scripted `SqlAlchemyRelationalRepository`: records statements, replays canned results.

    `units` keeps every unit of work's `(statement, params)` in order; the store's statement cap
    (the one text clause) is answered without consuming the script and kept out of `statements`.
    """

    def __init__(self, *script: _Result | BaseException) -> None:
        self.script: list[_Result | BaseException] = list(script)
        self.statements: list[Any] = []
        self.units: list[list[tuple[Any, Any]]] = []
        self.commits = 0

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        unit: list[tuple[Any, Any]] = []
        self.units.append(unit)

        async def execute(stmt: Any, params: Any = None) -> _Result:
            unit.append((stmt, params))
            if isinstance(stmt, TextClause):
                return _Result()
            self.statements.append(stmt)
            step = self.script.pop(0)
            if isinstance(step, BaseException):
                raise step
            return step

        async def commit() -> None:
            self.commits += 1

        yield SimpleNamespace(session=SimpleNamespace(execute=execute), commit=commit)


def _store(rel: _Rel, **kwargs: Any) -> mod.SqlAlchemyOrderStore:
    return mod.SqlAlchemyOrderStore(cast(Any, rel), **kwargs)  # structural fake


def _order_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {f.name: None for f in fields(OrderRow)}
    row |= {"id": ORDER, "exchange_account_id": ACCOUNT, "order_link_id": LINK, "qty": Decimal(1)}
    return row | over


def _event_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {name: None for name in EVENT_FIELDS}
    return row | {"id": 7, "order_id": ORDER, "seq": 1, "kind": "ack", "payload": {}} | over


_GROUP, _PROFILE = uuid.UUID(int=4), uuid.UUID(int=5)


def _scoped_row(**over: Any) -> dict[str, Any]:
    """`in_scope_statement`'s one row for `_order_row`'s order in the scope: the probe's `holder`
    beside the order, its group, its leg's profile, its creator and the trade flag."""
    judged = {"trade_group_id": _GROUP, "profile_id": _PROFILE, "created_by": USER}
    return _order_row() | judged | {"can_trade": True, "holder": ACCOUNT} | over


async def test_create_maps_the_returned_row_and_commits_once() -> None:
    rel = _Rel(_Result([_order_row(stop_loss=Decimal("62000"), tpsl_mode="Partial")]))
    row = await _store(rel).create(_new_order(), _event())
    assert (row.order_link_id, row.stop_loss, row.tpsl_mode) == (LINK, Decimal("62000"), "Partial")
    assert (rel.commits, len(rel.statements)) == (1, 1)


async def test_reads_map_rows_and_absence() -> None:
    rel = _Rel(
        _Result([_order_row()]), _Result(), _Result([_order_row(), _order_row()]), _Result(),
        _Result(scalar=True), _Result([_event_row(seq=4, order_link_id=LINK)]),
        _Result([_order_row(exchange_order_id="x-1")]), _Result(),
    )  # fmt: skip
    store = _store(rel)
    assert (await store.get(ACCOUNT, ORDER)) == OrderRow(**_order_row())
    assert await store.get_by_link_id(ACCOUNT, LINK) is None
    assert len(await store.list_open(ACCOUNT, symbol="BTCUSDT")) == 2
    assert await store.list_open(ACCOUNT) == ()
    assert await store.link_id_taken(LINK) is True
    (event,) = await store.list_for_order(ACCOUNT, ORDER, after_seq=3, limit=1)
    assert (event.seq, rel.commits) == (4, 0)
    bound = await store.get_by_exchange_order_id(ACCOUNT, "x-1")
    assert bound == OrderRow(**_order_row(exchange_order_id="x-1"))
    assert await store.get_by_exchange_order_id(ACCOUNT, "x-2") is None and rel.commits == 0


@pytest.mark.parametrize("trade", [True, False], ids=["trade", "view-only"])
async def test_get_in_scope_maps_a_scoped_row_to_the_order_and_what_it_is_judged_by(
    trade: bool,
) -> None:
    """Rulings Q6 and Q7: the order with its group, its leg's profile, its creator and whether the
    scope may trade its account, read in one statement and committing nothing."""
    rel = _Rel(_Result([_scoped_row(can_trade=trade)]))
    got = await _store(rel).get_in_scope(_GRANT, ORDER, environment="demo")
    assert got == port.ScopedOrder(OrderRow(**_order_row()), _GROUP, _PROFILE, USER, trade)
    assert (len(rel.statements), rel.commits) == (1, 0)


@pytest.mark.parametrize("holder", [ACCOUNT, None], ids=["outside-the-scope", "missing"])
async def test_get_in_scope_maps_no_scoped_row_to_the_holding_account_alone(holder: Any) -> None:
    """Ruling Q12: for an id outside the scope every scoped column is NULL and only the probe's
    `holder` comes back, None for an id no order holds; both answer the same 404 (SR-E29-13)."""
    rel = _Rel(_Result([dict.fromkeys(_scoped_row()) | {"holder": holder}]))
    got = await _store(rel).get_in_scope(_GRANT, ORDER, environment="demo")
    assert got == port.OutOfScope(holder)


def test_a_scope_refusal_of_the_account_set_is_no_store_failure() -> None:
    """SR-E29-13: an account the request names outside the scope refuses the whole set, the
    caller's scope and never an outage: no `OrderStoreError`, which the OMS reads as a store that
    did not serve (24 Sec.8.2 S7), so no caller answers it `503` in place of its `403`."""
    with pytest.raises(port.AccountsOutOfScope) as refused:
        port.settle_accounts([ACCOUNT], [ACCOUNT, ORDER])
    assert not isinstance(refused.value, port.OrderStoreError)


@pytest.mark.parametrize("text", [None, "", "x" * 65], ids=["none", "empty", "overlong"])
async def test_a_read_by_an_exchange_order_id_no_order_can_hold_runs_no_statement(
    text: Any,
) -> None:
    rel = _Rel()
    with pytest.raises(ValueError, match="1 to 64 characters"):
        await _store(rel).get_by_exchange_order_id(ACCOUNT, text)
    assert rel.units == []


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


_LOCKED = _Result([{"qty": Decimal("0.3"), "is_paper": False}])  # `lock_order` reads `_HELD`
_TAKEN = _Result([SimpleNamespace(order_id=ORDER)])  # a fill's insert took a row
_CAS, _EVENT = _Result([_order_row()]), _Result([_event_row()])
_FILL_SCRIPT = [_LOCKED, _TAKEN, _CAS, _EVENT]  # what one `commit_fill` of `_FILL` reads
_Step = tuple[Callable[[_Rel], Awaitable[Any]], list[_Result], str, str]
_STEPS: dict[str, _Step] = {  # a step: its call, script, statements it runs, event's `to_state`
    "transition": (lambda r: _store(r).transition(_STEP), [_LOCKED, _CAS], "UPDATE", "rejected"),
    "commit_fill": (
        lambda rel: ex.SqlAlchemyExecutionStore(cast(Any, rel)).commit_fill(_FILL),
        [_LOCKED, _TAKEN, _CAS], "INSERT UPDATE", "partially_filled",
    ),
}  # fmt: skip


@pytest.mark.parametrize("call", sorted(_STEPS))
async def test_a_step_locks_its_order_then_writes_and_commits_once(call: str) -> None:
    """24 Sec.8.2 S8: the step's event, with both states, commits with its compare-and-set."""
    run, script, verbs, to_state = _STEPS[call]
    rel = _Rel(*script, _EVENT)
    done = await run(rel)
    assert (done.order.order_link_id, done.event.order_link_id, rel.commits) == (LINK, LINK, 1)
    assert [_sql(stmt).split()[0] for stmt in rel.statements] == f"SELECT {verbs} INSERT".split()
    assert _sql(rel.statements[0]).startswith("SELECT orders.order_link_id, orders.qty, orders.is_")
    assert _bound(rel.statements[-1])[6:8] == ["accepted", to_state]


_STALE = {"order_id": ORDER, "expected": "accepted"}  # the state the step expected, not its own
_ABOVE = {"order_id": ORDER, "reason": "above_qty"}


@pytest.mark.parametrize(
    ("call", "script", "error", "named"),
    [
        ("transition", [_Result()], OrderNotFoundError, {}),
        ("transition", [_LOCKED, _Result()], StaleOrderState, _STALE),
        ("commit_fill", [_Result([{"qty": Decimal(0), "is_paper": False}]), _TAKEN],
         FillRefused, _ABOVE),
        ("commit_fill", [_LOCKED, _TAKEN, _Result()], StaleOrderState, _STALE),  # rolled back
    ],
)  # fmt: skip
async def test_a_refused_step_writes_nothing(
    call: str, script: list[_Result], error: type, named: dict[str, object]
) -> None:
    """S7, and the error names what slice 6 reads to choose its audit record and code."""
    rel = _Rel(*script)
    with pytest.raises(error) as err:
        await _STEPS[call][0](rel)
    assert (len(rel.statements), rel.commits) == (len(script), 0)
    assert {name: getattr(err.value, name) for name in named} == named


@pytest.mark.parametrize(
    "write",
    [lambda st: st.transition(step(_HELD, "filled")),  # a fill comes with its execution
     lambda st: st.transition(step(_HELD, "partially_filled", event("partial_fill"))),
     lambda st: st.append(ACCOUNT, ORDER, event("fill")),  # nor appended without it
     lambda st: st.append(ACCOUNT, ORDER, event("partial_fill")),
     lambda st: st.create(_new_order(), _event(source="reconcile"))],  # without its message
)  # fmt: skip
async def test_a_write_refused_as_it_starts_opens_no_unit(write: Any) -> None:
    rel = _Rel()
    with pytest.raises(ValueError, match=r"commit_fill|OM-R02"):
        await write(_store(rel))
    assert rel.units == []


async def test_a_duplicate_fill_is_none_and_commits_nothing() -> None:
    """S4 before OM-T04: a duplicate is no refusal, though its order would refuse it as new."""
    rel = _Rel(_Result([{"qty": Decimal(0), "is_paper": True}]), _Result())  # no row inserted
    assert await _STEPS["commit_fill"][0](rel) is None
    assert (len(rel.statements), rel.commits) == (2, 0)


_CAP = "SELECT set_config('statement_timeout', :timeout, true)"
#: Every store call, with the script one call consumes.
_CALLS: dict[str, tuple[Callable[[mod.SqlAlchemyOrderStore], Awaitable[object]], list[_Result]]] = {
    "create": (lambda st: st.create(_new_order(), _event()), [_Result([_order_row()])]),
    "get": (lambda st: st.get(ACCOUNT, ORDER), [_Result()]),
    "get_by_link_id": (lambda st: st.get_by_link_id(ACCOUNT, LINK), [_Result()]),
    "get_by_exchange_order_id": (lambda st: st.get_by_exchange_order_id(ACCOUNT, "x"), [_Result()]),
    "list_open": (lambda st: st.list_open(ACCOUNT), [_Result()]),
    "link_id_taken": (lambda st: st.link_id_taken(LINK), [_Result(scalar=False)]),
    "append": (
        lambda st: st.append(ACCOUNT, ORDER, _event(kind="ack", source="rest")),
        [_Result(scalar=LINK), _Result([_event_row()])],
    ),
    "list_for_order": (lambda st: st.list_for_order(ACCOUNT, ORDER), [_Result()]),
    "list_unfinished": (
        lambda st: st.list_unfinished("demo", limit=10),
        [_Result([{"id": ACCOUNT}]), _Result([_order_row(state="held")])],
    ),
    "environment_accounts": (
        lambda st: st.environment_accounts("demo"),
        [_Result([{"id": ACCOUNT}])],
    ),
    "transition": (lambda st: st.transition(_STEP), [_LOCKED, _CAS, _EVENT]),
    "get_in_scope": (
        lambda st: st.get_in_scope(_GRANT, ORDER, environment="demo"),
        [_Result([_scoped_row()])],
    ),
    "accounts_in_scope": (
        lambda st: st.accounts_in_scope(_GRANT, "demo", ()),
        [_Result([{"id": ACCOUNT}])],
    ),
}


@pytest.mark.parametrize("call", sorted(_CALLS))
@pytest.mark.parametrize(("kwargs", "cap"), [({}, "2000"), ({"statement_timeout_ms": 150}, "150")])
async def test_every_call_is_one_unit_of_work_capped_first_at_the_store_timeout(
    call: str, kwargs: dict[str, int], cap: str
) -> None:
    """The cap precedes the call's own statements (#845 default 2000 ms), so a write blocked on a
    lock fails within it instead of the repository-wide 30 s."""
    run, script = _CALLS[call]
    rel = _Rel(*script)
    await run(_store(rel, **kwargs))
    assert [(str(stmt), params) for stmt, params in (unit[0] for unit in rel.units)] == [
        (_CAP, {"timeout": cap})
    ]


@pytest.mark.parametrize("timeout_ms", [0, -1, True, 1.5, "2000"])
def test_a_statement_timeout_that_is_not_a_positive_int_is_refused(timeout_ms: Any) -> None:
    """0 would switch the cap off in Postgres."""
    with pytest.raises(ValueError, match="statement_timeout_ms"):
        _store(_Rel(), statement_timeout_ms=timeout_ms)


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


@pytest.mark.parametrize(
    "read",
    ["get", "get_by_link_id", "get_by_exchange_order_id", "link_id_taken", "list_for_order",
     "list_open", "list_unfinished", "environment_accounts", "get_in_scope", "accounts_in_scope"],
)  # fmt: skip
async def test_a_failed_read_keeps_only_its_sqlstate_like_a_write(read: str) -> None:
    """One error family for the OMS (24 Sec.8.2 S7): the allocator's lookup and every other read
    raise `StorageQueryFailed` when a statement fails (57014: the cap), as the writes do."""
    rel = _Rel(_leaky(OperationalError, "57014"))
    with pytest.raises(StorageQueryFailed) as err:
        await _CALLS[read][0](_store(rel))
    assert err.value.sqlstate == "57014"
    assert (err.value.__cause__, err.value.__suppress_context__) == (None, True)
    assert _P1 not in "".join(traceback.format_exception(err.value))


def test_a_violation_named_on_the_driver_error_itself_is_read_too() -> None:
    orig = _PgError("23505")
    cast(Any, orig).constraint_name = "ux_orders_exch_id"
    assert mod._violated_constraint(DBAPIError("stmt", {}, orig)) == "ux_orders_exch_id"


class _Checkout:
    """A unit of work whose connection checkout fails, as the pool's or the driver's does."""

    def __init__(self, error: BaseException) -> None:
        self._error = error

    async def __aenter__(self) -> Any:
        raise self._error

    async def __aexit__(self, *exc: object) -> None:
        return None


class _Down:
    """A relational repository that cannot hand out a connection."""

    def __init__(self, error: BaseException) -> None:
        self.error = error

    def unit_of_work(self) -> _Checkout:
        return _Checkout(self.error)


_PEER = "('127.0.0.1', 1)"  # what a driver error names; it must not leave the store
#: What the driver and the pool raise when Postgres cannot be reached (none is a `DBAPIError`).
_UNREACHABLE: dict[str, Callable[[], BaseException]] = {
    "refused": lambda: ConnectionRefusedError(111, f"Connect call failed {_PEER}"),
    "connect_timeout": lambda: TimeoutError(f"connect to {_PEER} timed out"),
    "dns": lambda: socket.gaierror(-2, f"Name or service not known {_PEER}"),
    "pool": lambda: PoolTimeoutError(f"QueuePool limit of size 10 reached {_PEER}"),
}


@pytest.mark.parametrize("call", sorted(_CALLS))
@pytest.mark.parametrize("error", sorted(_UNREACHABLE))
async def test_an_unreachable_database_is_tier_unavailable_unchained(call: str, error: str) -> None:
    """24 Sec.8.2 S7: no connection, for every call, is `StorageTierUnavailable`; the driver's
    error, which names the peer, is not chained."""
    exc = _UNREACHABLE[error]()
    with pytest.raises(StorageTierUnavailable) as err:
        await _CALLS[call][0](_store(cast(Any, _Down(exc))))
    assert str(err.value) == f"postgres unreachable ({type(exc).__name__})"
    assert (err.value.__cause__, err.value.__suppress_context__) == (None, True)
    assert _PEER not in "".join(traceback.format_exception(err.value))


@pytest.mark.parametrize("write", sorted(_WRITES))
@pytest.mark.parametrize(
    ("invalidated", "sqlstate"), [(True, "08003"), (True, None), (False, "08006")]
)
async def test_a_connection_lost_mid_write_is_tier_unavailable_and_commits_nothing(
    write: str, invalidated: bool, sqlstate: str | None
) -> None:
    """asyncpg reports a connection lost mid-statement as a `DBAPIError` that SQLAlchemy marks
    `connection_invalidated`, SQLSTATE 08003: Postgres is unavailable (24 Sec.8.2 S7)."""
    orig = _PgError(sqlstate, message=f"connection was closed in the middle of operation {_PEER}")
    rel = _script(write, DBAPIError("stmt", {"p": _P1}, orig, connection_invalidated=invalidated))
    with pytest.raises(StorageTierUnavailable) as err:
        await _WRITES[write](_store(rel))
    assert (str(err.value), rel.commits) == ("postgres unreachable (DBAPIError)", 0)
    assert (err.value.__cause__, err.value.__suppress_context__) == (None, True)
    assert _PEER not in "".join(traceback.format_exception(err.value))


#: Where a database error meets the store: when it connects, or on its first statement.
_SITES: dict[str, Callable[[BaseException], object]] = {"checkout": _Down, "statement": _Rel}


@pytest.mark.parametrize("call", sorted(_CALLS))
@pytest.mark.parametrize("sqlstate", ["57P01", "57P02", "57P03", "53300"])
@pytest.mark.parametrize("site", sorted(_SITES))
async def test_a_server_that_does_not_serve_is_tier_unavailable_unchained(
    call: str, sqlstate: str, site: str
) -> None:
    """Shut down (57P01, 57P02), starting up (57P03) or out of connection slots (53300): a
    connection the store cannot get or keep, so Postgres is unavailable (24 Sec.8.2 S7), not a
    failed statement, for every call."""
    rel = _SITES[site](_leaky(OperationalError, sqlstate))
    with pytest.raises(StorageTierUnavailable) as err:
        await _CALLS[call][0](_store(cast(Any, rel)))
    assert str(err.value) == "postgres unreachable (OperationalError)"
    assert (err.value.__cause__, err.value.__suppress_context__) == (None, True)
    assert _P1 not in "".join(traceback.format_exception(err.value))


@pytest.mark.parametrize("call", ["append", "get"])
async def test_cancellation_passes_through_the_error_mapping(call: str) -> None:
    """An `asyncio.timeout` around a call cancels it inside the store: the cancellation must leave
    as `CancelledError`, never as a storage error (20-python-backend: honour cancellation)."""
    script = [_Result(scalar=LINK)] if call == "append" else []
    rel = _Rel(*script, asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await _CALLS[call][0](_store(rel))
    assert rel.commits == 0


# -- E29-T04: the send's attempt count and the entry's recorded stops ------------------------------


def test_the_sends_step_counts_an_attempt_from_the_stored_count() -> None:
    sent = step(_HELD, "submitted", bump_submit_attempts=True, idempotency_state="in_flight")
    sql = _sql(mod.transition_statement(sent))
    assert "submit_attempts=(orders.submit_attempts + $" in sql
    assert "idempotency_state=$" in sql
    plain = _sql(mod.transition_statement(step(_HELD, "submitted")))
    assert "submit_attempts=" not in plain.split(" RETURNING ", 1)[0]  # only the send counts


@pytest.mark.parametrize(
    ("over", "rule"),
    [
        ({"bump_submit_attempts": True}, "only the send's step"),
        ({"idempotency_state": "lost"}, "ord_idem"),
        ({"entry_stops": "ended"}, "answered or void"),
    ],
)
def test_a_step_names_only_values_its_columns_and_rules_take(
    over: dict[str, Any], rule: str
) -> None:
    with pytest.raises(ValueError, match=rule):
        step(_HELD, "cancelled", **over)


@pytest.mark.parametrize(
    ("settle", "sets", "only"),
    [
        ("answered", "answered_at=$1::TIMESTAMP WITH TIME ZONE", "answered_at IS NULL"),
        ("void", "status=$1::VARCHAR, closed_at=$2::TIMESTAMP WITH TIME ZONE", None),
    ],
)
def test_the_settle_touches_only_the_orders_pending_entry_rows(
    settle: Any, sets: str, only: str | None
) -> None:
    sql = " ".join(_sql(mod.settle_entry_stops_statement(ACCOUNT, ORDER, settle, T0)).split())
    assert sql.startswith("UPDATE recorded_stops SET ")
    assert sql.split(" SET ", 1)[1].split(" WHERE ", 1)[0] == sets
    where = sql.split(" WHERE ", 1)[1]
    for term in ("exchange_account_id = $", "order_id = $", "source = $", "status = $"):
        assert f"recorded_stops.{term}" in where
    assert (only is not None and f"recorded_stops.{only}" in where) or "answered_at" not in where


#: SEC-2A-01: the void's own check that its order holds no recorded fill.
_NO_FILL = (
    "NOT (EXISTS (SELECT $7::INTEGER AS anon_1 FROM orders WHERE orders.id = "
    "recorded_stops.order_id AND orders.cum_exec_qty > $8::INTEGER))"
)


@pytest.mark.parametrize("settle", ["answered", "void"])
def test_a_void_never_meets_a_fill_its_order_holds(settle: Any) -> None:
    """Belt and braces under the step's rule (SEC-2A-01): only the void needs it, the answer may
    meet a fill, and the bound is zero."""
    stmt = mod.settle_entry_stops_statement(ACCOUNT, ORDER, settle, T0)
    sql = " ".join(_sql(stmt).split())
    assert sql.endswith(f" AND {_NO_FILL}") is (settle == "void")
    assert ("EXISTS" in sql) is (settle == "void")
    if settle == "void":
        assert _bound(stmt)[-2:] == [1, 0]  # SELECT 1 ... cum_exec_qty > 0


async def test_a_step_settles_its_entry_stops_in_its_own_transaction() -> None:
    """R10: after the compare-and-set and the event, before the one commit, so the void's own
    check (SEC-2A-01) reads the totals this step wrote."""
    rel = _Rel(_LOCKED, _CAS, _EVENT, _Result())
    move = step(_HELD, "cancelled", entry_stops="void")
    await _store(rel).transition(move)
    verbs = [_sql(stmt).split()[:2] for stmt in rel.statements]
    assert verbs == [["SELECT", "orders.order_link_id,"], ["UPDATE", "orders"],
                     ["INSERT", "INTO"], ["UPDATE", "recorded_stops"]]  # fmt: skip
    assert rel.commits == 1
    assert move.event.event_ts in _bound(rel.statements[-1])  # the step's own time
    assert _NO_FILL in " ".join(_sql(rel.statements[-1]).split())
