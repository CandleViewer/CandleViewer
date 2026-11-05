"""E29-S06 #981 slice 3b: the closed-PnL sync (24 Sec.8.13) in the OMS runtime (20 Sec.6.2), on
the runtime's own rig (`test_oms_runtime`): built from the runtime's parts, started once `ready`
is set, stopped before what it reads through closes; its two seams, which only enqueue; a sync
that fails, which holds neither `ready` nor a fill; and its faults, a start the lane does not
confirm and an end of its task no stop asked for, a cancel included, each paged once and read by
`/readyz` alone. The venue is the fake port: no network, no sleeps."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.app import _oms_state
from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.models import PrivateStreamStatus
from candleviewer.oms.closed_pnl_sync import (
    CLOSED_PNL_LOOKBACK,
    DEBOUNCE_S,
    PORT_TIMEOUT_S,
    ClosedPnlSync,
)
from candleviewer.oms.day_figures import DayRiskFigures
from candleviewer.oms.fakes import InMemorySubmissionStore
from candleviewer.oms.ports import NoReconciliation
from candleviewer.oms.reconcile_job import ReconcileJobs
from candleviewer.oms.repository import ExecutionRepository
from candleviewer.oms.stop_gate import ResolvingStopGate
from candleviewer.oms_stream_wiring import ExchangeWallClock
from candleviewer.oms_wiring import ClosedPnlResyncs, OmsStores
from candleviewer.risk.day_boundary import DayBoundary, day_containing
from candleviewer.storage.repositories.executions import NewExecution
from candleviewer.storage.repositories.trading_accounts import TradingAccountRow
from tests.unit.audit.audit_waits import virtual
from tests.unit.exchange.bybit._trading import ACCOUNT_A
from tests.unit.oms import command_rig as cr
from tests.unit.oms.test_closed_pnl_sync import Store, _fill, rig
from tests.unit.oms.test_e29_t05_acceptance import FILLS, fill_row, parsed
from tests.unit.oms.test_handovers import _Store
from tests.unit.oms.test_oms_runtime import KEY, SENDING, T0, World, crashed, settle, started, until
from tests.unit.oms.test_order_repository import _DONE, _AnyStore
from tests.unit.test_oms_reconcile_wiring import Reads

T0_US = int(T0.timestamp()) * 1_000_000
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass
class Synced(World):
    """The runtime's world with the closed-PnL store composed (slice 3's fake), so a sync is."""

    records: Store = field(default_factory=Store)

    def stores(self) -> OmsStores:
        return replace(super().stores(), closed_pnl=cast(Any, self.records))


def keyed[W: World](world: W, *, read: bool = True) -> W:
    """The demo account, of the process's environment and holding a key; the flags read unless
    `read` is False."""
    InMemorySubmissionStore(world.store).seed_account(cr.ref())
    world.accounts.append(TradingAccountRow(cr.ACCOUNT, "demo", cr.UIDS["demo"], False, KEY))
    for flag in world.flags if read else ():
        flag.read()
    return world


def _reads(world: World) -> list[tuple[UUID, str]]:
    """Each closed-PnL read the venue was asked for, its account and lane: the sync's alone."""
    calls = [c for port in world.venue.ports for c in port.calls if c.method == "closed_pnl"]
    return [(c.account_id, c.lane) for c in calls]


def _sync_pages(world: World) -> list[str]:
    """The pages the runtime raised for the sync: its start's and its task's end."""
    return [call for call in world.pager.calls if call.startswith("oms_closed_pnl_sync_")]


