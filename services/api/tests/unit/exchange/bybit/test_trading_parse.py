"""Strict-model unit tests of the trading parsers (G-8, #2877; E8-8, rulings R7 and R12).

Inputs here are unit inputs built from the documented field names, never presented as venue
evidence (ruling R2): the transcribed replies are parsed in `test_contract_trading.py`. They cover
what no transcription shows: refused types, bounds, unknown fields, the per-row owner check and
the shapes the documentation gives no example of (a Partial-mode stop row, a linear position, a
USDT wallet row, a derivatives fee-rate row).
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.domain.order_link import ext_key
from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.errors import UnknownStateError
from candleviewer.exchange.base.models import ClosedPnl, Execution, Order, Position, Wallet
from candleviewer.exchange.bybit import trading_parse as tp
from candleviewer.exchange.bybit.metrics import cv_bybit_unknown_fields_total
from tests.unit.exchange.bybit._trading import ACCOUNT_B, account, link

T_MS = "1700000000000"


def _row(**fields: Any) -> dict[str, Any]:
    """A unit input with every field the order parser reads (names as documented)."""
    base: dict[str, Any] = {
        "orderId": "e-1",
        "orderLinkId": link(),
        "symbol": "BTCUSDT",
        "price": "60000",
        "qty": "0.010",
        "side": "Buy",
        "positionIdx": 0,
        "orderStatus": "New",
        "avgPrice": "",
        "leavesQty": "0.010",
        "cumExecQty": "0",
        "timeInForce": "GTC",
        "orderType": "Limit",
        "stopOrderType": "",
        "triggerPrice": "0",
        "takeProfit": "",
        "stopLoss": "58000",
        "tpslMode": "Full",
        "reduceOnly": False,
        "createdTime": T_MS,
        "updatedTime": T_MS,
    }
    return base | fields


def _unknown(model: str) -> float:
    value: float = cv_bybit_unknown_fields_total.labels(model=model)._value.get()
    return value


def test_a_row_parses_into_the_neutral_order_with_the_calls_account() -> None:
    order = tp.to_order(tp.parse(tp.OrderRow, _row(), "order"), account())
    assert (order.order_link_id, order.exchange_order_id, order.account_id) == (
        link(),
        "e-1",
        account().account_id,
    )
    assert (order.price, order.stop_loss, order.trigger_price, order.take_profit) == (
        Decimal("60000"),
        Decimal("58000"),
        None,
        None,
    )
    assert (order.state, order.order_kind, order.tpsl_mode, order.order_id) == (
        "new",
        "order",
        "full",
        None,
    )
    assert order.created_at == int(T_MS) * 1000 and order.terminal_at is None


def test_a_partial_mode_stop_row_maps_its_kind_and_mode() -> None:
    """No documented example shows one (#2877 O-4): the parser alone is covered."""
    row = _row(
        stopOrderType="PartialStopLoss",
        tpslMode="Partial",
        triggerPrice="57500",
        orderType="Market",
        price="0",
        reduceOnly=True,
        orderStatus="Untriggered",
    )
    order = tp.to_order(tp.parse(tp.OrderRow, row, "order"), account())
    assert (order.order_kind, order.tpsl_mode, order.trigger_price, order.price) == (
        "partial_stop_loss",
        "partial",
        Decimal("57500"),
        None,
    )
    assert order.reduce_only and order.state == "untriggered"
    assert order.order_type == "market"  # a Market row is no limit order, whatever its price


#: `T_MS` in microseconds: when a terminal row's order ended (its `updatedTime`).
T_US = int(T_MS) * 1000


@pytest.mark.parametrize(
    ("status", "state", "terminal_at"),
    [
        ("New", "new", None),
        ("PartiallyFilled", "partially_filled", None),
        ("Untriggered", "untriggered", None),
        ("Triggered", "triggered", None),
        ("Rejected", "rejected", T_US),
        ("PartiallyFilledCanceled", "partially_filled_canceled", T_US),
        ("Filled", "filled", T_US),
        ("Cancelled", "cancelled", T_US),
        ("Deactivated", "deactivated", T_US),
    ],
)
def test_every_status_maps_to_its_state_and_a_terminal_one_carries_its_time(
    status: str, state: str, terminal_at: int | None
) -> None:
    """Every documented `orderStatus`, by literal name: B1 and reconciliation read the state."""
    order = tp.to_order(tp.parse(tp.OrderRow, _row(orderStatus=status), "order"), account())
    assert (order.state, order.terminal_at) == (state, terminal_at)


@pytest.mark.parametrize(
    ("stop_order_type", "kind"),
    [
        ("", "order"),
        ("UNKNOWN", "order"),
        ("Stop", "conditional"),
        ("TakeProfit", "take_profit"),
        ("StopLoss", "stop_loss"),
        ("PartialTakeProfit", "partial_take_profit"),
        ("PartialStopLoss", "partial_stop_loss"),
        ("TrailingStop", "trailing_stop"),
        ("MmRateClose", "mm_rate_close"),
    ],
)
def test_every_stop_order_type_maps_to_its_order_kind(stop_order_type: str, kind: str) -> None:
    """Ruling R8: `order_kind` is how the OMS tells an exchange-made stop from a plain order
    (C-2.6), so each documented `stopOrderType` maps by literal name."""
    row = _row(stopOrderType=stop_order_type)
    assert tp.to_order(tp.parse(tp.OrderRow, row, "order"), account()).order_kind == kind


@pytest.mark.parametrize(
    ("time_in_force", "expected"),
    [("GTC", "gtc"), ("IOC", "ioc"), ("FOK", "fok"), ("PostOnly", "post_only"), ("RPI", "rpi")],
)
def test_every_time_in_force_maps_by_name(time_in_force: str, expected: str) -> None:
    row = _row(timeInForce=time_in_force)
    order = tp.to_order(tp.parse(tp.OrderRow, row, "order"), account())
    assert order.time_in_force == expected


@pytest.mark.parametrize(
    ("tpsl_mode", "expected"),
    [("Full", "full"), ("Partial", "partial"), ("", None), ("UNKNOWN", None)],
)
def test_every_tpsl_mode_maps_by_name(tpsl_mode: str, expected: str | None) -> None:
    order = tp.to_order(tp.parse(tp.OrderRow, _row(tpslMode=tpsl_mode), "order"), account())
    assert order.tpsl_mode == expected


def test_a_partly_filled_row_maps_every_field_to_its_own() -> None:
    """Quantities, prices and times that all differ, so a swapped or dropped field shows."""
    row = _row(
        orderId="e-7", qty="0.030", leavesQty="0.010", cumExecQty="0.020", avgPrice="60010.5",
        orderStatus="PartiallyFilled", triggerPrice="59000", takeProfit="65000",
        stopLoss="58000", tpslMode="Partial", stopOrderType="Stop", positionIdx=2,
        timeInForce="IOC", reduceOnly=True, side="Sell", createdTime="1700000000001",
        updatedTime="1700000000002",
    )  # fmt: skip
    order = tp.to_order(tp.parse(tp.OrderRow, row, "order"), account())
    assert order == Order(
        order_link_id=link(),
        exchange_order_id="e-7",
        account_id=account().account_id,
        symbol="BTCUSDT",
        side="sell",
        order_type="limit",
        qty=Decimal("0.030"),
        price=Decimal("60000"),
        state="partially_filled",
        filled_qty=Decimal("0.020"),
        leaves_qty=Decimal("0.010"),
        avg_fill_price=Decimal("60010.5"),
        created_at=1_700_000_000_001_000,
        terminal_at=None,
        updated_at=1_700_000_000_002_000,
        reduce_only=True,
        trigger_price=Decimal("59000"),
        stop_loss=Decimal("58000"),
        take_profit=Decimal("65000"),
        tpsl_mode="partial",
        order_kind="conditional",
        position_idx=2,
        time_in_force="ioc",
    )


def test_a_limit_order_without_a_price_is_unknown() -> None:
    with pytest.raises(UnknownStateError):
        tp.to_order(tp.parse(tp.OrderRow, _row(price="0"), "order"), account())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("price", 60000),
        ("price", "6e4"),
        ("price", "NaN"),
        ("price", " 60000"),
        ("price", "-1"),
        ("qty", "1" * 30),
        ("qty", "-0.1"),
        ("stopLoss", "1e13"),
        ("stopLoss", "10000000000000"),
        ("positionIdx", "0"),
        ("positionIdx", True),
        ("positionIdx", 3),
        ("reduceOnly", "false"),
        ("orderStatus", "Created"),
        ("timeInForce", "GoodTillCancel"),
        ("stopOrderType", "OcoOrder"),
        ("createdTime", 1700000000000),
        ("createdTime", "1400000000000"),
        ("createdTime", "4102444800001"),
        ("orderId", ""),
        ("orderLinkId", "x" * 65),
        ("symbol", "btcusdt"),
    ],
)
def test_a_field_of_the_wrong_type_shape_or_bound_fails_the_reply(field: str, value: Any) -> None:
    with pytest.raises(UnknownStateError) as caught:
        tp.parse(tp.OrderRow, _row(**{field: value}), "order")
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_a_missing_field_fails_the_reply() -> None:
    row = _row()
    del row["leavesQty"]
    with pytest.raises(UnknownStateError, match="malformed order reply"):
        tp.parse(tp.OrderRow, row, "order")


