"""E08-X02 (b): semantic attacks on market integrity. Register section B."""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from typing import Any

import pytest

from candleviewer.book.models import BookPhase, BookStatus
from candleviewer.domain.events import Instrument
from candleviewer.exchange.base.models import BookDelta, BookSnapshot, KlineEvent

# nosemgrep: cv-adapter-isolation reason=X02 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.instruments import parse_instruments
from candleviewer.ingestion.instruments import diff_changed_fields
from tests._corpus import rest
from tests.security.ingestion._harness import Rig
from tests.security.ingestion.corpus import TICKERS, TS, book, trade

BIDS = [["100.0", "1"], ["99.9", "2"]]
ASKS = [["100.1", "1"], ["100.2", "2"]]


async def _live(rig: Rig) -> None:
    await rig.feed(book("snapshot", 1, BIDS, ASKS))
    assert rig.books.phase("BTCUSDT") is BookPhase.LIVE
    rig.drain()


def _crossed(objs: list[Any]) -> bool:
    for o in objs:
        if isinstance(o, BookSnapshot) and o.bids and o.asks:
            if max(b.price for b in o.bids) >= min(a.price for a in o.asks):
                return True
    return False


async def test_crossed_delta_desyncs_and_is_never_served() -> None:
    rig = Rig()
    await _live(rig)
    await rig.feed(book("delta", 2, [["100.5", "3"]], []))  # bid above best ask
    out = rig.drain()
    assert not any(isinstance(o, BookDelta) for o in out)
    assert not _crossed(out)
    status = [o for o in out if isinstance(o, BookStatus)]
    assert status and status[-1].reason == "crossed"
    assert rig.books.view("BTCUSDT", 50) is None
    assert list(rig.resubs) == ["orderbook.50.BTCUSDT"]  # resync requested


async def test_crossed_snapshot_never_goes_live() -> None:
    rig = Rig()
    await rig.feed(book("snapshot", 1, [["101.0", "1"]], [["100.0", "1"]]))
    out = rig.drain()
    assert not _crossed(out)
    assert rig.books.view("BTCUSDT", 50) is None


async def test_delete_of_missing_level_is_a_noop() -> None:
    rig = Rig()
    await _live(rig)
    await rig.feed(book("delta", 2, [["50.0", "0"]], []))
    view = rig.books.view("BTCUSDT", 50)
    assert view is not None and [str(b.price) for b in view.snapshot.bids] == ["100.0", "99.9"]


@pytest.mark.parametrize("qty", ["-1", "NaN"])
async def test_negative_or_nan_level_rejected(qty: str) -> None:
    rig = Rig()
    await _live(rig)
    await rig.feed(book("delta", 2, [["99.8", qty]], []))
    assert not any(isinstance(o, BookDelta) for o in rig.drain())


async def test_zero_size_level_in_snapshot_never_goes_live() -> None:
    rig = Rig()
    await rig.feed(book("snapshot", 1, [["100.0", "0"]], ASKS))
    assert rig.books.view("BTCUSDT", 50) is None


@pytest.mark.parametrize("u", [1, 2], ids=["backwards", "repeat"])
async def test_sequence_backwards_or_repeat_resyncs(u: int) -> None:
    rig = Rig()
    await _live(rig)
    await rig.feed(book("delta", 2, [["99.8", "1"]], []))
    rig.drain()
    await rig.feed(book("delta", u, [["99.7", "1"]], []))
    out = rig.drain()
    assert not any(isinstance(o, BookDelta) for o in out)
    assert rig.books.view("BTCUSDT", 50) is None or u == 1  # u==1 is a server reset snapshot


# fixed by #1898 (#1890): off-tick price truncated, level silently lost
async def test_off_tick_price_is_rejected() -> None:
    rig = Rig()
    await rig.feed(book("snapshot", 1, [["100.05", "1"], ["100.0", "2"]], ASKS))
    assert rig.books.view("BTCUSDT", 50) is None


async def test_zero_qty_trade_rejected() -> None:
    rig = Rig()
    await rig.feed(trade(v="0"))
    assert rig.drain() == []


# fixed by #1898 (#1892): trade ts far in the future accepted
async def test_far_future_trade_rejected() -> None:
    rig = Rig()
    await rig.feed(trade(T=TS * 1000))
    assert rig.drain() == []


# fixed by #1898 (#1892): 1e308 trade price accepted as a print
async def test_absurd_trade_price_rejected() -> None:
    rig = Rig()
    await rig.feed(trade(p="1e308"))
    assert rig.drain() == []


# fixed by #1898 (#1892): negative/crossed ticker values accepted
async def test_negative_or_crossed_ticker_rejected() -> None:
    rig = Rig()
    msg = json.loads(TICKERS[0])
    msg["data"].update(lastPrice="-5", bid1Price="10", ask1Price="9")
    await rig.feed(json.dumps(msg))
    assert not [e for e in rig.drain() if type(e).__name__ == "TickerEvent"]


