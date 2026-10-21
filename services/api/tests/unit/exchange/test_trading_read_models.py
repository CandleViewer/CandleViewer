"""The neutral read models of `TradingPort` (G-8, #2877; 24 §8.1 and §14.4).

`Execution` follows 24 §8.1: it names the exchange order it fills (`exchange_order_id`, never
empty), and its `exec_type` and `fee_rate` are what `21-database-schema.md` §3.3.6 stores (the
`ex_type` CHECK, numeric(18,10)). Every `Order` a read returns carries the exchange's id too
(the orchestrator's ruling 3 on #3972). A model the parser could not fill refuses, so no read
returns an order or an execution the OMS could not bind, pair or store.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, get_args
from uuid import UUID

import pytest
from pydantic import ValidationError

from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.models import ExecType, Execution, Order

ACCOUNT = AccountId(UUID("5b1c9d2e-7f30-4a6b-8c4d-2e3f4a5b6c7d"))
T0 = 1_790_000_000_000_000
#: `21-database-schema.md` §3.3.6, `CONSTRAINT ex_type`, as `exec_type` spells each value.
STORED = ("Trade", "AdlTrade", "Funding", "BustTrade", "Settle", "SessionSettlePnl")


def _execution(**fields: Any) -> Execution:
    base: dict[str, Any] = {
        "exec_id": "x-1", "exchange_order_id": "e-1", "order_link_id": "ext-" + "0" * 32,
        "account_id": ACCOUNT, "symbol": "BTCUSDT", "side": "buy", "price": Decimal("60000"),
        "qty": Decimal("1"), "fee": Decimal("0.1"), "fee_rate": Decimal("0.00055"),
        "fee_currency": "USDT", "is_maker": False, "exec_type": "trade", "closed_pnl": None,
        "ts_exec": T0, "ts_ingest": T0, "seq": 1,
    }  # fmt: skip
    return Execution.model_validate(base | fields)


def test_exec_type_is_21s_stored_set_in_the_neutral_spelling() -> None:
    snake = {"".join(f"_{c.lower()}" if c.isupper() else c for c in v).lstrip("_") for v in STORED}
    assert set(get_args(ExecType.__value__)) == snake


def test_an_execution_carries_its_order_id_type_and_fee_rate() -> None:
    fill = _execution()
    assert (fill.exchange_order_id, fill.exec_type, fill.fee_rate) == (
        "e-1",
        "trade",
        Decimal("0.00055"),
    )


@pytest.mark.parametrize(
    "fields",
    [
        {"exchange_order_id": ""},
        {"exchange_order_id": None},
        {"exchange_order_id": "e" * 65},
        {"exec_type": "block_trade"},
        {"exec_type": "Trade"},
        {"fee_rate": Decimal("0.00000000001")},
        {"fee_rate": Decimal("123456789")},
    ],
    ids=[
        "empty-order-id",
        "no-order-id",
        "order-id-past-64",
        "type-21-does-not-store",
        "venue-spelling",
        "fee-rate-eleven-places",
        "fee-rate-nine-whole-digits",
    ],
)
def test_an_execution_refuses_what_it_could_not_pair_or_store(fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _execution(**fields)


def test_an_execution_without_its_order_id_is_refused() -> None:
    base = _execution().model_dump()
    del base["exchange_order_id"]
    with pytest.raises(ValidationError):
        Execution.model_validate(base)


def _order(**fields: Any) -> Order:
    base: dict[str, Any] = {
        "order_link_id": "ext-" + "0" * 32, "exchange_order_id": "e-1", "account_id": ACCOUNT,
        "symbol": "BTCUSDT", "side": "buy", "order_type": "limit", "qty": Decimal("1"),
        "price": Decimal("60000"), "state": "new", "filled_qty": Decimal(0),
        "leaves_qty": Decimal("1"), "avg_fill_price": None, "created_at": T0,
        "terminal_at": None,
    }  # fmt: skip
    return Order.model_validate(base | fields)


@pytest.mark.parametrize("exchange_order_id", ["", None, "e" * 65])
def test_an_order_without_the_exchanges_id_is_refused(exchange_order_id: object) -> None:
    assert _order().exchange_order_id == "e-1"
    with pytest.raises(ValidationError):
        _order(exchange_order_id=exchange_order_id)
