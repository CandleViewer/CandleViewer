"""`event_from_row`: the one canonical stored-row -> `RecordedEvent` mapping (E26-T02).

Both tiers go through it, so a row read from QuestDB (PGWire: naive datetime, float) and the
same row read from Parquet (aware datetime, float64) must map to equal events — the basis of
"the straddling window equals a single-tier read" (ticket AC 2).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.exchange.base.models import BookDelta, BookSnapshot
from candleviewer.exchange.base.trade_print import TradePrint
from candleviewer.recorder.writer import delta_records, snapshot_records, trade_records
from candleviewer.storage.errors import StorageRecordInvalid
from candleviewer.storage.models import StreamKind
from candleviewer.storage.repositories.recorded import (
    RecordedBookDelta,
    RecordedBookSnapshot,
    RecordedFunding,
    RecordedKline,
    RecordedLiquidation,
    RecordedOpenInterest,
    RecordedTicker,
    RecordedTrade,
    event_from_row,
    order_key,
)
from tests._corpus import frames, normalize

TS_US = 1_789_000_000_123_456
NAIVE = datetime(1970, 1, 1) + timedelta(microseconds=TS_US)  # PGWire shape (UTC, tz-less)
AWARE = NAIVE.replace(tzinfo=UTC)  # Parquet TIMESTAMP(MICROS, UTC) shape


def _trade(ts: object = NAIVE, **over: object) -> dict[str, object]:
    row: dict[str, object] = {
        "ts": ts,
        "symbol": "BTCUSDT",
        "side": "buy",
        "price": 65000.5,
        "size": 0.001,
        "trade_id": "t-1",
        "is_block": False,
        "seq": 42,
    }
    return row | over


def _delta(**over: object) -> dict[str, object]:
    row: dict[str, object] = {
        "ts": NAIVE,
        "symbol": "BTCUSDT",
        "depth": 200,
        "side": "bid",
        "price": 64999.9,
        "size": 0.0,
        "update_id": 7,
        "cross_seq": 9001,
    }
    return row | over


def test_hot_and_cold_shapes_of_one_trade_map_to_equal_events() -> None:
    hot = event_from_row(StreamKind.TRADES, _trade(ts=NAIVE))
    cold = event_from_row(StreamKind.TRADES, _trade(ts=AWARE))

    assert hot == cold
    assert hot.ts_us == TS_US


def test_integer_microsecond_timestamps_are_accepted() -> None:
    assert event_from_row(StreamKind.TRADES, _trade(ts=TS_US)).ts_us == TS_US


def test_double_prices_become_shortest_round_trip_decimals() -> None:
    event = event_from_row(StreamKind.TRADES, _trade(price=0.1, size=1e-05))

    assert isinstance(event.payload, RecordedTrade)
    assert event.payload.price == Decimal("0.1")
    assert str(event.payload.size) == "0.00001"


def test_float_subclasses_such_as_numpy_doubles_convert_exactly() -> None:
    """Regression: `repr(numpy.float64(x))` is `np.float64(x)`, not a number."""
    import numpy as np

    event = event_from_row(StreamKind.TRADES, _trade(price=np.float64(65000.5)))

    assert isinstance(event.payload, RecordedTrade)
    assert event.payload.price == Decimal("65000.5")


def test_decimal_text_and_integers_convert_exactly() -> None:
    event = event_from_row(StreamKind.TRADES, _trade(price="65000.50", size=3))

    assert isinstance(event.payload, RecordedTrade)
    assert str(event.payload.price) == "65000.50"
    assert event.payload.size == Decimal(3)


def test_trade_seq_is_the_stored_exchange_sequence_and_tiebreak_its_id() -> None:
    event = event_from_row(StreamKind.TRADES, _trade())

    assert (event.seq, event.tiebreak) == (42, ("t-1",))


def test_trade_without_a_stored_sequence_orders_with_seq_zero() -> None:
    assert event_from_row(StreamKind.TRADES, _trade(seq=None)).seq == 0


def test_book_delta_seq_is_the_cross_sequence() -> None:
    event = event_from_row(StreamKind.ORDERBOOK_DELTA, _delta())

    assert event.seq == 9001
    assert event.tiebreak == (7, 200, "bid", Decimal("64999.9"))
    assert event.payload == RecordedBookDelta(200, "bid", Decimal("64999.9"), Decimal(0), 7, 9001)


def test_book_delta_falls_back_to_update_id_without_a_cross_sequence() -> None:
    assert event_from_row(StreamKind.ORDERBOOK_DELTA, _delta(cross_seq=None)).seq == 7


def test_a_book_stream_mixing_cross_seq_and_update_id_rows_keeps_one_total_order() -> None:
    """Rows with and without `cross_seq` can share a stream (a resync snapshot may carry none).
    Each row falls back on its own, so the order is per-row `seq`, then the tiebreak: total and
    storage-order independent (C-2.15), though not cross-sequence-true across provenances."""
    rows = [_delta(update_id=9, cross_seq=3), _delta(update_id=7, cross_seq=None, side="ask")]
    events = [event_from_row(StreamKind.ORDERBOOK_DELTA, row) for row in rows]

    assert [e.seq for e in events] == [3, 7]
    assert sorted(events, key=order_key) == sorted(reversed(events), key=order_key) == events


def test_snapshot_levels_parse_from_text_or_numeric_json() -> None:
    row: dict[str, object] = {
        "ts": NAIVE,
        "symbol": "BTCUSDT",
        "depth": 50,
        "update_id": 11,
        "cross_seq": 12,
        "epoch_id": None,
        "bids": '[["65000.5","1.25"],["65000.4","0.5"]]',
        "asks": "[[65000.6, 2]]",
    }
    event = event_from_row(StreamKind.ORDERBOOK_SNAPSHOT, row)

    assert isinstance(event.payload, RecordedBookSnapshot)
    assert event.payload.bids == (
        (Decimal("65000.5"), Decimal("1.25")),
        (Decimal("65000.4"), Decimal("0.5")),
    )
    assert event.payload.asks == ((Decimal("65000.6"), Decimal(2)),)
    assert (event.seq, event.tiebreak) == (12, (11, 50, -1))


def test_ticker_keeps_unwritten_columns_as_none() -> None:
    row: dict[str, object] = {"ts": NAIVE, "symbol": "BTCUSDT", "last_price": 65000.5}
    event = event_from_row(StreamKind.TICKERS, row)

    assert isinstance(event.payload, RecordedTicker)
    assert event.payload.last_price == Decimal("65000.5")
    assert event.payload.mark_price is None
    assert (event.seq, event.tiebreak) == (0, ())


@pytest.mark.parametrize(
    ("stream", "row", "payload_type", "tiebreak"),
    [
        (
            StreamKind.KLINES,
            {
                "interval": "1",
                "open": 1.0,
                "high": 2.0,
                "low": 0.5,
                "close": 1.5,
                "volume": 10.0,
                "turnover": 15.0,
                "confirmed": True,
            },
            RecordedKline,
            ("1",),
        ),
        (
            StreamKind.LIQUIDATIONS,
            {"side": "sell", "price": 64000.0, "size": 0.2, "batch_index": 3},
            RecordedLiquidation,
            (3, "sell", Decimal("64000.0"), Decimal("0.2")),
        ),
        (
            StreamKind.OPEN_INTEREST,
            {"oi": 51234.5, "oi_value": None, "interval": "1s", "source": "ws_ticker"},
            RecordedOpenInterest,
            ("1s", "ws_ticker"),
        ),
        (
            StreamKind.FUNDING_RATES,
            {"funding_rate": 0.0001, "interval_min": 480, "source": "rest"},
            RecordedFunding,
            (),
        ),
    ],
)
def test_every_other_replayable_stream_maps_to_its_typed_payload(
    stream: StreamKind,
    row: dict[str, object],
    payload_type: type,
    tiebreak: tuple[object, ...],
) -> None:
    event = event_from_row(stream, {"ts": NAIVE, "symbol": "BTCUSDT"} | row)

    assert isinstance(event.payload, payload_type)
    assert (event.stream, event.seq, event.tiebreak) == (stream, 0, tiebreak)


def test_liquidation_without_batch_index_sorts_first_in_its_instant() -> None:
    row = {"ts": NAIVE, "symbol": "BTCUSDT", "side": "buy", "price": 1.0, "size": 1.0}

    assert event_from_row(StreamKind.LIQUIDATIONS, row).tiebreak[0] == -1


def test_missing_required_column_fails_closed_naming_the_column() -> None:
    row = _trade()
    del row["price"]

    with pytest.raises(StorageRecordInvalid, match="price"):
        event_from_row(StreamKind.TRADES, row)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, "not-a-number", object()])
def test_unusable_required_price_fails_closed(bad: object) -> None:
    with pytest.raises(StorageRecordInvalid, match="price"):
        event_from_row(StreamKind.TRADES, _trade(price=bad))


_SNAPSHOT_ROW: dict[str, object] = {
    "ts": NAIVE,
    "symbol": "BTCUSDT",
    "depth": 50,
    "update_id": 1,
    "bids": "[]",
    "asks": "[]",
}


@pytest.mark.parametrize(
    ("stream", "base", "override", "column"),
    [
        (StreamKind.TRADES, _trade(), {"seq": True}, "seq"),
        (StreamKind.TRADES, _trade(), {"seq": "x1"}, "seq"),
        (StreamKind.TRADES, _trade(), {"side": 1}, "side"),
        (StreamKind.TRADES, _trade(), {"trade_id": ""}, "trade_id"),
        (StreamKind.TRADES, _trade(), {"is_block": "yes"}, "is_block"),
        (StreamKind.TRADES, _trade(), {"ts": None}, "ts"),
        (StreamKind.TRADES, _trade(), {"ts": "yesterday"}, "ts"),
        (StreamKind.ORDERBOOK_DELTA, _delta(), {"update_id": None}, "update_id"),
        (StreamKind.ORDERBOOK_SNAPSHOT, _SNAPSHOT_ROW, {"bids": None}, "bids"),
        (StreamKind.ORDERBOOK_SNAPSHOT, _SNAPSHOT_ROW, {"asks": '[["NaN","1"]]'}, "asks"),
    ],
)
def test_wrongly_typed_columns_fail_closed(
    stream: StreamKind, base: dict[str, object], override: dict[str, object], column: str
) -> None:
    with pytest.raises(StorageRecordInvalid, match=column):
        event_from_row(stream, base | override)


def test_non_finite_optional_value_reads_as_missing() -> None:
    row: dict[str, object] = {"ts": NAIVE, "symbol": "BTCUSDT", "mark_price": float("nan")}
    event = event_from_row(StreamKind.TICKERS, row)

    assert isinstance(event.payload, RecordedTicker)
    assert event.payload.mark_price is None


@pytest.mark.parametrize("levels", ["not json", '{"a": 1}', '[["1"]]', '[["1","2","3"]]'])
def test_malformed_snapshot_levels_fail_closed(levels: str) -> None:
    row: dict[str, object] = {
        "ts": NAIVE,
        "symbol": "BTCUSDT",
        "depth": 50,
        "update_id": 1,
        "bids": levels,
        "asks": "[]",
    }
    with pytest.raises(StorageRecordInvalid, match="bids"):
        event_from_row(StreamKind.ORDERBOOK_SNAPSHOT, row)


def test_derived_streams_are_not_replayable() -> None:
    with pytest.raises(StorageRecordInvalid, match="bars"):
        event_from_row(StreamKind.BARS, {"ts": NAIVE, "symbol": "BTCUSDT"})


@given(
    a=st.tuples(st.integers(1, 3), st.sampled_from(["bid", "ask"]), st.integers(1, 4)),
    b=st.tuples(st.integers(1, 3), st.sampled_from(["bid", "ask"]), st.integers(1, 4)),
)
def test_delta_order_key_is_unique_per_natural_key(
    a: tuple[int, str, int], b: tuple[int, str, int]
) -> None:
    """Distinct dedup keys never collide on `(ts_us, seq, tiebreak)` (a total order)."""
    ea = event_from_row(StreamKind.ORDERBOOK_DELTA, _delta(update_id=a[0], side=a[1], price=a[2]))
    eb = event_from_row(StreamKind.ORDERBOOK_DELTA, _delta(update_id=b[0], side=b[1], price=b[2]))

    assert ((ea.ts_us, ea.seq, ea.tiebreak) == (eb.ts_us, eb.seq, eb.tiebreak)) == (a == b)


#: Columns QuestDB stores as DOUBLE (21 Sec.4): read back over PGWire as Python floats.
_DOUBLE = frozenset({"price", "size", "notional"})


def _as_stored(row: dict[str, object]) -> dict[str, object]:
    """The same recorded row as QuestDB returns it: DOUBLE columns come back as floats."""
    return {k: float(str(v)) if k in _DOUBLE else v for k, v in row.items()}


def test_recorded_trades_map_back_to_their_exact_values() -> None:
    """Recorded corpus -> production parser -> the E16 recorder's row -> `event_from_row`."""
    prints = [
        ev
        for frame in frames("ws/clean_publicTrade_BTCUSDT.jsonl")
        for ev in normalize(frame)
        if isinstance(ev, TradePrint)
    ]
    assert len(prints) > 100

    for seq, tp in enumerate(prints, start=1):
        bus_event = SimpleNamespace(  # the `TradeLike` fields the recorder reads off the bus
            symbol=tp.symbol,
            ts_event=tp.ts_event_us,
            side=tp.side,
            price=tp.price,
            qty=tp.qty,
            notional=tp.price * tp.qty,
            trade_id=tp.trade_id,
            is_block_trade=tp.is_block_trade,
            seq=seq,
        )
        (record,) = trade_records(bus_event)
        for row in (record.row, _as_stored(record.row)):
            got = event_from_row(StreamKind.TRADES, row)
            assert isinstance(got.payload, RecordedTrade)
            assert (got.ts_us, got.seq, got.tiebreak) == (tp.ts_event_us, seq, (tp.trade_id,))
            assert (got.payload.price, got.payload.size) == (tp.price, tp.qty)


