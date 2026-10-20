"""Session-anchored instances (`vwap`, `cvd`) are never primed from inside a session (E13-T02,
#426; 24-internal-schemas §7.4; review of the WS delivery: a fresh instance on a session longer
than the store's tail served a partial session's value, with no error).

Most rows run one UTC day of 1 300 one-minute bars from 00:00 (the anchor): the series store holds
the newest 1 000 (from index 300), and a stored-bar read serves the day. A fresh instance reads back
to the session start, through an admission, a re-prime and a `ctl` swap, and serves what an
instance that folded the whole day serves, bit for bit. When it cannot read that far it serves
`None` (`warmup`) until the next session, never a partial session's value."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from decimal import Decimal
from typing import Any, Final

import pytest

from candleviewer.bars.models import Bar, BarSpec
from candleviewer.bars.reader import BarTail
from candleviewer.bars.series import BarSeries
from candleviewer.bars.series_store import Hold, SeriesStore
from candleviewer.orderflow.errors import RecomputeRefusedError
from candleviewer.orderflow.indicators.engine import (
    Available,
    IndicatorEngine,
    Point,
    Requested,
    resolve_instances,
)
from candleviewer.orderflow.indicators.kernels import compute
from candleviewer.orderflow.indicators.limits import MAX_FILL_SLOTS, MAX_WINDOW_BARS
from candleviewer.orderflow.indicators.types import BarInput, KernelContext, Unavailable, bar_input
from tests.unit.orderflow.indicators._engine import (
    EMA3,
    M1,
    SYM,
    T0,
    T5,
    Listener,
    admit,
    bar,
    close,
)

GEN: Final = 4
DAY: Final = 1_300  # one-minute bars from 00:00 UTC, past the store's 1 000-bar tail
NEXT_SESSION: Final = 1_440  # the slot of the next day's 00:00
ANCHORED: Final[list[list[dict[str, Any]]]] = [
    [{"indicator": "vwap"}],
    [{"indicator": "cvd"}],
    [{"indicator": "cvd", "params": {"anchor": "utc_day"}}],
]


def _bar(i: int, *, slot: int | None = None, spec: BarSpec = M1) -> Bar:
    """Bar `i` of the day: prices, volume and delta that move, so each session sum is its own."""
    c = 100.0 + (i % 11) * 0.5 - (i % 3) * 0.25
    return bar(
        i, c, spec=spec, slot=slot, high=c + 0.75, low=c - 0.5, volume=1.0 + i % 5,
        delta=float(i % 7) - 3.0,
    )  # fmt: skip


class _Tail:
    """The store's hydration read: the newest `limit` stored bars, all of generation `GEN`."""

    def __init__(self, bars: Sequence[Bar]) -> None:
        self.bars = list(bars)

    async def __call__(self, symbol: str, spec: BarSpec, limit: int) -> BarTail:
        newest = self.bars[-limit:]
        return BarTail([(GEN, b) for b in newest], since_us=0, fetched=len(newest))


class _Stored:
    """`HistoryRead` over every stored bar, by open time: each call's window, held by `go`, raising
    `fail` when set."""

    def __init__(self, bars: Sequence[Bar]) -> None:
        self.bars = list(bars)
        self.calls: list[tuple[int, int]] = []
        self.fail: Exception | None = None
        self.go = asyncio.Event()
        self.go.set()

    async def __call__(
        self, symbol: str, spec: BarSpec, generation: int, start_us: int, end_us: int
    ) -> list[tuple[int, BarInput]]:
        self.calls.append((start_us, end_us))
        await self.go.wait()
        if self.fail is not None:
            raise self.fail
        return [(b.index, bar_input(b)) for b in self.bars if start_us <= b.open_time < end_us]


async def _day(**kw: Any) -> tuple[list[Bar], SeriesStore, IndicatorEngine, _Stored, Hold]:
    """The day stored, the store holding its newest 1 000 bars, and an engine reading the rest."""
    day = [_bar(i) for i in range(DAY)]
    store = SeriesStore(_Tail(day))
    hold = await store.ensure(SYM, M1)
    stored = _Stored(day)
    return day, store, IndicatorEngine(store, history=stored, **kw), stored, hold


async def _done(engine: IndicatorEngine) -> None:
    await asyncio.gather(*list(engine._tasks))


