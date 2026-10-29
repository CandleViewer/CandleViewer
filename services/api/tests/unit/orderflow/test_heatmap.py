"""E21-T02 (#605): the `HeatmapEngine` and the `heatmap.{symbol}` topic (`orderflow/heatmap.py`)
against a fake hub, on a fake epoch-ms clock (never a sleep): the Gherkin scenarios of the ticket
and the D-rows of its ruling (BQ-5), the G-02 / G-03 / G-07a caps, the kind-6 part and the
`heatmap_cells` hand-off. Book input is the book module's own engine fed synthetic levels or the
recorded captures (`packages/fixtures/bybit/2026-10-05`, C-13.5); no network."""

from __future__ import annotations

import asyncio
import base64
import itertools
import json
from array import array
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any, cast

import pytest
from prometheus_client import REGISTRY

from candleviewer.book.models import BookPhase
from candleviewer.book.resync import BookEngine
from candleviewer.bus.bus import Bus
from candleviewer.bus.models import StreamInvalidated
from candleviewer.exchange.base.models import BookDelta, BookLevel, BookSnapshot
from candleviewer.orderflow import heatmap as H
from candleviewer.orderflow.heatmap import (
    COLUMN_MS,
    HEATMAP_SNAPSHOT_MAX_COLUMNS,
    ROWS,
    HeatmapColumn,
    HeatmapLease,
    HeatmapSpec,
    HeatmapSpecCapError,
    HeatmapTopic,
)
from candleviewer.ws.binary import FLAG_ESTIMATED, HEATMAP_COLUMN, Frame, decode, encode
from candleviewer.ws.cvwb_vectors import structured
from candleviewer.ws.sequencing import SnapshotBody
from tests._corpus import frames
from tests.chaos.ws._book import _recorded
from tests.unit.book._builders import delta, lvl, snap

SYM = "BTCUSDT"
T0 = 1_700_000_000_000  # epoch ms on every bucket grid (100 ms to 5 s)
STEPS = {
    "BTCUSDT": (Decimal("0.1"), Decimal("0.001")),
    "ETHUSDT": (Decimal("0.01"), Decimal("0.01")),
}
QUEUE_BYTES, QUEUE_FRAMES = 8_388_608, 2_000


@dataclass
class Sub:
    """The fields of a WS subscription the topic reads."""

    heatmap_lease: HeatmapLease | None
    effective: dict[str, Any] = field(default_factory=lambda: {"encoding": "binary"})
    replay_session_id: str | None = None
    snapshot_pending: bool = False
    ch: str = f"heatmap.{SYM}"


@dataclass
class Hub:
    frames: list[tuple[str, dict[str, Any], Any]] = field(default_factory=list)
    subs: list[Sub] = field(default_factory=list)
    flushed: list[Sub] = field(default_factory=list)

    def publish(
        self,
        ch: str,
        body: Mapping[str, Any] | None = None,
        *,
        part: Any = None,
        coalesced_count: int = 1,
        select: Callable[[Any], bool] | None = None,
    ) -> int:
        assert body is not None and coalesced_count == 1
        self.frames.append((ch, dict(body), part))
        return sum(1 for s in self.subs if select is None or select(s))

    def flush_pending(self, match: Callable[[Any], bool] | None = None) -> int:
        hits = [s for s in self.subs if match is None or match(s)]
        self.flushed.extend(hits)
        return len(hits)


def part(
    ts_ms: int,
    pmin: int,
    pstep: int,
    rows: tuple[tuple[int, int], ...],
    ps: int,
    qs: int,
    est: bool,
) -> Frame:
    return Frame(HEATMAP_COLUMN, rows, FLAG_ESTIMATED if est else 0, ps, qs, ts_base_ms=ts_ms,
                 prefix=(0, pmin, pstep))  # fmt: skip


class Store:
    def __init__(self) -> None:
        self.columns: list[
            tuple[str, int, tuple[tuple[float, float, float], ...], dict[str, Any]]
        ] = []
        self.closed = False

    async def write_column(
        self, symbol: str, ts_us: int, cells: Sequence[tuple[float, float, float]], **kw: Any
    ) -> None:
        self.columns.append((symbol, ts_us, tuple(cells), kw))

    async def close(self) -> None:
        self.closed = True


class World:
    def __init__(self, *, store: Store | None = None, queue_frames: int = QUEUE_FRAMES) -> None:
        self.now = float(T0)
        self.hub = Hub()
        self.engines: dict[str, BookEngine] = {}
        self.liquid: list[tuple[str, HeatmapColumn]] = []
        self.steps: dict[str, tuple[Decimal, Decimal]] = dict(STEPS)
        self.topic = HeatmapTopic(
            self.hub, engine=self.engines.get, steps=self.steps.get, part=part, body=SnapshotBody,
            bus=Bus(), env="live", queue_bytes=QUEUE_BYTES, queue_frames=queue_frames, store=store,
            liquidity=lambda s, c: self.liquid.append((s, c)), clock_ms=lambda: self.now,
        )  # fmt: skip

    async def engine(self, symbol: str = SYM, depth: int = 200) -> BookEngine:
        async def publish(ev: object) -> None:
            self.topic.offer(ev)

        async def resub() -> None:
            return None

        eng = BookEngine(symbol=symbol, depth=depth, publish=publish, resubscribe=resub,
                         now_us=lambda: int(self.now * 1000))  # fmt: skip
        self.engines[symbol] = eng
        await eng.start()
        return eng

    def hold(self, spec: HeatmapSpec, consumer: str = "c1", **effective: Any) -> Sub:
        sub = Sub(self.topic.hold(consumer, spec), {"encoding": "binary", **effective})
        self.hub.subs.append(sub)
        return sub

    def at(self, ms: float) -> int:
        """Move the clock to `T0 + ms` and run one turn; the frames sent."""
        self.now = T0 + ms
        return self.topic.tick()

    def columns(self) -> list[dict[str, Any]]:
        return [c for _, body, _ in self.hub.frames for c in body["columns"]]


def ladder(
    bid: int = 10_000, ask: int = 10_001, n: int = 50
) -> tuple[list[BookLevel], list[BookLevel]]:
    return [lvl(bid - i, 1) for i in range(n)], [lvl(ask + i, 2) for i in range(n)]


async def live(w: World, bids: list[BookLevel] | None = None, asks: list[BookLevel] | None = None,
               symbol: str = SYM) -> BookEngine:  # fmt: skip
    eng = await w.engine(symbol)
    b, a = ladder()
    await eng.on_event(snap(10, b if bids is None else bids, a if asks is None else asks))
    assert eng.phase is BookPhase.LIVE
    return eng


def ring(w: World, spec: HeatmapSpec) -> list[HeatmapColumn]:
    """The columns a spec's ring holds, oldest first."""
    return list(w.topic._symbols[spec.symbol].specs[spec].ring)


def missing(symbol: str = SYM) -> float:
    value = REGISTRY.get_sample_value("heatmap_missing_columns_total", {"symbol": symbol})
    return value or 0.0


def emitted(state: str) -> float:
    return REGISTRY.get_sample_value("heatmap_columns_emitted_total", {"state": state}) or 0.0


# -- Gherkin "Columns at cadence" and the cadence D-row -------------------------------------------


