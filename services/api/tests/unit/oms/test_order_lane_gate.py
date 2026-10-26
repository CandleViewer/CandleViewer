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
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer import oms_wiring
from candleviewer.account_health_wiring import TRACKING_FAULT_AFTER_S
from candleviewer.accounts.health import AccountHealthMonitor
from candleviewer.accounts.key_standing import KeyStandings
from candleviewer.accounts.order_gate import AccountHealthCheck
from candleviewer.accounts.verification import Refusal
from candleviewer.admin.flags.maintenance import MAINTENANCE_REFUSAL, MaintenanceGate
from candleviewer.domain.order_entry import OrderEntryGate, OrderEntryRefusal
from candleviewer.domain.primitives import AccountId
from candleviewer.observability.metrics import Metrics
from candleviewer.oms.errors import OmsNotReady
from candleviewer.oms_lane import Serving
from candleviewer.oms_wiring import ServedGate, ServedStandings
from candleviewer.settings import ACCOUNT_DOWN_MAX_S
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
#: One lane read: when it began, the lane's gate's answer (`ServedGate`, which reads twice) and
#: that of one read of the app's gate under it, which no second read makes up for (CR-S3L4-03).
Read = tuple[str, Answer, Answer]


@pytest.fixture
def finest_switching() -> Iterator[None]:
    """The interpreter switches threads as often as it can while a race runs, so the race is dense.
    The switch interval is the process's, not the test's: this restores it in `finally` whatever
    the test does, and each test that takes it is marked `serial`, so no other test shares the
    process meanwhile (the orchestrator's ruling of 2026-10-25 18:27Z (4); no subprocess)."""
    interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        yield
    finally:
        sys.setswitchinterval(interval)


class _Clock(FakeClock):
    """The key standing's clock. Armed for a thread and a call, that thread's next such call holds
    it there until the lane has read meanwhile (`go`): `now` dates a rejection and `monotonic` ages
    a tracking read, each just before its write is published, so the write is held half done and
    the race is run, never hoped for."""

    def __init__(self) -> None:
        super().__init__()
        self._armed: tuple[threading.Thread, str] | None = None
        self.holding, self.go = threading.Event(), threading.Event()

    def arm(self, thread: threading.Thread, call: str) -> None:
        self._armed, self.holding, self.go = (thread, call), threading.Event(), threading.Event()

    def _hold(self, call: str) -> None:
        if self._armed == (threading.current_thread(), call):
            self._armed = None
            self.holding.set()
            assert self.go.wait(BOUND_S)

    def now(self) -> datetime:
        self._hold("now")
        return super().now()

    def monotonic(self) -> float:
        self._hold("monotonic")
        return super().monotonic()

    def held(self) -> bool:
        """The armed thread waits in its call meanwhile, its write not yet published."""
        return self.holding.is_set() and not self.go.is_set()


@dataclass
class _World:
    clock: _Clock
    health_clock: FakeClock
    standings: KeyStandings
    served: ServedStandings
    gate: ServedGate
    raw: OrderEntryGate  # the app's gate under `gate`
    accounts: Sequence[UUID]


def _serving() -> Serving:
    return Serving(asyncio.get_running_loop(), Metrics("demo"))


def _world(serving: Serving, accounts: Sequence[UUID]) -> _World:
    """The app's one gate as `create_app` composes it, the maintenance check disengaged, each of
    `accounts` listed with a fresh pass and healthy, the read's age bound the wiring's; the lane's
    bridges over it, as `OmsRuntime` builds them."""
    clock, health_clock = _Clock(), FakeClock()
    standings = KeyStandings(
        None, interval_s=3600.0, stale_after_s=TRACKING_FAULT_AFTER_S, clock=clock
    )
    standings.observe([key_row(account) for account in accounts])
    monitor = AccountHealthMonitor(health_clock, Dms())
    for account in accounts:
        monitor.track(account)
        monitor.ws_heartbeat(account)
    maintenance = MaintenanceGate()
    maintenance.set(False)
    gate = OrderEntryGate(maintenance, AccountHealthCheck(monitor, standings, Sizing()))
    served = ServedStandings(standings, serving)
    return _World(clock, health_clock, standings, served, ServedGate(gate, served), gate, accounts)


def _reason(refusal: OrderEntryRefusal | None) -> Answer:
    return None if refusal is None else refusal.reason


def _read(world: _World, account: UUID, when: str) -> Read:
    return when, _reason(world.gate.refusal(account)), _reason(world.raw.refusal(account))


