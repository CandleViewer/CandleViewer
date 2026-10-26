"""#913 slice 3 L1b (E29-T04, 29 CV-C13): the seven `Served*` bridges, each on a real order lane
whose serving loop is this test's (CR-S3L1B-02); L2 gave the lane its own audit writer and sink,
so neither crosses any more. A stalled serving loop is one blocked on an event; each wait is a
bound on the test, never a time it expects."""

from __future__ import annotations

import asyncio
import inspect
import threading
from collections.abc import Callable, Sequence
from typing import Any
from uuid import UUID

import pytest

from candleviewer import oms_wiring
from candleviewer.accounts.verification import Refusal
from candleviewer.domain.order_entry import OrderEntryRefusal
from candleviewer.exchange.base.models import AccountRef, Position
from candleviewer.exchange.base.ports import TradingPort
from candleviewer.observability.metrics import Metrics
from candleviewer.oms_lane import Serving
from candleviewer.oms_wiring import (
    ServedClock,
    ServedDemand,
    ServedFeed,
    ServedGate,
    ServedPort,
    ServedProfiles,
    ServedStandings,
)
from tests.unit.oms import command_rig as cr
from tests.unit.oms.test_oms_runtime import Port
from tests.unit.oms.test_order_lane import BOUND_S, running

OTHER = UUID(int=2)
#: What the serving loop's side of each bridge was called for, and on which thread.
Calls = list[tuple[str, threading.Thread]]


class Spy:
    """The serving loop's side of every bridge: each call by its name and thread, a coroutine
    member's when it runs."""

    def __init__(self, calls: Calls) -> None:
        self.calls = calls

    def __getattr__(self, name: str) -> Callable[..., Any]:
        def noted(*_args: Any, **_kwargs: Any) -> None:
            self.calls.append((name, threading.current_thread()))

        async def run(*args: Any, **kwargs: Any) -> None:
            noted()

        awaited = name in ("get_effective_profile", "resync_after_signature_failure")
        return run if awaited else noted


def _serving() -> Serving:
    return Serving(asyncio.get_running_loop(), Metrics("demo"))


async def test_the_gate_is_read_on_the_lane_before_a_notice_sent_ahead_of_it_lands() -> None:
    """#913 L4 (C-2.21): the lane reads the gate in place, twice, never waiting on the serving loop,
    so a read of another account answers there while a rejection's notice sent ahead of it waits
    for this loop; the account the notice names the lane refuses meanwhile itself (below)."""
    calls, done, serving = Calls(), threading.Event(), _serving()
    spy: Any = Spy(calls)
    standings = ServedStandings(spy, serving)
    gate = ServedGate(spy, standings)

    async def rejected() -> threading.Thread:
        try:
            standings.credential_rejected(cr.ACCOUNT, Refusal.UNKNOWN_KEY)
            assert gate.refusal(OTHER) is None
            return threading.current_thread()
        finally:
            done.set()

    async with running() as lane:
        answered = lane.call(rejected())
        assert done.wait(BOUND_S)  # this loop blocks meanwhile: the notice cannot land
        on = await answered
        await lane.call(asyncio.sleep(0))  # this loop has turned: the notice has landed
    here = threading.current_thread()
    assert calls == [("refusal", on), ("refusal", on), ("credential_rejected", here)]


async def test_a_rejected_credential_is_refused_on_the_lane_before_its_notice_lands() -> None:
    """CR-S3L1B-04 (C-2.21): while this loop stalls, the lane's gate refuses at once an account it
    told of a rejected credential, without this loop; once the notice lands, the lane's own refusal
    ends and the key standing's answers."""
    calls, done, serving = Calls(), threading.Event(), _serving()
    spy: Any = Spy(calls)
    standings = ServedStandings(spy, serving)
    gate = ServedGate(spy, standings)

    async def rejected() -> OrderEntryRefusal | None:
        try:
            standings.credential_rejected(cr.ACCOUNT, Refusal.UNKNOWN_KEY)
            return gate.refusal(cr.ACCOUNT)
        finally:
            done.set()

    async with running() as lane:
        answered = lane.call(rejected())
        assert done.wait(BOUND_S)  # the stall: the notice cannot land meanwhile
        refused = await answered
        assert refused is not None and refused.reason == "no_active_key"
        await lane.call(asyncio.sleep(0))  # this loop has turned: the notice has landed
    assert not standings.refused(cr.ACCOUNT) and [name for name, _ in calls] == [
        "credential_rejected"
    ]