async def test_recorded_ticker_snapshot_publishes() -> None:
    # Control for the case above: the unmutated recorded frame does publish.
    rig = Rig()
    await rig.feed(TICKERS[0])
    assert [e for e in rig.drain() if type(e).__name__ == "TickerEvent"]


# fixed by #1898 (#1892): KlineEvent accepts high < low
def test_kline_high_below_low_rejected() -> None:
    with pytest.raises(ValueError):
        KlineEvent.model_validate(
            {
                "event_id": "00000000-0000-0000-0000-000000000001",
                "ts_event": 1,
                "ts_ingest": 1,
                "source": "live",
                "symbol": "BTCUSDT",
                "interval": "1",
                "start": 0,
                "end": 60_000_000,
                **{"open": 5, "high": 1, "low": 9, "close": 5, "volume": 1, "turnover": 1},
                "confirmed": True,
            }
        )


def _instr(**over: Any) -> tuple[list[Instrument], list[str]]:
    raw = copy.deepcopy(rest("rest/instruments_before.json")["result"]["list"][0])
    raw["priceFilter"].update(over.get("price", {}))
    raw["lotSizeFilter"].update(over.get("lot", {}))
    res = parse_instruments([raw], fetched_at_us=1)
    return list(res.instruments), [r.reason for r in res.rejected]


@pytest.mark.parametrize("tick", ["0", "-0.1", "NaN"])
def test_instrument_tick_size_zero_rejected(tick: str) -> None:
    ok, rejected = _instr(price={"tickSize": tick})
    assert ok == [] and rejected


def test_absurd_min_notional_is_visible_as_change() -> None:
    (base,), _ = _instr()
    (bad,), _ = _instr(lot={"minNotionalValue": "1e12"})
    assert bad.min_notional == Decimal("1e12")
    assert "min_notional" in diff_changed_fields(base, bad)  # surfaced, never silent


@pytest.mark.parametrize(
    "over",
    [
        {"priceFilter": ["x"]},
        {"lotSizeFilter": "x"},
        {"leverageFilter": 1},
        {"status": ["Trading"]},
        {"status": {"a": 1}},
        {"symbol": ["BTCUSDT"]},
        {"symbol": ""},
        {"baseCoin": ["BTC"]},
        {"launchTime": ["1"]},
        {"fundingInterval": None},
        {"fundingInterval": ""},
        {"fundingInterval": True},
        {"fundingInterval": 1.5},
        {"launchTime": True},
        {"priceFilter": {"tickSize": 10**5000}},
        {"lotSizeFilter": {"qtyStep": 10**5000, "minOrderQty": "1", "maxOrderQty": "9"}},
        {"symbol": 10**5000},
        {"fundingInterval": 10**5000},
        {"fundingInterval": 0},
        {"fundingInterval": -480},
    ],
)
def test_malformed_instrument_row_cannot_fail_catalogue(over: dict[str, Any]) -> None:
    """#1896 / #1933: a malformed row is one rejection; every other row still parses."""
    good = rest("rest/instruments_before.json")["result"]["list"]
    res = parse_instruments([{**good[0], **over}, good[1]], fetched_at_us=1)
    assert len(res.instruments) == 1 and len(res.rejected) == 1
    assert res.instruments[0].symbol == good[1]["symbol"]


@pytest.mark.parametrize(
    "over",
    [{"fundingInterval": "9" * 5000}, {"launchTime": "x" * 5000}, {"status": "y" * 5000}],
)
def test_rejection_reason_is_bounded(over: dict[str, Any]) -> None:
    """#1896: the value is hostile, so its size is too; a reason quotes a bounded part of it."""
    good = rest("rest/instruments_before.json")["result"]["list"]
    res = parse_instruments([{**good[0], **over}], fetched_at_us=1)
    assert len(res.rejected) == 1 and len(res.rejected[0].reason) < 300


def test_rejected_symbol_is_bounded() -> None:
    """#1896: the rejection's symbol is logged; an oversized one is not carried."""
    good = rest("rest/instruments_before.json")["result"]["list"]
    res = parse_instruments([{**good[0], "symbol": "S" * 5000, "status": "Bogus"}], fetched_at_us=1)
    assert res.rejected[0].symbol is None


def test_missing_funding_interval_is_rejected_not_defaulted() -> None:
    """#1933: no silent 480; the row is rejected and names the field."""
    good = rest("rest/instruments_before.json")["result"]["list"]
    row = {k: v for k, v in good[0].items() if k != "fundingInterval"}
    res = parse_instruments([row], fetched_at_us=1)
    assert res.instruments == ()
    assert res.rejected[0].symbol == good[0]["symbol"]
    assert "fundingInterval" in res.rejected[0].reason


@pytest.mark.parametrize("row", [["BTCUSDT"], "BTCUSDT", None, 7])
def test_non_object_instrument_row_is_rejected(row: object) -> None:
    """#1896: a list item that is not an object is a rejection, not an escape."""
    good = rest("rest/instruments_before.json")["result"]["list"]
    rows: list[Any] = [row, good[1]]  # hostile input: not every item is an object
    res = parse_instruments(rows, fetched_at_us=1)
    assert len(res.instruments) == 1 and res.rejected[0].symbol is None
