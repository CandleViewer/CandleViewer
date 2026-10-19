"""E12-T06 #2787 D2-H1 (P4a): the series store's side of the heal driver (`bars/series_store.py`):
`due`, `refresh`, the repair hook (23 §7.4 `history_repair`) and `bars_series_incomplete_in_use`.
The store's clock is the test's, the read is a fake and the hook records its calls; a hold keeps
each series held as a subscriber does. Nothing sleeps; no network, no QuestDB.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import gc
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any
from unittest.mock import Mock

import pytest
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.bars import series_store
from candleviewer.bars.emit import BarEmission
from candleviewer.bars.limits import MAX_CONCURRENT_TAIL_READS
from candleviewer.bars.metrics import EXPORTED_NAMES
from candleviewer.bars.models import Bar, BarSpec
from candleviewer.bars.reader import BarTail
from candleviewer.bars.series_store import (
    MAX_HISTORY,
    RECENT_CLOSES,
    RELEASE_GRACE_S,
    RETRY_AFTER_S,
    Hold,
    SeriesStore,
)
from candleviewer.observability.metrics_catalogue import CATALOGUE
from tests.unit.bars.test_series_store import (
    SPEC,
    STEP,
    SYM,
    T0,
    Clock,
    H,
    Tail,
    bar,
    counted,
    emit,
    rows,
    up,
    view,
)

GAUGE = "bars_series_incomplete_in_use"
FAILED = "bars_series_repair_failed_total"
LATE = 1_000.0  # far past any re-read interval these tests reach


def incomplete() -> float | None:
    return REGISTRY.get_sample_value(GAUGE)  # the scrape's path: the gauge's callback


class Hook:
    """The repair hook: records each call and the series as the call saw it, then raises
    `error`, if any."""

    def __init__(self, store: SeriesStore, error: BaseException | None = None) -> None:
        self.store, self.error = store, error
        self.calls: list[tuple[str, BarSpec, int]] = []
        self.seen: list[tuple[tuple[list[int], int | None], bool, bool]] = []
        store.on_repair(self)

    def __call__(self, symbol: str, spec: BarSpec, min_history: int) -> int:
        st = self.store
        self.calls.append((symbol, spec, min_history))
        self.seen.append((view(st), st.hydrated(SYM, H), st.gapped(SYM, H)))
        if self.error is not None:
            raise self.error
        return 1  # the publisher's snaps sent: the store ignores it


async def gapped(clock: Clock, *, forming: bool = False) -> tuple[SeriesStore, Tail, Hold]:
    """Rows 0..9 are stored; a live close at 11 (and bar 12 forming) leaves a hole at 10."""
    tail = Tail(rows(*range(10)), now=True)
    store = SeriesStore(tail, clock=clock)
    hold = await store.ensure(SYM, SPEC)
    await emit(store, up("close", 11), *([up("open", 12)] if forming else []))
    return store, tail, hold


async def live_only(clock: Clock) -> tuple[SeriesStore, Tail, Hold]:
    """The first read failed: the series holds what it saw live, bar 5 closed and 6 forming."""
    tail = Tail(error=OSError("questdb down"), now=True)
    store = SeriesStore(tail, clock=clock)
    hold = await store.ensure(SYM, SPEC)
    await emit(store, up("close", 5), up("open", 6))
    tail.error, tail.tail = None, BarTail(rows(*range(6)))  # the writer's rows, readable again
    return store, tail, hold


@pytest.mark.parametrize("state", ["failed", "degraded", "gapped"])
async def test_a_series_not_complete_is_due_once_its_interval_has_passed(state: str) -> None:
    clock = Clock()
    tail = Tail(rows(*range(10)), error=OSError("down") if state == "failed" else None, now=True)
    if state == "degraded":
        tail.tail = BarTail(rows(*range(10)), dropped=1)  # SR-E12-11: served, never final
    store = SeriesStore(tail, clock=clock)
    _held = await store.ensure(SYM, SPEC)
    if state == "gapped":
        await emit(store, up("close", 11))
    assert store.due(clock.t + RETRY_AFTER_S - 0.5) == []
    assert store.due(clock.t + RETRY_AFTER_S) == [(SYM, H)]


async def test_a_complete_series_or_one_no_reader_can_read_is_never_due() -> None:
    clock = Clock()
    store = SeriesStore(Tail(rows(*range(10)), now=True), clock=clock)
    bare = SeriesStore(clock=clock)  # no reader: it keeps what it sees live, never `hydrated`
    _held, _bare = await store.ensure(SYM, SPEC), await bare.ensure(SYM, SPEC)
    assert (store.due(clock.t + LATE), bare.due(clock.t + LATE)) == ([], [])
    clock.t += LATE
    assert (await store.refresh(SYM, H), await bare.refresh(SYM, H)) == (False, False)


async def test_a_series_with_a_read_in_flight_is_neither_due_nor_read_again() -> None:
    clock = Clock()
    store, tail, _held = await live_only(clock)
    tail.gate.clear()
    tail.started.clear()
    clock.t += RETRY_AFTER_S
    reading = asyncio.create_task(store.ensure(SYM, SPEC))
    await tail.started.wait()
    assert store.due(clock.t + LATE) == [] and not await store.refresh(SYM, H)
    tail.gate.set()
    await reading
    assert tail.calls == 2


async def test_a_released_series_or_one_not_kept_is_not_due_nor_read() -> None:
    """Released, in its grace or past it (not swept yet): no subscriber holds it."""
    clock = Clock()
    tail = Tail(error=OSError("down"), now=True)
    store = SeriesStore(tail, clock=clock)
    (await store.ensure(SYM, SPEC)).release()
    for at in (RETRY_AFTER_S, RELEASE_GRACE_S + 1):
        assert store.due(clock.t + at) == []
    clock.t += RETRY_AFTER_S
    assert not await store.refresh(SYM, H) and not await store.refresh("XUSDT", H)
    assert tail.calls == 1


async def test_due_lists_the_earliest_due_first_and_at_most_limit() -> None:
    """Read in reverse name order, a second apart: due by time, not by name; 8 by default."""
    clock = Clock()
    store = SeriesStore(Tail(error=OSError("down"), now=True), clock=clock)
    syms = [f"S{i}USDT" for i in range(MAX_CONCURRENT_TAIL_READS + 2)][::-1]
    holds = []
    for sym in syms:
        holds.append(await store.ensure(sym, SPEC))
        clock.t += 1
    first = [(sym, H) for sym in syms]
    assert store.due(clock.t + LATE) == first[:MAX_CONCURRENT_TAIL_READS]
    assert store.due(clock.t + LATE, limit=3) == first[:3]
    assert store.due(clock.t - len(syms) + RETRY_AFTER_S + 1) == first[:2]


async def older_history(clock: Clock) -> tuple[SeriesStore, Tail, Hold]:
    """The first read failed: the series holds the ring's closes 20..35, then 36 and 37 closed
    live and 38 forming."""
    tail = Tail(error=OSError("questdb down"), now=True)
    store = SeriesStore(tail, clock=clock)
    await emit(store, *(up("close", i) for i in range(20, 20 + RECENT_CLOSES)))
    hold = await store.ensure(SYM, SPEC)
    await emit(store, up("close", 36), up("close", 37), up("open", 38))
    tail.error = None
    return store, tail, hold


async def full(clock: Clock) -> tuple[SeriesStore, Tail, Hold]:
    """1 000 rows read; a live close at 1 001 leaves a hole at 1 000, and the cap trims bar 0."""
    tail = Tail(rows(*range(MAX_HISTORY)), now=True)
    store = SeriesStore(tail, clock=clock)
    hold = await store.ensure(SYM, SPEC)
    await emit(store, up("close", MAX_HISTORY + 1))
    return store, tail, hold


def served(store: SeriesStore, history: int) -> tuple[list[Bar], Bar | None]:
    got = store.latest(SYM, H, history)
    assert got is not None
    return got.closed, got.forming


@pytest.mark.parametrize(
    ("setup", "stored", "depth", "live"),
    [
        (functools.partial(gapped, forming=False), BarTail(rows(*range(12))), 2, None),
        (functools.partial(gapped, forming=True), BarTail(rows(*range(12))), 3, None),
        (gapped, BarTail(rows(*range(2, 12)), since_us=T0 + 2 * STEP), 2, None),  # 0, 1: before it
        (full, BarTail(rows(*range(2, MAX_HISTORY + 2))), 2, None),  # 1: in the window, past cap
        (older_history, BarTail(rows(*range(38))), 20, None),
        (gapped, BarTail(rows(*range(12))), 3, 12),  # bar 12 closes live during the read
        (gapped, BarTail(rows(*range(10))), None, 12),  # the same rows: the hole at 10 stays
    ],
    ids=["gap", "gap-forming", "window-moved", "full", "older-history", "live-fills", "live-same"],
)
async def test_min_history_is_the_shallowest_history_whose_snapshot_the_read_changed(
    setup: Callable[[Clock], Awaitable[tuple[SeriesStore, Tail, Hold]]],
    stored: BarTail,
    depth: int | None,
    live: int | None,
) -> None:
    """One call per repairing read. A subscriber with `history == min_history` holds a bar the
    read added (its `snap` changed) and one with `min_history - 1` none: checked against `latest`
    for every `history` up to 40, the forming bar counted first. Held bars below the oldest row
    that opened before the read's window, or that the 1 000-bar cap leaves out, are not lost. A
    plain live close (`live`, no reset) during the read is in the series the fold finds, not
    something the read added: the same rows repair nothing; rows that fill the hole at 10 repair
    it at 3 (bars 12, 11, 10), not 1."""
    clock = Clock()
    store, tail, _held = await setup(clock)
    hook = Hook(store)
    tail.tail = stored
    tail.gate.clear()
    tail.started.clear()
    clock.t += RETRY_AFTER_S
    reading = asyncio.create_task(store.refresh(SYM, H))
    await tail.started.wait()
    if live is not None:
        await emit(store, up("close", live))
    deep = range(1, 41)
    before = [served(store, h) for h in deep]  # the series as the fold finds it
    tail.gate.set()
    assert await reading is (depth is not None)
    changed = [h for h, was in zip(deep, before, strict=True) if served(store, h) != was]
    assert (hook.calls, changed) == (
        ([], []) if depth is None else ([(SYM, SPEC, depth)], list(range(depth, 41)))
    )


@pytest.mark.parametrize("trigger", ["ensure", "refresh"])
async def test_the_hook_follows_a_repairing_read_whoever_starts_it_and_sees_it_folded(
    trigger: str,
) -> None:
    """A subscriber's `ensure` or the driver's `refresh`: the call ends the read, after the fold
    and its bookkeeping, so the hook sees the series healed, `hydrated` and not `gapped`."""
    clock = Clock()
    store, tail, _held = await live_only(clock)
    hook = Hook(store)
    clock.t += RETRY_AFTER_S
    if trigger == "ensure":
        _second = await store.ensure(SYM, SPEC)  # another subscriber's
    else:
        assert await store.refresh(SYM, H)
    assert (tail.calls, hook.calls) == (2, [(SYM, SPEC, 3)])
    assert hook.seen == [((list(range(6)), 6), True, False)]


@pytest.mark.parametrize("read", ["same-rows", "lost-a-bar", "lost-at-the-edge"])
async def test_a_read_that_changes_nothing_or_loses_a_held_bar_repairs_nothing(read: str) -> None:
    """The same rows read clean (the first read was degraded); or rows that fill the hole at 10
    but lack a held bar inside the read's window: bar 9, or bar 0 at the oldest edge (23 §7.4: a
    read that loses a bar is no repair, even if it adds)."""
    clock = Clock()
    if read == "same-rows":
        tail = Tail(now=True)
        tail.tail = BarTail(rows(*range(10)), dropped=1)
        store = SeriesStore(tail, clock=clock)
        _held = await store.ensure(SYM, SPEC)
        tail.tail, after = BarTail(rows(*range(10))), list(range(10))
    else:
        store, tail, _held = await gapped(clock)
        after = [i for i in range(12) if i != (9 if read == "lost-a-bar" else 0)]
        tail.tail = BarTail(rows(*after), since_us=T0)  # the window holds bar 0
    hook = Hook(store)
    clock.t += RETRY_AFTER_S
    assert not await store.refresh(SYM, H)
    assert (tail.calls, hook.calls, view(store)) == (2, [], (after, None))
    assert store.hydrated(SYM, H) and store.due(clock.t + LATE) == []  # complete: no more reads


@pytest.mark.parametrize(
    ("fetched", "hole", "depth"),
    [(MAX_HISTORY, None, 2), (MAX_HISTORY - 1, None, None), (MAX_HISTORY, 500, None)],
    ids=["row-limit", "below-it", "row-limit-hole"],
)
async def test_a_read_at_its_row_limit_counts_the_older_held_bars_as_slid_off_not_lost(
    fetched: int, hole: int | None, depth: int | None
) -> None:
    """1 000 rows fetched, one skipped: 999 bars, so the series is not full, but the row limit, not
    `since_us`, ended the read's window: held bars 1 and 2, below its oldest row, slid off and the
    read repairs the hole at 1 000. One row fewer fetched, the read took every row from `since_us`
    on and they are lost. At the limit too, a held bar inside the rows' span that the read lacks
    (500, skipped) is lost: no repair."""
    clock = Clock()
    store, tail, _held = await full(clock)  # holds 1 to 999 and 1 001: the hole at 1 000
    hook = Hook(store)
    oldest = MAX_HISTORY + 3 - fetched  # the rows less the skipped ones, `fetched - 1` bars
    bars = [i for i in range(oldest, MAX_HISTORY + 2) if i != hole]
    tail.tail = BarTail(rows(*bars), skipped=1 + (hole is not None), fetched=fetched)
    clock.t += RETRY_AFTER_S
    assert await store.refresh(SYM, H) is (depth is not None)
    assert hook.calls == ([] if depth is None else [(SYM, SPEC, depth)])
    assert view(store)[0][0] == oldest and not store.gapped(SYM, H)


async def test_a_failed_refresh_returns_false_and_takes_the_store_failure_path() -> None:
    clock = Clock()
    store, tail, _held = await gapped(clock)
    hook = Hook(store)
    tail.error = OSError("questdb down")
    clock.t += RETRY_AFTER_S
    before = counted("bars_series_hydrate_failed_total", "connection")
    with capture_logs() as logs:
        assert not await store.refresh(SYM, H)
    assert [e["event"] for e in logs] == ["bars_series_hydrate_failed"] and hook.calls == []
    assert counted("bars_series_hydrate_failed_total", "connection") == before + 1
    assert store.gapped(SYM, H) and store.due(clock.t + RETRY_AFTER_S) == [(SYM, H)]


async def test_the_gap_backoff_spaces_refresh_reads_as_it_spaces_ensure_reads() -> None:
    """The hole at 10 stays: each read that finds it again doubles the interval, whoever reads."""
    clock = Clock()
    store, tail, _held = await gapped(clock)
    for step, reads in ((1, 2), (1, 2), (1, 3), (2, 3)):  # read at 5 s, then 10 s later
        clock.t += step * RETRY_AFTER_S
        assert not await store.refresh(SYM, H) and tail.calls == reads
    _second = await store.ensure(SYM, SPEC)  # 10 s after the last read, which set 20 s
    assert tail.calls == 3 and store.due(clock.t + 2 * RETRY_AFTER_S - 0.5) == []
    assert store.due(clock.t + 2 * RETRY_AFTER_S) == [(SYM, H)]


@pytest.mark.parametrize(
    "error", [ValueError("min_history 0 holds no bar"), asyncio.CancelledError()],
    ids=["error", "cancelled"],
)  # fmt: skip
async def test_a_raising_hook_leaves_the_read_standing(error: BaseException) -> None:
    """An error is counted and logged, never raised; a cancellation is raised, never swallowed.
    Either way the read stands: healed, `hydrated`, nothing in flight."""
    clock = Clock()
    store, tail, _held = await gapped(clock)
    hook = Hook(store, error)
    tail.tail = BarTail(rows(*range(12)))
    clock.t += RETRY_AFTER_S
    before = counted(FAILED, "hook")
    with capture_logs() as logs:
        if isinstance(error, Exception):
            assert await store.refresh(SYM, H)
        else:
            with pytest.raises(asyncio.CancelledError):
                await store.refresh(SYM, H)
    logged = [(e["min_history"], e["error_type"]) for e in logs]
    kept = isinstance(error, Exception)  # caught by the store
    assert (counted(FAILED, "hook") - before, logged) == (
        (1, [(2, "ValueError")]) if kept else (0, [])
    )
    assert len(hook.calls) == 1 and view(store) == (list(range(12)), None)
    assert (store.hydrated(SYM, H), store.gapped(SYM, H), store.due(clock.t + LATE)) == (
        True, False, [],
    )  # fmt: skip
    _again = await asyncio.wait_for(store.ensure(SYM, SPEC), 1.0)  # a bound, not a delay
    assert tail.calls == 2


async def test_the_incomplete_gauge_follows_hydrate_gap_heal_and_release() -> None:
    clock = Clock()
    tail = Tail(error=OSError("questdb down"), now=True)
    store = SeriesStore(tail, clock=clock)
    counts = [incomplete()]
    _btc, eth = await store.ensure(SYM, SPEC), await store.ensure("ETHUSDT", SPEC)
    counts.append(incomplete())  # both reads failed: not `hydrated`
    tail.error, tail.tail = None, BarTail(rows(*range(10)))
    clock.t += RETRY_AFTER_S
    assert await store.refresh(SYM, H)
    counts.append(incomplete())  # BTC hydrated
    await emit(store, up("close", 11))
    counts.append(incomplete())  # BTC gapped
    tail.tail = BarTail(rows(*range(12)))
    clock.t += RETRY_AFTER_S
    assert await store.refresh(SYM, H)
    counts.append(incomplete())  # BTC healed
    eth.release()
    counts.append(incomplete())  # ETH released: in its grace, held by no one
    assert counts == [0, 2, 1, 2, 1, 0] and store.incomplete_count() == 0


async def test_the_incomplete_gauge_reads_0_once_its_store_is_collected() -> None:
    """A weak reference: the gauge keeps no store alive. A hold dropped unreleased only queues
    its release, so the series is still held when the store goes."""
    store = SeriesStore()
    hold = await store.ensure(SYM, SPEC)  # no reader: never `hydrated`
    assert incomplete() == 1
    del hold, store
    gc.collect()
    assert incomplete() == 0


def test_the_repair_hook_is_set_once() -> None:
    store = SeriesStore()
    store.on_repair(lambda *_: None)
    with pytest.raises(RuntimeError, match="set already"):
        store.on_repair(lambda *_: None)


def test_the_depth_counts_bars_as_latest_serves_them_and_an_equal_bar_is_no_change() -> None:
    """White-box (`_repair_depth`): an equal bar in another object changes nothing; another close
    of a held bar replaces it; a bar below the deepest `history` (1 000, the forming bar first)
    is in no snapshot."""
    s, depth = series_store._Series(1, SPEC), series_store._repair_depth
    s.closed.update((i, bar(i)) for i in range(MAX_HISTORY))
    before = {i: bar(i) for i in range(MAX_HISTORY)}  # equal copies, other objects
    assert depth(s, before, 0) is None
    s.closed[MAX_HISTORY - 2] = bar(MAX_HISTORY - 2, close="105")  # bar 998 closed again
    assert depth(s, before, 0) == 2
    s.closed[MAX_HISTORY - 2] = before[MAX_HISTORY - 2]
    del before[0]  # bar 0 is new
    assert depth(s, before, 0) == MAX_HISTORY
    s.forming = bar(MAX_HISTORY, closed=False)  # now bar 0 is at 1 001
    assert depth(s, before, 0) is None


def test_the_gauge_and_the_repair_counter_are_live_exported_and_bounded_with_one_help() -> None:
    """The counter's `reason` is `depth` or `hook`: two series at most (C-2.18)."""
    helps = {m.name: m.documentation for m in REGISTRY.collect()}
    for name, kind, labels, most in (
        (GAUGE, "gauge", (), 200),
        (FAILED, "counter", ("reason",), 2),
    ):
        spec = next(s for s in CATALOGUE if s.name == name)
        assert (spec.kind, spec.labels, spec.max_series) == (kind, labels, most)
        assert (spec.status, spec.exported, name in EXPORTED_NAMES) == ("live", True, True)
        assert helps[name.removesuffix("_total")] == spec.help


