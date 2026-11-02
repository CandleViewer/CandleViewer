"""#1944: the write-behind healer refills hot-tier holes, verifies them, and clears whole runs.

Recorded-shape REST page (`rest/recent_trade_BTCUSDT.json`: prints 1, 3-7), a DEDUP-keyed fake
store, a fake clock and sleep; no network, no real time (C-13.7).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Collection, Sequence
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.bus.bus import Bus
from candleviewer.exchange.base.errors import RateLimitError
from candleviewer.exchange.base.models import TradeEvent
from candleviewer.exchange.base.trade_print import TradePrint
from candleviewer.exchange.bybit.trades import parse_recent_trades
from candleviewer.ingestion import write_behind as wb_mod
from candleviewer.ingestion.kline_coverage import Range
from candleviewer.ingestion.metrics import (
    book_writes_dropped_total,
    trade_writes_dropped_total,
    write_behind_heal_ranges_total,
    write_behind_heal_rows_total,
)
from candleviewer.ingestion.trade_stream import TradeStream
from candleviewer.ingestion.write_behind import WriteBehindBuffer
from candleviewer.ingestion.write_behind_heal import (
    HEAL_HORIZON_S,
    HEAL_SETTLE_S,
    WAL_LAG_RETRY_S,
    TradeHealPorts,
    WriteBehindHealer,
)
from tests._corpus import corpus_path
from tests.unit.ingestion._fakes import settle

RECENT = json.loads(corpus_path("rest/recent_trade_BTCUSDT.json").read_text(encoding="utf-8"))
PAGE = sorted(parse_recent_trades("BTCUSDT", RECENT), key=lambda p: (p.ts_event_us, p.trade_id))
P1, P3, P4, P5, P6, P7 = PAGE  # ts ...0.05 s, 0.29 s, 1 s, 5 s, 5 s, 9 s
SYM = "BTCUSDT"


def _val(counter: Any, **labels: str) -> float:
    return float(counter.labels(**labels)._value.get())


def _ranges(result: str, table: str = "trades") -> float:
    return _val(write_behind_heal_ranges_total, table=table, result=result)


class _Store:
    """The hot tier's `trades` table: DEDUP UPSERT KEYS (ts, symbol, trade_id)."""

    def __init__(self) -> None:
        self.rows: dict[tuple[int, str, str], TradeEvent] = {}
        self.down = False
        self.lagging_reads = 0  # reads that miss everything (WAL not applied yet)
        self.reads = 0
        self.read_down = False

    async def write_trades(self, events: Sequence[TradeEvent]) -> None:
        if self.down:
            raise OSError("questdb down")
        for e in events:
            self.rows[(e.ts_event, e.symbol, e.trade_id)] = e

    async def read_trade_ids(self, symbol: str, start_us: int, end_us: int) -> Collection[str]:
        self.reads += 1
        if self.read_down:
            raise OSError("pgwire down")
        if self.lagging_reads:
            self.lagging_reads -= 1
            return set()
        return {t for ts, s, t in self.rows if s == symbol and start_us <= ts < end_us}


class _Fetch:
    def __init__(self, page: Sequence[TradePrint] = PAGE) -> None:
        self.page, self.calls = list(page), 0
        self.fail: Exception | None = None
        self.during: list[Callable[[], Awaitable[None]]] = []  # awaited inside the fetch

    async def __call__(self, symbol: str) -> Sequence[TradePrint]:
        self.calls += 1
        for hook in list(self.during):
            await hook()
        if self.fail is not None:
            raise self.fail
        return self.page


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class _Sleep:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, s: float) -> None:
        self.delays.append(s)


def _stream() -> TradeStream:
    return TradeStream(
        bus=Bus(),
        env="live",
        set_desired=lambda _t: None,
        parse_frame=lambda _f: None,
        topic_for=lambda s: s,
        is_listed=lambda _s: True,
        touch=lambda _t: None,
    )


def _buf(maxsize: int = 1) -> WriteBehindBuffer[TradeEvent]:
    return WriteBehindBuffer(
        table="trades",
        maxsize=maxsize,
        dropped=trade_writes_dropped_total,
        key=lambda e: (e.symbol, e.ts_event),
        rand=lambda: 0.0,
    )


async def _lose(buf: WriteBehindBuffer[TradeEvent], lost: Sequence[TradePrint]) -> None:
    """A writer outage evicts `lost` (one closed run), then a write lands (recovery)."""
    to_event = _stream().heal_event
    buf.requeue([])  # the writer is failing
    for p in [*lost, P7]:
        buf.put(to_event(p))  # maxsize 1: each put evicts the previous row
    buf.succeeded(await buf.take(1))  # P7 lands: the open run closes, `degraded` clears


