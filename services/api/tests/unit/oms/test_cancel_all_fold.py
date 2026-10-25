"""The venue cancel-all fold's standalone parts (E29-T04 #913 slice 4, S4-F; 24 Sec.8.7): a
symbol's cancels fold only when every plain order resting there is selected; one venue
`cancel-all` leaves per UID per second, on an injected monotonic clock; and its members meet at a
join that sends one call once all have arrived, else none (the fail-safe). Nothing sleeps: the
gather's bound is an injected sleep the test releases."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Coroutine
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.errors import TransportError, UnknownStateError
from candleviewer.exchange.base.models import Order, OrderAck
from candleviewer.oms.cancel_all_fold import (
    CANCEL_ALL_INTERVAL_S,
    FOLDED_KIND,
    GATHER_S,
    CancelAllJoin,
    CancelAllSpacer,
    covers,
)

_ACCOUNT = AccountId(UUID("5b1c9d2e-7f30-4a6b-8c4d-2e3f4a5b6c7d"))


def _resting(link: str, kind: Any = "order") -> Order:
    return Order(
        order_link_id=link, exchange_order_id=f"x-{link}", account_id=_ACCOUNT, symbol="BTCUSDT",
        side="buy", order_type="limit", qty=Decimal("0.010"), price=Decimal("60000"), state="new",
        filled_qty=Decimal("0"), leaves_qty=Decimal("0.010"), avg_fill_price=None,
        created_at=1_790_000_000_000_000, terminal_at=None, order_kind=kind,
    )  # fmt: skip


class _Clock:
    """A monotonic clock the test moves; `sleep` records each wait and moves it that far."""

    def __init__(self, now: float = 100.0) -> None:
        self.now, self.slept = now, list[float]()

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def test_a_symbol_whose_every_plain_resting_order_is_selected_folds() -> None:
    assert covers([_resting("a"), _resting("b")], {"a", "b", "c"})  # c: not resting, its own cancel


def test_a_plain_order_the_request_left_out_keeps_the_symbol_on_per_order_cancels() -> None:
    assert not covers([_resting("a"), _resting("theirs")], {"a"})


@pytest.mark.parametrize(
    "kind", ["conditional", "take_profit", "stop_loss", "partial_stop_loss", "trailing_stop"]
)
def test_an_order_the_venues_cancel_all_leaves_does_not_count(kind: str) -> None:
    """The venue's plain-order filter (24 Sec.14.2 rule 12, SR-E29-06) cancels plain orders only:
    a TP/SL or a conditional order stays put, so
    it neither blocks the fold nor is taken by it (SR-E29-06)."""
    assert covers([_resting("a"), _resting("stop", kind)], {"a"})
    assert not covers([_resting("stop", kind)], {"stop"})  # nothing plain rests: no fold
    assert FOLDED_KIND == "order"


def test_nothing_resting_folds_nothing() -> None:
    assert not covers([], {"a"})


async def test_the_first_cancel_all_of_a_uid_leaves_at_once() -> None:
    clock = _Clock()
    spacer = CancelAllSpacer(monotonic=clock, sleep=clock.sleep)
    assert await spacer.turn("100001", deadline=clock.now + 5)
    assert clock.slept == []


async def test_the_next_waits_out_the_uids_second() -> None:
    clock = _Clock()
    spacer = CancelAllSpacer(monotonic=clock, sleep=clock.sleep)
    assert await spacer.turn("100001", deadline=105.0)
    clock.now += 0.25
    assert await spacer.turn("100001", deadline=105.0)
    assert clock.slept == [pytest.approx(0.75)]
    assert CANCEL_ALL_INTERVAL_S == 1.0


async def test_a_second_past_the_last_the_next_leaves_at_once() -> None:
    clock = _Clock()
    spacer = CancelAllSpacer(monotonic=clock, sleep=clock.sleep)
    assert await spacer.turn("100001", deadline=105.0)
    clock.now += 1.0
    assert await spacer.turn("100001", deadline=105.0)
    assert clock.slept == []


async def test_after_a_quiet_spell_the_second_runs_from_the_call_not_the_old_slot() -> None:
    clock = _Clock()
    spacer = CancelAllSpacer(monotonic=clock, sleep=clock.sleep)
    assert await spacer.turn("100001", deadline=200.0)
    clock.now = 110.0  # long past the 101 slot
    assert await spacer.turn("100001", deadline=200.0)
    assert await spacer.turn("100001", deadline=200.0)
    assert clock.slept == [pytest.approx(1.0)]  # 110 then 111, never two inside one second


async def test_another_uid_has_its_own_second() -> None:
    clock = _Clock()
    spacer = CancelAllSpacer(monotonic=clock, sleep=clock.sleep)
    assert await spacer.turn("100001", deadline=105.0)
    assert await spacer.turn("100002", deadline=105.0)
    assert clock.slept == []


async def test_a_slot_past_the_deadline_is_refused_at_once_and_takes_nothing() -> None:
    clock = _Clock()
    spacer = CancelAllSpacer(monotonic=clock, sleep=clock.sleep)
    assert await spacer.turn("100001", deadline=105.0)
    assert not await spacer.turn("100001", deadline=100.5)  # its slot is 101
    assert clock.slept == []
    assert await spacer.turn("100001", deadline=101.0)  # the slot it did not take is still 101
    assert clock.slept == [pytest.approx(1.0)]


async def test_callers_that_arrive_together_leave_in_turn_a_second_apart() -> None:
    clock, waits = _Clock(), list[float]()
    held = asyncio.Event()

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        await held.wait()

    spacer = CancelAllSpacer(monotonic=clock, sleep=sleep)
    turns = [asyncio.create_task(spacer.turn("100001", deadline=110.0)) for _ in range(3)]
    for _ in range(5):
        await asyncio.sleep(0)
    assert turns[0].done() and waits == [1.0, 2.0]  # each took its slot before it waited
    held.set()
    assert await asyncio.gather(*turns) == [True, True, True]


async def test_a_caller_cancelled_while_it_waits_leaves_its_slot_spent() -> None:
    clock, held = _Clock(), asyncio.Event()

    async def sleep(seconds: float) -> None:
        await held.wait()

    spacer = CancelAllSpacer(monotonic=clock, sleep=sleep)
    assert await spacer.turn("100001", deadline=110.0)
    waiting = asyncio.create_task(spacer.turn("100001", deadline=110.0))
    await asyncio.sleep(0)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    assert not await spacer.turn("100001", deadline=101.5)  # 101 was spent: the next slot is 102


async def test_the_uids_it_remembers_are_bounded_by_those_whose_slot_passed() -> None:
    clock = _Clock()
    spacer = CancelAllSpacer(monotonic=clock, sleep=clock.sleep, max_uids=2)
    for uid in ("u1", "u2"):
        assert await spacer.turn(uid, deadline=105.0)
    clock.now += 1.0  # both slots passed
    assert await spacer.turn("u3", deadline=105.0)
    assert set(spacer._free_at) == {"u3"}  # the passed ones are forgotten, the new one kept
    for uid in ("u4", "u5"):
        assert await spacer.turn(uid, deadline=105.0)
    assert set(spacer._free_at) == {"u3", "u4", "u5"}  # none passed yet: none forgotten


@pytest.mark.parametrize("interval_s", [0, -1.0, math.nan, math.inf, True])
def test_the_interval_is_finite_and_above_zero(interval_s: float) -> None:
    with pytest.raises(ValueError, match="interval_s"):
        CancelAllSpacer(monotonic=_Clock(), interval_s=interval_s)


@pytest.mark.parametrize("max_uids", [0, -1, True])
def test_at_least_one_uid_is_remembered(max_uids: int) -> None:
    with pytest.raises(ValueError, match="max_uids"):
        CancelAllSpacer(monotonic=_Clock(), max_uids=max_uids)


def _ack(link: str | None, *, ok: bool = True) -> OrderAck:
    return OrderAck(
        ok=ok, order_link_id=link, exchange_order_id=None if link is None else f"x-{link}",
        error_code=None if ok else "RATE_LIMITED", latency_ms=3, transport="rest",
    )  # fmt: skip


class _Venue:
    """The fold's slot and its one call: the slot comes at once, or once `slot_hold` is set, as
    `slot_ok` says; the call answers `acks` (or raises `error`) once `hold` is set. Each counted."""

    def __init__(
        self,
        acks: list[OrderAck] | None = None,
        error: BaseException | None = None,
        *,
        slot_ok: bool = True,
    ) -> None:
        self.acks, self.error, self.slot_ok = acks or [], error, slot_ok
        self.slots, self.calls = 0, 0
        self.hold: asyncio.Event | None = None
        self.slot_hold: asyncio.Event | None = None

    async def slot(self) -> bool:
        self.slots += 1
        if self.slot_hold is not None:
            await self.slot_hold.wait()
        return self.slot_ok

    async def call(self) -> list[OrderAck]:
        self.calls += 1
        if self.hold is not None:
            await self.hold.wait()
        if self.error is not None:
            raise self.error
        return self.acks


class _Gather:
    """The gather's sleep: it ends only when the test lets the bound pass; `stopped` counts the
    waits cut short (the watchdog stopped)."""

    def __init__(self) -> None:
        self.passed, self.asked, self.stopped = asyncio.Event(), list[float](), 0

    async def sleep(self, seconds: float) -> None:
        self.asked.append(seconds)
        try:
            await self.passed.wait()
        except asyncio.CancelledError:
            self.stopped += 1
            raise


class _Owner:
    """The join's owner, as the coalescer is: it spawns and holds each of the join's tasks."""

    def __init__(self) -> None:
        self.tasks: list[asyncio.Task[None]] = []

    def spawn(self, coro: Coroutine[Any, Any, None], *, name: str) -> asyncio.Task[None]:
        task = asyncio.create_task(coro, name=name)
        self.tasks.append(task)
        return task

    def named(self, name: str) -> list[asyncio.Task[None]]:
        return [task for task in self.tasks if task.get_name() == name]


def _join(
    venue: _Venue, *members: str, clock: _Clock | None = None, owner: _Owner | None = None
) -> tuple[CancelAllJoin, _Gather]:
    gather = _Gather()
    join = CancelAllJoin(
        members or ("a", "b"), venue.slot, venue.call, monotonic=clock or _Clock(),
        sleep=gather.sleep, spawn=(owner or _Owner()).spawn,
    )  # fmt: skip
    return join, gather


async def _settle() -> None:
    for _ in range(10):
        await asyncio.sleep(0)


async def test_once_every_member_arrives_one_call_answers_each_by_its_own_ack() -> None:
    venue = _Venue([_ack("a"), _ack("b")])
    join, _ = _join(venue)
    first = asyncio.create_task(join.arrive("a"))
    await _settle()
    assert not first.done() and venue.calls == 0  # waits for the other member
    assert await join.arrive("b") == _ack("b")
    assert await first == _ack("a") and venue.calls == 1
    assert (join.left, join.abandoned) == (True, None)


async def test_a_member_the_acks_do_not_name_sends_its_own_cancel() -> None:
    """The venue's 500-order cap, or a race: the member's own cancel follows (24 Sec.8.7)."""
    join, _ = _join(_Venue([_ack("a")]))
    first = asyncio.create_task(join.arrive("a"))
    assert await join.arrive("b") is None
    assert await first == _ack("a")


@pytest.mark.parametrize(
    ("acks", "slot_ok", "abandoned"),
    [([_ack(None, ok=False)], True, None), ([_ack(None)], True, None), ([], False, "slot")],
    ids=["refused", "none_cancelled", "spacer_refused"],
)
async def test_a_call_that_names_no_member_leaves_each_to_its_own_cancel(
    acks: list[OrderAck], slot_ok: bool, abandoned: str | None
) -> None:
    venue = _Venue(acks, slot_ok=slot_ok)
    join, _ = _join(venue)
    first = asyncio.create_task(join.arrive("a"))
    assert await join.arrive("b") is None
    assert await first is None
    assert (venue.calls, join.abandoned) == (0 if abandoned else 1, abandoned)


async def test_a_gather_past_its_bound_sends_nothing_and_each_sends_its_own() -> None:
    venue = _Venue([_ack("a"), _ack("b")])
    join, gather = _join(venue)
    first = asyncio.create_task(join.arrive("a"))
    await _settle()
    assert gather.asked == [pytest.approx(GATHER_S)]
    gather.passed.set()  # "b" never arrived in time
    assert await first is None
    assert await join.arrive("b") is None and venue.slots == venue.calls == 0  # it sends its own
    assert join.abandoned == "gather"


async def test_the_last_member_arriving_past_the_bound_sends_nothing() -> None:
    clock, venue = _Clock(), _Venue([_ack("a"), _ack("b")])
    join, _ = _join(venue, clock=clock)
    first = asyncio.create_task(join.arrive("a"))
    await _settle()
    clock.now += GATHER_S + 0.1  # the watchdog has not run yet, the clock has passed
    assert await join.arrive("b") is None
    assert await first is None and venue.slots == venue.calls == 0
    assert join.abandoned == "gather"


async def test_a_member_that_leaves_abandons_the_fold_at_once() -> None:
    venue = _Venue([_ack("a"), _ack("b")])
    join, gather = _join(venue)
    first = asyncio.create_task(join.arrive("a"))
    await _settle()
    join.leave("b")  # refused before its send: it will never arrive
    assert await first is None and venue.calls == 0 and not gather.passed.is_set()
    assert join.abandoned == "left"


async def test_a_leave_while_the_call_waits_for_its_slot_abandons_the_fold_and_its_wait() -> None:
    """L1: before the call leaves nothing was sent, so a member that no longer waits abandons the
    fold, and the call's wait for its slot ends with it."""
    venue = _Venue([_ack("a"), _ack("b")])
    venue.slot_hold = asyncio.Event()
    owner = _Owner()
    join, _ = _join(venue, owner=owner)
    first = asyncio.create_task(join.arrive("a"))
    last = asyncio.create_task(join.arrive("b"))
    await _settle()
    assert venue.slots == 1 and venue.calls == 0
    join.leave("a")
    assert (await first, await last) == (None, None)
    [call] = owner.named("oms-cancel-all-call")
    await asyncio.wait([call])
    assert call.cancelled() and venue.calls == 0 and join.abandoned == "left"


