"""#3353: with `CV_WS_BACKPRESSURE_ENABLED` on, a merged window keeps its family's CVWB body kind on
a binary subscription (`23-ws-protocol.md` §3.2, §3.4, §8.2). `book` (kind 2), `trades` (3) and
`bars` (4) re-encode it from their updates' parts and decode back to the merged body. A `bars`
window leaves structured only by §3.4's own trigger, and as one frame per kind-4 frame past the
u32 span (§3.6). An unmerged update keeps its own part. A window without a part of its family's
kind leaves structured, as do a `trades` window with `dropped` prints and every footprint and
heatmap window (no encoder yet: #593, #605), and a structured subscription's window is never built
from parts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from decimal import Decimal
from typing import Any
from unittest.mock import Mock

import pytest
from prometheus_client import REGISTRY

from candleviewer.bars.models import Bar, BarSpec
from candleviewer.ws.bars_wire import bar_item, bars_frames, covering_scales
from candleviewer.ws.binary import (
    BARS,
    BOOK_DELTA,
    BOOK_SNAPSHOT,
    FLAG_COALESCED,
    FLAG_ESTIMATED,
    FLAG_REPLAY,
    TRADES,
    Frame,
    decode,
    decode_b64,
    encode,
)
from candleviewer.ws.coalescing import MAX_PENDING_ITEMS, CoalescingQueue, Emission
from candleviewer.ws.cvwb_vectors import structured, vector_frames
from candleviewer.ws.pacing import Pacer
from candleviewer.ws.permissions import Subscription
from candleviewer.ws.sequencing import SnapshotBody
from tests.unit.ws._seq_support import ACC_A, Conn, Source

Body = dict[str, Any]
Update = tuple[Body, Frame | None, Mapping[str, Any] | None]

SPEC = BarSpec(kind="time", interval_ms=60_000)
T0_US = 1_700_000_000_000_000
T0_MS = T0_US // 1000
MINUTE_US = 60_000_000
_HEAD = {"symbol": "BTCUSDT", "bar_type": "time", "param": "1"}
_VECTORS = dict(vector_frames())


def _scaled(value: str, scale: int) -> int:
    return int(Decimal(value).scaleb(scale))


def _book(bids: list[list[str]], asks: list[list[str]]) -> Update:
    """A `book` delta and its kind-2 twin at scales (1, 3)."""
    records = tuple(
        (side, _scaled(price, 1), _scaled(size, 3))
        for side, levels in ((0, bids), (1, asks))
        for price, size in levels
    )
    body = {"symbol": "BTCUSDT", "bids": bids, "asks": asks}
    return body, Frame(BOOK_DELTA, records, 0, 1, 3), None


def _trades(
    *prints: tuple[int, str, str, str], flags: int = 0, scales: tuple[int, int] = (1, 3)
) -> Update:
    """A `trades` batch and its kind-3 twin at `scales`, based at its first print; each print is
    `(ms after T0, price, size, side)`, and a sell is flagged a liquidation (bit1)."""
    (ps, qs), base = scales, T0_MS + prints[0][0]
    trades = [
        {"ts_ms": T0_MS + t, "price": p, "size": q, "side": s, "is_liquidation": s == "sell"}
        for t, p, q, s in prints
    ]
    records = tuple(
        (T0_MS + t - base, _scaled(p, ps), _scaled(q, qs), int(s == "sell"), 2 * (s == "sell"))
        for t, p, q, s in prints
    )
    body = {"symbol": "BTCUSDT", "trades": trades}
    return body, Frame(TRADES, records, flags, ps, qs, base), None


def _bar(index: int, **kw: Any) -> Bar:
    """A one-minute bar at `index`, forming unless `closed=True`."""
    open_us = T0_US + index * MINUTE_US
    base: dict[str, Any] = dict(
        spec_hash=SPEC.spec_hash, symbol="BTCUSDT", index=index, open_time=open_us,
        close_time=open_us + MINUTE_US - 1, open=Decimal("100.1"), high=Decimal("101"),
        low=Decimal("99.5"), close=Decimal("100.5"), volume=Decimal("10"),
        buy_volume=Decimal("6"), sell_volume=Decimal("4"), delta=Decimal("-2.5"),
        min_delta=Decimal("-3"), max_delta=Decimal("1.5"), trade_count=7,
        turnover=Decimal("1001"), vwap=Decimal("100.3"), closed=False, partial=False,
        gap_before=False,
    )  # fmt: skip
    return Bar.model_validate({**base, **kw})


def _far(index: int) -> Bar:
    """A bar opening one past the u32 offset span (2^32 ms, §3.6) after bar 3's open."""
    open_us = T0_US + 3 * MINUTE_US + 2**32 * 1000
    return _bar(index, open_time=open_us, close_time=open_us + MINUTE_US - 1)