async def test_a_landed_rejection_is_dropped_never_a_later_one_and_a_failed_one_stays() -> None:
    """SEC-S3L1C-03: the lane's own refusal is the gate's `NO_ACTIVE_KEY`; a rejection whose notice
    has landed is dropped, never a later one of its account still on its way; one whose notice
    fails there stays refused for good."""
    loop, seen = asyncio.new_event_loop(), list[bool]()  # a serving loop that turns only below

    class Standing:
        def credential_rejected(self, account_id: UUID, refusal: Refusal) -> None:
            seen.append(standings.refused(cr.ACCOUNT))
            if account_id == OTHER:
                raise RuntimeError("the key standing failed")

    standing: Any = Standing()
    serving = Serving(loop, Metrics("demo"))
    standings = ServedStandings(standing, serving)
    for account in (cr.ACCOUNT, cr.ACCOUNT, OTHER):
        standings.credential_rejected(account, Refusal.UNKNOWN_KEY)
    await asyncio.to_thread(loop.run_until_complete, asyncio.sleep(0))  # the notices land
    loop.close()
    assert seen == [True, True, False] and list(standings._sent) == [OTHER]
    assert ServedGate(standing, standings).refusal(OTHER) is oms_wiring.NO_ACTIVE_KEY


async def test_the_port_awaits_each_venue_call_on_the_serving_loop_and_refuses_a_private_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CR-S3L1B-05: each coroutine member of the trading port but `subscribe_private` is declared
    and awaited on the serving loop; the private stream is a typed refusal; the headroom is read
    in place, on the lane."""
    threads, positions = list[threading.Thread](), Port.positions

    async def noted(self: Port, account: AccountRef) -> Sequence[Position]:
        threads.append(threading.current_thread())
        return await positions(self, account)

    monkeypatch.setattr(Port, "positions", noted)
    served = ServedPort(Port(environment="demo"), _serving())

    async def on_lane() -> None:
        assert await served.positions(cr.ref()) == []
        assert served.headroom(cr.ref(), "entry").lane == "entry"
        with pytest.raises(oms_wiring.PrivateStreamRefused):
            await served.subscribe_private(cr.ref())

    async with running() as lane:
        await lane.call(on_lane())
    assert threads == [threading.current_thread()]
    hops = {name for name, m in inspect.getmembers(TradingPort) if inspect.iscoroutinefunction(m)}
    assert hops - set(vars(served)) == {"subscribe_private"}


async def test_the_feed_demand_profiles_and_clock_land_on_the_serving_loop() -> None:
    """The notices land in order, before the awaited hops after them; the clock's health is read in
    place, on the lane."""
    calls, serving = Calls(), _serving()
    spy: Any = Spy(calls)

    async def on_lane() -> threading.Thread:
        ServedFeed(spy, serving).publish(OTHER, cr.ACCOUNT, {}, last=True)
        ServedDemand(spy, serving).asked("BTCUSDT", priced=False)
        await ServedProfiles(spy, serving).get_effective_profile(cr.ACCOUNT)
        clock = ServedClock(spy, serving)
        clock.assert_healthy()
        await clock.resync_after_signature_failure(reason="signature")
        return threading.current_thread()

    async with running() as lane:
        on = await lane.call(on_lane())
    here = threading.current_thread()
    assert calls == [
        ("publish", here), ("asked", here), ("get_effective_profile", here),
        ("assert_healthy", on), ("resync_after_signature_failure", here),
    ]  # fmt: skip