async def test_the_sync_is_built_from_the_runtimes_parts_and_starts_once_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Built at the composition on the router, the account binding, the closed-PnL, execution and
    snapshot stores and the exchange-synced clock the position store reads; started once `ready`
    is set and the consumer has started, with the accounts that trade, in the `poll` lane."""
    world, starts = keyed(Synced(), read=False), list[tuple[bool, bool | None, list[AccountId]]]()
    runtime, start = world.runtime(), ClosedPnlSync.start

    def recorded(self: ClosedPnlSync, accounts: Iterable[AccountId]) -> bool:
        starts.append((runtime._ready.is_set(), runtime._streaming, list(accounts)))
        return start(self, starts[-1][2])

    monkeypatch.setattr(ClosedPnlSync, "start", recorded)
    async with started(runtime):
        parts = runtime._composed()
        sync = parts.closed_pnl
        assert isinstance(sync, ClosedPnlSync) and sync._task is None
        accounts, closes = cast(object, sync._accounts), cast(object, sync._closes)
        assert sync._router is parts.submission._router and accounts is parts.route.accounts
        assert sync._records is world.records and closes is world.store.executions
        assert sync._snapshots is parts.stream.positions._snapshots
        [clock] = world.position_clocks
        assert isinstance(clock, ExchangeWallClock) and sync._now is clock
        await settle()
        assert (starts, _reads(world)) == ([], [])  # the startup waits for the flags' first read
        for flag in world.flags:
            flag.read()
        await until(lambda: bool(_reads(world)))
    assert starts == [(True, True, [AccountId(cr.ACCOUNT)])]
    assert _reads(world) == [(cr.ACCOUNT, "poll")]


async def test_one_resolver_over_the_stores_column_gives_the_cap_and_the_sync_their_day() -> None:
    """24 Sec.8.13: one resolver, over the column `OmsStores.risk_policy` reads, is the order
    path's daily-loss figure's and the sync's: at +180 the sync reaches `CLOSED_PNL_LOOKBACK`
    before its day's start, 21:00Z of the previous UTC date, never UTC midnight's."""
    world = keyed(Synced())
    world.policy.offset = 180
    async with started(world.runtime()) as runtime:
        parts = runtime._composed()
        sync, figures = parts.closed_pnl, parts.submission._deps.figures
        assert sync is not None and isinstance(figures, DayRiskFigures)
        days = figures._days
        assert isinstance(days, DayBoundary) and days._policy is world.policy
        assert sync._day_start == days.day_start  # bound to the one resolver
        await until(lambda: bool(_reads(world)))
    calls = [c for port in world.venue.ports for c in port.calls if c.method == "closed_pnl"]
    start, end = (_EPOCH + timedelta(microseconds=us) for us in cast(Any, calls[0].request))
    day = day_containing(end, 180)  # its local midnight is 21:00Z of the previous UTC date
    assert day != day_containing(end, 0) and (day.day_start + timedelta(hours=3)).hour == 0
    assert start == day.day_start - CLOSED_PNL_LOOKBACK


async def test_the_cap_and_the_sync_hand_the_one_resolver_instants_from_one_clock() -> None:
    """Slice 4's lens fold (N1; 24 Sec.8.13 "one window and one lookback for the cap and the
    view"): the order path's daily-loss figure reads the clock the sync reads, the exchange-synced
    one the position store is built over, never the runtime's host clock beside it."""
    world = Synced()
    async with started(world.runtime()) as runtime:
        parts = runtime._composed()
        sync, figures = parts.closed_pnl, parts.submission._deps.figures
        assert sync is not None and isinstance(figures, DayRiskFigures)
        [clock] = world.position_clocks
        assert isinstance(clock, ExchangeWallClock)
        assert figures._now is clock and sync._now is clock


async def test_the_stop_ends_the_sync_before_anything_it_reads_through_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Its closer, ahead of the stop gate, the trading port and the pool, awaits its stop: the
    stop gate closes once its task has ended, and no task of it is left."""
    world = keyed(Synced())
    stop, close = ClosedPnlSync.stop, ResolvingStopGate.aclose

    async def stopped(self: ClosedPnlSync, timeout_s: float = PORT_TIMEOUT_S) -> None:
        await stop(self, timeout_s)
        world.log.append("closed_pnl_sync.stopped")

    async def closed(self: ResolvingStopGate) -> None:
        world.log.append("stop_gate.close")
        await close(self)

    monkeypatch.setattr(ClosedPnlSync, "stop", stopped)
    monkeypatch.setattr(ResolvingStopGate, "aclose", closed)
    async with started(world.runtime()) as runtime:
        parts = runtime._composed()
        sync = parts.closed_pnl
        assert sync is not None
        await until(lambda: bool(_reads(world)))
        task, names = sync._task, [name for name, _ in parts.closers]
    used = ("stop_gate", "trading_port", "pool")
    assert all(names.index("closed_pnl_sync") < names.index(name) for name in used)
    assert world.log.index("closed_pnl_sync.stopped") < world.log.index("stop_gate.close")
    assert task is not None and task.cancelled() and sync.fault is None
    assert "oms-closed-pnl-sync" not in {t.get_name() for t in asyncio.all_tasks()}
    assert _sync_pages(world) == []  # the stop it was asked for pages nothing


async def test_a_fill_the_composed_facade_commits_reaches_the_syncs_stored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The venue's fill of `SENDING`, which the sweep resumed and the venue acknowledged, crosses
    the consumer and B1's step into the execution repository, which reports it to the sync once
    committed: the execution the step wrote, its row in the store by then."""
    world = Synced()
    await crashed(world)
    world.tracked.accounts = frozenset({cr.ACCOUNT})
    told, stored = list[tuple[str, bool]](), ClosedPnlSync.stored

    def recorded(self: ClosedPnlSync, execution: NewExecution) -> None:
        held = (execution.exchange_account_id, execution.exec_id) in world.store._fills
        told.append((execution.exec_id, held))
        stored(self, execution)

    monkeypatch.setattr(ClosedPnlSync, "stored", recorded)
    for flag in world.flags:
        flag.read()
    async with started(world.runtime()) as runtime:
        await until(lambda: runtime.state == "ok")
        await until(lambda: world.store._orders[SENDING.id].lifecycle_state == "submitted")
        venue_id = world.store._orders[SENDING.id].exchange_order_id
        [port] = world.venue.ports
        row = fill_row(SENDING, "e1", "0.010", seq=1, orderId=venue_id)
        for event in parsed(FILLS, [row], cr.ref(), T0_US):
            port.push(event)
        await until(lambda: bool(told))
    assert told == [("e1", True)]