def _bars(*bars: Bar, flow: bool = False) -> Update:
    """A `bars` update as `BarsPublisher` sends it: the §14.3 items, their kind-4 frame at the
    scales covering them from the instrument's (1, 3), and the `include_delta` echo."""
    items = [bar_item(b, generation=0, bar_kind="time", include_delta=flow) for b in bars]
    ps, qs = covering_scales(bars, price_scale=1, qty_scale=3, include_delta=flow)
    (part,) = bars_frames(bars, generation=0, include_delta=flow, price_scale=ps, qty_scale=qs)
    return {**_HEAD, "bars": items}, part, {"include_delta": flow}


def _rows(payload: Mapping[str, Any]) -> list[tuple[Any, ...]]:
    """What both forms carry, comparable: decimals as `Decimal`, and for a bar every field kind 4
    holds (`delta` reads 0 where the item has none, §3.4)."""
    if "bids" in payload:
        return [(s, Decimal(p), Decimal(q)) for s in ("bids", "asks") for p, q in payload[s]]
    if "trades" in payload:
        return [
            (t["ts_ms"], Decimal(t["price"]), Decimal(t["size"]), t["side"], t["is_liquidation"])
            for t in payload["trades"]
        ]
    ids = ("generation", "index", "t_ms", "trades", "confirm")
    keys = ("o", "h", "l", "c", "v", "turnover", "delta")  # `delta` reads 0 where it is absent
    return [(*(b[k] for k in ids), *(Decimal(b.get(k, 0)) for k in keys)) for b in payload["bars"]]


def _take(family: str, updates: list[Update], max_items: int = MAX_PENDING_ITEMS) -> list[Emission]:
    queue = CoalescingQueue(family, max_items=max_items)
    for body, part, meta in updates:
        assert queue.offer(body, part, meta=meta)
    emissions = queue.take()
    assert not queue.overflowed  # a window whose part cannot be built is never refused
    return emissions


def _decoded(part: Frame | None) -> Body:
    """`part` sent and read back: encoded, decoded and rendered in §14 item form."""
    assert part is not None
    return structured(decode(encode(part)))


#: Per family, one window as its producer sends it, each update beside its CVWB twin: levels set,
#: then deleted; two batches, the later one earlier in time; a forming bar, then its close beside
#: the next bar's open (with `include_delta`, without it, and with no echo of it: read as false).
_WINDOWS: dict[str, Callable[[], list[Update]]] = {
    "book": lambda: [
        _book([["100", "1"]], [["101", "2"]]),
        _book([["100", "0"], ["99.5", "3"]], []),
    ],
    "trades": lambda: [
        _trades((900, "100.5", "0.25", "buy"), (905, "100.4", "1", "sell")),
        _trades((0, "100.6", "2.5", "buy")),
    ],
    "bars": lambda: [_bars(_bar(3)), _bars(_bar(3, close=Decimal("100.7"), closed=True), _bar(4))],
    "bars_include_delta": lambda: [
        _bars(_bar(3), flow=True),
        _bars(_bar(3, closed=True), _bar(4, delta=Decimal("1.25")), flow=True),
    ],
    "bars_without_meta": lambda: [(b, p, None) for b, p, _ in _WINDOWS["bars"]()],
}
_KINDS = {"book": BOOK_DELTA, "trades": TRADES} | {w: BARS for w in _WINDOWS if "bars" in w}


