"""The reconciliation job driver (E29-T06 #914 PR 2b; 24-internal-schemas.md Sec.8.5 "Runs" and its
trigger table; BQ-1, BQ-7, BQ-13, BQ-14; 28 B19): one B19 per account on the real binding and the
pass's recording doubles (`reconcile_rig`), built through `cv.statechart.factory` and restored
through `statechart.persistence`, every send through the gateway. Host timers are held until a
test releases them; no sleeps, no network."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from itertools import pairwise
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.models import RateHeadroom
from candleviewer.observability.metrics import Metrics
from candleviewer.oms import reconcile_job as rj
from candleviewer.oms.errors import ReconciliationUnavailable
from candleviewer.oms.reconcile_job import (
    JobLocked,
    NoSuchJob,
    NothingToResolve,
    PassTaken,
    ReconcileJobs,
    RetryHop,
    leaf_of,
)
from candleviewer.oms.reconcile_standing import STALE_AFTER_S
from candleviewer.statechart.bindings import b19_reconciliation as b19
from candleviewer.statechart.factory import default_clock
from candleviewer.statechart.factory import restore as restore_chart
from candleviewer.statechart.persistence import (
    ChainTripLatch,
    InMemoryDrainJournal,
    MachineKey,
    Persister,
    Restorer,
    SealedSnapshot,
    hmac_sealer,
)
from candleviewer.statechart.plugins import InMemoryMachineEventSink
from candleviewer.statechart.registry import default_registry
from tests.unit.oms.reconcile_rig import ACCOUNT, Job, remote, rest, row
from tests.xstate_contract._harness import Audit, Keys, Pager, Repo

WINDOW_US = round(STALE_AFTER_S * 1_000_000)
REG = default_registry()


class Timers:
    """The driver's host timers (`sleep`), each held until a test releases it."""

    def __init__(self) -> None:
        self.asked: list[float] = []
        self._held: list[asyncio.Event] = []

    async def sleep(self, seconds: float) -> None:
        self.asked.append(seconds)
        gate = asyncio.Event()
        self._held.append(gate)
        await gate.wait()

    async def release(self) -> None:
        """Every timer held now fires (a timer just spawned reaches its sleep first)."""
        for _ in range(20):
            await asyncio.sleep(0)
        held, self._held = self._held, []
        for gate in held:
            gate.set()
        for _ in range(50):
            await asyncio.sleep(0)


class Memory:
    """`JobPersistence` over the real `Persister` and `Restorer`, with in-memory stores: what
    `stop` seals, the next driver restores. `persisted` records each persist's key, and whether
    B19's port was still wired then (it must be: unwired, a pass would lock)."""

    def __init__(self) -> None:
        self.repo, self.keys = Repo(), Keys()
        self.persisted: list[tuple[MachineKey, bool]] = []
        self.refuse_load = False

    async def load(self, key: MachineKey) -> SealedSnapshot | None:
        if self.refuse_load:
            raise ConnectionError("the snapshot store is down")
        sealed: SealedSnapshot | None = self.repo.rows.get(key)
        return sealed

    async def restore(self, key: MachineKey, sealed: SealedSnapshot) -> Any:
        restorer = Restorer(
            registry=REG, keys=self.keys, journal=InMemoryDrainJournal(), audit=Audit(),
            pager=Pager(), latch=ChainTripLatch(), plugins=lambda _key: [],
            clock=default_clock(), lane="order",
        )  # fmt: skip
        return (await restore_chart(restorer, key, sealed)).interpreter

    async def plugins(self, key: MachineKey) -> tuple[Any, ...]:
        return ()

    async def persist(self, interp: Any, key: MachineKey) -> None:
        self.persisted.append((key, b19.ports_wired()))
        await Persister(
            repo=self.repo, journal=InMemoryDrainJournal(), audit=Audit(),
            seal=hmac_sealer(self.keys, REG.get("reconciliation")), machine_hash_of=REG.hash,
            pager=Pager(),
        ).persist(interp, key=key)  # fmt: skip


def _driver(
    job: Job,
    timers: Timers,
    *,
    environment: str = "demo",
    persistence: Memory | None = None,
    remediates: Callable[[str], bool] = lambda _env: True,
) -> ReconcileJobs:
    hop = job.phases._retries
    assert isinstance(hop, RetryHop)
    # `environment` is the tests' plain `str`, not the `Environment` literal the driver takes
    driver = ReconcileJobs(
        job.phases, standing=job.standing, environment=environment,  # type: ignore[arg-type]
        remediates=remediates, metrics=job.metrics, pager=job.world.oms,
        sink=InMemoryMachineEventSink(), persistence=persistence, sleep=timers.sleep,
    )  # fmt: skip
    hop.bind(driver)
    return driver


