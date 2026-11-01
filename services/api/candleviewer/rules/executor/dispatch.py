"""Bounded, ordered dispatch of rule fires, off the evaluation tick (E35-S03; 24 §11.5).

The tick only offers (C-2.20): one fire per evaluation, synchronously and never awaited. A fixed
set of workers hands each fire, whole, to the executor (`rules/executor/engine.py`), which runs its
actions one after another in IR order; what each action passes through is the fire's `emit`, the
emitter the caller picks.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Literal
from uuid import UUID

import structlog

from candleviewer.observability import spawn, spawn_child
from candleviewer.rules.evaluator.snapshot import Value
from candleviewer.rules.executor.results import BlockedBy
from candleviewer.rules.ir.models import RuleLimits
from candleviewer.rules.scope import ActionRequest

#: The fires that may wait, all rules together, before the newest is refused (C-2.18).
FIRE_QUEUE_BOUND: Final = 1024
#: The fixed set of dispatch workers: at most this many rules dispatch at once.
DISPATCH_WORKERS: Final = 4
#: The audit-only jobs that may wait on `AuditDispatch`'s own queue, and its workers.
AUDIT_QUEUE_BOUND: Final = 256
AUDIT_WORKERS: Final = 1
#: One action's whole step (its re-read, its scope re-check and audit, its records written ahead
#: and its hand-over), above the re-read's and each write's own 2 s bound.
ACTION_TIMEOUT_S: Final = 10.0
#: A job's kind (BQ-4): a fire; a fire the full fire queue refused, whose records go on the audit
#: queue; or a scope-skipped evaluation's audits. A shed job is counted under its kind.
JobKind = Literal["fire", "refused_fire", "scope_denial"]


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Fire:
    """One evaluation's actions on their way to dispatch, in IR order, and the emit each goes
    through. The caller picks it (`RulesService._on_fire`: the routing emitter for a fired result,
    the audit-only one for a scope-skipped one); a worker never chooses where an action goes. A
    fire carries its run row's facts (24 §11.5, 21 §3.4.3): the active version it was evaluated
    under, its trigger type and the metric values its conditions saw, never logged; and (E35-T10)
    when it was offered, on the service's monotonic clock, which a trip time or a kill time is
    compared with at dispatch (one with none counts as offered before either), the rule's limits
    and, for a record-only job of a fire refused whole, the `blocked_by` its records name."""

    rule_id: str
    run_id: UUID
    requests: tuple[ActionRequest, ...]
    emit: Callable[[ActionRequest], Awaitable[object]]
    kind: JobKind = "fire"
    version_id: str | None = None
    trigger_type: str = ""
    metric_values: Mapping[str, Value] = field(default_factory=dict, repr=False)
    offered_at: float = float("-inf")
    limits: RuleLimits = field(default_factory=RuleLimits)
    refused_by: BlockedBy = "backpressure"

    @property
    def armed(self) -> bool:
        """Its actions carry the stored row's mode, one for the whole fire."""
        return bool(self.requests) and self.requests[0].mode == "armed"

    @property
    def queue(self) -> str:
        """The queue the job rides, which a line about it names (#5231's carry RC-03): a fire
        the fire queue, a record-only job the audit queue."""
        return FireDispatch._name if self.kind == "fire" else AuditDispatch._name


#: Records a refused fire on the tick; `first` for its rule's first refusal of the episode.
Refused = Callable[[Fire, bool], None]
#: Runs one job whole, in a worker (`ActionExecutor.execute`).
Execute = Callable[[Fire], Awaitable[None]]