def test_an_unknown_field_is_ignored_and_counted_by_model() -> None:
    before = _unknown("order")
    order = tp.parse(tp.OrderRow, _row(newVenueField="x", another=1), "order")
    assert order.orderId == "e-1" and _unknown("order") == before + 2


def test_a_documented_field_the_port_does_not_read_is_never_counted() -> None:
    before = _unknown("order")
    tp.parse(tp.OrderRow, _row(cancelType="UNKNOWN", cumFeeDetail={"MNT": "0.1"}), "order")
    assert _unknown("order") == before


def test_every_model_label_is_one_of_the_closed_set() -> None:
    labels = {
        model.metric_model
        for model in vars(tp).values()
        if isinstance(model, type) and issubclass(model, tp._Venue) and model is not tp._Venue
    }
    assert labels == tp.MODEL_LABELS


@pytest.mark.parametrize("category", ["spot", "inverse", "option", None])
def test_a_page_of_another_category_fails_the_reply(category: str | None) -> None:
    page: dict[str, Any] = {"category": category, "nextPageCursor": "", "list": []}
    with pytest.raises(UnknownStateError):
        tp.parse(tp.OrderPage, page, "open_orders")


def test_an_over_long_cursor_fails_the_reply() -> None:
    page = {"category": "linear", "nextPageCursor": "c" * 513, "list": []}
    with pytest.raises(UnknownStateError):
        tp.parse(tp.OrderPage, page, "open_orders")