@pytest.fixture
async def timers() -> Timers:
    return Timers()


@pytest.fixture
async def job() -> AsyncIterator[Job]:
    wired = Job(retries=RetryHop())  # type: ignore[arg-type]  # the driver's hop, not the rig's
    yield wired
    b19.set_ports(None)


async def _resting(driver: ReconcileJobs, account: AccountId = ACCOUNT) -> str:
    return str(await rest(driver._jobs[account].interp))


async def _asked(timers: Timers, done: Callable[[list[float]], bool]) -> None:
    """Yields (never sleeps) until the timers asked for satisfy `done`, else fails."""
    for _ in range(400):
        if done(timers.asked):
            return
        await asyncio.sleep(0)
    raise AssertionError(f"timers asked {timers.asked}")


async def _until(driver: ReconcileJobs, state: str, account: AccountId = ACCOUNT) -> str:
    """Yields (never sleeps) until the account's job rests in `state`, or its budget ends."""
    for _ in range(4000):
        interp = driver._jobs[account].interp
        if leaf_of(interp) == state and await rest(interp, budget=1) == state:
            break
        await asyncio.sleep(0)
    return leaf_of(driver._jobs[account].interp)


def _starve(job: Job, starved: bool = True) -> None:
    tokens, wait = (0.0, 60.0) if starved else (100.0, 0.0)
    job.world.venue.set_headroom(ACCOUNT, RateHeadroom(lane="poll", tokens=tokens, wait_s=wait))


