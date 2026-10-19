"""E12-T06 slice B (#2195, #399): the bars WS snapshot store, `23-ws-protocol.md` §6.1, §8.2."""

from __future__ import annotations

import asyncio
import gc
from collections.abc import Mapping, Sequence
from decimal import Decimal

import pytest
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.bars import series_store
from candleviewer.bars.emit import BarEmission
from candleviewer.bars.errors import SpecCapExceeded
from candleviewer.bars.models import Bar, BarSpec, BarUpdate
from candleviewer.bars.reader import BarTail
from candleviewer.bars.series_store import (
    MAX_HISTORY,
    RECENT_CLOSES,
    RELEASE_GRACE_S,
    RETRY_AFTER_S,
    SeriesStore,
)

SPEC = BarSpec(kind="time", interval_ms=300_000)
SYM, H = "BTCUSDT", SPEC.spec_hash
T0, STEP = 1_700_000_000_000_000, 300_000_000


def bar(i: int, *, closed: bool = True, close: str = "100", shift: int = 0, sym: str = SYM) -> Bar:
    """Bar `i`, opening `shift` steps later than bar `i` of the first run (a restarted run)."""
    one, t = Decimal(1), T0 + (i + shift) * STEP
    return Bar.model_construct(
        spec_hash=H, symbol=sym, index=i, open_time=t, close_time=t + STEP - 1, open=one,
        high=one, low=one, close=Decimal(close), volume=one, buy_volume=one, sell_volume=one * 0,
        delta=one, min_delta=one, max_delta=one, trade_count=1, turnover=one, vwap=one,
        closed=closed, partial=False, gap_before=False,
    )  # fmt: skip


def up(
    kind: str, i: int, *, amended: bool = False, close: str = "100", shift: int = 0, sym: str = SYM
) -> BarUpdate:
    b = bar(i, closed=kind == "close", close=close, shift=shift, sym=sym)
    return BarUpdate.model_construct(kind=kind, bar=b, amended=amended)


async def emit(store: SeriesStore, *updates: BarUpdate, generation: int = 0) -> None:
    await store.emit(BarEmission(SPEC, generation, updates))


def view(
    store: SeriesStore, history: int = MAX_HISTORY, sym: str = SYM
) -> tuple[list[int], int | None]:
    got = store.latest(sym, H, history)
    assert got is not None
    closed, forming = got.closed, got.forming
    return [b.index for b in closed], None if forming is None else forming.index


def closes(store: SeriesStore, history: int = MAX_HISTORY) -> list[tuple[int, str]]:
    got = store.latest(SYM, H, history)
    assert got is not None
    return [(b.index, str(b.close)) for b in got.closed]


def generation(store: SeriesStore) -> int | None:
    got = store.latest(SYM, H, 1)
    assert got is not None
    return got.generation


def counted(name: str, reason: str | None = None) -> float:
    """A store counter's value (D3 observability), by `reason` when it has one."""
    labels = {} if reason is None else {"reason": reason}
    return float(REGISTRY.get_sample_value(name, labels) or 0.0)


class Clock:
    """The store's injected monotonic clock (seconds); tests move it by hand."""

    def __init__(self) -> None:
        self.t = 1_000.0

    def __call__(self) -> float:
        return self.t


async def held(*updates: BarUpdate) -> SeriesStore:
    store = SeriesStore()
    await store.ensure(SYM, SPEC)
    await emit(store, *updates)
    return store


async def test_sink_folds_open_update_and_close_into_forming_then_closed() -> None:
    store = await held(up("open", 0))
    assert view(store) == ([], 0)
    await emit(store, up("update", 0, close="101"))
    assert view(store) == ([], 0)
    await emit(store, up("close", 0, close="102"), up("open", 1))
    assert view(store) == ([0], 1) and closes(store) == [(0, "102")]
    await emit(store, up("close", 1))
    assert view(store) == ([0, 1], None)  # its close ends the forming bar


@pytest.mark.parametrize("amended", [True, False])
async def test_sink_a_close_of_a_held_bar_replaces_it_in_place(amended: bool) -> None:
    """An amended close, or the same close again (same key and open time)."""
    store = await held(*(up("close", i) for i in range(3)))
    await emit(store, up("close", 1, amended=amended, close="105"))
    assert closes(store) == [(0, "100"), (1, "105"), (2, "100")]


async def test_sink_amended_close_of_a_bar_not_held_is_ignored() -> None:
    store = await held(up("close", 5), up("close", 6))
    before = store.version(SYM, H)
    await emit(store, up("close", 3, amended=True))  # older than the window: nothing to replace
    assert view(store) == ([5, 6], None) and store.version(SYM, H) == before


@pytest.mark.parametrize(
    ("before", "window"),
    [((up("open", 0),), ([], 0)), ((up("close", 5), up("close", 6)), ([5, 6], None))],
    ids=["empty", "5-6"],
)
async def test_sink_an_amended_close_above_the_window_is_ignored(
    before: tuple[BarUpdate, ...], window: tuple[list[int], int | None]
) -> None:
    """Never a bar's first sight: above the newest index it would open a hole (#2666 r2)."""
    store = await held(*before)
    version = store.version(SYM, H)
    await emit(store, up("close", 9, amended=True))
    assert view(store) == window and store.version(SYM, H) == version


async def test_sink_a_live_generation_change_resets_the_series_in_both_directions() -> None:
    """§8.2 generation swap: one live builder per series, so a lower live generation (#2662's
    clock-regression cold start) is as authoritative as a higher one."""
    store = await held(*(up("close", i) for i in range(3)), up("open", 3))
    before = counted("bars_series_resets_total", "generation_swap")
    await emit(store, up("close", 0, shift=4), generation=1)
    assert (generation(store), view(store)) == (1, ([0], None))  # the forming bar went too
    await emit(store, up("close", 7, shift=4), generation=0)
    assert (generation(store), view(store)) == (0, ([7], None))
    assert counted("bars_series_resets_total", "generation_swap") == before + 2


async def test_a_series_has_no_generation_until_its_first_emission() -> None:
    """Generations are opaque epochs (#2662): none is assumed, the first emission names it."""
    store = await held()
    before = counted("bars_series_resets_total", "generation_swap")
    assert generation(store) is None and view(store) == ([], None)
    await emit(store, up("open", 0), generation=7)
    assert (generation(store), view(store)) == (7, ([], 0))
    assert counted("bars_series_resets_total", "generation_swap") == before  # naming: no reset


@pytest.mark.parametrize(("kind", "after"), [("open", ([], 0)), ("close", ([0], None))])
async def test_sink_index_going_backwards_restarts_the_series(
    kind: str, after: tuple[list[int], int | None]
) -> None:
    """`index` going back within one generation means the builder restarted: clients key by it."""
    store = await held(*(up("close", i) for i in range(5)), up("open", 5))
    before = counted("bars_series_resets_total", "restart")
    await emit(store, up(kind, 0, shift=6))  # a new bar 0, opening after bar 5
    assert view(store) == after
    assert counted("bars_series_resets_total", "restart") == before + 1


@pytest.mark.parametrize(("kind", "after"), [("open", ([], 4)), ("close", ([4], None))])
async def test_sink_another_bar_at_the_newest_index_restarts_the_series(
    kind: str, after: tuple[list[int], int | None]
) -> None:
    """The boundary of both restart rules: a bar AT the newest closed index, opening later."""
    store = await held(*(up("close", i) for i in range(5)))
    before = counted("bars_series_resets_total", "restart")
    await emit(store, up(kind, 4, shift=1))
    assert view(store) == after
    assert counted("bars_series_resets_total", "restart") == before + 1


