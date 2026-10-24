"""One governor drawn from two event loops, each on a thread of its own (#913 L3, ruling Q11;
C-12.7), and the per-loop turn its takers queue on. The injected clock is frozen and the
injected sleep never sleeps. Every wait for another thread is bounded at 10 s, for work of a
few milliseconds. CI's Hypothesis profile runs the race test in full; a dev run takes less.
"""

from __future__ import annotations

import asyncio
import contextlib
import gc
import os
import sys
import threading
import weakref
from collections.abc import Callable, Coroutine, Iterator
from concurrent.futures import Future
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.exchange.base.errors import RateBudgetExceededError
from candleviewer.exchange.bybit import rate_limit
from candleviewer.exchange.bybit.config import EndpointClass
from candleviewer.exchange.bybit.metrics import bybit_ip_hold_remaining_seconds
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor, _Bucket, _IpGate, _Turn
from tests._hypothesis_profiles import CI

ORDER, ACCOUNT = EndpointClass.ORDER, EndpointClass.ACCOUNT
#: The bound on every wait for another thread.
JOIN_S = 10.0
#: The race test's rounds per example and examples: in full under CI's profile, fewer in dev.
ROUNDS, EXAMPLES = (4, 40) if os.environ.get("HYPOTHESIS_PROFILE") == CI else (1, 10)
#: How often the GIL changes hands while the loops race (`sys.setswitchinterval`).
SWITCH_S = 1e-5


@pytest.fixture(autouse=True)
def _no_hold_left_on_the_gauge() -> Iterator[None]:
    yield
    bybit_ip_hold_remaining_seconds.set(0.0)


class _Loop:
    """An event loop running in a thread of its own until closed."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self._thread.start()

    def start[T](self, coro: Coroutine[Any, Any, T]) -> Future[T]:
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def run[T](self, coro: Coroutine[Any, Any, T]) -> T:
        return self.start(coro).result(JOIN_S)

    def close(self) -> bool:
        """Stops and closes the loop, and says whether its thread ended within the bound."""
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(JOIN_S)
        if self._thread.is_alive():
            return False
        self.loop.close()
        return True


@contextlib.contextmanager
def _two_loops() -> Iterator[tuple[_Loop, _Loop]]:
    loops = (_Loop(), _Loop())
    try:
        yield loops
    finally:
        closed = [loop.close() for loop in loops]
    assert all(closed), "a loop's thread outlived the bound"  # only if the body passed


async def _on[T](call: Callable[..., T], *args: Any) -> T:
    """Makes a plain call from the loop that runs this, as code on that loop does."""
    return call(*args)


async def _spawn(coro: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
    return asyncio.ensure_future(coro)


async def _cancel(task: asyncio.Task[None]) -> bool:
    """Cancels `task` on its own loop and says whether it ended cancelled."""
    task.cancel()
    await asyncio.wait([task])
    return task.cancelled()


class _Parked:
    """The injected sleep: it parks its caller on the caller's own loop until cancelled."""

    def __init__(self) -> None:
        self._parked = threading.Semaphore(0)

    async def __call__(self, _seconds: float) -> None:
        self._parked.release()
        await asyncio.Event().wait()

    def wait(self, takers: int) -> None:
        assert all(self._parked.acquire(timeout=JOIN_S) for _ in range(takers))


@contextlib.contextmanager
def _switching_often() -> Iterator[None]:
    """The GIL changes hands often, so the two loops' takes interleave finely."""
    before = sys.getswitchinterval()
    sys.setswitchinterval(SWITCH_S)
    try:
        yield
    finally:
        sys.setswitchinterval(before)


async def _granted(governor: TokenBucketGovernor, uid: str, takers: int) -> int:
    """How many of `takers` acquisitions that may not wait are granted; a refusal takes none."""
    granted = 0
    for _ in range(takers):
        with contextlib.suppress(RateBudgetExceededError):
            await governor.acquire(uid, ORDER, lane="entry", deadline_s=0.0)
            granted += 1
    return granted