# -- normalisation and the owner check (24 §14.2 rule 11, R12) -----------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (link(), link()),
        ("", ext_key("e-1")),
        ("linear-004", ext_key("e-1")),
        (ext_key("other"), ext_key("e-1")),
    ],
    ids=["ours", "empty", "foreign", "ext-shaped"],
)
def test_ids_normalise_to_ours_or_the_ext_key(raw: str, expected: str) -> None:
    assert tp.normalised_link(raw, "e-1") == expected


@pytest.mark.parametrize(
    ("row_link", "reason"),
    [
        (link(), None),
        (link(environment="live"), "environment"),
        (link(environment="testnet"), "environment"),
        (link(ACCOUNT_B), "account"),
        (ext_key("e-1"), None),
    ],
)
def test_the_owner_check_names_why_a_row_is_not_this_accounts(
    row_link: str, reason: str | None
) -> None:
    assert tp.owner_refusal(row_link, account()) == reason


@given(st.uuids(), st.uuids())
def test_a_row_of_another_account_is_never_kept(mine: UUID, theirs: UUID) -> None:
    me, them = AccountId(mine), AccountId(theirs)
    ref = account(me)
    rows = [link(me), link(them)]
    kept = tp.kept(rows, lambda r: r, ref)
    assert link(me) in kept
    assert (link(them) in kept) is (tp.owner_refusal(link(them), ref) is None)


# -- the shapes with no documented linear example -----------------------------------------------


def _coin(**fields: Any) -> dict[str, Any]:
    base = {"coin": "USDT", "equity": "1000.5", "walletBalance": "990",
            "availableToWithdraw": "", "unrealisedPnl": "10.5", "cumRealisedPnl": "-3"}  # fmt: skip
    return base | fields


def _wallet(*coins: dict[str, Any]) -> dict[str, Any]:
    account_fields = {"accountType": "UNIFIED", "accountIMRate": "0.01", "accountMMRate": "0.005",
                      "totalAvailableBalance": "900", "totalInitialMargin": "90"}  # fmt: skip
    return {"list": [account_fields | {"coin": list(coins)}]}


def test_a_usdt_wallet_row_maps_with_an_unreported_withdrawable_figure() -> None:
    page = tp.parse(tp.WalletPage, _wallet(_coin(), _coin(coin="BTC")), "wallet")
    wallet = tp.to_wallet(page, account(), "USDT", 1_700_000_000_000)
    assert (wallet.equity, wallet.available_to_withdraw, wallet.used_margin) == (
        Decimal("1000.5"),
        None,
        Decimal("90"),
    )
    assert wallet.updated_at == 1_700_000_000_000_000


def test_a_wallet_maps_every_figure_to_its_own() -> None:
    coin = _coin(equity="1000.5", walletBalance="990.25", availableToWithdraw="800",
                 unrealisedPnl="10.5", cumRealisedPnl="-3")  # fmt: skip
    page = tp.parse(tp.WalletPage, _wallet(coin), "wallet")
    assert tp.to_wallet(page, account(), "USDT", 1_700_000_000_004) == Wallet(
        account_id=account().account_id,
        coin="USDT",
        equity=Decimal("1000.5"),
        wallet_balance=Decimal("990.25"),
        available_to_withdraw=Decimal("800"),
        available_margin=Decimal("900"),
        used_margin=Decimal("90"),
        unrealised_pnl=Decimal("10.5"),
        cum_realised_pnl=Decimal("-3"),
        account_im_rate=Decimal("0.01"),
        account_mm_rate=Decimal("0.005"),
        updated_at=1_700_000_000_004_000,
    )


def test_a_wallet_with_two_usdt_rows_is_unknown() -> None:
    page = tp.parse(tp.WalletPage, _wallet(_coin(), _coin()), "wallet")
    with pytest.raises(UnknownStateError):
        tp.to_wallet(page, account(), "USDT", 1_700_000_000_000)


def test_a_linear_position_row_maps_a_flat_side_to_none() -> None:
    row = {"positionIdx": 0, "symbol": "BTCUSDT", "side": "", "size": "0", "avgPrice": "0",
           "markPrice": "60000", "liqPrice": "", "leverage": "5", "unrealisedPnl": "0",
           "cumRealisedPnl": "-1.5", "takeProfit": "0.00", "stopLoss": "58000",
           "trailingStop": "0.00", "updatedTime": T_MS}  # fmt: skip
    position = tp.to_position(tp.parse(tp.PositionRow, row, "positions"), account())
    assert (position.side, position.qty, position.avg_entry_price, position.liq_price) == (
        None,
        Decimal("0"),
        None,
        None,
    )
    assert position.stop_loss == Decimal("58000") and position.take_profit is None


def test_a_position_row_maps_every_field_to_its_own() -> None:
    """Every figure differs, so a swapped or dropped field shows (the PnL pair included)."""
    row = {"positionIdx": 1, "symbol": "BTCUSDT", "side": "Buy", "size": "0.5",
           "avgPrice": "60000", "markPrice": "60100", "liqPrice": "55000", "leverage": "7",
           "unrealisedPnl": "50", "cumRealisedPnl": "-12.5", "takeProfit": "65000",
           "stopLoss": "58000", "trailingStop": "150", "updatedTime": "1700000000003"}  # fmt: skip
    position = tp.to_position(tp.parse(tp.PositionRow, row, "positions"), account())
    assert position == Position(
        account_id=account().account_id,
        symbol="BTCUSDT",
        position_idx=1,
        side="buy",
        qty=Decimal("0.5"),
        avg_entry_price=Decimal("60000"),
        mark_price=Decimal("60100"),
        liq_price=Decimal("55000"),
        leverage=Decimal("7"),
        unrealised_pnl=Decimal("50"),
        cum_realised_pnl=Decimal("-12.5"),
        take_profit=Decimal("65000"),
        stop_loss=Decimal("58000"),
        trailing_stop_distance=Decimal("150"),
        updated_at=1_700_000_000_003_000,
    )