class _Rig:
    def __init__(self, *, max_work: int = 512) -> None:
        self.buf, self.store, self.fetch = _buf(), _Store(), _Fetch()
        self.clock, self.sleep = _Clock(), _Sleep()
        ports = TradeHealPorts(self.fetch, _stream().heal_event, self.store, self.store)
        self.healer = WriteBehindHealer(
            self.buf, table="trades", trades=ports, clock=self.clock, sleep=self.sleep,
            rand=lambda: 0.0, max_work=max_work,
        )  # fmt: skip

    async def settled_tick(self) -> None:
        """Recovered, then `HEAL_SETTLE_S` later: the first pass that may heal."""
        await self.healer.tick()
        self.clock.t += HEAL_SETTLE_S
        await self.healer.tick()


# ---- WriteBehindBuffer.clear ------------------------------------------------------------


async def test_clear_drops_only_wholly_covered_closed_runs() -> None:
    buf = _buf()
    await _lose(buf, [P1])
    await _lose(buf, [P3, P4])
    run1, run2 = buf.closed_ranges(SYM)
    assert buf.clear(SYM, [Range(run2.start_us, run2.end_us - 1)]) == 0  # partly covered: whole
    assert buf.clear(SYM, [run2]) == 1
    assert buf.lost_ranges(SYM) == [run1]
    assert buf.clear(SYM, [run1]) == 1 and buf.lost_ranges(SYM) == [] and buf.lost_symbols() == []
    assert buf.clear(SYM, [run1]) == 0  # nothing left


async def test_clear_never_touches_the_open_run() -> None:
    buf = _buf()
    to_event = _stream().heal_event
    buf.requeue([])
    for p in (P1, P3):  # P1 evicted: an open run, not closed
        buf.put(to_event(p))
    assert buf.lost_symbols() == [SYM] and buf.closed_ranges(SYM) == []
    assert buf.clear(SYM, [Range(0, 2**62)]) == 0
    assert buf.lost_ranges(SYM) == [Range(P1.ts_event_us, P1.ts_event_us + 1)]


async def test_clear_racing_an_eviction_keeps_the_run_that_grew(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wb_mod, "MAX_LOST_RUNS", 1)  # the next close merges into this run
    buf = _buf()
    await _lose(buf, [P1])
    snapshot = buf.closed_ranges(SYM)  # pre-heal
    await _lose(buf, [P4])  # an eviction during the heal: the run grows to cover P4
    grown = buf.closed_ranges(SYM)
    assert grown == [Range(P1.ts_event_us, P4.ts_event_us + 1)]
    assert buf.clear(SYM, snapshot) == 0  # not wholly covered: kept whole, never hidden
    assert buf.closed_ranges(SYM) == grown


# ---- the healer ------------------------------------------------------------------------


async def test_heal_outage_then_recovery_refills_the_hole_and_clears_the_run() -> None:
    rig = _Rig()
    await _lose(rig.buf, [P3, P4])
    healed, rows = _ranges("healed"), _val(write_behind_heal_rows_total, table="trades")
    await rig.settled_tick()
    assert rig.fetch.calls == 1
    assert {k[2] for k in rig.store.rows} == {P3.trade_id, P4.trade_id}  # in-run prints only
    assert {k[0] for k in rig.store.rows} == {P3.ts_event_us, P4.ts_event_us}  # real ts
    assert all(e.source == "backfill" for e in rig.store.rows.values())
    assert rig.buf.lost_ranges(SYM) == []
    assert _ranges("healed") == healed + 1
    assert _val(write_behind_heal_rows_total, table="trades") == rows + 2


async def test_heal_waits_until_the_writer_stays_recovered() -> None:
    rig = _Rig()
    await _lose(rig.buf, [P3])
    rig.buf.requeue([])  # degraded again
    await rig.settled_tick()
    assert rig.fetch.calls == 0
    rig.buf.succeeded()
    await rig.healer.tick()  # recovered, not yet settled
    rig.clock.t += HEAL_SETTLE_S - 1
    await rig.healer.tick()
    assert rig.fetch.calls == 0
    rig.buf.requeue([])  # a flap restarts the settle window
    await rig.healer.tick()
    rig.buf.succeeded()
    rig.clock.t += 1
    await rig.healer.tick()
    assert rig.fetch.calls == 0
    rig.clock.t += HEAL_SETTLE_S
    await rig.healer.tick()
    assert rig.fetch.calls == 1 and rig.buf.lost_ranges(SYM) == []


