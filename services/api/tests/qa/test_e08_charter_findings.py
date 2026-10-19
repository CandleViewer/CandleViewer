"""E08-Q06 exploratory charter findings, promoted to tests (#283).

Each test drives production code in-process (recorded corpus, fake clock, no network) and asserts
the behaviour the E08 contracts promise. Both fail on main today, so they are strict xfails: the
fix flips one to a failure and its PR removes the marker. Each xfail is limited to
`AssertionError`, so a probe that a refactor breaks fails loudly instead of passing as expected.
Debriefs: `docs/qa/charters/` (E08-charter-1 to -4). Under the E08 severity rule
(`qa/plans/e08-market-data-test-plan.md` section 0.1) wrong or old data with no visible signal is
P0, and the coordinator filed the findings as P0 bugs on 2026-10-19: F1 is #3806, F2 is #3807 and
F3 is #3808; each reason below names its issue. #3823 fixed F1 before this module merged: its
strict xfail XPASSed when this change was rebased, so the F1 probe was removed here, and its
regression case is the one #3823 added in `tests/unit/ingestion/test_book_grid_resync.py`. A fix
that merges before this module flips its test to a strict XPASS, which fails the pack; whichever
change lands second removes the marker.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

import pytest

from candleviewer.book.models import BookPhase
from candleviewer.bus.bus import Bus
from candleviewer.exchange.base.models import KlineEvent
from candleviewer.exchange.bybit.orderbook import book_topic, parse_book_frame
from candleviewer.ingestion.kline_backfill import KlineBackfillService
from candleviewer.ingestion.kline_coverage import Range
from candleviewer.ingestion.kline_read import KlineReadService
from candleviewer.orderbook_wiring import BookStream
from tests._corpus import frames

BOOK: str = "ws/orderbook_BTCUSDT.jsonl"
NOW_US = 1_700_000_100_000_000


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


async def _resubscribe(_topic: str) -> None:
    return None


def _book_stream(tick: dict[str, Decimal], clock: _Clock, desired: list[set[str]]) -> BookStream:
    return BookStream(
        bus=Bus(),
        env="live",
        set_desired=lambda topics: desired.append(set(topics)),
        parse_frame=lambda f: parse_book_frame(f, tick.get),
        topic_for=book_topic,
        resubscribe=_resubscribe,
        is_listed=lambda s: s == "BTCUSDT",
        touch=lambda _t: None,
        clock=clock,
        now_us=lambda: NOW_US,
    )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="#3807 (E08-Q06 charter 2, F2): once a released book's grace runs out with no "
    "sync(), its frames are ignored and the frozen book is served as live",
)
async def test_f2_a_released_book_is_never_served_frozen_as_live_after_its_grace() -> None:
    clock = _Clock()
    desired: list[set[str]] = []
    stream = _book_stream({"BTCUSDT": Decimal("0.1")}, clock, desired)
    stream.acquire("ws:book:50", "BTCUSDT")
    raw = frames(BOOK)
    for frame in raw[:100]:
        await stream.handle_frame(frame)
    stream.release("ws:book:50", "BTCUSDT")
    clock.t = 3600.0  # an hour on; the upstream feed kept running
    for frame in raw[100:400]:
        await stream.handle_frame(frame)

    view = stream.view("BTCUSDT", 50)
    served_live = stream.phase("BTCUSDT") is BookPhase.LIVE and view is not None and not view.stale
    assert not served_live, "a book that stopped applying frames an hour ago is served as live"


_W = 300_000_000  # one 5-minute bar, in microseconds


def _bar(index: int) -> KlineEvent:
    start = index * _W
    return KlineEvent.model_validate(
        dict(event_id="00000000-0000-7000-8000-000000000001", ts_event=start, ts_ingest=start,
             source="backfill", symbol="BTCUSDT", interval="5", start=start, end=start + _W - 1,
             open="100", high="101", low="99", close="100", volume="1", turnover="100",
             confirmed=True)
    )  # fmt: skip


@dataclass
class _Row:
    ts_us: int
    source: str
    confirmed: bool = True
    open: str = "100"
    high: str = "101"
    low: str = "99"
    close: str = "100"
    volume: str = "1"
    turnover: str = "100"


@dataclass
class _HotTier:
    rows: dict[int, _Row] = field(default_factory=dict)

    async def read_klines(
        self, sym: str, interval: str, rng: Range, tier: str = "auto", limit: int | None = None
    ) -> Sequence[_Row]:
        out = [r for t, r in sorted(self.rows.items()) if rng.start_us <= t < rng.end_us]
        return out if limit is None else out[-limit:]

    async def write_klines(self, rows: Sequence[object]) -> None:
        for row in rows:
            assert isinstance(row, dict)
            self.rows[int(row["ts_us"])] = _Row(int(row["ts_us"]), str(row["source"]))


@dataclass
class _Venue:
    """Serves the bars it has; `latest` is the newest bar the venue has formed so far."""

    latest: int
    calls: int = 0

    async def __call__(
        self, symbol: str, interval: str, start: int, end: int, limit: int = 1000
    ) -> Sequence[KlineEvent]:
        self.calls += 1
        bars = [_bar(i) for i in range(self.latest + 1) if start <= i * _W <= end]
        return bars[-limit:]


async def _settle(backfill: KlineBackfillService) -> None:
    # The read schedules the backfill job and nothing public awaits it, so this reaches into the
    # private `_jobs`. If that is renamed, F3 fails with AttributeError (outside `raises=`), loudly.
    await asyncio.gather(*backfill._jobs.values())


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="#3808 (E08-Q06 charter 3, F3): a klines window after the venue's newest bar is "
    "cached as covered, so its bars are never fetched or flagged",
)
async def test_f3_a_window_read_before_its_bars_exist_is_fetched_once_they_do() -> None:
    hot, venue = _HotTier(), _Venue(latest=99)
    backfill = KlineBackfillService(fetch_klines=venue, cache=hot)
    read = KlineReadService(hot, backfill=backfill)
    window = Range(120 * _W, 130 * _W)  # ten bars past the venue's newest one

    await read.read("BTCUSDT", "5", window)
    await _settle(backfill)
    venue.latest = 139  # time passes: the venue now has those bars
    later = await read.read("BTCUSDT", "5", window)
    await _settle(backfill)
    again = await read.read("BTCUSDT", "5", window)

    reported = bool(later.holes) or later.backfilling or bool(again.rows)
    assert reported, "the bars exist at the venue, yet reads return none and report no hole"