class FireDispatch:
    """The fire queue and its workers (24 §11.5 "The fire queue").

    **Bound and overflow (C-2.18).** At most `FIRE_QUEUE_BOUND` fires wait, all rules together.
    `offer` refuses a fire past it: the newest, never one already waiting. `refused` records it
    (each of its actions `blocked`, `backpressure`), told whether it is its rule's first refusal
    of the episode, and the episode's first refusal pages; the episode ends when the queue next
    runs empty. No fire is dropped silently, and `offer` never awaits (C-2.20).

    **Order.** Striped by rule id: a rule's fires wait in its own lane, in the order offered, and
    one worker at a time holds a lane, so they run in fire order. The workers take the lanes in
    turn, so a rule whose sink is slow holds one worker and never another rule's lane. A worker
    hands each fire, whole, to `execute`, which runs its actions one after another, in IR order
    (E5), each bounded by `ACTION_TIMEOUT_S`.

    **Tasks.** The workers belong to one `TaskGroup` under a supervisor task this owns; `stop()`
    drains them within its grace, then cancels them. A cancel is never swallowed: a worker logs
    the fire it cut short and, for a cancel neither `stop()` nor its group issued, its own loss."""

    _name = "rule-dispatch"  # the supervisor task's; worker n's is `<name>-worker-<n>`
    _pages = True  # the episode's first refusal pages

    def __init__(self, refused: Refused, execute: Execute) -> None:
        self._refused, self._execute = refused, execute
        self._bound, self._workers = self._sizes()
        self._lanes: dict[str, deque[Fire]] = {}  # per rule with a fire waiting or running
        #: The lanes with a fire waiting and no worker: one per waiting fire at most, never full.
        self._ready: asyncio.Queue[str] = asyncio.Queue(maxsize=self._bound)
        self._queued = 0
        self._idle = asyncio.Event()
        self._idle.set()
        self._blocked: set[str] = set()  # the rules refused this episode, one entry each
        self._running: dict[str, Fire] = {}  # by worker name, the fire it runs
        self._supervisor: asyncio.Task[None] | None = None

    @staticmethod
    def _sizes() -> tuple[int, int]:
        """The bound and the worker count, read as the queue is built."""
        return FIRE_QUEUE_BOUND, DISPATCH_WORKERS

    @property
    def queued(self) -> int:
        """The fires waiting for a worker."""
        return self._queued

    def start(self) -> None:
        if self._supervisor is None:
            self._supervisor = spawn(self._supervise(), name=self._name)
            self._supervisor.add_done_callback(self._ended)

    def offer(self, fire: Fire) -> bool:
        """On the tick, never awaited: `fire` waits behind its rule's earlier fires, or is refused
        when the queue is full."""
        if self._queued >= self._bound:
            if self._pages and not self._blocked:
                _log().critical("rules.dispatch_backpressure", cv_page=True)
            first = fire.rule_id not in self._blocked
            self._blocked.add(fire.rule_id)
            self._refused(fire, first)
            return False
        lane = self._lanes.get(fire.rule_id)
        if lane is None:  # nothing of the rule waits or runs: its lane joins the turn
            lane = self._lanes[fire.rule_id] = deque()
            self._ready.put_nowait(fire.rule_id)
            self._idle.clear()
        lane.append(fire)
        self._queued += 1
        return True

    async def idle(self) -> None:
        """Until no fire waits or runs."""
        await self._idle.wait()

    def drop(self, rule_id: str) -> tuple[Fire, ...]:
        """Take `rule_id`'s waiting fires out of its lane and return them, oldest first; never the
        fire a worker runs, nor another rule's lane (E35-T10: the circuit breaker and the
        kill-switch hook). Synchronous, so nothing is offered to the lane meanwhile; an emptied
        lane keeps its turn, and the worker that meets it skips it."""
        lane = self._lanes.get(rule_id)
        if not lane:
            return ()
        dropped = tuple(lane)
        lane.clear()
        self._queued -= len(dropped)
        if self._queued == 0:
            self._blocked.clear()  # the queue ran empty: the next refusal starts an episode
        return dropped

    async def stop(self, grace_s: float) -> None:
        """Drain within `grace_s` seconds, then end the workers. Past the grace they are cancelled,
        mid-action too, and the fires still waiting are dropped (a restart loses queued fires by
        design), taken out before the line that counts them, by rule too, beside the fires in
        flight, so none starts after it; each worker logs the fire it held as it is cancelled.
        Call it once the tick has stopped offering."""
        supervisor, self._supervisor = self._supervisor, None
        if supervisor is None:
            return
        try:
            async with asyncio.timeout(grace_s):
                await self._idle.wait()
        except TimeoutError:
            waiting = {rule_id: len(lane) for rule_id, lane in self._lanes.items() if lane}
            dropped = self._drop_waiting()  # before the line: none it counts starts after it
            _log().warning(
                "rules.dispatch_stopped", queue=self._name, dropped=dropped,
                inflight=len(self._running), waiting=waiting,
            )  # fmt: skip
        finally:
            supervisor.cancel()
            await asyncio.wait({supervisor})

    def _drop_waiting(self) -> int:
        """Every waiting fire out of its lane, and the turn emptied, so a worker whose fire ends
        before its cancel lands starts no other (#5231's carry RC-01); the worker lets its own
        lane go. How many fires it dropped."""
        while not self._ready.empty():
            self._ready.get_nowait()
        for lane in self._lanes.values():
            lane.clear()
        dropped, self._queued = self._queued, 0
        return dropped

    def _ended(self, task: asyncio.Task[None]) -> None:
        """Only `stop()` ends the workers, and it lets go of the supervisor first: any other end
        leaves the queued fires with no worker, so it pages at once, by the error's class alone
        (C-12.6). The error is retrieved either way."""
        error = None if task.cancelled() else task.exception()
        if task is self._supervisor:
            name = None if error is None else type(error).__name__
            _log().critical("rules.dispatch_ended", cv_page=True, queue=self._name, error=name)

    async def _supervise(self) -> None:
        async with asyncio.TaskGroup() as group:
            for n in range(self._workers):
                name = f"{self._name}-worker-{n}"
                spawn_child(group, self._worker(name), name=name)

    async def _worker(self, name: str) -> None:
        """`_work` until cancelled. A cancel is logged, then re-raised: the fire it cuts short, by
        its ids, and, for a cancel neither `stop()` nor the group issued, the worker's loss."""
        try:
            await self._work(name)
        except asyncio.CancelledError:
            if (fire := self._running.pop(name, None)) is not None:
                _log().warning(
                    "rules.fire_cancelled", worker=name, rule_id=fire.rule_id,
                    run_id=str(fire.run_id),
                )  # fmt: skip
            if self._supervisor is not None and not self._supervisor.cancelling():
                _log().error("rules.dispatch_worker_lost", worker=name)  # the pool has one fewer
            raise

    async def _work(self, name: str) -> None:
        """The next lane in turn, its oldest fire, then the lane back in the turn, behind the
        others, while it has fires waiting."""
        while True:
            rule_id = await self._ready.get()
            lane = self._lanes[rule_id]
            if not lane:  # `drop` emptied it while it waited its turn: no worker holds it
                del self._lanes[rule_id]
                if not self._lanes:
                    self._idle.set()
                continue
            fire = self._running[name] = lane.popleft()
            self._queued -= 1
            if self._queued == 0:
                self._blocked.clear()  # the queue ran empty: the next refusal starts an episode
            try:
                await self._run(fire)
            finally:  # a cancel too: the lane stays whole
                if lane:
                    self._ready.put_nowait(rule_id)
                else:
                    del self._lanes[rule_id]
                    if not self._lanes:
                        self._idle.set()
            del self._running[name]

    async def _run(self, fire: Fire) -> None:
        """The fire, whole, through `execute`, which records each action's result and bounds each
        action. A raise it lets through is a defect: logged by its class alone (C-12.6) and its
        queue, and the worker goes on with the next fire."""
        try:
            await self._execute(fire)
        except Exception as exc:  # never `CancelledError`, which is no `Exception`
            _log().error(
                "rules.fire_failed", queue=self._name, rule_id=fire.rule_id,
                run_id=str(fire.run_id), kind=type(exc).__name__,
            )  # fmt: skip


class AuditDispatch(FireDispatch):
    """The record-only jobs, on a queue, lanes and a worker of their own, so none takes a fire's
    slot, lane or worker (BQ-4): a scope-skipped evaluation's audits (the tick's scope gate refused
    its actions, so none is a fire), and a refused fire's run row and per-action records.

    **Bound and overflow (C-2.18).** At most `AUDIT_QUEUE_BOUND` jobs wait, all rules together,
    for `AUDIT_WORKERS` worker. Past the bound the newest is shed, never awaited and never one
    already waiting: `refused` counts it under its kind (`rule_records_shed_total{kind}`) and logs
    its rule's first of the episode. It pages nothing: no fire is refused."""

    _name = "rule-dispatch-audit"
    _pages = False

    @staticmethod
    def _sizes() -> tuple[int, int]:
        return AUDIT_QUEUE_BOUND, AUDIT_WORKERS
