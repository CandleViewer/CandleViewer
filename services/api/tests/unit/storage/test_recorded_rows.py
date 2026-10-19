"""`event_from_row`: the one canonical stored-row -> `RecordedEvent` mapping (E26-T02).

Both tiers go through it, so a row read from QuestDB (PGWire: naive datetime, float) and the
same row read from Parquet (aware datetime, float64) must map to equal events — the basis of
"the straddling window equals a single-tier read" (ticket AC 2). `seq` and `tiebreak` order
events within one `(symbol, stream)` only: `trades.seq` is the recorder's ingest counter and
book `cross_seq` the exchange's sequence, so streams sharing an instant are ordered by the
replay's stream ordinal, never by comparing their `seq`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
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
from candleviewer.storage.natural_keys import NATURAL_KEY
from candleviewer.storage.repositories.recorded import (
    REPLAYABLE_STREAMS,
    RecordedBookDelta,
    RecordedBookSnapshot,
    RecordedEvent,
    RecordedFunding,
    RecordedKline,
    RecordedLiquidation,
    RecordedOpenInterest,
    RecordedPayload,
    RecordedTicker,
    RecordedTrade,
    Tiebreak,
    event_from_row,
    order_key,
)
from tests._corpus import frames, normalize

D = Decimal
TS_US = 1_789_000_000_123_456
NAIVE = datetime(1970, 1, 1) + timedelta(microseconds=TS_US)  # PGWire shape (UTC, tz-less)
AWARE = NAIVE.replace(tzinfo=UTC)  # Parquet TIMESTAMP(MICROS, UTC) shape
NEXT_FUNDING_US = TS_US + 8 * 3_600_000_000


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


def _snapshot(**over: object) -> dict[str, object]:
    row: dict[str, object] = {
        "ts": NAIVE,
        "symbol": "BTCUSDT",
        "depth": 50,
        "update_id": 1,
        "bids": "[]",
        "asks": "[]",
    }
    return row | over


def _liquidation(**over: object) -> dict[str, object]:
    row: dict[str, object] = {
        "ts": NAIVE,
        "symbol": "BTCUSDT",
        "side": "buy",
        "price": 1.0,
        "size": 1.0,
    }
    return row | over


class _WrappedReprFloat(float):
    """A driver float subclass whose `repr` is not decimal text, like numpy 2's float64."""

    def __repr__(self) -> str:
        return f"np.float64({float.__repr__(self)})"


def test_hot_and_cold_shapes_of_one_trade_map_to_equal_events() -> None:
    hot = event_from_row(StreamKind.TRADES, _trade(ts=NAIVE))
    cold = event_from_row(StreamKind.TRADES, _trade(ts=AWARE))

    assert hot == cold
    assert hot.ts_us == TS_US


def test_double_prices_become_shortest_round_trip_decimals() -> None:
    event = event_from_row(StreamKind.TRADES, _trade(price=0.1, size=1e-05))

    assert isinstance(event.payload, RecordedTrade)
    assert event.payload.price == Decimal("0.1")
    assert str(event.payload.size) == "0.00001"


def test_a_float_subclass_with_a_wrapped_repr_converts_by_its_value() -> None:
    """Regression: `Decimal(repr(np.float64(0.1)))` raised a bare `InvalidOperation`."""
    event = event_from_row(StreamKind.TRADES, _trade(price=_WrappedReprFloat(0.1)))

    assert isinstance(event.payload, RecordedTrade)
    assert str(event.payload.price) == "0.1"


def test_decimal_text_and_integers_convert_exactly() -> None:
    event = event_from_row(StreamKind.TRADES, _trade(price="65000.50", size=3))

    assert isinstance(event.payload, RecordedTrade)
    assert str(event.payload.price) == "65000.50"
    assert event.payload.size == Decimal(3)


def test_trade_seq_is_the_stored_ingest_counter_and_tiebreak_its_id() -> None:
    """`trades.seq` is the recorder's per-process, per-symbol ingest counter (24 Sec.2.1),
    meaningful within the trades stream only."""
    event = event_from_row(StreamKind.TRADES, _trade())

    assert (event.seq, event.tiebreak) == (42, ("t-1",))


def test_trade_without_a_stored_ingest_counter_orders_with_seq_zero() -> None:
    assert event_from_row(StreamKind.TRADES, _trade(seq=None)).seq == 0