def test_a_position_without_a_leverage_is_unknown() -> None:
    """Portfolio margin reports "" for leverage: refused until the model can hold it."""
    row = {"positionIdx": 0, "symbol": "BTCUSDT", "side": "Buy", "size": "1", "avgPrice": "1",
           "markPrice": "1", "liqPrice": "", "leverage": "", "unrealisedPnl": "0",
           "cumRealisedPnl": "0", "takeProfit": "", "stopLoss": "", "trailingStop": "",
           "updatedTime": T_MS}  # fmt: skip
    with pytest.raises(UnknownStateError):
        tp.parse(tp.PositionRow, row, "positions")


def test_a_derivatives_fee_rate_row_carries_no_category() -> None:
    page = {"list": [{"symbol": "BTCUSDT", "takerFeeRate": "0.00055", "makerFeeRate": "0.0002"}]}
    fee = tp.to_fee_rate(tp.parse(tp.FeeRatePage, page, "fee-rate"), "BTCUSDT", 5)
    assert (fee.maker, fee.taker, fee.fetched_at, fee.estimated) == (
        Decimal("0.0002"),
        Decimal("0.00055"),
        5,
        False,
    )
    with pytest.raises(UnknownStateError):
        tp.to_fee_rate(tp.parse(tp.FeeRatePage, page, "fee-rate"), "ETHUSDT", 5)


@pytest.mark.parametrize(
    ("mode", "status", "expected"),
    [
        ("ISOLATED_MARGIN", 5, ("isolated", True)),
        ("PORTFOLIO_MARGIN", 6, ("portfolio", True)),
        ("REGULAR_MARGIN", 1, ("regular", False)),
    ],
)
def test_account_info_maps_every_margin_mode(
    mode: str, status: int, expected: tuple[str, bool]
) -> None:
    result = {"marginMode": mode, "unifiedMarginStatus": status, "updatedTime": T_MS}
    info = tp.to_account_info(tp.parse(tp.AccountInfoResult, result, "account-info"), account())
    assert (info.margin_mode, info.unified_margin, info.position_mode) == (*expected, None)


#: A unit input with every field the execution parser reads (names as documented).
EXEC_ROW: dict[str, Any] = {
    "symbol": "BTCUSDT", "orderId": "e-1", "orderLinkId": link(), "side": "Sell",
    "execFee": "-0.01", "feeRate": "0.00055", "execId": "x-1", "execPrice": "60000",
    "execQty": "0.01", "execType": "Trade", "execTime": T_MS, "feeCurrency": "USDT",
    "isMaker": True, "seq": 7,
}  # fmt: skip
#: Every `execType` of the enum page at the transcriptions' docs commit (`docs/v5/enum.mdx`,
#: `bybit-exchange/docs@19518b90fb36`), as listed there.
DOCUMENTED_EXEC_TYPES = frozenset(
    {
        "Trade", "AdlTrade", "Funding", "BustTrade", "Delivery", "Settle", "BlockTrade",
        "MovePosition", "FutureSpread", "ForwardSplitSettle", "ForwardSplitOpen",
        "ReverseSplitSettle", "ReverseSplitOpen", "UNKNOWN",
    }
)  # fmt: skip
#: `exec_type` as 24 §8.1 and `21-database-schema.md` §3.3.6 name it (the CHECK `ex_type`).
STORED_EXEC_TYPES = {
    "Trade": "trade", "AdlTrade": "adl_trade", "Funding": "funding", "BustTrade": "bust_trade",
    "Settle": "settle", "SessionSettlePnl": "session_settle_pnl",
}  # fmt: skip


def test_the_parser_reads_21s_execution_types_and_sets_every_other_documented_one_aside() -> None:
    """Every venue type 21 stores is read under its `exec_type`, but `Funding`, set aside until
    E29-K01 shows its row; every other documented type is set aside, none is mapped by guess."""
    known = tp.EXEC_TYPES.keys() | tp.NOT_FILLS | tp.UNMAPPED_TYPES
    assert known == DOCUMENTED_EXEC_TYPES | {"SessionSettlePnl"}
    assert len(known) == len(tp.EXEC_TYPES) + len(tp.NOT_FILLS) + len(tp.UNMAPPED_TYPES)
    assert dict(tp.EXEC_TYPES) == {k: v for k, v in STORED_EXEC_TYPES.items() if k != "Funding"}
    assert "Funding" in tp.NOT_FILLS


@pytest.mark.parametrize(
    ("exec_type", "stored"),
    [
        ("Trade", "trade"),
        ("AdlTrade", "adl_trade"),
        ("BustTrade", "bust_trade"),
        ("Settle", "settle"),
        ("SessionSettlePnl", "session_settle_pnl"),
    ],
)
def test_every_type_21_stores_is_read_with_its_exec_type(exec_type: str, stored: str) -> None:
    """A documented type never fails the read (it would halt fill reconciliation)."""
    row = EXEC_ROW | {"execType": exec_type}
    fill = tp.to_execution(tp.parse(tp.ExecutionRow, row, "executions"), account(), 42)
    assert (tp.set_aside(row), fill.exec_type) == (None, stored)