def _answers(reads: list[Read], when: str) -> tuple[set[Answer], set[Answer]]:
    """The lane's gate's answers and the app's gate's, of the reads that began `when`."""
    begun = [read for read in reads if read[0] == when]
    return {served for _, served, _ in begun}, {raw for _, _, raw in begun}


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


async def test_a_stalled_serving_loop_leaves_the_lane_admitting_until_its_gate_ages_out() -> None:
    """CR-S3L4-04, the outer bounds (20 Sec.6.2, OM-D11): with this loop blocked nothing it writes
    lands, and the gate itself admits on what it last wrote (the switches of a new submit and of a
    risk-increasing amend are fenced first, `test_oms_runtime.py`), yet it judges its age bounds at
    read time: the account's health goes `down` `ACCOUNT_DOWN_MAX_S` after its last success, and
    the key standing lists nothing once its last tracking read is older than
    `TRACKING_FAULT_AFTER_S`."""
    world, done = _world(_serving(), [ACC]), threading.Event()
    health0, read0 = world.health_clock.mono, world.clock.mono

    def read_after(health_s: float, read_s: float) -> Answer:
        world.health_clock.mono, world.clock.mono = health0 + health_s, read0 + read_s
        return _reason(world.gate.refusal(ACC))

    async def reads() -> list[Answer]:
        try:
            return [
                read_after(ACCOUNT_DOWN_MAX_S - 0.001, TRACKING_FAULT_AFTER_S),
                read_after(ACCOUNT_DOWN_MAX_S, 0.0),
                read_after(0.0, TRACKING_FAULT_AFTER_S + 0.001),
            ]
        finally:
            done.set()

    async with running() as lane:
        answered = lane.call(reads())
        assert done.wait(BOUND_S)  # this loop blocks meanwhile: the stall
        assert await answered == [None, "account_unhealthy", "no_active_key"]


def test_the_serving_tick_is_stale_past_twice_its_interval_until_it_beats_again() -> None:
    """The orchestrator's CR-04 ruling of 2026-10-25 19:19Z: the lane reads the serving loop's tick
    in place, and a new submit, or a risk-increasing amend (the ruling of 21:56Z), is fenced once
    the last beat is older than twice the tick's interval, the 1 s within which a stalled serving
    loop refused a gate read before L4. Sticky: however long the lane waits, only a beat of the
    serving loop ends it. Past the bound the tick gives the age it judged (SEC-S3L4-04)."""
    now = [100.0]
    tick = oms_wiring.ServingTick(clock=lambda: now[0])
    assert oms_wiring.SERVING_STALE_S == 2 * oms_wiring.SERVING_TICK_S == 1.0
    now[0] += oms_wiring.SERVING_STALE_S
    assert tick.overdue() is None  # at twice its interval: not yet
    now[0] += 0.001
    assert tick.overdue() == pytest.approx(1.001)
    now[0] += 3600.0
    assert tick.overdue() == pytest.approx(3601.001)  # the time passing never ends it
    tick.beat()
    assert tick.overdue() is None


class _Admitting:
    """Switches that admit every account: only the fence refuses."""

    def refusal(self, account_id: AccountId, environment: str) -> None:
        return None


def test_the_fence_logs_the_age_it_judged_from_its_one_read_beside_its_bound() -> None:
    """SEC-S3L4-04 (the Fable lens at 8b626ef6): `oms_submit_fenced` names the last beat's age as
    the fence judged it, from its one read of the tick's clock, never the bound alone nor a later
    read, so a beat landing meanwhile never logs a fresh age for a refusal; the bound beside it."""
    reads = iter([100.0, 101.75, 160.0])  # the tick built; the fence's one read; any second read
    fenced = oms_wiring.FencedSwitches(
        _Admitting(), oms_wiring.ServingTick(clock=lambda: next(reads))
    )
    with capture_logs() as logs, pytest.raises(OmsNotReady):
        fenced.refusal(AccountId(ACC), "demo")
    assert [(e["event"], e["age_s"], e["stale_s"]) for e in logs] == [
        ("oms_submit_fenced", 1.75, oms_wiring.SERVING_STALE_S)
    ]


class _Open:
    """An order-entry gate that admits every account: only a fence refuses."""

    def refusal(self, account_id: UUID) -> None:
        return None


