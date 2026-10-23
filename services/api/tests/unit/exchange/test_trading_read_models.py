"""The neutral read models of `TradingPort` (G-8, #2877; 24 §8.1 and §14.4), and the private
stream's events and statuses (G-8b, #3963; 24 §14.2 rule 13).

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
from candleviewer.exchange.base.models import (
    PRIVATE_STREAM_REASONS,
    ExchangeRecord,
    ExecType,
    Execution,
    FastExecution,
    Order,
    Position,
    PrivateEvent,
    PrivateKind,
    PrivateStreamReason,
    PrivateStreamState,
    PrivateStreamStatus,
    Wallet,
)

ACCOUNT = AccountId(UUID("5b1c9d2e-7f30-4a6b-8c4d-2e3f4a5b6c7d"))
OTHER = AccountId(UUID("6c2d0e3f-8041-4b7c-9d5e-3f4a5b6c7d8e"))
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


def test_an_order_is_not_exchange_placed_unless_a_read_says_so() -> None:
    """24 §8.10 (E29-T05's contract): a bool, false by default, so an order no adapter has
    mapped as the exchange's own freezes like any other (SR-E27-19). Only a bool is taken."""
    assert _order().exchange_placed is False
    assert _order(exchange_placed=True).exchange_placed is True
    with pytest.raises(ValidationError):
        _order(exchange_placed="maybe")


def _fast(**fields: Any) -> FastExecution:
    base: dict[str, Any] = {
        "exec_id": "x-1", "exchange_order_id": "e-1", "order_link_id": "ext-" + "0" * 32,
        "account_id": ACCOUNT, "symbol": "BTCUSDT", "side": "sell", "price": Decimal("60000"),
        "qty": Decimal("1"), "is_maker": False, "ts_exec": T0,
    }  # fmt: skip
    return FastExecution.model_validate(base | fields)


def _position(account_id: AccountId = ACCOUNT) -> Position:
    return Position(
        account_id=account_id, symbol="BTCUSDT", position_idx=0, side=None, qty=Decimal(0),
        avg_entry_price=None, mark_price=None, liq_price=None, leverage=Decimal("10"),
        unrealised_pnl=Decimal(0), cum_realised_pnl=Decimal(0), take_profit=None,
        stop_loss=None, trailing_stop_distance=None, updated_at=T0,
    )  # fmt: skip


def _wallet() -> Wallet:
    zero = Decimal(0)
    return Wallet(
        account_id=ACCOUNT, equity=zero, wallet_balance=zero, available_to_withdraw=None,
        available_margin=zero, used_margin=zero, unrealised_pnl=zero, cum_realised_pnl=zero,
        account_im_rate=zero, account_mm_rate=zero, updated_at=T0,
    )  # fmt: skip


PAYLOADS: dict[str, Any] = {
    "order": _order(),
    "execution": _execution(),
    "execution_fast": _fast(),
    "position": _position(),
    "wallet": _wallet(),
}
RECORD = ExchangeRecord(transport="ws_private", topic="order.linear")


def _event(kind: str, payload: Any, **fields: Any) -> PrivateEvent:
    base = {"kind": kind, "account_id": ACCOUNT, "payload": payload, "ts_event": T0}
    return PrivateEvent.model_validate(base | {"ts_ingest": T0} | fields)


def test_every_private_kind_carries_its_own_payload_type() -> None:
    assert set(PAYLOADS) == set(get_args(PrivateKind.__value__))
    for kind, payload in PAYLOADS.items():
        assert _event(kind, payload).payload is payload
        for other, wrong in PAYLOADS.items():
            if other != kind:
                with pytest.raises(ValidationError, match="not of the event's kind"):
                    _event(kind, wrong)


def test_a_private_event_refuses_a_payload_of_another_account() -> None:
    """SR-E29-02: the event and its payload both name the stream's account."""
    with pytest.raises(ValidationError, match="another account's"):
        _event("position", _position(OTHER))


@pytest.mark.parametrize("kind", ["order", "execution", "execution_fast"])
def test_an_order_or_execution_event_may_carry_its_record(kind: str) -> None:
    assert _event(kind, PAYLOADS[kind], record=RECORD).record == RECORD


@pytest.mark.parametrize("kind", ["position", "wallet"])
def test_a_position_or_wallet_event_carries_no_record(kind: str) -> None:
    with pytest.raises(ValidationError, match="only an order or execution event"):
        _event(kind, PAYLOADS[kind], record=RECORD)


def test_a_private_events_seq_and_record_are_optional() -> None:
    """Order and wallet pushes carry no sequence (24 §14.4): `seq` is `None` where it has none."""
    event = _event("order", PAYLOADS["order"])
    assert (event.seq, event.record) == (None, None)
    assert _event("execution", PAYLOADS["execution"], seq=7).seq == 7
    assert _fast().seq is None and _fast(seq=4).seq == 4


@pytest.mark.parametrize("exchange_order_id", ["", None, "e" * 65])
def test_a_fast_execution_without_the_exchanges_order_id_is_refused(
    exchange_order_id: object,
) -> None:
    with pytest.raises(ValidationError):
        _fast(exchange_order_id=exchange_order_id)


def test_each_status_reason_belongs_to_exactly_one_state() -> None:
    states = get_args(PrivateStreamState.__value__)
    reasons = get_args(PrivateStreamReason.__value__)
    assert set(PRIVATE_STREAM_REASONS) == set(states)
    owned = [r for group in PRIVATE_STREAM_REASONS.values() for r in group]
    assert sorted(owned) == sorted(reasons)  # every reason once, none outside the set
    for state, group in PRIVATE_STREAM_REASONS.items():
        for reason in reasons:
            fields = {"account_id": ACCOUNT, "state": state, "reason": reason, "epoch": 0}
            if reason in group:
                assert PrivateStreamStatus.model_validate(fields | {"ts": T0}).reason == reason
            else:
                with pytest.raises(ValidationError, match="not one of its state's"):
                    PrivateStreamStatus.model_validate(fields | {"ts": T0})


def test_a_status_epoch_is_never_negative() -> None:
    with pytest.raises(ValidationError):
        PrivateStreamStatus(
            account_id=ACCOUNT, state="down", reason="socket_closed", epoch=-1, ts=T0
        )
