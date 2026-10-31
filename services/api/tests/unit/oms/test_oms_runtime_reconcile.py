"""The OMS runtime's reconciliation start and the routes' service (E29-T06 #914;
24-internal-schemas.md Sec.8.5 "The stale rule", 20-architecture.md Sec.6.2), on the world of
`test_oms_runtime`.

A start of the jobs that fails before any opens, or that its bound cuts short, holds every
account's order entry (the standing, `account_stale`) while the runtime goes on to `ready`, and the
startup task retries it on the sweep's backoff until it works, which lifts the hold (#914's
security look, Low 2; INV-B19-a); one that fails once the stop has begun holds and pages nothing.
An account whose read fails at the start is held until its job opens, and a refused one skipped
(the code look's m1 and M2). The routes reach the jobs only through `OmsRuntime.reconciliation`:
each call on the order lane, its write-ahead record back on the serving loop, which a real
`OrderLane` shows across threads."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer import oms_wiring
from candleviewer.domain.order_entry import OrderEntryRefusal
from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.models import AccountRef
from candleviewer.observability.metrics import Metrics
from candleviewer.oms.errors import OmsNotReady, ReconciliationUnavailable
from candleviewer.oms.fakes import InMemorySubmissionStore
from candleviewer.oms.reconcile_job import NothingToResolve, PassTaken, ReconcileJobs
from candleviewer.oms.reconcile_standing import UNSTARTED_DETAIL, ReconcileStanding
from candleviewer.oms_lane import HOP_TIMEOUT_S, OrderLane, Serving
from candleviewer.oms_wiring import OmsRuntime, OnLaneReconciliation
from candleviewer.statechart.bindings import b19_reconciliation as b19
from candleviewer.storage.errors import StorageQueryFailed
from candleviewer.storage.repositories.trading_accounts import (
    InMemoryTradingAccountReads,
    TradingAccountRow,
)
from tests.unit.oms.test_handovers import _Store
from tests.unit.oms.test_oms_runtime import KEY, Recording, World, started, until
from tests.unit.test_oms_reconcile_wiring import Reads

ACCOUNT = AccountId(UUID(int=0x914))
HELD = OrderEntryRefusal("account_stale", UNSTARTED_DETAIL)


def _world(**over: Any) -> World:
    world = World(handover_store=_Store(), reconcile_reads=Reads(), **over)
    for flag in world.flags:
        flag.read()
    return world


async def _ready(runtime: OmsRuntime) -> None:
    await asyncio.wait_for(runtime.wait_ready(), 10)  # a bound on the test


def _accounts(world: World, monkeypatch: pytest.MonkeyPatch, fail: Any) -> list[int]:
    """`environment_accounts` with the calls `fail(n)` names raising (n from 1: the sweep reads
    first, then each start of the jobs); `fail` may await first. The calls made, in order."""
    real, calls = world.store.environment_accounts, list[int]()

    async def reads(environment: Any) -> Any:
        calls.append(len(calls) + 1)
        if await fail(len(calls)):
            raise ConnectionError("the environment's accounts are unreadable")
        return await real(environment)

    monkeypatch.setattr(world.store, "environment_accounts", reads)
    return calls


async def test_a_failed_start_holds_every_account_until_a_retry_starts_the_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#914's security look, Low 2, and the code look's M2: the start fails before any job
    opens, so every account is held, it is logged CRITICAL and paged once, and the runtime is
    `ready` all the same (BQ-14); a retry that fails is logged, and the one that works lifts it."""
    world, standing, gate = _world(), ReconcileStanding(), asyncio.Event()
    runtime = world.runtime(standing=standing)

    async def fail(n: int) -> bool:
        if n == 3:
            await gate.wait()  # the first retry, held until the test has looked
        return n in (2, 3)

    calls = _accounts(world, monkeypatch, fail)
    with capture_logs() as logs:
        async with started(runtime):
            await _ready(runtime)  # order entry never waits for the jobs (BQ-14)
            await until(lambda: len(calls) == 3)
            assert standing.held and standing.refusal(ACCOUNT) == HELD  # fail closed
            assert world.pager.calls.count("oms_reconcile_unstarted") == 1
            assert not b19.ports_wired()  # no job opened
            gate.set()
            await until(lambda: not standing.held)
            assert calls == [1, 2, 3, 4] and b19.ports_wired()
            assert standing.refusal(ACCOUNT) is None
            assert world.clock.slept[-2:] == [1.0, 2.0]  # the sweep's backoff, doubling
    unstarted = [e for e in logs if e["event"] == "oms_reconcile_unstarted"]
    assert [(e["log_level"], e["error"]) for e in unstarted] == [("critical", "ConnectionError")]
    events = [e["event"] for e in logs]
    assert events.count("oms_reconcile_start_retry_failed") == 1
    assert events.count("oms_reconcile_started_on_retry") == 1
    assert world.pager.calls.count("oms_reconcile_unstarted") == 1  # the retries page no more