def test_book_delta_seq_is_the_exchange_cross_sequence() -> None:
    event = event_from_row(StreamKind.ORDERBOOK_DELTA, _delta())

    assert (event.seq, event.tiebreak) == (9001, (7, 200, "bid", Decimal("64999.9")))


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


#: One stored row per replayable stream, every column a distinct value, so a mapper that reads
#: the wrong column, swaps two columns or drops one cannot produce the expected event.
_ROWS: dict[StreamKind, dict[str, object]] = {
    StreamKind.TRADES: {
        "side": "sell",
        "price": 65000.5,
        "size": 0.25,
        "trade_id": "t-9",
        "is_block": True,
        "seq": 42,
    },
    StreamKind.ORDERBOOK_DELTA: {
        "depth": 200,
        "side": "ask",
        "price": 64999.9,
        "size": 1.5,
        "update_id": 7,
        "cross_seq": 9001,
    },
    StreamKind.ORDERBOOK_SNAPSHOT: {
        "depth": 50,
        "update_id": 11,
        "cross_seq": 12,
        "epoch_id": 3,
        "bids": '[["65000.5","1.25"]]',
        "asks": "[[65000.6, 2]]",
    },
    StreamKind.TICKERS: {
        "last_price": 65000.5,
        "mark_price": 65001.25,
        "index_price": 64999.75,
        "bid1_price": 65000.0,
        "bid1_size": 1.5,
        "ask1_price": 65000.1,
        "ask1_size": 2.25,
        "open_interest": 51234.5,
        "funding_rate": 0.0001,
        "open_interest_value": 3330000000.5,
        "turnover_24h": 987654321.25,
        "volume_24h": 15234.75,
        "price_24h_pcnt": -0.0125,
        "next_funding_ts": NAIVE + timedelta(hours=8),
    },
    StreamKind.KLINES: {
        "interval": "5",
        "open": 1.5,
        "high": 4.5,
        "low": 0.5,
        "close": 2.5,
        "volume": 10.25,
        "turnover": 15.75,
        "confirmed": True,
    },
    StreamKind.LIQUIDATIONS: {"side": "buy", "price": 64000.5, "size": 0.2, "batch_index": 3},
    StreamKind.OPEN_INTEREST: {
        "oi": 51234.5,
        "oi_value": 3330000000.5,
        "interval": "5min",
        "source": "rest",
    },
    StreamKind.FUNDING_RATES: {"funding_rate": 0.0001, "interval_min": 480, "source": "rest"},
}

_TICKER = RecordedTicker(
    D("65000.5"),
    D("65001.25"),
    D("64999.75"),
    D("65000.0"),
    D("1.5"),
    D("65000.1"),
    D("2.25"),
    D("51234.5"),
    D("0.0001"),
    D("3330000000.5"),
    D("987654321.25"),
    D("15234.75"),
    D("-0.0125"),
    NEXT_FUNDING_US,
)

#: `(seq, tiebreak, payload)` each `_ROWS` entry must map to.
_MAPPED: dict[StreamKind, tuple[int, Tiebreak, RecordedPayload]] = {
    StreamKind.TRADES: (42, ("t-9",), RecordedTrade("sell", D("65000.5"), D("0.25"), "t-9", True)),
    StreamKind.ORDERBOOK_DELTA: (
        9001,
        (7, 200, "ask", D("64999.9")),
        RecordedBookDelta(200, "ask", D("64999.9"), D("1.5"), 7, 9001),
    ),
    StreamKind.ORDERBOOK_SNAPSHOT: (
        12,
        (11, 50, 3),
        RecordedBookSnapshot(50, 11, 12, ((D("65000.5"), D("1.25")),), ((D("65000.6"), D(2)),)),
    ),
    StreamKind.TICKERS: (0, (), _TICKER),
    StreamKind.KLINES: (
        0,
        ("5",),
        RecordedKline("5", D("1.5"), D("4.5"), D("0.5"), D("2.5"), D("10.25"), D("15.75"), True),
    ),
    StreamKind.LIQUIDATIONS: (
        0,
        (3, "buy", D("64000.5"), D("0.2")),
        RecordedLiquidation("buy", D("64000.5"), D("0.2"), 3),
    ),
    StreamKind.OPEN_INTEREST: (
        0,
        ("5min", "rest"),
        RecordedOpenInterest(D("51234.5"), D("3330000000.5"), "5min", "rest"),
    ),
    StreamKind.FUNDING_RATES: (0, (), RecordedFunding(D("0.0001"), 480, "rest")),
}


