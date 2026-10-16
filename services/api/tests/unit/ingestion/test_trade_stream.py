"""E08-S04 acceptance scenarios: trade tape (fake clock, recorded-shape fixtures, no network)."""

from __future__ import annotations

import asyncio
import functools
import json
import time
from collections.abc import Sequence
from decimal import Decimal
from itertools import pairwise
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy
from candleviewer.exchange.base.models import TradeEvent
from candleviewer.exchange.base.trade_print import TradePrint
from candleviewer.exchange.bybit.trades import (
    parse_recent_trades,
    parse_trade_frame,
    recent_trades_fetcher,
    trade_topic,
)
from candleviewer.ingestion import trade_stream as trade_stream_mod
from candleviewer.ingestion.metrics import (
    trade_duplicates_suppressed_total,
    trade_gaps_total,
)
from candleviewer.ingestion.ticker_stream import UnknownSymbolError
from candleviewer.ingestion.trade_stream import (
    GAP_RETRY_MAX_S,
    GAP_RETRY_MIN_S,
    UNRECOVERED_RETENTION_S,
    DedupeRing,
    GapEvent,
    TradeStream,
    merge_ordered,
)
from candleviewer.ingestion.watchdog import FeedHealthEvent
from tests._corpus import corpus_path
from tests.unit.ingestion._fakes import ParkingSleep, settle

FIX = corpus_path("ws")
FRAMES = (FIX / "publicTrade_BTCUSDT.jsonl").read_text(encoding="utf-8").splitlines()
RECENT = json.loads(corpus_path("rest/recent_trade_BTCUSDT.json").read_text(encoding="utf-8"))
ID = "a0000001-0000-4000-8000-00000000000"


def _val(counter: Any, **labels: str) -> float:
    return float(counter.labels(**labels)._value.get())


async def _park(_delay: float) -> None:
    """Default gap-retry `sleep`: parks until the test ends (never real time, C-13.7)."""
    await asyncio.Event().wait()


class Harness:
    def __init__(
        self,
        fetch: Any = None,
        writer: Any = None,
        maxsize: int = 100_000,
        retry_sleep: Any = _park,
        clock: Any = lambda: 0.0,
    ) -> None:
        self.bus = Bus()
        self.desired: set[str] = set()
        self.sub = self.bus.subscribe(
            "t", "live.md.*.trade", QueuePolicy.NEVER_DROP, maxsize=maxsize
        )
        self.gaps = self.bus.subscribe("g", "live.md.*.gap", QueuePolicy.NEVER_DROP)
        self.stream = TradeStream(
            bus=self.bus,
            env="live",
            set_desired=self._set,
            parse_frame=parse_trade_frame,
            topic_for=trade_topic,
            is_listed=lambda s: s in ("BTCUSDT", "ETHUSDT"),
            touch=lambda _t: None,
            fetch_recent=fetch,
            tick_size=lambda _s: Decimal("0.10"),
            clock=clock,
            now_us=lambda: 1_700_000_009_500_000,
            writer=writer,
            retry_sleep=retry_sleep,
            retry_rand=lambda: 0.5,
        )
        self.stream.acquire("tape", "BTCUSDT")
        # #1905: backfill runs off the dispatch path; these scenarios assert
        # the merged outcome, so each frame is followed by its backfill.
        inner = self.stream.handle_frame

        async def handle_and_settle(frame: str) -> None:
            await inner(frame)
            await self.stream.wait_backfills()

        self.stream.handle_frame = handle_and_settle  # type: ignore[method-assign]

    def _set(self, desired: set[str]) -> None:
        self.desired = set(desired)

    def events(self) -> list[TradeEvent]:
        out = []
        while not self.sub.queue.empty():
            out.append(self.sub.queue.get_nowait())
        return out

    def gap_events(self) -> list[GapEvent]:
        out = []
        while not self.gaps.queue.empty():
            out.append(self.gaps.queue.get_nowait())
        return out


async def _recent(_s: str) -> Sequence[TradePrint]:
    return parse_recent_trades("BTCUSDT", RECENT)


async def _reconnect(h: Harness) -> None:
    await h.stream.process_health(FeedHealthEvent("publicTrade.BTCUSDT", "resubscribing", 0.0))


