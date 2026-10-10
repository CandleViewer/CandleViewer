"""E16-T04 interval algebra, tier split and `CoverageService` (Gherkin "Coverage is honest",
"Kline backfill does not erase the tick gap") + the hypothesis invariant."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.exchange.bybit.public_ws import stream_for_topic
from candleviewer.recorder.coverage import CoverageService, attribute_tiers
from candleviewer.recorder.integrity import mark_kline_backfill
from candleviewer.recorder.intervals import (
    COVERAGE_MERGE_TOLERANCE_MS,
    Span,
    coverage,
    subtract,
    union,
)
from candleviewer.recorder.sessions import SessionManager, to_dt, to_us
from candleviewer.storage.models import StreamKind
from tests.unit.recorder._session_fakes import MemRecorderStore, UsClock

S = 1_000_000


def _us(y: int, m: int, d: int, hh: int = 0, mm: int = 0, ss: int = 0) -> int:
    return to_us(datetime(y, m, d, hh, mm, ss, tzinfo=UTC))


# -- algebra ----------------------------------------------------------------------------------


def test_span_rejects_zero_length_and_inverted() -> None:
    with pytest.raises(ValueError):
        Span(5, 5)
    with pytest.raises(ValueError):
        Span(6, 5)


def test_union_merges_overlapping_and_adjacent_sessions() -> None:
    assert union([Span(5, 9), Span(0, 3), Span(3, 4), Span(8, 12)]) == [Span(0, 4), Span(5, 12)]


def test_subtract_adjacent_gaps() -> None:
    assert subtract([Span(0, 100)], [Span(10, 20), Span(20, 30), Span(90, 200)]) == [
        Span(0, 10), Span(30, 90)
    ]  # fmt: skip


def test_merge_tolerance_merges_hairlines_but_never_a_gap() -> None:
    tol = COVERAGE_MERGE_TOLERANCE_MS * 1000
    sessions = [Span(0, 10 * S), Span(10 * S + tol, 20 * S)]  # reconnect churn, no gap row
    assert coverage(sessions, []) == [Span(0, 20 * S)]
    real = Span(5 * S, 5 * S + 3 * S)  # a real 3 s gap
    assert coverage([Span(0, 20 * S)], [real]) == [Span(0, 5 * S), Span(8 * S, 20 * S)]
    tiny = Span(5 * S, 5 * S + 1)  # even a 1 µs gap row is kept
    assert coverage([Span(0, 20 * S)], [tiny]) == [Span(0, 5 * S), Span(5 * S + 1, 20 * S)]


def test_tier_split_at_watermark() -> None:
    got = attribute_tiers([Span(0, 10), Span(20, 30)], 25)
    assert [(i.lo, i.hi, i.tier) for i in got] == [
        (0, 10, "parquet"), (20, 25, "parquet"), (25, 30, "questdb")
    ]  # fmt: skip
    assert [i.tier for i in attribute_tiers([Span(0, 10)], 0)] == ["questdb"]


# -- property: coverage + gaps == session windows, never overlapping ---------------------------

_ev = st.lists(
    st.tuples(st.sampled_from(["drop", "up", "crash", "wait"]), st.integers(1, 600)),
    min_size=1, max_size=25,
)  # fmt: skip


@settings(max_examples=60, deadline=None)
@given(_ev)
async def test_property_coverage_plus_gaps_equals_sessions(events: list[tuple[str, int]]) -> None:
    store, clock = MemRecorderStore(), UsClock(_us(2026, 9, 1))
    t_start = clock.t
    mgr = SessionManager(store, now_us=clock, topics=stream_for_topic)
    from tests.unit.recorder.test_sessions import _added

    await mgr.on_set_changed(_added())
    for kind, secs in events:
        clock.advance_s(secs)
        if kind == "drop":
            await mgr.on_feed_health("publicTrade.BTCUSDT", "degraded")
        elif kind == "up":
            await mgr.on_feed_health("publicTrade.BTCUSDT", "healthy")
        elif kind == "crash":
            mgr = SessionManager(store, now_us=clock, topics=stream_for_topic)
            await mgr.recover_on_startup(clock.t)
            await mgr.on_set_changed(_added())
    clock.advance_s(1)
    hi = clock.t
    svc = CoverageService(store, now_us=clock)
    (cov,) = await svc.coverage("BTCUSDT", ["trades"], t_start, hi)
    intervals = [Span(i.lo, i.hi) for i in cov.intervals]
    gaps = [Span(g.lo, g.hi) for g in cov.gaps]
    sessions = []
    for s in store.sessions.values():
        end = to_us(s["ended_at"]) if s["ended_at"] else hi
        if end > to_us(s["started_at"]):
            sessions.append(Span(to_us(s["started_at"]), min(end, hi)))
    # Gaps may extend outside the session windows (process_restart covers the dead time).
    assert union(intervals) == subtract(sessions, gaps)
    for i in intervals:
        assert not any(g.lo < i.hi and g.hi > i.lo for g in gaps), "interval overlaps a gap"
    assert union([*intervals, *gaps]) == union([*subtract(sessions, gaps), *gaps])


# -- CoverageService (Gherkin) ----------------------------------------------------------------


@dataclass(frozen=True)
class _Mark:
    archived_through_us: int


class _Marks:
    def __init__(self, through: int) -> None:
        self.through = through
        self.calls: list[tuple[str, StreamKind]] = []

    async def get(self, symbol: str, stream: StreamKind) -> _Mark:
        self.calls.append((symbol, stream))
        return _Mark(self.through)


async def _seeded() -> tuple[MemRecorderStore, str]:
    """Trades recorded 2026-09-01 .. 09-14 with a ws gap 09-04 02:11:00 .. 02:14:20."""
    store = MemRecorderStore()
    sid = await store.open_session_at(
        recorded_symbol_id="r", symbol="BTCUSDT", streams=["trades"], orderbook_depth=200,
        ws_endpoint="x", started_at=to_dt(_us(2026, 9, 1)),
    )  # fmt: skip
    await store.close_session_at(sid, reason="stopped", ended_at=to_dt(_us(2026, 9, 14)))
    await store.touch_session_events(
        sid, first=to_dt(_us(2026, 9, 1)), last=to_dt(_us(2026, 9, 14))
    )
    await store.record_gap(
        session_id=sid, symbol="BTCUSDT", stream="trades",
        gap_start=to_dt(_us(2026, 9, 4, 2, 11)), gap_end=to_dt(_us(2026, 9, 4, 2, 14, 20)),
        cause="ws_disconnect",
    )  # fmt: skip
    return store, sid


async def test_coverage_two_intervals_with_tiers_and_the_gap_separately() -> None:
    store, _ = await _seeded()
    marks = _Marks(_us(2026, 9, 7))
    svc = CoverageService(store, now_us=UsClock(_us(2026, 9, 14, 10)), watermarks=marks)
    (cov,) = await svc.coverage("BTCUSDT", ["trades"], _us(2026, 9, 1), _us(2026, 9, 14))
    got = [(i.lo, i.hi, i.tier) for i in cov.intervals]
    g_lo, g_hi = _us(2026, 9, 4, 2, 11), _us(2026, 9, 4, 2, 14, 20)
    assert got == [
        (_us(2026, 9, 1), g_lo, "parquet"),
        (g_hi, _us(2026, 9, 7), "parquet"),
        (_us(2026, 9, 7), _us(2026, 9, 14), "questdb"),
    ]
    # two contiguous covered intervals (the watermark split is a tier boundary, not a hole)
    assert union([Span(a, b) for a, b, _ in got]) == [
        Span(_us(2026, 9, 1), g_lo), Span(g_hi, _us(2026, 9, 14))
    ]  # fmt: skip
    assert [(g.lo, g.hi, g.cause) for g in cov.gaps] == [(g_lo, g_hi, "ws_disconnect")]
    assert all(not (i.lo < g_hi and i.hi > g_lo) for i in cov.intervals)
    assert marks.calls == [("BTCUSDT", StreamKind.TRADES)]


async def test_coverage_cache_is_invalidated_by_writes_and_old_ranges_hit_sql() -> None:
    store, sid = await _seeded()
    now = UsClock(_us(2026, 9, 14, 10))
    svc = CoverageService(store, now_us=now)
    lo, hi = _us(2026, 9, 1), _us(2026, 9, 14)
    first = await svc.coverage("BTCUSDT", ["trades"], lo, hi)
    await store.record_gap(session_id=sid, symbol="BTCUSDT", stream="trades",
                           gap_start=to_dt(lo + S), gap_end=to_dt(lo + 2 * S),
                           cause="seq_jump")  # fmt: skip
    assert await svc.coverage("BTCUSDT", ["trades"], lo, hi) == first  # cached
    svc.invalidate("BTCUSDT")
    assert len((await svc.coverage("BTCUSDT", ["trades"], lo, hi))[0].gaps) == 2
    now.t = _us(2027, 6, 1)  # range now older than the 90 d cache: straight SQL
    assert len((await svc.coverage("BTCUSDT", ["trades"], lo, hi))[0].gaps) == 2
    with pytest.raises(ValueError):
        await svc.coverage("BTCUSDT", ["trades"], hi, lo)


async def test_coverage_other_stream_and_open_session_end_at_now() -> None:
    store = MemRecorderStore()
    await store.open_session_at(recorded_symbol_id="r", symbol="BTCUSDT", streams=["trades"],
                                orderbook_depth=1, ws_endpoint="x",
                                started_at=to_dt(_us(2026, 9, 1)))  # fmt: skip
    now = _us(2026, 9, 2)
    svc = CoverageService(store, now_us=UsClock(now))
    trades, book = await svc.coverage("BTCUSDT", ["trades", "orderbook_delta"], 0, now + S)
    assert [(i.lo, i.hi) for i in trades.intervals] == [(_us(2026, 9, 1), now)]
    assert book.intervals == () and book.gaps == ()


async def test_recording_started_at_is_earliest_first_event_ts() -> None:
    store, _ = await _seeded()
    sid2 = await store.open_session_at(recorded_symbol_id="r", symbol="BTCUSDT",
                                       streams=["trades"], orderbook_depth=1, ws_endpoint="x",
                                       started_at=to_dt(_us(2026, 8, 1)))  # fmt: skip
    await store.touch_session_events(
        sid2, first=to_dt(_us(2026, 8, 2)), last=to_dt(_us(2026, 8, 3))
    )
    svc = CoverageService(store, now_us=UsClock(0))
    assert await svc.recording_started_at_us("BTCUSDT") == _us(2026, 8, 2)
    assert await svc.recording_started_at_us("SOLUSDT") is None


async def test_kline_backfill_marks_gap_but_tick_coverage_still_missing() -> None:
    """Gherkin: Kline backfill does not erase the tick gap."""
    store, _ = await _seeded()
    g_lo, g_hi = _us(2026, 9, 4, 2, 11), _us(2026, 9, 4, 2, 14, 20)
    bars: list[tuple[int, int]] = []

    async def backfill(symbol: str, lo: int, hi: int) -> int:
        bars.append((lo, hi))
        return 3  # partly fillable: three 1-minute bars

    inval: list[str] = []
    marked = await mark_kline_backfill(store, backfill, "BTCUSDT", _us(2026, 9, 1),
                                       _us(2026, 9, 14), on_write=inval.append)  # fmt: skip
    assert marked == [1] and bars == [(g_lo, g_hi)] and inval == ["BTCUSDT"]
    assert store.gaps[0]["backfilled"] is True and store.gaps[0]["backfill_source"] == "kline"
    assert to_us(store.gaps[0]["gap_start"]) == g_lo and to_us(store.gaps[0]["gap_end"]) == g_hi
    svc = CoverageService(store, now_us=UsClock(_us(2026, 9, 14, 10)))
    (cov,) = await svc.coverage("BTCUSDT", ["trades"], _us(2026, 9, 1), _us(2026, 9, 14))
    assert [(g.lo, g.hi, g.backfilled, g.backfill_source) for g in cov.gaps] == [
        (g_lo, g_hi, True, "kline")
    ]  # fmt: skip
    assert all(not (i.lo < g_hi and i.hi > g_lo) for i in cov.intervals)
    # idempotent: an already-backfilled gap is not refetched
    assert await mark_kline_backfill(store, backfill, "BTCUSDT", 0, _us(2026, 9, 14)) == []


async def test_kline_backfill_with_no_bars_leaves_gap_unmarked() -> None:
    store, _ = await _seeded()

    async def nothing(symbol: str, lo: int, hi: int) -> int:
        return 0

    assert await mark_kline_backfill(store, nothing, "BTCUSDT", 0, _us(2026, 9, 14)) == []
    assert store.gaps[0]["backfilled"] is False


async def test_real_watermark_store_drives_tier_attribution(tmp_path: Path) -> None:
    """E16-T05 API (FileWatermarkStore): before roll-off everything is questdb; advancing the
    watermark into a session splits it; past the session window makes it entirely parquet."""
    from candleviewer.storage.cold.layout import DatasetRegistry
    from candleviewer.storage.cold.watermarks import FileWatermarkStore

    store, _ = await _seeded()
    marks = FileWatermarkStore(DatasetRegistry(tmp_path / "cold"))
    lo, hi = _us(2026, 9, 1), _us(2026, 9, 14)
    svc = CoverageService(store, now_us=UsClock(_us(2026, 9, 14, 10)), watermarks=marks)

    async def tiers() -> list[tuple[int, int, str]]:
        svc.invalidate("BTCUSDT")
        (cov,) = await svc.coverage("BTCUSDT", ["trades"], lo, hi)
        return [(i.lo, i.hi, i.tier) for i in cov.intervals]

    assert {t for *_, t in await tiers()} == {"questdb"}
    await marks.advance("BTCUSDT", StreamKind.TRADES, _us(2026, 9, 10), now_us=0)
    got = await tiers()
    assert (_us(2026, 9, 10), hi, "questdb") in got
    assert all(t == "parquet" for a, b, t in got if b <= _us(2026, 9, 10))
    await marks.advance("BTCUSDT", StreamKind.TRADES, _us(2026, 9, 20), now_us=0)
    assert {t for *_, t in await tiers()} == {"parquet"}
    assert len(await tiers()) == 2  # gap still separates; no questdb tail
