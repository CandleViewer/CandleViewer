"""E08-Q02 / E08-TC-C01: `tickers` snapshot + delta frames -> merged `TickerEvent`."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.api._generated.openapi_models import Ticker
from candleviewer.api.ticker import serialize_ticker
from candleviewer.bus.bus import Bus
from candleviewer.exchange.base.frame_guard import MAX_TS_MS, FrameRejectedError
from candleviewer.exchange.base.models import TickerEvent
from candleviewer.exchange.base.ticker_delta import TICKER_FIELDS, TickerDelta
from candleviewer.exchange.bybit.ticker import (
    parse_ticker_frame,
    parse_ticker_row,
    ticker_topic,
)
from candleviewer.ingestion.ticker_stream import REQUIRED_FIELDS, TickerMerger, TickerStream
from tests._corpus import frames

FULL = "ws/tickers_BTCUSDT.jsonl"
BURST = "ws/burst_tickers_BTCUSDT.jsonl"
RECORDED = "ws/recorded_tickers_BTCUSDT.jsonl"
#: Fields a live snapshot carries that the parser does not map (#3447); empty outside pre-market
#: for the last three. `highPrice24h` and `lowPrice24h` are mapped since E08-T08.
UNMAPPED = {"tickDirection", "prevPrice24h", "prevPrice1h", "fundingIntervalHour", "fundingCap",
            "singleOpenInterest", "singleOpenInterestValue", "preOpenPrice", "preQty",
            "curPreListingPhase"}  # fmt: skip
#: The 24 h range (E08-T08): optional, so the documented shape, which lacks it, still merges.
RANGE = {"high_24h", "low_24h"}
INGEST_US = 1_700_000_000_500_000
#: Numeric fields are bounded in length and scale before they are stored (E08-T08): a value has
#: at most 32 characters of text and 20 decimal places.
CHARS, SCALE = 32, 20


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
    assert set(snap.fields) == set(TICKER_FIELDS) - RANGE  # the documented shape has no range
    assert snap.fields["last_price"] == Decimal("63120.50")
    assert snap.fields["bid1_qty"] == Decimal("12.501")  # wire `bid1Size`
    assert snap.fields["next_funding_time"] == 1_700_006_400_000_000  # ms -> us
    assert all(isinstance(v, Decimal | int) for v in snap.fields.values())


def test_a_recorded_capture_with_bybits_newer_fields_merges_as_before() -> None:
    # #3447: a live snapshot carries twelve fields the documented shapes lacked. The parser maps
    # every field it knows from the snapshot, ignores the rest, and the merged stream keeps the
    # last price on the wire.
    raws = frames(RECORDED)
    snapshot = json.loads(raws[0])
    assert snapshot["type"] == "snapshot" and UNMAPPED <= set(snapshot["data"])
    deltas = _deltas(RECORDED)
    assert deltas[0].is_snapshot and set(deltas[0].fields) == set(TICKER_FIELDS)
    assert not any(d.is_snapshot for d in deltas[1:])
    merger = TickerMerger()
    events = [merger.apply(d, ts_ingest_us=INGEST_US) for d in deltas]
    assert all(isinstance(ev, TickerEvent) for ev in events)
    last = [json.loads(raw)["data"].get("lastPrice") for raw in raws]
    final = events[-1]
    assert isinstance(final, TickerEvent)
    assert final.last_price == Decimal([price for price in last if price is not None][-1])


def test_the_recorded_24h_high_and_low_are_mapped_carried_and_never_required() -> None:
    """E08-T08: `highPrice24h` / `lowPrice24h` -> `high_24h` / `low_24h` as `Decimal` prices,
    carried through a delta that leaves them out, and outside the required set, so the
    documented shape, which has neither, still yields a complete event."""
    deltas = _deltas(RECORDED)
    high, low = Decimal("82850.00"), Decimal("80611.70")
    assert (deltas[0].fields["high_24h"], deltas[0].fields["low_24h"]) == (high, low)
    assert RANGE.isdisjoint(REQUIRED_FIELDS) and RANGE <= set(TICKER_FIELDS)
    merger = TickerMerger()
    events = [merger.apply(d, ts_ingest_us=INGEST_US) for d in deltas]
    assert all(isinstance(e, TickerEvent) for e in events)
    assert {(e.high_24h, e.low_24h) for e in events if e is not None} == {(high, low)}
    documented = TickerMerger().apply(_deltas(FULL)[0], ts_ingest_us=INGEST_US)
    assert documented is not None and (documented.high_24h, documented.low_24h) == (None, None)


def test_the_rest_ticker_serves_the_recorded_24h_range_and_omits_an_unknown_one() -> None:
    """E08-T08: a field the merged state lacks is left out of the REST ticker, never `null`."""
    event = TickerMerger().apply(_deltas(RECORDED)[0], ts_ingest_us=INGEST_US)
    assert event is not None
    body = serialize_ticker(event, stale=False)
    assert (body["high_24h"], body["low_24h"]) == ("82850.00", "80611.70")
    Ticker.model_validate(body)
    documented = TickerMerger().apply(_deltas(FULL)[0], ts_ingest_us=INGEST_US)
    assert documented is not None
    bare = serialize_ticker(documented, stale=True)
    assert RANGE.isdisjoint(bare) and None not in bare.values()
    assert {"symbol", "last_price", "ts", "stale"} <= bare.keys()


@pytest.mark.parametrize("wire", ["highPrice24h", "lowPrice24h"])
@pytest.mark.parametrize("value", ["-1", "1e13"])  # in [0, MAX_PRICE], as every price (#1892)
def test_an_implausible_24h_price_rejects_the_frame(wire: str, value: str) -> None:
    frame = {"topic": "tickers.BTCUSDT", "type": "delta", "ts": 1, "data": {wire: value}}
    with pytest.raises(FrameRejectedError):
        parse_ticker_frame(json.dumps(frame))


@pytest.mark.parametrize(
    ("wire", "field"), [("highPrice24h", "high_24h"), ("lowPrice24h", "low_24h")]
)
def test_a_zero_24h_price_is_absent_so_the_known_one_is_kept_and_none_served(
    wire: str, field: str
) -> None:
    """E08-T08: `"0"` as the 24 h high or low is no price, absent like an empty value: the frame
    stands, a delta carrying it keeps the merged range, and a snapshot carrying it leaves the field
    out of the event and the REST ticker. Each frame is a recorded one with that one change."""
    recorded = frames(RECORDED)
    merger = TickerMerger()
    known = merger.apply(_deltas(RECORDED)[0], ts_ingest_us=INGEST_US)
    assert known is not None and getattr(known, field) is not None
    delta_msg = json.loads(recorded[1])
    delta_msg["data"][wire] = "0"
    delta = parse_ticker_frame(json.dumps(delta_msg))
    assert delta is not None and field not in delta.fields
    kept = merger.apply(delta, ts_ingest_us=INGEST_US)
    assert kept is not None and getattr(kept, field) == getattr(known, field)
    snapshot_msg = json.loads(recorded[0])
    snapshot_msg["data"][wire] = "0"
    snapshot = parse_ticker_frame(json.dumps(snapshot_msg))
    assert snapshot is not None and set(snapshot.fields) == set(TICKER_FIELDS) - {field}
    bare = TickerMerger().apply(snapshot, ts_ingest_us=INGEST_US)
    assert bare is not None and getattr(bare, field) is None
    assert field not in serialize_ticker(bare, stale=False)


def _widened(text: str, bound: str, past: int) -> str:
    """A recorded value's `text` with zeros added, its value unchanged: in front, to `past`
    characters beyond the length bound (`"length"`), else after the point, to `past` places
    beyond the scale bound."""
    if bound == "length":
        return text.rjust(CHARS + past, "0")
    whole, _, places = text.partition(".")
    return f"{whole}.{places.ljust(SCALE + past, '0')}"


def _stream() -> TickerStream:
    """The ticker stream over this parser, with BTCUSDT demanded; no socket, a fixed clock."""
    stream = TickerStream(
        bus=Bus(),
        env="live",
        set_desired=lambda _: None,
        parse_frame=parse_ticker_frame,
        topic_for=ticker_topic,
        is_listed=lambda symbol: symbol == "BTCUSDT",
        touch=lambda _: None,
        clock=lambda: 0.0,
        now_us=lambda: INGEST_US,
    )
    stream.acquire("test", "BTCUSDT")
    return stream


@pytest.mark.parametrize("bound", ["length", "scale"])
@pytest.mark.parametrize(
    ("wire", "field"),
    [("lastPrice", "last_price"), ("fundingRate", "funding_rate")],
    ids=["price", "rate"],
)
async def test_a_frame_refuses_a_value_beyond_the_length_or_scale_bound(
    wire: str, field: str, bound: str
) -> None:
    """Numeric fields are bounded in length and scale before they are stored. The recorded
    snapshot with one value widened to the bound parses to the recorded value; one step past it,
    the frame is refused `out_of_bounds` and the stream's merged state stays as it was."""
    raw = frames(RECORDED)[0]
    msg = json.loads(raw)
    recorded = msg["data"][wire]
    msg["data"][wire] = _widened(recorded, bound, 0)
    at = parse_ticker_frame(json.dumps(msg))
    assert at is not None and at.fields[field] == Decimal(recorded)
    msg["data"][wire] = _widened(recorded, bound, 1)
    past = json.dumps(msg)
    with pytest.raises(FrameRejectedError) as refused:
        parse_ticker_frame(past)
    assert refused.value.reason == "out_of_bounds"
    stream = _stream()
    await stream.handle_frame(raw)
    known = stream.latest("BTCUSDT")
    await stream.handle_frame(past)
    assert known is not None and stream.latest("BTCUSDT") is known