def _draws(mode: str, capacity: int) -> tuple[tuple[TokenBucketGovernor, str], ...]:
    """Each loop's `(governor or view, uid)`, sharing `capacity` tokens: one UID bucket, the IP
    bucket (two UIDs), one UID bucket via the governor and a view, or a view's cap (two UIDs)."""
    big = 10_000
    governor = TokenBucketGovernor(
        default_capacity=capacity if mode in {"uid", "view"} else big,
        ip_budget_per_5s=capacity if mode == "ip" else big,
        clock=lambda: 0.0,
    )
    view = governor.capped(capacity if mode == "cap" else big)
    first = view if mode == "cap" else governor
    second = governor if mode in {"uid", "ip"} else view
    return (first, "uid-1"), (second, "uid-1" if mode in {"uid", "view"} else "uid-2")


@settings(max_examples=EXAMPLES, deadline=None)
@given(
    mode=st.sampled_from(["uid", "ip", "view", "cap"]),
    capacity=st.integers(1, 16),
    bursts=st.tuples(st.integers(0, 24), st.integers(0, 24)),
)
def test_two_loops_never_draw_more_than_the_budget_they_share(
    mode: str, capacity: int, bursts: tuple[int, int]
) -> None:
    barrier = threading.Barrier(2, timeout=JOIN_S)

    async def burst(governor: TokenBucketGovernor, uid: str, takers: int) -> int:
        barrier.wait()  # both loops start together
        return await _granted(governor, uid, takers)

    with _switching_often(), _two_loops() as loops:
        for _ in range(ROUNDS):  # a fresh budget each round: one more race per round
            draws = _draws(mode, capacity)
            runs = [lp.start(burst(*d, n)) for lp, d, n in zip(loops, draws, bursts, strict=True)]
            assert sum(run.result(JOIN_S) for run in runs) == min(capacity, sum(bursts))


def test_a_hold_set_on_one_loop_refuses_the_other_loops_acquire_and_both_read_it() -> None:
    """A `10018` hold set on loop A refuses loop B's acquire whose wait it outlasts (24 §8.6)."""
    governor = TokenBucketGovernor(clock=lambda: 0.0)
    with _two_loops() as (a, b):
        a.run(_on(governor.hold_ip, 30.0))
        with pytest.raises(RateBudgetExceededError) as refused:
            b.run(governor.acquire("uid-1", ORDER, lane="entry", deadline_s=5.0))
        held = [loop.run(_on(governor.ip_hold_remaining_s)) for loop in (a, b)]
    assert (refused.value.retry_after_s, held) == (30.0, [30.0, 30.0])


def test_a_drain_on_one_loop_is_what_the_other_loop_reads() -> None:
    governor = TokenBucketGovernor(clock=lambda: 0.0)
    with _two_loops() as (a, b):
        b.run(_on(governor.drain, "uid-1", ORDER, 4.0))
        assert a.run(_on(governor.remaining, "uid-1", ORDER)) == 6.0


def test_a_cancel_on_either_loop_gives_back_every_token_it_took() -> None:
    """One view call per loop waits on the empty IP bucket holding cap and UID tokens; a cancel
    gives each back, never past the capacity: nothing is spent on a request never sent (24 §8.7)."""
    sleep = _Parked()
    governor = TokenBucketGovernor(ip_budget_per_5s=1, clock=lambda: 0.0, sleep=sleep)
    view = governor.capped(5)
    with _two_loops() as loops:
        loops[0].run(governor.acquire_ip_only())  # the IP bucket is empty now
        calls = [view.acquire(f"uid-{n}", ACCOUNT, lane="poll") for n in range(2)]
        waiters = [loop.run(_spawn(call)) for loop, call in zip(loops, calls, strict=True)]
        sleep.wait(2)
        for n in range(2):  # meanwhile the venue reports both UID buckets full
            governor.observe_header(f"uid-{n}", ACCOUNT, 10)
        assert [loop.run(_cancel(w)) for loop, w in zip(loops, waiters, strict=True)] == [True] * 2
    assert view._cap is not None and view._cap.tokens == 5.0
    held = [governor._get_bucket(f"uid-{n}", ACCOUNT).tokens for n in range(2)]  # unrefilled
    assert held == [10.0, 10.0]


