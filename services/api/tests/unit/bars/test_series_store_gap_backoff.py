"""E12-T06 D2-H2 (#2787, #399): a bars gap that never heals is read again at a growing interval,
logged once per range and counted (see `bars/series_store.py`). The store's clock is the test's,
the read is a fake, and a hold keeps each series held as a subscriber does; nothing sleeps.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence

import pytest
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.bars.metrics import EXPORTED_NAMES
from candleviewer.bars.reader import BarTail
from candleviewer.bars.series_store import RECENT_CLOSES, RETRY_AFTER_S, Hold, SeriesStore
from candleviewer.observability.metrics_catalogue import CATALOGUE
from tests.unit.bars.test_series_store import SPEC, SYM, Clock, H, Tail, counted, emit, rows, up

REREADS = "bars_series_gap_rereads_total"
#: A live restart (a later run's bar 0 opens or closes) or a generation swap.
RESETS = pytest.mark.parametrize(
    ("generation", "shift", "first"),
    [(0, 20, "open"), (0, 20, "close"), (1, 0, "close")],
    ids=["restart-open", "restart-close", "swap"],
)


def ranges(logs: Sequence[Mapping[str, object]]) -> list[tuple[object, object]]:
    return [(e["from_index"], e["to_index"]) for e in logs if e["event"] == "bars_series_gap"]


async def gapped(clock: Clock) -> tuple[SeriesStore, Tail, Hold]:
    """Rows 0..9 are stored and the writer lands no more: a live close at 11 leaves a hole at 10
    that every read finds again. The hold keeps the series past the release grace."""
    tail = Tail(rows(*range(10)), now=True)
    store = SeriesStore(tail, clock=clock)
    hold = await store.ensure(SYM, SPEC)
    await emit(store, up("close", 11))
    return store, tail, hold


async def reread(store: SeriesStore, clock: Clock, wait: float) -> None:
    clock.t += wait * RETRY_AFTER_S
    await store.ensure(SYM, SPEC)


async def test_a_gap_that_stays_doubles_the_re_read_interval_up_to_160_s() -> None:
    """5, 10, 20, 40, 80, then 160 s, where it stays; an `ensure` before it reads nothing."""
    clock = Clock()
    store, tail, _held = await gapped(clock)
    for k, wait in enumerate((1, 2, 4, 8, 16, 32, 32)):
        clock.t += wait * RETRY_AFTER_S - 0.5
        await store.ensure(SYM, SPEC)
        assert tail.calls == k + 1
        clock.t += 0.5
        await store.ensure(SYM, SPEC)
        assert (tail.calls, store.gapped(SYM, H)) == (k + 2, True)


async def test_a_read_that_heals_the_gap_brings_the_interval_back_and_forgets_its_ranges() -> None:
    """The read that heals it withholds a row (SR-E12-11), so it is read again 5 s later, not 80."""
    clock = Clock()
    store, tail, _held = await gapped(clock)
    for wait in (1, 2, 4):
        await reread(store, clock, wait)
    tail.tail = BarTail(rows(*range(5), *range(6, 12)), dropped=1)
    await reread(store, clock, 8)
    assert (tail.calls, store.gapped(SYM, H), store.hydrated(SYM, H)) == (5, False, False)
    assert not store._series[(SYM, H)].logged  # white-box: forgotten
    await reread(store, clock, 1)
    assert tail.calls == 6


async def test_a_new_gap_seen_live_is_read_retry_after_s_after_the_last_read_and_resets() -> None:
    """A hole at 12..13 shows live just after a read, while the one at 10 waits 40 s: it is read
    `retry_after_s` after that read, not sooner, and the interval starts over (10 s, not 80)."""
    clock = Clock()
    store, tail, _held = await gapped(clock)
    for wait in (1, 2, 4):
        await reread(store, clock, wait)
    await emit(store, up("close", 14))
    for step, calls in ((4.5, 4), (0.5, 5), (5.0, 5), (5.0, 6)):
        clock.t += step
        await store.ensure(SYM, SPEC)
        assert tail.calls == calls
    assert store.gapped(SYM, H)


async def test_a_range_is_logged_once_however_often_it_is_read_and_a_new_range_logs() -> None:
    clock = Clock()
    with capture_logs() as logs:
        store, tail, _held = await gapped(clock)
        for wait in (1, 2, 4, 8, 16):  # five reads find the hole at 10 again
            await reread(store, clock, wait)
        await emit(store, up("close", 14))
        for wait in (1, 2):  # two find both
            await reread(store, clock, wait)
    assert (tail.calls, ranges(logs)) == (8, [(10, 10), (12, 13)])


async def test_a_series_keeps_8_logged_ranges_and_forgets_the_oldest_first() -> None:
    """C-2.18: nine holes seen live log once each; the series keeps the newest eight."""
    store = SeriesStore(Tail(rows(*range(10)), now=True))
    await store.ensure(SYM, SPEC)
    holes = [(i, i) for i in range(10, 28, 2)]
    with capture_logs() as logs:
        await emit(store, *(up("close", i + 1) for i, _ in holes))
    assert ranges(logs) == holes
    assert list(store._series[(SYM, H)].logged) == holes[1:]  # white-box: the bound


@RESETS
async def test_a_live_reset_or_swap_forgets_the_logged_ranges(
    generation: int, shift: int, first: str
) -> None:
    """A re-read finds the hole at 10 again and logs nothing; after a live restart (a later run's
    bar 0 opens or closes) or swap, the new bars' hole at 10 is another gap, and logs."""
    clock = Clock()
    with capture_logs() as logs:
        store, _, _held = await gapped(clock)
        await reread(store, clock, 1)
        after = (up("close", i, shift=shift) for i in (*range(10), 11))
        await emit(store, up(first, 0, shift=shift), *after, generation=generation)
    assert ranges(logs) == [(10, 10), (10, 10)] and store.gapped(SYM, H)


