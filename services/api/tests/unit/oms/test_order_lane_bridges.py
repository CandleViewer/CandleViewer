"""#913 slice 3 L1b (E29-T04, 29 CV-C13): the nine `Served*` bridges, each on a real order lane
whose serving loop is this test's (CR-S3L1B-02). A stalled serving loop is one blocked on an
event; each wait is a bound on the test, never a time it expects."""

from __future__ import annotations

import asyncio
import inspect
import threading
from collections.abc import Callable, Sequence
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer import oms_wiring
from candleviewer.accounts.verification import Refusal
from candleviewer.audit.machine_events import APPEND_FAILURE_COOLDOWN_S
from candleviewer.domain.order_entry import OrderEntryRefusal
from candleviewer.exchange.base.models import AccountRef, Position
from candleviewer.exchange.base.ports import TradingPort
from candleviewer.observability.metrics import Metrics
from candleviewer.oms.cancel_all import CancelAll
from candleviewer.oms.errors import OmsNotReady
from candleviewer.oms.exits import OrderExits
from candleviewer.oms_lane import Serving
from candleviewer.oms_wiring import (
    OnLaneCancelAll,
    OnLaneExits,
    ServedAudit,
    ServedClock,
    ServedDemand,
    ServedFeed,
    ServedGate,
    ServedPort,
    ServedProfiles,
    ServedSink,
    ServedStandings,
)
from candleviewer.statechart.plugins.audit import CvAuditPlugin
from tests.unit.oms import command_rig as cr
from tests.unit.oms.test_oms_runtime import Port
from tests.unit.oms.test_order_lane import BOUND_S, running

OTHER = UUID(int=2)
#: What the serving loop's side of each bridge was called for, and on which thread.
Calls = list[tuple[str, threading.Thread]]
#: The sink bridge's page for an append the serving loop did not begin: its class alone.
DROPPED = {
    "event": "oms_sink_append_dropped",
    "cv_page": True,
    "error": "TimeoutError",
    "log_level": "critical",
}


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

        awaited = name in ("get_effective_profile", "resync_after_signature_failure", "emit")
        return run if awaited else noted


def _serving() -> Serving:
    return Serving(asyncio.get_running_loop(), Metrics("demo"))


async def test_a_stalled_serving_loop_leaves_the_gate_not_ready_and_the_sink_unrun() -> None:
    """C-2.21, fail closed: this loop is blocked, so neither blocking hop begins here within its
    bound. The gate is `OmsNotReady`, logged, so nothing is sent; the sink's append raises; neither
    runs once this loop turns again."""
    calls, done, serving = Calls(), threading.Event(), _serving()
    spy: Any = Spy(calls)
    gate, sink = ServedGate(spy, serving, ServedStandings(spy, serving)), ServedSink(spy, serving)

    async def hops() -> list[str]:
        failed = []
        try:
            gate.refusal(cr.ACCOUNT)
        except OmsNotReady:
            failed.append("gate")
        try:
            sink.append(spy)
        except TimeoutError:
            failed.append("sink")
        done.set()
        return failed

    with capture_logs() as logs:
        async with running() as lane:
            answered = lane.call(hops())
            assert done.wait(BOUND_S)  # this loop blocks meanwhile: the stall
            assert await answered == ["gate", "sink"]
            await lane.call(asyncio.sleep(0))  # this loop has turned meanwhile
    unanswered = [e["account_id"] for e in logs if e["event"] == "oms_gate_unanswered"]
    assert unanswered == [str(cr.ACCOUNT)] and calls == []


async def test_an_unbegun_append_pages_once_in_its_window_and_still_reaches_the_plugin() -> None:
    """SEC-S3L1CE-01 (24 Sec.17.6, M19): a write-ahead row the stalled serving loop does not begin
    within 1 s never runs, a hole no chain check sees. The bridge pages it, by its class alone and
    once in its window, and still raises it to the audit plugin, which counts each; the plugin's
    hook contains it, so the machine's step runs on, as it will until L2."""
    calls, done, serving = Calls(), threading.Event(), _serving()
    spy: Any = Spy(calls)
    plugin = CvAuditPlugin(
        machine_kind="order",
        entity_id=str(OTHER),
        env="demo",
        sink=ServedSink(spy, serving, monotonic=lambda: 0.0),  # both appends in one window
        write_ahead=True,
    )

    async def steps() -> None:
        try:
            for _ in range(2):  # two steps, each with its write-ahead row
                plugin.on_event_received(None, SimpleNamespace(type="SUBMIT", data={"qty": "1"}))
                plugin.on_action_execute(None, "send_create")  # contained: never raises
        finally:
            done.set()

    with capture_logs() as logs:
        async with running() as lane:
            answered = lane.call(steps())
            assert done.wait(BOUND_S)  # this loop blocks meanwhile: the stall
            await answered
            await lane.call(asyncio.sleep(0))  # this loop has turned meanwhile
    assert [e for e in logs if e.get("cv_page")] == [DROPPED]
    failed = [e["error"] for e in logs if e["event"] == "statechart_audit_sink_failed"]
    assert failed == ["TimeoutError"] * 2
    assert (plugin.sink_failures, plugin.hook_errors, calls) == (2, 2, [])


