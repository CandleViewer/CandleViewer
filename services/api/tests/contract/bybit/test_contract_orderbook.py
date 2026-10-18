"""E08-Q02 / E08-TC-E01, E08-TC-E02, E08-TC-E03, E08-TC-E06: `orderbook.N` -> snapshot/delta."""

from __future__ import annotations

import itertools
import json
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.book.models import BookPhase
from candleviewer.book.resync import BookEngine
from candleviewer.book.state import BookState
from candleviewer.exchange.base.models import BookDelta, BookSnapshot
from candleviewer.exchange.bybit.orderbook import parse_book_frame
from tests._corpus import frames
from tests.contract.bybit._support import TICK, book_events, tick_of

BTC = "ws/orderbook_BTCUSDT.jsonl"
GAP = "ws/gap_orderbook_ETHUSDT.jsonl"
HOLE_AT, RESET_AT = 2700, 4000  # documented in the corpus manifest


def _eth_tick(_s: str) -> Decimal:
    return Decimal("0.01")


def test_snapshot_maps_levels_to_decimal_ticks_and_internal_fields() -> None:
    snap = book_events(frames(BTC)[:1])[0]
    wire = json.loads(frames(BTC)[0])
    assert isinstance(snap, BookSnapshot) and snap.reason == "subscribe" and snap.depth == 200
    assert snap.update_id == wire["data"]["u"] == 1 and snap.cross_seq == wire["data"]["seq"]
    assert snap.ts_event == wire["ts"] * 1000 and snap.ts_match == wire["cts"] * 1000
    assert len(snap.bids) == 200 and len(snap.asks) == 200
    for lv in (*snap.bids, *snap.asks):
        assert isinstance(lv.price, Decimal) and isinstance(lv.qty, Decimal)
        assert lv.price_ticks == int(lv.price / TICK)


def test_delta_prev_update_id_is_u_minus_one_and_u_is_monotonic_until_the_hole() -> None:
    evs = book_events(frames(BTC)[:HOLE_AT])
    deltas = [e for e in evs if isinstance(e, BookDelta)]
    assert all(d.prev_update_id == d.update_id - 1 for d in deltas)
    ids = [e.update_id for e in evs]
    assert all(b == a + 1 for a, b in itertools.pairwise(ids))
    seqs = [e.cross_seq for e in evs]
    assert all(b >= a for a, b in itertools.pairwise(seqs))


def test_the_corpus_really_contains_the_hole_and_the_server_reset() -> None:
    ids = [e.update_id for e in book_events(frames(BTC))]
    breaks = [(i, a, b) for i, (a, b) in enumerate(itertools.pairwise(ids), 1) if b != a + 1]
    assert [(i, b) for i, _a, b in breaks] == [(HOLE_AT, ids[HOLE_AT]), (RESET_AT, 1)]
    reset = book_events(frames(BTC))[RESET_AT]
    assert isinstance(reset, BookSnapshot) and reset.update_id == 1  # `u == 1` => snapshot


def test_zero_size_levels_are_carried_as_deletes_and_remove_the_level() -> None:
    evs = book_events(frames(BTC)[:HOLE_AT])
    book = BookState.from_levels(200, evs[0].bids, evs[0].asks)
    deletes = 0
    for ev in evs[1:]:
        for lv in (*ev.bids, *ev.asks):
            if lv.qty == 0:
                deletes += 1
        book.apply(ev.bids, ev.asks)
        bids, asks = book.snapshot()
        gone = {lv.price_ticks for lv in (*ev.bids, *ev.asks) if lv.qty == 0}
        assert gone.isdisjoint({lv.price_ticks for lv in (*bids, *asks)})
        assert all(lv.qty > 0 for lv in (*bids, *asks))
    assert deletes > 100  # the corpus exercises deletes heavily


def _naive_apply(side: dict[int, Decimal], levels: tuple[object, ...]) -> None:
    for lv in levels:
        ticks, qty = lv.price_ticks, lv.qty  # type: ignore[attr-defined]
        if qty == 0:
            side.pop(ticks, None)
        else:
            side[ticks] = qty


