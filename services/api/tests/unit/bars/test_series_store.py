"""E12-T06 slice B (#2195, #399): the bars WS snapshot store, `23-ws-protocol.md` §6.1, §8.2."""

from __future__ import annotations

from decimal import Decimal

import pytest
from prometheus_client import REGISTRY

from candleviewer.bars import series_store
from candleviewer.bars.emit import BarEmission
from candleviewer.bars.errors import SpecCapExceeded
from candleviewer.bars.models import Bar, BarSpec, BarUpdate
from candleviewer.bars.series_store import MAX_HISTORY, RELEASE_GRACE_S, SeriesStore

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


def generation(store: SeriesStore) -> int:
    got = store.latest(SYM, H, 1)
    assert got is not None
    return got.generation


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


async def test_sink_a_live_generation_change_resets_the_series_in_both_directions() -> None:
    """§8.2 generation swap: one live builder per series, so a lower live generation (#2662's
    clock-regression cold start) is as authoritative as a higher one."""
    store = await held(*(up("close", i) for i in range(3)), up("open", 3))
    await emit(store, up("close", 0, shift=4), generation=1)
    assert (generation(store), view(store)) == (1, ([0], None))  # the forming bar went too
    await emit(store, up("close", 7, shift=4), generation=0)
    assert (generation(store), view(store)) == (0, ([7], None))


@pytest.mark.parametrize(("kind", "after"), [("open", ([], 0)), ("close", ([0], None))])
async def test_sink_index_going_backwards_restarts_the_series(
    kind: str, after: tuple[list[int], int | None]
) -> None:
    """A builder cold start restarts `index` at 0 in generation 0: clients key by index."""
    store = await held(*(up("close", i) for i in range(5)), up("open", 5))
    await emit(store, up(kind, 0, shift=6))  # a new bar 0, opening after bar 5
    assert view(store) == after


@pytest.mark.parametrize(("kind", "after"), [("open", ([], 4)), ("close", ([4], None))])
async def test_sink_another_bar_at_the_newest_index_restarts_the_series(
    kind: str, after: tuple[list[int], int | None]
) -> None:
    """The boundary of both restart rules: a bar AT the newest closed index, opening later."""
    store = await held(*(up("close", i) for i in range(5)))
    await emit(store, up(kind, 4, shift=1))
    assert view(store) == after


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
    await store.ensure("ETHUSDT", SPEC)  # sweeps every unheld series past its grace
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


async def test_a_new_hold_starts_from_the_last_16_closes_seen_before_it() -> None:
    """Live bars only: the closes the sink saw while nobody held the series. No ring holds the
    forming bar; the sink keeps the series current from there."""
    store = SeriesStore()
    await emit(store, *(up("close", i) for i in range(18)), up("open", 18))
    await store.ensure(SYM, SPEC)
    assert view(store) == (list(range(2, 18)), None)
    await emit(store, up("close", 18))
    assert view(store) == (list(range(2, 19)), None)


async def test_a_new_hold_replays_its_recent_closes_by_the_sink_rules() -> None:
    """A builder restart among the closes seen before the hold drops the older run, as live."""
    store = SeriesStore()
    await emit(store, *(up("close", i, shift=-30) for i in (20, 21)))
    await emit(store, *(up("close", i) for i in range(3)))
    await store.ensure(SYM, SPEC)
    assert view(store) == ([0, 1, 2], None)


async def test_only_the_newest_generations_recent_closes_start_a_hold() -> None:
    """A swap among the closes seen before the hold: the earlier generation's are not the
    series' bars."""
    store = SeriesStore()
    await emit(store, up("close", 5))
    await emit(store, up("close", 7), generation=1)
    await store.ensure(SYM, SPEC)
    assert generation(store) == 1 and view(store) == ([7], None)


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