def test_the_drop_pages_each_windows_first_and_a_begun_refusal_is_the_sinks_to_page() -> None:
    """SEC-S3L1CE-01: the bridge pages the first unbegun append of each window, M19's own
    (`APPEND_FAILURE_COOLDOWN_S`, in which the sink pages its own failed appends), on the injected
    clock. A refusal the serving loop's sink answered is raised as it is and paged by the sink
    (`audit/machine_events.py`), never here."""

    class Hop:
        """The serving loop's blocking hop, begun or not as the test sets it, never waiting."""

        begun = False

        def block(self, fn: Callable[[], None]) -> None:
            if not self.begun:
                raise TimeoutError
            fn()

    class Refusing:
        def append(self, row: Any) -> None:
            raise ValueError("the sink refused the row")

    now, hop = [0.0], Hop()
    served: Any = hop
    row: Any = SimpleNamespace()  # never read: the refusing sink raises at once
    sink = ServedSink(Refusing(), served, monotonic=lambda: now[0])
    window = APPEND_FAILURE_COOLDOWN_S
    with capture_logs() as logs:
        for at, begun, error in (
            (0.0, False, TimeoutError),
            (window - 0.001, False, TimeoutError),
            (window - 0.001, True, ValueError),
            (window, False, TimeoutError),
        ):
            now[0], hop.begun = at, begun
            with pytest.raises(error):
                sink.append(row)
    assert [e for e in logs if e.get("cv_page")] == [DROPPED, DROPPED]
    assert oms_wiring.SINK_PAGE_COOLDOWN_S == window


async def test_a_rejected_credentials_notice_lands_before_a_later_gate_read_from_the_lane() -> None:
    """C-2.21: the notice is never awaited, yet it reaches the key standing before any gate read the
    lane makes after it."""
    calls, serving = Calls(), _serving()
    spy: Any = Spy(calls)
    standings = ServedStandings(spy, serving)
    gate = ServedGate(spy, serving, standings)

    async def rejected() -> OrderEntryRefusal | None:
        standings.credential_rejected(cr.ACCOUNT, Refusal.UNKNOWN_KEY)
        return gate.refusal(OTHER)

    async with running() as lane:
        assert await lane.call(rejected()) is None
    here = threading.current_thread()
    assert calls == [("credential_rejected", here), ("refusal", here)]


async def test_a_rejected_credential_is_refused_on_the_lane_before_its_notice_lands() -> None:
    """CR-S3L1B-04 (C-2.21): while this loop stalls, the lane's gate refuses at once an account it
    told of a rejected credential, without this loop; once the notice lands, the lane's own refusal
    ends and the key standing's answers."""
    calls, done, serving = Calls(), threading.Event(), _serving()
    spy: Any = Spy(calls)
    standings = ServedStandings(spy, serving)
    gate = ServedGate(spy, serving, standings)

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
    assert ServedGate(standing, serving, standings).refusal(OTHER) is oms_wiring.NO_ACTIVE_KEY


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


async def test_the_feed_demand_profiles_clock_and_audit_land_on_the_serving_loop() -> None:
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
        await ServedAudit(spy, serving).emit("orders.submit")
        return threading.current_thread()

    async with running() as lane:
        on = await lane.call(on_lane())
    here = threading.current_thread()
    assert calls == [
        ("publish", here), ("asked", here), ("get_effective_profile", here),
        ("assert_healthy", on), ("resync_after_signature_failure", here), ("emit", here),
    ]  # fmt: skip


@pytest.mark.parametrize(
    ("bridge", "service"),
    [(OnLaneExits, OrderExits), (OnLaneCancelAll, CancelAll)],
    ids=["exits", "cancel_all"],
)
def test_each_lane_bridge_takes_exactly_its_services_parameters(
    bridge: type, service: type
) -> None:
    """A bridge re-declares each coroutine it hops to the lane, so a parameter the service has and
    the bridge does not take is a TypeError in the route that passes it, or a value the service
    never sees (`deny`'s `step`, #913): each public coroutine of a bridge takes exactly its
    service's same-named parameters, by name, kind and default."""
    hops = {
        name: method
        for name, method in inspect.getmembers(bridge, inspect.iscoroutinefunction)
        if not name.startswith("_")
    }
    assert hops  # the bridge was read, not an emptied scan
    for name, hop in hops.items():
        own = inspect.signature(getattr(service, name)).parameters.values()
        lane = inspect.signature(hop).parameters.values()
        assert [(p.name, p.kind, p.default) for p in lane] == [
            (p.name, p.kind, p.default) for p in own
        ], name
