"""D2-G3 (#2787, decision D-G2 of #399): the bars series store's first reads on a REAL QuestDB.

Runs in CI's `integration` job, and in the py job's db-chaos lane under `--cov` (where
tracing slows it); `D2G3_MACHINE` names the host in the output line. SYNTHETIC bars
(pure functions of a fixed seed, no exchange data) go in through the production row path (`bar_row`
into `QuestDbRowSink`, as `app._build_bars_sink` builds it): 16 series of 1 m time bars, and 8
`range` series at the smallest param with `D2G3_DENSE_ROWS` rows together (default 250 000, a knob
for local dense runs) in the 31 d window; a `range` first read starts at its 1 000th-newest `ts`
(D2-M2). The objects are built as `app.py` builds them: one `LazyPgWire` shared by a `BarReader`,
`SeriesStore(reader.read_tail)` and the `/market/bars` router; a second `LazyPgWire`, with its own
`BarReader` and router, is option A's separation. A 5 ms ticker samples the loop: its worst
lateness is `lag_ms` (C-2.17 allows 50 ms), the longest callback `step_ms`, the longest collection
`gc_ms`; `gc_full` counts generation-2 collections (a full one, `collect_ms`, runs before each
pass, outside it); `hold_ms` is each first read's hold of the shared connection. Three repeats:

- m1: one `range` first read alone, through the store's 2 s timeout.
- m2: the 16 time series' first reads started together (`single_*`: one alone); `m2_8`: eight.
- m3, `m3_8`: m2 and m2_8 with two `/market/bars` reads right behind the first reads, one on the
  shared connection (`rest_shared_*`), one on the second (`rest_own_*`).
- m5: the 8 `range` series' first reads started together, with the same two REST reads.
- m4: the synchronous `BarsSnapshotSource.build` of a 1 000-bar `range` series, per 1 000 bars.

One JSON line, `D2G3_FIRST_READS=`. Assertions are correctness only (row counts; every read that
is served returns the seeded bars), never a measured time; only fixed deadlines (among them the
readiness waits, 120 s and 180 s, the 5 s connect timeout and the 10 s query timeout) can fail it,
on a very slow runner.
"""

from __future__ import annotations

import asyncio
import contextlib
import gc
import json
import os
import statistics
import time
from collections import defaultdict
from collections.abc import AsyncIterator, Callable, Iterable, Iterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

import asyncpg
import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from prometheus_client import REGISTRY

from candleviewer.api.market import MarketDataPrincipal
from candleviewer.api.market_bars import make_market_bars_router
from candleviewer.api.market_response import iso_us
from candleviewer.bars.limits import DEFAULT_LIMIT, MAX_TAIL, RANGE_TICKS_RANGE
from candleviewer.bars.models import Bar, BarSpec
from candleviewer.bars.reader import BarReader, tail_window_us
from candleviewer.bars.rows import bar_row
from candleviewer.bars.series_store import Hold, SeriesStore
from candleviewer.storage.questdb.runner import run_migrations
from candleviewer.storage.questdb.wiring import LazyPgWire, QuestDbRowSink
from candleviewer.ws.bars_source import BarsSnapshotSource
from candleviewer.ws.permissions import Subscription
from candleviewer.ws.topics import effective_options, parse_topic
from tests.integration.storage.test_questdb_hot_tier import (
    _PGWIRE_PASSWORD,
    _PGWIRE_USER,
    DDL_DIR,
    _AsyncpgExecutor,
    _connect,
    wait_for_row_count,
)

pytestmark = pytest.mark.integration