@pytest.mark.parametrize("window", list(_WINDOWS))
def test_a_merged_window_leaves_in_its_body_kind_and_decodes_to_the_merged_body(
    window: str,
) -> None:
    """§3.4, §8.2: one part of the family's kind, read back equal to the merged structured body,
    with the window's count (a `trades` batch counts 1, §8.6; the emitter sets bit1 from it)."""
    family = window.split("_", 1)[0]
    [emission] = _take(family, _WINDOWS[window]())
    assert emission.part is not None and emission.part.body_kind == _KINDS[window]
    assert emission.coalesced_count == (1 if family == "trades" else 2)
    assert _rows(_decoded(emission.part)) == _rows(emission.body)


@pytest.mark.parametrize("family", ["book", "trades", "bars"])
def test_a_single_update_leaves_with_its_own_part_unchanged(family: str) -> None:
    body, part, meta = _WINDOWS[family]()[-1]
    [emission] = _take(family, [(body, part, meta)])
    assert emission.part is part and emission.coalesced_count == 1


def _footprint(t_ms: int) -> Update:
    cell = {"price": "100", "bid_volume": "1", "ask_volume": "2"}
    bar = {"generation": 0, "index": t_ms, "t_ms": T0_MS + t_ms, "cells": [cell]}
    return {**_HEAD, "bars": [bar]}, _VECTORS["footprint"], None


def _heatmap(t_ms: int) -> Update:
    column = {"t_ms": T0_MS + t_ms, "price_min": "100", "price_step": "1", "bids": [1], "asks": [2]}
    body = {"symbol": "BTCUSDT", "time_bucket_ms": 500, "columns": [column]}
    return body, _VECTORS["heatmap_column"], None


def _bare(update: Update) -> Update:
    """`update` from a producer that sent no part with it."""
    return update[0], None, update[2]


@pytest.mark.parametrize(
    ("family", "updates"),
    [
        pytest.param(
            "book", lambda: [_WINDOWS["book"]()[0], _bare(_WINDOWS["book"]()[1])], id="book"
        ),
        pytest.param(
            "trades", lambda: [_bare(_WINDOWS["trades"]()[0]), _WINDOWS["trades"]()[1]], id="trades"
        ),
        pytest.param(  # an amended close or unknown scales: `BarsPublisher` sends no part (§3.4)
            "bars", lambda: [_WINDOWS["bars"]()[0], _bare(_WINDOWS["bars"]()[1])], id="bars"
        ),
        pytest.param(  # book snapshot frames as the parts of book deltas: not kind 2
            "book",
            lambda: [(b, _VECTORS["book_snapshot"], m) for b, _, m in _WINDOWS["book"]()],
            id="book-other-kind",
        ),
        # These two flip to kinds 5 and 6 when #593 and #605 add their merged-window encoders.
        pytest.param("footprint", lambda: [_footprint(0), _footprint(60_000)], id="footprint-593"),
        pytest.param("heatmap", lambda: [_heatmap(0), _heatmap(500)], id="heatmap-605"),
    ],
)
def test_a_merged_window_without_a_part_it_can_carry_leaves_structured(
    family: str, updates: Callable[[], list[Update]]
) -> None:
    [emission] = _take(family, updates())
    assert (emission.part, emission.coalesced_count) == (None, 1 if family == "trades" else 2)