# ---- Scenario: Ingest -------------------------------------------------------
async def test_ingest_normalises_and_publishes_each_print_once() -> None:
    h = Harness()
    assert h.desired == {"publicTrade.BTCUSDT"}
    for f in FRAMES[:2]:
        await h.stream.handle_frame(f)
    ev = h.events()
    assert [e.trade_id for e in ev] == [f"{ID}1", f"{ID}2", f"{ID}3"]
    first = ev[0]
    assert first.ts_event == 1_700_000_000_050_000  # ms -> µs
    assert (first.price, first.qty, first.side) == (Decimal("63120.50"), Decimal("0.010"), "buy")
    assert first.notional == Decimal("63120.50") * Decimal("0.010")
    assert first.price_ticks == 631205
    assert first.source == "live" and [e.seq for e in ev] == [1, 2, 3]
    assert ev[2].is_block_trade is True and first.is_block_trade is False


def test_bybit_S_is_the_taker_side() -> None:
    """Documented fixture: `S`="Buy" = taker lifted the ask; never re-derived from `L`."""
    prints = parse_trade_frame(FRAMES[0])
    assert prints is not None
    assert [(p.trade_id[-1], p.side) for p in prints] == [("1", "buy"), ("2", "sell")]


def test_parser_ignores_other_topics_and_rejects_hostile_payloads() -> None:
    assert parse_trade_frame('{"topic":"tickers.BTCUSDT","data":{}}') is None
    assert parse_trade_frame("not json") is None
    rec = json.loads(FRAMES[0])
    for mutate in (
        lambda r: r["data"][0].__setitem__("i", "x" * 65),
        lambda r: r["data"][0].__setitem__("p", "NaN"),
        lambda r: r["data"][0].__setitem__("v", "-1"),
        lambda r: r["data"][0].__setitem__("S", "Up"),
        lambda r: r.__setitem__("data", [r["data"][0]] * 2001),
        lambda r: r.__setitem__("topic", "publicTrade.bad*"),
    ):
        bad = json.loads(FRAMES[0])
        mutate(bad)
        with pytest.raises(ValueError):
            parse_trade_frame(json.dumps(bad))
    assert rec  # untouched original


async def test_unknown_symbol_cannot_create_topic() -> None:
    h = Harness()
    with pytest.raises(UnknownSymbolError):
        h.stream.acquire("x", "EVIL.*")


async def test_malformed_frame_is_dropped_stream_continues() -> None:
    h = Harness()
    await h.stream.handle_frame('{"topic":"publicTrade.BTCUSDT","data":[{"s":"BTCUSDT"}]}')
    await h.stream.handle_frame(FRAMES[1])
    assert [e.trade_id for e in h.events()] == [f"{ID}3"]


# ---- Scenario: Gap detection and backfill / Backfill overlaps live data ------
async def test_reconnect_records_gap_backfills_and_marks_window() -> None:
    h = Harness(fetch=_recent)
    for f in FRAMES[:2]:
        await h.stream.handle_frame(f)
    h.events()
    await _reconnect(h)
    assert "BTCUSDT" in h.stream.open_gaps()
    before = _val(trade_gaps_total, symbol="BTCUSDT", recovered="true")
    await h.stream.handle_frame(FRAMES[2])
    (gap,) = h.gap_events()
    assert (gap.start_us, gap.end_us, gap.recovered) == (
        1_700_000_000_290_000,
        1_700_000_009_000_000,
        True,
    )
    assert gap.reason == "reconnect" and gap.label() == "Backfilled 22:13:20-22:13:29"
    assert _val(trade_gaps_total, symbol="BTCUSDT", recovered="true") == before + 1
    ev = h.events()
    assert [e.trade_id[-1] for e in ev] == ["4", "5", "6", "7"]
    assert [e.source for e in ev] == ["backfill"] * 3 + ["live"]
    assert h.stream.gaps("BTCUSDT") == [gap]


