"""#2762: a failed or cancelled first registration never drops another consumer's lease.

A registrant that finds its series still being built waits for that build: the build's error
reaches it too and it keeps no lease, and if the builder's registrant is cancelled it builds the
series itself. With several waiters, the first to resume takes the build over and the others wait
on that takeover. `_GatedStore` drives each interleaving: its `load`, the first await of a build,
parks until the test sets `go`, and `_gate` counts the builds started, so a waiter that starts a
build of its own fails at once. No sleeps: tasks run in the order they were woken. Every wait on
a registration task, a gather or a gate event is bounded, so a wake-up that never comes fails the
test instead of hanging it; a `register` made before the gate or with it open, `tick` and `stop`
cannot park, so they are not wrapped. `_consistent` checks the invariant after each step."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from candleviewer.bars.builder_set import BarBuilderSet
from candleviewer.bars.errors import BarsError, BarServiceStopping
from candleviewer.bars.leases import GRACE_US, SpecLeases
from candleviewer.bars.models import BarBuilder, BarSpec
from candleviewer.bars.state_store import StateStore, StoredState
from candleviewer.bus.bus import Bus

from ._set_harness import M1, T3, Clock, make_set
from ._trades import SYM, us

T0 = us("10:00:00")
KEY = (SYM, M1.spec_hash)
BOUND_S = 5  # every wait on a registration task, a gather or a gate event: fails, never hangs


class _GatedStore(StateStore):
    """`load` parks until `go` is set, then raises `fail` or loads. `loads` counts the loads and
    `builds` the builds started: `_build_shared` makes its builder before it waits for the lane
    lock, so a second build shows in `builds` while the first is parked in `load`."""

    def __init__(self, root: Path, fail: Exception | None = None) -> None:
        super().__init__(root)
        self.entered, self.go, self.fail = asyncio.Event(), asyncio.Event(), fail
        self.loads = self.builds = 0

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
    make = s._factory

    def counted(spec: BarSpec, symbol: str) -> BarBuilder:
        store.builds += 1
        return make(spec, symbol)

    s._factory = counted
    return store


def _holders(s: BarBuilderSet) -> set[str]:
    series = s._leases._series.get(KEY)
    return set() if series is None else set(series.holders)


def _consistent(s: BarBuilderSet, **registrations: asyncio.Task[None]) -> None:
    """The invariant (#2762) after a step: a consumer whose `register` returned holds a lease, on a
    series that is active or quarantined; one whose `register` raised or was cancelled holds none;
    one still registering holds its own; a series nobody holds is in its grace, and no active
    series lacks its lease; and once every registration has ended, nothing is being built."""
    holders = _holders(s)
    for consumer, task in registrations.items():
        if not task.done():
            assert consumer in holders, f"{consumer} is registering without its lease"
        elif task.cancelled() or task.exception() is not None:
            assert consumer not in holders, f"{consumer} ended in an error and kept its lease"
        else:
            assert consumer in holders, f"{consumer} returned without a lease"
            assert M1.spec_hash in s.active(SYM) or s.quarantined(SYM, M1.spec_hash)
    leases = s._leases._series.values()
    assert all(lease.holders or lease.expires_at is not None for lease in leases)
    assert all((SYM, h) in s._leases for h in s.active(SYM)), "a series without a lease"
    if all(task.done() for task in registrations.values()):
        assert s._building == {}


async def _registering(
    s: BarBuilderSet, store: _GatedStore, *consumers: str
) -> tuple[asyncio.Task[None], ...]:
    """The first consumer's build parks in `load`; the others register the same series meanwhile
    (tasks start in order)."""
    tasks = tuple(asyncio.create_task(s.register(M1, SYM, c)) for c in consumers)
    await asyncio.wait_for(store.entered.wait(), BOUND_S)
    return tasks


async def _cancelled(task: asyncio.Task[None]) -> None:
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, BOUND_S)


async def test_a_registrant_joining_a_build_returns_once_the_series_exists(tmp_path: Path) -> None:
    s = make_set(tmp_path)
    store = _gate(s, tmp_path)
    a, b = await _registering(s, store, "a", "b")
    assert not b.done() and _holders(s) == {"a", "b"}  # B holds its lease and waits for the build
    _consistent(s, a=a, b=b)
    store.go.set()
    await asyncio.wait_for(asyncio.gather(a, b), BOUND_S)
    assert (_holders(s), s.active(SYM), store.loads) == ({"a", "b"}, (M1.spec_hash,), 1)
    _consistent(s, a=a, b=b)
    await s.stop()


async def test_a_cancelled_first_build_is_built_by_the_registrant_still_waiting(
    tmp_path: Path,
) -> None:
    s = make_set(tmp_path)
    store = _gate(s, tmp_path)
    a, b = await _registering(s, store, "a", "b")
    _consistent(s, a=a, b=b)
    a.cancel()  # A's client left mid-subscribe
    await _cancelled(a)
    _consistent(s, a=a, b=b)
    store.go.set()
    await asyncio.wait_for(b, BOUND_S)
    assert (_holders(s), s.active(SYM), store.loads) == ({"b"}, (M1.spec_hash,), 2)
    with pytest.raises(BarsError, match="holds no lease"):
        s.release(M1.spec_hash, SYM, "a")  # A holds nothing
    _consistent(s, a=a, b=b)
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
    a, b = await _registering(s, store, "a", "b")
    assert not b.done() and _holders(s) == {"a", "b"}  # B waits for the series, holding a lease
    _consistent(s, a=a, b=b)
    store.go.set()
    with pytest.raises(BarsError) as raised_a:
        await asyncio.wait_for(a, BOUND_S)
    with pytest.raises(BarsError) as raised_b:
        await asyncio.wait_for(b, BOUND_S)
    assert raised_a.value is raised_b.value is err and store.loads == 1  # one build, one error
    assert _holders(s) == set() and s._building == {}
    assert s._leases.keys() == (((SYM, T3.spec_hash),) if shared else ())
    assert (SYM in s._lanes, len(bus._subscriptions)) == (shared, int(shared))
    _consistent(s, a=a, b=b)
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
    a, b = await _registering(s, store, "a", "b")
    assert not b.done()
    _consistent(s, a=a, b=b)
    b.cancel()  # B's client left while it waited
    await _cancelled(b)
    assert _holders(s) == {"a"}  # at once, while A's build is still parked
    _consistent(s, a=a, b=b)
    store.go.set()
    await asyncio.wait_for(a, BOUND_S)
    assert (_holders(s), s.active(SYM), store.loads) == ({"a"}, (M1.spec_hash,), 1)
    _consistent(s, a=a, b=b)
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
    a, b = await _registering(s, store, "a", "b")
    store.go.set()
    await asyncio.wait_for(a, BOUND_S)
    _consistent(s, a=a, b=b)
    s.release(M1.spec_hash, SYM, "a")  # A's client leaves: B holds the last lease
    assert not b.done()  # woken by the build, not resumed yet
    b.cancel()
    await _cancelled(b)
    _consistent(s, b=b)
    assert (s._leases.keys(), s.active(SYM)) == ((KEY,), (M1.spec_hash,))  # in its grace
    clock.t += GRACE_US
    await s.tick()
    assert (s._leases.keys(), s.active(SYM), bus._subscriptions) == ((), (), [])
    _consistent(s, b=b)
    await s.stop()


async def test_stop_with_a_build_in_flight_builds_nothing_new_when_its_builder_leaves(
    tmp_path: Path,
) -> None:
    before = asyncio.all_tasks()
    bus = Bus()
    s = make_set(tmp_path, bus=bus)
    store = _gate(s, tmp_path)
    a, b = await _registering(s, store, "a", "b")
    _consistent(s, a=a, b=b)
    stopping = asyncio.create_task(s.stop())
    a.cancel()
    store.go.set()  # a build started from here on would not park
    await _cancelled(a)
    with pytest.raises(BarServiceStopping):
        await asyncio.wait_for(b, BOUND_S)  # refused: a lane opened now would outlive `stop()`
    await asyncio.wait_for(stopping, BOUND_S)
    assert (s._lanes, bus._subscriptions, s._leases.keys(), s._building) == ({}, [], (), {})
    _consistent(s, a=a, b=b)
    assert asyncio.all_tasks() - before == set()


async def test_two_waiters_of_a_cancelled_build_share_one_takeover(tmp_path: Path) -> None:
    """A's client leaves while B1 and B2 wait: B1, woken first, takes the build over, and B2 waits
    on that takeover instead of starting a second build."""
    s = make_set(tmp_path)
    store = _gate(s, tmp_path)
    a, b1, b2 = await _registering(s, store, "a", "b1", "b2")
    first = s._building[KEY]
    _consistent(s, a=a, b1=b1, b2=b2)
    store.entered.clear()
    a.cancel()
    await _cancelled(a)
    _consistent(s, a=a, b1=b1, b2=b2)
    await asyncio.wait_for(store.entered.wait(), BOUND_S)  # the takeover's `load` parks
    assert first.cancelled() and list(s._building) == [KEY] and s._building[KEY] is not first
    assert (store.builds, store.loads) == (2, 2)  # A's and B1's: B2 waits on B1's, it builds none
    assert not (b1.done() or b2.done())
    _consistent(s, a=a, b1=b1, b2=b2)
    store.go.set()
    await asyncio.wait_for(asyncio.gather(b1, b2), BOUND_S)
    assert (_holders(s), s.active(SYM), store.loads) == ({"b1", "b2"}, (M1.spec_hash,), 2)
    assert s._building == {}
    _consistent(s, a=a, b1=b1, b2=b2)
    await s.stop()


async def test_a_cancelled_takeover_is_taken_over_by_the_waiter_left(tmp_path: Path) -> None:
    """B1, woken first, takes A's build over and its client leaves too: B2 takes it over in turn."""
    s = make_set(tmp_path)
    store = _gate(s, tmp_path)
    a, b1, b2 = await _registering(s, store, "a", "b1", "b2")
    _consistent(s, a=a, b1=b1, b2=b2)
    store.entered.clear()
    a.cancel()
    await _cancelled(a)
    _consistent(s, a=a, b1=b1, b2=b2)
    await asyncio.wait_for(store.entered.wait(), BOUND_S)  # B1, woken first, takes it over
    assert store.builds == 2  # A's and B1's: B2 waits on B1's, it builds none
    _consistent(s, a=a, b1=b1, b2=b2)
    store.entered.clear()
    b1.cancel()  # B1's client leaves too, mid-takeover
    await _cancelled(b1)
    _consistent(s, a=a, b1=b1, b2=b2)
    await asyncio.wait_for(store.entered.wait(), BOUND_S)  # B2 takes it over in turn
    assert store.builds == 3  # the third build, B2's
    _consistent(s, a=a, b1=b1, b2=b2)
    store.go.set()
    await asyncio.wait_for(b2, BOUND_S)
    assert (_holders(s), s.active(SYM), store.loads) == ({"b2"}, (M1.spec_hash,), 3)
    assert s._building == {}
    _consistent(s, a=a, b1=b1, b2=b2)
    await s.stop()


async def test_a_failed_takeover_raises_its_error_in_the_waiter_left(tmp_path: Path) -> None:
    """B1's takeover of A's build fails: B2, waiting on it, raises the same error object, and no
    lease, lane or build is left."""
    bus = Bus()
    s = make_set(tmp_path, bus=bus)
    store = _gate(s, tmp_path)
    a, b1, b2 = await _registering(s, store, "a", "b1", "b2")
    _consistent(s, a=a, b1=b1, b2=b2)
    store.entered.clear()
    a.cancel()
    await _cancelled(a)
    _consistent(s, a=a, b1=b1, b2=b2)
    await asyncio.wait_for(store.entered.wait(), BOUND_S)  # B1's takeover parks
    assert store.builds == 2  # A's and B1's: B2 waits on B1's, it builds none
    _consistent(s, a=a, b1=b1, b2=b2)
    store.fail = err = BarsError("the takeover failed")
    store.go.set()
    with pytest.raises(BarsError) as raised_b1:
        await asyncio.wait_for(b1, BOUND_S)
    with pytest.raises(BarsError) as raised_b2:
        await asyncio.wait_for(b2, BOUND_S)
    assert raised_b1.value is raised_b2.value is err and store.loads == 2  # the same error object
    assert (s._leases.keys(), s._lanes, bus._subscriptions, s._building) == ((), {}, [], {})
    _consistent(s, a=a, b1=b1, b2=b2)
    await s.stop()


def test_giving_back_a_lease_not_held_changes_nothing() -> None:
    leases = SpecLeases()
    leases.give_back(KEY, "a", 0, built=False)  # no such series
    leases.acquire(KEY, "a", None)
    leases.give_back(KEY, "b", 0, built=True)  # a lease B never took
    assert leases.keys() == (KEY,) and leases._series[KEY].holders == {"a": None}
