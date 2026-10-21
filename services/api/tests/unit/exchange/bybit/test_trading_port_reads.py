"""The trading port's reads (G-8, #2877): pages, windows, the per-row account check (SR-E29-02,
ruling R12) and the account reads. Replies are the transcribed shapes of `rest/trading-*.json`
(ruling R2); where a test needs a value the documentation does not show (a page that ends, a row
under one of our ids), it changes that one field of the transcription and says so.
"""

from __future__ import annotations

import itertools
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.domain.order_link import ext_key
from candleviewer.exchange.base.errors import UnknownStateError
from candleviewer.exchange.base.models import Wallet
from candleviewer.exchange.bybit import trading
from candleviewer.exchange.bybit.metrics import bybit_rows_refused_total
from candleviewer.exchange.bybit.trading import BybitTradingPort
from tests._corpus import rest
from tests.unit.exchange.bybit._trading import (
    ACCOUNT_B,
    DAY_US,
    NOW_US,
    Venue,
    account,
    link,
    make_port,
    with_result,
)

REALTIME = rest("rest/trading-order-realtime.json")
HISTORY = rest("rest/trading-order-history.json")
EXECUTIONS = rest("rest/trading-execution-list.json")
CLOSED = rest("rest/trading-closed-pnl.json")


def _last(page: dict[str, Any]) -> dict[str, Any]:
    """The transcribed page as the walk's last one: its cursor cleared (a test input)."""
    return with_result(page, nextPageCursor="")


def _rows(page: dict[str, Any], **row: Any) -> dict[str, Any]:
    """The transcribed page's first row with `row`'s fields replaced (a test input)."""
    return with_result(page, list=[{**page["result"]["list"][0], **row}])


def _refused(reason: str) -> float:
    value: float = bybit_rows_refused_total.labels(reason=reason)._value.get()
    return value


async def test_the_walk_follows_the_cursor_and_dedupes_by_order() -> None:
    cursor = REALTIME["result"]["nextPageCursor"]
    venue = Venue().on("/v5/order/realtime", REALTIME, _last(REALTIME))

    orders = await make_port(venue).open_orders(account())

    assert [q.get("cursor") for q in venue.queries()] == [None, cursor]
    assert len(orders) == 1  # the same order on both pages is listed once


async def test_a_cursor_that_repeats_is_unknown() -> None:
    venue = Venue().on("/v5/order/realtime", REALTIME)  # the same cursor again and again
    with pytest.raises(UnknownStateError, match="cursor repeats"):
        await make_port(venue).open_orders(account())
    assert len(venue.sent) == 2


async def test_a_walk_past_the_page_bound_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trading, "_MAX_PAGES", 2)
    pages = [_rows(REALTIME, orderId=f"order-{n}") for n in range(3)]
    pages = [with_result(p, nextPageCursor=f"c{n}") for n, p in enumerate(pages)]
    venue = Venue().on("/v5/order/realtime", *pages)
    with pytest.raises(UnknownStateError, match="more pages"):
        await make_port(venue).open_orders(account())
    assert len(venue.sent) == 2  # the bound's pages, and no page past them


async def test_a_walk_of_exactly_the_page_bound_reads_every_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(trading, "_MAX_PAGES", 2)
    first = with_result(_rows(REALTIME, orderId="order-0"), nextPageCursor="c0")
    venue = Venue().on("/v5/order/realtime", first, _last(_rows(REALTIME, orderId="order-1")))
    orders = await make_port(venue).open_orders(account())
    assert [o.exchange_order_id for o in orders] == ["order-0", "order-1"]
    assert len(venue.sent) == 2


async def test_history_without_a_window_is_one_call_in_the_venues_default() -> None:
    venue = Venue().on("/v5/order/history", _last(HISTORY))
    await make_port(venue).order_history(account())
    assert venue.queries() == [{"category": "linear", "settleCoin": "USDT", "limit": "50"}]