async def test_a_start_that_fails_as_the_runtime_stops_holds_nothing_and_pages_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The code look's M2, the stopping branch: a start that fails once the stop has begun is
    the stop's own end, so it holds no account, pages nothing and sets no `ready`."""
    world, standing = _world(), ReconcileStanding()
    runtime = world.runtime(standing=standing)

    async def fail(n: int) -> bool:
        if n == 2:  # the start's read fails once a stop has begun, before it cancels the task
            await until(lambda: not runtime.started)
        return n == 2

    calls = _accounts(world, monkeypatch, fail)
    with capture_logs() as logs:
        await runtime.start()
        try:
            await until(lambda: len(calls) == 2)
        finally:
            await runtime.stop()
    assert not standing.held and world.pager.calls.count("oms_reconcile_unstarted") == 0
    assert "oms_reconcile_unstarted" not in [e["event"] for e in logs]
    assert "oms_ready" not in [e["event"] for e in logs]


async def test_a_stop_ends_the_retry_and_only_a_start_that_works_lifts_the_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world, standing = _world(), ReconcileStanding()
    runtime = world.runtime(standing=standing)

    async def fail(n: int) -> bool:
        return n >= 2

    _accounts(world, monkeypatch, fail)
    async with started(runtime):
        await _ready(runtime)
        await until(lambda: len(world.clock.slept) >= 3)  # still retrying, on its backoff
        assert standing.held
    assert standing.held and runtime._startup is None  # the stop ended it; still fail closed
    monkeypatch.undo()
    async with started(runtime):
        await _ready(runtime)
        assert not standing.held and b19.ports_wired()