def _continuous(r: Requested, bars: Sequence[Bar], spec: BarSpec = M1) -> list[tuple[str, ...]]:
    """What an instance that folded every bar from the generation's first serves, one row per
    real bar, as reprs (bit for bit)."""
    dense = BarSeries(spec, list(bars)).densify() if spec.kind == "time" else list(bars)
    rows = compute(
        r.definition.id, [bar_input(b) for b in dense], r.params, source=r.kernel.sources[0],
        context=KernelContext(),
    )  # fmt: skip
    return [tuple(map(repr, row)) for row, b in zip(rows, dense, strict=True) if not b.synthetic]


def _reprs(points: Sequence[Point]) -> list[tuple[str, ...]]:
    return [tuple(map(repr, p.values)) for p in points]


def _served(engine: IndicatorEngine, r: Requested) -> list[tuple[str, ...]]:
    batch = engine.snapshot(SYM, r.key, 1_000)
    assert batch is not None
    assert [p.index for p in batch.points] == list(range(DAY - 1_000, DAY))
    return _reprs(batch.points)


@pytest.mark.parametrize("raw", ANCHORED, ids=["vwap", "cvd", "cvd-utc-day"])
async def test_a_fresh_session_instance_reads_back_to_its_session_start(
    raw: list[dict[str, Any]],
) -> None:
    """The review's probe: 500 bars of history are in the store, but the session began 300 bars
    before its tail, so the instance reads from 00:00 and serves the whole session's values."""
    day, _store, engine, stored, _hold = await _day()
    (r,) = admit(engine, raw, history=500)
    await _done(engine)
    assert stored.calls == [(T0, day[-1].open_time + 1)]
    assert _served(engine, r) == _continuous(r, day)[DAY - 1_000 :]
    got = engine.read(SYM, r.key)
    assert isinstance(got, Available) and (repr(got.value),) == _continuous(r, day)[-1][:1]


async def test_a_re_primed_session_instance_reads_back_to_its_session_start_again() -> None:
    """A store repair re-primes the instance (`backfill`): with no history asked for, it still
    reads from the session start, and two primings of one key agree."""
    day, _store, engine, stored, _hold = await _day()
    (r,) = admit(engine, [{"indicator": "vwap"}], history=0)
    await _done(engine)
    first = _served(engine, r)
    stored.calls.clear()
    engine.history_repair(SYM, M1, 1)
    await _done(engine)
    assert stored.calls == [(T0, day[-1].open_time + 1)]
    assert _served(engine, r) == first == _continuous(r, day)[DAY - 1_000 :]


async def test_a_ctl_swap_to_a_session_instance_reads_back_to_its_session_start() -> None:
    day, _store, engine, stored, _hold = await _day()
    (ema,) = admit(engine, EMA3, history=5)  # the store's bars suffice: no read
    assert stored.calls == []
    new = resolve_instances([{"indicator": "cvd"}], M1)
    engine.admit(SYM, M1, new, "c1", "u1", history=500, replacing=(ema.key,), reason="param_change")
    await _done(engine)
    assert stored.calls == [(T0, day[-1].open_time + 1)]
    assert _served(engine, new[0]) == _continuous(new[0], day)[DAY - 1_000 :]


async def test_a_session_instance_that_cannot_read_serves_none_until_the_next_session() -> None:
    """The read fails: the store's 1 000 bars begin inside the session, so every value of it is
    withheld (`warmup`), an amended close in it publishes nothing, and the next session, folded
    from its start, is served."""
    day, store, engine, stored, _hold = await _day()
    stored.fail = OSError("down")
    listener = Listener()
    engine.listen(listener)
    (r,) = admit(engine, [{"indicator": "cvd"}], history=500)
    await _done(engine)
    batch = engine.snapshot(SYM, r.key, 1_000)
    assert batch is not None and {p.values for p in batch.points} == {(None,)}
    assert engine.read(SYM, r.key) == Unavailable("warmup")
    listener.events.clear()
    late = day[-1].model_copy(update={"delta": Decimal(50)})
    await close(store, engine, late, generation=GEN, amended=True)
    assert listener.kinds() == []  # still None: no amended point goes out
    nxt = _bar(DAY, slot=NEXT_SESSION)
    await close(store, engine, nxt, generation=GEN)
    got = engine.read(SYM, r.key)
    assert isinstance(got, Available) and got.value == float(nxt.delta)


