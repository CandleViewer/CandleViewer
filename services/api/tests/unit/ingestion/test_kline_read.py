"""E12-S05 read path: cache-first, cold-tier read-through, non-blocking backfill, `meta.sources`
/ `meta.recording_started_at`, and cross-check discrepancy logging. Fakes only, no network."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

import pytest
import structlog

from candleviewer.exchange.base.models import KlineEvent
from candleviewer.ingestion.kline_backfill import KlineBackfillService
from candleviewer.ingestion.kline_coverage import Range
from candleviewer.ingestion.kline_crosscheck import cross_check
from candleviewer.ingestion.kline_read import KlineReadService
from candleviewer.ingestion.metrics import kline_crosscheck_divergence_total

SYM, IV = "BTCUSDT", "5"
W = 300_000_000


@dataclass
class _Row:
    ts_us: int
    source: str = "tape"
    confirmed: bool = True
    open: str = "100"
    high: str = "101"
    low: str = "99"
    close: str = "100"
    volume: str = "1"
    turnover: str = "100"


@dataclass
class _Hot:
    rows: dict[int, _Row] = field(default_factory=dict)
    reads: int = 0

    async def read_klines(
        self, sym: str, interval: str, rng: Range, tier: str = "auto", limit: int | None = None
    ) -> Sequence[_Row]:
        self.reads += 1
        out = [r for t, r in sorted(self.rows.items()) if rng.start_us <= t < rng.end_us]
        return out if limit is None else out[-limit:]

    async def write_klines(self, rows: Sequence[object]) -> None:
        for row in rows:
            assert isinstance(row, dict)
            self.rows[int(row["ts_us"])] = _Row(int(row["ts_us"]), source=str(row["source"]))


def _k(start: int) -> KlineEvent:
    return KlineEvent.model_validate(
        dict(event_id="00000000-0000-7000-8000-000000000001", ts_event=start, ts_ingest=start,
             source="backfill", symbol=SYM, interval=IV, start=start, end=start + W - 1,
             open="100", high="101", low="99", close="100", volume="1", turnover="100",
             confirmed=True)
    )  # fmt: skip


class _Port:
    def __init__(self, n: int) -> None:
        self.bars = [_k(i * W) for i in range(n)]
        self.calls = 0
        self.release = asyncio.Event()
        self.release.set()

    async def __call__(
        self, symbol: str, interval: str, start: int, end: int, limit: int = 1000
    ) -> Sequence[KlineEvent]:
        self.calls += 1
        await self.release.wait()
        return [b for b in self.bars if start <= b.start <= end][-limit:]


class _RaisingPort:
    """A5: an adapter that fails the test on ANY call — proves a cache hit never fetches."""

    async def __call__(self, *a: object, **kw: object) -> Sequence[KlineEvent]:
        raise AssertionError("cache hit must not call the exchange")


async def _started_at_zero(symbol: str) -> int | None:
    return 0


def _svc(
    hot: _Hot, port: _Port | _RaisingPort, **kw: object
) -> tuple[KlineReadService, KlineBackfillService]:
    bf = KlineBackfillService(fetch_klines=port, cache=hot)
    return KlineReadService(hot, backfill=bf, **kw), bf  # type: ignore[arg-type]  # **kw: object passthrough


async def test_cache_hit_served_locally_without_exchange_call() -> None:
    hot = _Hot({i * W: _Row(i * W) for i in range(10)})
    svc, _ = _svc(hot, _RaisingPort(), recording_started_at_us=_started_at_zero)
    read = await svc.read(SYM, IV, Range(0, 10 * W))
    assert not read.backfilling and read.holes == []
    assert len(read.rows) == 10 and read.sources == ["questdb"]
    assert read.recording_started_at_us == 0


async def test_tail_only_fetch_and_first_page_served_while_backfill_continues() -> None:
    hot = _Hot({i * W: _Row(i * W) for i in range(5)})
    port = _Port(8)
    port.release.clear()
    svc, bf = _svc(hot, port)
    read = await svc.read(SYM, IV, Range(0, 8 * W))
    # Interactive now: stored bars returned, tail backfill running in the background.
    assert len(read.rows) == 5 and read.backfilling
    assert read.holes == [Range(5 * W, 8 * W)]
    assert read.sources == ["questdb"]  # A4: a job alone is not an exchange-sourced row
    port.release.set()
    task = bf._jobs[(SYM, IV)]
    result = await task
    assert [e.start for e in result.fetched] == [5 * W, 6 * W, 7 * W]
    again = await svc.read(SYM, IV, Range(0, 8 * W))
    assert len(again.rows) == 8 and port.calls == 1 and not again.backfilling
    assert "exchange_rest" in again.sources  # rest-sourced rows are now in the window


async def test_cold_tier_read_through_for_window_older_than_hot_retention() -> None:
    hot = _Hot({i * W: _Row(i * W) for i in range(5, 10)})
    cold_calls: list[Range] = []

    async def cold(sym: str, interval: str, rng: Range) -> Sequence[_Row]:
        cold_calls.append(rng)
        return [_Row(i * W, source="parquet") for i in range(5) if rng.start_us <= i * W]

    svc, _ = _svc(hot, _Port(10), cold=cold, hot_boundary_us=lambda: 5 * W)
    read = await svc.read(SYM, IV, Range(0, 10 * W))
    assert cold_calls == [Range(0, 5 * W)]
    assert [r.ts_us for r in read.rows] == [i * W for i in range(10)]
    assert read.sources == ["parquet", "questdb"]


async def test_window_entirely_cold_never_backfills() -> None:
    async def cold(sym: str, interval: str, rng: Range) -> Sequence[_Row]:
        return []

    port = _Port(5)
    svc, _ = _svc(_Hot(), port, cold=cold, hot_boundary_us=lambda: 100 * W)
    read = await svc.read(SYM, IV, Range(0, 5 * W))
    assert read.rows == [] and read.sources == [] and port.calls == 0


async def test_backfill_window_is_bounded_and_month_interval_never_backfills() -> None:
    port = _Port(0)
    svc, bf = _svc(_Hot(), port, max_backfill_bars=10)
    read = await svc.read(SYM, IV, Range(0, 1_000 * W))
    assert read.holes == [Range(990 * W, 1_000 * W)]
    await bf._jobs[(SYM, IV)]
    month = await svc.read(SYM, "M", Range(0, 1_000 * W))
    assert month.holes == [] and not month.backfilling


async def test_window_read_before_its_bars_exist_is_fetched_once_they_do() -> None:
    """#3808 (E08-Q06 F3, #283): an empty venue page for a window past the venue's newest bar is
    not coverage, so the window stays a hole and its bars are fetched once they exist (it used
    to be cached as covered: every later read got no rows and no hole)."""
    hot, port = _Hot(), _Port(100)  # the venue's newest bar is 99
    svc, bf = _svc(hot, port)
    window = Range(120 * W, 130 * W)  # ten bars past it
    await svc.read(SYM, IV, window)
    await asyncio.gather(*bf._jobs.values())
    port.bars = [_k(i * W) for i in range(140)]  # time passes: the venue now has those bars
    later = await svc.read(SYM, IV, window)
    assert later.holes == [window] and later.backfilling
    await asyncio.gather(*bf._jobs.values())
    again = await svc.read(SYM, IV, window)
    assert [r.ts_us for r in again.rows] == [i * W for i in range(120, 130)]
    assert again.holes == [] and not again.backfilling


async def test_read_without_backfill_service_is_cache_only() -> None:
    svc = KlineReadService(_Hot({0: _Row(0, source="kline")}))
    read = await svc.read(SYM, IV, Range(0, W))
    assert read.sources == ["questdb", "exchange_rest"] and read.recording_started_at_us is None


@dataclass
class _Bar:
    open_time: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    closed: bool = True


def _bar(t: int, *, closed: bool = True, **kw: str) -> _Bar:
    base = {"open": "100", "high": "101", "low": "99", "close": "100", "volume": "1"}
    base.update(kw)
    return _Bar(t, **{k: Decimal(v) for k, v in base.items()}, closed=closed)


def test_cross_check_logs_and_counts_divergence_beyond_tolerance() -> None:
    before = kline_crosscheck_divergence_total.labels(symbol=SYM, interval=IV)._value.get()
    klines = [_k(0), _k(W), _k(2 * W), _k(3 * W)]
    tape = [_bar(0), _bar(W, high="101.5"), _bar(2 * W, volume="1.0005"), _bar(9 * W)]
    with structlog.testing.capture_logs() as logs:
        out = cross_check(SYM, IV, klines, tape, tick_size=Decimal("0.1"))
    assert [(d.ts_us, d.fields) for d in out] == [(W, ("high",))]
    after = kline_crosscheck_divergence_total.labels(symbol=SYM, interval=IV)._value.get()
    assert after == before + 1
    ev = [e for e in logs if e["event"] == "kline_crosscheck_divergence"]
    assert ev and ev[0]["symbol"] == SYM and ev[0]["interval"] == IV and ev[0]["ts_us"] == W


@pytest.mark.parametrize(
    ("kw", "ticks", "fields"),
    [
        ({"close": "100.1"}, 1, ()),
        ({"close": "100.2"}, 1, ("close",)),
        ({"volume": "2"}, 0, ("volume",)),
        ({"volume": "0"}, 0, ("volume",)),
    ],
)
def test_cross_check_tolerance(kw: dict[str, str], ticks: int, fields: tuple[str, ...]) -> None:
    out = cross_check(
        SYM, IV, [_k(0)], [_bar(0, closed=True, **kw)], tick_size=Decimal("0.1"), price_ticks=ticks
    )
    assert (out[0].fields if out else ()) == fields


def test_cross_check_no_overlap_or_zero_volume_is_not_a_divergence() -> None:
    zero = _k(0).model_copy(update={"volume": Decimal(0)})
    assert cross_check(SYM, IV, [zero], [_bar(0, volume="0")]) == []
    assert cross_check(SYM, IV, [_k(W)], [_bar(0)]) == []


@pytest.mark.perf
async def test_cache_hit_5000_bars_median_read_within_300ms_budget() -> None:
    """US-MKT-008 sanity bound: a 5 000-bar cache hit within 300 ms of code-path overhead.
    `perf`-marked (deselected on shared laptops), gc disabled, fastest of 7; the adapter
    raises on any call, so this can never be a backfill in disguise."""
    import gc
    import time

    hot = _Hot({i * W: _Row(i * W) for i in range(5_000)})
    svc, _ = _svc(hot, _RaisingPort())
    samples = []
    gc.disable()
    try:
        for _ in range(7):
            t0 = time.perf_counter()
            read = await svc.read(SYM, IV, Range(0, 5_000 * W))
            samples.append((time.perf_counter() - t0) * 1000)
            assert len(read.rows) == 5_000
    finally:
        gc.enable()
    assert min(samples) <= 300.0


async def test_cache_hit_read_cost_scales_linearly_not_worse() -> None:
    """A5 ratio-style (no wall-clock budget): 10x the bars costs ~10x the work, measured as
    rows touched by the read path, never as time."""
    touched: list[int] = []

    class _Counting(_Hot):
        async def read_klines(self, *a: object, **kw: object) -> Sequence[_Row]:
            out = await super().read_klines(*a, **kw)  # type: ignore[arg-type]  # forwarded as-is
            touched.append(len(out))
            return out

    for n in (500, 5_000):
        hot = _Counting({i * W: _Row(i * W) for i in range(n)})
        svc, _ = _svc(hot, _RaisingPort())
        assert len((await svc.read(SYM, IV, Range(0, n * W))).rows) == n
    small, large = touched[-2], touched[-1]
    assert large <= 10 * small * 1.1


async def test_tracked_keys_are_lru_bounded_and_running_jobs_are_kept() -> None:
    port = _Port(0)
    port.release.clear()  # every job stays running until released
    bf = KlineBackfillService(fetch_klines=port, cache=_Hot(), max_tracked_keys=3)
    svc = KlineReadService(_Hot(), backfill=bf, max_tracked_keys=3)
    await svc.read("AAAUSDT", IV, Range(0, 2 * W))  # running job: never evicted
    port.release.set()
    await bf._jobs[("AAAUSDT", IV)]
    for i in range(10):
        await svc.read(f"S{i:02d}USDT", IV, Range(0, 2 * W))
        await asyncio.gather(*bf._jobs.values())
    assert bf.tracked_keys <= 3 and len(svc._primed) <= 3
    assert len(bf._locks) <= 3


async def test_read_limit_keeps_newest_rows() -> None:
    hot = _Hot({i * W: _Row(i * W) for i in range(10)})
    svc, _ = _svc(hot, _Port(10))
    read = await svc.read(SYM, IV, Range(0, 10 * W), limit=3)
    assert [r.ts_us for r in read.rows] == [7 * W, 8 * W, 9 * W]


def test_cross_check_skips_forming_bars_on_either_side() -> None:
    """A3: an unconfirmed kline or an unclosed tape bar is never compared."""
    forming = _k(0).model_copy(update={"confirmed": False})
    assert cross_check(SYM, IV, [forming], [_bar(0, high="200")]) == []
    assert cross_check(SYM, IV, [_k(0)], [_bar(0, closed=False, high="200")]) == []
    assert len(cross_check(SYM, IV, [_k(0)], [_bar(0, high="200")])) == 1


async def test_exchange_rest_only_claimed_once_an_exchange_row_is_merged() -> None:
    """A4: a running job alone does not add `exchange_rest`; a merged kline row does."""
    port = _Port(3)
    port.release.clear()
    svc, bf = _svc(_Hot(), port)
    first = await svc.read(SYM, IV, Range(0, 3 * W))
    assert first.backfilling and first.sources == []
    port.release.set()
    await bf._jobs[(SYM, IV)]
    second = await svc.read(SYM, IV, Range(0, 3 * W))
    assert second.sources == ["questdb", "exchange_rest"]


async def test_wired_recording_started_at_is_first_tape_trade_or_null() -> None:
    """A1, wiring level (real composition helper over the storage repository, no fake service):
    populated tape -> oldest trade ts; empty tape -> None."""
    from candleviewer.app import build_app_context, recording_started_at_us
    from candleviewer.storage.repositories.rows import TradeRow
    from candleviewer.storage.testing import FakeMarketDataRepository

    ctx = build_app_context()
    repo = FakeMarketDataRepository()
    ctx.storage._market_data = repo  # the fake backend's repository, as `storage.start()` sets
    first = recording_started_at_us(ctx)
    assert await first(SYM) is None
    await repo.write_trades([
        TradeRow(ts_us=t, symbol=SYM, price="1", qty="1", side="buy", trade_id=str(t))
        for t in (5_000, 2_000, 9_000)
    ])  # fmt: skip
    assert await first(SYM) == 2_000
    assert await first("ETHUSDT") is None
    svc = KlineReadService(_Hot(), recording_started_at_us=first)
    assert (await svc.read(SYM, IV, Range(0, W))).recording_started_at_us == 2_000