def test_a_kind_with_no_encoder_arm_leaves_structured(monkeypatch: pytest.MonkeyPatch) -> None:
    """A kind in `_BODY_KINDS` without its own `_encoded` arm leaves structured, and never takes
    another kind's arm. Book snapshot frames (kind 1) stand in for it: a window is built from
    deltas, so that kind will never get an arm, unlike footprint and heatmap, which #593 and #605
    give one."""
    monkeypatch.setattr("candleviewer.ws.coalescing._BODY_KINDS", {"book": BOOK_SNAPSHOT})
    monkeypatch.setattr("candleviewer.ws.coalescing._book_delta", Mock(side_effect=AssertionError))
    snapshots: list[Update] = [(b, _VECTORS["book_snapshot"], m) for b, _, m in _WINDOWS["book"]()]
    [emission] = _take("book", snapshots)
    assert (emission.part, emission.coalesced_count) == (None, 2)


def _amended_with_a_part() -> list[Update]:
    """A producer that sent an amended close with a kind-4 part, which `BarsPublisher` never does:
    kind 4 has no amended bit (§3.4 trigger 2)."""
    body, part, meta = _bars(_bar(3, close=Decimal("100.7"), closed=True))
    body["bars"][0]["amended"] = True
    return [_bars(_bar(3)), (body, part, meta)]


def _past_u64() -> list[Update]:
    """Each update fits kind 4 at its own scales, but the window takes the finer of both, at which
    the first bar's volume is past its u64 field (§3.4 trigger 1, a value)."""
    big = _bar(3, open=Decimal("100.12345678"), volume=Decimal("1E+12"), turnover=Decimal("1E+14"))
    return [_bars(big), _bars(_bar(4, volume=Decimal("0.00000001")))]


def _past_u8() -> list[Update]:
    """A price that needs 256 places, past the header's u8 scale (§3.4 trigger 1, the scales): an
    item no twin could carry, beside a kind-4 part."""
    body, part, meta = _bars(_bar(4))
    body["bars"][0]["o"] = "0." + "0" * 255 + "1"
    return [_bars(_bar(3)), (body, part, meta)]


def _unreadable(key: str, value: object = None) -> Callable[[], list[Update]]:
    """An item kind 4 cannot read (`key` set to `value`, or missing) leaves the window
    structured, never refused."""

    def updates() -> list[Update]:
        body, part, meta = _bars(_bar(4))
        item = body["bars"][0]
        if value is None:
            del item[key]
        else:
            item[key] = value
        return [_bars(_bar(3)), (body, part, meta)]

    return updates


@pytest.mark.parametrize(
    "updates",
    [
        _amended_with_a_part,
        _past_u64,
        _past_u8,
        pytest.param(_unreadable("turnover"), id="no-turnover"),
        pytest.param(_unreadable("o", "abc"), id="a-price-not-a-number"),
        pytest.param(_unreadable("trades", [7]), id="a-trade-count-not-a-number"),
    ],
)
def test_a_merged_bars_window_kind_4_cannot_carry_leaves_structured(
    updates: Callable[[], list[Update]],
) -> None:
    [emission] = _take("bars", updates())
    assert (emission.part, emission.coalesced_count) == (None, 2)


def test_a_merged_bars_window_widens_to_the_scales_its_bars_need() -> None:
    """§3.4 (C16): a bar finer than the latest part's scales widens the frame's (never coarser than
    the instrument's) instead of falling back: scales are not §3.4's trigger."""
    [emission] = _take("bars", [_bars(_bar(3, open=Decimal("100.15"))), _bars(_bar(4))])
    assert emission.part is not None
    assert (emission.part.price_scale, emission.part.qty_scale) == (2, 3)
    assert _rows(_decoded(emission.part)) == _rows(emission.body)