def _stored(stream: StreamKind, **over: object) -> dict[str, object]:
    return {"ts": NAIVE, "symbol": "BTCUSDT"} | _ROWS[stream] | over


@pytest.mark.parametrize("stream", REPLAYABLE_STREAMS)
def test_each_stream_maps_its_row_to_the_whole_expected_event(stream: StreamKind) -> None:
    seq, tiebreak, payload = _MAPPED[stream]

    event = event_from_row(stream, _stored(stream))

    assert event == RecordedEvent(TS_US, seq, "BTCUSDT", stream, tiebreak, payload)


@pytest.mark.parametrize("confirmed", [None, False])
def test_a_kline_without_a_true_confirm_flag_is_unconfirmed(confirmed: bool | None) -> None:
    event = event_from_row(StreamKind.KLINES, _stored(StreamKind.KLINES, confirmed=confirmed))

    assert isinstance(event.payload, RecordedKline)
    assert event.payload.confirmed is False


def test_open_interest_without_a_source_keeps_none_in_the_payload() -> None:
    """Only the tiebreak reads a missing `source` as "" (to stay comparable)."""
    event = event_from_row(StreamKind.OPEN_INTEREST, _stored(StreamKind.OPEN_INTEREST, source=None))

    assert isinstance(event.payload, RecordedOpenInterest)
    assert (event.payload.source, event.tiebreak) == (None, ("5min", ""))


def test_ticker_keeps_unwritten_columns_as_none() -> None:
    row: dict[str, object] = {"ts": NAIVE, "symbol": "BTCUSDT", "last_price": 65000.5}

    event = event_from_row(StreamKind.TICKERS, row)

    assert event.payload == RecordedTicker(
        D("65000.5"), None, None, None, None, None, None, None, None
    )


def test_liquidation_without_batch_index_sorts_first_in_its_instant() -> None:
    assert event_from_row(StreamKind.LIQUIDATIONS, _liquidation()).tiebreak[0] == -1


def test_snapshot_without_epoch_id_reads_it_as_minus_one_in_the_tiebreak() -> None:
    event = event_from_row(StreamKind.ORDERBOOK_SNAPSHOT, _snapshot(cross_seq=12))

    assert (event.seq, event.tiebreak) == (12, (1, 50, -1))


def test_snapshot_levels_parse_from_text_or_numeric_json() -> None:
    row = _snapshot(bids='[["65000.5","1.25"],["65000.4","0.5"]]', asks="[[65000.6, 2]]")

    event = event_from_row(StreamKind.ORDERBOOK_SNAPSHOT, row)

    assert isinstance(event.payload, RecordedBookSnapshot)
    assert event.payload.bids == ((D("65000.5"), D("1.25")), (D("65000.4"), D("0.5")))
    assert event.payload.asks == ((D("65000.6"), D(2)),)


def test_missing_required_column_fails_closed_naming_the_column() -> None:
    row = _trade()
    del row["price"]

    with pytest.raises(StorageRecordInvalid, match="price"):
        event_from_row(StreamKind.TRADES, row)


def test_a_numeric_string_in_an_int_column_reads_as_its_value() -> None:
    """The int fast path takes `int` itself only: text a driver hands back for a LONG still
    reads exactly, by the slower path."""
    assert event_from_row(StreamKind.TRADES, _trade(seq="42")).seq == 42


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, "not-a-number", object()])
def test_unusable_required_price_fails_closed(bad: object) -> None:
    with pytest.raises(StorageRecordInvalid, match="price"):
        event_from_row(StreamKind.TRADES, _trade(price=bad))