async def test_an_acquire_ended_by_any_other_exception_gives_back_every_token_it_took() -> None:
    """Not only a refusal or a cancel: an interrupt ending the wait gives back the cap and UID
    tokens too (security L-3). Only the collector's `GeneratorExit` gives nothing back (M-1)."""

    class Interrupted(BaseException):
        pass

    async def sleep(_seconds: float) -> None:
        raise Interrupted

    governor = TokenBucketGovernor(ip_budget_per_5s=1, clock=lambda: 0.0, sleep=sleep)
    await governor.acquire_ip_only()  # the IP bucket is empty now
    view = governor.capped(5)
    with pytest.raises(Interrupted):
        await view.acquire("uid-1", ACCOUNT, lane="poll")
    assert view._cap is not None and view._cap.tokens == 5.0
    assert governor.remaining("uid-1", ACCOUNT) == 10.0


def _empty_bucket(sleep: _Parked, capacity: float = 1.0) -> TokenBucketGovernor:
    """uid-1's order bucket is empty, and only a header can fill it: the clock is frozen."""
    governor = TokenBucketGovernor(default_capacity=capacity, clock=lambda: 0.0, sleep=sleep)
    governor.drain("uid-1", ORDER, capacity)
    return governor


def test_takers_abandoned_with_their_loop_end_quietly_even_inside_a_critical_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M-1: a loop closed with a holder and a waiter of one turn, uncancelled. The collector ends
    them inside the governor's lock, and they take no lock on the way out. The waiter, kept till
    the holder has released, was never handed the closed loop's turn: it releases nothing."""
    gc.collect()  # garbage an earlier test left is not this test's to judge
    unraisable: list[object] = []
    monkeypatch.setattr(sys, "unraisablehook", unraisable.append)
    governor = _empty_bucket(_Parked())

    async def park_two() -> asyncio.Task[None]:
        calls = [governor.acquire("uid-1", ORDER, lane="entry") for _ in range(2)]
        takers = [asyncio.ensure_future(call) for call in calls]
        await asyncio.sleep(0)  # the first waits for a token holding the turn, the second queues
        return takers[1]

    loop = asyncio.new_event_loop()
    waiter = loop.run_until_complete(park_two())
    loop.close()
    closed = weakref.ref(loop)
    del loop

    def ended_inside_the_lock() -> bool:
        def collect() -> None:
            with governor._guard:
                for _ in range(2):
                    gc.collect()

        collector = threading.Thread(target=collect, daemon=True)
        collector.start()
        collector.join(JOIN_S)
        return not collector.is_alive()

    holder_ended = ended_inside_the_lock()
    del waiter
    assert (holder_ended, ended_inside_the_lock(), unraisable, closed()) == (True, True, [], None)


def test_a_taker_waiting_on_one_loop_never_holds_up_the_other_loop() -> None:
    """The lock covers the arithmetic, never a wait: while a taker sleeps on loop A for a token
    of one bucket, no one holds the lock and loop B takes from another bucket at once."""
    sleep = _Parked()
    governor = _empty_bucket(sleep)
    with _two_loops() as (a, b):
        waiter = a.run(_spawn(governor.acquire("uid-1", ORDER, lane="entry")))
        sleep.wait(1)
        assert not governor._guard.locked()
        b.run(governor.acquire("uid-2", ORDER, lane="entry", deadline_s=0.0))
        assert a.run(_cancel(waiter))


