"""E08-Q02 / E08-TC-C01: `tickers` snapshot + delta frames -> merged `TickerEvent`."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.exchange.base.models import TickerEvent
from candleviewer.exchange.base.ticker_delta import TICKER_FIELDS, TickerDelta
from candleviewer.exchange.bybit.ticker import parse_ticker_frame
from candleviewer.ingestion.ticker_stream import TickerMerger
from tests._corpus import frames

FULL = "ws/tickers_BTCUSDT.jsonl"
BURST = "ws/burst_tickers_BTCUSDT.jsonl"
INGEST_US = 1_700_000_000_500_000


def _deltas(rel: str) -> list[TickerDelta]:
    out = []
    for raw in frames(rel):
        d = parse_ticker_frame(raw)
        assert d is not None
        out.append(d)
    return out


def test_snapshot_frame_maps_every_wire_field_to_an_internal_name() -> None:
    snap = _deltas(FULL)[0]
    assert snap.is_snapshot and snap.symbol == "BTCUSDT"
    assert snap.ts_event_us == json.loads(frames(FULL)[0])["ts"] * 1000
    assert set(snap.fields) == set(TICKER_FIELDS)
    assert snap.fields["last_price"] == Decimal("63120.50")
    assert snap.fields["bid1_qty"] == Decimal("12.501")  # wire `bid1Size`
    assert snap.fields["next_funding_time"] == 1_700_006_400_000_000  # ms -> us
    assert all(isinstance(v, Decimal | int) for v in snap.fields.values())


def test_delta_carries_only_the_keys_present_on_the_wire() -> None:
    deltas = _deltas(FULL)
    assert not deltas[1].is_snapshot and set(deltas[1].fields) == {"last_price"}
    assert set(deltas[2].fields) == {"bid1_price", "bid1_qty", "funding_rate"}


def test_merge_keeps_unchanged_fields_and_applies_explicit_zero() -> None:
    events: list[TickerEvent] = []
    merger = TickerMerger()
    for d in _deltas(FULL):
        ev = merger.apply(d, ts_ingest_us=INGEST_US)
        assert isinstance(ev, TickerEvent) and ev.is_delta is False
        events.append(ev)
    snap, d1, d2 = events
    assert d1.last_price == Decimal("63121.00") and d1.mark_price == snap.mark_price
    assert d1.funding_rate == snap.funding_rate and d1.open_interest == snap.open_interest
    assert d2.last_price == d1.last_price  # untouched by delta 2
    assert d2.bid1_price == Decimal("63121.00")
    assert d2.bid1_qty == Decimal("0") and d2.funding_rate == Decimal("0")  # explicit 0 != absent


def test_delta_before_any_snapshot_yields_nothing_never_a_half_empty_event() -> None:
    merger = TickerMerger()
    assert merger.apply(_deltas(FULL)[1], ts_ingest_us=INGEST_US) is None


def test_snapshot_resets_state_so_stale_fields_cannot_leak() -> None:
    merger = TickerMerger()
    d = _deltas(FULL)
    merger.apply(d[0], ts_ingest_us=INGEST_US)
    merger.apply(d[2], ts_ingest_us=INGEST_US)
    again = merger.apply(d[0], ts_ingest_us=INGEST_US)
    assert again is not None and again.bid1_qty == Decimal("12.501")


@given(n=st.integers(min_value=1, max_value=600))
@settings(max_examples=25, deadline=None)
def test_burst_merge_equals_last_write_wins_over_the_prefix(n: int) -> None:
    """Invariant: after any prefix of the delta-only burst the merged `last_price` is the last
    value on the wire and every other field still equals the snapshot's."""
    deltas = _deltas(BURST)
    merger = TickerMerger()
    ev = None
    for d in deltas[: n + 1]:
        ev = merger.apply(d, ts_ingest_us=INGEST_US)
    assert ev is not None
    assert ev.last_price == deltas[n].fields["last_price"]
    first = TickerMerger().apply(deltas[0], ts_ingest_us=INGEST_US)
    assert first is not None and ev.mark_price == first.mark_price


@pytest.mark.parametrize(
    "frame",
    [
        '{"topic":"tickers.BTCUSDT","type":"delta","ts":1,"data":{"lastPrice":"NaN"}}',
        '{"topic":"tickers.BTCUSDT","type":"delta","ts":1,"data":{"lastPrice":"abc"}}',
        '{"topic":"tickers.BTCUSDT","type":"bogus","ts":1,"data":{}}',
        '{"topic":"tickers.BTCUSDT","type":"delta","data":{}}',
        '{"topic":"tickers.btc","type":"delta","ts":1,"data":{}}',
    ],
)
def test_hostile_ticker_frames_are_rejected(frame: str) -> None:
    with pytest.raises(ValueError):
        parse_ticker_frame(frame)


@pytest.mark.parametrize("tail", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_a_ticker_symbol_ending_in_a_newline_is_rejected(tail: str) -> None:
    """#3555: `$` also matches before a final newline, so `match` took `tickers.BTCUSDT\\n`.
    The frame is a recorded snapshot with that one change."""
    msg = json.loads(frames(FULL)[0])
    legal = parse_ticker_frame(json.dumps(msg))
    assert legal is not None and legal.symbol == "BTCUSDT"
    msg["topic"] += tail
    with pytest.raises(ValueError, match="invalid symbol"):
        parse_ticker_frame(json.dumps(msg))


def test_foreign_and_truncated_frames_are_ignored() -> None:
    assert parse_ticker_frame("") is None
    assert parse_ticker_frame(frames(FULL)[0][:50]) is None
    assert parse_ticker_frame('{"op":"pong"}') is None