@RESETS
async def test_a_live_reset_or_swap_brings_the_interval_back_to_retry_after_s(
    generation: int, shift: int, first: str
) -> None:
    """Three re-reads back the hole at 10 off to 40 s; a live restart or swap whose bars run on
    with no hole brings the interval back: the next read comes `retry_after_s` after the last."""
    clock = Clock()
    store, tail, _held = await gapped(clock)
    for wait in (1, 2, 4):
        await reread(store, clock, wait)
    after = (up("close", i, shift=shift) for i in (0, 1))
    await emit(store, up(first, 0, shift=shift), *after, generation=generation)
    clock.t += RETRY_AFTER_S - 0.5
    await store.ensure(SYM, SPEC)
    assert tail.calls == 4
    clock.t += 0.5
    await store.ensure(SYM, SPEC)
    assert tail.calls == 5


@RESETS
async def test_a_read_in_flight_never_undoes_a_live_reset_or_swap(
    generation: int, shift: int, first: str
) -> None:
    """R2 begins on the gapped series; while it is in flight, a live restart or swap lands and its
    bars skip index 2. R2 is no re-read: it counts nothing and keeps the interval the reset set,
    so R3 reads `retry_after_s` later (and heals: the new bars' rows are stored by then)."""
    clock = Clock()
    store, tail, _held = await gapped(clock)
    await reread(store, clock, 1)  # R1 leaves it gapped: R2 is due 10 s later
    before = counted(REREADS)
    tail.gate.clear()
    tail.started.clear()
    clock.t += 2 * RETRY_AFTER_S
    task = asyncio.create_task(store.ensure(SYM, SPEC))
    await tail.started.wait()
    after = (up("close", i, shift=shift) for i in (0, 1, 3))
    await emit(store, up(first, 0, shift=shift), *after, generation=generation)
    tail.gate.set()
    await task
    assert (tail.calls, store.gapped(SYM, H), counted(REREADS)) == (3, True, before)
    tail.tail = BarTail(rows(*range(4), gen=generation, shift=shift))
    await reread(store, clock, 1)
    assert (tail.calls, store.gapped(SYM, H), counted(REREADS)) == (4, False, before)


async def test_a_re_read_over_two_stored_runs_logs_its_gap_once() -> None:
    """A cold start reused indexes, so each read's rows restart the series; only a live restart
    forgets the ranges logged, so the newer run's hole at 2 logs once."""
    clock = Clock()
    tail = Tail([*rows(*range(5)), *rows(0, 1, shift=10)], now=True)
    store = SeriesStore(tail, clock=clock)
    with capture_logs() as logs:
        _held = await store.ensure(SYM, SPEC)
        await emit(store, up("close", 3, shift=10))
        for wait in (1, 2):
            await reread(store, clock, wait)
    assert (tail.calls, ranges(logs)) == (3, [(2, 2)])


async def test_the_re_read_counter_counts_only_reads_that_find_and_leave_a_series_gapped() -> None:
    """Not the read that finds the gap, nor a failed read (which keeps the interval), nor the one
    that heals: 3 of 6."""
    clock = Clock()
    tail = Tail(rows(*range(10)), now=True)
    store = SeriesStore(tail, clock=clock)
    await emit(store, *(up("close", i) for i in range(14, 14 + RECENT_CLOSES)))  # before the hold
    before = counted(REREADS)
    _held = await store.ensure(SYM, SPEC)
    assert store.gapped(SYM, H)  # the hole at 10..13
    for wait in (1, 2, 4):
        await reread(store, clock, wait)
    tail.error = OSError("questdb down")
    await reread(store, clock, 8)
    await reread(store, clock, 1)  # the interval is still 40 s
    assert tail.calls == 5
    tail.error, tail.tail = None, BarTail(rows(*range(30)))
    await reread(store, clock, 8)
    assert (tail.calls, store.gapped(SYM, H), counted(REREADS)) == (6, False, before + 3)


async def test_a_gap_first_seen_during_a_read_is_no_re_read() -> None:
    """Not gapped as the read begins (a degraded read is due again), gapped by a live close while
    it is in flight: it counts nothing and the interval stays 5 s. The next read is a re-read."""
    clock = Clock()
    tail = Tail(now=True)
    tail.tail = BarTail(rows(*range(10)), dropped=1)
    store = SeriesStore(tail, clock=clock)
    await store.ensure(SYM, SPEC)
    before = counted(REREADS)
    tail.gate.clear()
    tail.started.clear()
    clock.t += RETRY_AFTER_S
    task = asyncio.create_task(store.ensure(SYM, SPEC))
    await tail.started.wait()
    await emit(store, up("close", 11))
    tail.gate.set()
    await task
    assert (tail.calls, store.gapped(SYM, H), counted(REREADS)) == (2, True, before)
    await reread(store, clock, 1)
    assert (tail.calls, counted(REREADS)) == (3, before + 1)
    await reread(store, clock, 1)  # not hydrated, it backs off too: 10 s now
    assert tail.calls == 3


def test_the_re_read_counter_is_one_unlabelled_live_exported_series_with_one_help() -> None:
    spec = next(s for s in CATALOGUE if s.name == REREADS)
    assert (spec.kind, spec.labels, spec.status, spec.exported) == ("counter", (), "live", True)
    assert REREADS in EXPORTED_NAMES  # `export_bars_metrics` serves it, with `env`
    helps = {m.name: m.documentation for m in REGISTRY.collect()}
    assert helps[REREADS.removesuffix("_total")] == spec.help  # one text in both places