async def test_a_leave_once_the_call_has_left_changes_nothing() -> None:
    venue = _Venue([_ack("a"), _ack("b")])
    venue.hold = asyncio.Event()
    join, _ = _join(venue)
    first = asyncio.create_task(join.arrive("a"))
    last = asyncio.create_task(join.arrive("b"))
    await _settle()
    assert venue.calls == 1
    join.leave("a")
    venue.hold.set()
    assert (await first, await last) == (_ack("a"), _ack("b"))


async def test_the_bound_passing_while_the_call_is_out_keeps_its_answer() -> None:
    venue = _Venue([_ack("a"), _ack("b")])
    venue.hold = asyncio.Event()
    join, gather = _join(venue)
    first = asyncio.create_task(join.arrive("a"))
    last = asyncio.create_task(join.arrive("b"))
    await _settle()
    gather.passed.set()  # the watchdog was stopped when the last arrived; nothing changes
    await _settle()
    venue.hold.set()
    assert (await first, await last) == (_ack("a"), _ack("b"))


async def test_a_call_that_raises_raises_for_every_member_and_is_never_resent() -> None:
    """Its outcome is not known, as a member's own call's would not be (B1 parks it)."""
    fault = TransportError("the venue did not answer")
    venue = _Venue(error=fault)
    join, _ = _join(venue)
    first = asyncio.create_task(join.arrive("a"))
    with pytest.raises(TransportError):
        await join.arrive("b")
    with pytest.raises(TransportError):
        await first
    assert venue.calls == 1


