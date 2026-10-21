"""Strict-model unit tests of the trading parsers (G-8, #2877; E8-8, rulings R7 and R12).

Inputs here are unit inputs built from the documented field names, never presented as venue
evidence (ruling R2): the transcribed replies are parsed in `test_contract_trading.py`. They cover
what no transcription shows: refused types, bounds, unknown fields, the per-row owner check and
the shapes the documentation gives no example of (a Partial-mode stop row, a linear position, a
USDT wallet row, a derivatives fee-rate row).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.domain.order_link import ext_key
from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.errors import UnknownStateError
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


@pytest.mark.parametrize(
    ("status", "terminal"),
    [
        ("Filled", True),
        ("Cancelled", True),
        ("Rejected", True),
        ("Deactivated", True),
        ("PartiallyFilledCanceled", True),
        ("Triggered", False),
        ("PartiallyFilled", False),
    ],
)
def test_terminal_statuses_carry_their_time(status: str, terminal: bool) -> None:
    order = tp.to_order(tp.parse(tp.OrderRow, _row(orderStatus=status), "order"), account())
    assert (order.terminal_at is not None) is terminal


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


@pytest.mark.parametrize("rows", [51, 0])
def test_a_page_is_bounded_by_its_limit(rows: int) -> None:
    page = {"category": "linear", "nextPageCursor": "", "list": [_row()] * rows}
    if rows > 50:
        with pytest.raises(UnknownStateError):
            tp.parse(tp.OrderPage, page, "open_orders")
    else:
        assert tp.parse(tp.OrderPage, page, "open_orders").rows == []


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


def test_an_execution_row_maps_with_the_ingest_time() -> None:
    row = {"symbol": "BTCUSDT", "orderId": "e-1", "orderLinkId": link(), "side": "Sell",
           "execFee": "-0.01", "execId": "x-1", "execPrice": "60000", "execQty": "0.01",
           "execType": "Trade", "execTime": T_MS, "feeCurrency": "USDT", "isMaker": True,
           "seq": 7}  # fmt: skip
    fill = tp.to_execution(tp.parse(tp.ExecutionRow, row, "executions"), account(), 42)
    assert (fill.order_link_id, fill.fee, fill.is_maker, fill.ts_ingest, fill.seq) == (
        link(),
        Decimal("-0.01"),
        True,
        42,
        7,
    )
    assert tp.is_fill(row) and not tp.is_fill(row | {"execType": "Funding"})


@pytest.mark.parametrize(
    ("model", "data"),
    [
        (tp.ExecutionRow, {"execPrice": "2000000000000"}),
        (tp.ExecutionRow, {"execFee": "2000000000000000"}),
        (tp.ClosedPnlRow, {"closedPnl": "-2000000000000000"}),
    ],
    ids=["price-over-bound", "amount-over-bound", "negative-amount-over-bound"],
)
def test_an_amount_or_price_past_its_bound_fails_the_reply(
    model: type[tp._Venue], data: dict[str, str]
) -> None:
    with pytest.raises(UnknownStateError):
        tp.parse(model, data, "bounds")
    assert tp._decimal("-999999999999999") == Decimal("-999999999999999")


@pytest.mark.parametrize("data", [[_row()], "row", None, 7])
def test_a_reply_that_is_no_object_fails_without_counting_fields(data: object) -> None:
    before = _unknown("order")
    with pytest.raises(UnknownStateError):
        tp.parse(tp.OrderRow, data, "order")
    assert _unknown("order") == before


def test_account_info_refuses_a_boolean_status() -> None:
    result = {"marginMode": "REGULAR_MARGIN", "unifiedMarginStatus": True, "updatedTime": T_MS}
    with pytest.raises(UnknownStateError):
        tp.parse(tp.AccountInfoResult, result, "account-info")