async def test_backfill_overlap_each_id_once_ordered_never_backwards() -> None:
    h = Harness(fetch=_recent)
    for f in FRAMES[:2]:
        await h.stream.handle_frame(f)
    await _reconnect(h)
    await h.stream.handle_frame(FRAMES[2])
    ev = h.events()
    ids = [e.trade_id for e in ev]
    assert len(ids) == len(set(ids)) == 7
    keys = [(e.ts_event, e.trade_id) for e in ev]
    assert keys[2:] == sorted(keys[2:])  # 5 and 6 share ts 5000 ms -> ordered by trade_id
    assert all(a.ts_event <= b.ts_event for a, b in pairwise(ev) if a.seq > 2)


# ---- Scenario: Duplicate suppression -------------------------------------
async def test_same_trade_id_after_reconnect_ingested_once_and_counted() -> None:
    h = Harness()
    await h.stream.handle_frame(FRAMES[1])
    before = _val(trade_duplicates_suppressed_total, symbol="BTCUSDT")
    await _reconnect(h)
    await h.stream.handle_frame(FRAMES[1])  # replayed after reconnect
    assert [e.trade_id for e in h.events()] == [f"{ID}3"]
    assert _val(trade_duplicates_suppressed_total, symbol="BTCUSDT") == before + 1


def test_dedupe_ring_is_bounded() -> None:
    ring = DedupeRing(capacity=3)
    assert all(ring.add(str(i)) for i in range(5))
    assert len(ring) == 3
    assert not ring.add("4") and ring.add("0")  # evicted oldest is new again


# ---- Scenario: Backfill unavailable ----------------------------------------
@pytest.mark.parametrize("mode", ["rate_limited", "short", "none"])
async def test_backfill_unavailable_leaves_gap_unrecovered_stream_continues(mode: str) -> None:
    async def rate_limited(_s: str) -> Sequence[TradePrint]:
        raise RuntimeError("10006 rate limit")

    async def short(_s: str) -> Sequence[TradePrint]:
        return [p for p in parse_recent_trades("BTCUSDT", RECENT) if p.trade_id[-1] in "67"]

    fetch = {"rate_limited": rate_limited, "short": short, "none": None}[mode]
    sleep = ParkingSleep()
    h = Harness(fetch=fetch, retry_sleep=sleep)
    await h.stream.handle_frame(FRAMES[1])
    await _reconnect(h)
    before = _val(trade_gaps_total, symbol="BTCUSDT", recovered="false")
    await h.stream.handle_frame(FRAMES[2])
    (gap,) = h.gap_events()
    assert gap.recovered is False and gap.start_us < gap.end_us
    assert gap.label().startswith("No data ")
    assert _val(trade_gaps_total, symbol="BTCUSDT", recovered="false") == before + 1
    assert h.events()[-1].trade_id == f"{ID}7"  # stream continues
    assert h.stream.unrecovered_gaps() == {"BTCUSDT": (gap.start_us, gap.end_us)}  # #2715
    await settle()  # only a failed fetch is retried: a short page already scrolled past it
    assert len(sleep.delays) == (1 if mode == "rate_limited" else 0)
    await h.stream.stop()


async def test_recent_trades_fetcher_passes_limit_1000() -> None:
    seen: dict[str, Any] = {}

    async def get_public(path: str, *, params: dict[str, Any]) -> dict[str, Any]:
        seen.update(params, path=path)
        return RECENT

    rows = await recent_trades_fetcher(get_public)("BTCUSDT")
    assert seen["limit"] == 1000 and seen["path"] == "/v5/market/recent-trade"
    assert len(rows) == 6 and rows[-1].ts_event_us == 1_700_000_000_050_000


async def test_frame_loss_marks_gap() -> None:
    h = Harness()
    await h.stream.handle_frame(FRAMES[1])
    h.stream.mark_gap("frame_loss", "BTCUSDT")
    await h.stream.handle_frame(FRAMES[2])
    (gap,) = h.gap_events()
    assert gap.reason == "frame_loss" and gap.recovered is False


# ---- Property: any interleaving of live and backfilled prints ----------------
def _p(i: int, ts_ms: int) -> TradePrint:
    one = Decimal("1")
    return TradePrint("BTCUSDT", f"t{i:05d}", ts_ms * 1000, one, one, "buy", False)