async def test_a_series_keeps_only_the_newest_max_history_closes() -> None:
    store = await held(*(up("close", i) for i in range(MAX_HISTORY + 5)))
    closed, _ = view(store, MAX_HISTORY + 5)  # ask for more than the series may hold
    assert len(closed) == MAX_HISTORY and closed[0] == 5 and closed[-1] == MAX_HISTORY + 4


async def test_untracked_series_is_ignored_and_reads_as_none() -> None:
    store = SeriesStore()
    await emit(store, up("close", 0))
    assert store.latest(SYM, H, 10) is None and store.version(SYM, H) == 0
    assert store.series_count() == 0 and store  # an empty store is not falsy


async def test_version_moves_on_every_change_only() -> None:
    store = await held()
    seen = [store.version(SYM, H)]
    for u in (up("open", 0), up("update", 0), up("close", 0), up("open", 1)):
        await emit(store, u)
        seen.append(store.version(SYM, H))
    assert seen == sorted(set(seen)) and seen[0] > 0
    await emit(store, up("close", 0, amended=True, shift=9))  # not held: no change
    assert store.version(SYM, H) == seen[-1]


async def test_latest_counts_the_forming_bar_inside_history() -> None:
    store = await held(*(up("close", i) for i in range(5)), up("open", 5))
    assert view(store, 3) == ([3, 4], 5)
    assert view(store, 1) == ([], 5)
    assert view(store, 0) == ([], None)


async def test_release_is_idempotent_per_hold() -> None:
    """A double release drops only its own hold: the other holder keeps the series."""
    clock = Clock()
    store = SeriesStore(clock=clock)
    mine, theirs = await store.ensure(SYM, SPEC), await store.ensure(SYM, SPEC)
    mine.release()
    mine.release()
    clock.t += RELEASE_GRACE_S
    _eth = await store.ensure("ETHUSDT", SPEC)  # sweeps every unheld series past its grace
    assert store.latest(SYM, H, 1) is not None
    theirs.release()
    clock.t += RELEASE_GRACE_S
    await store.ensure("SOLUSDT", SPEC)
    assert store.latest(SYM, H, 1) is None and store.series_count() == 2  # ETH and SOL


async def test_a_released_series_is_kept_current_through_its_grace() -> None:
    """US-MKT-005: a quick resubscribe finds the series as the sink kept it (the forming bar
    too, which no ring holds); held again, it outlives its old deadline."""
    clock = Clock()
    store = SeriesStore(clock=clock)
    (await store.ensure(SYM, SPEC)).release()
    clock.t += RELEASE_GRACE_S - 0.5
    await emit(store, up("close", 0), up("open", 1))
    await store.ensure(SYM, SPEC)
    assert view(store) == ([0], 1)
    clock.t += 1.0  # past the old deadline: held again, it is not swept
    await store.ensure("ETHUSDT", SPEC)
    assert store.latest(SYM, H, 1) is not None


async def test_an_expired_series_stops_counting_toward_the_cap_at_its_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(series_store, "MAX_SERIES", 1)
    clock = Clock()
    store = SeriesStore(clock=clock)
    (await store.ensure(SYM, SPEC)).release()
    clock.t += RELEASE_GRACE_S - 0.5
    with pytest.raises(SpecCapExceeded):  # in its grace it still counts, as in `SpecLeases`
        await store.ensure("ETHUSDT", SPEC)
    clock.t += 0.5
    await store.ensure("ETHUSDT", SPEC)  # this ensure sweeps it first
    assert store.latest(SYM, H, 1) is None and store.series_count() == 1


def refused() -> float:
    sample = REGISTRY.get_sample_value("bars_spec_cap_rejected_total", {"reason": "process-wide"})
    return float(sample or 0.0)


async def test_ensure_refuses_more_than_max_series_like_the_lease_layer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The process-wide cap's name and refusal counter are `SpecLeases`' own."""
    monkeypatch.setattr(series_store, "MAX_SERIES", 1)
    store = SeriesStore()
    await store.ensure(SYM, SPEC)
    await store.ensure(SYM, SPEC)  # the same series joins
    before = refused()
    with pytest.raises(SpecCapExceeded) as caught:
        await store.ensure("ETHUSDT", SPEC)
    assert (caught.value.cap, caught.value.limit, caught.value.active) == ("process-wide", 1, 1)
    assert refused() == before + 1 and store.series_count() == 1


async def test_a_hold_dropped_unreleased_frees_its_slot_once_collected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A vanished consumer cannot pin a slot: a collected hold is released as of its collection
    (the next `ensure` applies it), and a collection never frees a hold still referenced."""
    monkeypatch.setattr(series_store, "MAX_SERIES", 1)
    clock = Clock()
    store = SeriesStore(clock=clock)
    hold = await store.ensure(SYM, SPEC)
    gc.collect()
    clock.t += RELEASE_GRACE_S
    with pytest.raises(SpecCapExceeded):  # still referenced: still held
        await store.ensure("ETHUSDT", SPEC)
    del hold
    gc.collect()
    assert store._series[(SYM, H)].refs == 1  # white-box: the finalizer only queued it
    clock.t += RELEASE_GRACE_S - 1
    with pytest.raises(SpecCapExceeded):  # released as of the collection: in its grace
        await store.ensure("ETHUSDT", SPEC)
    clock.t += 1
    eth = await store.ensure("ETHUSDT", SPEC)
    assert store.latest(SYM, H, 1) is None and eth.symbol == "ETHUSDT"


async def test_a_released_hold_is_not_released_again_when_collected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`release` and the finalizer drop a hold once between them: the other holder keeps it."""
    monkeypatch.setattr(series_store, "MAX_SERIES", 1)
    clock = Clock()
    store = SeriesStore(clock=clock)
    mine, theirs = await store.ensure(SYM, SPEC), await store.ensure(SYM, SPEC)
    mine.release()
    del mine
    gc.collect()
    clock.t += RELEASE_GRACE_S
    with pytest.raises(SpecCapExceeded):
        await store.ensure("ETHUSDT", SPEC)
    theirs.release()
    clock.t += RELEASE_GRACE_S
    await store.ensure("ETHUSDT", SPEC)
    assert store.latest(SYM, H, 1) is None


async def test_the_grace_counts_from_the_latest_release_not_an_earlier_lost_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One hold is collected unreleased, the other released 50 s later: however late the queue
    is applied, the series keeps the whole grace from that later release (BR-38)."""
    monkeypatch.setattr(series_store, "MAX_SERIES", 1)
    clock = Clock()
    store = SeriesStore(clock=clock)
    lost, kept = await store.ensure(SYM, SPEC), await store.ensure(SYM, SPEC)
    del lost
    gc.collect()
    clock.t += 50
    kept.release()
    clock.t += RELEASE_GRACE_S - 0.5
    with pytest.raises(SpecCapExceeded):  # applies the queued release: still in the grace
        await store.ensure("ETHUSDT", SPEC)
    clock.t += 0.5
    await store.ensure("ETHUSDT", SPEC)
    assert store.latest(SYM, H, 1) is None


async def test_a_hold_released_without_grace_frees_its_slot_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hold that never reached its lease starts no grace: unheld, its series frees its slot at
    once, or when an earlier release's grace ends, which it neither extends nor shortens."""
    monkeypatch.setattr(series_store, "MAX_SERIES", 1)
    clock = Clock()
    store = SeriesStore(clock=clock)
    (await store.ensure(SYM, SPEC)).release(grace=False)
    (await store.ensure("ETHUSDT", SPEC)).release()  # at the same instant: the slot was free
    clock.t += 10
    (await store.ensure("ETHUSDT", SPEC)).release(grace=False)  # inside ETH's grace
    clock.t += RELEASE_GRACE_S - 10 - 0.5
    with pytest.raises(SpecCapExceeded):
        await store.ensure(SYM, SPEC)
    clock.t += 0.5  # the first release's grace ends
    await store.ensure(SYM, SPEC)
    assert store.latest("ETHUSDT", H, 1) is None


