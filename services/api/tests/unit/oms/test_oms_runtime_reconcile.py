"""The OMS runtime's reconciliation start and the routes' service (E29-T06 #914;
24-internal-schemas.md Sec.8.5 "The stale rule", 20-architecture.md Sec.6.2), on the world of
`test_oms_runtime`.

A start of the jobs that fails before any opens holds every account's order entry (the standing,
`account_stale`) while the runtime goes on to `ready`, and the startup task retries it on the
sweep's backoff until it works, which lifts the hold (#914's security look, Low 2; INV-B19-a); one
that fails once the stop has begun holds and pages nothing (the code look's M2)."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.domain.order_entry import OrderEntryRefusal
from candleviewer.domain.primitives import AccountId
from candleviewer.oms.reconcile_standing import UNSTARTED_DETAIL, ReconcileStanding
from candleviewer.oms_wiring import OmsRuntime
from candleviewer.statechart.bindings import b19_reconciliation as b19
from tests.unit.oms.test_handovers import _Store
from tests.unit.oms.test_oms_runtime import World, started, until
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


async def test_a_composition_with_no_reconciliation_lifts_a_hold_an_earlier_start_left() -> None:
    world, standing = World(), ReconcileStanding()
    for flag in world.flags:
        flag.read()
    standing.hold()
    async with started(world.runtime(standing=standing)) as runtime:
        await _ready(runtime)
        assert not standing.held