@given(cut=st.integers(min_value=1, max_value=HOLE_AT - 1))
@settings(max_examples=25, deadline=None)
def test_replay_then_independent_snapshot_yields_identical_top_n(cut: int) -> None:
    """Round-trip invariant: the maintained book equals a snapshot rebuilt by an independent
    naive dict model (the REST-snapshot oracle) at the same update id, for any prefix."""
    evs = book_events(frames(BTC)[: cut + 1])
    book = BookState.from_levels(200, evs[0].bids, evs[0].asks)
    bids: dict[int, Decimal] = {lv.price_ticks: lv.qty for lv in evs[0].bids}
    asks: dict[int, Decimal] = {lv.price_ticks: lv.qty for lv in evs[0].asks}
    for ev in evs[1:]:
        book.apply(ev.bids, ev.asks)
        _naive_apply(bids, ev.bids)
        _naive_apply(asks, ev.asks)
    top_b, top_a = book.top(50)
    oracle_b = sorted(bids.items(), reverse=True)[:50]
    oracle_a = sorted(asks.items())[:50]
    assert [(lv.price_ticks, lv.qty) for lv in top_b] == oracle_b
    assert [(lv.price_ticks, lv.qty) for lv in top_a] == oracle_a


async def _engine(depth: int = 200) -> tuple[BookEngine, list[object], list[int]]:
    published: list[object] = []
    resubs: list[int] = []

    async def pub(obj: object) -> None:
        published.append(obj)

    async def resub() -> None:
        resubs.append(1)

    eng = BookEngine(
        symbol="BTCUSDT", depth=depth, publish=pub, resubscribe=resub, now_us=lambda: 0
    )
    await eng.start()
    return eng, published, resubs


def _phase(eng: BookEngine) -> BookPhase:
    """Re-read the phase so mypy does not narrow it across awaited mutations."""
    return eng.phase


def test_eth_gap_fixture_carries_the_documented_update_id_jump() -> None:
    """The ETH window is parse-level evidence only: its book crosses at u=3 (T05 defect, see PR
    notes), so the engine-level gap scenario below runs on the BTC hole instead."""
    ids = [e.update_id for e in book_events(frames(GAP), _eth_tick)]
    assert [(a, b) for a, b in itertools.pairwise(ids) if b != a + 1] == [(30, 34)]


async def test_sequence_gap_invalidates_never_patches_across_the_gap() -> None:
    """E08-TC-E06 / Gherkin 'sequence gap must invalidate, never patch': at the u hole the book
    is DESYNCED, exactly one resubscribe is issued, resync_count (the engine-side source of
    `book_resync_total`) increments and no delta at/after the hole is published."""
    eng, published, resubs = await _engine()
    evs = book_events(frames(BTC))
    for ev in evs[:HOLE_AT]:
        await eng.on_event(ev)
    assert eng.phase is BookPhase.LIVE and eng.resync_count == 0
    base_resubs, last_good = len(resubs), eng.last_u
    await eng.on_event(evs[HOLE_AT])  # the gap frame
    assert _phase(eng) is BookPhase.SNAPSHOT_PENDING and eng.book is None  # dropped, not patched
    assert len(resubs) == base_resubs + 1 and eng.resync_count == 1
    assert eng.live_snapshot() is None  # nothing is served while resyncing
    deltas = [o for o in published if isinstance(o, BookDelta)]
    assert deltas and max(d.update_id for d in deltas) == last_good < evs[HOLE_AT].update_id