@pytest.mark.parametrize(
    ("stream", "row", "column"),
    [
        (StreamKind.TRADES, _trade(seq=True), "seq"),
        (StreamKind.TRADES, _trade(seq="x1"), "seq"),
        (StreamKind.TRADES, _trade(side=1), "side"),
        (StreamKind.TRADES, _trade(trade_id=""), "trade_id"),
        (StreamKind.TRADES, _trade(is_block="yes"), "is_block"),
        (StreamKind.TRADES, _trade(ts=None), "ts"),
        (StreamKind.TRADES, _trade(ts="yesterday"), "ts"),
        (StreamKind.TRADES, _trade(ts=True), "ts"),  # a bool is not epoch µs: no int fast path
        (StreamKind.ORDERBOOK_DELTA, _delta(update_id=None), "update_id"),
        (StreamKind.ORDERBOOK_SNAPSHOT, _snapshot(bids=None), "bids"),
        (StreamKind.ORDERBOOK_SNAPSHOT, _snapshot(asks='[["NaN","1"]]'), "asks"),
        (
            StreamKind.TICKERS,
            _stored(StreamKind.TICKERS, next_funding_ts="soon"),
            "next_funding_ts",
        ),
    ],
)
def test_wrongly_typed_columns_fail_closed(
    stream: StreamKind, row: dict[str, object], column: str
) -> None:
    with pytest.raises(StorageRecordInvalid, match=column):
        event_from_row(stream, row)


@pytest.mark.parametrize(
    ("stream", "row"),
    [
        (StreamKind.TRADES, _trade(side="Buy")),
        (StreamKind.TRADES, _trade(side="bid")),
        (StreamKind.ORDERBOOK_DELTA, _delta(side="buy")),
        (StreamKind.LIQUIDATIONS, _liquidation(side="long")),
    ],
)
def test_a_side_outside_its_closed_set_fails_closed(
    stream: StreamKind, row: dict[str, object]
) -> None:
    with pytest.raises(StorageRecordInvalid, match="side"):
        event_from_row(stream, row)


@pytest.mark.parametrize(
    ("stream", "row", "column"),
    [
        (StreamKind.ORDERBOOK_SNAPSHOT, _snapshot(epoch_id=-1), "epoch_id"),
        (StreamKind.LIQUIDATIONS, _liquidation(batch_index=-1), "batch_index"),
    ],
)
def test_a_negative_id_that_would_tie_with_the_missing_sentinel_fails_closed(
    stream: StreamKind, row: dict[str, object], column: str
) -> None:
    with pytest.raises(StorageRecordInvalid, match=column):
        event_from_row(stream, row)


@pytest.mark.parametrize(
    ("stream", "row", "column"),
    [
        (StreamKind.TRADES, _trade(seq="s3cr3t"), "seq"),
        (StreamKind.TRADES, _trade(price="s3cr3t"), "price"),
        (StreamKind.TRADES, _trade(ts="s3cr3t"), "ts"),
        (StreamKind.ORDERBOOK_SNAPSHOT, _snapshot(bids="s3cr3t"), "bids"),
    ],
)
def test_a_failed_conversion_chains_no_exception_carrying_the_stored_value(
    stream: StreamKind, row: dict[str, object], column: str
) -> None:
    with pytest.raises(StorageRecordInvalid, match=column) as caught:
        event_from_row(stream, row)

    assert (caught.value.__cause__, caught.value.__context__) == (None, None)
    assert "s3cr3t" not in str(caught.value)


def test_non_finite_optional_value_reads_as_missing() -> None:
    row: dict[str, object] = {"ts": NAIVE, "symbol": "BTCUSDT", "mark_price": float("nan")}
    event = event_from_row(StreamKind.TICKERS, row)

    assert isinstance(event.payload, RecordedTicker)
    assert event.payload.mark_price is None


@pytest.mark.parametrize("levels", ["not json", '{"a": 1}', '[["1"]]', '[["1","2","3"]]'])
def test_malformed_snapshot_levels_fail_closed(levels: str) -> None:
    with pytest.raises(StorageRecordInvalid, match="bids"):
        event_from_row(StreamKind.ORDERBOOK_SNAPSHOT, _snapshot(bids=levels))


def test_derived_streams_are_not_replayable() -> None:
    with pytest.raises(StorageRecordInvalid, match="bars"):
        event_from_row(StreamKind.BARS, {"ts": NAIVE, "symbol": "BTCUSDT"})


def _as_tiebreak_value(value: object) -> object:
    return Decimal(repr(value)) if isinstance(value, float) else value


