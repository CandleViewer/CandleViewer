"""#913 slice 3 L4 (E29-T04, C-2.21): the order-entry gate read in place on the order lane, with no
hop to the serving loop (the orchestrator's ruling of 2026-10-24 09:02Z), over the app's real gate:
the maintenance check, then the account check over a real key standing and health monitor, on a
real lane whose serving loop is this test's. A stalled serving loop is one blocked on an event; each
wait is a bound on the test, never a time it expects."""

from __future__ import annotations

import asyncio
import inspect
import sys
import threading
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import pytest

from candleviewer.accounts.health import AccountHealthMonitor
from candleviewer.accounts.key_standing import KeyStandings
from candleviewer.accounts.order_gate import AccountHealthCheck
from candleviewer.accounts.verification import Refusal
from candleviewer.admin.flags.maintenance import MAINTENANCE_REFUSAL, MaintenanceGate
from candleviewer.domain.order_entry import OrderEntryGate, OrderEntryRefusal
from candleviewer.observability.metrics import Metrics
from candleviewer.oms_lane import Serving
from candleviewer.oms_wiring import ServedGate, ServedStandings
from tests.unit.accounts._fakes import ACC, ACC_B, Dms, FakeClock, Sizing, key_row
from tests.unit.oms.test_order_lane import BOUND_S, running

#: How many times each race runs, one account each: a bound on the test, not a count it needs.
RACES = 48
#: The lane's reads while the serving loop is held mid-write, and once the write is done.
DURING, AFTER = 3, 3
#: A bound on the reads of one race, so a lane that never sees a write ends the test.
READS = 50_000
#: The reason a read answers: `None` admits.
Answer = str | None


class _Clock(FakeClock):
    """The key standing's clock. Armed for a thread, the next `now()` that thread calls holds it
    there until the lane has read meanwhile (`go`): a rejection is dated just before it is
    published, so its write is held half done and the race is run, never hoped for."""

    def __init__(self) -> None:
        super().__init__()
        self._thread: threading.Thread | None = None
        self.holding, self.go = threading.Event(), threading.Event()

    def arm(self, thread: threading.Thread) -> None:
        self._thread, self.holding, self.go = thread, threading.Event(), threading.Event()

    def now(self) -> datetime:
        if threading.current_thread() is self._thread:
            self._thread = None
            self.holding.set()
            assert self.go.wait(BOUND_S)
        return super().now()

    def held(self) -> bool:
        """The armed thread waits in `now()` meanwhile, its write not yet published."""
        return self.holding.is_set() and not self.go.is_set()


@dataclass
class _World:
    clock: _Clock
    standings: KeyStandings
    served: ServedStandings
    gate: ServedGate


def _serving() -> Serving:
    return Serving(asyncio.get_running_loop(), Metrics("demo"))


def _world(serving: Serving, accounts: Sequence[UUID]) -> _World:
    """The app's one gate as `create_app` composes it, the maintenance check disengaged, each of
    `accounts` listed with a fresh pass and healthy; the lane's bridges over it, as `OmsRuntime`
    builds them."""
    clock = _Clock()
    standings = KeyStandings(None, interval_s=3600.0, stale_after_s=60.0, clock=clock)
    standings.observe([key_row(account) for account in accounts])
    monitor = AccountHealthMonitor(FakeClock(), Dms())
    for account in accounts:
        monitor.track(account)
        monitor.ws_heartbeat(account)
    maintenance = MaintenanceGate()
    maintenance.set(False)
    gate = OrderEntryGate(maintenance, AccountHealthCheck(monitor, standings, Sizing()))
    served = ServedStandings(standings, serving)
    return _World(clock, standings, served, ServedGate(gate, served))


def _reason(refusal: OrderEntryRefusal | None) -> Answer:
    return None if refusal is None else refusal.reason


@contextmanager
def _finest_switching() -> Iterator[None]:
    """The interpreter switches threads as often as it can meanwhile, so the race is dense."""
    interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        yield
    finally:
        sys.setswitchinterval(interval)


def _answers(reads: list[tuple[str, Answer]], when: str) -> set[Answer]:
    return {answer for began, answer in reads if began == when}