def test_recorded_book_frames_map_back_to_their_exact_levels() -> None:
    books = [
        ev
        for frame in frames("ws/orderbook_BTCUSDT.jsonl")[:300]
        for ev in normalize(frame)
        if isinstance(ev, BookSnapshot | BookDelta)
    ]
    assert any(isinstance(ev, BookSnapshot) for ev in books)
    assert any(isinstance(ev, BookDelta) for ev in books)

    for ev in books:
        if isinstance(ev, BookSnapshot):
            (record,) = snapshot_records(ev)
            snap = event_from_row(StreamKind.ORDERBOOK_SNAPSHOT, record.row)
            assert isinstance(snap.payload, RecordedBookSnapshot)
            assert snap.payload.bids == tuple((lv.price, lv.qty) for lv in ev.bids)
            assert snap.payload.asks == tuple((lv.price, lv.qty) for lv in ev.asks)
            assert snap.seq == ev.cross_seq
            continue
        levels = [(lv.price, lv.qty) for lv in (*ev.bids, *ev.asks)]
        for (price, qty), record in zip(levels, delta_records(ev), strict=True):
            got = event_from_row(StreamKind.ORDERBOOK_DELTA, _as_stored(record.row))
            assert isinstance(got.payload, RecordedBookDelta)
            assert (got.payload.price, got.payload.size) == (price, qty)
            assert (got.seq, got.payload.update_id) == (ev.cross_seq, ev.update_id)