@pytest.mark.parametrize(
    ("exec_type", "reason"),
    [
        ("Funding", "not_a_fill"),
        ("UNKNOWN", "not_a_fill"),
        ("Delivery", "unmapped_type"),
        ("BlockTrade", "unmapped_type"),
        ("MovePosition", "unmapped_type"),
        ("FutureSpread", "unmapped_type"),
        ("ForwardSplitSettle", "unmapped_type"),
        ("ForwardSplitOpen", "unmapped_type"),
        ("ReverseSplitSettle", "unmapped_type"),
        ("ReverseSplitOpen", "unmapped_type"),
    ],
)
def test_every_other_documented_type_is_set_aside_with_its_reason(
    exec_type: str, reason: str
) -> None:
    assert tp.set_aside(EXEC_ROW | {"execType": exec_type}) == reason


def test_an_undocumented_execution_type_fails_the_read() -> None:
    row = EXEC_ROW | {"execType": "NotInTheEnumPage"}
    assert tp.set_aside(row) is None
    with pytest.raises(UnknownStateError):
        tp.parse(tp.ExecutionRow, row, "executions")


@pytest.mark.parametrize("kind", [["Trade"], {"x": 1}, 1.5, None])
def test_an_execution_type_that_is_no_text_fails_the_read_as_unknown_state(kind: object) -> None:
    """A list or an object is unhashable: the set-aside check never meets it as a set member,
    so it is parsed and fails as `UnknownStateError`, never a builtin `TypeError`."""
    row = EXEC_ROW | {"execType": kind}
    assert tp.set_aside(row) is None
    with pytest.raises(UnknownStateError):
        tp.parse(tp.ExecutionRow, row, "executions")


def test_an_execution_row_maps_with_the_ingest_time() -> None:
    row = EXEC_ROW
    fill = tp.to_execution(tp.parse(tp.ExecutionRow, row, "executions"), account(), 42)
    assert (fill.order_link_id, fill.fee, fill.is_maker, fill.ts_ingest, fill.seq) == (
        link(),
        Decimal("-0.01"),
        True,
        42,
        7,
    )
    assert (fill.exchange_order_id, fill.exec_type, fill.fee_rate) == (
        "e-1",
        "trade",
        Decimal("0.00055"),
    )
    assert tp.set_aside(row) is None and tp.set_aside(row | {"execType": "Funding"})


def test_an_execution_row_maps_every_field_to_its_own() -> None:
    """The whole fill record from `EXEC_ROW`, a Sell (the transcribed fill is a Buy), so a side
    read as the other, or a swapped figure, shows in the immutable record the OMS stores."""
    fill = tp.to_execution(tp.parse(tp.ExecutionRow, EXEC_ROW, "executions"), account(), 42)
    assert fill == Execution(
        exec_id="x-1",
        exchange_order_id="e-1",
        order_link_id=link(),
        account_id=account().account_id,
        symbol="BTCUSDT",
        side="sell",
        price=Decimal("60000"),
        qty=Decimal("0.01"),
        fee=Decimal("-0.01"),
        fee_rate=Decimal("0.00055"),
        fee_currency="USDT",
        is_maker=True,
        exec_type="trade",
        closed_pnl=None,
        ts_exec=int(T_MS) * 1000,
        ts_ingest=42,
        seq=7,
    )


@pytest.mark.parametrize("rate", ["-0.000025", "0.0006", "0.0006000000000", "12345678.1234567890"])
def test_a_fee_rate_numeric_18_10_holds_is_read(rate: str) -> None:
    fill = tp.to_execution(
        tp.parse(tp.ExecutionRow, EXEC_ROW | {"feeRate": rate}, "executions"), account(), 42
    )
    assert fill.fee_rate == Decimal(rate)


@pytest.mark.parametrize(
    "rate", ["0.00000000001", "123456789", "", "abc", 0.0006, None],
    ids=["eleven-places", "nine-whole-digits", "empty", "text", "json-number", "null"],
)  # fmt: skip
def test_a_fee_rate_numeric_18_10_cannot_hold_fails_the_read(rate: object) -> None:
    with pytest.raises(UnknownStateError):
        tp.parse(tp.ExecutionRow, EXEC_ROW | {"feeRate": rate}, "executions")


@pytest.mark.parametrize("order_id", ["", None, 7])
def test_an_execution_without_its_order_id_fails_the_read(order_id: object) -> None:
    """24 §8.1: an execution names the exchange order it fills; none is no execution."""
    with pytest.raises(UnknownStateError):
        tp.parse(tp.ExecutionRow, EXEC_ROW | {"orderId": order_id}, "executions")


@pytest.mark.parametrize(
    ("closed_size", "exec_pnl", "closed_pnl"),
    [
        ("0.01", "12.5", Decimal("12.5")), ("0.01", "-1.5", Decimal("-1.5")),
        ("0.01", "0", Decimal("0")), ("0", "0", None), ("", None, None), (None, None, None),
        ("0.01", None, None), ("0.01", "", None),
    ],
    ids=["closing-gain", "closing-loss", "closing-flat", "opening", "rest-blank", "unstated",
         "closing-without-pnl", "closing-blank-pnl"],
)  # fmt: skip
def test_an_execution_carries_the_venues_pnl_of_the_size_it_closed(
    closed_size: str | None, exec_pnl: str | None, closed_pnl: Decimal | None
) -> None:
    """24 §8.1: `closed_pnl` is present on a reducing fill, the venue's `execPnl` of it (#848's
    post-Done note); an opening fill, or a reply that states neither, has none."""
    given = {
        k: v for k, v in {"closedSize": closed_size, "execPnl": exec_pnl}.items() if v is not None
    }
    fill = tp.to_execution(tp.parse(tp.ExecutionRow, EXEC_ROW | given, "executions"), account(), 42)
    assert fill.closed_pnl == closed_pnl