def _sent(driver: ReconcileJobs, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every event the driver sends through its gateway, in order (BQ-1)."""
    sent: list[str] = []
    send = driver._gateway.send

    async def spy(key: str, event: Any, *, wait: bool = False) -> Any:
        sent.append(str(event["type"]))
        return await send(key, event, wait=wait)

    monkeypatch.setattr(driver._gateway, "send", spy)
    return sent


async def _locked(job: Job, driver: ReconcileJobs, timers: Timers) -> None:
    """The account's job locked stale: its fetch starved for the window (BQ-4)."""
    _starve(job)
    await driver.trigger(ACCOUNT, "periodic")
    assert await _resting(driver) == "backing_off"
    job.world.now_us += WINDOW_US
    await timers.release()  # the host timer's RETRY_DUE
    assert await _until(driver, "stale_lockout") == "stale_lockout"


# --- Start, and the startup trigger (BQ-14) ------------------------------------------------------


async def test_start_wires_b19_and_sends_each_account_startup_through_the_gateway(
    job: Job, timers: Timers, monkeypatch: pytest.MonkeyPatch
) -> None:
    driver = _driver(job, timers)
    sent = _sent(driver, monkeypatch)
    await driver.start([ACCOUNT])
    try:
        assert b19.ports_wired()
        assert await _resting(driver) == "idle"
        assert sent == ["STARTUP"]
        [(_, _pass_id, state)] = job.records.rows
        assert (state["trigger"], state["result"]) == ("startup", "clean")
        assert driver.state(ACCOUNT) == "idle" and driver.state(AccountId(UUID(int=7))) is None
    finally:
        await driver.stop()
    assert not b19.ports_wired()


async def test_a_trigger_for_an_account_with_no_job_opens_one(job: Job, timers: Timers) -> None:
    driver = _driver(job, timers)
    await driver.start([])
    try:
        assert await driver.request_reconciliation(ACCOUNT, reason="reconnected") is None
        assert await _resting(driver) == "idle"
        assert [r[2]["trigger"] for r in job.records.rows] == ["reconnect"]
        with pytest.raises(ValueError):  # "bogus" is no `ResyncReason`, on purpose
            await driver.request_reconciliation(ACCOUNT, reason="bogus")  # type: ignore[arg-type]
    finally:
        await driver.stop()


# --- The trigger rule (24 Sec.8.5) ----------------------------------------------------------------


async def _held_fetch(job: Job, monkeypatch: pytest.MonkeyPatch) -> asyncio.Event:
    """The next fetch waits for the returned gate: a pass held running in `fetching`."""
    gate, fetch = asyncio.Event(), job.phases.fetch

    async def held(*args: Any, **kwargs: Any) -> Any:
        await gate.wait()
        return await fetch(*args, **kwargs)

    monkeypatch.setattr(job.phases, "fetch", held)
    return gate


async def test_a_trigger_while_a_pass_runs_is_skipped_never_queued(
    job: Job, timers: Timers, monkeypatch: pytest.MonkeyPatch
) -> None:
    driver = _driver(job, timers)
    await driver.start([])
    gate = await _held_fetch(job, monkeypatch)
    try:
        first = await driver.trigger(ACCOUNT, "periodic")
        with capture_logs() as logs:
            for trigger in ("periodic", "unknown", "startup", "reconnect"):
                assert await driver.trigger(ACCOUNT, trigger) is None
        skipped = [e for e in logs if e["event"] == "reconcile_trigger_skipped"]
        assert [(e["trigger"], e["reason"]) for e in skipped] == [
            ("periodic", "running"), ("unknown", "running"), ("startup", "running"),
            ("reconnect", "running"),
        ]  # fmt: skip
        gate.set()
        assert await _resting(driver) == "idle"
        assert [r[1] for r in job.records.rows] == [first]  # one pass, nothing queued after it
        assert driver._jobs[ACCOUNT].interp.deferred_count == 0
    finally:
        gate.set()
        await driver.stop()


async def test_divergent_takes_every_trigger_as_sweep_due_carrying_it(
    job: Job, timers: Timers, monkeypatch: pytest.MonkeyPatch
) -> None:
    job.world.oms.seed(row(3, "cancelled"))
    job.world.venue.seed_order(remote(3), uid="1001")  # bound to a final row: an anomaly
    driver = _driver(job, timers)
    await driver.start([ACCOUNT])
    sent = _sent(driver, monkeypatch)
    try:
        assert await _resting(driver) == "divergent"
        for trigger in ("reconnect", "unknown", "startup", "periodic"):
            await driver.trigger(ACCOUNT, trigger)
            assert await _resting(driver) == "divergent"
        assert sent == ["SWEEP_DUE"] * 4
        assert [r[2]["trigger"] for r in job.records.rows] == [
            "startup", "reconnect", "unknown", "startup", "periodic",
        ]  # fmt: skip
        assert driver._jobs[ACCOUNT].interp.deferred_count == 0
    finally:
        await driver.stop()


async def test_stale_lockout_skips_every_trigger_but_records_a_reconnect(
    job: Job, timers: Timers, monkeypatch: pytest.MonkeyPatch
) -> None:
    driver = _driver(job, timers)
    await driver.start([])
    await _locked(job, driver, timers)
    sent = _sent(driver, monkeypatch)
    try:
        with capture_logs() as logs:
            for trigger in ("periodic", "startup", "unknown", "manual", "reconnect"):
                assert await driver.trigger(ACCOUNT, trigger) is None
        assert sent == ["RECONNECTED"]  # recorded; clears nothing (INV-B19-b)
        skipped = [e["trigger"] for e in logs if e["event"] == "reconcile_trigger_skipped"]
        assert skipped == ["periodic", "startup", "unknown", "manual"]
        assert "reconcile_reconnect_while_locked" in {e["event"] for e in logs}
        assert await _resting(driver) == "stale_lockout"
        assert job.standing.is_stale(ACCOUNT)
        assert driver._jobs[ACCOUNT].interp.deferred_count == 0  # nothing waits to replay
    finally:
        await driver.stop()


# --- The on-demand pass and the operator's decision (22, BQ-7) -----------------------------------


async def test_a_manual_request_writes_ahead_then_starts_a_pass_or_joins_the_running_one(
    job: Job, timers: Timers, monkeypatch: pytest.MonkeyPatch
) -> None:
    driver = _driver(job, timers)
    await driver.start([ACCOUNT])
    await _resting(driver)
    sent, written = _sent(driver, monkeypatch), list[tuple[PassTaken, list[str]]]()

    async def write_ahead(taken: PassTaken) -> None:
        written.append((taken, list(sent)))  # what B19 had been sent when the record was written

    gate = await _held_fetch(job, monkeypatch)
    try:
        started = await driver.reconcile_now(ACCOUNT, write_ahead=write_ahead)
        joined = await driver.reconcile_now(ACCOUNT, write_ahead=write_ahead)
        assert (started.joined, joined) == (False, PassTaken(started.pass_id, joined=True))
        assert written == [(started, []), (joined, ["SWEEP_DUE"])]  # each written ahead
        gate.set()
        assert await _resting(driver) == "idle"
        assert job.records.rows[-1][1:] == (started.pass_id, job.records.rows[-1][2])
        assert job.records.rows[-1][2]["trigger"] == "manual"
    finally:
        gate.set()
        await driver.stop()


async def test_a_manual_request_opens_the_job_of_an_account_with_none_but_never_once_stopping(
    job: Job, timers: Timers
) -> None:
    """24 Sec.8.5: an on-demand request is a trigger like any other, so it opens the account's
    job (restored, or built afresh) and starts its pass; once the driver stops, none opens and
    nothing is written."""
    driver = _driver(job, timers)
    await driver.start([])
    written: list[PassTaken] = []

    async def write_ahead(taken: PassTaken) -> None:
        written.append(taken)

    try:
        assert ACCOUNT not in driver._jobs
        taken = await driver.reconcile_now(ACCOUNT, write_ahead=write_ahead)
        assert ACCOUNT in driver._jobs and written == [taken] and taken.joined is False
        assert await _resting(driver) == "idle"
        assert job.records.rows[-1][1] == taken.pass_id
    finally:
        await driver.stop()
    with pytest.raises(ReconciliationUnavailable):
        await driver.reconcile_now(AccountId(UUID(int=7)), write_ahead=write_ahead)
    assert len(written) == 1


async def test_a_manual_request_on_a_locked_job_is_refused_and_writes_nothing(
    job: Job, timers: Timers
) -> None:
    driver = _driver(job, timers)
    await driver.start([])
    await _locked(job, driver, timers)
    written: list[PassTaken] = []

    async def write_ahead(taken: PassTaken) -> None:
        written.append(taken)

    try:
        with pytest.raises(JobLocked):
            await driver.reconcile_now(ACCOUNT, write_ahead=write_ahead)
        assert written == [] and await _resting(driver) == "stale_lockout"
    finally:
        await driver.stop()


async def test_resolve_writes_ahead_then_b19_unlocks_and_the_standing_clears_after(
    job: Job, timers: Timers
) -> None:
    """BQ-5, C-2.21: the decision is recorded before B19 is told, while the account is still
    refused; the standing clears only once B19 has recorded `OPERATOR_RESOLVED`."""
    driver = _driver(job, timers)
    await driver.start([])
    await _locked(job, driver, timers)
    seen: list[tuple[str, bool]] = []

    async def write_ahead(state: str) -> None:
        seen.append((state, job.standing.is_stale(ACCOUNT)))

    try:
        assert await driver.resolve(ACCOUNT, decided_by="owner", write_ahead=write_ahead) == (
            "stale_lockout"
        )
        assert seen == [("stale_lockout", True)]
        assert not job.standing.is_stale(ACCOUNT) and await _resting(driver) == "idle"
        with pytest.raises(NothingToResolve):  # idle: OPERATOR_RESOLVED is sent nowhere else
            await driver.resolve(ACCOUNT, decided_by="owner", write_ahead=write_ahead)
        assert len(seen) == 1
    finally:
        await driver.stop()


async def test_a_decision_whose_record_fails_changes_nothing(job: Job, timers: Timers) -> None:
    driver = _driver(job, timers)
    await driver.start([])
    await _locked(job, driver, timers)

    async def refused(_state: str) -> None:
        raise ConnectionError("the audit store is down")

    try:
        with pytest.raises(ConnectionError):
            await driver.resolve(ACCOUNT, decided_by="owner", write_ahead=refused)
        assert job.standing.is_stale(ACCOUNT) and await _resting(driver) == "stale_lockout"
    finally:
        await driver.stop()


async def test_kill_is_never_sent_to_b19(
    job: Job, timers: Timers, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BQ-13: the kill switch stops entries, never protection (C-2.6); a `KILL` is a defect."""
    driver = _driver(job, timers)
    sent = _sent(driver, monkeypatch)
    await driver.start([ACCOUNT])
    try:
        await _resting(driver)
        for trigger in ("periodic", "reconnect", "unknown", "manual", "startup"):
            await driver.trigger(ACCOUNT, trigger)
            await _resting(driver)
        with pytest.raises(AssertionError, match="KILL is never sent"):
            await driver._send_job(driver._jobs[ACCOUNT], "KILL", {})
    finally:
        await driver.stop()
    assert "KILL" not in sent


# --- auto_remediate comes from the capability only (C-4.14, 24 Sec.14.3) ------------------------


@pytest.mark.parametrize("environment", ["live", "demo"])
async def test_a_live_or_demo_record_that_does_not_remediate_refuses_start(
    job: Job, timers: Timers, environment: str
) -> None:
    driver = _driver(job, timers, environment=environment, remediates=lambda _env: False)
    with pytest.raises(ValueError, match="always remediates"):
        await driver.start([ACCOUNT])
    assert driver._jobs == {}


async def test_a_testnet_job_takes_auto_remediate_from_its_record(job: Job, timers: Timers) -> None:
    asked: list[str] = []

    def remediates(environment: str) -> bool:
        asked.append(environment)
        return False

    job.world.oms.seed(row(1))  # found nowhere: a divergence the pass would act on
    driver = _driver(job, timers, environment="testnet", remediates=remediates)
    await driver.start([ACCOUNT])
    try:
        assert await _resting(driver) == "idle"
        assert asked == ["testnet"]
        assert driver._jobs[ACCOUNT].interp.context["auto_remediate"] is False
        assert job.world.oms.effects("command") == []  # reported, never acted on
    finally:
        await driver.stop()


async def test_a_snapshot_whose_auto_remediate_is_not_the_records_does_not_open(
    job: Job, timers: Timers, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INV-B19-d, 24 Sec.14.3: the record is `auto_remediate`'s only source, on a restore too. A
    testnet job snapshotted while its record said `False`, restored once it says `True`, does not
    open: the restored machine is stopped, and the start refuses the account order entry and
    pages, as for a store that fails."""
    memory = Memory()
    first = _driver(job, timers, environment="testnet", persistence=memory,
                    remediates=lambda _env: False)  # fmt: skip
    await first.start([ACCOUNT])
    await _resting(first)
    await first.stop()
    restored: list[Any] = []
    restore = memory.restore

    async def kept(key: MachineKey, sealed: SealedSnapshot) -> Any:
        restored.append(await restore(key, sealed))
        return restored[-1]

    monkeypatch.setattr(memory, "restore", kept)
    fresh = Job(retries=RetryHop())  # type: ignore[arg-type]  # the driver's hop, not the rig's
    later = _driver(fresh, timers, environment="testnet", persistence=memory)
    with capture_logs() as logs:
        await later.start([ACCOUNT])
    try:
        assert later.state(ACCOUNT) is None and fresh.standing.is_stale(ACCOUNT)
        failed = [e["failure"] for e in logs if e["event"] == "reconcile_job_open_failed"]
        assert failed == ["ValueError"]
        [interp] = restored
        assert interp.context["auto_remediate"] is False and not interp.is_running
        assert ("page", rj._UNOPENED) in fresh.world.oms.pages
    finally:
        await later.stop()


# --- Stop, restore and the standing (BQ-5, INV-B19-e) --------------------------------------------


async def test_stop_persists_every_job_before_b19_is_unwired(job: Job, timers: Timers) -> None:
    memory = Memory()
    other = AccountId(UUID(int=0xA2))
    driver = _driver(job, timers, persistence=memory)
    await driver.start([ACCOUNT, other])
    await _resting(driver)
    await driver.stop()
    keys = {key.entity_id for key, _ in memory.persisted}
    assert keys == {str(ACCOUNT), str(other)}
    assert all(wired for _, wired in memory.persisted)  # unwired only once each was snapshotted
    assert not b19.ports_wired()
    with pytest.raises(ReconciliationUnavailable):  # stopped: no job opens again
        await driver.trigger(ACCOUNT, "periodic")


async def test_a_restart_restores_a_locked_job_and_never_unlocks_it(
    job: Job, timers: Timers
) -> None:
    memory = Memory()
    first = _driver(job, timers, persistence=memory)
    await first.start([])
    await _locked(job, first, timers)
    await first.stop()
    fresh = Job(retries=RetryHop())  # type: ignore[arg-type]  # a new process, the driver's hop
    later = _driver(fresh, timers, persistence=memory)
    with capture_logs() as logs:
        await later.start([ACCOUNT])
    try:
        assert later.state(ACCOUNT) == "stale_lockout"
        assert fresh.standing.is_stale(ACCOUNT)  # rebuilt from the restored state
        assert fresh.standing.refusal(ACCOUNT) is not None
        skipped = [e for e in logs if e["event"] == "reconcile_trigger_skipped"]
        assert [(e["trigger"], e["reason"]) for e in skipped] == [("startup", "locked")]
    finally:
        await later.stop()


async def test_stop_cancels_a_pass_backing_off_so_its_snapshot_restores_idle(
    job: Job, timers: Timers
) -> None:
    memory = Memory()
    first = _driver(job, timers, persistence=memory)
    await first.start([])
    _starve(job)
    await first.trigger(ACCOUNT, "periodic")
    assert await _resting(first) == "backing_off"
    # stop cancels a pass backing off (CANCEL, to idle) before it persists the job
    await first.stop()
    assert memory.persisted and memory.repo.rows
    [(key, sealed)] = memory.repo.rows.items()
    restored = await memory.restore(key, sealed)
    try:
        assert leaf_of(restored) == "idle"
    finally:
        await restored.stop()


async def test_a_job_that_cannot_open_at_start_is_refused_order_entry_and_paged(
    job: Job, timers: Timers
) -> None:
    memory = Memory()
    memory.refuse_load = True
    driver = _driver(job, timers, persistence=memory)
    with capture_logs() as logs:
        await driver.start([ACCOUNT])
    try:
        assert driver.state(ACCOUNT) is None
        assert job.standing.is_stale(ACCOUNT)  # fail closed until a job opens
        assert "reconcile_job_unopened" in {e["event"] for e in logs}
        assert ("page", rj._UNOPENED) in job.world.oms.pages
        memory.refuse_load = False
        await driver.trigger(ACCOUNT, "periodic")  # the next trigger opens it
        assert not job.standing.is_stale(ACCOUNT)
    finally:
        await driver.stop()


@pytest.mark.parametrize("step", ["load", "restore", "plugins"])
async def test_an_open_whose_step_hangs_is_bounded_and_refuses_the_account(
    job: Job, timers: Timers, monkeypatch: pytest.MonkeyPatch, step: str
) -> None:
    """C-2.18: each step of a job's open the driver awaits (its snapshot's load, its restore, a
    fresh build's plugins) is bounded (`OPEN_TIMEOUT_S`, spent at once here), so one that hangs is
    logged by its class, and the start refuses the account order entry and pages, as a store that
    fails would: fail closed, never a start that waits on it in silence."""
    memory = Memory()
    if step != "plugins":  # a snapshot to load and restore; with none, a fresh build's plugins
        first = _driver(job, timers, persistence=memory)
        await first.start([ACCOUNT])
        await _resting(first)
        await first.stop()

    async def hangs(*_args: Any) -> Any:
        await asyncio.Event().wait()

    monkeypatch.setattr(memory, step, hangs)
    monkeypatch.setattr(rj, "OPEN_TIMEOUT_S", 0.0)
    fresh = Job(retries=RetryHop())  # type: ignore[arg-type]  # the driver's hop, not the rig's
    driver = _driver(fresh, timers, persistence=memory)
    with capture_logs() as logs:
        await asyncio.wait_for(driver.start([ACCOUNT]), 10)  # a bound on the test
    try:
        assert driver.state(ACCOUNT) is None and fresh.standing.is_stale(ACCOUNT)
        failed = [e["failure"] for e in logs if e["event"] == "reconcile_job_open_failed"]
        assert failed == ["TimeoutError"]
        assert ("page", rj._UNOPENED) in fresh.world.oms.pages
    finally:
        await driver.stop()


# --- The host timers: the cadence and the retry (C-12.7, A2) ---------------------------------


async def test_the_cadence_spreads_the_accounts_under_five_seconds_apart_and_ticks(
    job: Job, timers: Timers
) -> None:
    now = [100.0]
    accounts = [AccountId(UUID(int=0xA0 + n)) for n in range(1, 4)]
    driver = ReconcileJobs(
        job.phases, standing=job.standing, environment="demo", remediates=lambda _e: True,
        metrics=Metrics("dev"), pager=job.world.oms, sink=InMemoryMachineEventSink(),
        sleep=timers.sleep, monotonic=lambda: now[0],
    )  # fmt: skip
    ticks: list[tuple[AccountId, str]] = []
    trigger = driver.trigger

    async def counted(account: AccountId, kind: Any) -> str | None:
        ticks.append((account, kind))
        return await trigger(account, kind)

    driver.trigger = counted  # type: ignore[method-assign]  # a spy over the real trigger
    await driver.start(accounts)
    try:
        await _asked(timers, lambda asked: len(asked) >= 3)
        offsets = sorted(round(w - 30.0, 6) for w in timers.asked)
        assert offsets[0] == 0.0 and all(o < 5.0 for o in offsets)  # jitter under 5 s
        assert all(b - a >= 0.2 for a, b in pairwise(offsets))  # never in one 200 ms window
        now[0] += 35.0
        await timers.release()  # each account's first periodic tick
        await _asked(timers, lambda asked: len(asked) >= 6)
        assert sorted(a for a, kind in ticks if kind == "periodic") == accounts
    finally:
        await driver.stop()


async def test_a_failed_fetch_backs_off_on_a_host_timer_until_the_window_locks(
    job: Job, timers: Timers
) -> None:
    driver = _driver(job, timers)
    await driver.start([])
    _starve(job)
    try:
        await driver.trigger(ACCOUNT, "periodic")
        assert await _until(driver, "backing_off") == "backing_off"
        await _asked(timers, lambda asked: 1.0 in asked)  # a second later, never an `after:`
        timers.asked.clear()
        await timers.release()
        await _asked(timers, lambda asked: 2.0 in asked)  # backing off: 1 s, then 2 s
        assert await _until(driver, "backing_off") == "backing_off"
        job.world.now_us += WINDOW_US
        await timers.release()
        assert await _until(driver, "stale_lockout") == "stale_lockout"
        assert job.standing.is_stale(ACCOUNT)
    finally:
        await driver.stop()


async def test_a_retry_with_no_driver_bound_is_logged_and_dropped() -> None:
    hop = RetryHop()
    with capture_logs() as logs:
        hop.retry(ACCOUNT, attempt=1)
    assert [e["event"] for e in logs] == ["reconcile_retry_unbound"]


# --- The edges: configuration, unknown subjects, restores and failures ---------------------------


def test_a_jitter_of_five_seconds_or_one_over_the_interval_is_refused(job: Job) -> None:
    for jitter, interval in ((5.0, 30.0), (0.1, 30.0), (4.0, 3.0)):
        with pytest.raises(ValueError, match="jitter"):
            ReconcileJobs(
                job.phases, standing=job.standing, environment="demo", remediates=lambda _e: True,
                metrics=Metrics("dev"), pager=job.world.oms, sink=InMemoryMachineEventSink(),
                jitter_s=jitter, interval_s=interval,
            )  # fmt: skip


def test_a_machine_with_no_reconciliation_leaf_reads_none() -> None:
    from types import SimpleNamespace

    assert leaf_of(SimpleNamespace(current_state_ids=["order.lifecycle.idle"])) == ""


async def test_unknown_triggers_and_accounts_are_refused(job: Job, timers: Timers) -> None:
    driver = _driver(job, timers)
    await driver.start([ACCOUNT])
    try:
        with pytest.raises(ValueError, match="triggers"):  # "kill" is no `Trigger`, on purpose
            await driver.trigger(ACCOUNT, "kill")  # type: ignore[arg-type]
        nobody = AccountId(UUID(int=7))

        async def never(_state: str) -> None:
            raise AssertionError("nothing is written for an account with no job")

        with pytest.raises(NoSuchJob):
            await driver.resolve(nobody, decided_by="owner", write_ahead=never)
        driver.retry(nobody, attempt=1)  # no job: nothing scheduled
    finally:
        await driver.stop()
    await driver.stop()  # a second stop unwires nothing it no longer wires
    driver.retry(ACCOUNT, attempt=1)  # stopping: nothing scheduled


async def test_a_retry_that_finds_the_job_no_longer_backing_off_sends_nothing(
    job: Job, timers: Timers, monkeypatch: pytest.MonkeyPatch
) -> None:
    driver = _driver(job, timers)
    await driver.start([ACCOUNT])
    sent = _sent(driver, monkeypatch)

    async def now(_seconds: float) -> None:
        return None

    try:
        await _resting(driver)
        monkeypatch.setattr(driver, "_sleep", now)
        await driver._retry_after(driver._jobs[ACCOUNT], 1.0)
        assert sent == []
    finally:
        await driver.stop()


async def test_a_job_restored_backing_off_is_sent_its_owed_retry_due(
    job: Job, timers: Timers
) -> None:
    """INV-B19-e: a static restore resumes no host timer, so the driver sends the `RETRY_DUE`
    the restored job is owed, and the pass runs."""
    memory = Memory()
    first = _driver(job, timers, persistence=memory)
    await first.start([])
    _starve(job)
    await first.trigger(ACCOUNT, "periodic")
    assert await _until(first, "backing_off") == "backing_off"
    await memory.persist(first._jobs[ACCOUNT].interp, first._jobs[ACCOUNT].machine_key)
    await first.stop()
    fresh = Job(retries=RetryHop())  # type: ignore[arg-type]  # the driver's hop, not the rig's
    later = _driver(fresh, timers, persistence=memory)
    sent = _sent(later, pytest.MonkeyPatch())
    await later.start([ACCOUNT])
    try:
        assert sent[0] == "RETRY_DUE"
        assert await _resting(later) == "idle"
        assert [r[2]["trigger"] for r in fresh.records.rows] == ["periodic"]
    finally:
        await later.stop()


async def test_a_refused_or_mid_pass_restore_builds_the_job_afresh(
    job: Job, timers: Timers, monkeypatch: pytest.MonkeyPatch
) -> None:
    from candleviewer.statechart.persistence import RestoreRefusedError

    memory = Memory()
    first = _driver(job, timers, persistence=memory)
    await first.start([ACCOUNT])
    await _resting(first)
    await first.stop()
    [key] = memory.repo.rows

    async def refused(_key: MachineKey, _sealed: SealedSnapshot) -> Any:
        raise RestoreRefusedError(key, "machine_hash")

    for case in ("refused", "mid_pass"):
        fresh = Job(retries=RetryHop())  # type: ignore[arg-type]  # the driver's hop, not the rig's
        later = _driver(fresh, timers, persistence=memory)
        with monkeypatch.context() as patch:
            if case == "refused":
                patch.setattr(memory, "restore", refused)
            else:  # diffing or remediating: no event leaves them, so the job is rebuilt
                patch.setattr(b19, "redrive_after_restore", lambda _state, _context: None)
            await later.start([ACCOUNT])
        try:
            assert await _resting(later) == "idle"
            assert [r[2]["trigger"] for r in fresh.records.rows] == ["startup"]
        finally:
            await later.stop()


async def test_a_persist_that_fails_stops_the_job_without_a_snapshot(
    job: Job, timers: Timers, monkeypatch: pytest.MonkeyPatch
) -> None:
    memory = Memory()
    driver = _driver(job, timers, persistence=memory)
    await driver.start([ACCOUNT])
    await _resting(driver)
    interp = driver._jobs[ACCOUNT].interp

    async def broken(_interp: Any, _key: MachineKey) -> None:
        raise ConnectionError("the snapshot store is down")

    monkeypatch.setattr(memory, "persist", broken)
    with capture_logs() as logs:
        await driver.stop()
    assert "reconcile_job_persist_failed" in {e["event"] for e in logs}
    assert not interp.is_running and not b19.ports_wired()


async def test_a_refused_send_and_a_failed_timer_are_logged(
    job: Job, timers: Timers, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    driver = _driver(job, timers)
    await driver.start([ACCOUNT])
    await _resting(driver)

    async def refused(_key: str, _event: Any, *, wait: bool = False) -> Any:
        return SimpleNamespace(deferred=False, changed=False, error=ValueError("denied"))

    async def broken() -> None:
        raise RuntimeError("a timer's defect")

    try:
        with capture_logs() as logs:
            monkeypatch.setattr(driver._gateway, "send", refused)
            await driver.trigger(ACCOUNT, "periodic")
            failed = driver._spawn(broken(), "reconcile-test")
            await asyncio.gather(failed, return_exceptions=True)
            await asyncio.sleep(0)
        events = [e["event"] for e in logs]
        assert "reconcile_send_refused" in events and "reconcile_timer_failed" in events
    finally:
        monkeypatch.undo()
        await driver.stop()


async def test_a_tick_that_fails_keeps_the_cadence_and_one_that_finds_it_stopping_ends_it(
    job: Job, timers: Timers, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [10_000.0]
    driver = ReconcileJobs(
        job.phases, standing=job.standing, environment="demo", remediates=lambda _e: True,
        metrics=Metrics("dev"), pager=job.world.oms, sink=InMemoryMachineEventSink(),
        sleep=timers.sleep, monotonic=lambda: now[0],
    )  # fmt: skip
    await driver.start([ACCOUNT])
    job_ = driver._jobs[ACCOUNT]
    seen: list[str] = []

    async def failing(_account: AccountId, kind: Any) -> str | None:
        seen.append(kind)
        if len(seen) == 1:
            raise RuntimeError("one tick's defect")
        raise ReconciliationUnavailable("stopping")

    try:
        assert job_.cadence is not None
        job_.cadence.cancel()  # this test runs the account's cadence itself
        monkeypatch.setattr(driver, "trigger", failing)
        now[0] += 1_000.0  # the first tick is long due: it is not waited for
        with capture_logs() as logs:
            ticking = asyncio.ensure_future(driver._cadence(job_))
            await _asked(timers, lambda asked: any(a < 30.0 for a in asked))  # the next, later
            await timers.release()  # the second tick finds it stopping: the cadence ends
            await asyncio.wait_for(ticking, 1.0)
        assert seen == ["periodic", "periodic"]
        assert "reconcile_tick_failed" in {e["event"] for e in logs}
    finally:
        monkeypatch.undo()
        await driver.stop()


async def test_no_job_is_built_while_b19s_port_is_unwired(job: Job, timers: Timers) -> None:
    """#5121's carry: a job built unwired would lock on its first pass, so `ports_wired()` is
    checked before every build or restore, and a trigger then finds no job to take it."""
    driver = _driver(job, timers)
    await driver.start([])
    b19.set_ports(None)  # as a stop elsewhere would leave it
    try:
        with pytest.raises(ReconciliationUnavailable):
            await driver.trigger(ACCOUNT, "reconnect")
        assert driver.state(ACCOUNT) is None and job.records.rows == []
    finally:
        await driver.stop()