def test_a_spare_token_goes_to_the_taker_that_waited_first_on_either_loop() -> None:
    """A spare token is handed to loop A's parked taker, first in line, so loop B's is refused;
    A's cancel gives that token back, never past the capacity, and B takes it."""
    sleep = _Parked()
    governor = _empty_bucket(sleep)
    with _two_loops() as (a, b):
        first = a.run(_spawn(governor.acquire("uid-1", ORDER, lane="entry")))
        sleep.wait(1)
        b.run(_on(governor.observe_header, "uid-1", ORDER, 1))
        with pytest.raises(RateBudgetExceededError, match="no rate token"):
            b.run(governor.acquire("uid-1", ORDER, lane="entry", deadline_s=0.0))
        b.run(_on(governor.observe_header, "uid-1", ORDER, 1))  # full again before it comes back
        assert a.run(_cancel(first))
        assert governor._get_bucket("uid-1", ORDER).tokens == 1.0  # unrefilled
        b.run(governor.acquire("uid-1", ORDER, lane="entry", deadline_s=0.0))


def test_a_taker_behind_another_loops_taker_waits_for_its_place_in_the_queue() -> None:
    """Loop A's taker is first for the empty bucket (5 tokens a second): loop B's token is the
    second to come, 0.4 s away, past its 0.3 s wait, so it is refused at once (24 §8.7)."""
    sleep = _Parked()
    governor = _empty_bucket(sleep)
    with _two_loops() as (a, b):
        first = a.run(_spawn(governor.acquire("uid-1", ORDER, lane="entry")))
        sleep.wait(1)
        with pytest.raises(RateBudgetExceededError) as refused:
            b.run(governor.acquire("uid-1", ORDER, lane="entry", deadline_s=0.3))
        assert a.run(_cancel(first))
    assert refused.value.retry_after_s == pytest.approx(0.4)


def test_a_stalled_loop_keeps_at_most_the_one_token_it_was_handed() -> None:
    """Ruling (4): of a stalled loop's two waiting takers only the first waits for a token, so it
    is handed one per (bucket, loop), never sent; the live loop takes the rest."""
    governor = _empty_bucket(_Parked(), capacity=3.0)
    stalled, live = asyncio.new_event_loop(), asyncio.new_event_loop()
    try:
        calls = [governor.acquire("uid-1", ORDER, lane="entry") for _ in range(2)]
        takers = [stalled.create_task(call) for call in calls]
        stalled.run_until_complete(asyncio.sleep(0))  # both wait, then the loop stops
        governor.observe_header("uid-1", ORDER, 3)
        granting = asyncio.wait_for(_granted(governor, "uid-1", 3), JOIN_S)
        granted = live.run_until_complete(granting)
        assert (granted, governor.remaining("uid-1", ORDER)) == (2, 0)
        for taker in takers:  # both, before the stalled loop runs again
            taker.cancel()
        _, pending = stalled.run_until_complete(asyncio.wait(takers, timeout=JOIN_S))
        assert not pending
        assert all(t.cancelled() for t in takers) and governor.remaining("uid-1", ORDER) == 1.0
    finally:
        stalled.close()
        live.close()


def test_a_closed_loop_is_not_kept_alive_by_a_bucket_it_queued_on() -> None:
    """A bucket outlives the loops that draw on it. Once a second taker has queued behind a
    first on one loop and both were cut, nothing of the governor keeps the closed loop alive."""
    governor = _empty_bucket(_Parked())

    async def two_takers() -> list[bool]:
        calls = [governor.acquire("uid-1", ORDER, lane="entry") for _ in range(2)]
        takers = [asyncio.ensure_future(call) for call in calls]
        await asyncio.sleep(0)  # the first parks for a token, the second queues behind it
        return [await _cancel(taker) for taker in takers]

    lp = _Loop()
    cut, stopped = lp.run(two_takers()), lp.close()
    closed = weakref.ref(lp.loop)
    del lp
    gc.collect()
    assert (cut, stopped, closed()) == ([True, True], True, None)