@pytest.mark.parametrize("closed_size", ["-0.01", "abc", 0.01])
def test_an_execution_whose_closed_size_is_no_quantity_fails_the_read(closed_size: object) -> None:
    with pytest.raises(UnknownStateError):
        tp.parse(tp.ExecutionRow, EXEC_ROW | {"closedSize": closed_size}, "executions")


#: A unit input with every field the closed-PnL parser reads (names as documented).
CLOSED_ROW: dict[str, Any] = {
    "symbol": "BTCUSDT", "side": "Sell", "closedSize": "0.5", "avgEntryPrice": "60000",
    "avgExitPrice": "61000", "closedPnl": "500", "leverage": "5", "createdTime": T_MS,
    "updatedTime": T_MS,
}  # fmt: skip


def test_a_closed_pnl_row_maps_every_field_to_its_own() -> None:
    """A Buy (the transcribed record is a Sell) with every figure and time its own."""
    row = CLOSED_ROW | {
        "side": "Buy",
        "createdTime": "1700000000001",
        "updatedTime": "1700000000002",
    }
    record = tp.to_closed_pnl(tp.parse(tp.ClosedPnlRow, row, "closed-pnl"), account())
    assert record == ClosedPnl(
        account_id=account().account_id,
        symbol="BTCUSDT",
        side="buy",
        qty=Decimal("0.5"),
        avg_entry_price=Decimal("60000"),
        avg_exit_price=Decimal("61000"),
        closed_pnl=Decimal("500"),
        leverage=Decimal("5"),
        opened_at=1_700_000_000_001_000,
        closed_at=1_700_000_000_002_000,
    )


@pytest.mark.parametrize(
    ("model", "row", "field", "value"),
    [
        (tp.ExecutionRow, EXEC_ROW, "execPrice", "0"),
        (tp.ExecutionRow, EXEC_ROW, "execPrice", "-1"),
        (tp.ExecutionRow, EXEC_ROW, "execPrice", "1000000000000.1"),
        (tp.ExecutionRow, EXEC_ROW, "execPrice", "2000000000000"),
        (tp.ExecutionRow, EXEC_ROW, "execFee", "2000000000000000"),
        (tp.ExecutionRow, EXEC_ROW, "execFee", "-2000000000000000"),
        (tp.ExecutionRow, EXEC_ROW, "execFee", "1000000000000001"),
        (tp.ClosedPnlRow, CLOSED_ROW, "closedPnl", "-2000000000000000"),
        (tp.ClosedPnlRow, CLOSED_ROW, "closedPnl", "1000000000000001"),
    ],
    ids=[
        "price-zero", "price-negative", "price-past-max", "price-twice-max", "fee-over",
        "fee-under", "fee-edge", "pnl-under", "pnl-edge",
    ],
)  # fmt: skip
def test_an_amount_or_price_past_its_bound_fails_a_complete_row(
    model: type[tp._Venue], row: dict[str, Any], field: str, value: str
) -> None:
    """The row is read as it is, so the failure is the one field's: a fill at no price, or a
    figure no account comes near, fails the reply (plausibility, `frame_guard`)."""
    assert tp.parse(model, row, "bounds") is not None
    with pytest.raises(UnknownStateError):
        tp.parse(model, row | {field: value}, "bounds")


@pytest.mark.parametrize(
    ("model", "row", "field", "value"),
    [
        (tp.ExecutionRow, EXEC_ROW, "execPrice", "1000000000000"),
        (tp.ExecutionRow, EXEC_ROW, "execFee", "1000000000000000"),
        (tp.ExecutionRow, EXEC_ROW, "execFee", "-1000000000000000"),
        (tp.ClosedPnlRow, CLOSED_ROW, "closedPnl", "-999999999999999"),
    ],
    ids=["price-max", "fee-max", "fee-min", "pnl-inside"],
)
def test_an_amount_or_price_on_its_bound_is_read(
    model: type[tp._Venue], row: dict[str, Any], field: str, value: str
) -> None:
    parsed = tp.parse(model, row | {field: value}, "bounds")
    assert getattr(parsed, field) == Decimal(value)


@pytest.mark.parametrize("data", [[_row()], "row", None, 7])
def test_a_reply_that_is_no_object_fails_without_counting_fields(data: object) -> None:
    before = _unknown("order")
    with pytest.raises(UnknownStateError):
        tp.parse(tp.OrderRow, data, "order")
    assert _unknown("order") == before


@pytest.mark.parametrize(
    ("status", "unified"), [(1, False), (3, True), (4, True), (5, True), (6, True)]
)
def test_every_unified_margin_status_says_whether_the_account_is_unified(
    status: int, unified: bool
) -> None:
    """`1` is a classic account; `3` to `6` are unified trading accounts."""
    result = {"marginMode": "REGULAR_MARGIN", "unifiedMarginStatus": status, "updatedTime": T_MS}
    info = tp.to_account_info(tp.parse(tp.AccountInfoResult, result, "account-info"), account())
    assert info.unified_margin is unified


def test_account_info_refuses_a_boolean_status() -> None:
    result = {"marginMode": "REGULAR_MARGIN", "unifiedMarginStatus": True, "updatedTime": T_MS}
    with pytest.raises(UnknownStateError):
        tp.parse(tp.AccountInfoResult, result, "account-info")


# -- page bounds, per model -----------------------------------------------------------------------