async def test_an_unread_account_is_held_and_a_refused_one_skipped_until_its_job_opens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The code look's m1 (`tradable`): an account the binding refuses (deleted or keyless) is
    skipped, as its stream opens it; one whose read fails (`StoreUnavailable`) is no refusal, so
    it is held, logged at WARNING, until a trigger opens its job, which rebuilds its standing."""
    world, standing = _world(), ReconcileStanding()
    ok, gone, unread = (AccountId(UUID(int=n)) for n in (0xA1, 0xA2, 0xA3))
    for account, deleted in ((ok, False), (gone, True), (unread, False)):
        ref = AccountRef(account_id=account, uid="1", environment="demo", key_ref="k")
        InMemorySubmissionStore(world.store).seed_account(ref)
        world.accounts.append(TradingAccountRow(account, "demo", "1", deleted, KEY))
    real = InMemoryTradingAccountReads.read_account

    async def read(self: InMemoryTradingAccountReads, account_id: UUID) -> Any:
        if account_id == unread:
            raise StorageQueryFailed(None)  # the store down: the binding answers StoreUnavailable
        return await real(self, account_id)

    monkeypatch.setattr(InMemoryTradingAccountReads, "read_account", read)
    runtime = world.runtime(standing=standing)
    with capture_logs() as logs:
        async with started(runtime):
            await _ready(runtime)
            jobs = runtime._composed().reconcile
            assert jobs is not None
            assert set(jobs.jobs._jobs) == {ok}  # only the account that resolved
            assert standing.is_stale(unread) and not standing.is_stale(gone)
            await jobs.jobs.trigger(unread, "reconnect")  # its stream's first trigger
            assert not standing.is_stale(unread)  # opened, so rebuilt from its state
    skipped = [e["account_id"] for e in logs if e["event"] == "oms_reconcile_account_skipped"]
    held = [e for e in logs if e["event"] == "oms_reconcile_account_unread"]
    assert skipped == [str(gone)]
    assert [(e["account_id"], e["log_level"]) for e in held] == [(str(unread), "warning")]


async def test_a_start_its_bound_cuts_holds_the_accounts_it_missed_until_a_retry_opens_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#914's security look, Low 2, under the start's bound (`_bounded`): a start cut short once
    its first account's job opened is a failed start, so the whole environment is held and the
    account it never reached, with neither a job nor a standing mark, is refused all the same. It
    is logged CRITICAL as a `TimeoutError` and paged once; the retry opens the jobs and lifts it."""
    monkeypatch.setattr(oms_wiring, "SWEEP_STATEMENT_TIMEOUT_MS", 0)
    monkeypatch.setattr(oms_wiring, "SWEEP_CALL_SLACK_S", 0.3)  # real time, kept short
    world, standing = _world(), ReconcileStanding()
    first, cut, missed = (AccountId(UUID(int=n)) for n in (0xB1, 0xB2, 0xB3))
    for account in (first, cut, missed):
        ref = AccountRef(account_id=account, uid="1", environment="demo", key_ref="k")
        InMemorySubmissionStore(world.store).seed_account(ref)
        world.accounts.append(TradingAccountRow(account, "demo", "1", False, KEY))
    real, hangs = ReconcileJobs.trigger, [cut]

    async def trigger(self: ReconcileJobs, account: AccountId, trigger: Any) -> str | None:
        if account in hangs and trigger == "startup":
            hangs.clear()  # the first start's only: the retry's goes through
            await asyncio.Event().wait()  # until the bound cancels the start's task
        return await real(self, account, trigger)

    monkeypatch.setattr(ReconcileJobs, "trigger", trigger)
    runtime, seen = world.runtime(standing=standing), list[tuple[Any, ...]]()

    async def look(n: int) -> bool:
        if n == 3:  # the retry's read: what the cut start left
            wiring = runtime._composed().reconcile
            assert wiring is not None
            held, refusal = standing.held, standing.refusal(missed)
            seen.append((held, refusal, standing.is_stale(missed), set(wiring.jobs._jobs)))
        return False

    _accounts(world, monkeypatch, look)
    with capture_logs() as logs:
        async with started(runtime):
            await _ready(runtime)
            await until(lambda: not standing.held)
            wiring = runtime._composed().reconcile
            assert wiring is not None and set(wiring.jobs._jobs) == {first, cut, missed}
            assert standing.refusal(missed) is None  # opened, so rebuilt from its state
    assert seen == [(True, HELD, False, {first})]  # held by the environment's hold alone
    unstarted = [e for e in logs if e["event"] == "oms_reconcile_unstarted"]
    assert [(e["log_level"], e["error"]) for e in unstarted] == [("critical", "TimeoutError")]
    assert world.pager.calls.count("oms_reconcile_unstarted") == 1


async def test_a_composition_with_no_reconciliation_lifts_a_hold_an_earlier_start_left() -> None:
    world, standing = World(), ReconcileStanding()
    for flag in world.flags:
        flag.read()
    standing.hold()
    async with started(world.runtime(standing=standing)) as runtime:
        await _ready(runtime)
        assert not standing.held and not runtime.reconciliation.wired