async def test_a_hold_released_without_grace_never_touches_another_holder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other holder keeps the series unexpiring; its own release then runs the whole grace."""
    monkeypatch.setattr(series_store, "MAX_SERIES", 1)
    clock = Clock()
    store = SeriesStore(clock=clock)
    refused, theirs = await store.ensure(SYM, SPEC), await store.ensure(SYM, SPEC)
    refused.release(grace=False)
    s = store._series[(SYM, H)]
    assert (s.refs, s.expires_at) == (1, None)  # white-box: still held, nothing armed
    clock.t += RELEASE_GRACE_S
    with pytest.raises(SpecCapExceeded):  # no slot for another series: still held
        await store.ensure("ETHUSDT", SPEC)
    assert store.latest(SYM, H, 1) is not None
    theirs.release()
    clock.t += RELEASE_GRACE_S - 0.5
    with pytest.raises(SpecCapExceeded):  # the full grace counts from this release
        await store.ensure("ETHUSDT", SPEC)
    clock.t += 0.5
    await store.ensure("ETHUSDT", SPEC)
    assert store.latest(SYM, H, 1) is None


async def test_a_new_hold_starts_from_the_last_16_closes_seen_before_it() -> None:
    """Live bars only: the closes the sink saw while nobody held the series. No ring holds the
    forming bar; the sink keeps the series current from there."""
    store = SeriesStore()
    await emit(store, *(up("close", i) for i in range(18)), up("open", 18))
    await store.ensure(SYM, SPEC)
    assert view(store) == (list(range(2, 18)), None)
    await emit(store, up("close", 18))
    assert view(store) == (list(range(2, 19)), None)


async def test_a_re_close_takes_its_bars_slot_in_the_ring_not_a_new_one() -> None:
    """The ring keeps the last 16 bars: an amended close replaces its original (as a plain close,
    so a new hold takes it as that bar's close) and a repeated one changes nothing."""
    store = SeriesStore()
    await emit(store, *(up("close", i) for i in range(RECENT_CLOSES)))
    await emit(store, up("close", 3, amended=True, close="103"), up("close", 9))
    await store.ensure(SYM, SPEC)
    assert view(store) == (list(range(RECENT_CLOSES)), None) and not store.gapped(SYM, H)
    assert closes(store)[3] == (3, "103")


async def test_a_new_hold_replays_its_recent_closes_by_the_sink_rules() -> None:
    """A builder restart among the closes seen before the hold drops the older run, as live;
    the replay counts no reset (the sink counted none: nobody held the series)."""
    store = SeriesStore()
    await emit(store, *(up("close", i, shift=-30) for i in range(4)))
    await emit(store, *(up("close", i) for i in range(2)))  # the new run reuses indexes 0 and 1
    before = counted("bars_series_resets_total", "restart")
    await store.ensure(SYM, SPEC)
    assert view(store) == ([0, 1], None)
    assert counted("bars_series_resets_total", "restart") == before


async def test_only_the_newest_generations_recent_closes_start_a_hold() -> None:
    """A swap among the closes seen before the hold: the earlier generation's are not the
    series' bars, not even a twin at the same index and open time (an ADR-0033 rebuild's)."""
    store = SeriesStore()
    await emit(store, up("close", 0), up("close", 1))
    await emit(store, up("close", 0), generation=1)
    before = counted("bars_series_resets_total", "generation_swap")
    await store.ensure(SYM, SPEC)
    assert generation(store) == 1 and view(store) == ([0], None)
    assert counted("bars_series_resets_total", "generation_swap") == before  # a replay counts none


async def test_recent_closes_are_kept_for_max_series_least_recently_closed_dropped_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(series_store, "MAX_SERIES", 2)
    eth = "ETHUSDT"
    store = SeriesStore()
    for u in (up("close", 1), up("close", 1, sym=eth), up("close", 2), up("close", 1, sym="SOL")):
        await emit(store, u)  # BTC closed again after ETH: SOL's ring displaces ETH's
    await store.ensure(SYM, SPEC)
    await store.ensure(eth, SPEC)
    assert view(store) == ([1, 2], None) and view(store, sym=eth) == ([], None)


class Tail:
    """`TailRead` fake: counts calls, blocks until `gate` is set, then returns `tail` or raises."""

    def __init__(
        self,
        bars: Sequence[tuple[int, Bar]] = (),
        *,
        error: Exception | None = None,
        now: bool = False,
    ) -> None:
        self.tail, self.error, self.calls = BarTail(list(bars)), error, 0
        self.gate, self.started = asyncio.Event(), asyncio.Event()
        if now:
            self.gate.set()

    async def __call__(self, symbol: str, spec: BarSpec, limit: int) -> BarTail:
        assert (spec, limit) == (SPEC, MAX_HISTORY)
        self.calls += 1
        self.started.set()
        await self.gate.wait()
        if self.error is not None:
            raise self.error
        return self.tail


def rows(*indexes: int, gen: int = 0, shift: int = 0) -> list[tuple[int, Bar]]:
    return [(gen, bar(i, shift=shift)) for i in indexes]


def events(logs: Sequence[Mapping[str, object]], name: str) -> list[Mapping[str, object]]:
    return [e for e in logs if e["event"] == name]


async def test_concurrent_ensure_waits_for_the_one_hydration() -> None:
    tail = Tail(rows(0))
    store = SeriesStore(tail)
    first = asyncio.create_task(store.ensure(SYM, SPEC))
    await tail.started.wait()
    second = asyncio.create_task(store.ensure(SYM, SPEC))
    await asyncio.sleep(0)  # let the second ensure reach its wait (a yield, not a delay)
    assert not second.done()
    tail.gate.set()
    await first
    await asyncio.wait_for(second, 1.0)  # a bound, not a delay
    assert tail.calls == 1 and view(store) == ([0], None)


async def test_version_moves_when_a_read_lands() -> None:
    """A snapshot cached while the read was in flight must not outlive it."""
    tail = Tail(rows(0))
    store = SeriesStore(tail)
    task = asyncio.create_task(store.ensure(SYM, SPEC))
    await tail.started.wait()
    before = store.version(SYM, H)
    tail.gate.set()
    await task
    assert store.version(SYM, H) > before


@pytest.mark.parametrize(
    ("error", "error_type", "reason"),
    [(OSError("questdb down"), "OSError", "connection"),
     (RuntimeError("bad query " * 20), "RuntimeError", "query_error"),
     (None, "TimeoutError", "timeout")],
    ids=["os-error", "any-error", "timeout"],
)  # fmt: skip
async def test_a_failed_or_timed_out_read_leaves_the_series_live_and_says_so(
    error: Exception | None, error_type: str, reason: str
) -> None:
    tail = Tail(error=error, now=error is not None)  # a hung read meets the (zero) timeout
    store = SeriesStore(tail, timeout_s=5.0 if error else 0.0)
    before = counted("bars_series_hydrate_failed_total", reason)
    with capture_logs() as logs:
        async with asyncio.timeout(1.0):  # a bound: a lost store timeout fails here, not hangs
            await store.ensure(SYM, SPEC)
    await emit(store, up("close", 4), up("open", 5))
    assert view(store) == ([4], 5) and not store.hydrated(SYM, H) and not store.gapped(SYM, H)
    assert events(logs, "bars_series_hydrate_failed") == [{
        "event": "bars_series_hydrate_failed", "log_level": "warning", "spec_hash": H,
        "symbol": SYM, "error_type": error_type, "error": str(error or "")[:120],
    }]  # fmt: skip
    assert counted("bars_series_hydrate_failed_total", reason) == before + 1


async def test_a_failed_read_is_read_again_by_an_ensure_retry_after_s_later() -> None:
    """One QuestDB blip must not leave a series history-less for its whole hold."""
    clock = Clock()
    tail = Tail(error=OSError("questdb down"), now=True)
    store = SeriesStore(tail, clock=clock)
    await store.ensure(SYM, SPEC)
    clock.t += RETRY_AFTER_S - 0.5
    await store.ensure(SYM, SPEC)
    assert tail.calls == 1 and not store.hydrated(SYM, H)
    tail.error, tail.tail = None, BarTail(rows(0))
    clock.t += 0.5  # exactly `retry_after_s` after the failed read
    await store.ensure(SYM, SPEC)
    assert tail.calls == 2 and store.hydrated(SYM, H) and view(store) == ([0], None)


async def test_a_cancelled_first_ensure_hands_its_read_to_a_waiter() -> None:
    """A client's disconnect must not leave another's series history-less: the waiter reads
    again, keeps a close seen during the abandoned read, and the cancelled one holds nothing."""
    clock = Clock()
    tail = Tail(rows(0))
    store = SeriesStore(tail, clock=clock)
    first = asyncio.create_task(store.ensure(SYM, SPEC))
    await tail.started.wait()
    second = asyncio.create_task(store.ensure(SYM, SPEC))
    await asyncio.sleep(0)  # the second reaches its wait (a yield, not a delay)
    await emit(store, up("close", 1))  # not stored yet; the abandoned read's replay goes
    tail.started.clear()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert store._series[(SYM, H)].refs == 1  # released at once, not left to the finalizer
    await asyncio.wait_for(tail.started.wait(), 1.0)  # the waiter's own read (a bound)
    tail.gate.set()
    hold = await asyncio.wait_for(second, 1.0)
    assert tail.calls == 2 and store.hydrated(SYM, H) and view(store) == ([0, 1], None)
    hold.release()  # the last hold: the cancelled ensure took none with it
    clock.t += RELEASE_GRACE_S
    await store.ensure("ETHUSDT", SPEC)
    assert store.latest(SYM, H, 1) is None


async def test_a_cancelled_ensure_starts_no_grace_of_its_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hold that never reached its lease frees its slot at once: the series an `ensure` created
    and was cancelled mid-read on is gone for the next series, at the same instant."""
    monkeypatch.setattr(series_store, "MAX_SERIES", 1)
    tail = Tail()  # its read waits on the gate
    store = SeriesStore(tail, clock=Clock())
    task = asyncio.create_task(store.ensure(SYM, SPEC))
    await tail.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    tail.gate.set()  # the next series reads freely
    await store.ensure("ETHUSDT", SPEC)
    assert store.latest(SYM, H, 1) is None


async def test_waiters_share_the_read_that_replaces_a_cancelled_one() -> None:
    """The second waiter waits for the first waiter's read instead of starting a third."""
    tail = Tail(rows(0))
    store = SeriesStore(tail)
    first = asyncio.create_task(store.ensure(SYM, SPEC))
    await tail.started.wait()
    waiters = [asyncio.create_task(store.ensure(SYM, SPEC)) for _ in range(2)]
    await asyncio.sleep(0)  # both reach their wait (a yield, not a delay)
    tail.started.clear()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    await asyncio.wait_for(tail.started.wait(), 1.0)  # a waiter's read is in flight
    tail.gate.set()
    await asyncio.wait_for(asyncio.gather(*waiters), 1.0)
    assert tail.calls == 2 and store.hydrated(SYM, H) and view(store) == ([0], None)


async def test_each_read_waits_on_a_fresh_unset_event() -> None:
    """A waiter on an event the last read left set would spin and freeze the loop (white-box)."""
    tail = Tail(now=True)
    tail.tail = BarTail(rows(0), dropped=1)  # degraded: the next ensure reads again
    store = SeriesStore(tail, retry_after_s=0.0)
    await store.ensure(SYM, SPEC)
    tail.gate.clear()
    task = asyncio.create_task(store.ensure(SYM, SPEC))
    await asyncio.sleep(0)  # the second read starts (a yield, not a delay)
    assert tail.calls == 2 and not store._series[(SYM, H)].ready.is_set()
    tail.gate.set()
    await task


async def test_a_cancelled_lone_read_does_not_hold_off_the_next_ensure() -> None:
    """A cancellation is not a completed read: the next `ensure` reads at once."""
    tail = Tail(rows(0))
    store = SeriesStore(tail, clock=Clock())
    task = asyncio.create_task(store.ensure(SYM, SPEC))
    await tail.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    tail.gate.set()
    await store.ensure(SYM, SPEC)
    assert tail.calls == 2 and store.hydrated(SYM, H)


@pytest.mark.parametrize(("degraded", "reads"), [(False, 1), (True, 2)], ids=["failed", "degraded"])
async def test_a_waiter_keeps_a_failed_read_but_reads_a_degraded_one_again(
    degraded: bool, reads: int
) -> None:
    """A failed read completed: its waiters keep the result. A degraded read is never final
    (SR-E12-11): a waiter reads again as soon as `retry_after_s` allows (0 here)."""
    tail = Tail(error=None if degraded else OSError("questdb down"))
    tail.tail = BarTail(rows(0), dropped=1)
    store = SeriesStore(tail, retry_after_s=0.0)
    first = asyncio.create_task(store.ensure(SYM, SPEC))
    await tail.started.wait()
    second = asyncio.create_task(store.ensure(SYM, SPEC))
    await asyncio.sleep(0)  # the second reaches its wait (a yield, not a delay)
    tail.gate.set()
    await first
    await asyncio.wait_for(second, 1.0)
    assert tail.calls == reads


async def test_a_degraded_read_is_served_but_not_final_and_is_read_again_later() -> None:
    """SR-E12-11: a tail missing integrity-dropped rows is served, not `hydrated`, and read again
    `retry_after_s` later. A hole inside the rows is not a gap."""
    clock = Clock()
    tail = Tail(now=True)
    tail.tail = BarTail(rows(0, 2), dropped=1)
    store = SeriesStore(tail, clock=clock)
    with capture_logs() as logs:
        await store.ensure(SYM, SPEC)
    assert view(store) == ([0, 2], None) and not store.hydrated(SYM, H)
    assert not store.gapped(SYM, H) and events(logs, "bars_series_hydrate_degraded") == [{
        "event": "bars_series_hydrate_degraded", "log_level": "warning", "spec_hash": H,
        "symbol": SYM, "dropped": 1,
    }]  # fmt: skip
    clock.t += RETRY_AFTER_S - 0.5
    await store.ensure(SYM, SPEC)
    assert tail.calls == 1
    tail.tail = BarTail(rows(0, 1, 2))
    clock.t += 0.5
    await store.ensure(SYM, SPEC)
    assert tail.calls == 2 and store.hydrated(SYM, H) and view(store) == ([0, 1, 2], None)


async def test_closes_emitted_just_before_the_hold_fill_the_junction() -> None:
    """The review's case: rows 0..9 are stored; closes 10 and 11 were emitted before the hold but
    are not queryable yet; an amended close of stored bar 8, 12 and the forming 13 arrive during
    the read. No hole and no gap warning; bar 8 takes its amended close."""
    tail = Tail(rows(*range(10)))
    store = SeriesStore(tail)
    await emit(store, up("close", 10), up("close", 11))  # nobody holds the series yet
    task = asyncio.create_task(store.ensure(SYM, SPEC))
    await tail.started.wait()
    with capture_logs() as logs:
        await emit(store, up("close", 8, amended=True, close="108"), up("close", 12))
        await emit(store, up("open", 13))
        tail.gate.set()
        await task
    assert view(store) == (list(range(13)), 13) and store.hydrated(SYM, H)
    assert closes(store)[8] == (8, "108") and not store.gapped(SYM, H)
    assert not events(logs, "bars_series_gap")


async def test_more_closes_during_the_read_than_the_ring_keeps_leave_no_gap() -> None:
    """Beyond the ring's 16, the read's replay keeps every close seen during it, in order."""
    tail = Tail(rows(*range(10)))
    store = SeriesStore(tail)
    task = asyncio.create_task(store.ensure(SYM, SPEC))
    await tail.started.wait()
    await emit(store, *(up("close", i) for i in range(10, 14 + RECENT_CLOSES)))
    tail.gate.set()
    await task
    assert view(store)[0] == list(range(30)) and store.hydrated(SYM, H) and not store.gapped(SYM, H)


async def test_the_closes_seen_during_a_read_are_bounded_and_the_oldest_are_shed() -> None:
    """C-2.18: a burst bigger than `MAX_HISTORY` during a read keeps the newest closes."""
    tail = Tail(rows(0))
    store = SeriesStore(tail)
    task = asyncio.create_task(store.ensure(SYM, SPEC))
    await tail.started.wait()
    await emit(store, *(up("close", i) for i in range(1, MAX_HISTORY + 51)))
    replay = store._series[(SYM, H)].replay  # white-box: the bound itself
    assert replay is not None and len(replay) == MAX_HISTORY and replay[0][0].bar.index == 51
    tail.gate.set()
    await task
    closed, _ = view(store)
    assert len(closed) == MAX_HISTORY and closed[-1] == MAX_HISTORY + 50


async def test_a_jump_past_the_recent_closes_flags_a_gap_that_the_next_read_heals() -> None:
    """More closes than the ring keeps went unstored before the hold: the fold flags the jump
    once, and an `ensure` `retry_after_s` later reads the rows the writer has landed by then."""
    clock = Clock()
    tail = Tail(rows(*range(10)), now=True)
    store = SeriesStore(tail, clock=clock)
    await emit(store, *(up("close", i) for i in range(10, 14 + RECENT_CLOSES)))
    before = counted("bars_series_gaps_total")
    with capture_logs() as logs:
        await store.ensure(SYM, SPEC)
    assert store.gapped(SYM, H) and view(store)[0] == [*range(10), *range(14, 30)]
    assert counted("bars_series_gaps_total") == before  # a read's fold: no live close skipped
    assert events(logs, "bars_series_gap") == [{
        "event": "bars_series_gap", "log_level": "warning", "spec_hash": H, "symbol": SYM,
        "from_index": 10, "to_index": 13,
    }]  # fmt: skip
    tail.tail = BarTail(rows(*range(30)))
    clock.t += RETRY_AFTER_S
    await store.ensure(SYM, SPEC)
    assert tail.calls == 2 and not store.gapped(SYM, H) and view(store)[0] == list(range(30))


async def test_a_re_read_keeps_the_live_bars_storage_still_lacks() -> None:
    """The writer still lags at the second read: the bars the series held stay (#2666 r2)."""
    clock = Clock()
    tail = Tail(rows(*range(10)), now=True)
    store = SeriesStore(tail, clock=clock)
    await emit(store, *(up("close", i) for i in range(10, 30)))
    await store.ensure(SYM, SPEC)  # bars 10..13 are missing: gapped
    await emit(store, *(up("close", i) for i in range(30, 50)))
    clock.t += RETRY_AFTER_S
    await store.ensure(SYM, SPEC)  # storage still ends at 9
    assert (tail.calls, view(store)[0]) == (2, [*range(10), *range(14, 50)])


@pytest.mark.parametrize("amended", [2, 4], ids=["inner-row", "newest-row"])
@pytest.mark.parametrize("clean", [False, True], ids=["degraded", "clean"])
async def test_a_re_read_keeps_a_live_amendment_the_ring_has_rolled_out(
    clean: bool, amended: int
) -> None:
    """A held bar replaces its stored twin: its amended close has left the 16-close ring and the
    writer still holds the original. A degraded re-read merges an inner row's twin (bar 2) into
    its rows; the newest row's twin (bar 4), and every twin on a clean re-read, is put over its
    row after the rows. A clean re-read ends `hydrated`: a stale twin would be served as final."""
    clock = Clock()
    tail = Tail(now=True)
    tail.tail = BarTail(rows(*range(5)), dropped=1)  # degraded: the next ensure reads again
    store = SeriesStore(tail, clock=clock)
    await store.ensure(SYM, SPEC)
    await emit(store, up("close", amended, amended=True, close="102"))
    await emit(store, *(up("close", i) for i in range(5, 5 + 2 * RECENT_CLOSES)))
    if clean:
        tail.tail = BarTail(rows(*range(5)))
    clock.t += RETRY_AFTER_S
    await store.ensure(SYM, SPEC)
    assert tail.calls == 2 and closes(store)[amended] == (amended, "102")
    assert store.hydrated(SYM, H) == clean


@pytest.mark.parametrize(
    ("stored", "rebuilt", "served", "gap"),
    [(12, [], list(range(12)), False), (10, [], [*range(10), 11], True),
     (10, [(7, bar(12))], [*range(10), 11], True)],
    ids=["landed", "lagging", "lagging-rebuild-ahead"],
)  # fmt: skip
async def test_a_degraded_re_read_keeps_a_held_bar_whose_row_it_withheld(
    stored: int, rebuilt: list[tuple[int, Bar]], served: list[int], gap: bool
) -> None:
    """D2-H1b: rows 0..9 are held and a live close at 11 flags a gap; the re-read withholds row 5
    (SR-E12-11) and returns 0..4 and 6..11 (or 6..9: the writer still lags). Bar 5, which the
    store holds, is still served, a gap still open stays flagged, and the series stays not
    `hydrated`: it is read again later. An unflipped rebuild's row newer than bar 11 (generation
    7) moves no bound: the merge stops at the series' own newest row, so bar 11 is still checked
    for the gap below it."""
    clock = Clock()
    tail = Tail(rows(*range(10)), now=True)
    store = SeriesStore(tail, clock=clock)
    await store.ensure(SYM, SPEC)
    await emit(store, up("close", 11))
    assert store.gapped(SYM, H)
    tail.tail = BarTail([*rows(*range(5), *range(6, stored)), *rebuilt], dropped=1)
    clock.t += RETRY_AFTER_S
    await store.ensure(SYM, SPEC)
    assert (tail.calls, view(store)[0], store.gapped(SYM, H)) == (2, served, gap)
    assert not store.hydrated(SYM, H)


@pytest.mark.parametrize(
    "reread",
    [BarTail([], dropped=3), BarTail(rows(0, 1, gen=7), dropped=1)],
    ids=["every-row-withheld", "only-another-generations-rows"],
)
async def test_a_degraded_re_read_with_no_row_of_the_series_keeps_every_held_bar(
    reread: BarTail,
) -> None:
    """D2-H1b with nothing to merge into: a page-wide checksum failure withholds every row
    (SR-E12-11), or the read finds only another generation's (an unflipped rebuild's). The
    `ensure` raises nothing, every held bar stays, the gap at 10 stays flagged, and the series
    stays not `hydrated`."""
    clock = Clock()
    tail = Tail(rows(*range(10)), now=True)
    store = SeriesStore(tail, clock=clock)
    await store.ensure(SYM, SPEC)
    await emit(store, up("close", 11))
    tail.tail = reread
    clock.t += RETRY_AFTER_S
    await store.ensure(SYM, SPEC)
    assert (tail.calls, generation(store), view(store)[0]) == (2, 0, [*range(10), 11])
    assert store.gapped(SYM, H) and not store.hydrated(SYM, H)


async def test_a_degraded_re_read_keeps_a_withheld_bar_among_bars_sharing_an_open_time() -> None:
    """D2-H1b merges by `(open_time, index)`: non-time bars can share an open time (renko bricks),
    so held bar 7 goes between rows 6 and 8. After row 9 it would read as a restart and drop 6."""
    clock = Clock()
    shared = [(0, bar(i, shift=6 - i)) for i in range(6, 10)]  # bars 6..9 open at once
    tail = Tail(now=True)
    tail.tail = BarTail(shared, dropped=1)  # degraded: the next ensure reads again
    store = SeriesStore(tail, clock=clock)
    await store.ensure(SYM, SPEC)
    tail.tail = BarTail([shared[0], *shared[2:]], dropped=1)  # row 7 withheld
    clock.t += RETRY_AFTER_S
    await store.ensure(SYM, SPEC)
    assert (tail.calls, view(store)) == (2, ([6, 7, 8, 9], None))


async def test_a_degraded_re_read_over_two_stored_runs_drops_the_older_runs_held_bars() -> None:
    """Legacy generation-0 history can hold two runs (a cold start reused `index`). The first read
    withheld the newer run's rows, so the store holds the older run's bars; the re-read returns
    the newer run. Merged by `(open_time, index)`, the held bars sort before it, and its first row
    restarts the series and drops them, as with no merge: only the newer run is served."""
    clock = Clock()
    older, newer = rows(*range(10)), [(0, bar(i, shift=20, close="120")) for i in (0, 1)]
    tail = Tail(now=True)
    tail.tail = BarTail(older, dropped=2)  # the newer run's rows are withheld
    store = SeriesStore(tail, clock=clock)
    await store.ensure(SYM, SPEC)
    tail.tail = BarTail([*older[:5], *older[6:], *newer], dropped=1)  # row 5 withheld
    clock.t += RETRY_AFTER_S
    await store.ensure(SYM, SPEC)
    assert (tail.calls, closes(store)) == (2, [(0, "120"), (1, "120")])


async def test_held_bars_of_a_newer_run_than_the_rows_keep_their_gap_check() -> None:
    """The store holds the newer run (a cold start seen live, with a gap at 2), and the re-read
    withholds that run's rows, so its newest row is the older run's bar 9. The held bars opened
    after it: they are folded after the rows by the gap rules, not merged into them by `index`
    below 9. The first restarts the series, and the hole at 2 stays flagged."""
    clock = Clock()
    tail = Tail(now=True)
    tail.tail = BarTail(rows(*range(10)), dropped=1)  # degraded: the next ensure reads again
    store = SeriesStore(tail, clock=clock)
    await store.ensure(SYM, SPEC)
    await emit(store, *(up("close", i, shift=20, close="120") for i in (0, 1, 3)))
    tail.tail = BarTail(rows(*range(10)), dropped=2)  # the newer run's rows 0 and 1 withheld
    clock.t += RETRY_AFTER_S
    await store.ensure(SYM, SPEC)
    assert (tail.calls, closes(store)) == (2, [(0, "120"), (1, "120"), (3, "120")])
    assert store.gapped(SYM, H) and not store.hydrated(SYM, H)


@pytest.mark.parametrize("other", [7, 3], ids=["higher", "lower"])
async def test_a_re_read_never_replaces_the_generation_a_series_names(other: int) -> None:
    """Only an emission swaps a kept series' generation, so the publisher sees every swap: a
    re-read keeps the one an earlier read named, and skips the newer rows of another one."""
    tail = Tail(now=True)
    tail.tail = BarTail(rows(0, 1, gen=5), dropped=1)  # degraded: the next ensure reads again
    store = SeriesStore(tail, retry_after_s=0.0)
    await store.ensure(SYM, SPEC)
    tail.tail = BarTail([*rows(0, 1, gen=5), (other, bar(0, shift=2))])  # the newest row
    await store.ensure(SYM, SPEC)
    assert (generation(store), view(store), store.hydrated(SYM, H)) == (5, ([0, 1], None), True)
    await emit(store, up("open", 1, shift=2), generation=other)  # its builder's next emission
    assert (generation(store), view(store), store.hydrated(SYM, H)) == (other, ([], 1), False)


async def test_a_close_sharing_the_newest_rows_open_time_is_kept() -> None:
    """Non-time bars can share an open time (renko bricks): live closes are ordered by key."""
    store = SeriesStore(Tail(rows(6, 7, 8), now=True))
    await emit(store, up("close", 9, shift=-1))  # opens with bar 8, not stored yet
    await store.ensure(SYM, SPEC)
    assert view(store) == ([6, 7, 8, 9], None) and not store.gapped(SYM, H)


async def test_a_restarted_run_outranks_the_old_run_still_stored_by_open_time() -> None:
    """Held bars compare by `(open_time, index)`: the restart opens later with `index` back at 0,
    so the old run's rows (index 0..9) must not outrank it."""
    store = SeriesStore(Tail(rows(*range(10)), now=True))
    await emit(store, up("close", 0, shift=20), up("close", 1, shift=20))
    before = counted("bars_series_resets_total", "restart")
    await store.ensure(SYM, SPEC)
    assert view(store) == ([0, 1], None) and store.hydrated(SYM, H) and not store.gapped(SYM, H)
    assert counted("bars_series_resets_total", "restart") == before  # the fold counts no reset


async def test_the_first_emission_after_an_empty_read_is_not_a_swap() -> None:
    """Naming a first generation is not a change of one (23 §8.2): no stored row is left to read."""
    store = SeriesStore(Tail(now=True))
    await store.ensure(SYM, SPEC)
    await emit(store, up("close", 0), generation=3)
    assert (store.hydrated(SYM, H), generation(store), view(store)) == (True, 3, ([0], None))


async def test_a_live_generation_swap_after_the_read_leaves_it_not_hydrated() -> None:
    """ADR-0033: the new generation's history is in storage, so the series is read again."""
    store = SeriesStore(Tail(rows(0, 1), now=True))
    await store.ensure(SYM, SPEC)
    await emit(store, up("close", 0, shift=5), generation=1)
    assert (store.hydrated(SYM, H), generation(store), view(store)) == (False, 1, ([0], None))


async def test_a_live_close_that_skips_an_index_after_the_read_flags_a_gap() -> None:
    """Nothing was seen live around a quiet read: the first close past a missing one shows it."""
    store = SeriesStore(Tail(rows(*range(10)), now=True))
    await store.ensure(SYM, SPEC)
    before = counted("bars_series_gaps_total")
    with capture_logs() as logs:
        await emit(store, up("update", 11), up("close", 11))
    assert store.gapped(SYM, H) and view(store) == ([*range(10), 11], None)
    assert [(e["from_index"], e["to_index"]) for e in events(logs, "bars_series_gap")] == [(10, 10)]
    assert counted("bars_series_gaps_total") == before + 1


async def test_a_first_close_above_0_after_an_empty_read_is_a_gap_a_re_read_heals() -> None:
    """D2-H1a: a series read clean and empty holds no bar, so a first live close at index 20
    skips 0..19, in the builder's order (the bar opens and updates first). Read again while the
    writer still lags, it stays gapped; once the writer has landed 0..20, an `ensure`
    its re-read interval later serves them."""
    clock = Clock()
    tail = Tail(now=True)  # an empty read
    store = SeriesStore(tail, clock=clock)
    await store.ensure(SYM, SPEC)
    before = counted("bars_series_gaps_total")
    with capture_logs() as logs:
        await emit(store, up("open", 20))
        await emit(store, up("update", 20))
        await emit(store, up("close", 20), up("open", 21))
    assert store.gapped(SYM, H) and view(store) == ([20], 21)
    assert [(e["from_index"], e["to_index"]) for e in events(logs, "bars_series_gap")] == [(0, 19)]
    assert counted("bars_series_gaps_total") == before + 1
    clock.t += RETRY_AFTER_S
    await store.ensure(SYM, SPEC)  # storage is still empty: the gap stays
    assert (tail.calls, view(store), store.gapped(SYM, H)) == (2, ([20], 21), True)
    tail.tail = BarTail(rows(*range(21)))  # the writer has landed 0..20
    clock.t += 2 * RETRY_AFTER_S  # that re-read left it gapped: its interval doubled (D2-H2)
    await store.ensure(SYM, SPEC)
    assert (tail.calls, view(store)[0], store.gapped(SYM, H)) == (3, list(range(21)), False)


@pytest.mark.parametrize(("after_open_us", "gap"), [(1, False), (0, True)], ids=["after", "at"])
async def test_a_first_close_after_an_empty_read_is_a_gap_only_if_it_opened_in_the_window(
    after_open_us: int, gap: bool
) -> None:
    """D2-H1a: a clean empty read says only that no row lies in its window, which takes the rows
    that opened at or after `since_us`. A restored builder keeps its index, so after a long
    downtime its first close can be bar 500, which opened before that window (here 1 µs before
    it, and closed inside it): the bars below it opened earlier still, outside every read, so it
    is no gap. A bar that opened at the window's start lies inside it: a gap from index 0."""
    tail = Tail(now=True)
    tail.tail = BarTail([], since_us=T0 + 500 * STEP + after_open_us)  # bar 500's open, or 1 µs on
    store = SeriesStore(tail)
    await store.ensure(SYM, SPEC)
    before = counted("bars_series_gaps_total")
    with capture_logs() as logs:
        await emit(store, up("update", 500))
        await emit(store, up("close", 500), up("open", 501))
    assert view(store) == ([500], 501) and store.gapped(SYM, H) == gap
    logged = [(e["from_index"], e["to_index"]) for e in events(logs, "bars_series_gap")]
    assert logged == ([(0, 499)] if gap else [])
    assert counted("bars_series_gaps_total") == before + gap


async def test_empty_re_reads_keep_a_gap_until_a_window_starts_after_its_bar_opened() -> None:
    """D2-H1a over clean empty reads while the writer never lands bars 0..19. Bar 20 opened inside
    R1's window: a gap. R2's window starts after bar 20 opened, but R2's fold judges by R1's (the
    read `hydrated` came from), so the gap stays; R3's fold judges by R2's and clears it. Then the
    series is `hydrated` and not `gapped`, so a later `ensure` reads nothing."""
    clock = Clock()
    tail = Tail(now=True)
    tail.tail = BarTail([], since_us=T0)  # R1: bar 20 opens inside its window
    store = SeriesStore(tail, clock=clock)
    await store.ensure(SYM, SPEC)
    await emit(store, up("open", 20))
    await emit(store, up("close", 20), up("open", 21))
    seen = [store.gapped(SYM, H)]
    for start in (21, 22, 23):  # R2 and R3 start after bar 20 opened; the last ensure reads none
        tail.tail = BarTail([], since_us=T0 + start * STEP)
        clock.t += 2 * RETRY_AFTER_S  # R2 leaves it gapped: R3 waits twice as long (D2-H2)
        await store.ensure(SYM, SPEC)
        seen.append(store.gapped(SYM, H))
    assert (tail.calls, seen, view(store)) == (3, [True, True, False, False], ([20], 21))


async def test_index_0_is_next_after_an_empty_read_so_closes_0_and_1_are_no_gap_and_3_is() -> None:
    """D2-H1a's boundary: on a series read clean and empty, a first close at 0 skips nothing."""
    store = SeriesStore(Tail(now=True))
    await store.ensure(SYM, SPEC)
    before = counted("bars_series_gaps_total")
    await emit(store, up("close", 0))
    await emit(store, up("close", 1))
    assert not store.gapped(SYM, H) and counted("bars_series_gaps_total") == before
    await emit(store, up("close", 3))
    assert store.gapped(SYM, H) and counted("bars_series_gaps_total") == before + 1


async def test_an_older_close_the_rows_lack_is_not_mistaken_for_a_restart() -> None:
    """A row the writer missed, or the run before a cold start, sits in the recent closes. Folded
    after newer rows it must not reset the series; the hole stays as storage has it."""
    tail = Tail([*rows(0, 1, 2, 4)], now=True)
    store = SeriesStore(tail)
    await emit(store, up("close", 7, shift=-10), up("close", 3), up("close", 4))
    await store.ensure(SYM, SPEC)
    assert view(store) == ([0, 1, 2, 4], None) and not store.gapped(SYM, H)


async def test_hydration_keeps_the_live_generations_rows_over_another_epochs() -> None:
    """A cold start after a clock regression (#2662) can take a lower generation than the epoch
    before it. Seen live, its generation decides: its stored rows stay, the old epoch's go."""
    tail = Tail([*rows(0, 1, gen=5), *rows(0, 1, gen=3, shift=5)], now=True)
    store = SeriesStore(tail)
    await emit(store, up("close", 2, shift=5), generation=3)  # the live builder, before the hold
    await store.ensure(SYM, SPEC)
    assert generation(store) == 3 and view(store) == ([0, 1, 2], None)


async def test_an_unflipped_rebuilds_rows_do_not_displace_the_live_generations() -> None:
    """ADR-0033 rebuild rows (a higher generation, not live yet) share the read's window: the
    rows kept are the live generation's, not the newest row's."""
    rebuilt = [(7, bar(i, close="107")) for i in (0, 1)]
    twins = sorted([*rows(0, 1), *rebuilt], key=lambda r: (r[1].open_time, r[0]))
    store = SeriesStore(Tail(twins, now=True))
    await emit(store, up("close", 2))  # the live builder, generation 0
    await store.ensure(SYM, SPEC)
    assert generation(store) == 0 and closes(store) == [(0, "100"), (1, "100"), (2, "100")]


async def test_only_the_newest_generations_recent_closes_are_folded() -> None:
    """A swap among the closes seen live: the earlier generation's are not the series' bars. The
    swap came before the read, which clears D2-H1c's flag as it starts, so the read hydrates."""
    store = SeriesStore(Tail(now=True))
    await emit(store, up("close", 5))
    await emit(store, up("close", 7), generation=1)
    await store.ensure(SYM, SPEC)
    assert generation(store) == 1 and view(store) == ([7], None) and not store.gapped(SYM, H)
    assert store.hydrated(SYM, H)


async def test_an_old_generations_close_never_overwrites_a_bar_of_the_new_one() -> None:
    """A replayed close of the old generation that shares a stored bar's key is not that bar."""
    store = SeriesStore(Tail(rows(0, gen=1), now=True))
    await emit(store, up("close", 0, close="90"))  # generation 0
    await emit(store, up("close", 1), generation=1)
    await store.ensure(SYM, SPEC)
    assert generation(store) == 1 and closes(store) == [(0, "100"), (1, "100")]


async def test_a_generation_swap_during_the_read_keeps_only_the_new_generation() -> None:
    """The live builder moved to generation 1 (an `open`) while the read was in flight: the
    stored rows and the earlier closes are generation 0, so only the forming bar remains."""
    tail = Tail(rows(*range(3)))
    store = SeriesStore(tail)
    await emit(store, up("close", 3))
    task = asyncio.create_task(store.ensure(SYM, SPEC))
    await tail.started.wait()
    await emit(store, up("open", 0, shift=9), generation=1)
    tail.gate.set()
    await task
    assert generation(store) == 1 and view(store) == ([], 0) and not store.hydrated(SYM, H)


async def test_a_swap_after_the_first_naming_inside_a_first_read_leaves_it_not_hydrated() -> None:
    """D2-H1c: no generation is named when the read starts; the live builder names 3, then swaps
    to 4, while the read is in flight. Its rows are 3's, so the series is read again, for 4's."""
    clock = Clock()
    tail = Tail(rows(0, 1, gen=3))
    store = SeriesStore(tail, clock=clock)
    task = asyncio.create_task(store.ensure(SYM, SPEC))
    await tail.started.wait()
    await emit(store, up("close", 2), generation=3)  # the first naming: not a swap
    await emit(store, up("close", 0, shift=5), generation=4)  # a swap
    tail.gate.set()
    await task
    assert (generation(store), view(store), store.hydrated(SYM, H)) == (4, ([0], None), False)
    tail.tail = BarTail(rows(0, 1, gen=4, shift=5))
    clock.t += RETRY_AFTER_S
    await store.ensure(SYM, SPEC)
    assert (tail.calls, view(store), store.hydrated(SYM, H)) == (2, ([0, 1], None), True)


async def test_a_read_after_a_live_swap_between_reads_hydrates_the_new_generation() -> None:
    """D2-H1c's flag is cleared as a read starts: a swap after one read ended only sends the series
    to be read again, and that read, which no swap interrupts, hydrates it."""
    clock = Clock()
    tail = Tail(rows(0, 1), now=True)
    store = SeriesStore(tail, clock=clock)
    await store.ensure(SYM, SPEC)
    await emit(store, up("close", 0, shift=5), generation=1)  # the swap: read again
    assert not store.hydrated(SYM, H)
    tail.tail = BarTail(rows(0, 1, gen=1, shift=5))  # the new generation's rows
    clock.t += RETRY_AFTER_S
    await store.ensure(SYM, SPEC)
    assert (tail.calls, generation(store), view(store)) == (2, 1, ([0, 1], None))
    assert store.hydrated(SYM, H)


async def hydrated(
    bars: Sequence[tuple[int, Bar]], builds: dict[tuple[int, int, int], int]
) -> SeriesStore:
    tail = Tail(now=True)
    tail.tail = BarTail(list(bars), builds=builds)
    store = SeriesStore(tail)
    await store.ensure(SYM, SPEC)
    return store


def oldest(store: SeriesStore, history: int) -> int | None:
    got = store.latest(SYM, H, history)
    assert got is not None
    return got.oldest_build


async def test_latest_names_the_oldest_build_among_the_bars_it_returns() -> None:
    """§6.1 `meta.build_version`: the lowest among the bars sent. A live re-close of a hydrated
    bar, or the ring dropping it, leaves only bars built by the running code."""
    store = await hydrated(rows(0, 1, 2), {(0, 0, T0): 1, (0, 1, T0 + STEP): 2})
    assert (oldest(store, 3), oldest(store, 2), oldest(store, 1)) == (1, 2, None)
    await emit(store, up("close", 0, amended=True, close="101"))
    assert oldest(store, 3) == 2  # bar 0 is the running code's now; bar 1 is not
    await emit(store, *(up("close", i) for i in range(3, MAX_HISTORY + 1)))  # bar 0 rolls out
    assert oldest(store, MAX_HISTORY) == 2  # bar 1 is still served, with its mark
    await emit(store, up("close", MAX_HISTORY + 1))  # bar 1 rolls out
    assert oldest(store, MAX_HISTORY) is None
    kept = store._series[(SYM, H)]
    assert set(kept.stale) <= set(kept.closed)  # white-box: a build mark leaves with its bar


async def test_a_restart_forgets_the_old_run_builds() -> None:
    """A cold start reuses index 0: the new bar 0 is not the old run's stale bar 0."""
    store = await hydrated(rows(0, 1), {(0, 0, T0): 1})
    await emit(store, up("close", 0, shift=10))
    assert view(store) == ([0], None) and oldest(store, 2) is None


async def test_build_marks_survive_a_re_read_and_a_live_re_close_clears_one() -> None:
    """SR-E12-14: a re-read must not pass old-build bars off as current (#399 r3 major)."""
    clock = Clock()
    tail = Tail(now=True)
    tail.tail = BarTail(rows(0, 1, 2), builds={(0, 1, T0 + STEP): 1}, dropped=1)  # read again
    store = SeriesStore(tail, clock=clock)
    await store.ensure(SYM, SPEC)
    tail.tail = BarTail(rows(0, 1, 2), builds={(0, 1, T0 + STEP): 1})
    clock.t += RETRY_AFTER_S
    await store.ensure(SYM, SPEC)
    assert (tail.calls, oldest(store, 3)) == (2, 1)
    await emit(store, up("close", 1, amended=True, close="101"))
    assert oldest(store, 3) is None  # re-closed by the running code


async def test_a_generation_flip_led_by_an_ignored_emission_moves_the_version() -> None:
    """An amended close of a bar the new generation does not hold still resets the series."""
    store = await held(*(up("close", i) for i in range(5)))
    before = store.version(SYM, H)
    await emit(store, up("close", 3, amended=True), generation=1)
    assert (generation(store), view(store)) == (1, ([], None)) and store.version(SYM, H) > before


async def test_a_read_across_a_cold_start_marks_only_the_old_runs_bars() -> None:
    """Two stored runs reuse `(generation, index)` (#2662): the open time keys each build, so the
    new run's bar 0 is not marked with the old run's build."""
    builds = {(0, 0, T0): 1, (0, 1, T0 + STEP): 1}
    store = await hydrated([*rows(0, 1), *rows(0, shift=10)], builds)
    assert view(store) == ([0], None) and oldest(store, 1) is None


async def test_with_nothing_seen_live_the_newest_rows_generation_is_kept() -> None:
    """The builder starts after the hold: the newest stored epoch is kept, and the rows of
    another generation are skipped with their builds."""
    builds = {(5, 0, T0): 1, (5, 1, T0 + STEP): 1, (3, 0, T0 + 5 * STEP): 1}
    store = await hydrated([*rows(0, 1, gen=5), *rows(0, 1, gen=3, shift=5)], builds)
    assert generation(store) == 3 and view(store) == ([0, 1], None)
    assert (oldest(store, 2), oldest(store, 1)) == (1, None)


async def test_a_resubscribe_inside_the_grace_reads_nothing() -> None:
    """BR-38: the series is still kept, so a quick resubscribe does not read it again."""
    clock = Clock()
    tail = Tail(rows(0), now=True)
    store = SeriesStore(tail, clock=clock)
    (await store.ensure(SYM, SPEC)).release()
    clock.t += RELEASE_GRACE_S - 0.5
    await store.ensure(SYM, SPEC)
    assert tail.calls == 1 and store.hydrated(SYM, H)


async def test_an_empty_read_with_nothing_seen_live_names_no_generation() -> None:
    """No rows and no emission: none is assumed (#2662); the first emission will name it."""
    store = SeriesStore(Tail(now=True))
    await store.ensure(SYM, SPEC)
    assert generation(store) is None and view(store) == ([], None) and store.hydrated(SYM, H)