async def test_columns_at_cadence_exactly_one_column_per_100ms_bucket() -> None:
    """Gherkin "Columns at cadence" (D-row: fake-clock cadence +-0): one column per 100 ms bucket,
    each at its bucket's start, complete (its sample count equals the native count, so `samples`
    is left out, 23 §14.5), with its kind-6 twin."""
    w = World()
    await live(w)
    w.hold(HeatmapSpec(SYM, time_bucket_ms=100))
    for k in range(1, 11):
        assert w.at(k * COLUMN_MS) == 1
        assert w.at(k * COLUMN_MS + 50) == 0  # nothing between two deadlines
    cols = w.columns()
    assert [c["t_ms"] for c in cols] == [T0 + k * COLUMN_MS for k in range(10)]
    assert all(c["complete"] is True and "samples" not in c for c in cols)
    assert all(p is not None for _, _, p in w.hub.frames)
    held = ring(w, HeatmapSpec(SYM, time_bucket_ms=100))
    assert [(c.samples, c.expected) for c in held] == [(1, 1)] * 10


async def test_columns_at_cadence_a_500ms_bucket_counts_five_samples() -> None:
    w = World()
    await live(w)
    w.hold(HeatmapSpec(SYM, time_bucket_ms=500))
    for k in range(1, 11):
        w.at(k * COLUMN_MS)
    cols = ring(w, HeatmapSpec(SYM, time_bucket_ms=500))
    assert [(c.ts_ms, c.samples, c.expected) for c in cols] == [(T0, 5, 5), (T0 + 500, 5, 5)]


async def test_columns_at_cadence_a_250ms_bucket_counts_its_own_deadlines() -> None:
    """A 250 ms bucket holds two or three native deadlines (none of them on its edge at 250)."""
    w = World()
    await live(w)
    w.hold(HeatmapSpec(SYM, time_bucket_ms=250))
    for k in range(1, 11):
        w.at(k * 50)
    cols = ring(w, HeatmapSpec(SYM, time_bucket_ms=250))
    assert [(c.ts_ms - T0, c.samples, c.expected) for c in cols] == [(0, 2, 2), (250, 3, 3)]
    assert all("samples" not in c for c in w.columns())


async def test_columns_at_cadence_only_levels_inside_the_window_off_window_totals_apart() -> None:
    """Gherkin "Columns at cadence": the column holds only levels inside its window; a level
    beyond it is the off-window total, carried on the structured wire only (BQ-8)."""
    w = World()
    b, a = ladder()
    await live(w, [*b, lvl(10_000 - 400, 7)], [*a, lvl(10_001 + 300, 3)])
    w.hold(HeatmapSpec(SYM, time_bucket_ms=100))
    w.at(100)
    [(_, body, p)] = w.hub.frames
    [col] = body["columns"]
    assert (col["off_window_bid_qty"], col["off_window_ask_qty"]) == (7.0, 3.0)
    assert p is None  # kind 6 has no field for it: structured
    lo = Decimal(col["price_min"])
    assert lo > Decimal("960") and len(col["bids"]) <= ROWS
    assert sum(col["bids"]) == 50.0 and sum(col["asks"]) == 100.0


async def test_time_weighted_a_level_resting_5ms_of_100_weighs_5_percent() -> None:
    w = World()
    eng = await live(w)
    spec = HeatmapSpec(SYM, time_bucket_ms=100)
    w.hold(spec)
    await eng.on_event(delta(11, 10, [lvl(9_990, 10)]))  # 9 990 already rests at 1
    w.at(50)
    await eng.on_event(delta(12, 11, [lvl(9_990, 1)]))
    w.at(55)
    w.at(100)
    [col] = ring(w, spec)
    row = (9_990 - col.price_origin_ticks) // col.price_step_ticks
    assert col.bid_sizes[row] == pytest.approx(1 + 9 * 0.05)  # 1 throughout, +9 for 5 ms of 100
    assert col.bid_sizes[(10_000 - col.price_origin_ticks)] == pytest.approx(1.0)


async def test_rows_never_exceed_the_row_cap() -> None:
    """G-07a (23 §16.2): a column carries at most `rows` rows; a book wider than the window in
    steps goes to the off-window totals, never to more rows."""
    w = World()
    bids = [lvl(10_000 - 2 * i, 1) for i in range(200)]  # 400 ticks a side: wider than 512 rows
    asks = [lvl(10_001 + 2 * i, 1) for i in range(200)]
    await live(w, bids, asks)
    w.hold(HeatmapSpec(SYM, time_bucket_ms=100))
    w.at(100)
    [col] = w.columns()
    assert len(col["bids"]) == len(col["asks"]) <= ROWS
    total = sum(col["bids"]) + col.get("off_window_bid_qty", 0)
    assert total == 200.0 and col["off_window_bid_qty"] > 0


# -- Gherkin "Engine stall is visible" ------------------------------------------------------------


async def test_engine_stall_is_visible_as_samples_zero_columns() -> None:
    """Gherkin "Engine stall is visible" (D-row: a stall is a missed column deadline): each missed
    deadline is a `samples = 0`, empty column, and `heatmap_missing_columns_total` counts it."""
    w = World()
    await live(w)
    w.hold(HeatmapSpec(SYM, time_bucket_ms=100))
    w.at(100)
    before = missing()
    w.at(450)  # the loop ran 350 ms late: the deadlines at 200 and 300 were missed
    cols = w.columns()
    assert [(c["t_ms"] - T0, c.get("samples")) for c in cols] == [
        (0, None), (100, 0), (200, 0), (300, None),
    ]  # fmt: skip
    assert cols[1]["bids"] == cols[1]["asks"] == []
    assert missing() - before == 2


async def test_engine_stall_in_a_500ms_bucket_leaves_it_incomplete_and_structured() -> None:
    w = World()
    await live(w)
    w.hold(HeatmapSpec(SYM, time_bucket_ms=500))
    w.at(100)
    w.at(450)  # 200 and 300 missed, 400 met
    w.at(500)
    [(_, body, p)] = w.hub.frames
    assert body["columns"][0]["samples"] == 3 and p is None


async def test_a_very_long_stall_skips_without_building_a_column_per_deadline() -> None:
    w = World()
    await live(w)
    w.hold(HeatmapSpec(SYM, time_bucket_ms=100))
    w.at(100)
    before = missing()
    w.at(100 + (HEATMAP_SNAPSHOT_MAX_COLUMNS + 10) * COLUMN_MS)
    assert missing() - before == HEATMAP_SNAPSHOT_MAX_COLUMNS + 10
    assert len(w.columns()) == 1  # the gap is a gap: no column is built for it
    w.at(100 + (HEATMAP_SNAPSHOT_MAX_COLUMNS + 11) * COLUMN_MS)
    assert len(w.columns()) == 2


# -- Gherkin "Resync marks data estimated" --------------------------------------------------------


async def test_resync_marks_data_estimated_and_keeps_it_from_the_rules_side() -> None:
    """Gherkin "Resync marks data estimated" (D-row: estimated columns never reach the rules
    module, tested at the topic boundary): after a sequence gap every column built while the book
    resyncs is `estimated` (root flag, kind-6 bit0), and the `liquidity` consumer gets the live
    native columns only."""
    w = World()
    eng = await live(w)
    w.hold(HeatmapSpec(SYM, time_bucket_ms=100))
    w.at(100)
    assert [c.estimated for _, c in w.liquid] == [False]
    await eng.on_event(delta(99, 50, [lvl(9_000, 1)]))  # `prev` is not the last `u`: a gap
    assert eng.phase is not BookPhase.LIVE
    w.at(110)  # the topic reads the status edge 10 ms later
    before = emitted("estimated")
    for k in range(2, 5):
        w.at(k * COLUMN_MS)
    frames = w.hub.frames[1:]
    assert [body["estimated"] for _, body, _ in frames] == [True, True, True]
    assert all(p is not None and p.flags & FLAG_ESTIMATED for _, _, p in frames)
    assert emitted("estimated") - before == 3
    assert len(w.liquid) == 1  # none of the three estimated native columns
    await eng.on_event(snap(200, *ladder()))  # the fresh snapshot: live again
    w.at(450)
    w.at(600)
    assert w.hub.frames[-1][1]["estimated"] is False
    assert [c.estimated for _, c in w.liquid][-1] is False