#: A unit input with every field the position parser reads (names as documented).
POSITION_ROW: dict[str, Any] = {
    "positionIdx": 0, "symbol": "BTCUSDT", "side": "Buy", "size": "1", "avgPrice": "60000",
    "markPrice": "60100", "liqPrice": "", "leverage": "5", "unrealisedPnl": "100",
    "cumRealisedPnl": "0", "takeProfit": "", "stopLoss": "58000", "trailingStop": "",
    "updatedTime": T_MS,
}  # fmt: skip
#: One `create-batch` item and its code, as unit inputs.
BATCH_ITEM: dict[str, Any] = {"symbol": "BTCUSDT", "orderId": "e-1", "orderLinkId": link()}
BATCH_CODE: dict[str, Any] = {"code": 0, "msg": "OK"}


def _page(row: dict[str, Any]) -> Callable[[int], dict[str, Any]]:
    return lambda rows: {"category": "linear", "nextPageCursor": "", "list": [row] * rows}


def _batch_reply(items: int, codes: int | None = None) -> dict[str, Any]:
    """`items` orders and as many codes, or `codes` of them."""
    count = items if codes is None else codes
    return {"result": {"list": [BATCH_ITEM] * items}, "retExtInfo": {"list": [BATCH_CODE] * count}}


PAGES: list[tuple[type[Any], Callable[[int], dict[str, Any]], int, Callable[[Any], int]]] = [
    (tp.OrderPage, _page(_row()), 50, lambda parsed: len(parsed.rows)),
    (tp.ExecutionPage, _page(EXEC_ROW), 100, lambda parsed: len(parsed.rows)),
    (tp.PositionPage, _page(POSITION_ROW), 200, lambda parsed: len(parsed.rows)),
    (tp.ClosedPnlPage, _page(CLOSED_ROW), 100, lambda parsed: len(parsed.rows)),
    (
        tp.BatchReply,
        _batch_reply,
        20,
        lambda parsed: min(len(parsed.result.items), len(parsed.retExtInfo.codes)),
    ),
]
PAGE_IDS = ["order", "execution", "position", "closed_pnl", "batch"]


@pytest.mark.parametrize(("model", "page", "limit", "count"), PAGES, ids=PAGE_IDS)
def test_a_page_of_the_venues_limit_is_read_whole(
    model: type[Any], page: Callable[[int], dict[str, Any]], limit: int, count: Callable[[Any], int]
) -> None:
    """The port asks for the venue's page limit (`_PAGE_LIMIT`), so a full page is a normal
    answer; a bound below it would fail every full page."""
    assert count(tp.parse(model, page(limit), "page")) == limit
    assert count(tp.parse(model, page(0), "page")) == 0


@pytest.mark.parametrize(
    ("model", "data"),
    [
        (tp.OrderPage, _page(_row())(51)),
        (tp.ExecutionPage, _page(EXEC_ROW)(101)),
        (tp.PositionPage, _page(POSITION_ROW)(201)),
        (tp.ClosedPnlPage, _page(CLOSED_ROW)(101)),
        (tp.BatchReply, _batch_reply(21, 20)),
        (tp.BatchReply, _batch_reply(20, 21)),
    ],
    ids=[*PAGE_IDS[:4], "batch-items", "batch-codes"],
)
def test_a_page_past_the_venues_limit_fails_the_reply(
    model: type[Any], data: dict[str, Any]
) -> None:
    with pytest.raises(UnknownStateError):
        tp.parse(model, data, "page")


#: The other bounded replies, each built with `n` items (unit inputs), and their bound.
FEE_ROW: dict[str, Any] = {"symbol": "BTCUSDT", "takerFeeRate": "0.00055", "makerFeeRate": "0.0002"}
BOUNDS: list[tuple[type[Any], Callable[[int], object], int]] = [
    (tp.CancelAllResult, lambda n: {"list": [{"orderId": "e-1", "orderLinkId": ""}] * n}, 10_000),
    (tp.WalletPage, lambda n: {"list": _wallet(_coin())["list"] * n}, 4),
    (tp.WalletPage, lambda n: _wallet(*[_coin(coin=f"C{k}") for k in range(n)]), 200),
    (tp.FeeRatePage, lambda n: {"list": [FEE_ROW] * n}, 1),
    (tp.OrderReply, lambda n: {"orderId": "e" * n, "orderLinkId": ""}, 64),
]


@pytest.mark.parametrize(
    ("model", "reply", "bound"),
    BOUNDS,
    ids=["cancel-all-rows", "wallet-accounts", "wallet-coins", "fee-rate-rows", "venue-id-length"],
)
def test_a_reply_on_its_bound_is_read_and_one_past_it_fails(
    model: type[Any], reply: Callable[[int], object], bound: int
) -> None:
    """Each bound sits where the venue's answer can reach and no further: one more item, or
    one more character of an id, fails the reply (E8-8)."""
    assert tp.parse(model, reply(bound), "bound") is not None
    with pytest.raises(UnknownStateError):
        tp.parse(model, reply(bound + 1), "bound")


@pytest.mark.parametrize(
    ("model", "row"),
    [(tp.OrderRow, _row()), (tp.PositionRow, POSITION_ROW)],
    ids=["order", "position"],
)
def test_a_dated_futures_row_fails_the_read_as_rule_12_says(
    model: type[tp._Venue], row: dict[str, Any]
) -> None:
    """24 §14.2 rule 12: the port reads USDT linear perpetuals only (C-1.2 item 3). A dated
    future's symbol (`BTCUSDT-26DEC25`) fails a read that names the settle coin or a symbol,
    closed, rather than being read as a perpetual's; that such a read lists none is assumed
    pending E29-K01. The closed-PnL read names neither and sets such a row aside before this
    parse (`other_contract`, pinned in `test_trading_port_reads.py`)."""
    assert tp.parse(model, row, "row") is not None
    with pytest.raises(UnknownStateError):
        tp.parse(model, row | {"symbol": "BTCUSDT-26DEC25"}, "row")


