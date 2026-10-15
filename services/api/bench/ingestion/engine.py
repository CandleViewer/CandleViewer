"""Per-symbol ingestion lanes on virtual time (scenarios 1, 2, 3, 5).

Each symbol gets the composition-root shape the architecture mandates (20-architecture
§3.3-3.4): its own bounded inbound frame queue, its own worker task running the *real*
`TradeStream.handle_frame` (parse -> dedupe -> bus publish) and the real `BookState.apply`, and a
NEVER_DROP bus subscriber counting what was actually ingested. Frames are synthetic but shaped
exactly like the recorded public-trade corpus (`fixture_app.CORPUS`, capture 2026-10-05) and run
through the production parser; prices are anchored on the E08-T06 `SyntheticMarket`.

Time is virtual (tick index; no sleeps, C-13.7). A worker processes at most `capacity_factor x`
the steady per-tick frame count, which models a consumer with that much headroom: a burst above it
queues in the exchange-side buffer (the TCP analogue) and must drain afterwards.

Stage latency (§5.1): every frame records receipt -> parsed -> derived -> emitted stamps through
`observability.latency.stage_durations`, i.e. the same arithmetic as `ingest_stage_seconds`.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

import psutil

from bench.ingestion.budgets import Sample
from bench.ingestion_soak import Reservoir, SyntheticMarket
from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy
from candleviewer.exchange.base.trade_print import TradePrint

# nosemgrep: cv-adapter-isolation reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.trades import parse_trade_frame, trade_topic
from candleviewer.ingestion.trade_stream import GapEvent, TradeStream
from candleviewer.observability.latency import StageStamps, stage_durations

#: Corpus envelope epoch (the clean public-trade captures start at ts=1700000000000).
T0_MS = 1_700_000_000_000
#: Modelled cold (Parquet, compressed) bytes per row, E16-K01 note §2 (depth 200).
COLD_BYTES_PER_TRADE = 24
COLD_BYTES_PER_DELTA_LEVEL = 6
SIDES = ("Buy", "Sell")
PHASES = ("steady", "loaded", "after")


def _us_stamp(perf_s: float) -> int:
    """perf_counter seconds -> integer microseconds, fed to `StageStamps` (whose unit is ms) so
    `stage_durations` returns ms at µs resolution instead of rounding sub-ms stages to zero."""
    return int(perf_s * 1_000_000)


class ProcSampler(Protocol):
    def sample(self) -> tuple[int, float]:
        """(rss_bytes, cumulative cpu seconds)."""
        ...


class PsutilProcSampler:
    def __init__(self, pid: int | None = None) -> None:
        self._proc = psutil.Process(pid)

    def sample(self) -> tuple[int, float]:
        t = self._proc.cpu_times()
        return self._proc.memory_info().rss, t.user + t.system


@dataclass(slots=True)
class LaneConfig:
    symbols: tuple[str, ...]
    duration_s: float
    tick_s: float = 0.1
    trades_per_s: int = 50
    prints_per_frame: int = 5
    book_deltas_per_s: int = 10
    capacity_factor: int = 4
    inbound_queue: int = 64
    sample_every_s: float = 5.0
    seed: int = 7
    #: Pace each tick on the wall clock (the 24 h 1x leg); virtual time otherwise.
    realtime: bool = False
    #: Per-symbol rate multiplier windows: (symbol, start_s, end_s, factor).
    loads: tuple[tuple[str, float, float, int], ...] = ()
    #: Self-test hooks: silently drop every Nth frame of a symbol (undetected loss), drop and
    #: *report* it (detected gap), or retain every ingested event (a memory leak).
    drop_every: int = 0
    drop_detected: bool = False
    drop_symbol: str = ""
    leak: bool = False


@dataclass(slots=True)
class LaneResult:
    samples: list[Sample] = field(default_factory=list)
    injected: dict[str, int] = field(default_factory=dict)
    ingested: dict[str, int] = field(default_factory=dict)
    detected_gap: dict[str, int] = field(default_factory=dict)
    lag_ms: dict[str, dict[str, list[float]]] = field(default_factory=dict)  # sym -> phase -> ms
    stage_ms: list[float] = field(default_factory=list)  # receipt -> emitted, per sampled frame
    stage_parts_ms: dict[str, list[float]] = field(default_factory=dict)
    max_backlog: dict[str, int] = field(default_factory=dict)
    backpressure: dict[str, int] = field(default_factory=dict)
    recovery_s: dict[str, float | None] = field(default_factory=dict)
    sampling_cost_ms: float = 0.0
    wall_s: float = 0.0
    retained: int = 0


class _Frame:
    __slots__ = ("deltas", "enq_tick", "enq_wall", "payload", "prints")

    def __init__(self, payload: str, prints: int, deltas: int, enq_tick: int) -> None:
        self.payload, self.prints, self.deltas = payload, prints, deltas
        self.enq_tick, self.enq_wall = enq_tick, 0.0


class Lane:
    """One symbol: exchange-side buffer -> bounded inbound queue -> worker (real TradeStream)."""

    def __init__(self, sym: str, cfg: LaneConfig, market: SyntheticMarket, idx: int) -> None:
        self.sym, self.cfg, self.market = sym, cfg, market
        self.bus = Bus()
        self.now_us = T0_MS * 1000
        self._t_parsed = 0.0
        self.stream = TradeStream(
            bus=self.bus,
            env="demo",
            set_desired=lambda _d: None,
            parse_frame=self._parse,
            topic_for=trade_topic,
            is_listed=lambda s: s == sym,
            touch=lambda _t: None,
            clock=lambda: self.now_us / 1e6,
            now_us=lambda: self.now_us,
        )
        self.stream.acquire("bench", sym)
        self.sub = self.bus.subscribe(
            f"bench-{sym}", f"demo.md.{sym}.trade", QueuePolicy.NEVER_DROP, maxsize=1_000_000
        )
        self.gap_sub = self.bus.subscribe(
            f"bench-gap-{sym}", f"demo.md.{sym}.gap", QueuePolicy.NEVER_DROP
        )
        self.buffer: deque[_Frame] = deque()
        self.inbound: deque[_Frame] = deque()
        self.base_trades = cfg.trades_per_s * cfg.tick_s
        steady_frames = self.base_trades / cfg.prints_per_frame + cfg.book_deltas_per_s * cfg.tick_s
        self.capacity = max(1, round(steady_frames * cfg.capacity_factor))
        self.carry = 0.0
        self.next_id = idx * 10**12
        self.frames_seen = 0
        self.pending_detect = 0
        self.retained: list[object] = []
        self.injected = self.ingested = self.detected = 0
        self.max_backlog = self.backpressure = 0
        self.storage_bytes = 0
        # Bounded reservoirs (E08-T06 `Reservoir`): a 24 h run's bookkeeping must not leak.
        self.lag = {k: Reservoir(seed=cfg.seed + i) for i, k in enumerate(PHASES)}
        self.stage = Reservoir(seed=cfg.seed + 5)
        self.parts = {
            k: Reservoir(seed=cfg.seed + 6 + i) for i, k in enumerate(("parse", "derive"))
        }
        self.recovery_s: float | None = None

    def _parse(self, frame: str) -> list[TradePrint] | None:
        out = parse_trade_frame(frame)
        self._t_parsed = time.perf_counter()
        return out

    def mult(self, t: float) -> int:
        for sym, lo, hi, factor in self.cfg.loads:
            if sym == self.sym and lo <= t < hi:
                return factor
        return 1

    def phase(self, t: float) -> str:
        windows = [(lo, hi) for s, lo, hi, _ in self.cfg.loads]
        if not windows:
            return "steady"
        lo = min(w[0] for w in windows)
        hi = max(w[1] for w in windows)
        return "steady" if t < lo else "loaded" if t < hi else "after"

    def _trade_frame(self, n: int, ts_ms: int) -> str:
        data = []
        for _ in range(n):
            self.next_id += 1
            side = SIDES[self.next_id % 2]
            px = self.market.books[self.sym].snapshot()[0][0].price
            data.append(
                {
                    "T": ts_ms - 5,
                    "s": self.sym,
                    "S": side,
                    "v": "0.001",
                    "p": str(px),
                    "L": "PlusTick",
                    "i": f"b{self.next_id:015d}",
                    "BT": False,
                }
            )
        return json.dumps(
            {"topic": trade_topic(self.sym), "type": "snapshot", "ts": ts_ms, "data": data}
        )

    def feed(self, tick: int) -> None:
        t = tick * self.cfg.tick_s
        mult = self.mult(t)
        ts_ms = T0_MS + int(t * 1000)
        self.carry += self.base_trades * mult
        n = int(self.carry)
        self.carry -= n
        while n > 0:
            k = min(n, self.cfg.prints_per_frame)
            n -= k
            self.injected += k
            self.buffer.append(_Frame(self._trade_frame(k, ts_ms), k, 0, tick))
        for _ in range(max(1, round(self.cfg.book_deltas_per_s * self.cfg.tick_s * mult))):
            self.buffer.append(_Frame("", 0, 2, tick))

    def _drop(self, fr: _Frame) -> bool:
        cfg = self.cfg
        if not cfg.drop_every or fr.prints == 0 or self.sym != (cfg.drop_symbol or self.sym):
            return False
        self.frames_seen += 1
        if self.frames_seen % cfg.drop_every:
            return False
        if cfg.drop_detected:
            self.pending_detect += fr.prints
            self.stream.mark_gap("rejected_frame", self.sym)
        return True

    async def work(self, tick: int, record_stages: bool) -> None:
        """Admit buffered frames into the bounded inbound queue, then process up to `capacity`."""
        while self.buffer and len(self.inbound) < self.cfg.inbound_queue:
            fr = self.buffer.popleft()
            fr.enq_wall = time.perf_counter()
            self.inbound.append(fr)
        if self.buffer:
            self.backpressure += 1  # inbound queue full: the exchange-side buffer holds the rest
        t = tick * self.cfg.tick_s
        phase = self.phase(t)
        for _ in range(min(self.capacity, len(self.inbound))):
            fr = self.inbound.popleft()
            self.now_us = (T0_MS + int(t * 1000)) * 1000
            t_recv = time.perf_counter()
            if fr.deltas:
                bids, asks = self.market.delta(self.sym)
                self.market.books[self.sym].apply(bids, asks)
                self.storage_bytes += COLD_BYTES_PER_DELTA_LEVEL * fr.deltas
                t_parsed = t_derived = time.perf_counter()
            else:
                if self._drop(fr):
                    continue
                await self.stream.handle_frame(fr.payload)
                t_parsed, t_derived = self._t_parsed, time.perf_counter()
                self.storage_bytes += COLD_BYTES_PER_TRADE * fr.prints
            t_emit = time.perf_counter()
            # Virtual queueing delay (ticks waited) + real processing time.
            queued_ms = (tick - fr.enq_tick) * self.cfg.tick_s * 1000
            self.lag[phase].add(queued_ms + (t_emit - t_recv) * 1000)
            if record_stages and fr.prints:
                r, p_, d, e = (_us_stamp(x) for x in (t_recv, t_parsed, t_derived, t_emit))
                parts = stage_durations(StageStamps(r, r, p_, d, e), 0)
                parse, derive = parts["parse"] or 0.0, parts["derive"] or 0.0
                self.parts["parse"].add(parse)
                self.parts["derive"].add(derive)
                self.stage.add(parse + derive + (parts["fanout"] or 0.0))
        self._drain_bus()
        backlog = len(self.buffer) + len(self.inbound)
        self.max_backlog = max(self.max_backlog, backlog)
        if phase == "after" and self.recovery_s is None and backlog == 0:
            end = max((hi for s, _lo, hi, _f in self.cfg.loads if s == self.sym), default=t)
            self.recovery_s = max(0.0, t - end)

    def _drain_bus(self) -> None:
        while self.sub.qsize():
            ev = self.sub.get_nowait()
            self.ingested += 1
            if self.cfg.leak:
                self.retained.append(ev)
        while self.gap_sub.qsize():
            if isinstance(self.gap_sub.get_nowait(), GapEvent):
                self.detected += self.pending_detect
                self.pending_detect = 0

    async def settle(self) -> None:
        """End of feed. A gap opened by the very last frame is closed the way production closes
        it — by the next live frame — so one trailing frame is injected (and counted)."""
        if self.pending_detect:
            self.injected += 1
            await self.stream.handle_frame(self._trade_frame(1, T0_MS + 10**9))
        await self.stream.wait_backfills()
        self._drain_bus()

    def backlog(self) -> int:
        return len(self.buffer) + len(self.inbound)


async def run_lanes(
    cfg: LaneConfig,
    sampler: ProcSampler,
    *,
    record_stages: bool = False,
    drain_ticks: int = 0,
    bind: Callable[[list[Lane]], None] | None = None,
) -> LaneResult:
    """Drive every lane tick by tick (virtual time). One task per symbol per tick (gathered),
    so a lane's work never runs inside another's; the clock only advances when all are done."""
    market = SyntheticMarket(cfg.symbols, cfg.seed)
    lanes = [Lane(s, cfg, market, i) for i, s in enumerate(cfg.symbols)]
    if bind is not None:
        bind(lanes)  # self-tests observe lane state (e.g. retained events) from the sampler
    n_ticks = int(cfg.duration_s / cfg.tick_s)
    every = max(1, int(cfg.sample_every_s / cfg.tick_s))
    res = LaneResult()
    sample_cost: list[float] = []
    wall0 = time.perf_counter()
    rss0, cpu0 = sampler.sample()
    res.samples.append(Sample(0.0, rss0, 0.0, 0.0, 0, 0))
    lag_window: deque[float] = deque(maxlen=64)
    for tick in range(n_ticks + drain_ticks):
        feeding = tick < n_ticks
        if feeding:
            for lane in lanes:
                lane.feed(tick)
        t_tick = time.perf_counter()
        await asyncio.gather(*(lane.work(tick, record_stages) for lane in lanes))
        spent = time.perf_counter() - t_tick
        lag_window.append(spent * 1000)
        if cfg.realtime and feeding:
            await asyncio.sleep(max(0.0, cfg.tick_s - spent))
        if not feeding and all(lane.backlog() == 0 for lane in lanes):
            break
        if feeding and (tick + 1) % every == 0:
            t_s0 = time.perf_counter()
            rss, cpu = sampler.sample()
            res.samples.append(
                Sample(
                    (tick + 1) * cfg.tick_s,
                    rss,
                    cpu - cpu0,
                    max(lag_window, default=0.0),
                    sum(lane.backlog() for lane in lanes),
                    sum(lane.storage_bytes for lane in lanes),
                )
            )
            sample_cost.append((time.perf_counter() - t_s0) * 1000)
    for lane in lanes:
        await lane.settle()
        res.injected[lane.sym] = lane.injected
        res.ingested[lane.sym] = lane.ingested
        res.detected_gap[lane.sym] = lane.detected
        res.lag_ms[lane.sym] = {k: list(v.values) for k, v in lane.lag.items()}
        res.max_backlog[lane.sym] = lane.max_backlog
        res.backpressure[lane.sym] = lane.backpressure
        res.recovery_s[lane.sym] = lane.recovery_s
        res.stage_ms.extend(lane.stage.values)
        for k, v in lane.parts.items():
            res.stage_parts_ms.setdefault(k, []).extend(v.values)
        res.retained += len(lane.retained)
    res.sampling_cost_ms = sum(sample_cost) / len(sample_cost) if sample_cost else 0.0
    res.wall_s = time.perf_counter() - wall0
    return res


class ScriptedSampler:
    """Deterministic sampler for tests: RSS = base + slope * n (+ retained * bytes_per_event)."""

    def __init__(
        self,
        base: int = 120 * 2**20,
        slope: int = 0,
        cpu_per_sample: float = 0.01,
        retained: Callable[[], int] | None = None,
        bytes_per_event: int = 0,
    ) -> None:
        self.n, self.base, self.slope, self.cpu = 0, base, slope, cpu_per_sample
        self._retained, self._bpe = retained, bytes_per_event

    def sample(self) -> tuple[int, float]:
        extra = self._retained() * self._bpe if self._retained else 0
        out = (self.base + self.n * self.slope + extra, self.n * self.cpu)
        self.n += 1
        return out


def symbols_for(n: int, preferred: Sequence[str]) -> tuple[str, ...]:
    """First `n` of `preferred`, padded with deterministic synthetic tickers."""
    out = list(preferred[:n])
    i = 0
    while len(out) < n:
        out.append(f"SYN{i:02d}USDT")
        i += 1
    return tuple(out)