@pytest.mark.parametrize("trigger", ["ensure", "refresh"])
@pytest.mark.parametrize("walk", ["raises", "zero", "negative"])
async def test_a_depth_the_store_cannot_count_goes_out_as_1_never_skipped(
    walk: str, trigger: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P11's caller contract: a depth walk that raises, or gives 0 or -1, still calls the hook once,
    with 1 (every subscription with a `history` gets the snap); counted (`reason="depth"`),
    logged at error, and the read completes: healed, `hydrated`, its next read time set."""

    def broken(*_: object) -> int:
        if walk == "raises":
            raise TypeError("a broken walk")
        return 0 if walk == "zero" else -1

    monkeypatch.setattr(series_store, "_repair_depth", broken)
    clock = Clock()
    store, tail, _held = await gapped(clock)
    hook = Hook(store)
    tail.tail = BarTail(rows(*range(12)))
    clock.t += RETRY_AFTER_S
    before = counted(FAILED, "depth")
    with capture_logs() as logs:
        repaired = await store.refresh(SYM, H) if trigger == "refresh" else None
        _second = await store.ensure(SYM, SPEC)  # after a refresh: complete, so no read
    s = store._series[(SYM, H)]  # white-box: the read's bookkeeping ran
    assert repaired is (True if trigger == "refresh" else None)
    assert (hook.calls, counted(FAILED, "depth") - before, tail.calls) == ([(SYM, SPEC, 1)], 1, 2)
    assert (s.hydrated, s.gapped, s.attempted, s.read_at) == (True, False, True, clock.t)
    logged = [(e["event"], e["log_level"]) for e in logs]
    assert logged == [("bars_series_repair_depth_failed", "error")]


async def test_a_degraded_repairing_read_calls_the_hook_and_a_clean_one_after_does_not() -> None:
    """SR-E12-11: a re-read that withholds row 3 (and skips two) but brings bar 10 repairs the
    hole (the held 3 stays, D2-H1b) and leaves the series not `hydrated`; the clean read of the
    same rows after it changes nothing, so it calls nothing."""
    clock = Clock()
    store, tail, _held = await gapped(clock)
    hook = Hook(store)
    tail.tail = BarTail(rows(*range(3), *range(4, 12)), dropped=1, skipped=2)
    clock.t += RETRY_AFTER_S
    with capture_logs() as logs:  # logged after the hook, as the read's last lines
        assert await store.refresh(SYM, H) and not store.hydrated(SYM, H)
    events = [e["event"] for e in logs]
    assert events == ["bars_series_hydrate_degraded", "bars_series_rows_skipped"]
    tail.tail = BarTail(rows(*range(12)))
    clock.t += RETRY_AFTER_S
    assert not await store.refresh(SYM, H) and store.hydrated(SYM, H)
    assert (tail.calls, hook.calls, view(store)) == (3, [(SYM, SPEC, 2)], (list(range(12)), None))


async def test_a_log_line_that_raises_never_skips_the_hook(monkeypatch: pytest.MonkeyPatch) -> None:
    """A logger that raises after the fold never skips the hook: for a depth below 1 (0 here),
    withheld rows and skipped rows, the hook is called once, with 1, and `hydrated` is set before
    the error escapes. Not pinned: where a raising walk's log line sits, nor the order of
    `since_us`, the gap reset and the backoff against the logs."""
    clock = Clock()
    store, tail, _held = await gapped(clock)
    hook = Hook(store)
    tail.tail = BarTail(rows(*range(3), *range(4, 12)), dropped=1, skipped=2)
    clock.t += RETRY_AFTER_S
    log = Mock()
    log.error.side_effect = log.warning.side_effect = log.info.side_effect = OSError("log down")
    monkeypatch.setattr(series_store, "_log", lambda: log)
    monkeypatch.setattr(series_store, "_repair_depth", lambda *_: 0)  # a depth fault
    with pytest.raises(OSError, match="log down"):
        await store.refresh(SYM, H)
    s = store._series[(SYM, H)]  # white-box: the read's bookkeeping ran
    assert hook.calls == [(SYM, SPEC, 1)]
    assert (s.hydrated, s.gapped, s.replay, s.read_at) == (False, False, None, clock.t)


def drive(coro: Coroutine[Any, Any, None]) -> None:
    """Run inline a coroutine that never awaits (the sink's `emit`)."""
    with contextlib.suppress(StopIteration):
        coro.send(None)


async def test_nothing_awaits_between_the_fold_and_the_hook() -> None:
    """A cancel and an emission queued right behind the read's completion both land after the
    hook: it is called once, sees the series exactly as the fold left it (no bar 12), and the
    read stands (cancellation-safety; with an await there, the cancel would skip the hook)."""
    clock = Clock()
    store, tail, _held = await gapped(clock)
    hook = Hook(store)
    tail.tail = BarTail(rows(*range(12)))
    tail.gate.clear()
    tail.started.clear()
    clock.t += RETRY_AFTER_S
    reading = asyncio.create_task(store.refresh(SYM, H))
    await tail.started.wait()
    loop = asyncio.get_running_loop()
    tail.gate.set()  # the read resumes first, then the cancel, then the emission
    loop.call_soon(reading.cancel)
    loop.call_soon(drive, store.emit(BarEmission(SPEC, 0, (up("close", 12),))))
    assert await reading
    assert hook.calls == [(SYM, SPEC, 2)] and hook.seen == [((list(range(12)), None), True, False)]
    assert view(store) == (list(range(13)), None)  # the emission came after the hook


@pytest.mark.parametrize("generation", [0, 1], ids=["restart", "swap"])
async def test_a_reset_or_swap_during_a_refresh_read_repairs_nothing_it_did_not_fold(
    generation: int,
) -> None:
    """H2's reset epoch and the repair compose: a live restart (or swap) lands while the read is
    in flight, so the series is a later run's bar 0; the read's rows are the old run's, the fold
    keeps the later run, and no hook is called for bars the series no longer serves."""
    clock = Clock()
    store, tail, _held = await gapped(clock)
    hook = Hook(store)
    tail.tail = BarTail(rows(*range(12)))
    tail.gate.clear()
    tail.started.clear()
    clock.t += RETRY_AFTER_S
    reading = asyncio.create_task(store.refresh(SYM, H))
    await tail.started.wait()
    await emit(store, up("close", 0, shift=20), generation=generation)
    tail.gate.set()
    assert not await reading
    assert (hook.calls, view(store)) == ([], ([0], None))