def test_a_merged_bars_window_past_one_frames_span_leaves_one_frame_per_kind_4_frame() -> None:
    """§3.4, §3.6: bars 2^32 ms apart take two kind-4 frames, cut as the publisher cuts a `d`, each
    with its items and bit1; the window's counts ride on the first (#571 counts the window once)."""
    queue = CoalescingQueue("bars")
    for body, part, meta in (_bars(_bar(3)), _bars(_far(4))):
        assert queue.offer(body, part, ts_ms=9, meta=meta)
    emissions = queue.take()
    assert [[b["index"] for b in e.body["bars"]] for e in emissions] == [[3], [4]]
    meta = {"include_delta": False}
    counts = [(e.coalesced_count, e.window_count, e.ts_ms, e.meta) for e in emissions]
    assert counts == [(2, 2, 9, meta), (1, 1, 9, meta)]
    for emission in emissions:
        assert emission.part is not None and emission.part.body_kind == BARS
        assert emission.part.flags & FLAG_COALESCED
        assert _rows(_decoded(emission.part)) == _rows(emission.body)


def _flagged(update: Update, flags: int) -> Update:
    body, part, meta = update
    assert part is not None
    return body, replace(part, flags=flags), meta


@pytest.mark.parametrize(
    ("family", "flags"), [("trades", FLAG_ESTIMATED), ("bars", FLAG_ESTIMATED | FLAG_COALESCED)]
)
def test_a_merged_window_keeps_estimated_from_any_part_and_no_other_producer_bit(
    family: str, flags: int
) -> None:
    """§3.4: bit0 `estimated` is kept if any part had it, here the first; the producer's bits 1
    and 2 are not, as the emitter owns them. A `bars` part carries bit1 itself (choice 1)."""
    first, later = _WINDOWS[family]()
    window = [_flagged(first, FLAG_ESTIMATED), _flagged(later, FLAG_REPLAY | FLAG_COALESCED)]
    [emission] = _take(family, window)
    assert emission.part is not None and emission.part.flags == flags


def test_a_merged_trades_window_with_dropped_prints_leaves_structured() -> None:
    """Kind 3 has no field for `dropped` (§14.2: prints `min_size` filtered out, never silent), so
    a window that carries any leaves structured with them; how a binary subscription gets them is
    #654's to decide."""
    first, later = _WINDOWS["trades"]()
    [emission] = _take("trades", [({**first[0], "dropped": 1}, first[1], None), later])
    assert (emission.part, emission.body["dropped"]) == (None, 1)


@pytest.mark.parametrize(
    ("ms", "scales", "kind"),
    [
        pytest.param(2**32 - 1, (1, 3), TRADES, id="a-u32-offset-apart-fits"),
        pytest.param(2**32, (1, 3), None, id="past-a-u32-offset"),
        pytest.param(1, (2, 3), None, id="other-price-scale"),
        pytest.param(1, (1, 4), None, id="other-qty-scale"),
    ],
)
def test_a_merged_trades_window_is_one_batch_at_one_scale_within_a_u32_offset(
    ms: int, scales: tuple[int, int], kind: int | None
) -> None:
    later = _trades((ms, "100", "1", "buy"), scales=scales)
    [emission] = _take("trades", [_trades((0, "100", "1", "buy")), later])
    assert (emission.part.body_kind if emission.part else None) == kind


def test_a_trades_batch_at_the_item_bound_leaves_as_one_frame() -> None:
    """C-2.18: the batch holds up to the queue's item bound in parts and in records."""
    [emission] = _take("trades", [_trades((0, "100", "1", "buy"))] * 2, max_items=2)
    assert emission.part is not None and len(emission.part.records) == 2


def test_a_trades_batch_past_the_item_bound_in_records_leaves_structured() -> None:
    """A part with more records than its body has prints counts by its records."""
    body, part, _ = _trades((0, "100", "1", "buy"))
    assert part is not None
    wide = replace(part, records=part.records * 2)
    [emission] = _take("trades", [(body, part, None), (body, wide, None)], max_items=2)
    assert emission.part is None


def test_a_trades_batch_past_the_item_bound_in_parts_leaves_structured() -> None:
    """A part without a print still counts, so updates that carry none cannot grow the batch."""
    _, part, _ = _trades((0, "100", "1", "buy"))
    assert part is not None
    empty = ({"symbol": "BTCUSDT", "trades": []}, replace(part, records=()), None)
    [emission] = _take("trades", [empty] * 3, max_items=2)
    assert emission.part is None


