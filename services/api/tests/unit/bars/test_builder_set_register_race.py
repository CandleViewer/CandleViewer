"""#2762: a failed or cancelled first registration never drops another consumer's lease.

A registrant that finds its series still being built waits for that build: the build's error
reaches it too and it keeps no lease, and if the builder's registrant is cancelled it builds the
series itself. `_GatedStore` drives each interleaving: its `load`, the first await of a build,
parks until the test sets `go`. No sleeps: tasks run in the order they were woken."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from candleviewer.bars.builder_set import BarBuilderSet
from candleviewer.bars.errors import BarsError, BarServiceStopping
from candleviewer.bars.leases import GRACE_US, SpecLeases
from candleviewer.bars.state_store import StateStore, StoredState
from candleviewer.bus.bus import Bus

from ._set_harness import M1, T3, Clock, make_set
from ._trades import SYM, us

T0 = us("10:00:00")
KEY = (SYM, M1.spec_hash)


class _GatedStore(StateStore):
    """`load` parks until `go` is set, then raises `fail` or loads; `loads` counts the builds."""

    def __init__(self, root: Path, fail: Exception | None = None) -> None:
        super().__init__(root)
        self.entered, self.go, self.fail, self.loads = asyncio.Event(), asyncio.Event(), fail, 0

    async def load(self, symbol: str, spec_hash: str) -> tuple[StoredState | None, str]:
        self.loads += 1
        self.entered.set()
        await self.go.wait()
        if self.fail is not None:
            raise self.fail
        return await super().load(symbol, spec_hash)


def _gate(s: BarBuilderSet, root: Path, fail: Exception | None = None) -> _GatedStore:
    store = _GatedStore(root, fail)
    s._store = store  # every build from now on parks in it
    return store


def _holders(s: BarBuilderSet) -> set[str]:
    series = s._leases._series.get(KEY)
    return set() if series is None else set(series.holders)


async def _a_builds_b_registers(
    s: BarBuilderSet, store: _GatedStore
) -> tuple[asyncio.Task[None], asyncio.Task[None]]:
    """A's build parks in `load`; then B registers the same series (tasks start in order)."""
    a = asyncio.create_task(s.register(M1, SYM, "a"))
    b = asyncio.create_task(s.register(M1, SYM, "b"))
    await store.entered.wait()
    return a, b


async def test_a_registrant_joining_a_build_returns_once_the_series_exists(tmp_path: Path) -> None:
    s = make_set(tmp_path)
    store = _gate(s, tmp_path)
    a, b = await _a_builds_b_registers(s, store)
    assert not b.done() and _holders(s) == {"a", "b"}  # B holds its lease and waits for the build
    store.go.set()
    await asyncio.gather(a, b)
    assert (_holders(s), s.active(SYM), store.loads) == ({"a", "b"}, (M1.spec_hash,), 1)
    await s.stop()


async def test_a_cancelled_first_build_is_built_by_the_registrant_still_waiting(
    tmp_path: Path,
) -> None:
    s = make_set(tmp_path)
    store = _gate(s, tmp_path)
    a, b = await _a_builds_b_registers(s, store)
    a.cancel()  # A's client left mid-subscribe
    with pytest.raises(asyncio.CancelledError):
        await a
    store.go.set()
    await b
    assert (_holders(s), s.active(SYM), store.loads) == ({"b"}, (M1.spec_hash,), 2)
    with pytest.raises(BarsError, match="holds no lease"):
        s.release(M1.spec_hash, SYM, "a")  # A holds nothing
    await s.stop()


@pytest.mark.parametrize("shared", [False, True], ids=["alone-on-its-lane", "lane-shared"])
async def test_a_failed_first_build_raises_in_its_waiter_and_leaves_no_lease(
    tmp_path: Path, shared: bool
) -> None:
    bus = Bus()
    s = make_set(tmp_path, bus=bus)
    if shared:  # another series keeps the symbol's lane open
        await s.register(T3, SYM, "other")
    err = BarsError("the build failed")
    store = _gate(s, tmp_path, err)
    a, b = await _a_builds_b_registers(s, store)
    assert not b.done() and _holders(s) == {"a", "b"}  # B waits for the series, holding a lease
    store.go.set()
    with pytest.raises(BarsError) as raised_a:
        await a
    with pytest.raises(BarsError) as raised_b:
        await b
    assert raised_a.value is raised_b.value is err and store.loads == 1  # one build, one error
    assert _holders(s) == set() and s._building == {}
    assert s._leases.keys() == (((SYM, T3.spec_hash),) if shared else ())
    assert (SYM in s._lanes, len(bus._subscriptions)) == (shared, int(shared))
    await s.stop()