#: The image `infra/compose/docker-compose.yml` pins, by digest.
QDB_IMAGE = (
    "questdb/questdb:8.1.1@sha256:82ef61a3919f4014e2aae1216f2803288b176a54c197d0933863bdc8c04a2e03"
)
NOW_US = 1_700_000_000_000_000  # the reader's clock: every series ends here, each window is fixed
MINUTE_US, DAY_US, GEN, CHUNK, REPEATS = 60_000_000, 86_400_000_000, 7, 5_000, 3
TIME_SPEC = BarSpec(kind="time", interval_ms=60_000)
DENSE_SPEC = BarSpec(kind="range", range_ticks=RANGE_TICKS_RANGE[0])  # the smallest param
SYMS = [f"D2G3{n:02d}USDT" for n in range(16)]
RANGES = [f"D2G3R{n}USDT" for n in range(8)]
#: Bars of a 1 m series: the whole first-read window (`tail_window_us`); `MAX_TAIL` are read.
TIME_ROWS = tail_window_us(TIME_SPEC, MAX_TAIL) // MINUTE_US - 1
DENSE_ROWS = int(os.environ.get("D2G3_DENSE_ROWS") or 250_000)  # the 8 `range` series' rows
RANGE_ROWS = max(MAX_TAIL, DENSE_ROWS // len(RANGES))
#: symbol -> (spec, bars, bar width in µs); each series ends at `NOW_US` (a `range` one spans 29 d).
SEEDS = {
    **{s: (TIME_SPEC, TIME_ROWS, MINUTE_US) for s in SYMS},
    **{s: (DENSE_SPEC, RANGE_ROWS, 29 * DAY_US // RANGE_ROWS) for s in RANGES},
}
#: The `/market/bars` page of the first time series: its oldest `DEFAULT_LIMIT` bars (one page).
REST: dict[str, str | int] = {
    "symbol": SYMS[0], "bar_type": "time", "param": "1", "limit": DEFAULT_LIMIT,
    "from": iso_us(NOW_US - TIME_ROWS * MINUTE_US).replace("+00:00", "Z"),
    "to": iso_us(NOW_US).replace("+00:00", "Z"),
}  # fmt: skip
SOLO = {"single_ms": "max_ms", "single_cpu_ms": "cpu_ms", "single_step_ms": "step_ms",
        "single_hold_ms": "hold_max_ms"}  # fmt: skip
Rep = dict[str, float | list[float]]  # one pass's numbers; a list holds one value per first read


class _Steps:
    """The longest loop callback since `ms` was last reset, in ms (timed by `steps`)."""

    ms = 0.0


@pytest.fixture
def steps(monkeypatch: pytest.MonkeyPatch) -> _Steps:
    """Time every loop callback: a lateness is many short callbacks queued or one long block."""
    run, out = asyncio.events.Handle._run, _Steps()

    def timed(handle: asyncio.Handle) -> None:
        t = time.perf_counter()
        run(handle)
        out.ms = max(out.ms, (time.perf_counter() - t) * 1e3)

    monkeypatch.setattr(asyncio.events.Handle, "_run", timed)
    return out


@pytest_asyncio.fixture
async def questdb() -> AsyncIterator[tuple[str, int, int]]:
    from testcontainers.core.container import DockerContainer

    with DockerContainer(QDB_IMAGE).with_exposed_ports(8812, 9009) as c:
        host, pg = c.get_container_host_ip(), int(c.get_exposed_port(8812))
        ilp = int(c.get_exposed_port(9009))
        for _ in range(60):
            try:
                await (await _connect(host, pg)).close()
                break
            except (OSError, asyncpg.PostgresError):
                await asyncio.sleep(1.0)
        yield host, pg, ilp


def _at(us: int) -> Callable[[], int]:
    return lambda: us  # a clock stopped at `us`


def _bar(symbol: str, i: int) -> Bar:
    """Bar `i` of `symbol`'s series: a pure function of its arguments, so what is seeded and what
    a read must return agree. Prices are whole cents, so every double round-trips as written."""
    spec, n, width = SEEDS[symbol]
    t = NOW_US - (n - i) * width
    px = Decimal(10_000 + (i * 7_919 + sum(map(ord, symbol)) * 104_729) % 977) / 100
    return Bar.model_construct(
        spec_hash=spec.spec_hash, symbol=symbol, index=i, open_time=t, close_time=t + width - 1,
        open=px, high=px + 1, low=px - 1, close=px + Decimal("0.5"), volume=Decimal(4),
        buy_volume=Decimal("2.5"), sell_volume=Decimal("1.5"), delta=Decimal(1),
        min_delta=Decimal(0), max_delta=Decimal(1), trade_count=4, turnover=4 * px, vwap=px,
        closed=True, partial=False, gap_before=False,
    )  # fmt: skip


def _keys(bars: Iterable[Bar]) -> list[tuple[int, int, Decimal]]:
    return [(b.index, b.open_time, b.close) for b in bars]


def _want(symbol: str) -> list[tuple[int, int, Decimal]]:
    """What a first read of `symbol` returns: its newest `MAX_TAIL` bars, oldest first."""
    n = SEEDS[symbol][1]
    return _keys(_bar(symbol, i) for i in range(n - MAX_TAIL, n))


def _chunks(symbols: list[str]) -> Iterator[list[dict[str, object]]]:
    """A table's rows in time order, about `CHUNK` at a time (never all held at once)."""
    spec, n, _ = SEEDS[symbols[0]]
    step = max(1, CHUNK // len(symbols))
    for lo in range(0, n, step):
        rows = range(lo, min(n, lo + step))
        yield [bar_row(_bar(s, i), spec, generation=GEN) for i in rows for s in symbols]


def _sink(host: str, pg: int, ilp: int) -> QuestDbRowSink:
    """`app._build_bars_sink`'s object: its `pgwire` is the one connection the app shares."""
    return QuestDbRowSink(f"{host}:{ilp}", f"{host}:{pg}", _PGWIRE_USER, _PGWIRE_PASSWORD)


async def _seed(host: str, pg: int, ilp: int) -> None:
    sink = _sink(host, pg, ilp)
    try:
        for table, symbols in (("bars_time", SYMS), ("bars_range", RANGES)):
            for rows in _chunks(symbols):
                await sink.write_rows(table, rows, "ts")
    finally:
        await sink.stop()  # drains the ILP buffer


async def _applied(conn: asyncpg.Connection, table: str, rows: int) -> None:
    """`rows` rows applied, a quiet WAL (no new transaction for 3 s, within 120 s: a reused
    container may still commit re-sent rows), then the rows with `writerTxn == sequencerTxn`."""
    await wait_for_row_count(conn, table, rows, timeout_s=180)
    txn, quiet, deadline = None, 0, time.monotonic() + 120
    while quiet < 6:
        if time.monotonic() > deadline:
            pytest.fail(f"{table}: its WAL never stayed quiet for 3 s within 120 s")
        now = await conn.fetchval("SELECT sequencerTxn FROM wal_tables() WHERE name = $1", table)
        txn, quiet = now, (quiet + 1 if now == txn else 0)
        await asyncio.sleep(0.5)
    await wait_for_row_count(conn, table, rows, timeout_s=180)


async def _no_rebuild(symbol: str, spec_hash: str, from_us: int, to_us: int) -> None:
    """`app._no_rebuild_executor`: stale-build rebuilds have no executor yet."""


async def _started(symbol: str) -> int:
    """`app.recording_started_at_us`'s place (it reads the market-data store, not this
    connection): a fixed time, awaited as `get_bars` awaits it, with no round trip."""
    return NOW_US - 30 * DAY_US


class _Resolver:
    def resolve(self, request: Request) -> MarketDataPrincipal:
        return MarketDataPrincipal("bench", frozenset({"marketdata:read"}))


def _client(reader: BarReader) -> httpx.AsyncClient:
    """`/market/bars` over `reader`, in process, through `make_market_bars_router`."""
    app = FastAPI()
    app.include_router(
        make_market_bars_router(
            lambda: reader, recording_started_at_us=_started, principal_resolver=_Resolver(),
            symbol_listed=lambda _s: True, now_us=_at(NOW_US),
        )
    )  # fmt: skip
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bench")


class _Lap:
    """`with`: the block's wall time (`ms`)."""

    ms = 0.0

    def __enter__(self) -> _Lap:
        self._t = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> None:
        self.ms = (time.perf_counter() - self._t) * 1e3


class _TimedLock(asyncio.Lock):
    """The shared `LazyPgWire`'s lock, timed: how long each task held the connection (`held`,
    ms). The same lock otherwise; the bench installs it, as `LazyPgWire` takes no lock."""

    def __init__(self) -> None:
        super().__init__()
        self.held: defaultdict[object, float] = defaultdict(float)

    async def acquire(self) -> Literal[True]:
        await super().acquire()
        self._at = (asyncio.current_task(), time.perf_counter())
        return True

    def release(self) -> None:
        task, t = self._at
        self.held[task] += (time.perf_counter() - t) * 1e3
        super().release()


class _Stalls:
    """`async with`: the longest the loop was unavailable meanwhile (`ms`, the worst lateness of a
    5 ms ticker), the longest single callback it ran (`step_ms`, from `steps`), the longest
    collection (`gc_ms`) and how many generation-2 collections ran (`gc_full`)."""

    ms = step_ms = gc_ms = 0.0
    gc_full = 0

    def __init__(self, steps: _Steps) -> None:
        self._steps = steps

    def _gc(self, phase: str, info: dict[str, int]) -> None:
        if phase == "start":
            self._gc_t = time.perf_counter()
            return
        self.gc_ms = max(self.gc_ms, (time.perf_counter() - self._gc_t) * 1e3)
        self.gc_full += info["generation"] == 2

    async def _tick(self) -> None:
        loop = asyncio.get_running_loop()
        last = loop.time()
        while True:
            await asyncio.sleep(0.005)
            now = loop.time()
            self.ms, last = max(self.ms, (now - last - 0.005) * 1e3), now

    async def __aenter__(self) -> _Stalls:
        gc.callbacks.append(self._gc)
        self._ticker = asyncio.create_task(self._tick())
        await asyncio.sleep(0)  # the ticker takes its first sample before the work starts
        self._steps.ms = 0.0  # in a new callback: the one before it ended at the `await`
        return self

    async def __aexit__(self, *exc: object) -> None:
        await asyncio.sleep(0.02)  # one more sample, for a stall that ended with the block
        self.step_ms = self._steps.ms
        gc.callbacks.remove(self._gc)
        self._ticker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._ticker


@dataclass
class _Rig:
    """A pass's objects: the store's reader on the shared connection and its timed lock, the
    `/market/bars` clients over it and over the second connection (in that order), the timer."""

    reader: BarReader
    lock: _TimedLock
    rest: tuple[httpx.AsyncClient, httpx.AsyncClient]
    steps: _Steps


def _timeouts() -> float:
    labels = {"reason": "timeout"}
    return float(REGISTRY.get_sample_value("bars_series_hydrate_failed_total", labels) or 0)


async def _pass(rig: _Rig, syms: list[str], *, rest: bool = False) -> Rep:
    """First reads of `syms` through a fresh `SeriesStore`, all started together; `rest`: then a
    `/market/bars` read on each connection, issued right behind them."""
    store, failed = SeriesStore(rig.reader.read_tail), _timeouts()
    holds: list[Hold] = []

    async def first(sym: str) -> tuple[float, float]:
        with _Lap() as lap:
            holds.append(await store.ensure(sym, SEEDS[sym][0]))
        return lap.ms, rig.lock.held.pop(asyncio.current_task(), 0.0)

    async def served(client: httpx.AsyncClient) -> tuple[httpx.Response, float]:
        with _Lap() as lap:
            resp = await client.get("/market/bars", params=REST)
        return resp, lap.ms

    async def run() -> tuple[list[tuple[float, float]], list[tuple[httpx.Response, float]]]:
        reads = [asyncio.ensure_future(first(s)) for s in syms]
        queued = [asyncio.ensure_future(served(c)) for c in rig.rest] if rest else []
        return list(await asyncio.gather(*reads)), list(await asyncio.gather(*queued))

    with _Lap() as collect:  # a full collection first: each pass starts on a collected heap
        gc.collect()
    async with _Stalls(rig.steps) as stalls:
        cpu = time.thread_time()
        with _Lap() as total:
            reads, rests = await run()
        cpu = (time.thread_time() - cpu) * 1e3  # the loop thread's CPU over `total_ms`
    live, kept = 0, []
    for s in syms:
        spec = SEEDS[s][0]
        latest = store.latest(s, spec.spec_hash, MAX_TAIL)
        assert latest is not None
        kept.append(len(latest.closed))
        if store.hydrated(s, spec.spec_hash):
            assert _keys(latest.closed) == _want(s)  # what the store serves is the seeded tail
        else:
            live += 1  # a failed or timed-out read leaves the series live-only, and empty here
            assert not latest.closed
    for hold in holds:
        hold.release()
    lat, held = [r[0] for r in reads], [r[1] for r in reads]
    out: Rep = {
        "total_ms": total.ms, "p50_ms": statistics.median(lat), "max_ms": max(lat),
        "hold_p50_ms": statistics.median(held), "hold_max_ms": max(held), "lag_ms": stalls.ms,
        "step_ms": stalls.step_ms, "gc_ms": stalls.gc_ms, "gc_full": stalls.gc_full,
        "collect_ms": collect.ms, "cpu_ms": cpu, "timeouts": _timeouts() - failed,
        "live_only": live, "rows_min": min(kept), "read_ms": lat, "hold_ms": held,
    }  # fmt: skip
    for name, (resp, ms) in zip(("shared", "own"), rests, strict=False):
        if resp.status_code == 200:  # served: the page is the seeded series' oldest bars
            assert [b["index"] for b in resp.json()["bars"]] == list(range(DEFAULT_LIMIT))
        out |= {f"rest_{name}_ms": ms, f"rest_{name}_status": resp.status_code}
    return out


def _build_ms(source: BarsSnapshotSource) -> Rep:
    """`build` of a `range` series' `MAX_TAIL` bars with `include_delta`, ms per 1 000 bars."""
    out: Rep = {}
    for encoding in ("binary", "structured"):
        topic = parse_topic(f"bars.{RANGES[0]}.range.{RANGE_TICKS_RANGE[0]}")
        opts = {"history": MAX_TAIL, "include_delta": True, "encoding": encoding}
        sub = Subscription("s_01", topic, opts, effective_options(topic, opts))
        t = time.perf_counter()
        body = source.build(sub)
        out[f"{encoding}_ms_per_1000"] = (time.perf_counter() - t) * 1e3 * 1_000 / MAX_TAIL
        assert body is not None
    return out


def _med(repeats: list[Rep]) -> dict[str, object]:
    """Each repeat, rounded, and the median of each number over the repeats."""

    def rnd(v: float | list[float]) -> float | list[float]:
        return [round(x, 1) for x in v] if isinstance(v, list) else round(v, 1)

    nums = [{k: v for k, v in r.items() if not isinstance(v, list)} for r in repeats]
    med = {k: round(statistics.median(n[k] for n in nums), 1) for k in nums[0]}
    return {"repeats": [{k: rnd(v) for k, v in r.items()} for r in repeats], "median": med}


@pytest.mark.asyncio
async def test_d2_g3_first_reads_on_a_seeded_questdb(
    questdb: tuple[str, int, int], steps: _Steps
) -> None:
    host, pg, ilp = questdb
    conn = await _connect(host, pg)
    sink = _sink(host, pg, ilp)  # a second one, never written to: its connection is the reads'
    own = LazyPgWire(host, pg, _PGWIRE_USER, _PGWIRE_PASSWORD)  # option A: a second connection
    lock = _TimedLock()
    sink.pgwire._lock = lock  # the bench's instrument on the shared connection
    try:
        await run_migrations(_AsyncpgExecutor(conn), DDL_DIR)
        await _seed(host, pg, ilp)
        await _applied(conn, "bars_time", len(SYMS) * TIME_ROWS)
        await _applied(conn, "bars_range", len(RANGES) * RANGE_ROWS)
        reader = BarReader(sink.pgwire, _no_rebuild, now_us=_at(NOW_US))
        for wire in (sink.pgwire, own):  # both open before the passes, as the writer's probe does
            await wire.fetch("SELECT 1")
        m: defaultdict[str, list[Rep]] = defaultdict(list)
        apart = BarReader(own, _no_rebuild, now_us=_at(NOW_US))
        async with _client(reader) as shared, _client(apart) as alone:
            rig = _Rig(reader, lock, (shared, alone), steps)
            for _ in range(REPEATS):
                m["m1"].append(await _pass(rig, RANGES[:1]))
                solo = await _pass(rig, SYMS[:1])
                one = {k: solo[v] for k, v in SOLO.items()}  # one of the 16, alone
                m["m2"].append({**one, **await _pass(rig, SYMS)})
                m["m2_8"].append(await _pass(rig, SYMS[:8]))
                m["m3"].append(await _pass(rig, SYMS, rest=True))
                m["m3_8"].append(await _pass(rig, SYMS[:8], rest=True))
                m["m5"].append(await _pass(rig, RANGES, rest=True))
        store = SeriesStore(reader.read_tail, timeout_s=60)  # m4's input, whatever the speed
        await store.ensure(RANGES[0], DENSE_SPEC)
        assert store.hydrated(RANGES[0], DENSE_SPEC.spec_hash)
        source = BarsSnapshotSource(store, lambda _s: (2, 3))
        m["m4"] = [_build_ms(source) for _ in range(REPEATS)]
        for sym, (spec, _n, _w) in SEEDS.items():  # control: `read_tail` with no store
            tail = await reader.read_tail(sym, spec, MAX_TAIL)
            assert (tail.dropped, tail.skipped) == (0, 0)
            assert _keys(b for _g, b in tail.bars) == _want(sym)
        rows = dict(D2G3_DENSE_ROWS=DENSE_ROWS, range_series=len(RANGES), time_series=len(SYMS),
                    range_rows_each=RANGE_ROWS, time_rows_each=TIME_ROWS)  # fmt: skip
        out = {
            "machine": os.environ.get("D2G3_MACHINE") or ("CI" if os.environ.get("CI") else "?"),
            "questdb": QDB_IMAGE,
            "rows": rows,
            "gc_objects": len(gc.get_objects()),  # what a full collection walks, to size `gc_ms`
            **{k: _med(v) for k, v in m.items()},
        }
        print("D2G3_FIRST_READS=" + json.dumps(out))
    finally:
        await own.close()
        await sink.stop()
        await conn.close()