async def test_a_session_instance_re_primed_with_no_free_slot_serves_none_until_next() -> None:
    """A repair re-primes the instance while the only slot runs another read: from the store
    alone, so the session it cannot reach the start of is withheld."""
    _day_bars, _store, engine, stored, _hold = await _day(slots=1)
    (r,) = admit(engine, [{"indicator": "vwap"}], history=0)
    await _done(engine)
    stored.go.clear()
    admit(engine, [{"indicator": "sma", "params": {"n": 1_100}}], consumer="c2", history=0)
    await asyncio.sleep(0)  # its read takes the slot and waits
    engine.history_repair(SYM, M1, 1)
    batch = engine.snapshot(SYM, r.key, 1_000)
    assert batch is not None and {p.values for p in batch.points} == {(None,) * 9}
    assert engine.read(SYM, r.key) == Unavailable("warmup")
    stored.go.set()
    await _done(engine)


async def test_a_session_on_a_non_time_series_is_whole_from_the_generations_first_bar_only() -> (
    None
):
    """No read serves a non-time series: an instance primed from a store whose first bar is not
    the generation's withholds that session; one primed from index 0 serves it."""
    store = SeriesStore()
    _hold = await store.ensure(SYM, T5)
    late_start = IndicatorEngine(store)
    ticks = [_bar(i, spec=T5) for i in range(10)]
    for b in ticks[5:]:  # the series' first five bars are not in the store
        await close(store, late_start, b, spec=T5)
    (r,) = admit(late_start, [{"indicator": "cvd"}], spec=T5)
    batch = late_start.snapshot(SYM, r.key, 500)
    assert batch is not None and {p.values for p in batch.points} == {(None,)}
    assert late_start.read(SYM, r.key) == Unavailable("warmup")
    nxt = _bar(10, slot=NEXT_SESSION, spec=T5)
    await close(store, late_start, nxt, spec=T5)
    got = late_start.read(SYM, r.key)
    assert isinstance(got, Available) and got.value == float(nxt.delta)

    whole_store = SeriesStore()
    _whole_hold = await whole_store.ensure(SYM, T5)
    whole = IndicatorEngine(whole_store)
    for b in ticks:
        await close(whole_store, whole, b, spec=T5)
    admit(whole, [{"indicator": "cvd"}], spec=T5)
    served = whole.snapshot(SYM, r.key, 500)
    assert served is not None and _reprs(served.points) == _continuous(r, ticks, T5)


async def test_a_kernel_restart_inside_a_session_withholds_the_rest_of_it() -> None:
    """A gap of more than `MAX_FILL_SLOTS` restarts the kernel at the bar after it: the session
    sum would start there, so the session's later values are `None` until the next one."""
    store = SeriesStore()
    _hold = await store.ensure(SYM, M1)
    engine = IndicatorEngine(store)
    (r,) = admit(engine, [{"indicator": "cvd"}])
    for i in range(3):
        await close(store, engine, _bar(i))
    assert isinstance(engine.read(SYM, r.key), Available)
    await close(store, engine, _bar(3, slot=2 + MAX_FILL_SLOTS + 2))  # the same day
    assert engine.read(SYM, r.key) == Unavailable("warmup")
    nxt = _bar(4, slot=NEXT_SESSION)
    await close(store, engine, nxt)
    got = engine.read(SYM, r.key)
    assert isinstance(got, Available) and got.value == float(nxt.delta)


def test_a_session_instance_s_window_counts_a_day_back_to_its_session_start() -> None:
    """SR-E13-04 bounds the read a session-anchored instance may take: its history and a day."""
    vwap, sma = resolve_instances([{"indicator": "vwap"}, {"indicator": "sma"}], M1)
    assert vwap.span(M1, 1_000) == 1 + 1_000 + NEXT_SESSION
    assert sma.span(M1, 1_000) == sma.warmup() + 1_000
    (on_ticks,) = resolve_instances([{"indicator": "vwap"}], T5)
    assert on_ticks.span(T5, 1_000) == 1 + 1_000  # no read serves a non-time series
    engine = IndicatorEngine(SeriesStore())
    history = MAX_WINDOW_BARS - NEXT_SESSION  # one bar too many with the day
    with pytest.raises(RecomputeRefusedError, match="needs more than"):
        engine.check(SYM, M1, (vwap,), None, history=history)
    engine.check(SYM, M1, (vwap,), None, history=history - 1)