def _with_next_funding_time(value: str) -> tuple[str, dict[str, object], int]:
    """The recorded snapshot with its next funding time set to `value`: as a frame for the stream,
    and as a row of the bulk read, with the frame's `ts`."""
    msg = json.loads(frames(RECORDED)[0])
    msg["data"]["nextFundingTime"] = value
    return json.dumps(msg), {**msg["data"], "symbol": "BTCUSDT"}, msg["ts"]


@pytest.mark.parametrize("value", ["0", str(MAX_TS_MS)], ids=["zero", "at-bound"])
def test_a_next_funding_time_within_the_event_time_bound_is_kept(value: str) -> None:
    frame, row, ts = _with_next_funding_time(value)
    parsed = parse_ticker_frame(frame)
    assert parsed is not None and parsed.fields["next_funding_time"] == int(value) * 1000
    assert parse_ticker_row(row, ts_ms=ts).fields == parsed.fields


@pytest.mark.parametrize(
    "value",
    [str(MAX_TS_MS + 1), "-1", "0" * (CHARS + 1)],
    ids=["past-bound", "negative", "past-length"],
)
def test_a_next_funding_time_beyond_the_length_or_time_bound_is_refused(value: str) -> None:
    """The next funding time is bounded in length and to the event-time bound before it is
    stored, through the stream's frame and the bulk read's row alike."""
    frame, row, ts = _with_next_funding_time(value)
    with pytest.raises(FrameRejectedError) as by_frame:
        parse_ticker_frame(frame)
    with pytest.raises(FrameRejectedError) as by_row:
        parse_ticker_row(row, ts_ms=ts)
    assert (by_frame.value.reason, by_row.value.reason) == ("out_of_bounds", "out_of_bounds")


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
