"""E21-T01 (#604) on the production `BookStream` (`orderbook_wiring.py`), over the recorded BTCUSDT
corpus: the tier per symbol and its 500 demand behind `heatmap_depth_500` (BQ-1), the
`BestQuoteEvent` publication (24 §2.8), each incident's `BookDesyncEvent` and structured log, the
resync counter's `depth`, `book_crossed_total` and `book_apply_latency_ms` (BQ-6)."""

from __future__ import annotations

import json
from typing import Any

import structlog

from candleviewer.book.models import BestQuoteEvent, BookDesyncEvent, BookPhase
from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy, TopicPattern
from candleviewer.exchange.bybit.orderbook import book_topic, parse_book_frame
from candleviewer.ingestion.metrics import (
    book_apply_latency_ms,
    book_crossed_total,
    ingest_book_resyncs_total,
    symbol_label,
)
from candleviewer.ingestion.planner import MAX_TOPICS_PER_FRAME, SubscriptionPlanner
from candleviewer.orderbook_wiring import (
    DEEP_TIER,
    SNAPSHOT_TIMEOUT_S,
    WARMUP_DEADLINE_S,
    BookStream,
)
from tests._corpus import TICKS, frames

SYM = "BTCUSDT"
RAW = frames("ws/orderbook_BTCUSDT.jsonl")


class Rig:
    def __init__(self, *, depth_500: bool = False) -> None:
        self.bus = Bus()
        self.desired: set[str] = set()
        self.resubs: list[str] = []
        self.perf = 0.0
        self.now = 0.0
        self.listed = {SYM}

        async def resub(topic: str) -> None:
            self.resubs.append(topic)

        self.stream = BookStream(
            bus=self.bus, env="live", set_desired=self._desire, topic_for=book_topic,
            parse_frame=lambda f: parse_book_frame(f, TICKS.get), resubscribe=resub,
            is_listed=self.listed.__contains__, touch=lambda _t: None, clock=lambda: self.now,
            now_us=lambda: int(self.now * 1_000_000), rand=lambda: 0.0, depth_500=depth_500,
            perf=self._perf,
        )  # fmt: skip
        self.quotes = self._sub("md", "quote")
        self.desyncs = self._sub("health", "book_desync")

    def _desire(self, topics: set[str]) -> None:
        self.desired = set(topics)

    def _perf(self) -> float:
        self.perf += 0.002  # 2 ms between two reads
        return self.perf

    def _sub(self, domain: str, detail: str) -> Any:
        pattern = TopicPattern(env="live", domain=domain, symbol=SYM, detail=detail)
        return self.bus.subscribe(f"t-{detail}", pattern, QueuePolicy.NEVER_DROP, maxsize=10_000)


def drain(q: Any) -> list[Any]:
    out = []
    while q.qsize():
        out.append(q.get_nowait())
    return out


def resyncs(reason: str, depth: str = "200") -> float:
    child = ingest_book_resyncs_total.labels(symbol=symbol_label(SYM), reason=reason, depth=depth)
    return float(child._value.get())


async def test_a_500_demand_moves_the_tier_only_with_heatmap_depth_500() -> None:
    off = Rig()
    off.stream.acquire_depth("ws:book:500", SYM, 500)
    assert off.stream.tier(SYM) == 200 and off.desired == {book_topic(SYM, 200)}
    on = Rig(depth_500=True)
    on.stream.acquire_depth("ws:book:50", SYM, 50)
    assert on.stream.tier(SYM) == 200
    on.stream.acquire_depth("ws:book:500", SYM, 500)
    assert on.stream.tier(SYM) == DEEP_TIER and on.desired == {book_topic(SYM, 500)}


async def test_the_tier_swaps_to_500_and_back_once_the_demand_is_gone() -> None:
    r = Rig(depth_500=True)
    r.stream.acquire_depth("ws:book:200", SYM, 200)
    await r.stream.handle_frame(RAW[0])
    assert r.stream.phase(SYM) is BookPhase.LIVE and await r.stream.apply_tiers() == 0
    r.stream.acquire_depth("ws:book:500", SYM, 500)
    assert await r.stream.apply_tiers() == 1  # the 500 tier warms, muted, beside the 200 one
    assert r.desired == {book_topic(SYM, 200), book_topic(SYM, 500)}
    assert await r.stream.apply_tiers() == 0  # already warming
    deep = json.loads(RAW[0])
    deep["topic"] = book_topic(SYM, 500)
    await r.stream.handle_frame(json.dumps(deep))
    engine = r.stream.engine(SYM)
    assert engine is not None and engine.depth == 500 and r.desired == {book_topic(SYM, 500)}
    r.stream.release("ws:book:500", SYM)
    assert r.stream.tier(SYM) == 200 and await r.stream.apply_tiers() == 1
    r.stream.release("ws:book:200", SYM)
    assert r.stream.tier(SYM) == 200