# -- prices below 1, and every bound of a complete row, on both sides ----------------------------

#: Prices of the sub-dollar USDT perpetuals (DOGE, XRP, `1000PEPE`), and 1 itself: test inputs.
SUB_DOLLAR = ["0.5", "0.00001234", "1"]


@pytest.mark.parametrize("price", SUB_DOLLAR)
@pytest.mark.parametrize(
    ("model", "row", "field"),
    [
        (tp.OrderRow, _row(), "price"),
        (tp.OrderRow, _row(), "stopLoss"),
        (tp.OrderRow, _row(), "takeProfit"),
        (tp.OrderRow, _row(), "triggerPrice"),
        (tp.ExecutionRow, EXEC_ROW, "execPrice"),
        (tp.ClosedPnlRow, CLOSED_ROW, "avgEntryPrice"),
        (tp.ClosedPnlRow, CLOSED_ROW, "avgExitPrice"),
    ],
    ids=["price", "stopLoss", "takeProfit", "triggerPrice", "execPrice", "entry", "exit"],
)
def test_a_price_below_one_is_read_unchanged(
    model: type[tp._Venue], row: dict[str, Any], field: str, price: str
) -> None:
    """A sub-dollar contract's rows are rows like any other: refusing one would fail the whole
    page and halt the reconciliation that also repairs stops (ruling R7)."""
    assert getattr(tp.parse(model, row | {field: price}, "prices"), field) == Decimal(price)


@pytest.mark.parametrize("price", SUB_DOLLAR)
def test_a_limit_order_priced_below_one_or_at_one_maps_with_its_price(price: str) -> None:
    order = tp.to_order(tp.parse(tp.OrderRow, _row(price=price), "order"), account())
    assert (order.order_type, order.price) == ("limit", Decimal(price))


#: The largest figure each bound admits, and the smallest past it (`frame_guard`: 1e12).
ON_BOUND, PAST_BOUND = "1000000000000", "1000000000000.1"


#: The order row's bounded quantities and optional prices.
BOUNDED = ["qty", "leavesQty", "cumExecQty", "stopLoss", "takeProfit", "triggerPrice", "avgPrice"]


@pytest.mark.parametrize("field", BOUNDED)
def test_a_quantity_or_price_on_its_bound_is_read(field: str) -> None:
    parsed = tp.parse(tp.OrderRow, _row(**{field: ON_BOUND}), "order")
    assert getattr(parsed, field) == Decimal(ON_BOUND)


@pytest.mark.parametrize("field", BOUNDED)
def test_a_quantity_or_price_past_its_bound_fails_the_row(field: str) -> None:
    with pytest.raises(UnknownStateError):
        tp.parse(tp.OrderRow, _row(**{field: PAST_BOUND}), "order")


@pytest.mark.parametrize("field", ["stopLoss", "takeProfit", "triggerPrice", "avgPrice"])
def test_a_negative_optional_price_fails_the_row(field: str) -> None:
    """`""` and a zero say "not set"; below zero is no price at all."""
    with pytest.raises(UnknownStateError):
        tp.parse(tp.OrderRow, _row(**{field: "-1"}), "order")


def test_a_fills_sequence_starts_at_zero() -> None:
    assert tp.parse(tp.ExecutionRow, EXEC_ROW | {"seq": 0}, "executions").seq == 0
    with pytest.raises(UnknownStateError):
        tp.parse(tp.ExecutionRow, EXEC_ROW | {"seq": -1}, "executions")


#: Zero-padded, so the digit cap of the venue's decimal text (`_DECIMAL`) and not the amount
#: bound decides: at most 24 whole digits and 18 places, signed by a minus only.
@pytest.mark.parametrize(
    "value", ["0" * 23 + "1", "0." + "0" * 17 + "1", "-1"], ids=["24-digits", "18-places", "minus"]
)
def test_decimal_text_within_its_digit_caps_is_read(value: str) -> None:
    fee = tp.parse(tp.ExecutionRow, EXEC_ROW | {"execFee": value}, "fee").execFee
    assert fee == Decimal(value)


@pytest.mark.parametrize(
    "value", ["0" * 24 + "1", "0." + "0" * 18 + "1", "+1"], ids=["25-digits", "19-places", "plus"]
)
def test_decimal_text_past_its_digit_caps_or_signed_plus_fails_the_row(value: str) -> None:
    with pytest.raises(UnknownStateError):
        tp.parse(tp.ExecutionRow, EXEC_ROW | {"execFee": value}, "fee")


@pytest.mark.parametrize("millis", ["1514764800000", "4102444800000"], ids=["2018", "2100"])
def test_an_exchange_time_on_the_plausible_windows_edges_is_read(millis: str) -> None:
    assert tp.parse(tp.OrderRow, _row(createdTime=millis), "order").createdTime == int(millis)


@pytest.mark.parametrize(
    "millis", ["1514764799999", "4102444800001"], ids=["before-2018", "after-2100"]
)
def test_an_exchange_time_past_the_plausible_windows_edges_fails_the_row(millis: str) -> None:
    with pytest.raises(UnknownStateError):
        tp.parse(tp.OrderRow, _row(createdTime=millis), "order")