async def test_heal_rerun_is_idempotent_under_the_dedup_key() -> None:
    rig = _Rig()
    await _lose(rig.buf, [P3, P4])
    await rig.settled_tick()
    before = dict(rig.store.rows)
    await _lose(rig.buf, [P3, P4])  # the same hole again
    rig.clock.t += HEAL_SETTLE_S
    await rig.healer.tick()
    assert rig.fetch.calls == 2 and rig.buf.lost_ranges(SYM) == []
    assert rig.store.rows.keys() == before.keys()  # upserted in place, no double rows


async def test_heal_page_lagging_the_run_end_keeps_it_partial_and_backs_off() -> None:
    rig = _Rig()
    rig.fetch.page = [P1, P3, P4]  # REST has not caught up past the run's end
    await _lose(rig.buf, [P3, P4])
    partial = _ranges("partial")
    await rig.settled_tick()
    assert _ranges("partial") == partial + 1
    assert len(rig.buf.closed_ranges(SYM)) == 1  # kept for retry
    await rig.healer.tick()  # inside the 2 s retry backoff: no second page
    assert rig.fetch.calls == 1
    rig.fetch.page = PAGE
    rig.clock.t += 2.0
    await rig.healer.tick()
    assert rig.fetch.calls == 2 and rig.buf.lost_ranges(SYM) == []


async def test_heal_short_read_back_is_read_once_more_then_partial() -> None:
    rig = _Rig()
    await _lose(rig.buf, [P3])
    rig.store.lagging_reads = 1  # WAL lag: the second read sees the rows
    await rig.settled_tick()
    assert rig.store.reads == 2 and rig.sleep.delays == [WAL_LAG_RETRY_S]
    assert rig.buf.lost_ranges(SYM) == []
    await _lose(rig.buf, [P4])
    rig.store.lagging_reads = 2  # stays short
    partial = _ranges("partial")
    rig.clock.t += HEAL_SETTLE_S
    await rig.healer.tick()
    assert _ranges("partial") == partial + 1 and len(rig.buf.closed_ranges(SYM)) == 1


async def test_heal_empty_page_is_partial() -> None:
    rig = _Rig()
    rig.fetch.page = []
    await _lose(rig.buf, [P3])
    partial = _ranges("partial")
    await rig.settled_tick()
    assert _ranges("partial") == partial + 1 and len(rig.buf.closed_ranges(SYM)) == 1


async def test_heal_run_the_page_no_longer_reaches_is_unrecoverable_once_and_kept() -> None:
    rig = _Rig()
    rig.fetch.page = [P4, P5, P6, P7]  # oldest print after the run's start
    await _lose(rig.buf, [P3, P4])
    lost = rig.buf.lost_ranges(SYM)
    unrec = _ranges("unrecoverable")
    with capture_logs() as logs:
        await rig.settled_tick()
    assert _ranges("unrecoverable") == unrec + 1
    assert rig.buf.lost_ranges(SYM) == lost  # never hidden
    assert P4.trade_id in {k[2] for k in rig.store.rows}  # what the page had is re-written
    assert any(e["event"] == "write-behind run unrecoverable" for e in logs)
    rig.clock.t += HEAL_HORIZON_S
    await rig.healer.tick()  # out of the work set: no second fetch, no second count
    assert rig.fetch.calls == 1 and _ranges("unrecoverable") == unrec + 1


async def test_heal_run_past_the_horizon_is_unrecoverable_counted_once() -> None:
    rig = _Rig()
    rig.fetch.fail = RateLimitError("10006")  # governed upstream; here only an error
    await _lose(rig.buf, [P3])
    errors, unrec = _ranges("error"), _ranges("unrecoverable")
    await rig.settled_tick()
    assert _ranges("error") == errors + 1
    rig.clock.t += 0.5  # inside the 1-2 s first backoff: no second page
    await rig.healer.tick()
    assert rig.fetch.calls == 1
    rig.clock.t += HEAL_HORIZON_S
    await rig.healer.tick()
    await rig.healer.tick()
    assert _ranges("unrecoverable") == unrec + 1
    assert rig.fetch.calls == 1 and len(rig.buf.lost_ranges(SYM)) == 1


async def test_heal_write_failure_is_an_error_and_keeps_the_run() -> None:
    rig = _Rig()
    await _lose(rig.buf, [P3])
    rig.store.down = True
    errors = _ranges("error")
    await rig.settled_tick()
    assert _ranges("error") == errors + 1 and len(rig.buf.closed_ranges(SYM)) == 1


