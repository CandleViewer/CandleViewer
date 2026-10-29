"""#604 (Fable security delta, Medium): a 500 tier the venue never snapshots is not re-warmed
every `WARMUP_DEADLINE_S` forever. Each abandonment counts
`ingest_book_tier_warmup_abandoned_total{symbol}` and pushes the next re-warm out (30 s doubling
to 10 min); the abandoned tier's LIVE, a change of the 500 demand set or forgetting the symbol
resets it, and the abandoned tier's snapshot backoff is not inherited by the LIVE active tier."""

from __future__ import annotations

import json

import structlog

from candleviewer.book.models import BookPhase
from candleviewer.exchange.bybit.orderbook import book_topic
from candleviewer.ingestion.metrics import ingest_book_tier_warmup_abandoned_total, symbol_label
from candleviewer.orderbook_wiring import (
    REWARM_BACKOFF_BASE_S,
    REWARM_BACKOFF_CAP_S,
    WARMUP_DEADLINE_S,
)
from tests.unit.ingestion.test_book_stream_tiers_quote_desync import RAW, SYM, Rig


def abandoned() -> float:
    child = ingest_book_tier_warmup_abandoned_total.labels(symbol=symbol_label(SYM))
    return float(child._value.get())


async def tick(r: Rig) -> tuple[int, float]:
    """One `_timeout_loop` pass at `r.now`: the tier changes started, the abandonments seen."""
    before = abandoned()
    r.stream.sync()
    started = await r.stream.apply_tiers()
    await r.stream.check_timeouts()
    return started, abandoned() - before


async def live_200_wanting_500() -> Rig:
    r = Rig(depth_500=True)
    r.stream.acquire_depth("ws:book:200", SYM, 200)
    await r.stream.handle_frame(RAW[0])
    assert r.stream.phase(SYM) is BookPhase.LIVE
    r.stream.acquire_depth("ws:book:500", SYM, 500)
    return r


async def run_cycles(r: Rig, cycles: int) -> tuple[list[float], list[float]]:
    """Step a 1 s clock until `cycles` abandonments: the warm starts and the abandonments."""
    starts: list[float] = []
    ends: list[float] = []
    while len(ends) < cycles:
        started, n = await tick(r)
        if started:
            starts.append(r.now)
        if n:
            assert n == 1.0  # once per abandonment
            ends.append(r.now)
        r.now += 1.0
    r.now -= 1.0  # left at the last abandonment
    return starts, ends


def test_the_rewarm_backoff_constants() -> None:
    assert REWARM_BACKOFF_BASE_S == WARMUP_DEADLINE_S == 30.0
    assert REWARM_BACKOFF_CAP_S == 600.0


async def test_repeated_abandonment_doubles_the_rewarm_delay_to_its_cap() -> None:
    r = await live_200_wanting_500()
    with structlog.testing.capture_logs() as logs:
        starts, ends = await run_cycles(r, 8)
    assert [e - s for s, e in zip(starts, ends, strict=True)] == [WARMUP_DEADLINE_S] * 8
    delays = [s - e for e, s in zip(ends, starts[1:], strict=False)]
    assert delays == [30.0, 60.0, 120.0, 240.0, 480.0, 600.0, 600.0]
    warned = [e for e in logs if e["event"] == "book_tier_warmup_abandoned"]
    assert len(warned) == 8 and warned[-1]["retry_in_s"] == 600.0
    assert r.stream.rewarm_at(SYM) == ends[-1] + REWARM_BACKOFF_CAP_S
    engine = r.stream.engine(SYM)
    assert engine is not None and engine.depth == 200 and r.desired == {book_topic(SYM, 200)}


async def test_the_abandoned_tier_going_live_resets_the_backoff() -> None:
    r = await live_200_wanting_500()
    _, ends = await run_cycles(r, 2)
    r.now = ends[-1] + 60.0
    assert await r.stream.apply_tiers() == 1  # the third warm-up
    deep = json.loads(RAW[0])
    deep["topic"] = book_topic(SYM, 500)
    await r.stream.handle_frame(json.dumps(deep))
    engine = r.stream.engine(SYM)
    assert engine is not None and engine.depth == 500 and engine.phase is BookPhase.LIVE
    assert r.stream.rewarm_at(SYM) is None


async def test_releasing_and_reacquiring_the_500_demand_resets_the_backoff() -> None:
    r = await live_200_wanting_500()
    _, ends = await run_cycles(r, 3)
    assert r.stream.rewarm_at(SYM) == ends[-1] + 120.0
    assert await r.stream.apply_tiers() == 0  # backing off
    r.stream.release("ws:book:500", SYM)
    r.stream.acquire_depth("ws:book:500", SYM, 500)
    assert r.stream.rewarm_at(SYM) is None
    assert await r.stream.apply_tiers() == 1  # warms at once


async def test_a_forgotten_symbol_drops_its_backoff() -> None:
    r = await live_200_wanting_500()
    await run_cycles(r, 1)
    assert r.stream.rewarm_at(SYM) is not None
    r.listed.clear()
    assert await r.stream.prune_unlisted() == [SYM]
    assert r.stream.rewarm_at(SYM) is None


async def test_the_live_active_tier_does_not_inherit_the_abandoned_tiers_backoff() -> None:
    """Item 3: the abandoned tier's snapshot timeouts grew the symbol's resync backoff; once it
    is dropped, a gap on the LIVE active tier resubscribes at once, not after that cooldown."""
    r = await live_200_wanting_500()
    await run_cycles(r, 6)
    r.resubs.clear()
    await r.stream.invalidate_symbol(SYM, "sequence_gap")
    assert r.resubs == [book_topic(SYM, 200)]