async def test_a_stalled_serving_loop_leaves_the_gate_answering_on_the_lane_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#913 L4 (SEC-S3L1A-03): this loop is blocked, yet the lane reads the gate in place and
    answers each account at once as it stands, no hop begun. Before L4 each read waited
    `BLOCK_TIMEOUT_S` in `Serving.block` for this loop, which never began it, then refused
    `oms_not_ready`."""
    hops, block = list[str](), Serving.block

    def noted(self: Serving, fn: Callable[[], Any], **bound: Any) -> Any:
        hops.append("block")
        return block(self, fn, **bound)

    monkeypatch.setattr(Serving, "block", noted)
    world, done = _world(_serving(), [ACC]), threading.Event()

    async def reads() -> list[Answer]:
        try:
            return [_reason(world.gate.refusal(account)) for account in (ACC, ACC_B)]
        finally:
            done.set()

    async with running() as lane:
        answered = lane.call(reads())
        assert done.wait(BOUND_S)  # this loop blocks meanwhile: the stall
        assert await answered == [None, "no_active_key"]  # ACC_B: the read did not list it
    assert hops == []


async def _rejected_here(world: _World, account: UUID, barrier: threading.Barrier,
                         returned: threading.Event) -> list[tuple[str, Answer]]:  # fmt: skip
    """The lane's reads of one race, each with when it began: while the serving loop's write is
    held (`during`), once it has returned (`after`), else around it (`racing`)."""
    reads: list[tuple[str, Answer]] = []
    began: Counter[str] = Counter()
    barrier.wait()
    try:
        while began["after"] < AFTER and len(reads) < READS:
            when = "after" if returned.is_set() else "during" if world.clock.held() else "racing"
            reads.append((when, _reason(world.gate.refusal(account))))
            began[when] += 1
            if began["during"] == DURING:
                world.clock.go.set()  # the write goes on: it publishes, then returns
    finally:
        world.clock.go.set()
    return reads


async def test_a_serving_loop_rejection_refuses_every_lane_read_begun_after_it_returns() -> None:
    """The ruling's race (#913 L4): `credential_rejected` on the serving loop (a rejection one of
    its own signed calls met, as the wallet reconciler's) against the lane's gate reads, under a
    barrier, its write held half done until the lane has read meanwhile, and the threads switching
    at the finest grain. A read begun while it is held admits, the lane never waiting on this loop;
    from the moment it returns, every lane read that begins after it refuses; no read raises or
    answers anything else."""
    here, accounts = threading.current_thread(), [UUID(int=1_000 + race) for race in range(RACES)]
    world = _world(_serving(), accounts)
    async with running() as lane:
        with _finest_switching():
            for account in accounts:
                barrier, returned = threading.Barrier(2, timeout=BOUND_S), threading.Event()
                world.clock.arm(here)
                answered = lane.call(_rejected_here(world, account, barrier, returned))
                barrier.wait()  # this loop's thread, until the lane is there too
                world.standings.credential_rejected(account, Refusal.UNKNOWN_KEY)  # held a while
                returned.set()
                reads = await answered
                assert _answers(reads, "during") == {None}
                assert _answers(reads, "after") == {"no_active_key"}
                assert {answer for _, answer in reads} <= {None, "no_active_key"}


async def _rejected_on_the_lane(world: _World, account: UUID,
                                signed: threading.Event) -> list[tuple[str, Answer]]:  # fmt: skip
    """The lane's signed call meets a rejection, then its reads, each with when it began: its notice
    still in flight to the serving loop (`in_flight`), landing there, held half done (`landing`),
    or landed, the lane's own refusal dropped (`landed`)."""
    world.served.credential_rejected(account, Refusal.UNKNOWN_KEY)  # a lane-signed call met it
    reads = [("in_flight", _reason(world.gate.refusal(account)))]  # this loop is blocked
    began: Counter[str] = Counter()
    signed.set()
    try:
        while began["landed"] < AFTER and len(reads) < READS:
            landed = not world.served.refused(account)
            when = "landed" if landed else "landing" if world.clock.held() else "in_flight"
            reads.append((when, _reason(world.gate.refusal(account))))
            began[when] += 1
            if began["landing"] == DURING:
                world.clock.go.set()  # the notice's write goes on: the standing, then the drop
    finally:
        world.clock.go.set()
    return reads


async def test_a_rejection_the_lane_signed_refuses_every_lane_read_from_its_call_on() -> None:
    """#913 L4 with L1c's lane-local refusal (CR-S3L1B-04): a rejection a lane-signed call met is
    notified to the serving loop, never awaited; the lane reads the gate in place meanwhile, its
    first read while this loop is blocked, the notice's write held half done here while the lane
    reads. Every read from the rejection's call on refuses: the lane's own refusal until the notice
    lands, then the key standing's, which `_land` writes before it drops the lane's."""
    here, accounts = threading.current_thread(), [UUID(int=2_000 + race) for race in range(RACES)]
    world = _world(_serving(), accounts)
    async with running() as lane:
        with _finest_switching():
            for account in accounts:
                signed = threading.Event()
                world.clock.arm(here)  # the notice's write, when it lands on this loop
                answered = lane.call(_rejected_on_the_lane(world, account, signed))
                assert signed.wait(BOUND_S)  # this loop blocks until the lane has read once
                reads = await answered  # this loop turns: the notice lands meanwhile
                assert [began for began, _ in reads[:1]] == ["in_flight"]
                assert {"landing", "landed"} <= {began for began, _ in reads}
                assert {answer for _, answer in reads} == {"no_active_key"}


async def test_the_lane_admits_only_when_two_gate_reads_in_a_row_admit() -> None:
    """#913 L4: a read in place takes each source of the gate at its own instant, so one that
    overlaps writes to two of them may combine two instants; a refusing write that lands inside the
    first read is in force for the second, which begins after it, so only two admitting reads in a
    row admit, and a first refusal is the answer, no second read made."""

    class Turning:
        """The app's gate as writes landing meanwhile leave it, an answer a read."""

        def __init__(self, *answers: OrderEntryRefusal | None) -> None:
            self.answers = list(answers)

        def refusal(self, account_id: UUID) -> OrderEntryRefusal | None:
            return self.answers.pop(0)

    standing: Any = object()  # told of no rejection: never called
    served = ServedStandings(standing, _serving())
    for answers, expected in (
        ((None, MAINTENANCE_REFUSAL), MAINTENANCE_REFUSAL),
        ((MAINTENANCE_REFUSAL,), MAINTENANCE_REFUSAL),
        ((None, None), None),
    ):
        gate = Turning(*answers)
        assert ServedGate(gate, served).refusal(ACC) is expected and gate.answers == []


def test_the_gate_bridges_keep_the_signatures_of_what_they_carry() -> None:
    """A bridge re-declares what it carries: the gate's `refusal`, the app's one gate's, and the
    standings' `credential_rejected`, the key standing's, so a caller of either calls the bridge
    alike."""
    for bridge, carried in (
        (ServedGate.refusal, OrderEntryGate.refusal),
        (ServedStandings.credential_rejected, KeyStandings.credential_rejected),
    ):
        assert inspect.signature(bridge) == inspect.signature(carried)
