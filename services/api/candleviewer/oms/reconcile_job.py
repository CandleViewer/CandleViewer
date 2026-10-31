"""The reconciliation job driver (E29-T06 #914 PR 2b; 24-internal-schemas.md Sec.8.5 "Runs", its
trigger table and the stale rule; the ruling of record on #914, BQ-1, BQ-7, BQ-13, BQ-14; 28 B19).

One B19 interpreter per exchange account of the process's environment, on the OMS's order lane:
built only through `cv.statechart.factory` (`build`) and restored only through
`statechart.persistence` (the factory's `restore`, the `Restorer`'s), every event sent through
`statechart.gateway` (BQ-1). B19's services run the pass (`oms.reconciler`) through the port the
composition wires (`b19_reconciliation.set_ports`), which `start` checks is wired before it builds
or restores any job, and which `stop` unwires only once every job is stopped and snapshotted, so a
pass that starts unwired never runs here (it would lock, #5121's carry). This module decides what
B19 is sent and when; it holds no pass state of its own.

**The triggers** (24 Sec.8.5's table): `startup`, sent as `start` opens each job, before the OMS
reports ready, which never waits for the pass (BQ-14); `reconnect`, the private stream's
`request_reconciliation` (`ReconciliationRequests`, which this driver is); `periodic`, every
`interval_s` (30 s) on a host timer; `manual`, `reconcileAccount` (`reconcile_now`); and `unknown`,
B1's `request_reconciliation` notice (an order `quarantined`, or a cancel the venue answered
`110001`). One rule sends them, by the state B19 rests in:

* `idle`: the table's event (`STARTUP`, `RECONNECTED`, `SWEEP_DUE`, `UNKNOWN_ORDER`); `SWEEP_DUE`
  carries its `trigger`, so a manual pass records `manual`;
* `divergent`: every trigger as `SWEEP_DUE` carrying its `trigger`, as only `SWEEP_DUE` and
  `OPERATOR_RESOLVED` have arms there (any other would be deferred);
* `stale_lockout`: a reconnect is sent as `RECONNECTED`, which B19 records and which clears
  nothing; every other trigger is skipped and logged, never sent, so never deferred (INV-B19-b);
* a pass running (any other state, or B19 not quiescent): skipped and logged, never queued; an
  on-demand request answers the running pass's `pass_id` (`joined`).

`KILL` is never sent to B19 (BQ-13): `_send` refuses it as a defect.

**The cadence** (C-12.7): each job's periodic tick runs at a fixed phase in its 30 s cycle, the
jobs' phases spread over the first `jitter_s` (under 5 s), so no two accounts start a pass in the
same `spacing` window (200 ms) while fewer than `jitter_s / spacing` accounts are reconciled. A
tick that finds a pass running is skipped, never queued. The pass's reads use the `poll` lane, its
fetch checks the lane's headroom first and stops at the first rate-limit answer (`reconciler`).
A failed fetch's retry is a host timer too (`retry`, B19's `schedule_retry_deadline`), backing off
from `retry_s[0]` to `retry_s[1]`, never an `after:` timer (28 Sec.1.2, A2).

**Restore** (INV-B19-e): a job with a sealed snapshot is restored, the account's standing rebuilt
from its restored state (`ReconcileStanding.restored`, so a restart never unlocks a stale
account), and what `redrive_after_restore` names is sent; a job restored mid-diff or remediation
is rebuilt afresh. A refused snapshot is quarantined and paged by the `Restorer` and the job is
built afresh. **Stop**: the timers end, then each job is drained to quiescence, persisted (drain,
journal, sealed snapshot, then `stop`) where a persister is wired, else stopped, and unregistered;
only then is B19's port unwired.

**`auto_remediate`** (INV-B19-d, 24 Sec.14.3, C-4.14) comes only from the account's environment's
capability record (`remediates`), never a setting, a flag or a role, and a live or demo record
that says `False` refuses `start`: such a job would never repair a naked position (C-2.6).

Logs carry account ids, pass ids, triggers and states only (C-12.6).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Protocol
from uuid import uuid4

import structlog

from candleviewer.domain.primitives import AccountId, Environment
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.statechart import build
from candleviewer.statechart.bindings import b19_reconciliation as b19
from candleviewer.statechart.factory import default_clock
from candleviewer.statechart.gateway import Gateway, receipt_is_conclusive
from candleviewer.statechart.persistence import (
    MachineKey,
    RestoreRefusedError,
    SealedSnapshot,
    quiescent,
)
from candleviewer.statechart.plugins import CvMetricsPlugin, MachineEventSink, Pager, cv_plugins

from .errors import ReconciliationUnavailable
from .ports import ResyncReason
from .reconcile_report import TRIGGERS, Trigger
from .reconcile_standing import ReconcileStanding

__all__ = [
    "JITTER_S",
    "MACHINE",
    "RETRY_S",
    "SPACING_S",
    "JobLocked",
    "JobPersistence",
    "NoSuchJob",
    "NothingToResolve",
    "PassTaken",
    "ReconcileJobs",
    "RetryHop",
]

#: B19's machine and lane (28 B19; the OMS's order lane, CV-C13).
MACHINE: Final = "reconciliation"
LANE: Final = "order"
#: `CV_OMS_RECONCILE_INTERVAL_S`'s default (#914 Technical notes): the periodic cadence.
INTERVAL_S: Final = 30.0
#: The phases of the jobs' periodic ticks are spread over this much of the cycle (under 5 s).
JITTER_S: Final = 4.8
#: The least gap between two accounts' periodic ticks while the spread allows it.
SPACING_S: Final = 0.2
#: A failed fetch's retry backs off from the first to the second (seconds), host-timed.
RETRY_S: Final = (1.0, 30.0)
#: Each send to a job, and each wait for its quiescence at the stop (C-2.18).
SEND_TIMEOUT_S: Final = 5.0
QUIESCE_TIMEOUT_S: Final = 10.0
QUIESCE_POLL_S: Final = 0.01
#: The states a pass is running in: a trigger there is skipped, never queued.
_RESTING: Final = frozenset({"idle", "divergent", "stale_lockout"})
#: The states the operator's decision leaves (22 `resolveReconciliation`).
RESOLVABLE: Final = frozenset({"stale_lockout", "divergent"})
#: A reconnect's reasons, all one trigger (24 Sec.8.5's table: a reconnect or a resync).
_RECONNECTS: Final[frozenset[str]] = frozenset({"connected", "reconnected", "rejected_frame"})
_STALE_GAUGE: Final = "oms_stale_accounts"
#: The environments whose jobs always remediate (24 Sec.14.3): never `False` there (C-2.6).
_ALWAYS_REMEDIATE: Final[frozenset[str]] = frozenset({"live", "demo"})


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class NoSuchJob(LookupError):
    """No job reconciles this account in this process (another environment's, or none)."""


class JobLocked(Exception):
    """The account's job is locked stale: no pass runs until the operator resolves it (22
    `reconcileAccount`'s `409 reconciliation_locked`)."""


class NothingToResolve(Exception):
    """The account's job is neither locked stale nor waiting for the operator (22
    `resolveReconciliation`'s `409 nothing_to_resolve`)."""


@dataclass(frozen=True, slots=True)
class PassTaken:
    """`reconcileAccount`'s answer: the pass started, or the one running (`joined`)."""

    pass_id: str
    joined: bool


class JobPersistence(Protocol):
    """The statechart persistence bundle as a job takes it (`statechart_wiring`): a sealed
    snapshot's load and restore, a fresh build's plugins (its chain seeded and the orphan scan
    run), and the quiescent persist that ends a job (drain, journal, snapshot, `stop`)."""

    async def load(self, key: MachineKey) -> SealedSnapshot | None: ...

    async def restore(self, key: MachineKey, sealed: SealedSnapshot) -> Any: ...

    async def plugins(self, key: MachineKey) -> tuple[Any, ...]: ...

    async def persist(self, interp: Any, key: MachineKey) -> None: ...


#: What a route writes ahead of telling B19, given what it decided (C-2.9): raising sends nothing.
type WriteAhead[T] = Callable[[T], Awaitable[None]]


@dataclass
class _Job:
    """One account's B19 and its host timers."""

    account: AccountId
    key: str
    machine_key: MachineKey
    interp: Any
    slot: int
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    cadence: asyncio.Task[None] | None = None
    retry: asyncio.Task[None] | None = None


def leaf_of(interp: Any) -> str:
    """B19's one active leaf (`reconciliation.<state>`), or `""` while it has none."""
    for state in interp.current_state_ids:
        if str(state).startswith(f"{MACHINE}."):
            return str(state).rsplit(".", 1)[1]
    return ""


class ReconcileJobs:
    """The process's reconciliation jobs (module docstring), one per account, on the order lane.
    It is the private stream's `ReconciliationRequests` (`request_reconciliation`) and B19's
    `RetryTimer` (`retry`)."""

    def __init__(
        self,
        phases: b19.JobPorts,
        *,
        standing: ReconcileStanding,
        environment: Environment,
        remediates: Callable[[Environment], bool],
        metrics: Metrics,
        pager: Pager,
        sink: MachineEventSink,
        persistence: JobPersistence | None = None,
        interval_s: float = INTERVAL_S,
        jitter_s: float = JITTER_S,
        retry_s: tuple[float, float] = RETRY_S,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        if not 0 < SPACING_S <= jitter_s < 5.0 or interval_s <= jitter_s:
            raise ValueError("the jitter is under 5 s and under the interval, the spacing in it")
        self._phases, self._standing, self._env = phases, standing, environment
        self._remediates, self._metrics, self._pager = remediates, metrics, pager
        self._sink, self._persistence = sink, persistence
        self._interval_s, self._jitter_s, self._retry_s = interval_s, jitter_s, retry_s
        self._sleep, self._monotonic = sleep, monotonic
        self._gateway = Gateway(pager=pager)
        self._jobs: dict[AccountId, _Job] = {}
        self._opening = asyncio.Lock()
        self._tasks: set[asyncio.Task[None]] = set()
        self._pass_ids: dict[AccountId, str] = {}
        self._remediate = True
        self._spacing = SPACING_S
        self._t0 = 0.0
        self._wired = self._stopping = False

    # --- Life -------------------------------------------------------------------------------------

    async def start(self, accounts: Iterable[AccountId]) -> None:
        """Wires B19's port, then opens each account's job (restored, or built afresh) and sends
        it `startup` (BQ-14: the caller reports ready after it, never after the pass). One
        account whose job cannot open is logged, paged and refused order entry (its standing
        set, fail closed) until a later trigger opens it; the others start."""
        remediate = self._remediates(self._env)
        if not remediate and self._env in _ALWAYS_REMEDIATE:  # C-2.6, C-4.14: never on live or demo
            raise ValueError("a live or demo reconciliation job always remediates (24 Sec.14.3)")
        self._remediate, self._stopping = remediate, False
        b19.set_ports(self._phases)
        self._wired = True
        self._t0 = self._now()
        ordered = sorted(set(accounts), key=str)
        self._spacing = max(SPACING_S, self._jitter_s / max(len(ordered), 1))
        self._gauge(lambda: float(self._standing.stale_count))
        for account in ordered:
            try:
                await self.trigger(account, "startup")
            except ReconciliationUnavailable:
                self._standing.mark_stale(account)  # unknown: refused until a job opens it
                _log().critical("reconcile_job_unopened", account_id=str(account), cv_page=True)
                self._pager.raise_alert("page", _UNOPENED, machine_kind=MACHINE)

    async def stop(self) -> None:
        """The timers end, then each job is drained to quiescence and persisted (or stopped), and
        unregistered; B19's port is unwired last, once every job is stopped and snapshotted."""
        self._stopping = True
        tasks = [t for t in self._tasks if not t.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for job in list(self._jobs.values()):
            await self._close(job)
        self._jobs.clear()
        self._gauge(lambda: 0.0)
        if self._wired:  # a stopped driver never unwires the port of the one after it
            self._wired = False
            b19.set_ports(None)

    # --- The triggers -----------------------------------------------------------------------------

    async def trigger(self, account: AccountId, trigger: Trigger) -> str | None:
        """Sends `trigger` to the account's job by the rule (module docstring), opening the job
        first if it has none: the pass id it started, or None when it was skipped (logged).
        `ReconciliationUnavailable` when no job can take it (stopping, unwired, or its open
        failed); never `KILL` (BQ-13)."""
        if trigger not in TRIGGERS:
            raise ValueError("not one of 24 Sec.8.5's triggers")
        job = await self._job(account)
        async with job.lock:
            return await self._sent(job, trigger)

    async def request_reconciliation(self, account_id: AccountId, *, reason: ResyncReason) -> None:
        """`ReconciliationRequests` (24 Sec.8.12): a stream that resyncs asks for a pass, the
        `reconnect` trigger; it returns once taken, never once the pass has run."""
        if reason not in _RECONNECTS:
            raise ValueError("not a resync reason")
        await self.trigger(account_id, "reconnect")

    async def reconcile_now(
        self, account: AccountId, *, write_ahead: WriteAhead[PassTaken]
    ) -> PassTaken:
        """`reconcileAccount` (22, BQ-7): a pass started now (`SWEEP_DUE`, `trigger: manual`), or
        the running one's id (`joined`); `write_ahead` records the request first (`oms.reconcile`,
        `stage: requested`) and a raise sends nothing. `NoSuchJob`, or `JobLocked` while locked."""
        job = self._jobs.get(account)
        if job is None:
            raise NoSuchJob(str(account))
        async with job.lock:
            state = leaf_of(job.interp)
            if state == "stale_lockout":
                raise JobLocked(str(account))
            if not self._resting(job, state):
                taken = PassTaken(self._running_pass(job), joined=True)
                await write_ahead(taken)
                return taken
            taken = PassTaken(str(uuid4()), joined=False)
            await write_ahead(taken)
            await self._send(job, "SWEEP_DUE", {"trigger": "manual", "pass_id": taken.pass_id})
            self._pass_ids[account] = taken.pass_id
            return taken

    async def resolve(
        self, account: AccountId, *, decided_by: str, write_ahead: WriteAhead[str]
    ) -> str:
        """`resolveReconciliation` (22, BQ-7): `OPERATOR_RESOLVED`, the one event that leaves
        `stale_lockout` (INV-B19-b), or ends `divergent`'s wait; `write_ahead` records the
        decision first (`stage: resolved`) and a raise sends nothing. The state it left, once B19
        recorded it, so the standing has cleared (BQ-5). `NoSuchJob`, or `NothingToResolve`."""
        job = self._jobs.get(account)
        if job is None:
            raise NoSuchJob(str(account))
        async with job.lock:
            state = leaf_of(job.interp)
            if state not in RESOLVABLE or not quiescent(job.interp):
                raise NothingToResolve(str(account))
            await write_ahead(state)
            await self._send(job, "OPERATOR_RESOLVED", {"decided_by": decided_by[:64]})
            return state

    def state(self, account: AccountId) -> str | None:
        """The account's job's state, or None without a job (a plain read, for the routes)."""
        job = self._jobs.get(account)
        return None if job is None else leaf_of(job.interp)

    # --- B19's host timers ------------------------------------------------------------------------

    def retry(self, account_id: AccountId, *, attempt: int) -> None:
        """`RetryTimer`: `RETRY_DUE` after a backoff, from a host timer (A2), as B19's
        `schedule_retry_deadline` asks; never a send from inside B19's action (CV-C25)."""
        job = self._jobs.get(account_id)
        if job is None or self._stopping:
            return
        first, ceiling = self._retry_s
        delay = min(first * 2 ** max(attempt - 1, 0), ceiling)
        if job.retry is not None:
            job.retry.cancel()
        job.retry = self._spawn(self._retry_after(job, delay), "reconcile-retry")

    async def _retry_after(self, job: _Job, delay: float) -> None:
        await self._sleep(delay)
        async with job.lock:
            if leaf_of(job.interp) == "backing_off" and quiescent(job.interp):
                await self._send(job, "RETRY_DUE", {})

    async def _cadence(self, job: _Job) -> None:
        """The periodic trigger at the job's fixed phase in each cycle (module docstring); a tick
        missed while one ran late is skipped, never caught up."""
        first = self._t0 + (job.slot * self._spacing) % self._jitter_s + self._interval_s
        tick = 0
        while True:
            due = first + tick * self._interval_s
            if (wait := due - self._now()) > 0:
                await self._sleep(wait)
            try:
                await self.trigger(job.account, "periodic")
            except ReconciliationUnavailable:
                return  # stopping
            except Exception as exc:  # one tick's failure never ends the cadence
                _log().error(
                    "reconcile_tick_failed", account_id=str(job.account), failure=type(exc).__name__
                )
            tick = max(tick + 1, int((self._now() - first) // self._interval_s) + 1)

    # --- Opening, sending and closing jobs --------------------------------------------------------

    async def _job(self, account: AccountId) -> _Job:
        job = self._jobs.get(account)
        if job is not None:
            return job
        async with self._opening:  # one open at a time: an account never gets two jobs
            return self._jobs.get(account) or await self._open(account)

    async def _open(self, account: AccountId) -> _Job:
        """The account's job: restored from its sealed snapshot where one is held, else built
        afresh, only once B19's port is wired (#5121's carry: unwired, a pass locks). Restored, its
        standing is rebuilt from its state and what the restore leaves owed is sent."""
        if self._stopping or not b19.ports_wired():
            raise ReconciliationUnavailable("no reconciliation job can open: stopping or unwired")
        key = MachineKey(MACHINE, str(account), self._env)
        try:
            interp, owed = await self._restored(account, key)
            if interp is None:
                interp = await self._built(account, key)
        except Exception as exc:  # the store or the build: no job, the caller decides
            _log().error("reconcile_job_open_failed", account_id=str(account),
                         failure=type(exc).__name__)  # fmt: skip
            raise ReconciliationUnavailable("the job did not open") from None
        job = _Job(account, f"{MACHINE}:{account}", key, interp, slot=len(self._jobs))
        recorder = CvMetricsPlugin(machine_kind=MACHINE, metrics=self._metrics)
        self._gateway.register(job.key, interp, kind=MACHINE, lane=LANE, metrics=recorder,
                               machine_key=key)  # fmt: skip
        self._jobs[account] = job
        state = leaf_of(interp)
        self._standing.restored(account, state)  # a restart never unlocks (BQ-5)
        pass_id = interp.context.get("pass_id")
        if isinstance(pass_id, str):
            self._pass_ids[account] = pass_id
        for event, payload in owed:
            await self._send(job, event, payload)
        job.cadence = self._spawn(self._cadence(job), "reconcile-cadence")
        _log().info("reconcile_job_opened", account_id=str(account), state=state,
                    restored=bool(owed) or state != "idle")  # fmt: skip
        return job

    async def _restored(
        self, account: AccountId, key: MachineKey
    ) -> tuple[Any | None, tuple[tuple[str, dict[str, Any]], ...]]:
        """The job restored, with what it is owed (`redrive_after_restore`), or None to build
        afresh: no persistence, no snapshot, a refused one (the `Restorer` quarantines and pages
        it), or one restored mid-diff or remediation, which no event leaves."""
        if self._persistence is None:
            return None, ()
        sealed = await self._persistence.load(key)
        if sealed is None:
            return None, ()
        try:
            interp = await self._persistence.restore(key, sealed)
        except RestoreRefusedError:
            _log().error("reconcile_job_restore_refused", account_id=str(account))
            return None, ()
        owed = b19.redrive_after_restore(leaf_of(interp), interp.context)
        if owed is None:
            await interp.stop()
            return None, ()
        return interp, owed

    async def _built(self, account: AccountId, key: MachineKey) -> Any:
        if self._persistence is not None:  # its chain seeded and the orphan scan run first
            plugins = await self._persistence.plugins(key)
        else:
            plugins = cv_plugins(
                machine_kind=MACHINE, lane=LANE, entity_id=str(account), env=self._env,
                metrics=self._metrics, sink=self._sink, pager=self._pager,
            )  # fmt: skip
        ctx = {"account_id": str(account), "auto_remediate": self._remediate}
        built = await build(MACHINE, ctx=ctx, clock=default_clock(), lane=LANE, plugins=plugins)
        return built.interpreter

    async def _sent(self, job: _Job, trigger: Trigger) -> str | None:
        """The rule (module docstring), under the job's lock."""
        state = leaf_of(job.interp)
        if not self._resting(job, state):
            self._skipped(job, trigger, state, "running")
            return None
        if state == "stale_lockout":
            if trigger != "reconnect":
                self._skipped(job, trigger, state, "locked")
                return None
            await self._send(job, "RECONNECTED", {})  # recorded; clears nothing (INV-B19-b)
            return None
        pass_id = str(uuid4())
        event = b19.TRIGGER_EVENTS[trigger] if state == "idle" else "SWEEP_DUE"
        payload: dict[str, Any] = {"pass_id": pass_id}
        if event == "SWEEP_DUE":
            payload["trigger"] = trigger
        await self._send(job, event, payload)
        self._pass_ids[job.account] = pass_id
        return pass_id

    def _skipped(self, job: _Job, trigger: Trigger, state: str, why: str) -> None:
        """A trigger that finds a pass running, or the job locked, is logged, never sent (24
        Sec.8.5): no series counts it, as 24 names none."""
        _log().info("reconcile_trigger_skipped", account_id=str(job.account), trigger=trigger,
                    state=state or "none", reason=why)  # fmt: skip

    @staticmethod
    def _resting(job: _Job, state: str) -> bool:
        """B19 rests where a trigger is judged: no service runs and nothing waits to run."""
        return state in _RESTING and quiescent(job.interp)

    def _running_pass(self, job: _Job) -> str:
        known = self._pass_ids.get(job.account)
        running = job.interp.context.get("pass_id")
        return known if known is not None else str(running)

    async def _send(self, job: _Job, event: str, payload: Mapping[str, Any]) -> None:
        """Through the gateway, the only send path (BQ-1), bounded (C-2.18). A refusal is logged
        by the event and the account; `KILL` is a defect and is never sent (BQ-13)."""
        if event == "KILL":
            raise AssertionError("KILL is never sent to B19 (BQ-13)")
        async with asyncio.timeout(SEND_TIMEOUT_S):
            receipt = await self._gateway.send(job.key, {"type": event, **payload}, wait=True)
        if receipt_is_conclusive(receipt) and getattr(receipt, "error", None) is not None:
            _log().error("reconcile_send_refused", account_id=str(job.account), sent=event)

    async def _close(self, job: _Job) -> None:
        """A job drained to rest and persisted, else stopped: a pass fetching or backing off is
        cancelled first (`CANCEL`, to `idle`), any other running pass waited for, bounded."""
        interp = job.interp
        try:
            try:
                if leaf_of(interp) in ("fetching", "backing_off"):
                    await self._send(job, "CANCEL", {})
                await self._quiesced(interp)
            finally:
                self._gateway.unregister(job.key)
            if self._persistence is not None and leaf_of(interp) in b19.REST_STATES:
                await self._persistence.persist(interp, job.machine_key)
                return
        except Exception as exc:  # a faulted job: stopped without a snapshot, the next restores
            _log().error("reconcile_job_persist_failed", account_id=str(job.account),
                         failure=type(exc).__name__)  # fmt: skip
        if interp.is_running:
            await interp.stop()

    async def _quiesced(self, interp: Any) -> None:
        """Until the job rests with nothing to run, looked at again a poll apart, bounded."""
        async with asyncio.timeout(QUIESCE_TIMEOUT_S):
            while True:
                if leaf_of(interp) in b19.REST_STATES and quiescent(interp):
                    return
                await asyncio.sleep(QUIESCE_POLL_S)

    def _spawn(self, coro: Awaitable[None], name: str) -> asyncio.Task[None]:
        task: asyncio.Task[None] = asyncio.ensure_future(coro)
        task.set_name(name)
        self._tasks.add(task)
        task.add_done_callback(self._ended)
        return task

    def _ended(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            _log().error("reconcile_timer_failed", task=task.get_name(),
                         failure=type(error).__name__)  # fmt: skip

    def _gauge(self, read: Callable[[], float]) -> None:
        """`oms_stale_accounts` (20 Sec.12.1): read from the standing at each scrape."""
        spec = next(spec for spec in CATALOGUE if spec.name == _STALE_GAUGE)
        gauge = self._metrics.gauge(spec.name, spec.help, spec.labels, max_series=spec.max_series)
        set_function = getattr(gauge.child(), "set_function", None)
        if set_function is not None:
            set_function(read)

    def _now(self) -> float:
        if self._monotonic is not None:
            return self._monotonic()
        return asyncio.get_running_loop().time()


_UNOPENED: Final = "A reconciliation job could not open: its account's order entry is refused."


class RetryHop:
    """`ReconcilePhases`' `RetryTimer` before the driver exists: the composition builds the phases
    first, as the driver takes them, then binds the driver here. Unbound, a retry is logged at
    ERROR and dropped: the job stays backing off, and the next trigger is skipped while it does,
    so the stale rule still runs on the next fetch a restart or the Owner asks for."""

    def __init__(self) -> None:
        self._driver: ReconcileJobs | None = None

    def bind(self, driver: ReconcileJobs | None) -> None:
        self._driver = driver

    def retry(self, account_id: AccountId, *, attempt: int) -> None:
        if self._driver is None:
            _log().error("reconcile_retry_unbound", account_id=str(account_id))
            return
        self._driver.retry(account_id, attempt=attempt)
