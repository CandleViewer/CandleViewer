"""The venue cancel-all fold's standalone rules (E29-T04 #913 slice 4, S4-F; 24 Sec.8.7): a
symbol's cancels fold only when every plain order resting there is selected, and one venue
`cancel-all` leaves per UID per second, on an injected monotonic clock."""

from __future__ import annotations

import asyncio
import math
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.models import Order
from candleviewer.oms.cancel_all_fold import (
    CANCEL_ALL_INTERVAL_S,
    FOLDED_KIND,
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
    """`orderFilter=Order` cancels plain orders only: a TP/SL or a conditional order stays put, so
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