async def test_a_resyncing_status_asks_the_sync_for_a_read_then_reconciliation_for_its_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With reconciliation composed, the consumer's request goes through `ClosedPnlResyncs`: the
    sync's `reconnected` first, then the jobs' request as the consumer made it, the port still
    announced as real. Its jobs start no pass here (their own tests run them)."""
    world = keyed(Synced(handover_store=_Store(), reconcile_reads=Reads()))
    world.tracked.accounts = frozenset({cr.ACCOUNT})
    asked, reconnected = list[tuple[str, UUID]](), ClosedPnlSync.reconnected

    def recorded(self: ClosedPnlSync, account_id: AccountId) -> None:
        asked.append(("sync", account_id))
        reconnected(self, account_id)

    async def requested(self: ReconcileJobs, account_id: AccountId, *, reason: str) -> None:
        asked.append((reason, account_id))

    async def opened(self: ReconcileJobs, accounts: Iterable[AccountId]) -> None:
        return None

    monkeypatch.setattr(ClosedPnlSync, "reconnected", recorded)
    monkeypatch.setattr(ReconcileJobs, "request_reconciliation", requested)
    monkeypatch.setattr(ReconcileJobs, "start", opened)
    async with started(world.runtime()) as runtime:
        await until(lambda: runtime.state == "ok")
        assert isinstance(runtime._composed().stream.reconciliation, ClosedPnlResyncs)
        assert world.gauge("reconciliation") == 0.0
        [port] = world.venue.ports
        port.push(PrivateStreamStatus(
            account_id=cr.ACCOUNT, state="resyncing", reason="reconnected", epoch=1, ts=T0_US
        ))  # fmt: skip
        await until(lambda: len(asked) == 2)
    assert asked == [("sync", cr.ACCOUNT), ("reconnected", cr.ACCOUNT)]


@pytest.mark.parametrize("synced", [True, False], ids=["its_store", "no_store"])
async def test_without_reconciliation_the_stand_in_stays_bare_and_without_its_store_no_sync(
    synced: bool,
) -> None:
    """With no reconciliation composed, the consumer's stand-in is left unwrapped, so still
    announced as one (`oms_interim_ports`), and the sync runs without the reconnect trigger;
    with no closed-PnL store no sync is composed, and nothing reads the venue's records."""
    world = keyed(Synced() if synced else World())
    async with started(world.runtime()) as runtime:
        await until(lambda: runtime.state == "ok")
        parts = runtime._composed()
        assert isinstance(parts.stream.reconciliation, NoReconciliation)
        assert world.gauge("reconciliation") == 1.0
        names = [name for name, _ in parts.closers]
        assert (parts.closed_pnl is not None, "closed_pnl_sync" in names) == (synced, synced)
        await until(lambda: bool(_reads(world)) or not synced)
    assert bool(_reads(world)) is synced


async def test_a_sync_start_the_lane_does_not_confirm_is_paged_once_and_degrades_readyz_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Paged as unconfirmed, not as unstarted: a start whose answer the bound cut off may have
    run. It is the sync's fault (the orchestrator's review of 2026-11-05), though no task of it
    ended: `/readyz`'s `oms` check reads `degraded`, paged once however often it is read, while
    `ready` stands and what `placeOrder` and the exits read stays `ok`."""

    def refused(self: ClosedPnlSync, accounts: Iterable[AccountId]) -> bool:
        raise RuntimeError("the sync's start")

    monkeypatch.setattr(ClosedPnlSync, "start", refused)
    world = keyed(Synced())
    with capture_logs() as logs:
        async with started(world.runtime()) as runtime:
            await until(lambda: bool(_sync_pages(world)))
            sync = runtime._composed().closed_pnl
            assert sync is not None and sync.fault is None
            for _ in range(2):
                assert (runtime.state, runtime.readiness, _oms_state(runtime)) == (
                    "ok", "ok", "degraded"
                )  # fmt: skip
    assert _sync_pages(world) == ["oms_closed_pnl_sync_start_unconfirmed"]
    unconfirmed = [(e["error"], e["log_level"]) for e in logs
                   if e["event"] == "oms_closed_pnl_sync_start_unconfirmed"]  # fmt: skip
    assert unconfirmed == [("RuntimeError", "critical")]


async def test_an_account_a_start_skips_is_logged_under_its_callers_own_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The accounts read at start serve reconciliation's jobs and the sync: a keyless account is
    logged once under each one's own event, never twice under reconciliation's."""

    async def opened(self: ReconcileJobs, accounts: Iterable[AccountId]) -> None:
        return None

    monkeypatch.setattr(ReconcileJobs, "start", opened)
    world = keyed(Synced(handover_store=_Store(), reconcile_reads=Reads()))
    keyless = AccountId(UUID(int=0xC1))
    InMemorySubmissionStore(world.store).seed_account(cr.ref(keyless, "demo"))
    world.accounts.append(TradingAccountRow(keyless, "demo", "100002", False, None))
    with capture_logs() as logs:
        async with started(world.runtime()):
            await until(lambda: bool(_reads(world)))  # the sync has started
    skipped = sorted((e["event"], e["account_id"], e["reason"]) for e in logs
                     if e["event"].endswith("_account_skipped"))  # fmt: skip
    assert skipped == [
        ("oms_closed_pnl_account_skipped", str(keyless), "OrderEntryRefused"),
        ("oms_reconcile_account_skipped", str(keyless), "OrderEntryRefused"),
    ]