async def test_a_call_cut_short_at_teardown_leaves_each_member_an_unknown_outcome() -> None:
    """Only the join's owner cuts a call short once it has left (its `aclose`): the call may have
    reached the venue, so each member still waiting has an unknown outcome, never re-sent."""
    venue = _Venue([_ack("a"), _ack("b")])
    venue.hold = asyncio.Event()
    owner = _Owner()
    join, _ = _join(venue, owner=owner)
    first = asyncio.create_task(join.arrive("a"))
    last = asyncio.create_task(join.arrive("b"))
    await _settle()
    [call] = owner.named("oms-cancel-all-call")
    call.cancel()
    for member in (first, last):
        with pytest.raises(UnknownStateError) as unknown:
            await member
        assert unknown.value.retryable is False
    assert venue.calls == 1


async def test_a_waiting_member_cancelled_before_the_call_abandons_the_fold() -> None:
    venue = _Venue([_ack("a"), _ack("b"), _ack("c")])
    join, _ = _join(venue, "a", "b", "c")
    first = asyncio.create_task(join.arrive("a"))
    second = asyncio.create_task(join.arrive("b"))
    await _settle()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert await second is None
    assert await join.arrive("c") is None and venue.calls == 0


async def test_a_member_arriving_again_gets_its_answer_again() -> None:
    join, _ = _join(_Venue([_ack("a"), _ack("b")]))
    first = asyncio.create_task(join.arrive("a"))
    await join.arrive("b")
    await first
    assert await join.arrive("a") == _ack("a")


async def test_only_a_member_arrives() -> None:
    join, _ = _join(_Venue([]))
    with pytest.raises(ValueError, match="member"):
        await join.arrive("z")


async def test_a_fold_has_a_member_and_a_finite_gather() -> None:
    venue = _Venue([])
    with pytest.raises(ValueError, match="member"):
        CancelAllJoin((), venue.slot, venue.call, monotonic=_Clock())
    for gather_s in (0, -1.0, math.nan, math.inf, True):
        with pytest.raises(ValueError, match="gather_s"):
            CancelAllJoin(("a",), venue.slot, venue.call, monotonic=_Clock(), gather_s=gather_s)


async def test_a_lone_member_sends_at_once() -> None:
    venue = _Venue([_ack("a")])
    join, gather = _join(venue, "a")
    assert await join.arrive("a") == _ack("a")
    assert venue.calls == 1 and gather.asked == []