@pytest.mark.parametrize(
    ("stalled", "lost", "answer"),
    [
        (False, False, None),
        (False, True, "returned OmsNotReady"),
        (True, False, "raised"),
        (True, True, "raised"),
    ],
    ids=["neither", "lost_lock_alone", "stall_alone", "both"],
)
def test_the_stall_fence_and_the_lost_locks_compose_either_refusing_alone(
    stalled: bool, lost: bool, answer: str | None
) -> None:
    """20 Sec.6.2 on L4's re-base onto L2: `FencedSwitches` wraps the binding whose first refusal
    is the environment lock's fence (#913 L2), so the two compose, either refusing a new submit on
    its own: the lost lock's `OmsNotReady` returned, the stall fence's raised and logged. With
    both, the stall fence is read first and the binding is not asked."""
    now, asked = [100.0], list[str]()

    def fenced() -> bool:
        asked.append("lock")
        return lost

    binding = oms_wiring.TradingSwitchesBinding(
        live_enabled=False, live_flag=lambda: False, kill_switch=oms_wiring.InterimKillSwitch(),
        gate=_Open(), fenced=fenced,
    )  # fmt: skip
    switches = oms_wiring.FencedSwitches(binding, oms_wiring.ServingTick(clock=lambda: now[0]))
    if stalled:
        now[0] += 2 * oms_wiring.SERVING_STALE_S
    with capture_logs() as logs:
        try:
            refused = switches.refusal(AccountId(ACC), "demo")
        except OmsNotReady:
            got: str | None = "raised"
        else:
            got = None if refused is None else f"returned {type(refused).__name__}"
    assert got == answer
    assert [e["event"] for e in logs] == ["oms_submit_fenced"] * stalled
    assert asked == ([] if stalled else ["lock"])


def _rejected(world: _World, account: UUID) -> None:
    """A rejection one of the serving loop's own signed calls met (the wallet reconciler's)."""
    world.standings.credential_rejected(account, Refusal.UNKNOWN_KEY)


def _switched_off(world: _World, account: UUID) -> None:
    """A tracking read that finds the account switched off, the others as they were."""
    world.standings.observe([key_row(a, armed=a != account) for a in world.accounts])


async def _around_a_write(world: _World, account: UUID, barrier: threading.Barrier,
                          returned: threading.Event) -> list[Read]:  # fmt: skip
    """The lane's reads of one race, each with when it began: while the serving loop's write is
    held (`during`), once it has returned (`after`), else around it (`racing`)."""
    reads: list[Read] = []
    began: Counter[str] = Counter()
    barrier.wait()
    try:
        while began["after"] < AFTER and len(reads) < READS:
            when = "after" if returned.is_set() else "during" if world.clock.held() else "racing"
            reads.append(_read(world, account, when))
            began[when] += 1
            if began["during"] == DURING:
                world.clock.go.set()  # the write goes on: it publishes, then returns
    finally:
        world.clock.go.set()
    return reads


@pytest.mark.serial
@pytest.mark.usefixtures("finest_switching")
@pytest.mark.parametrize(
    ("call", "write", "refused"),
    [
        pytest.param("now", _rejected, "no_active_key", id="credential_rejected"),
        pytest.param("monotonic", _switched_off, "account_disabled_by_policy", id="observe"),
    ],
)
async def test_a_serving_loop_write_refuses_every_lane_read_begun_after_it_returns(
    call: str, write: Callable[[_World, UUID], None], refused: str
) -> None:
    """The ruling's race (#913 L4, CR-S3L4-03): a write on the serving loop, a rejection one of its
    own signed calls met or a tracking read that finds the account switched off, against the lane's
    gate reads, under a barrier, the write held half done until the lane has read meanwhile, and
    the threads switching at the finest grain. A read begun while it is held admits, the lane never
    waiting on this loop; from the moment it returns, every lane read that begins after it refuses,
    and so does one read of the app's gate, with no second read to make up for a miss; no read
    raises or answers anything else."""
    here, accounts = threading.current_thread(), [UUID(int=1_000 + race) for race in range(RACES)]
    world = _world(_serving(), accounts)
    async with running() as lane:
        for account in accounts:
            barrier, returned = threading.Barrier(2, timeout=BOUND_S), threading.Event()
            world.clock.arm(here, call)
            answered = lane.call(_around_a_write(world, account, barrier, returned))
            barrier.wait()  # this loop's thread, until the lane is there too
            write(world, account)  # held a while
            returned.set()
            reads = await answered
            assert _answers(reads, "during") == ({None}, {None})
            assert _answers(reads, "after") == ({refused}, {refused})
            assert {answer for read in reads for answer in read[1:]} <= {None, refused}