@pytest.mark.parametrize("stream", REPLAYABLE_STREAMS)
def test_the_tiebreak_covers_the_rest_of_the_stream_natural_key(stream: StreamKind) -> None:
    """Drift guard against `storage/natural_keys.py` (the QuestDB `DEDUP UPSERT KEYS`): the
    tiebreak holds every dedup-key column but `ts` and `symbol`, so distinct rows of one
    `(symbol, stream)` never tie on `order_key`."""
    rest = [column for column in NATURAL_KEY[stream] if column not in {"ts", "symbol"}]
    assert set(rest) <= set(_ROWS[stream]), "sample row lacks a natural-key column"

    event = event_from_row(stream, _stored(stream))

    assert {_as_tiebreak_value(_ROWS[stream][column]) for column in rest} <= set(event.tiebreak)


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

    assert (order_key(ea) == order_key(eb)) == (a == b)


#: Small per-column value pools, so generated rows of one stream share instants and ids often.
_POOLS: dict[StreamKind, dict[str, tuple[object, ...]]] = {
    StreamKind.TRADES: {
        "side": ("buy", "sell"),
        "price": (1.5, 2.5),
        "size": (0.5,),
        "trade_id": ("a", "b", "c"),
        "seq": (None, 1, 2),
    },
    StreamKind.ORDERBOOK_DELTA: {
        "depth": (50, 200),
        "side": ("bid", "ask"),
        "price": (1.5, 2.5),
        "size": (0.0, 0.5),
        "update_id": (1, 2),
        "cross_seq": (None, 1, 2),
    },
    StreamKind.ORDERBOOK_SNAPSHOT: {
        "depth": (50, 200),
        "update_id": (1, 2),
        "cross_seq": (None, 1, 2),
        "epoch_id": (None, 0, 1),
        "bids": ("[]",),
        "asks": ("[]",),
    },
    StreamKind.TICKERS: {"last_price": (None, 1.5, 2.5)},
    StreamKind.KLINES: {
        "interval": ("1", "5"),
        "open": (1.5,),
        "high": (2.5,),
        "low": (0.5,),
        "close": (1.5,),
        "volume": (1.0, 2.0),
    },
    StreamKind.LIQUIDATIONS: {
        "side": ("buy", "sell"),
        "price": (1.5, 2.5),
        "size": (0.5, 1.5),
        "batch_index": (None, 0, 1),
    },
    StreamKind.OPEN_INTEREST: {
        "oi": (1.5, 2.5),
        "interval": ("1s", "5min"),
        "source": (None, "ws_ticker", "rest"),
    },
    StreamKind.FUNDING_RATES: {"funding_rate": (0.0001, 0.0002), "interval_min": (None, 480)},
}


@st.composite
def _rows_of(draw: st.DrawFn, stream: StreamKind) -> list[dict[str, object]]:
    """Rows of `stream` with distinct natural keys, as dedup leaves them in storage."""
    pools = {"ts": (TS_US, TS_US + 1, TS_US + 2), "symbol": ("BTCUSDT",), **_POOLS[stream]}
    row = st.fixed_dictionaries({column: st.sampled_from(vals) for column, vals in pools.items()})
    key = NATURAL_KEY[stream]
    return draw(st.lists(row, min_size=2, max_size=8, unique_by=lambda r: tuple(r[c] for c in key)))


@pytest.mark.parametrize("stream", REPLAYABLE_STREAMS)
@given(data=st.data())
def test_sorting_one_stream_by_order_key_is_independent_of_storage_order(
    stream: StreamKind, data: st.DataObject
) -> None:
    events = [event_from_row(stream, row) for row in data.draw(_rows_of(stream))]

    shuffled = data.draw(st.permutations(events))

    assert sorted(shuffled, key=order_key) == sorted(events, key=order_key)


@given(ts_us=st.integers(min_value=0, max_value=4_102_444_800_000_000))
def test_naive_aware_and_integer_timestamps_of_one_instant_map_equal(ts_us: int) -> None:
    """PGWire (naive UTC), Parquet (aware), another offset and ILP (int) shapes, for `ts` and
    for `next_funding_ts`."""
    naive = datetime(1970, 1, 1) + timedelta(microseconds=ts_us)
    aware = naive.replace(tzinfo=UTC)
    shapes = (naive, aware, aware.astimezone(timezone(timedelta(hours=5, minutes=30))), ts_us)

    events = [
        event_from_row(
            StreamKind.TICKERS, {"ts": shape, "symbol": "BTCUSDT", "next_funding_ts": shape}
        )
        for shape in shapes
    ]

    assert all(event == events[0] for event in events)
    assert isinstance(events[0].payload, RecordedTicker)
    assert (events[0].ts_us, events[0].payload.next_funding_ts) == (ts_us, ts_us)


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
