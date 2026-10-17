"""Order store port, without a database (E29-T01 #845 slice 2/3).

The port is pinned to `0029_oms_core` (enums, CHECK vocabularies, `ix_orders_open`, the column
lists, the money and time columns `NewOrder` checks). The Postgres adapter's tests join this file
with the adapter.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import fields
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, get_args

import pytest
from sqlalchemy import CheckConstraint, DateTime, Numeric

from candleviewer.db import models
from candleviewer.storage.repositories import orders as port
from candleviewer.storage.repositories.orders import (
    EVENT_FIELDS,
    OPEN_STATES,
    NewOrder,
    NewOrderEvent,
    OrderConstraintError,
    OrderEventRow,
    OrderRow,
    require_aware,
    require_money,
)

T0 = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
ACCOUNT, ORDER = uuid.UUID(int=1), uuid.UUID(int=2)
LINK = "cvl-0TLr6mSAQFGvyfsJ0nLDCh-d0hb-00en"  # the #845 Gherkin id


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
        c
        for c in table.constraints
        if isinstance(c, CheckConstraint) and isinstance(c.name, str) and c.name.endswith(check)
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