@pytest.mark.parametrize("end", ["raises", "returns", "cancelled"])
async def test_a_sync_whose_task_ended_unasked_is_paged_once_and_degrades_readyz_alone(
    end: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Its task never restarts itself, so once it has ended unasked (`fault`), by an error, a
    return or a cancel no stop made, it is paged once and `/readyz`'s `oms` check reads `degraded`
    however often it is read (24 Sec.8.12 "Readiness", the orchestrator's ruling of 2026-11-04
    and its review of 2026-11-05); what `placeOrder` and the exits read stays `ok`, and the stop
    pages no more."""

    async def ended(self: ClosedPnlSync) -> None:
        if end == "raises":
            raise RuntimeError("the sync's task")
        if end == "cancelled":
            await asyncio.Event().wait()

    monkeypatch.setattr(ClosedPnlSync, "_run", ended)
    world = keyed(Synced())
    async with started(world.runtime()) as runtime:
        sync = runtime._composed().closed_pnl
        assert sync is not None
        await until(lambda: sync._task is not None)
        if end == "cancelled":
            await settle()
            assert (_sync_pages(world), _oms_state(runtime)) == ([], "ok")
            task = sync._task
            assert task is not None
            task.cancel()  # not through its stop: as the order lane's death cancels it
        await until(lambda: "oms_closed_pnl_sync_ended" in world.pager.calls)
        assert sync.fault is not None
        for _ in range(2):
            assert (runtime.state, runtime.readiness, _oms_state(runtime)) == (
                "ok", "ok", "degraded"
            )  # fmt: skip
    assert _sync_pages(world) == ["oms_closed_pnl_sync_ended"]


@virtual
async def test_a_stored_fill_only_enqueues_its_read_and_adds_no_wait_to_the_fill() -> None:
    """The seam on the fill path (C-2.20): with the sync's `stored` bound, a commit whose store
    answers at once ends in one step, so the report suspends nothing and reads nothing; the
    request waits in the sync's bounded queue, and its own task reads it a debounce later."""
    r = rig()
    assert r.sync.start([])
    fills = ExecutionRepository(cast(Any, _AnyStore(_DONE)))
    fills.bind_stored(r.sync.stored)
    call = fills.commit_fill(cast(Any, SimpleNamespace(execution=_fill(Decimal("0.5")))))
    with pytest.raises(StopIteration) as answered:
        call.send(None)  # one step: the fill's own write is the only wait on its path
    assert answered.value.value is _DONE and r.venue.reads == []
    assert r.sync._state[ACCOUNT_A].due == DEBOUNCE_S  # queued, the account's one entry
    await asyncio.sleep(2 * DEBOUNCE_S)
    assert r.times() == [DEBOUNCE_S]
    await r.sync.stop()


async def test_a_resync_the_sync_cannot_take_still_reaches_reconciliation() -> None:
    """What `reconnected` raises is logged by its class, never raised: the jobs still take it."""
    asked = list[str]()

    def refused(account_id: AccountId) -> None:
        raise RuntimeError("the sync")

    async def requested(account_id: AccountId, *, reason: str) -> None:
        asked.append(reason)

    jobs = SimpleNamespace(request_reconciliation=requested)
    resyncs = ClosedPnlResyncs(cast(Any, jobs), cast(Any, SimpleNamespace(reconnected=refused)))
    with capture_logs() as logs:
        await resyncs.request_reconciliation(AccountId(cr.ACCOUNT), reason="connected")
    failed = [(e["event"], e["error"]) for e in logs]
    assert (asked, failed) == (["connected"], [("oms_closed_pnl_resync_failed", "RuntimeError")])