@pytest.mark.parametrize(
    ("start", "end", "windows"),
    [
        (NOW_US - 15 * DAY_US, NOW_US, 3),
        (NOW_US - 7 * DAY_US, NOW_US, 1),
        (NOW_US - DAY_US, None, 1),
        (None, NOW_US, 1),
    ],
    ids=["15-days", "7-days", "start-only", "end-only"],
)
async def test_a_history_window_is_split_into_the_venues_7_days(
    start: int | None, end: int | None, windows: int
) -> None:
    venue = Venue().on("/v5/order/history", _last(HISTORY))
    await make_port(venue).order_history(account(), start=start, end=end)
    sent = [(int(q["startTime"]), int(q["endTime"])) for q in venue.queries()]
    assert len(sent) == windows
    assert all(0 <= high - low <= 7 * 86_400_000 for low, high in sent)
    assert all(b[0] == a[1] + 1 for a, b in itertools.pairwise(sent))


#: The venue's 7 days in ms, written out here (the port's own figure is `_WINDOW_MS`).
WEEK_MS = 604_800_000


@pytest.mark.parametrize(
    ("start", "end", "window"),
    [
        (NOW_US - DAY_US, None, ((NOW_US - DAY_US) // 1000, (NOW_US - DAY_US) // 1000 + WEEK_MS)),
        (None, NOW_US, (NOW_US // 1000 - WEEK_MS, NOW_US // 1000)),
    ],
    ids=["start-only", "end-only"],
)
async def test_one_bound_reads_the_venues_own_7_days_from_the_start_or_to_the_end(
    start: int | None, end: int | None, window: tuple[int, int]
) -> None:
    """As the venue answers a call with one bound (24 §14.1): sent as both bounds, never a
    window of no width or one reaching back to the epoch."""
    venue = Venue().on("/v5/order/history", _last(HISTORY))
    await make_port(venue).order_history(account(), start=start, end=end)
    [query] = venue.queries()
    assert (int(query["startTime"]), int(query["endTime"])) == window


async def test_an_order_on_every_window_of_a_history_range_is_listed_once() -> None:
    venue = Venue().on("/v5/order/history", _last(HISTORY))
    orders = await make_port(venue).order_history(account(), start=NOW_US - 15 * DAY_US, end=NOW_US)
    assert len(venue.sent) == 3 and len(orders) == 1


async def test_executions_walk_every_window_of_the_range() -> None:
    venue = Venue().on("/v5/execution/list", _last(EXECUTIONS))
    fills = await make_port(venue).executions(account(), NOW_US - 10 * DAY_US, NOW_US)
    assert len(venue.sent) == 2 and len(fills) == 1  # one fill, deduped across windows
    assert venue.queries()[0]["startTime"] == str((NOW_US - 10 * DAY_US) // 1000)


async def test_a_range_longer_than_the_venue_keeps_is_refused_unsent() -> None:
    venue = Venue()
    with pytest.raises(ValueError, match="longer than the exchange keeps"):
        await make_port(venue).executions(account(), NOW_US - 800 * DAY_US, NOW_US)
    assert venue.sent == []


Read = Callable[[BybitTradingPort], Awaitable[object]]


@pytest.mark.parametrize(
    "read",
    [
        lambda port: port.executions(account(), NOW_US, NOW_US - 1),
        lambda port: port.closed_pnl(account(), NOW_US, NOW_US - 1),
        lambda port: port.order_history(account(), start=NOW_US, end=NOW_US - 1),
    ],
    ids=["executions", "closed_pnl", "order_history"],
)
async def test_a_window_that_ends_before_it_starts_is_refused_unsent(read: Read) -> None:
    venue = Venue()
    with pytest.raises(ValueError, match="start is after end"):
        await read(make_port(venue))
    assert venue.sent == []


@pytest.mark.parametrize("exec_type", ["Funding", "UNKNOWN"])
async def test_a_row_that_fills_no_order_is_set_aside_and_counted(exec_type: str) -> None:
    """The enum lists `Funding` (a fee, not a fill of an order) and `UNKNOWN` (a classic
    account's row, of no named type) as execution types: neither fails the read."""
    row = _last(_rows(EXECUTIONS, execType=exec_type))
    before = _refused("not_a_fill")
    fills = await make_port(Venue().on("/v5/execution/list", row)).executions(
        account(), NOW_US - DAY_US, NOW_US
    )
    assert fills == [] and _refused("not_a_fill") == before + 1


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
async def test_a_type_21_stores_is_read_with_its_order_id_type_and_fee_rate(
    exec_type: str, stored: str
) -> None:
    """24 §8.1: the execution carries the exchange's id of its order, its type as 21 stores it
    and its fee rate, all from the row (`orderId`, `execType`, `feeRate`)."""
    row = _last(_rows(EXECUTIONS, execType=exec_type, symbol="ETHUSDT"))
    [fill] = await make_port(Venue().on("/v5/execution/list", row)).executions(
        account(), NOW_US - DAY_US, NOW_US
    )
    transcribed = EXECUTIONS["result"]["list"][0]
    assert (fill.symbol, fill.exec_type) == ("ETHUSDT", stored)
    assert (fill.exchange_order_id, fill.fee_rate) == (
        transcribed["orderId"],
        Decimal(transcribed["feeRate"]),
    )


@pytest.mark.parametrize(
    "exec_type",
    [
        "Delivery", "BlockTrade", "MovePosition", "FutureSpread", "ForwardSplitSettle",
        "ForwardSplitOpen", "ReverseSplitSettle", "ReverseSplitOpen",
    ],
)  # fmt: skip
async def test_a_documented_type_21_does_not_store_is_set_aside_and_counted(
    exec_type: str,
) -> None:
    """No `exec_type` names it (24 §8.1, `21-database-schema.md` §3.3.6), so it is neither
    mapped by guess nor allowed to fail the read: set aside, counted and logged by type."""
    row = _last(_rows(EXECUTIONS, execType=exec_type))
    before = _refused("unmapped_type")
    with capture_logs() as logs:
        fills = await make_port(Venue().on("/v5/execution/list", row)).executions(
            account(), NOW_US - DAY_US, NOW_US
        )
    assert fills == [] and _refused("unmapped_type") == before + 1
    [line] = [e for e in logs if e["event"] == "bybit_row_refused"]
    assert (line["reason"], line["exec_type"]) == ("unmapped_type", exec_type)


@pytest.mark.parametrize("kind", [["Trade"], {}, 1.5], ids=["list", "object", "number"])
async def test_an_execution_type_that_is_no_text_fails_the_read_as_unknown_state(
    kind: object,
) -> None:
    """A malformed type is the strict model's to refuse (E8-8): never a builtin `TypeError`."""
    row = _last(_rows(EXECUTIONS, execType=kind))
    before = (_refused("not_a_fill"), _refused("unmapped_type"))
    with pytest.raises(UnknownStateError, match="malformed executions reply"):
        await make_port(Venue().on("/v5/execution/list", row)).executions(
            account(), NOW_US - DAY_US, NOW_US
        )
    assert (_refused("not_a_fill"), _refused("unmapped_type")) == before


@pytest.mark.parametrize(
    ("row_link", "reason"),
    [(link(environment="live"), "environment"), (link(ACCOUNT_B), "account")],
)
async def test_a_row_of_another_environment_or_account_is_dropped_and_counted(
    row_link: str, reason: str
) -> None:
    """SR-E29-02, R12: never raised, never adopted; the row's id is logged."""
    page = _last(_rows(REALTIME, orderLinkId=row_link))
    before = _refused(reason)
    with capture_logs() as logs:
        orders = await make_port(Venue().on("/v5/order/realtime", page)).open_orders(account())
    assert orders == [] and _refused(reason) == before + 1
    assert {"event": "bybit_row_refused", "reason": reason, "order_link_id": row_link} in [
        {k: v for k, v in log.items() if k in {"event", "reason", "order_link_id"}} for log in logs
    ]


async def test_a_row_under_one_of_this_accounts_ids_is_kept_as_its_own() -> None:
    page = _last(_rows(REALTIME, orderLinkId=link()))
    [order] = await make_port(Venue().on("/v5/order/realtime", page)).open_orders(account())
    assert (order.order_link_id, order.account_id) == (link(), account().account_id)


async def test_executions_of_another_account_are_dropped_too() -> None:
    page = _last(_rows(EXECUTIONS, orderLinkId=link(ACCOUNT_B)))
    fills = await make_port(Venue().on("/v5/execution/list", page)).executions(
        account(), NOW_US - DAY_US, NOW_US
    )
    assert fills == []


async def test_a_cancel_all_row_of_another_account_is_dropped() -> None:
    reply = rest("rest/trading-cancel-all-reply.json")
    cancelled = reply["result"]["list"]
    foreign = {**cancelled[0], "orderLinkId": link(ACCOUNT_B)}
    mixed = with_result(reply, list=[foreign, cancelled[1]])
    acks = await make_port(Venue().on("/v5/order/cancel-all", mixed)).cancel_all(account(), None)
    assert [a.exchange_order_id for a in acks] == [cancelled[1]["orderId"]]


async def test_a_cancel_all_the_venue_reports_failed_is_unknown() -> None:
    failed = with_result(rest("rest/trading-cancel-all-reply.json"), success="0")
    port = make_port(Venue().on("/v5/order/cancel-all", failed))
    with pytest.raises(UnknownStateError, match="failed"):
        await port.cancel_all(account(), "BTCUSDT")


async def test_positions_take_the_settle_coin_and_refuse_another_category() -> None:
    """The documentation's example is an inverse position: the linear port refuses it."""
    venue = Venue().on("/v5/position/list", rest("rest/trading-position-list.json"))
    with pytest.raises(UnknownStateError, match="malformed positions reply"):
        await make_port(venue).positions(account())
    assert venue.queries() == [{"category": "linear", "settleCoin": "USDT", "limit": "200"}]


async def test_closed_pnl_sets_the_transcribed_usdc_row_aside_and_counts_it() -> None:
    """The documentation's example is a USDC perpetual's (`ETHPERP`): the read takes no settle
    coin, so the port, which reads USDT records only (C-1.2 item 3), never returns it as one."""
    venue = Venue().on("/v5/position/closed-pnl", _last(CLOSED))
    before = _refused("not_usdt")
    with capture_logs() as logs:
        records = await make_port(venue).closed_pnl(account(), NOW_US - DAY_US, NOW_US)
    assert records == [] and _refused("not_usdt") == before + 1
    [line] = [e for e in logs if e["event"] == "bybit_row_refused"]
    assert (line["reason"], line["symbol"]) == ("not_usdt", "ETHPERP")
    assert "settleCoin" not in venue.queries()[0]


async def test_closed_pnl_maps_a_usdt_row_of_the_transcribed_shape() -> None:
    venue = Venue().on("/v5/position/closed-pnl", _last(_rows(CLOSED, symbol="ETHUSDT")))
    [record] = await make_port(venue).closed_pnl(account(), NOW_US - DAY_US, NOW_US)
    assert (record.symbol, record.side, record.qty) == ("ETHUSDT", "sell", Decimal("3"))
    assert record.closed_pnl == Decimal("-47.4065323") and record.order_id is None


async def test_the_wallet_needs_one_unified_usdt_row() -> None:
    """The documentation's example holds one BTC coin row, so it is no USDT wallet."""
    venue = Venue().on("/v5/account/wallet-balance", rest("rest/trading-wallet-balance.json"))
    with pytest.raises(UnknownStateError, match="USDT"):
        await make_port(venue).wallet(account())
    assert venue.queries() == [{"accountType": "UNIFIED", "coin": "USDT"}]


async def test_the_wallet_needs_the_server_time() -> None:
    timeless = {k: v for k, v in rest("rest/trading-wallet-balance.json").items() if k != "time"}
    port = make_port(Venue().on("/v5/account/wallet-balance", timeless))
    with pytest.raises(UnknownStateError, match="server time"):
        await port.wallet(account())


async def test_the_fee_rate_refuses_another_products_rates() -> None:
    """The documentation's example is spot (`category: spot`); derivatives carry no category."""
    venue = Venue().on("/v5/account/fee-rate", rest("rest/trading-fee-rate.json"))
    with pytest.raises(UnknownStateError, match="fee-rate"):
        await make_port(venue).fee_rate(account(), "BTCUSDT")
    assert venue.queries() == [{"category": "linear", "symbol": "BTCUSDT"}]


async def test_account_info_maps_the_transcribed_reply() -> None:
    venue = Venue().on("/v5/account/info", rest("rest/trading-account-info.json"))
    info = await make_port(venue).account_info(account())
    assert (info.margin_mode, info.unified_margin, info.position_mode) == ("regular", True, None)
    assert info.uid == "100001" and venue.queries() == [{}]


async def test_a_history_lookup_by_our_id_sends_it() -> None:
    venue = Venue().on("/v5/order/history", _last(HISTORY))
    assert await make_port(venue).order_history(account(), order_link_id=link()) == []
    assert venue.queries()[0]["orderLinkId"] == link()


async def test_linear_positions_and_a_derivatives_fee_rate_map() -> None:
    """Unit inputs: the documentation gives no linear position or derivatives fee example."""
    row = {**rest("rest/trading-position-list.json")["result"]["list"][0], "symbol": "BTCUSDT"}
    page = {"retCode": 0, "result": {"category": "linear", "nextPageCursor": "", "list": [row]}}
    fee = {"retCode": 0, "result": {"list": [{"symbol": "BTCUSDT", "takerFeeRate": "0.00055",
                                              "makerFeeRate": "0.0002"}]}}  # fmt: skip
    venue = Venue().on("/v5/position/list", page).on("/v5/account/fee-rate", fee)
    port = make_port(venue)
    [position] = await port.positions(account())
    rate = await port.fee_rate(account(), "BTCUSDT")
    assert (position.symbol, position.qty, position.account_id) == (
        "BTCUSDT",
        Decimal("300"),
        account().account_id,
    )
    assert (rate.taker, rate.fetched_at) == (Decimal("0.00055"), NOW_US)


async def test_a_refused_cancel_all_is_one_rejection_naming_no_order() -> None:
    port = make_port(Venue().on("/v5/order/cancel-all", rest("rest/error_10018.json")))
    [ack] = await port.cancel_all(account(), "BTCUSDT")
    assert (ack.ok, ack.order_link_id, ack.error_code) == (False, None, "RATE_LIMITED")


# -- every page's rows, the reads' bounds and their queries ----------------------------------------

#: The transcribed inverse position (`rest/trading-position-list.json`) on a linear page: the
#: documentation shows no linear position, so its symbol and the page's category are test inputs.
POSITIONS = rest("rest/trading-position-list.json")
LINEAR_POSITIONS = with_result(POSITIONS, category="linear", nextPageCursor="")
RowKey = Callable[[Any], str]


@pytest.mark.parametrize(
    ("path", "page", "field", "values", "read", "key"),
    [
        (
            "/v5/order/realtime", REALTIME, "orderId", ("order-a", "order-b"),
            lambda port: port.open_orders(account()), lambda o: o.exchange_order_id,
        ),
        (
            "/v5/execution/list", EXECUTIONS, "execId", ("exec-a", "exec-b"),
            lambda port: port.executions(account(), NOW_US - DAY_US, NOW_US),
            lambda e: e.exec_id,
        ),
        (
            "/v5/position/list", LINEAR_POSITIONS, "symbol", ("BTCUSDT", "ETHUSDT"),
            lambda port: port.positions(account()), lambda p: p.symbol,
        ),
        (
            "/v5/position/closed-pnl", CLOSED, "symbol", ("BTCUSDT", "ETHUSDT"),
            lambda port: port.closed_pnl(account(), NOW_US - DAY_US, NOW_US),
            lambda c: c.symbol,
        ),
    ],
    ids=["open_orders", "executions", "positions", "closed_pnl"],
)  # fmt: skip
async def test_a_walk_returns_every_pages_rows_in_order(
    path: str, page: dict[str, Any], field: str, values: tuple[str, str], read: Read, key: RowKey
) -> None:
    """Row A on the first page, row B on the second (each the transcribed row with one field
    changed, a test input): a read that kept one page only would hide orders, fills or stops
    from reconciliation."""
    row = page["result"]["list"][0]
    first = with_result(page, list=[{**row, field: values[0]}], nextPageCursor="c1")
    second = with_result(page, list=[{**row, field: values[1]}], nextPageCursor="")
    venue = Venue().on(path, first, second)

    rows: Any = await read(make_port(venue))

    assert [key(r) for r in rows] == list(values)
    assert [q.get("cursor") for q in venue.queries()] == [None, "c1"]


# -- several rows in one page: every row is read, and only the ones set aside are dropped ----------


def _page(page: dict[str, Any], *rows: dict[str, Any]) -> dict[str, Any]:
    """The transcribed page holding `rows`, each its first row with fields changed, as the last
    page of the walk (test inputs)."""
    first = page["result"]["list"][0]
    return with_result(page, list=[{**first, **row} for row in rows], nextPageCursor="")


async def test_a_page_mixing_a_funding_row_among_fills_reads_every_fill() -> None:
    """Funding rows sit between fills on the venue's pages: the one set aside is the one
    counted, and every fill after it on the page is read."""
    page = _page(
        EXECUTIONS, {"execType": "Funding", "execId": "exec-f"}, {"execId": "exec-a"},
        {"execId": "exec-b"},
    )  # fmt: skip
    before = _refused("not_a_fill")
    fills = await make_port(Venue().on("/v5/execution/list", page)).executions(
        account(), NOW_US - DAY_US, NOW_US
    )
    assert [f.exec_id for f in fills] == ["exec-a", "exec-b"]
    assert _refused("not_a_fill") == before + 1


async def test_a_page_mixing_another_accounts_order_keeps_every_order_of_this_account() -> None:
    """One row under another account's id, one under this account's and an order placed
    outside the product (no `orderLinkId`): only the first is dropped and counted."""
    page = _page(
        REALTIME, {"orderId": "order-b", "orderLinkId": link(ACCOUNT_B)},
        {"orderId": "order-a", "orderLinkId": link()}, {"orderId": "order-x", "orderLinkId": ""},
    )  # fmt: skip
    before = _refused("account")
    orders = await make_port(Venue().on("/v5/order/realtime", page)).open_orders(account())
    assert [(o.exchange_order_id, o.order_link_id) for o in orders] == [
        ("order-a", link()),
        ("order-x", ext_key("order-x")),
    ]
    assert _refused("account") == before + 1


async def test_a_page_of_positions_is_read_whole_and_in_order() -> None:
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    page = _page(LINEAR_POSITIONS, *({"symbol": symbol} for symbol in symbols))
    positions = await make_port(Venue().on("/v5/position/list", page)).positions(account())
    assert [p.symbol for p in positions] == symbols


async def test_a_closed_pnl_page_sets_a_usdc_row_aside_and_keeps_every_usdt_one() -> None:
    page = _page(CLOSED, {}, {"symbol": "BTCUSDT"}, {"symbol": "ETHUSDT"})  # first: ETHPERP
    before = _refused("not_usdt")
    records = await make_port(Venue().on("/v5/position/closed-pnl", page)).closed_pnl(
        account(), NOW_US - DAY_US, NOW_US
    )
    assert [r.symbol for r in records] == ["BTCUSDT", "ETHUSDT"]
    assert _refused("not_usdt") == before + 1


async def test_a_history_page_of_two_orders_lists_both_in_order() -> None:
    page = _page(HISTORY, {"orderId": "order-a"}, {"orderId": "order-b"})
    orders = await make_port(Venue().on("/v5/order/history", page)).order_history(account())
    assert [o.exchange_order_id for o in orders] == ["order-a", "order-b"]


@pytest.mark.parametrize(
    ("path", "answer", "read", "query"),
    [
        (
            "/v5/order/realtime", _last(REALTIME), lambda port: port.open_orders(account()),
            {"category": "linear", "limit": "50", "settleCoin": "USDT"},
        ),
        (
            "/v5/order/realtime", _last(REALTIME),
            lambda port: port.open_orders(account(), "BTCUSDT"),
            {"category": "linear", "limit": "50", "symbol": "BTCUSDT"},
        ),
        (
            "/v5/position/list", LINEAR_POSITIONS, lambda port: port.positions(account()),
            {"category": "linear", "settleCoin": "USDT", "limit": "200"},
        ),
        (
            "/v5/execution/list", _last(EXECUTIONS),
            lambda port: port.executions(account(), NOW_US - DAY_US, NOW_US),
            {
                "category": "linear", "settleCoin": "USDT", "limit": "100",
                "startTime": str((NOW_US - DAY_US) // 1000), "endTime": str(NOW_US // 1000),
            },
        ),
        (
            "/v5/position/closed-pnl", _last(CLOSED),
            lambda port: port.closed_pnl(account(), NOW_US - DAY_US, NOW_US),
            {
                "category": "linear", "limit": "100",
                "startTime": str((NOW_US - DAY_US) // 1000), "endTime": str(NOW_US // 1000),
            },
        ),
    ],
    ids=["open-orders", "open-orders-by-symbol", "positions", "executions", "closed-pnl"],
)  # fmt: skip
async def test_each_read_sends_its_scope_and_the_venues_page_limit(
    path: str, answer: dict[str, Any], read: Read, query: dict[str, str]
) -> None:
    """A page limit above the venue's maximum fails every such read, and a read without its
    settle coin or symbol is no read of the account's USDT linear book (C-1.2 item 3)."""
    venue = Venue().on(path, answer)
    await read(make_port(venue))
    assert venue.queries() == [query]


async def test_open_orders_of_a_symbol_keep_only_that_symbols_rows() -> None:
    """The symbol goes on the wire and is applied again: the transcribed row is `ETHUSDT`."""
    venue = Venue().on("/v5/order/realtime", _last(REALTIME))
    port = make_port(venue)
    assert await port.open_orders(account(), "BTCUSDT") == []
    [kept] = await port.open_orders(account(), "ETHUSDT")
    assert kept.symbol == "ETHUSDT"


async def test_closed_pnl_walks_every_window_of_the_range() -> None:
    venue = Venue().on("/v5/position/closed-pnl", _last(_rows(CLOSED, symbol="ETHUSDT")))
    records = await make_port(venue).closed_pnl(account(), NOW_US - 15 * DAY_US, NOW_US)
    sent = [(int(q["startTime"]), int(q["endTime"])) for q in venue.queries()]
    assert len(sent) == 3 and len(records) == 3  # one record a window: no dedupe by design
    assert sent[0][0] == (NOW_US - 15 * DAY_US) // 1000 and sent[-1][1] == NOW_US // 1000
    assert all(b[0] == a[1] + 1 for a, b in itertools.pairwise(sent))


def test_a_range_takes_at_most_106_windows_of_7_days() -> None:
    """106 windows of 7 days cover the venue's two years; the 107th is refused, unsent."""
    week_ms = 7 * 86_400_000
    end_ms = NOW_US // 1000
    start_ms = end_ms - (106 * week_ms + 105)  # each later window starts 1 ms past the last
    windows = trading._windows(start_ms * 1000, NOW_US)
    assert len(windows) == 106 and windows[0][0] == start_ms and windows[-1][1] == end_ms
    with pytest.raises(ValueError, match="longer than the exchange keeps"):
        trading._windows((start_ms - 1) * 1000, NOW_US)


def test_a_window_starts_on_the_millisecond_that_holds_its_start() -> None:
    """The start rounds down: a range starting 1 µs into a millisecond still reads it."""
    assert trading._windows(NOW_US + 1, NOW_US + 2_000) == [(NOW_US // 1000, NOW_US // 1000 + 2)]


def test_a_window_ends_on_the_millisecond_that_holds_its_end() -> None:
    """The end rounds up: a range ending 1 µs into a millisecond still reads that millisecond."""
    assert trading._windows(NOW_US, NOW_US + 1) == [(NOW_US // 1000, NOW_US // 1000 + 1)]


async def test_executions_carry_the_ports_ingest_time() -> None:
    venue = Venue().on("/v5/execution/list", _last(EXECUTIONS))
    port = make_port(venue, now_us=lambda: NOW_US + 7)
    [fill] = await port.executions(account(), NOW_US - DAY_US, NOW_US)
    transcribed = EXECUTIONS["result"]["list"][0]
    assert (fill.ts_ingest, fill.ts_exec) == (NOW_US + 7, int(transcribed["execTime"]) * 1000)


async def test_a_unified_usdt_wallet_maps_every_figure_at_the_replys_time() -> None:
    """The transcribed reply's account and envelope with a USDT coin row whose figures all
    differ (test inputs: the documentation's example holds a BTC row only), so a swap shows."""
    reply = rest("rest/trading-wallet-balance.json")
    unified = reply["result"]["list"][0]
    usdt = {
        **unified["coin"][0], "coin": "USDT", "equity": "1000.5", "walletBalance": "990.25",
        "availableToWithdraw": "800", "unrealisedPnl": "10.5", "cumRealisedPnl": "-3",
    }  # fmt: skip
    figures = {
        "accountIMRate": "0.01", "accountMMRate": "0.005", "totalAvailableBalance": "900",
        "totalInitialMargin": "90",
    }  # fmt: skip
    answer = with_result(reply, list=[{**unified, **figures, "coin": [usdt]}])

    wallet = await make_port(Venue().on("/v5/account/wallet-balance", answer)).wallet(account())

    assert wallet == Wallet(
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
        updated_at=reply["time"] * 1000,
    )