async def test_a_hold_set_just_after_the_last_look_is_seen_before_any_token_is_taken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Another loop's `10018` lands after the third look at the hold, the IP take's (after
    acquire's and the UID take's): the take looks again under the lock and refuses."""
    governor = TokenBucketGovernor(clock=lambda: 0.0)
    look, looks = governor._wait_ip_hold, [0]

    async def look_then_hold(limit: float | None) -> None:
        await look(limit)
        looks[0] += 1
        if looks[0] == 3:
            governor.hold_ip(30.0)

    monkeypatch.setattr(governor, "_wait_ip_hold", look_then_hold)
    with pytest.raises(RateBudgetExceededError, match="IP-level hold outlasts"):
        await governor.acquire("uid-1", ORDER, lane="entry", deadline_s=5.0)
    assert (governor.remaining("uid-1", ORDER), governor._ip.bucket.tokens) == (10.0, 600.0)


async def test_an_ended_hold_is_cleared_only_while_no_new_one_has_been_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Another loop's `10018` can land just after this loop found its old hold ended: the
    clear that follows must not wipe the new hold."""
    now = [0.0]
    governor = TokenBucketGovernor(clock=lambda: now[0])
    governor.hold_ip(10.0)
    now[0], look = 11.0, governor.ip_hold_remaining_s

    def look_then_hold() -> float:
        left = look()
        governor.hold_ip(50.0)
        return left

    monkeypatch.setattr(governor, "ip_hold_remaining_s", look_then_hold)
    await governor._wait_ip_hold(None)
    assert governor._ip.hold_until == 61.0


class _Watched:
    """A shared field that notes each product-code read or write (`__init__` aside) made without
    the lock; one thread runs at a time, so a held lock is held by the reader."""

    def __init__(self, owner: type, name: str, guard: Any, misses: list[str]) -> None:
        self.name, self.slot, self.guard, self.misses = name, vars(owner).get(name), guard, misses

    def _note(self) -> None:
        code = sys._getframe(2).f_code
        if code.co_filename == rate_limit.__file__ and code.co_name != "__init__":
            if not self.guard.locked():
                self.misses.append(f"{code.co_name}: {self.name}")

    def __get__(self, obj: Any, owner: Any = None) -> Any:
        if obj is None:
            return self
        self._note()
        return obj.__dict__[self.name] if self.slot is None else self.slot.__get__(obj, owner)

    def __set__(self, obj: Any, value: Any) -> None:
        self._note()
        if self.slot is None:
            obj.__dict__[self.name] = value
        else:
            self.slot.__set__(obj, value)


def test_the_shared_state_is_read_and_changed_only_under_the_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """m-2: acquire, refusal, cancel, hold, drain, header, remaining, headroom, on two loops."""
    now, sleep, misses = [0.0], _Parked(), list[str]()
    governor = TokenBucketGovernor(ip_budget_per_5s=2, clock=lambda: now[0], sleep=sleep)
    watched = [(_Bucket, "tokens"), (_Bucket, "updated_at"), (_Bucket, "heads")]
    for owner, name in [*watched, (_IpGate, "hold_until"), (TokenBucketGovernor, "_buckets")]:
        watcher = _Watched(owner, name, governor._guard, misses)
        monkeypatch.setattr(owner, name, watcher, raising=False)  # `_buckets` is per instance
    view = governor.capped(5)
    with _two_loops() as (a, b):
        a.run(view.acquire("uid-1", ACCOUNT, lane="poll"))
        b.run(governor.acquire("uid-2", ORDER, lane="entry"))  # the IP bucket is empty now
        with pytest.raises(RateBudgetExceededError):
            b.run(governor.acquire("uid-2", ORDER, lane="entry", deadline_s=0.0))
        waiter = a.run(_spawn(governor.acquire("uid-1", ORDER, lane="entry")))
        sleep.wait(1)
        assert a.run(_cancel(waiter))  # it gives its UID token back and leaves the queue
        b.run(_on(governor.hold_ip, 5.0))
        now[0] = 10.0  # the hold has ended: the next acquire clears it
        a.run(governor.acquire("uid-1", ORDER, lane="entry"))
        b.run(_on(governor.drain, "uid-2", ORDER, 1.0))
        b.run(_on(governor.observe_header, "uid-2", ORDER, 3))
        a.run(_on(governor.remaining, "uid-1", ORDER))
        a.run(_on(lambda: governor.headroom("uid-3", ORDER, lane="entry")))
    assert misses == []