def _frame(prints: Sequence[TradePrint]) -> str:
    data = [
        {"T": p.ts_event_us // 1000, "s": p.symbol, "S": "Buy", "v": "1", "p": "1", "i": p.trade_id}
        for p in prints
    ]
    return json.dumps({"topic": "publicTrade.BTCUSDT", "data": data})


@settings(max_examples=60, deadline=None)
@given(
    ts=st.lists(st.integers(1, 50), min_size=2, max_size=40),
    split=st.integers(0, 40),
    picks=st.lists(st.booleans(), min_size=40, max_size=40),
    dupes=st.lists(st.integers(0, 39), max_size=10),
)
def test_property_interleaving_is_duplicate_free_and_ordered(
    ts: list[int], split: int, picks: list[bool], dupes: list[int]
) -> None:
    import asyncio

    tape = [_p(i, t) for i, t in enumerate(sorted(ts))]
    cut = min(split, len(tape) - 1)
    before, after = tape[:cut], tape[cut:]
    page = [p for p, keep in zip(tape, picks, strict=False) if keep]
    replay = [tape[d] for d in dupes if d < len(tape)]

    async def fetch(_s: str) -> Sequence[TradePrint]:
        return page

    async def run() -> list[TradeEvent]:
        h = Harness(fetch=fetch)
        if before:
            await h.stream.handle_frame(_frame(before))
        await _reconnect(h)
        await h.stream.handle_frame(_frame(after))
        if replay:
            await h.stream.handle_frame(_frame(replay))
        return h.events()

    ev = asyncio.run(run())
    ids = [e.trade_id for e in ev]
    assert len(ids) == len(set(ids))
    assert set(ids) >= {p.trade_id for p in tape}
    assert all(a.ts_event <= b.ts_event for a, b in pairwise(ev))


def test_merge_ordered_ties_by_trade_id() -> None:
    a, b = _p(2, 5), _p(1, 5)
    assert merge_ordered([a], [b, a]) == [b, a]


# ---- Scenario: Burst without loss ---------------------------------------
async def test_burst_5000_prints_per_second_no_loss_with_backpressure() -> None:
    import asyncio

    from candleviewer.bus.metrics import ingest_queue_full_total

    h = Harness(maxsize=64)  # slow consumer: queue fills, reader must block, not drop
    h.stream.acquire("tape", "ETHUSDT")
    full_before = _val(ingest_queue_full_total, **{"class": "trade"})
    got: list[TradeEvent] = []
    total = 5000

    async def consumer() -> None:
        while len(got) < total:
            got.append(await h.sub.queue.get())
            if len(got) % 100 == 0:
                await asyncio.sleep(0)

    task = asyncio.create_task(consumer())
    lat: list[float] = []
    for b in range(100):  # 100 frames x 50 prints = one second of 5 000 prints
        sym = "BTCUSDT" if b % 2 else "ETHUSDT"
        prints = [_p(b * 50 + i, 1000 + b) for i in range(50)]
        frame = _frame(prints).replace("BTCUSDT", sym)
        t0 = time.perf_counter()
        await h.stream.handle_frame(frame)
        lat.append((time.perf_counter() - t0) / 50)
    await asyncio.wait_for(task, 10)
    assert len(got) == total and len({(e.symbol, e.trade_id) for e in got}) == total
    assert _val(ingest_queue_full_total, **{"class": "trade"}) > full_before
    lat.sort()
    assert lat[int(len(lat) * 0.95)] < 0.020  # ingest->bus p95 budget per print


# ---- QuestDB write-behind ---------------------------------------------
class _Writer:
    def __init__(self, fail: bool = False) -> None:
        self.rows: list[TradeEvent] = []
        self.fail = fail

    async def write_trades(self, events: Sequence[TradeEvent]) -> None:
        if self.fail:
            raise OSError("questdb down")
        self.rows.extend(events)


async def test_write_behind_batches_and_survives_writer_failure() -> None:
    w = _Writer()
    h = Harness(writer=w)
    for f in FRAMES[:2]:
        await h.stream.handle_frame(f)
    assert await h.stream.drain_writes() == 3
    assert [e.trade_id[-1] for e in w.rows] == ["1", "2", "3"]
    w.fail = True
    await h.stream.handle_frame(FRAMES[2])
    assert await h.stream.drain_writes() == 0  # logged, not raised; requeued (#1918)
    assert h.stream.write_behind.qsize() == 1 and h.stream.write_behind.degraded
    w.fail = False
    assert await h.stream.drain_writes() == 1
    assert len(w.rows) == 4 and not h.stream.write_behind.degraded


async def test_stalled_writer_never_blocks_reader() -> None:
    from candleviewer.ingestion import trade_stream as ts

    h = Harness(writer=_Writer())
    for i in range(ts.WRITE_QUEUE_MAXSIZE + 10):  # nobody drains: drop-oldest, counted
        await h.stream.handle_frame(_frame([_p(i, 1 + i)]))
    assert h.stream._writes.qsize() == ts.WRITE_QUEUE_MAXSIZE


async def test_lifecycle_health_loop_marks_gap_and_release_unsubscribes() -> None:
    import asyncio

    h = Harness()
    await h.stream.start()
    await h.stream.handle_frame(FRAMES[1])
    from candleviewer.bus.models import Topic

    await h.bus.publish(
        Topic(env="live", domain="health", detail="feed"),
        FeedHealthEvent("publicTrade.BTCUSDT", "degraded", 0.0),
    )
    for _ in range(5):
        await asyncio.sleep(0)
    assert h.stream.open_gaps()["BTCUSDT"][1] == "reconnect"
    await h.stream.stop()
    h.stream.release("tape", "BTCUSDT")
    h.stream._demand._grace = 0.0
    h.stream.sync()
    assert h.desired == set() and h.stream.open_gaps() == {}
    assert h.stream.is_listed("BTCUSDT") and len(h.stream.recent("BTCUSDT")) == 1


async def test_frames_for_unsubscribed_symbol_ignored() -> None:
    h = Harness()
    await h.stream.handle_frame(FRAMES[0].replace("BTCUSDT", "SOLUSDT"))
    await h.stream.handle_frame('{"topic":"tickers.BTCUSDT"}')
    assert h.events() == []


# ---- #2715: an unrecovered window stays reported and is retried -------------------------
class _Rest:
    """Recent-trade REST double: each call pops the next answer (an exception is raised);
    once the answers run out the venue keeps failing."""

    def __init__(self, *answers: Exception | Sequence[TradePrint]) -> None:
        self.answers = list(answers)
        self.calls = 0

    async def __call__(self, _s: str) -> Sequence[TradePrint]:
        self.calls += 1
        answer = self.answers.pop(0) if self.answers else RuntimeError("503")
        if isinstance(answer, Exception):
            raise answer
        return answer


PAGE = parse_recent_trades("BTCUSDT", RECENT)  # prints 1, 3-7: reaches back past print 3


async def _unrecovered(h: Harness) -> GapEvent:
    """Print 3, reconnect, then print 7 closes the window while the first backfill fails."""
    await h.stream.handle_frame(FRAMES[1])
    await _reconnect(h)
    await h.stream.handle_frame(FRAMES[2])
    (gap,) = h.gap_events()
    assert gap.recovered is False
    return gap


async def test_failed_gap_backfill_is_retried_on_a_capped_jittered_backoff() -> None:
    rest, sleep = _Rest(), ParkingSleep()  # the venue's REST stays down
    h = Harness(fetch=rest, retry_sleep=sleep)
    await _unrecovered(h)
    for _ in range(7):
        await settle()
        sleep.release()
    await settle()
    steps = [min(GAP_RETRY_MAX_S, GAP_RETRY_MIN_S * 2**n) for n in range(8)]
    assert sleep.delays == [0.75 * step for step in steps]  # equal jitter at rand 0.5
    assert rest.calls == 1 + 7  # one page per attempt, on the first backfill's REST path
    assert "BTCUSDT" in h.stream.unrecovered_gaps()
    await h.stream.stop()
    assert sleep.parked[-1].cancelled()  # stop() cancels the tracked retry


async def test_gap_retry_waits_out_empty_and_lagging_pages_then_heals() -> None:
    lagging = [p for p in PAGE if p.trade_id[-1] != "7"]  # REST behind the window end
    rest, sleep, w = _Rest(RuntimeError("503"), [], lagging, PAGE), ParkingSleep(), _Writer()
    h = Harness(fetch=rest, retry_sleep=sleep, writer=w)
    gap = await _unrecovered(h)
    for _ in range(3):
        await settle()
        assert h.stream.unrecovered_gaps() == {"BTCUSDT": (gap.start_us, gap.end_us)}
        sleep.release()
    await settle()
    assert h.stream.unrecovered_gaps() == {}
    assert len(sleep.delays) == 3 and rest.calls == 4  # healed: no further retry
    while h.stream.write_behind.qsize():
        await h.stream.drain_writes()
    assert [e.trade_id[-1] for e in w.rows if e.source == "backfill"] == ["4", "5", "6"]
    assert [e.trade_id[-1] for e in h.events()] == ["3", "7"]  # never on the live topic
    assert h.gap_events() == []


async def test_gap_retry_stops_once_the_page_has_scrolled_past_the_window() -> None:
    scrolled = [p for p in PAGE if p.trade_id[-1] in "67"]  # oldest print after the start
    rest, sleep = _Rest(RuntimeError("503"), scrolled), ParkingSleep()
    h = Harness(fetch=rest, retry_sleep=sleep)
    gap = await _unrecovered(h)
    await settle()
    sleep.release()
    await settle()
    assert rest.calls == 2 and len(sleep.delays) == 1  # later pages only move forward
    assert h.stream.unrecovered_gaps() == {"BTCUSDT": (gap.start_us, gap.end_us)}  # a hole


async def test_unrecovered_windows_share_one_retry_and_stay_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(trade_stream_mod, "UNRECOVERED_WINDOWS_CAP", 2)
    rest, sleep = _Rest(), ParkingSleep()
    h = Harness(fetch=rest, retry_sleep=sleep)
    first = await _unrecovered(h)
    for i in range(2):  # two more unrecovered windows on the same symbol
        await _reconnect(h)
        await h.stream.handle_frame(_frame([_p(100 + i, 1_700_000_020_000 + 1000 * i)]))
    *_, last = h.gap_events()
    await settle()
    assert len(h.stream.unrecovered_windows("BTCUSDT")) == 2  # the newest folded into the last
    assert h.stream.unrecovered_gaps() == {"BTCUSDT": (first.start_us, last.end_us)}
    assert len(sleep.delays) == 1  # one retry per symbol, not one per window
    await h.stream.stop()


async def test_gap_retry_ends_without_rest_once_the_symbol_left_demand() -> None:
    now = [0.0]
    rest, sleep = _Rest(), ParkingSleep()
    h = Harness(fetch=rest, retry_sleep=sleep, clock=lambda: now[0])
    await _unrecovered(h)
    await settle()
    h.stream.release("tape", "BTCUSDT")
    assert "BTCUSDT" in h.stream.unrecovered_gaps()  # inside the 30 s demand grace
    now[0] = 31.0  # grace over; no sync() since
    assert h.stream.unrecovered_gaps() == {}
    calls = rest.calls
    sleep.release()
    await settle()
    assert rest.calls == calls and len(sleep.delays) == 1  # ended without a REST call


async def test_window_closed_during_a_retry_fetch_waits_for_the_next_retry() -> None:
    venue_answers = asyncio.Event()
    calls: list[str] = []

    async def fetch(symbol: str) -> Sequence[TradePrint]:
        calls.append(symbol)
        if len(calls) == 2:  # the retry's page; it only reaches the window-1 end
            await venue_answers.wait()
            return PAGE
        raise RuntimeError("503")

    sleep = ParkingSleep()
    h = Harness(fetch=fetch, retry_sleep=sleep)
    await _unrecovered(h)
    await settle()
    sleep.release()  # the retry's fetch is now in flight
    await settle()
    await _reconnect(h)  # a second window closes unrecovered meanwhile
    await h.stream.handle_frame(_frame([_p(100, 1_700_000_020_000)]))
    (second,) = h.gap_events()
    venue_answers.set()
    await settle()
    assert h.stream.unrecovered_gaps() == {"BTCUSDT": (second.start_us, second.end_us)}
    assert len(sleep.delays) == 2  # healed the first; the second waits for the next retry
    await h.stream.stop()


async def test_a_hole_the_first_page_cannot_reach_clears_after_the_retention_horizon() -> None:
    """#2715 review: the first page already starts after the window (later pages only move
    forward, so no retry); the hole is reported for `UNRECOVERED_RETENTION_S`, then only its
    `GapEvent(recovered=False)` remains, so one outage cannot pin health for good."""
    now = [0.0]
    scrolled = [p for p in PAGE if p.trade_id[-1] in "67"]
    h = Harness(fetch=_Rest(scrolled), clock=lambda: now[0])
    gap = await _unrecovered(h)
    now[0] = UNRECOVERED_RETENTION_S - 1.0
    assert h.stream.unrecovered_gaps() == {"BTCUSDT": (gap.start_us, gap.end_us)}
    now[0] = UNRECOVERED_RETENTION_S
    assert h.stream.unrecovered_gaps() == {}
    assert h.stream.unrecovered_windows("BTCUSDT") == []
    assert h.stream.gaps("BTCUSDT") == [gap]  # the permanent record


async def test_gap_retry_judges_each_window_against_the_page() -> None:
    """#2715 review: a page that no longer reaches window 1 still heals window 2 (its lost
    print reaches the hot tier); window 1 is not retried again and stays reported until the
    retention horizon ends."""
    now, w = [0.0], _Writer()
    rest, sleep = _Rest(), ParkingSleep()  # both windows' first backfill fails
    h = Harness(fetch=rest, retry_sleep=sleep, writer=w, clock=lambda: now[0])
    first = await _unrecovered(h)
    await _reconnect(h)
    await h.stream.handle_frame(_frame([_p(100, 1_700_000_020_000)]))
    (second,) = h.gap_events()
    assert (second.start_us, second.recovered) == (first.end_us, False)
    seven = [p for p in PAGE if p.trade_id[-1] == "7"]  # the page starts at window 2's start
    rest.answers.append([*seven, _p(101, 1_700_000_015_000), _p(100, 1_700_000_020_000)])
    await settle()
    sleep.release()
    await settle()
    assert h.stream.unrecovered_windows("BTCUSDT") == [(first.start_us, first.end_us)]
    assert rest.calls == 3 and len(sleep.delays) == 1  # nothing left worth a retry
    while h.stream.write_behind.qsize():
        await h.stream.drain_writes()
    assert [e.trade_id for e in w.rows if e.source == "backfill"] == ["t00101"]
    now[0] = UNRECOVERED_RETENTION_S
    assert h.stream.unrecovered_gaps() == {}


async def test_window_closing_as_the_retry_ends_still_gets_a_retry() -> None:
    """#2715 review: a finished retry task leaves `_retry_done` one loop turn later; a window
    that closes unrecovered in that turn must start its own retry, not count the done one."""
    answers: list[asyncio.Future[Sequence[TradePrint]]] = []

    async def fetch(_s: str) -> Sequence[TradePrint]:
        answer: asyncio.Future[Sequence[TradePrint]] = asyncio.get_running_loop().create_future()
        answers.append(answer)
        return await answer

    sleep = ParkingSleep()
    h = Harness(fetch=fetch, retry_sleep=sleep)
    frame = functools.partial(TradeStream.handle_frame, h.stream)  # backfills not awaited
    await frame(FRAMES[1])
    await _reconnect(h)
    await frame(FRAMES[2])  # window 1 closes ...
    await settle()
    answers[0].set_exception(RuntimeError("503"))  # ... unrecovered: its retry parks
    await settle()
    await _reconnect(h)
    await frame(_frame([_p(100, 1_700_000_020_000)]))  # window 2 closes; backfill pending
    await settle()
    sleep.release()
    await settle()  # the retry's page request is in flight too
    answers[2].set_result(PAGE)  # covers window 1: the retry task ends ...
    answers[1].set_exception(RuntimeError("503"))  # ... in the turn window 2 stays a hole
    await settle()
    _, second = h.gap_events()
    assert h.stream.unrecovered_gaps() == {"BTCUSDT": (second.start_us, second.end_us)}
    assert len(sleep.delays) == 2  # window 2 got a retry of its own
    await h.stream.stop()