async def test_a_failed_build_with_no_other_holder_leaves_no_lease_behind(tmp_path: Path) -> None:
    bus = Bus()
    s = make_set(tmp_path, bus=bus)
    store = _gate(s, tmp_path, BarsError("the build failed"))
    store.go.set()
    with pytest.raises(BarsError, match="the build failed"):
        await s.register(M1, SYM, "a")
    assert (s._leases.keys(), s._lanes, bus._subscriptions) == ((), {}, [])
    store.fail = None  # nothing was left over: the next registration builds the series
    await s.register(M1, SYM, "b")
    assert (_holders(s), s.active(SYM)) == ({"b"}, (M1.spec_hash,))
    await s.stop()


async def test_a_waiter_cancelled_gives_back_only_its_own_lease(tmp_path: Path) -> None:
    s = make_set(tmp_path)
    store = _gate(s, tmp_path)
    a, b = await _a_builds_b_registers(s, store)
    assert not b.done()
    b.cancel()  # B's client left while it waited
    with pytest.raises(asyncio.CancelledError):
        await b
    assert _holders(s) == {"a"}  # at once, while A's build is still parked
    store.go.set()
    await a
    assert (_holders(s), s.active(SYM), store.loads) == ({"a"}, (M1.spec_hash,), 1)
    await s.stop()


async def test_a_waiter_cancelled_as_its_build_lands_releases_into_the_grace(
    tmp_path: Path,
) -> None:
    """B's cancellation lands once A's build is done but before B resumes: the series exists, so
    B's lease goes as on `release`. The last one starts the grace, and the tick tears the series
    down: a built series is never left without a lease."""
    clock, bus = Clock(T0), Bus()
    s = make_set(tmp_path, bus=bus, clock=clock)
    store = _gate(s, tmp_path)
    a, b = await _a_builds_b_registers(s, store)
    store.go.set()
    await a
    s.release(M1.spec_hash, SYM, "a")  # A's client leaves: B holds the last lease
    assert not b.done()  # woken by the build, not resumed yet
    b.cancel()
    with pytest.raises(asyncio.CancelledError):
        await b
    assert (s._leases.keys(), s.active(SYM)) == ((KEY,), (M1.spec_hash,))  # in its grace
    clock.t += GRACE_US
    await s.tick()
    assert (s._leases.keys(), s.active(SYM), bus._subscriptions) == ((), (), [])
    await s.stop()


async def test_stop_with_a_build_in_flight_builds_nothing_new_when_its_builder_leaves(
    tmp_path: Path,
) -> None:
    before = asyncio.all_tasks()
    bus = Bus()
    s = make_set(tmp_path, bus=bus)
    store = _gate(s, tmp_path)
    a, b = await _a_builds_b_registers(s, store)
    stopping = asyncio.create_task(s.stop())
    a.cancel()
    store.go.set()  # a build started from here on would not park
    with pytest.raises(asyncio.CancelledError):
        await a
    with pytest.raises(BarServiceStopping):
        await b  # refused: a lane opened now would outlive `stop()`
    await stopping
    assert (s._lanes, bus._subscriptions, s._leases.keys(), s._building) == ({}, [], (), {})
    assert asyncio.all_tasks() - before == set()


def test_giving_back_a_lease_not_held_changes_nothing() -> None:
    leases = SpecLeases()
    leases.give_back(KEY, "a", 0, built=False)  # no such series
    leases.acquire(KEY, "a", None)
    leases.give_back(KEY, "b", 0, built=True)  # a lease B never took
    assert leases.keys() == (KEY,) and leases._series[KEY].holders == {"a": None}