async def test_heal_read_back_failure_is_an_error_and_keeps_the_run() -> None:
    rig = _Rig()
    await _lose(rig.buf, [P3])
    rig.store.read_down = True
    errors = _ranges("error")
    await rig.settled_tick()
    assert _ranges("error") == errors + 1 and len(rig.buf.closed_ranges(SYM)) == 1


async def test_heal_clear_racing_an_eviction_keeps_the_grown_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wb_mod, "MAX_LOST_RUNS", 1)  # the next close merges into the run
    rig = _Rig()
    await _lose(rig.buf, [P3])

    async def race() -> None:
        rig.fetch.during.clear()  # once
        await _lose(rig.buf, [P4])  # an eviction lands while the page is in flight

    rig.fetch.during.append(race)
    await rig.healer.tick()
    rig.clock.t += HEAL_SETTLE_S
    await rig.healer.tick()  # heals the snapshot run [P3]; the buffer merged it meanwhile
    grown = [Range(P3.ts_event_us, P4.ts_event_us + 1)]
    assert rig.buf.closed_ranges(SYM) == grown  # not wholly covered: kept whole
    await rig.healer.tick()  # the next pass heals the grown run whole
    assert rig.buf.lost_ranges(SYM) == []


async def test_heal_work_set_is_bounded_per_pass() -> None:
    rig = _Rig(max_work=1)
    await _lose(rig.buf, [P1])
    await _lose(rig.buf, [P3])
    await _lose(rig.buf, [P4])
    await rig.settled_tick()
    assert len(rig.buf.closed_ranges(SYM)) == 2  # one run worked this pass
    await rig.healer.tick()
    await rig.healer.tick()
    assert rig.buf.lost_ranges(SYM) == [] and rig.fetch.calls == 3


async def test_heal_book_run_is_unrecoverable_only_and_stays() -> None:
    buf: WriteBehindBuffer[tuple[str, int]] = WriteBehindBuffer(
        table="orderbook", maxsize=1, dropped=book_writes_dropped_total, key=lambda r: r
    )
    buf.requeue([])
    for ts in (1, 2, 3):
        buf.put((SYM, ts))
    buf.succeeded(await buf.take(1))
    clock = _Clock()
    healer = WriteBehindHealer(buf, table="orderbook", clock=clock)
    unrec = _ranges("unrecoverable", "orderbook")
    await healer.tick()
    clock.t += HEAL_SETTLE_S
    await healer.tick()
    await healer.tick()
    assert _ranges("unrecoverable", "orderbook") == unrec + 1  # once
    assert buf.lost_ranges(SYM) == [Range(1, 3)]  # stays: lost rows are never hidden


async def test_heal_stop_cancels_the_task_cleanly() -> None:
    parked = asyncio.Event()

    async def park(_s: float) -> None:
        parked.set()
        await asyncio.Event().wait()

    healer = WriteBehindHealer(_buf(), table="trades", sleep=park)
    healer.start()
    healer.start()  # a second start while running does nothing
    await parked.wait()
    task = healer._task
    with capture_logs() as logs:
        await healer.stop()
    assert task is not None and task.cancelled()
    assert not any(e["event"] == "write_behind_heal_ended" for e in logs)
    await healer.stop()  # idempotent


async def test_heal_tick_failure_logs_once_per_streak_and_the_loop_goes_on() -> None:
    class Broken:
        @property
        def degraded(self) -> bool:
            raise RuntimeError("boom")

    calls = 0
    done = asyncio.Event()

    async def sleep(_s: float) -> None:
        nonlocal calls
        calls += 1
        if calls > 3:
            done.set()
            await asyncio.Event().wait()

    broken: Any = Broken()  # a buffer whose `degraded` probe raises
    healer = WriteBehindHealer(broken, table="trades", sleep=sleep)
    with capture_logs() as logs:
        healer.start()
        await done.wait()
        await settle()
        await healer.stop()
    assert [e["event"] for e in logs].count("write_behind_heal_tick_failed") == 1


async def test_heal_task_ending_otherwise_is_logged() -> None:
    async def die(_s: float) -> None:
        raise RuntimeError("sleep broke")

    healer = WriteBehindHealer(_buf(), table="trades", sleep=die)
    with capture_logs() as logs:
        healer.start()
        await settle()
    assert any(e["event"] == "write_behind_heal_ended" for e in logs)
    await healer.stop()