async def _rejected_on_the_lane(world: _World, account: UUID,
                                signed: threading.Event) -> list[Read]:  # fmt: skip
    """The lane's signed call meets a rejection, then its reads, each with when it began: its notice
    still in flight to the serving loop (`in_flight`), landing there, held half done (`landing`),
    or landed, the lane's own refusal dropped (`landed`)."""
    world.served.credential_rejected(account, Refusal.UNKNOWN_KEY)  # a lane-signed call met it
    reads = [_read(world, account, "in_flight")]  # this loop is blocked
    began: Counter[str] = Counter()
    signed.set()
    try:
        while began["landed"] < AFTER and len(reads) < READS:
            landed = not world.served.refused(account)
            when = "landed" if landed else "landing" if world.clock.held() else "in_flight"
            reads.append(_read(world, account, when))
            began[when] += 1
            if began["landing"] == DURING:
                world.clock.go.set()  # the notice's write goes on: the standing, then the drop
    finally:
        world.clock.go.set()
    return reads


@pytest.mark.serial
@pytest.mark.usefixtures("finest_switching")
async def test_a_rejection_the_lane_signed_refuses_every_lane_read_from_its_call_on() -> None:
    """#913 L4 with L1c's lane-local refusal (CR-S3L1B-04): a rejection a lane-signed call met is
    notified to the serving loop, never awaited; the lane reads the gate in place meanwhile, its
    first read while this loop is blocked, the notice's write held half done here while the lane
    reads. Every read from the rejection's call on refuses: the lane's own refusal until the notice
    lands, the app's gate under it still admitting (CR-S3L4-03), then the key standing's, which
    `_land` writes before it drops the lane's, so one read of the app's gate refuses by then."""
    here, accounts = threading.current_thread(), [UUID(int=2_000 + race) for race in range(RACES)]
    world = _world(_serving(), accounts)
    async with running() as lane:
        for account in accounts:
            signed = threading.Event()
            world.clock.arm(here, "now")  # the notice's write, when it lands on this loop
            answered = lane.call(_rejected_on_the_lane(world, account, signed))
            assert signed.wait(BOUND_S)  # this loop blocks until the lane has read once
            reads = await answered  # this loop turns: the notice lands meanwhile
            assert reads[0] == ("in_flight", "no_active_key", None)  # the lane's own refusal
            assert {"landing", "landed"} <= {read[0] for read in reads}
            assert {served for _, served, _ in reads} == {"no_active_key"}
            assert _answers(reads, "landing")[1] == {None}  # not yet published there
            assert _answers(reads, "landed")[1] == {"no_active_key"}


class _Turning:
    """The app's gate as writes landing meanwhile leave it, an answer a read."""

    def __init__(self, *answers: OrderEntryRefusal | None) -> None:
        self.answers = list(answers)

    def refusal(self, account_id: UUID) -> OrderEntryRefusal | None:
        return self.answers.pop(0)


@pytest.mark.parametrize(
    ("answers", "expected"),
    [
        pytest.param((None, MAINTENANCE_REFUSAL), MAINTENANCE_REFUSAL, id="the_second_refuses"),
        pytest.param((MAINTENANCE_REFUSAL,), MAINTENANCE_REFUSAL, id="the_first_refuses"),
        pytest.param((None, None), None, id="both_admit"),
    ],
)
async def test_the_lane_admits_only_when_two_gate_reads_in_a_row_admit(
    answers: tuple[OrderEntryRefusal | None, ...], expected: OrderEntryRefusal | None
) -> None:
    """#913 L4: a read in place takes each source of the gate at its own instant, so one that
    overlaps writes to two of them may combine two instants; a refusing write that lands inside the
    first read is in force for the second, which begins after it, so only two admitting reads in a
    row admit, and a first refusal is the answer, no second read made."""
    standing: Any = object()  # told of no rejection: never called
    gate = _Turning(*answers)
    assert ServedGate(gate, ServedStandings(standing, _serving())).refusal(ACC) is expected
    assert gate.answers == []


@pytest.mark.parametrize(
    ("bridge", "carried"),
    [
        pytest.param(ServedGate.refusal, OrderEntryGate.refusal, id="gate"),
        pytest.param(
            ServedStandings.credential_rejected, KeyStandings.credential_rejected, id="standings"
        ),
    ],
)
def test_the_gate_bridges_keep_the_signatures_of_what_they_carry(
    bridge: Callable[..., object], carried: Callable[..., object]
) -> None:
    """A bridge re-declares what it carries, the gate's `refusal` the app's one gate's and the
    standings' `credential_rejected` the key standing's, so a caller of either calls it alike."""
    assert inspect.signature(bridge) == inspect.signature(carried)