async def test_gap_recovery_matches_the_independent_snapshot_oracle() -> None:
    """After the hole the book is rebuilt only from a fresh snapshot taken at the last good
    update id (the REST oracle; here the corpus `u == 1` reset levels re-stamped), the buffered
    next delta (u = hole + 1) chains onto it, and the result equals an independent dict model."""
    eng, _, _ = await _engine()
    evs = book_events(frames(BTC))
    for ev in evs[: HOLE_AT + 1]:
        await eng.on_event(ev)
    assert _phase(eng) is BookPhase.SNAPSHOT_PENDING
    oracle = evs[RESET_AT].model_copy(update={"update_id": evs[HOLE_AT].prev_update_id})
    await eng.on_event(oracle)
    assert _phase(eng) is BookPhase.LIVE and eng.last_u == oracle.update_id
    bids = {lv.price_ticks: lv.qty for lv in oracle.bids}
    asks = {lv.price_ticks: lv.qty for lv in oracle.asks}
    nxt = evs[HOLE_AT + 1]
    assert isinstance(nxt, BookDelta) and nxt.prev_update_id == oracle.update_id + 1
    await eng.on_event(nxt.model_copy(update={"prev_update_id": oracle.update_id}))
    _naive_apply(bids, nxt.bids)
    _naive_apply(asks, nxt.asks)
    live = eng.live_snapshot()
    assert live is not None
    assert [(lv.price_ticks, lv.qty) for lv in live.bids] == sorted(bids.items(), reverse=True)[
        :200
    ]
    assert [(lv.price_ticks, lv.qty) for lv in live.asks] == sorted(asks.items())[:200]


async def test_delta_before_any_snapshot_is_never_applied() -> None:
    eng, published, _ = await _engine()
    evs = book_events(frames(BTC)[:3])
    await eng.on_event(evs[1])
    assert eng.book is None and not [o for o in published if isinstance(o, BookDelta)]


def test_depth_truncation_serves_at_most_n_levels_best_first() -> None:
    snap = book_events(frames(BTC)[:1])[0]
    book = BookState.from_levels(200, snap.bids, snap.asks)
    for n in (1, 10, 50, 200):
        bids, asks = book.top(n)
        assert len(bids) == len(asks) == n
        assert [b.price_ticks for b in bids] == sorted((b.price_ticks for b in bids), reverse=True)
        assert [a.price_ticks for a in asks] == sorted(a.price_ticks for a in asks)
        assert bids[0].price_ticks < asks[0].price_ticks


@pytest.mark.parametrize(
    "frame",
    [
        '{"topic":"orderbook.7.BTCUSDT","ts":1,"data":{}}',
        '{"topic":"orderbook.200.BTCUSDT","type":"delta","ts":1,"data":{"s":"BTCUSDT","u":2,'
        '"b":[["1","-1"]],"a":[]}}',
        '{"topic":"orderbook.200.BTCUSDT","type":"delta","ts":1,"data":{"s":"BTCUSDT","u":2,'
        '"b":[["Infinity","1"]],"a":[]}}',
        '{"topic":"orderbook.200.BTCUSDT","type":"weird","ts":1,"data":{"s":"BTCUSDT","u":2}}',
        '{"topic":"orderbook.200.BTCUSDT","type":"delta","ts":1,"data":{"s":"BTCUSDT","u":0}}',
    ],
)
def test_hostile_book_frames_are_rejected_not_crashed(frame: str) -> None:
    with pytest.raises(ValueError):
        parse_book_frame(frame, tick_of)


@pytest.mark.parametrize("tail", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_a_book_symbol_ending_in_a_newline_is_rejected(tail: str) -> None:
    """#3555: `$` also matches before a final newline, so `match` took `orderbook.200.BTCUSDT\\n`.
    The frame is a recorded snapshot whose topic and `data.s` carry that symbol. The symbol
    pattern refuses it here; without that, the snapshot model refused it later, with its own
    error."""
    msg = json.loads(frames(BTC)[0])
    assert isinstance(parse_book_frame(json.dumps(msg), tick_of), BookSnapshot)
    msg["topic"] += tail
    msg["data"]["s"] += tail
    with pytest.raises(ValueError, match="invalid symbol"):
        parse_book_frame(json.dumps(msg), tick_of)


def test_truncated_frame_is_ignored_and_unknown_tick_is_rejected() -> None:
    assert parse_book_frame(frames(BTC)[1][:60], tick_of) is None
    with pytest.raises(ValueError, match="tick"):
        parse_book_frame(frames(BTC)[0], lambda _s: None)