def test_only_a_trades_window_holds_its_parts_against_the_item_bound() -> None:
    [emission] = _take("book", _WINDOWS["book"](), max_items=1)
    assert emission.part is not None


def _paced(encoding: str) -> tuple[Conn, Pacer, Subscription]:
    """A connection with the flag on (its `Pacer`) and one `bars` subscription in `encoding`."""
    source = Source()
    source.bodies["bars"] = SnapshotBody({**_HEAD, "bars": []})
    conn = Conn(source, ACC_A)
    conn.clock.now = 100.0
    _, sub = conn.sub({"ch": "bars.BTCUSDT.time.1", "opts": {"encoding": encoding}})
    conn.take()  # the snap
    return conn, Pacer(conn.emitter), sub


def _span_window(conn: Conn, pacer: Pacer, sub: Subscription) -> list[dict[str, Any]]:
    """The frames on the wire: the first update leaves at once; the next two, 2^32 ms apart in bar
    time, merge in one window."""
    for body, part, meta in (_bars(_bar(2)), _bars(_bar(3)), _bars(_far(4))):
        assert pacer.offer(sub, body, part=part, meta=meta)
    pacer.tick(100.3)
    return conn.take()


def _conflation() -> tuple[float, float]:
    """#571's series for `bars`: `cv_ws_conflated_total` and the `cv_ws_coalesced_updates` count."""
    conflated = REGISTRY.get_sample_value("cv_ws_conflated_total", {"topic": "bars"})
    observed = REGISTRY.get_sample_value("cv_ws_coalesced_updates_count")
    return conflated or 0.0, observed or 0.0


def test_a_window_past_one_frames_span_leaves_two_kind_4_frames_on_a_binary_subscription() -> None:
    """After the leading edge, two kind-4 `d` frames, each flagged `coalesced` (bit1), `s` running
    on (§3.6); #571's series count the window's two updates once (n - 1, one observation)."""
    before = _conflation()
    frames = _span_window(*_paced("binary"))
    after = _conflation()
    assert (after[0] - before[0], after[1] - before[1]) == (1.0, 1.0)
    parts = [decode_b64(f["p"]) for f in frames]
    assert [(f["e"], f["s"], p.body_kind) for f, p in zip(frames, parts, strict=True)] == [
        ("b64", s, BARS) for s in (2, 3, 4)
    ]
    assert [bool(p.flags & FLAG_COALESCED) for p in parts] == [False, True, True]
    assert [[b["index"] for b in structured(p)["bars"]] for p in parts] == [[2], [3], [4]]


def test_a_structured_subscriptions_window_is_one_frame_whatever_its_span() -> None:
    """`Pacer.offer` keeps no part for a structured subscription, so its window is built from
    bodies only and never cut at the kind-4 span."""
    frames = _span_window(*_paced("structured"))
    assert [(f["e"], f["s"]) for f in frames] == [("j", 2), ("j", 3)]
    assert [b["index"] for b in frames[1]["p"]["bars"]] == [3, 4]
    assert (frames[1]["p"]["coalesced"], frames[1]["p"]["coalesced_count"]) == (True, 2)


def test_a_trades_window_never_carries_the_prints_of_an_earlier_window() -> None:
    """Each window's batch starts empty, after a window leaves (`take`) and after `clear()`."""
    queue, seen = CoalescingQueue("trades"), []
    for window in ((0, 1), (2, 3), (4,), (5, 6)):
        for ms in window:
            body, part, _ = _trades((ms, "100", "1", "buy"))
            assert queue.offer(body, part)
        if window == (4,):
            queue.clear()  # the window is dropped (§8.4 step 1)
            continue
        [emission] = queue.take()
        seen.append([t["ts_ms"] - T0_MS for t in _decoded(emission.part)["trades"]])
    assert seen == [[0, 1], [2, 3], [5, 6]]