async def test_a_warming_tier_that_never_snapshots_falls_back_past_its_deadline() -> None:
    """F2: the warming 500 tier re-requests its snapshot on the active tier's timeout and, past
    the warm-up deadline, is dropped, so the symbol is never wedged and demand can fall back."""
    r = Rig(depth_500=True)
    r.stream.acquire_depth("ws:book:200", SYM, 200)
    await r.stream.handle_frame(RAW[0])
    r.stream.acquire_depth("ws:book:500", SYM, 500)
    assert await r.stream.apply_tiers() == 1  # no 500 snapshot ever arrives
    r.now = SNAPSHOT_TIMEOUT_S + 1
    assert await r.stream.check_timeouts() == 1 and r.resubs == [book_topic(SYM, 500)]
    r.now = WARMUP_DEADLINE_S + 1
    await r.stream.check_timeouts()
    engine = r.stream.engine(SYM)
    assert engine is not None and engine.depth == 200 and r.desired == {book_topic(SYM, 200)}
    assert await r.stream.apply_tiers() == 0  # re-warm backs off (test_book_tier_rewarm_backoff)
    r.now += WARMUP_DEADLINE_S
    assert await r.stream.apply_tiers() == 1  # the 500 demand is still there: it warms again
    r.stream.release("ws:book:500", SYM)
    r.now += WARMUP_DEADLINE_S + 1
    await r.stream.check_timeouts()
    assert await r.stream.apply_tiers() == 0 and r.desired == {book_topic(SYM, 200)}


async def test_a_delisted_symbol_forgets_its_depth_demand() -> None:
    """F6: pruning an unlisted symbol drops its per-consumer depth demand with its book."""
    r = Rig(depth_500=True)
    r.stream.acquire_depth("ws:book:500", SYM, 500)
    await r.stream.handle_frame(RAW[0])
    assert r.stream.tier(SYM) == DEEP_TIER
    r.listed.clear()
    assert await r.stream.prune_unlisted() == [SYM]
    assert r.stream.tier(SYM) == 200


async def test_best_quote_is_published_on_going_live_and_only_on_change() -> None:
    r = Rig()
    r.stream.acquire("c", SYM)
    await r.stream.handle_frame(RAW[0])
    first = drain(r.quotes)
    assert len(first) == 1 and isinstance(first[0], BestQuoteEvent)
    engine = r.stream.engine(SYM)
    assert engine is not None and engine.book is not None
    (bid,), (ask,) = engine.book.top(1)
    assert (first[0].bid, first[0].ask) == (bid.price, ask.price)
    quotes = 0
    for line in RAW[1:200]:
        before = engine.book.top(1) if engine.book is not None else None
        await r.stream.handle_frame(line)
        got = drain(r.quotes)
        after = engine.book.top(1) if engine.book is not None else None
        assert len(got) == (1 if after != before else 0)
        quotes += len(got)
    assert quotes > 0


async def test_a_gap_publishes_one_desync_event_with_its_structured_log() -> None:
    r = Rig()
    r.stream.acquire("c", SYM)
    before = resyncs("sequence_gap")
    with structlog.testing.capture_logs() as logs:
        for line in RAW[:2701]:  # the corpus's `u` hole is frame 2700
            await r.stream.handle_frame(line)
    events = drain(r.desyncs)
    assert len(events) == 1 and isinstance(events[0], BookDesyncEvent)
    ev = events[0]
    hole = json.loads(RAW[2700])["data"]["u"]
    assert (ev.reason, ev.depth, ev.got_update_id, ev.resync_count) == (
        "sequence_gap",
        200,
        hole,
        1,
    )
    assert ev.prev_update_id == json.loads(RAW[2699])["data"]["u"]
    logged = [entry for entry in logs if entry["event"] == "book_desync"]
    assert len(logged) == 1
    assert {k: logged[0][k] for k in ("prev_update_id", "got_update_id", "resync_count")} == {
        "prev_update_id": ev.prev_update_id, "got_update_id": hole, "resync_count": 1,
    }  # fmt: skip
    assert resyncs("sequence_gap") == before + 1


async def test_a_crossed_book_counts_book_crossed_total() -> None:
    r = Rig()
    r.stream.acquire("c", SYM)
    await r.stream.handle_frame(RAW[0])
    engine = r.stream.engine(SYM)
    assert engine is not None and engine.book is not None
    (_,), (ask,) = engine.book.top(1)
    crossing = {
        "topic": book_topic(SYM, 200), "type": "delta", "ts": 1700000002000,
        "data": {"s": SYM, "b": [[format(ask.price, "f"), "1.000"]], "a": [],
                 "u": engine.last_u + 1, "seq": 1},
    }  # fmt: skip
    child = book_crossed_total.labels(symbol=symbol_label(SYM))
    before = float(child._value.get())
    await r.stream.handle_frame(json.dumps(crossing))
    assert float(child._value.get()) == before + 1
    assert [e.reason for e in drain(r.desyncs)] == ["crossed"]
    assert r.stream.phase(SYM) is BookPhase.SNAPSHOT_PENDING


async def test_apply_latency_is_observed_per_applied_delta() -> None:
    r = Rig()
    r.stream.acquire("c", SYM)
    child = book_apply_latency_ms.labels(symbol=symbol_label(SYM))
    count = _count(child)
    for line in RAW[:11]:  # one snapshot, ten deltas
        await r.stream.handle_frame(line)
    assert _count(child) == count + 10


def _count(child: Any) -> float:
    samples = (s for m in child.collect() for s in m.samples)
    return float(next(s.value for s in samples if s.name.endswith("_count")))


def test_a_book_subscribe_request_carries_at_most_ten_args() -> None:
    """E08's planner packs every book topic, any tier, into frames of at most 10 args."""
    topics = [book_topic(f"S{i:03d}USDT", d) for i in range(23) for d in (200, 500)]
    batches = SubscriptionPlanner().plan(topics)
    assert MAX_TOPICS_PER_FRAME == 10
    assert all(len(b.topics) <= 10 for b in batches)
    assert sorted(t for b in batches for t in b.topics) == sorted(topics)


def test_the_resync_counter_names_the_active_tier() -> None:
    assert ingest_book_resyncs_total._labelnames == ("symbol", "reason", "depth")
