"""Order-path shapes, transcribed from the Bybit v5 documentation (G-8, #2877, ruling R2).

Each `rest/trading-*.json` file is a documented Response Example (or an error-table row), listed
in the corpus manifest with its `source_url` and retrieval date. These tests prove the adapter's
strict parsers read every documented shape, field for field, with no field left unknown
(`cv_bybit_unknown_fields_total`, ruling R7), and that the linear port refuses the documented
examples of another product. The shapes are evidence of the documentation only; E29-K01's
recordings replace them (`test_contract_trading_drift.py`).
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest

from candleviewer.domain.order_link import ext_key
from candleviewer.exchange.base.errors import (
    DuplicateClientIdError,
    NotFoundError,
    UnknownStateError,
)
from candleviewer.exchange.bybit import trading_parse as tp
from candleviewer.exchange.bybit.mapping import map_ret_code
from candleviewer.exchange.bybit.metrics import cv_bybit_unknown_fields_total
from tests._corpus import http_status, manifest, rest
from tests.unit.exchange.bybit._trading import account

TRANSCRIBED = {
    "rest/trading-account-info.json",
    "rest/trading-amend-reply.json",
    "rest/trading-cancel-all-reply.json",
    "rest/trading-cancel-reply.json",
    "rest/trading-closed-pnl.json",
    "rest/trading-create-batch-reply.json",
    "rest/trading-create-reply.json",
    "rest/trading-error-110001.json",
    "rest/trading-error-110072.json",
    "rest/trading-execution-list.json",
    "rest/trading-fee-rate.json",
    "rest/trading-order-history.json",
    "rest/trading-order-realtime.json",
    "rest/trading-position-list.json",
    "rest/trading-set-leverage-reply.json",
    "rest/trading-trading-stop-reply.json",
    "rest/trading-wallet-balance.json",
}


def _counts() -> dict[str, float]:
    return {m: cv_bybit_unknown_fields_total.labels(model=m)._value.get() for m in tp.MODEL_LABELS}


@pytest.fixture
def no_unknown_fields() -> Iterator[None]:
    """Every field of a documented shape is known to its model: none counted as drift."""
    before = _counts()
    yield
    assert _counts() == before


def test_every_transcription_is_listed_with_its_source() -> None:
    entries = {e["path"]: e for e in manifest()["fixtures"] if e["path"] in TRANSCRIBED}
    assert set(entries) == TRANSCRIBED
    for entry in entries.values():
        assert entry["source"] == "docs-transcribed" and entry["retrieved"] == "2026-10-21"
        assert entry["source_url"].startswith("https://bybit-exchange.github.io/docs/v5/")
        assert entry["source_ref"].startswith("github.com/bybit-exchange/docs@")
        assert entry["http_status"] is None  # no documentation page shows its example's status


def test_a_transcription_states_no_http_status_to_replay() -> None:
    with pytest.raises(ValueError, match="states no HTTP status"):
        http_status("rest/trading-create-reply.json")


@pytest.mark.usefixtures("no_unknown_fields")
@pytest.mark.parametrize(
    ("path", "order_id", "raw_link"),
    [
        ("rest/trading-create-reply.json", "1321003749386327552", "spot-test-postonly"),
        ("rest/trading-amend-reply.json", "c6f055d9-7f21-4079-913d-e6523a9cfffa", "linear-004"),
        ("rest/trading-cancel-reply.json", "c6f055d9-7f21-4079-913d-e6523a9cfffa", "linear-004"),
    ],
)
def test_a_trade_reply_names_its_order(path: str, order_id: str, raw_link: str) -> None:
    reply = tp.parse(tp.OrderReply, rest(path)["result"], "reply")
    assert (reply.orderId, reply.orderLinkId) == (order_id, raw_link)
    assert tp.normalised_link(reply.orderLinkId, reply.orderId) == ext_key(order_id)


@pytest.mark.usefixtures("no_unknown_fields")
def test_the_cancel_all_reply_lists_what_it_cancelled() -> None:
    result = tp.parse(tp.CancelAllResult, rest("rest/trading-cancel-all-reply.json")["result"], "x")
    assert [r.orderId for r in result.cancelled] == ["1616024329462743808", "1616024287544869632"]
    assert result.success == "1"


@pytest.mark.usefixtures("no_unknown_fields")
def test_the_batch_reply_pairs_items_with_codes() -> None:
    reply = tp.parse(tp.BatchReply, rest("rest/trading-create-batch-reply.json"), "batch")
    assert [(i.symbol, i.orderLinkId) for i in reply.result.items] == [
        ("BTCUSDT", "spot-btc-03"),
        ("ATOMUSDT", "spot-atom-03"),
    ]
    assert [(c.code, c.msg) for c in reply.retExtInfo.codes] == [(0, "OK"), (0, "OK")]


@pytest.mark.usefixtures("no_unknown_fields")
@pytest.mark.parametrize(
    "path", ["rest/trading-trading-stop-reply.json", "rest/trading-set-leverage-reply.json"]
)
def test_a_position_write_answers_an_empty_result(path: str) -> None:
    body: dict[str, Any] = rest(path)
    assert (body["retCode"], body["result"]) == (0, {})


@pytest.mark.usefixtures("no_unknown_fields")
def test_the_realtime_row_maps_field_for_field() -> None:
    page = tp.parse(tp.OrderPage, rest("rest/trading-order-realtime.json")["result"], "realtime")
    order = tp.to_order(page.rows[0], account())
    assert order.model_dump() == {
        "order_id": None,
        "order_link_id": ext_key("fd4300ae-7847-404e-b947-b46980a4d140"),
        "exchange_order_id": "fd4300ae-7847-404e-b947-b46980a4d140",
        "account_id": account().account_id,
        "symbol": "ETHUSDT",
        "side": "buy",
        "order_type": "limit",
        "qty": Decimal("0.10"),
        "price": Decimal("1600.00"),
        "state": "new",
        "filled_qty": Decimal("0.00"),
        "leaves_qty": Decimal("0.10"),
        "avg_fill_price": None,
        "created_at": 1684738540559000,
        "terminal_at": None,
        "updated_at": 1684738540561000,
        "reduce_only": False,
        "trigger_price": None,
        "stop_loss": Decimal("1500.00"),
        "take_profit": Decimal("2500.00"),
        "tpsl_mode": "full",
        "order_kind": "order",
        "position_idx": 1,
        "time_in_force": "gtc",
        "exchange_placed": False,
    }
    assert page.nextPageCursor.startswith("page_args")


@pytest.mark.usefixtures("no_unknown_fields")
def test_the_history_row_maps_a_cancelled_post_only_order() -> None:
    page = tp.parse(tp.OrderPage, rest("rest/trading-order-history.json")["result"], "history")
    order = tp.to_order(page.rows[0], account())
    assert (order.state, order.time_in_force, order.terminal_at) == (
        "cancelled",
        "post_only",
        1684476068372000,
    )
    assert order.updated_at == order.terminal_at  # an end is the order's last change
    assert (order.tpsl_mode, order.stop_loss, order.take_profit) == (None, None, None)
    assert order.order_link_id == ext_key("14bad3a1-6454-43d8-bcf2-5345896cf74d")


@pytest.mark.usefixtures("no_unknown_fields")
def test_the_execution_row_maps_a_fill_with_an_empty_id() -> None:
    page = tp.parse(tp.ExecutionPage, rest("rest/trading-execution-list.json")["result"], "fills")
    [raw] = page.rows
    assert tp.set_aside(raw) is None
    fill = tp.to_execution(tp.parse(tp.ExecutionRow, raw, "fills"), account(), 7)
    assert (fill.exec_id, fill.symbol, fill.side, fill.price, fill.qty) == (
        "e0cbe81d-0f18-5866-9415-cf319b5dab3b",
        "ETHPERP",
        "buy",
        Decimal("1190.15"),
        Decimal("0.1"),
    )
    assert (fill.fee, fill.fee_currency, fill.is_maker, fill.seq) == (
        Decimal("0.071409"),
        "",
        False,
        4688002127,
    )
    assert fill.order_link_id == ext_key("8c065341-7b52-4ca9-ac2c-37e31ac55c94")
    assert (fill.exchange_order_id, fill.exec_type, fill.fee_rate) == (
        "8c065341-7b52-4ca9-ac2c-37e31ac55c94",
        "trade",
        Decimal("0.0006"),
    )
    assert (fill.ts_exec, fill.ts_ingest) == (1672282722429000, 7)


@pytest.mark.usefixtures("no_unknown_fields")
def test_the_closed_pnl_row_maps_its_closed_size() -> None:
    page = tp.parse(tp.ClosedPnlPage, rest("rest/trading-closed-pnl.json")["result"], "pnl")
    record = tp.to_closed_pnl(tp.parse(tp.ClosedPnlRow, page.rows[0], "pnl"), account())
    assert (record.qty, record.avg_entry_price, record.avg_exit_price) == (
        Decimal("3"),
        Decimal("1194.97516667"),
        Decimal("1180.59833333"),
    )
    assert (record.closed_pnl, record.leverage) == (Decimal("-47.4065323"), Decimal("3"))
    assert (record.opened_at, record.closed_at) == (1672214887231000, 1672214887236000)


@pytest.mark.usefixtures("no_unknown_fields")
def test_the_inverse_position_example_is_refused_by_the_linear_page() -> None:
    result = rest("rest/trading-position-list.json")["result"]
    with pytest.raises(UnknownStateError):
        tp.parse(tp.PositionPage, result, "positions")
    row = tp.parse(tp.PositionRow, result["list"][0], "positions")  # the row's own shape reads
    position = tp.to_position(row, account())
    assert (position.symbol, position.side, position.qty, position.liq_price) == (
        "BTCUSD",
        "sell",
        Decimal("300"),
        None,
    )
    assert (position.stop_loss, position.take_profit, position.trailing_stop_distance) == (
        None,
        None,
        None,
    )


@pytest.mark.usefixtures("no_unknown_fields")
def test_the_wallet_example_reads_but_holds_no_usdt_row() -> None:
    page = tp.parse(tp.WalletPage, rest("rest/trading-wallet-balance.json")["result"], "wallet")
    assert [c.coin for a in page.accounts for c in a.coins] == ["BTC"]
    with pytest.raises(UnknownStateError, match="USDT"):
        tp.to_wallet(page, account(), "USDT", 1690872862481)
    btc = tp.to_wallet(page, account(), "BTC", 1690872862481)
    assert (btc.available_margin, btc.available_to_withdraw) == (Decimal("3.00326056"), Decimal(0))


@pytest.mark.usefixtures("no_unknown_fields")
def test_the_spot_fee_rate_example_is_refused_by_the_linear_page() -> None:
    result = rest("rest/trading-fee-rate.json")["result"]
    with pytest.raises(UnknownStateError):
        tp.parse(tp.FeeRatePage, result, "fee-rate")
    row = tp.parse(tp.FeeRateRow, result["list"][0], "fee-rate")
    assert (row.makerFeeRate, row.takerFeeRate) == (Decimal("0.001"), Decimal("0.001"))


@pytest.mark.usefixtures("no_unknown_fields")
def test_the_account_info_example_maps() -> None:
    result = tp.parse(tp.AccountInfoResult, rest("rest/trading-account-info.json")["result"], "x")
    info = tp.to_account_info(result, account())
    assert (info.margin_mode, info.unified_margin, info.position_mode) == ("regular", True, None)


def test_the_error_rows_map_to_the_taxonomy() -> None:
    duplicate = rest("rest/trading-error-110072.json")
    missing = rest("rest/trading-error-110001.json")
    on_create = map_ret_code(duplicate["retCode"], duplicate["retMsg"], create=True)
    assert isinstance(on_create, DuplicateClientIdError)
    assert isinstance(map_ret_code(missing["retCode"], missing["retMsg"]), NotFoundError)
    assert set(duplicate) == set(missing) == {"retCode", "retMsg"}  # the table shows no more