# -- the per-loop turn (`_Turn`, ruling 3: public asyncio only; L-2, R-1) ----------------------


@pytest.mark.parametrize(
    ("cut", "order"),
    [(None, [0, 1, 2]), ("waiting", [0, 2]), ("handed", [1, 2])],
    ids=["first-come-first-served", "the-middle-taker-cut", "cut-after-the-hand-off"],
)
async def test_a_turn_serves_its_takers_in_order_and_never_loses_a_hand_off(
    cut: str | None, order: list[int]
) -> None:
    """`release` hands the turn on, held throughout, so no newcomer barges in; a taker cut while
    it waits leaves the order as it was, one cut after the hand-off passes the turn on."""
    turn, served = _Turn(), list[int]()

    async def take(n: int) -> None:
        await turn.acquire()
        served.append(n)
        turn.release()

    await turn.acquire()
    takers = [asyncio.ensure_future(take(n)) for n in range(3)]
    await asyncio.sleep(0)  # each is queued now
    if cut == "waiting":
        takers[1].cancel()
    turn.release()
    held = turn.locked()
    if cut == "handed":
        takers[0].cancel()
    async with asyncio.timeout(1.0):  # a guard: a lost hand-off would wait for ever
        await asyncio.gather(*takers, return_exceptions=True)
    assert (held, served, turn.locked(), len(turn._waiters)) == (True, order, False, 0)


async def test_under_a_zero_timeout_a_free_turn_is_taken_and_a_held_one_leaves_no_trace() -> None:
    """A free turn is taken without yielding, so `deadline_s=0` never refuses it as busy."""
    turn = _Turn()
    async with asyncio.timeout(0):
        await turn.acquire()
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0):
            await turn.acquire()
    assert turn.locked() and not turn._waiters


def test_a_free_turn_cannot_be_released() -> None:
    with pytest.raises(RuntimeError, match="not held"):
        _Turn().release()


STEPS = st.tuples(st.sampled_from(["take", "cut", "give", "run"]), st.integers(0, 7))


@given(st.lists(STEPS, max_size=40))
def test_a_turn_never_strands_its_takers_whatever_the_order_of_takes_cuts_and_releases(
    steps: list[tuple[str, int]],
) -> None:
    asyncio.run(_drive(steps))


async def _drive(steps: list[tuple[str, int]]) -> None:
    """Takes, cuts and releases in the order `steps` gives, settling only on "run": once settled,
    the turn is locked exactly when one holder has it, in order, and free means none queued."""
    turn, holders, takers = _Turn(), list[int](), list[asyncio.Task[None]]()
    released = 0

    async def take(n: int) -> None:
        await turn.acquire()
        holders.append(n)

    async def settle() -> None:
        for _ in range(2 * len(takers) + 2):
            await asyncio.sleep(0)
        held = len(holders) - released
        assert held in {0, 1} and turn.locked() == (held == 1)
        assert (turn.locked() or not turn._waiters) and holders == sorted(holders)

    for step, n in steps:
        if step == "take":
            takers.append(asyncio.ensure_future(take(len(takers))))
        elif step == "cut" and (waiting := [t for t in takers if not t.done()]):
            waiting[n % len(waiting)].cancel()  # one handed the turn included
        elif step == "give" and len(holders) > released:
            turn.release()
            released += 1
        elif step == "run":
            await settle()
    for taker in takers:
        taker.cancel()
    await settle()
    if len(holders) > released:
        turn.release()
        released += 1
    await settle()  # free now, none queued