async def test_resync_past_the_estimate_hold_leaves_samples_zero() -> None:
    w = World()
    eng = await live(w)
    w.hold(HeatmapSpec(SYM, time_bucket_ms=100))
    w.at(100)
    await eng.on_event(delta(99, 50))
    w.at(150)
    hold = H.RESYNC_ESTIMATE_MS
    for k in range(2, hold // COLUMN_MS + 4):
        w.at(k * COLUMN_MS)
    frames = [body for _, body, _ in w.hub.frames]
    last = frames[-1]["columns"][0]
    assert last["samples"] == 0 and last["bids"] == []
    # Every column closed during the resync is estimated, past the hold too.
    assert all(body["estimated"] is True for body in frames[1:])


async def test_resync_on_the_recorded_gap_capture_marks_columns_estimated() -> None:
    """The recorded ETHUSDT capture (`gap_orderbook_ETHUSDT.jsonl`, C-13.5): its book crosses at
    `u = 3`, a desync, so the columns after it are estimated until a fresh snapshot."""
    w = World()
    eng = await w.engine("ETHUSDT", depth=50)
    w.hold(HeatmapSpec("ETHUSDT", depth=50, time_bucket_ms=100))
    tick = STEPS["ETHUSDT"][0]
    prev = 0
    for k, line in enumerate(frames("ws/gap_orderbook_ETHUSDT.jsonl")[:6], start=1):
        rec = json.loads(line)
        data = rec["data"]
        side = [[_level(p, q, tick) for p, q in data[s]] for s in ("b", "a")]
        if rec["type"] == "snapshot":
            await eng.on_event(_eth_snap(data["u"], *side))
        else:
            await eng.on_event(_eth_delta(data["u"], prev, *side))
        prev = data["u"]
        w.at(k * COLUMN_MS)
    flags = [body["estimated"] for _, body, _ in w.hub.frames]
    assert flags[0] is False and flags[-1] is True


def _level(price: str, qty: str, tick: Decimal) -> BookLevel:
    return BookLevel(price=Decimal(price), qty=Decimal(qty), price_ticks=int(Decimal(price) / tick))


def _eth_snap(u: int, bids: list[BookLevel], asks: list[BookLevel]) -> BookSnapshot:
    return snap(u, bids, asks, depth=50).model_copy(update={"symbol": "ETHUSDT"})


def _eth_delta(u: int, prev: int, bids: list[BookLevel], asks: list[BookLevel]) -> BookDelta:
    return delta(u, prev, bids, asks, depth=50).model_copy(update={"symbol": "ETHUSDT"})


async def test_the_recorded_btc_capture_builds_complete_columns_around_the_mid() -> None:
    """The recorded BTCUSDT depth-200 capture (`orderbook_BTCUSDT.jsonl`) through the book engine
    and the heatmap, one delta per native column: every column is complete, holds at most `rows`
    rows and sits around the book's mid; the sizes are the book's."""
    w = World()
    eng = await w.engine()
    w.hold(HeatmapSpec(SYM, time_bucket_ms=100))
    first, deltas = _recorded()
    tick = STEPS[SYM][0]

    def side(levels: list[list[str]]) -> list[BookLevel]:
        return [_level(p, q, tick) for p, q in levels]

    await eng.on_event(snap(first["u"], side(first["b"]), side(first["a"])))
    w.at(0)
    prev = first["u"]
    for k, data in enumerate(deltas[:50], start=1):
        await eng.on_event(delta(data["u"], prev, side(data["b"]), side(data["a"])))
        prev = data["u"]
        w.at(k * COLUMN_MS)
    assert eng.phase is BookPhase.LIVE
    cols = ring(w, HeatmapSpec(SYM, time_bucket_ms=100))
    assert len(cols) == 50 and all(c.full and 0 < c.rows <= ROWS for c in cols)
    last = cols[-1]
    assert last.best_bid_ticks is not None and last.best_ask_ticks is not None
    mid = (last.best_bid_ticks + last.best_ask_ticks) // 2
    assert last.price_origin_ticks <= mid < last.price_origin_ticks + last.rows


# -- D-rows: re-centring on a price gap, the restart gap ------------------------------------------


async def test_a_price_gap_recentres_with_empty_columns_between() -> None:
    """D-row (24 §6.3 "Price gap larger than the window"): the buckets with no book are empty
    `samples = 0` columns, never stretched, and the next column re-centres on the new mid."""
    w = World()
    eng = await live(w)
    spec = HeatmapSpec(SYM, time_bucket_ms=100)
    w.hold(spec)
    w.at(100)
    await eng.on_event(delta(99, 50))  # resync: no book
    end = H.RESYNC_ESTIMATE_MS + 300
    w.at(150)
    for k in range(2, end // COLUMN_MS):
        w.at(k * COLUMN_MS)
    await eng.on_event(snap(500, *ladder(60_000, 60_001)))  # far beyond 512 rows away
    w.at(end - 50)
    w.at(end + 100)
    cols = ring(w, spec)
    gap = [c for c in cols if c.samples == 0]
    assert gap and all(c.rows == 0 for c in gap)
    new = cols[-1]
    assert new.samples == 1 and new.price_origin_ticks > 59_000
    assert cols[0].price_origin_ticks < 10_001 < cols[0].price_origin_ticks + ROWS


async def test_the_restart_gap_reads_samples_zero_never_interpolated() -> None:
    """D-row (21 §4.12 "Restart"): a restarted engine re-seeds from the live book at the next
    boundary and stores nothing for the time it was down; its first bucket counts only the
    deadlines it met (`samples` below the native count)."""
    store = Store()
    w = World(store=store)
    await live(w)
    w.hold(HeatmapSpec(SYM, time_bucket_ms=500))
    for k in range(1, 4):
        w.at(k * COLUMN_MS)
    stored = [c.ts_us for c in w.topic._stored]
    assert stored == [(T0 + k * COLUMN_MS) * 1000 for k in range(3)]
    again = World(store=store)  # the restart, 10.2 s later
    again.now = T0 + 10_200
    eng = await live(again)
    assert eng.phase is BookPhase.LIVE
    again.hold(HeatmapSpec(SYM, time_bucket_ms=500))
    again.at(10_300)
    again.at(10_400)
    again.at(10_500)
    assert [c.ts_us // 1000 - T0 for c in again.topic._stored] == [10_200, 10_300, 10_400]
    [col] = again.columns()
    assert (col["t_ms"] - T0, col["samples"]) == (10_000, 3)  # 10 000-10 200 is the gap


# -- Gherkin "Snapshot cap" and G-03 --------------------------------------------------------------


def _col(
    t: int, rows: int, *, samples: int = 1, off: float = 0.0, est: bool = False
) -> HeatmapColumn:
    sizes = array("d", [1.0] * rows)
    return HeatmapColumn(T0 + t, 100, 10_000, 1, sizes, array("d", sizes), 10_000, 10_001, off,
                         0.0, est, samples, 1)  # fmt: skip


def _ring(n: int, rows: int = 400) -> list[HeatmapColumn]:
    return [_col(100 * i, rows) for i in range(n)]


def test_the_ring_is_columnar_and_returns_each_column_as_appended() -> None:
    """23 §6.1, §16.2: a spec's ring is one float64 buffer and a vector a field, 15.6 MiB
    and a little at 2 000 x 512; a column comes back as it went in, None prices included."""
    ring = H._Ring(HEATMAP_SNAPSHOT_MAX_COLUMNS)
    assert ring.nbytes <= 16 * 2**20 and ring._sizes.shape == (2_000, 2 * ROWS)
    col = replace(
        _col(0, 3, samples=2, off=0.5, est=True),
        best_bid_ticks=None,
        bid_sizes=array("d", [0.1, 0.0, 2.5]),
        ask_sizes=array("d", [0.0, 1e-9, 3.0]),
    )
    ring.append(col)
    assert ring[0] == col and ring[-1] == col and list(ring) == [col]
    assert ring.rows(0) == 3 and ring.t_ms(0) == T0 and ring.estimated(0)
    empty = replace(_col(100, 0, samples=0), best_ask_ticks=None)
    ring.append(empty)
    assert ring[1] == empty and ring[1].rows == 0


def test_the_ring_drops_its_oldest_at_capacity_and_a_read_column_keeps_its_values() -> None:
    """As `deque(maxlen=)`: the oldest out at capacity; a column read before its slot is reused
    is a copy, unchanged by the reuse."""
    ring = H._Ring(3)
    ring.extend(_col(100 * i, 2 + i) for i in range(3))
    first = ring[0]
    ring.append(_col(300, 5))
    assert [c.ts_ms for c in ring] == [T0 + 100, T0 + 200, T0 + 300]
    assert first.ts_ms == T0 and first.rows == 2  # its slot now holds T0 + 300
    with pytest.raises(IndexError):
        ring.appendleft(_col(-100, 1))
    with pytest.raises(IndexError):
        ring[3]
    assert ring.pop().ts_ms == T0 + 300 and len(ring) == 2
    ring.appendleft(_col(0, 1))
    assert [c.ts_ms for c in ring] == [T0, T0 + 100, T0 + 200]


def test_the_ring_copies_its_newest_columns_and_refuses_a_column_past_rows() -> None:
    """A seed's donor columns are copied (24 §6.3): later appends to the donor do not move them;
    a column past `ROWS` (G-07a) is refused, as is a side shorter than the other."""
    ring = H._Ring(4)
    ring.extend(_col(100 * i, 1) for i in range(6))  # wrapped: T0+200 .. T0+500
    copy = ring.newest(3)
    ring.append(_col(600, 1))
    assert [c.ts_ms for c in copy] == [T0 + 300, T0 + 400, T0 + 500]
    assert copy.pop().ts_ms == T0 + 500 and len(copy) == 2
    assert len(H._Ring(0).newest(5)) == 0
    H._Ring(0).append(_col(0, 1))  # the native spec keeps no ring
    full = H._Ring(1)
    full.append(_col(0, ROWS))
    full.append(_col(100, 3))  # the slot's reuse leaves no cell of its last column
    assert not full._sizes[0, 3:ROWS].any() and not full._sizes[0, ROWS + 3 :].any()
    with pytest.raises(ValueError, match="ROWS"):
        ring.append(_col(0, ROWS + 1))
    with pytest.raises(ValueError, match="ROWS"):
        ring.append(replace(_col(0, 2), ask_sizes=array("d", [1.0])))


@pytest.mark.parametrize("seed", range(20))
def test_the_rings_g03_walk_takes_the_columns_snapshot_columns_takes(seed: int) -> None:
    """G-03 (23 §6.1): the ring's vectorised walk is `snapshot_columns`' walk, in kind 6's and
    in §14.5's sizes, whatever the rows, the wrap and the bounds."""
    import random

    rng = random.Random(seed)  # noqa: S311 - seeded test data
    cap = rng.randint(1, 40)
    ring = H._Ring(cap)
    cols = [_col(100 * i, rng.randint(0, 30)) for i in range(rng.randint(0, 2 * cap))]
    ring.extend(cols)
    held = cols[-cap:] if cols else []
    for as_json, per_col, per_row in ((False, 48, 16), (True, 320, 48)):
        frames, nbytes = rng.randint(0, 2 * cap + 2), rng.randint(0, 4_000)
        want = H.snapshot_columns(held, window_seconds=900, bucket_ms=100, queue_bytes=nbytes,
                                queue_frames=frames, structured=as_json)  # fmt: skip
        limit = H._limit(window_seconds=900, bucket_ms=100, queue_frames=frames)
        got = ring.newest_fitting(per_col, per_row, limit, nbytes // 2)
        assert [ring[i] for i in got] == want
        assert ring.times(got) == [c.ts_ms for c in want]
        assert ring.total_rows(got) == sum(c.rows for c in want)


def test_snapshot_cap_window_900s_at_100ms_holds_at_most_2000_columns() -> None:
    """Gherkin "Snapshot cap": `window_seconds` 900 at 100 ms is 9 000 buckets; the snapshot holds
    at most the 2 000 most recent (older ones are REST's), when no other G-03 bound binds."""
    got = H.snapshot_columns(_ring(2_100, rows=1), window_seconds=900, bucket_ms=100,
                             queue_bytes=10**9, queue_frames=10**9)  # fmt: skip
    assert len(got) == HEATMAP_SNAPSHOT_MAX_COLUMNS
    assert got[0].ts_ms == T0 + 100 * 100 and got[-1].ts_ms == T0 + 100 * 2_099


@pytest.mark.parametrize(
    ("window_seconds", "queue_bytes", "queue_frames", "want"),
    [
        pytest.param(10, 10**9, 10**9, 100, id="window_seconds"),
        pytest.param(900, 8_388_608, 2_000, 650, id="bytes-at-the-default-budget"),
        pytest.param(900, 4_194_304, 256, 128, id="frames-at-the-floors"),
        pytest.param(900, 10**9, 10**9, 2_000, id="column-cap"),
    ],
)
def test_snapshot_bound_is_the_fewest_columns_of_four_limits(
    window_seconds: int, queue_bytes: int, queue_frames: int, want: int
) -> None:
    """G-03 (23 §6.1): each limit binds in its own case; at 400 rows a column is 6 448 B, so half
    the default 8 MiB holds 650 (§6.1's figure) and half the floors' 256 frames holds 128."""
    got = H.snapshot_columns(_ring(2_100), window_seconds=window_seconds, bucket_ms=100,
                             queue_bytes=queue_bytes, queue_frames=queue_frames)  # fmt: skip
    assert len(got) == want
    assert got[-1].ts_ms == T0 + 100 * 2_099  # always the newest


async def test_snapshot_build_is_kind_6_only_when_every_column_is_complete() -> None:
    w = World()
    await live(w)
    sub = w.hold(HeatmapSpec(SYM, time_bucket_ms=100))
    for k in range(1, 4):
        w.at(k * COLUMN_MS)
    body = w.topic.build(sub)
    assert isinstance(body, SnapshotBody)
    assert len(body.structured["columns"]) == len(body.parts) == 3
    assert (body.price_scale, body.qty_scale, body.estimated) == (1, 3, False)
    for col, p in zip(body.structured["columns"], body.parts, strict=True):
        assert structured(decode(encode(p)))["columns"][0]["t_ms"] == col["t_ms"]
    w.at(650)  # the deadlines at 400 and 500 missed: columns below their native count
    body = w.topic.build(sub)
    assert isinstance(body, SnapshotBody)
    assert body.parts == () and len(body.structured["columns"]) == 6
    sub.effective["encoding"] = "structured"
    again = w.topic.build(sub)
    assert isinstance(again, SnapshotBody) and again.parts == ()
    assert w.topic.generation(sub) == 6 and w.topic.continuity(sub, None) is False


async def test_snapshot_waits_for_the_instrument_steps_then_flushes() -> None:
    w = World()
    del w.steps[SYM]
    await live(w)
    sub = w.hold(HeatmapSpec(SYM, time_bucket_ms=100))
    sub.snapshot_pending = True
    assert w.topic.build(sub) is None and w.topic.generation(sub) == 0
    w.at(100)
    assert w.hub.frames == []  # nothing goes out before the steps are known
    w.steps[SYM] = STEPS[SYM]
    w.at(150)
    assert w.hub.flushed == [sub] and w.topic.build(sub) is not None
    assert w.topic.build(Sub(None)) is None


# -- G-02: the spec caps --------------------------------------------------------------------------


def test_spec_caps_four_per_symbol_and_one_spec_shared_counts_once() -> None:
    w = World()
    specs = [HeatmapSpec(SYM, price_grouping=g) for g in (1, 2, 5, 10)]
    for i, spec in enumerate(specs):
        w.topic.hold(f"c{i}", spec)
    w.topic.hold("c9", specs[0])  # the same spec: no new state
    with pytest.raises(HeatmapSpecCapError, match="4 heatmap specs per symbol"):
        w.topic.hold("c5", HeatmapSpec(SYM, price_grouping=20))
    lease = w.topic.hold("c6", HeatmapSpec(SYM, price_grouping=1, depth=200))
    w.topic.release(lease)
    w.topic.release(HeatmapLease("c0", specs[0]))
    w.topic.release(HeatmapLease("c9", specs[0]))  # its last lease: the spec is released
    w.topic.hold("c5", HeatmapSpec(SYM, price_grouping=20))


def test_spec_caps_thirty_two_per_server() -> None:
    w = World()
    for i in range(32):
        w.topic.hold(f"c{i}", HeatmapSpec(f"S{i // 4}USDT", price_grouping=1 + i % 4))
    with pytest.raises(HeatmapSpecCapError, match="At most 32 heatmap specs"):
        w.topic.hold("x", HeatmapSpec("ZZUSDT"))


def test_a_retune_checks_the_caps_with_its_own_spec_freed() -> None:
    w = World()
    leases = [w.topic.hold(f"c{g}", HeatmapSpec(SYM, price_grouping=g)) for g in (1, 2, 5, 10)]
    moved = w.topic.retune(leases[3], HeatmapSpec(SYM, price_grouping=20))  # 10's last lease
    assert moved.spec.price_grouping == 20
    w.topic.hold("x", HeatmapSpec(SYM, price_grouping=2))  # an existing spec: always allowed
    with pytest.raises(HeatmapSpecCapError):
        w.topic.check_retune(w.topic.hold("y", HeatmapSpec(SYM, price_grouping=1)),
                             HeatmapSpec(SYM, price_grouping=50))  # fmt: skip
    assert w.topic.retune(moved, moved.spec) is moved


# -- D-row: re-bucketing on a `price_grouping` change ---------------------------------------------


async def test_a_price_grouping_change_rebuckets_the_held_columns() -> None:
    """D-row (24 §6.3): the new spec takes the old one's columns re-bucketed on the coarser step
    (1 divides 5), each row summed into its row and nothing lost; the re-bucketing runs in the
    loop's turns, never in the `ctl`, and the subscription stays pending until it is done, then
    is flushed. A step that the held one does not divide starts empty (older: REST, E21-T03)."""
    w = World()
    b, a = ladder()
    await live(w, [*b, lvl(9_000, 4)], a)
    sub = w.hold(HeatmapSpec(SYM, time_bucket_ms=100))
    for k in range(1, 6):
        w.at(k * COLUMN_MS)
    assert sub.heatmap_lease is not None
    lease = w.topic.retune(
        sub.heatmap_lease, HeatmapSpec(SYM, price_grouping=5, time_bucket_ms=100)
    )
    sub.heatmap_lease, sub.snapshot_pending = lease, True
    st = w.topic._symbols[SYM]
    assert list(st.specs) == [lease.spec]
    assert ring(w, lease.spec) == [] and w.topic.build(sub) is None  # queued, not re-bucketed
    w.at(520)  # one turn: the seed and the flush
    assert w.hub.flushed == [sub]
    body = w.topic.build(sub)
    assert isinstance(body, SnapshotBody) and len(body.structured["columns"]) == 5
    cols = ring(w, lease.spec)
    assert len(cols) == 5 and all(c.price_step_ticks == 5 for c in cols)
    assert [c.ts_ms for c in cols] == sorted(c.ts_ms for c in cols)
    for c in cols:
        assert c.price_origin_ticks % 5 == 0
        assert sum(c.bid_sizes) + c.off_window_bid_qty == pytest.approx(54.0)
    odd = w.topic.retune(lease, HeatmapSpec(SYM, price_grouping=7, time_bucket_ms=100))
    assert len(st.specs[odd.spec].ring) == 0 and st.specs[odd.spec].seed is None
    with pytest.raises(ValueError, match="divide"):
        H.rebucket(cols[0], 7)


async def test_a_seed_runs_in_slices_and_never_in_the_sub() -> None:
    """A 2 000-column donor is re-bucketed a slice per turn (`seed_turn_s`), the
    newest first, capped at the G-03 frame bound; `hold` itself only queues it."""
    w = World(queue_frames=4_000)
    spec = HeatmapSpec(SYM, time_bucket_ms=100)
    w.hold(spec)
    st = w.topic._symbols[SYM]
    st.specs[spec].ring.extend(_col(100 * i, 512) for i in range(HEATMAP_SNAPSHOT_MAX_COLUMNS))
    w.topic._seed_turn_s = 0.0  # one column a turn
    new = HeatmapSpec(SYM, price_grouping=2, time_bucket_ms=100)
    w.hold(new, consumer="c2")
    state = st.specs[new]
    assert state.seed is not None and len(state.seed) == HEATMAP_SNAPSHOT_MAX_COLUMNS
    assert len(state.ring) == 0
    assert w.topic._seed_turn() == 1 and state.ring[0].ts_ms == T0 + 100 * 1_999
    assert w.topic.next_due() == w.now  # a queued seed makes the loop turn at once


# -- the kind-6 part (23 §3.4, 24 §6.5) -----------------------------------------------------------


async def test_a_columns_kind_6_part_decodes_to_its_structured_column() -> None:
    """The producer's part and its §14.5 twin agree: `price_min` and `price_step` exact at the
    tick's scale, sizes rounded half to even at the qty step's (2.0625 -> 2.062 at 3 places)."""
    w = World()
    eng = await live(w)
    w.hold(HeatmapSpec(SYM, time_bucket_ms=100))
    await eng.on_event(delta(11, 10, [lvl(9_995, "2.0625")]))
    w.at(0)
    w.at(100)
    [(_, body, p)] = w.hub.frames
    [col] = body["columns"]
    [back] = structured(decode(encode(p)))["columns"]
    assert (back["t_ms"], back["price_min"], back["price_step"]) == (
        col["t_ms"], col["price_min"], "0.1",
    )  # fmt: skip
    row = int((Decimal(col["price_min"]) * 10 - 9_995) * -1)
    assert col["bids"][row] == 2.0625 and back["bids"][row] == 2.062
    assert back["asks"] == [round(x, 3) for x in col["asks"]]


def test_scaled_size_rounds_half_to_even_and_refuses_what_is_no_u64() -> None:
    assert [H.scaled_size(x, 3) for x in (0.0625, 0.1875, 0.0, 1e-9)] == [62, 188, 0, 0]
    assert H.scaled_size(-1.0, 0) is None
    assert H.scaled_size(float("nan"), 0) is None and H.scaled_size(float("inf"), 0) is None
    assert H.scaled_size(2.0**64, 0) is None
    assert H.places(Decimal("0.10")) == 1 and H.places(Decimal("5")) == 0


def test_a_column_that_does_not_fit_kind_6_leaves_structured() -> None:
    w = World()
    big = _col(0, 2)
    huge = replace(big, bid_sizes=array("d", [2.0**70, 1.0]))
    assert w.topic._frame(huge, STEPS[SYM]) is None
    far = replace(big, price_origin_ticks=2**63)
    assert w.topic._frame(far, STEPS[SYM]) is None


# -- the wire column, normalisation ---------------------------------------------------------------


def test_wire_column_carries_samples_and_off_window_totals_only_when_they_say_something() -> None:
    full = H.wire_column(_col(0, 2), Decimal("0.1"))
    assert set(full) == {"t_ms", "price_min", "price_step", "bids", "asks", "complete"}
    part = H.wire_column(_col(0, 2, samples=0, off=1.5), Decimal("0.1"))
    assert (part["samples"], part["off_window_bid_qty"]) == (0, 1.5)
    assert full["price_min"] == "1000.0" and full["price_step"] == "0.1"


def test_a_column_without_a_sample_is_empty_and_keeps_its_origin() -> None:
    col = H.window_column(ts_ms=T0, bucket_ms=100, step=5, bids={}, asks={}, best_bid=None,
                          best_ask=None, estimated=False, samples=0, expected=1,
                          origin_hint=1_003)  # fmt: skip
    assert (col.rows, col.price_origin_ticks, col.full) == (0, 1_000, False)
    low = H.window_column(ts_ms=T0, bucket_ms=100, step=1, bids={}, asks={}, best_bid=10,
                          best_ask=11, estimated=False, samples=0, expected=1)  # fmt: skip
    assert low.price_origin_ticks == 0  # an empty column never sits below price 0
    assert H.native_count(T0, T0 + 250) == 2 and H.native_count(T0 + 250, T0 + 500) == 3


# -- heatmap_cells: the store hand-off (21 §4.12, 24 §6.5) ----------------------------------------


async def test_native_columns_reach_the_store_populated_rows_only_never_an_empty_column() -> None:
    store = Store()
    w = World(store=store)
    await live(w)
    w.hold(HeatmapSpec(SYM, time_bucket_ms=1000))
    w.topic.start()
    try:
        for k in range(1, 4):
            w.at(k * COLUMN_MS)
        w.at(650)  # 400 and 500 missed: no row is stored for them
        await w.topic.stop()
    finally:
        await w.topic.stop()
    assert store.closed
    assert [ts // 1000 - T0 for _, ts, _, _ in store.columns] == [0, 100, 200, 500]
    symbol, _, cells, kw = store.columns[0]
    assert symbol == SYM and len(cells) == 100 and all(b or a for _, b, a in cells)
    assert kw == {"estimated": False, "samples": 1, "off_window_bid_qty": 0.0,
                  "off_window_ask_qty": 0.0}  # fmt: skip
    assert cells[0][0] == pytest.approx(995.1)  # 9 951 ticks of 0.1, a `DOUBLE` of the Decimal


def test_a_size_that_is_not_finite_is_never_queued_and_counts_as_a_fault() -> None:
    store = Store()
    w = World(store=store)
    bad = replace(_col(0, 3), bid_sizes=array("d", [1.0, float("nan"), -1.0]))
    before = REGISTRY.get_sample_value("heatmap_cell_faults_total") or 0.0
    w.topic._native(SYM, bad)
    [queued] = w.topic._stored
    assert len(queued.cells) == 1
    w.topic._native(SYM, replace(_col(0, 1), off_window_bid_qty=float("inf")))
    assert len(w.topic._stored) == 1
    assert (REGISTRY.get_sample_value("heatmap_cell_faults_total") or 0.0) - before == 3


def test_the_store_queue_is_bounded_by_cells_and_sheds_its_oldest() -> None:
    """The bound counts cells, not columns (512 full columns, ~18 MiB of tuples)."""
    w = World(store=Store())
    full = H.STORE_CELLS_MAX // 512
    for i in range(full + 5):
        w.topic._native(SYM, _col(100 * i, 512))
    assert len(w.topic._stored) == full and w.topic._stored_cells == H.STORE_CELLS_MAX
    assert w.topic._stored[0].ts_us == (T0 + 500) * 1000
    assert w.topic._shed == 5
    w.at(0)
    assert w.topic._shed == 0


async def test_a_store_write_that_fails_loses_that_column_only() -> None:
    class Failing(Store):
        async def write_column(self, symbol: str, ts_us: int, cells: Any, **kw: Any) -> None:
            if ts_us == T0 * 1000:
                raise OSError("questdb down")
            await super().write_column(symbol, ts_us, cells, **kw)

    store = Failing()
    w = World(store=store)
    w.topic.start()
    w.topic._native(SYM, _col(0, 1))
    w.topic._native(SYM, _col(100, 1))
    await w.topic.stop()
    assert [ts // 1000 - T0 for _, ts, _, _ in store.columns] == [100]


# -- the bus and the loop -------------------------------------------------------------------------


async def test_offer_marks_only_held_symbols_and_the_overflow_marker_marks_all() -> None:
    w = World()
    eng = await live(w)
    w.hold(HeatmapSpec(SYM, time_bucket_ms=100))
    w.topic._dirty.clear()
    w.topic.offer(snap(1, *ladder()).model_copy(update={"symbol": "XRPUSDT"}))
    assert w.topic._dirty == set()
    w.topic.offer(StreamInvalidated(topic="live.md.BTCUSDT.book", ts_event=0))
    assert w.topic._dirty == {SYM}
    assert w.topic.next_due() == T0 + COLUMN_MS
    assert eng.phase is BookPhase.LIVE
    assert World().topic.next_due() is None


async def test_the_loop_publishes_as_its_clock_passes_deadlines_and_stops() -> None:
    """The owned loop on a clock that moves 50 ms a read, so no turn waits on wall time."""
    calls = itertools.count()
    bus = Bus()
    two = asyncio.Event()

    class Waking(Hub):
        def publish(self, ch: str, body: Mapping[str, Any] | None = None, **kw: Any) -> int:
            sent = super().publish(ch, body, **kw)
            if len(self.frames) >= 2:
                two.set()
            return sent

    hub = Waking()
    topic = HeatmapTopic(hub, engine=lambda _s: None, steps=STEPS.get, part=part,
                         body=SnapshotBody, bus=bus, env="live", queue_bytes=QUEUE_BYTES,
                         queue_frames=QUEUE_FRAMES,
                         clock_ms=lambda: T0 + 50.0 * next(calls))  # fmt: skip
    hub.subs.append(Sub(topic.hold("c", HeatmapSpec(SYM, time_bucket_ms=100))))
    topic.start()
    assert topic.pump() == 0
    await asyncio.wait_for(two.wait(), timeout=5)
    await topic.stop()
    assert all(body["columns"][0]["samples"] == 0 for _, body, _ in hub.frames)  # no book


# -- a depth-500 spec demands the deep tier --------------------------------------------------------


class Demand:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def acquire_depth(self, consumer: str, symbol: str, depth: int) -> None:
        self.calls.append(("acquire", consumer, symbol, str(depth)))

    def release(self, consumer: str, symbol: str) -> None:
        self.calls.append(("release", consumer, symbol))


async def test_a_depth_500_spec_demands_the_deep_tier_and_waits_for_its_swap() -> None:
    """A depth-500 spec demands the symbol's 500 tier once (as `book.X.500`
    does), integrates nothing and stays pending while the tier is 200, and is flushed and served
    once the 500 tier is live; its last lease lets the demand go."""
    w = World()
    demand = Demand()
    w.topic._demand = demand
    await live(w)  # the 200 tier
    sub = w.hold(HeatmapSpec(SYM, depth=500, time_bucket_ms=100))
    sub.snapshot_pending = True
    w.hold(HeatmapSpec(SYM, depth=500, time_bucket_ms=500), consumer="c2")  # one demand only
    assert demand.calls == [("acquire", H.DEEP_CONSUMER, SYM, "500")]
    w.at(100)
    assert w.topic.build(sub) is None and w.hub.flushed == []
    [col] = ring(w, HeatmapSpec(SYM, depth=500, time_bucket_ms=100))
    assert (col.samples, col.rows) == (0, 0)  # never a 200-level column under depth 500
    deep = await w.engine(depth=500)  # the swap: a new engine at the 500 tier goes live
    b, a = ladder(n=300)
    await deep.on_event(snap(10, b, a, depth=500))
    w.at(150)
    w.at(200)
    assert w.hub.flushed == [sub]
    body = w.topic.build(sub)
    assert isinstance(body, SnapshotBody) and body.structured["depth"] == 500
    last = ring(w, HeatmapSpec(SYM, depth=500, time_bucket_ms=100))[-1]
    assert sum(last.bid_sizes) + last.off_window_bid_qty == pytest.approx(300 * 0.5)
    assert sub.heatmap_lease is not None
    w.topic.release(sub.heatmap_lease)
    w.topic.release(HeatmapLease("c2", HeatmapSpec(SYM, depth=500, time_bucket_ms=500)))
    assert demand.calls[-1] == ("release", H.DEEP_CONSUMER, SYM)


async def test_a_binary_snapshot_builds_its_parts_a_step_each_and_keeps_none() -> None:
    """The ring keeps each column's sizes only; a snapshot builds its parts a column per
    step (`build_steps`, spread across loop turns by the gateway), equal to the parts its
    columns' `d` frames carried."""
    w = World()
    await live(w)
    sub = w.hold(HeatmapSpec(SYM, time_bucket_ms=100))
    for k in range(1, 4):
        w.at(k * COLUMN_MS)
    published = [p for _, _, p in w.hub.frames]
    steps = w.topic.build_steps(sub)
    taken = 0
    while True:
        try:
            next(steps)
        except StopIteration as done:
            body = done.value
            break
        taken += 1
    assert taken == 3 and isinstance(body, SnapshotBody)
    assert list(body.parts) == published
    ring = w.topic._symbols[SYM].specs[HeatmapSpec(SYM, time_bucket_ms=100)].ring
    assert isinstance(ring, H._Ring) and not hasattr(ring, "__dict__")  # nothing derived is kept


async def test_a_new_spec_closes_what_is_due_before_integrating_the_others() -> None:
    """`hold` of a second spec closes the first spec's due buckets first, so none of
    its buckets integrates time past its own end."""
    w = World()
    await live(w)
    first = HeatmapSpec(SYM, time_bucket_ms=100)
    w.hold(first)
    w.now = T0 + 150  # no turn ran at 100
    w.hold(HeatmapSpec(SYM, time_bucket_ms=500), consumer="c2")
    [col] = ring(w, first)
    assert col.ts_ms == T0 and w.topic._symbols[SYM].specs[first].acc.t == T0 + 150


async def test_a_structured_snapshot_counts_its_json_bytes_at_the_byte_bound() -> None:
    """G-03 (23 §6.1, §16.2): a structured subscriber's columns are counted at their JSON's
    bound, so the snapshot's wire bytes stay within half the queue's bytes; a binary one's at
    48 + 16 x rows. The bound is tight: real columns use most of it."""
    w = World()
    await live(w)
    spec = HeatmapSpec(SYM, time_bucket_ms=100)
    sub = w.hold(spec)
    state = w.topic._symbols[SYM].specs[spec]
    sizes = [0.1234567891234567 * (i + 1) + 7e-9 for i in range(ROWS)]  # full float reprs
    for i in range(2_000):
        col = replace(_col(100 * i, ROWS), bid_sizes=array("d", sizes), ask_sizes=array("d", sizes))
        state.ring.append(col)
    sub.effective = {"encoding": "structured", "window_seconds": 900}
    body = w.topic.build(sub)
    assert isinstance(body, SnapshotBody)
    columns = body.structured["columns"]
    per = H.STRUCTURED_COLUMN_BYTES + H.STRUCTURED_ROW_BYTES * ROWS
    assert len(columns) == (QUEUE_BYTES // 2) // per
    text = json.dumps(columns, separators=(",", ":"))
    assert len(text) <= QUEUE_BYTES // 2
    assert all(len(json.dumps(c, separators=(",", ":"))) > 0.7 * per for c in columns)
    sub.effective = {"encoding": "binary", "window_seconds": 900}
    binary = w.topic.build(sub)
    assert isinstance(binary, SnapshotBody)
    assert len(binary.parts) == (QUEUE_BYTES // 2) // (48 + 16 * ROWS)


def test_snapshot_columns_counts_a_structured_column_at_its_json_bound() -> None:
    ring = _ring(2_000, rows=ROWS)
    got = H.snapshot_columns(ring, window_seconds=900, bucket_ms=100, queue_bytes=QUEUE_BYTES,
                             queue_frames=10**9, structured=True)  # fmt: skip
    assert len(got) == (QUEUE_BYTES // 2) // ring[0].json_bytes


async def test_a_column_closing_mid_snapshot_follows_it_as_a_d(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """23 §7.1: a snapshot spread across loop turns holds the columns of its first
    turn; a column that closes meanwhile follows it as a `d` (`catch_up`), never lost between."""
    from candleviewer.ws.permissions import Subscription
    from candleviewer.ws.sequencing import SnapshotCache, TopicEmitter
    from candleviewer.ws.topics import effective_options, parse_topic

    w = World()
    await live(w)
    spec = HeatmapSpec(SYM, time_bucket_ms=100)
    lease = w.hold(spec).heatmap_lease
    for k in range(1, 6):
        w.at(k * COLUMN_MS)
    out: list[dict[str, Any]] = []
    emitter = TopicEmitter(out.append, connection_id="t", wall_ms=lambda: T0, clock=lambda: 0.0,
                           source=cast(Any, w.topic), cache=SnapshotCache())  # fmt: skip
    emitter.turn_s = 0.0
    parsed = parse_topic(f"heatmap.{SYM}")
    opts = {"encoding": "structured", "window_seconds": 900}
    sub = Subscription("s1", parsed, opts, effective_options(parsed, opts))
    sub.heatmap_lease = lease
    assert emitter.snapshot(sub, "initial") and out == []
    await asyncio.sleep(0)
    w.at(6 * COLUMN_MS)  # a column closes while the snapshot is under way
    for _ in range(10_000):
        await asyncio.sleep(0)
        if not emitter._jobs:  # the snapshot, then its catch-up, a `d` a step
            break
    snap, *rest = out
    held = [c["t_ms"] - T0 for c in snap["p"]["columns"]]
    assert held == [k * COLUMN_MS for k in range(5)]
    assert [(f["t"], f["s"], f["p"]["columns"][0]["t_ms"] - T0) for f in rest] == [("d", 2, 500)]


def _full(w: World, spec: HeatmapSpec, rows: int) -> H._SpecState:
    state = w.topic._symbols[SYM].specs[spec]
    for i in range(HEATMAP_SNAPSHOT_MAX_COLUMNS):
        state.ring.append(_col(100 * i, rows))
        state.version += 1
    return state


def _close_one(state: H._SpecState, rows: int) -> int:
    """A column closing, as `_close` keeps the ring: appended, the generation moved."""
    t = state.ring[-1].ts_ms + 100 - T0
    state.ring.append(_col(t, rows))
    state.version += 1
    return T0 + t


async def test_a_spread_snapshot_at_capacity_is_the_copy_of_its_first_step() -> None:
    """At capacity every close moves the ring's head; a snapshot spread across steps
    reads a copy taken at its first, so its parts and its `t_ms` agree, with no gap and no
    duplicate, and `catch_up` sends exactly the columns closed after the copy."""
    w = World()
    await live(w)
    spec = HeatmapSpec(SYM, time_bucket_ms=100)
    sub = w.hold(spec)
    state = _full(w, spec, ROWS)
    gen0 = w.topic.generation(sub)
    steps = w.topic.build_steps(sub)
    closed: list[int] = []
    while True:
        try:
            next(steps)
        except StopIteration as done:
            body = done.value
            break
        closed.append(_close_one(state, ROWS))  # a close between every two steps
    assert isinstance(body, SnapshotBody) and len(closed) > 100
    times = [c["t_ms"] for c in body.structured["columns"]]
    assert [p.ts_base_ms for p in body.parts] == times
    newest = T0 + 100 * (HEATMAP_SNAPSHOT_MAX_COLUMNS - 1)
    assert times == list(range(newest - 100 * (len(times) - 1), newest + 1, 100))
    missed = w.topic.catch_up(sub, gen0)
    assert missed is not None
    items = list(missed)  # binary: the part only, built as read
    assert all(i is not None and i[1] is not None for i in items)
    assert [i[1].ts_base_ms for i in items if i is not None] == closed


async def test_many_spread_snapshots_over_a_moving_spec_all_end_and_none_restarts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """32 concurrent snapshots of one full spec while columns keep closing (more than
    the old 64-column catch-up bound) all end, none is taken again, and each is followed by
    exactly the columns closed after its copy."""
    from candleviewer.ws.permissions import Subscription
    from candleviewer.ws.sequencing import SnapshotCache, TopicEmitter
    from candleviewer.ws.topics import effective_options, parse_topic

    w = World(queue_frames=200)  # 100-column snapshots: the test stays fast
    await live(w)
    spec = HeatmapSpec(SYM, time_bucket_ms=100)
    lease = w.hold(spec).heatmap_lease
    state = _full(w, spec, 64)
    restarts: list[str] = []
    real = TopicEmitter._restart

    def counted(self: Any, sub: Any) -> None:
        restarts.append(sub.sub_id)
        real(self, sub)

    monkeypatch.setattr(TopicEmitter, "_restart", counted)
    parsed = parse_topic(f"heatmap.{SYM}")
    opts = {"encoding": "binary", "window_seconds": 900}
    emitters: list[tuple[TopicEmitter, list[dict[str, Any]]]] = []
    for n in range(32):
        out: list[dict[str, Any]] = []
        emitter = TopicEmitter(out.append, connection_id=f"c{n}", wall_ms=lambda: T0,
                               clock=lambda: 0.0, source=cast(Any, w.topic),
                               cache=SnapshotCache())  # fmt: skip
        emitter.turn_s, emitter.step_s = 0.0, 0.0  # one step a turn, every job: the worst case
        sub = Subscription(f"s{n}", parsed, opts, effective_options(parsed, opts))
        sub.heatmap_lease = lease
        assert emitter.snapshot(sub, "initial")
        emitters.append((emitter, out))
    closes = 0
    for turn in range(1_000_000):
        if not any(e._jobs for e, _ in emitters):
            break
        await asyncio.sleep(0)
        if turn % 10 == 0 and closes < 300:
            _close_one(state, 64)
            closes += 1
    assert not any(e._jobs for e, _ in emitters) and not restarts and closes > 64
    for _, out in emitters:
        snaps = [f for f in out if f["t"] == "snap" and f["s"] is not None]
        assert len(snaps) == 1


async def test_a_catch_up_of_300_columns_runs_a_d_a_step_within_half_the_queue() -> None:
    """23 §6.1, §7.1, G-03: 300 columns close while a full binary snapshot is under
    way. The snapshot leaves out its oldest columns so it and the 300 `d` frames after it cost at
    most half the queue's bytes at G-03 sizes (the encoded total stays under the whole queue: no
    `slow_consumer`); each `d` is its own step (its CPU, a `d`'s build, is the bench's
    `catch_up_step_cpu_max_ms`); the `d` frames follow the snapshot's last column with no gap,
    no duplicate and consecutive `s`."""
    from candleviewer.ws.outbound import json_payload
    from candleviewer.ws.permissions import Subscription
    from candleviewer.ws.sequencing import SnapshotCache, TopicEmitter
    from candleviewer.ws.topics import effective_options, parse_topic

    w = World()
    await live(w)
    spec = HeatmapSpec(SYM, time_bucket_ms=100)
    lease = w.hold(spec).heatmap_lease
    state = _full(w, spec, ROWS)
    out: list[dict[str, Any]] = []
    encoded: list[int] = []

    def queued(frame: dict[str, Any], payload: str | bytes, _r: float | None) -> None:
        out.append(frame)
        encoded.append(len(payload))

    emitter = TopicEmitter(out.append, connection_id="t", wall_ms=lambda: T0, clock=lambda: 0.0,
                           source=cast(Any, w.topic), cache=SnapshotCache())  # fmt: skip
    emitter.push_encoded, emitter.encode_payload, emitter.wire = queued, json_payload, "json"
    emitter.step_s = 0.0  # a job step is one of its own steps: a `d` each, nothing batched
    parsed = parse_topic(f"heatmap.{SYM}")
    opts = {"encoding": "binary", "window_seconds": 900}
    sub = Subscription("s1", parsed, opts, effective_options(parsed, opts))
    sub.heatmap_lease = lease
    emitted: list[int] = []  # the `d` frames each job step queued
    real = TopicEmitter._step

    def counted(self: TopicEmitter, job: Any) -> bool:
        before = sum(f["t"] == "d" for f in out)
        try:
            return real(self, job)
        finally:
            emitted.append(sum(f["t"] == "d" for f in out) - before)

    TopicEmitter._step = counted  # type: ignore[method-assign]  # restored below
    try:
        assert emitter.snapshot(sub, "initial")
        closed: list[int] = []
        for _ in range(1_000_000):
            if not emitter._jobs:
                break
            if sub.snapshot_pending and len(closed) < 300:
                closed += [_close_one(state, ROWS) for _ in range(5)]
            await asyncio.sleep(0)
    finally:
        TopicEmitter._step = real  # type: ignore[method-assign]
    assert len(closed) == 300 and not emitter._jobs
    snaps = [f for f in out if f["t"] == "snap"]
    deltas = [f for f in out if f["t"] == "d"]
    assert len(deltas) == 300 and out[: len(snaps)] == snaps  # the `d` frames follow the snapshot
    assert [f["s"] for f in deltas] == list(range(2, 302))
    held = [decode(base64.b64decode(f["p"])).ts_base_ms for f in snaps]
    ts = [decode(base64.b64decode(f["p"])).ts_base_ms for f in deltas]
    assert ts == closed and held[-1] + 100 == ts[0]
    assert held == list(range(held[0], held[-1] + 1, 100))
    per = H.COLUMN_FRAME_BYTES + H.ROW_BYTES * ROWS
    assert (len(snaps) + len(deltas)) * per <= QUEUE_BYTES // 2 < (len(snaps) + 301) * per
    total = sum(encoded) + sum(len(json_payload(f)) for f in out[len(encoded) :])
    assert total <= QUEUE_BYTES  # nothing drained, and still no `slow_consumer` (§8.4)
    assert max(emitted) == 1 and sum(emitted) == 300  # a `d` a step, the writer between