async def test_the_routes_reach_the_jobs_on_the_lane_and_their_record_on_the_serving_loop() -> None:
    lanes: list[Recording] = []

    def lane() -> Recording:
        lanes.append(Recording())
        return lanes[-1]

    world = _world()
    runtime = world.runtime(lane=lane)
    with pytest.raises(OmsNotReady):
        _ = runtime.reconciliation  # the property refuses before the composition
    async with started(runtime):
        await _ready(runtime)
        service = runtime.reconciliation
        assert service.wired
        written: list[PassTaken] = []

        async def write_ahead(taken: PassTaken) -> None:
            written.append(taken)

        taken = await service.reconcile_now(ACCOUNT, write_ahead=write_ahead)
        assert written == [taken] and taken.joined is False
        assert ("ReconcileJobs.reconcile_now", HOP_TIMEOUT_S) in lanes[-1].hops
        with pytest.raises(NothingToResolve):  # the driver's refusal reaches the route as is
            await service.resolve(ACCOUNT, decided_by="owner", write_ahead=write_ahead)
        assert ("ReconcileJobs.resolve", HOP_TIMEOUT_S) in lanes[-1].hops


class _Jobs:
    """The driver's two calls, noting the thread each runs on and what it was told."""

    def __init__(self) -> None:
        self.threads: list[tuple[str, int]] = []
        self.told: list[str] = []

    async def reconcile_now(self, account: AccountId, *, write_ahead: Any) -> PassTaken:
        self.threads.append(("driver", threading.get_ident()))
        taken = PassTaken("00000000-0000-4000-8000-000000000914", joined=False)
        await write_ahead(taken)
        self.told.append("SWEEP_DUE")
        return taken

    async def resolve(self, account: AccountId, *, decided_by: str, write_ahead: Any) -> str:
        self.threads.append(("driver", threading.get_ident()))
        await write_ahead("stale_lockout")
        self.told.append("OPERATOR_RESOLVED")
        return "stale_lockout"


async def test_on_a_real_lane_the_record_is_written_on_the_serving_loops_thread() -> None:
    """CV-C13: the jobs run on the order lane's own thread, the route's record on the serving
    loop's, where its audit writer is bound; a record that raises there reaches the route as
    itself and the driver tells B19 nothing."""
    jobs, lane = _Jobs(), OrderLane(name="test-reconcile-lane")
    await lane.start()
    try:
        serving = Serving(asyncio.get_running_loop(), Metrics("demo"))
        parts = SimpleNamespace(reconcile=SimpleNamespace(jobs=jobs), serving=serving, lane=lane)
        service = OnLaneReconciliation(cast(Any, parts))
        here, written = threading.get_ident(), list[tuple[object, int]]()

        async def write_ahead(value: object) -> None:
            written.append((value, threading.get_ident()))

        taken = await service.reconcile_now(ACCOUNT, write_ahead=write_ahead)
        assert await service.resolve(ACCOUNT, decided_by="owner", write_ahead=write_ahead) == (
            "stale_lockout"
        )
        assert [thread for _, thread in written] == [here, here]
        assert [value for value, _ in written] == [taken, "stale_lockout"]
        assert {thread for _, thread in jobs.threads} != {here}  # the lane's own thread

        class Unwritten(Exception):
            pass

        async def refused(_value: object) -> None:
            raise Unwritten

        with pytest.raises(Unwritten):
            await service.resolve(ACCOUNT, decided_by="owner", write_ahead=refused)
        assert jobs.told == ["SWEEP_DUE", "OPERATOR_RESOLVED"]  # nothing more was told
    finally:
        await lane.stop()


async def test_with_no_serving_loop_or_no_jobs_nothing_reaches_the_lane() -> None:
    lane = Recording()
    for parts in (
        SimpleNamespace(reconcile=None, serving=object(), lane=lane),
        SimpleNamespace(reconcile=SimpleNamespace(jobs=_Jobs()), serving=None, lane=lane),
    ):
        service = OnLaneReconciliation(cast(Any, parts))
        assert not service.wired

        async def write_ahead(_value: object) -> None:
            raise AssertionError("nothing is written")

        with pytest.raises(ReconciliationUnavailable):
            await service.reconcile_now(ACCOUNT, write_ahead=write_ahead)
    assert lane.hops == []
