"""Bounded, ordered dispatch of rule fires, off the evaluation tick (E35-S03; 24 §11.5).

The tick only offers (C-2.20): one fire per evaluation, synchronously and never awaited. A fixed
set of workers runs the fires; what each action does is the fire's `emit`, which the caller picks.
"""

from __future__ import annotations

import asyncio
from collections import Counter, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Final, Literal
from uuid import UUID

import structlog

from candleviewer.observability import spawn, spawn_child
from candleviewer.rules.scope import ActionRequest

#: The fires that may wait, all rules together, before the newest is refused (C-2.18).
FIRE_QUEUE_BOUND: Final = 1024
#: The fixed set of dispatch workers: at most this many rules dispatch at once.
DISPATCH_WORKERS: Final = 4
#: One action's whole hand-over (the scope re-check's audit, the re-read, the sink), above the
#: re-read's own 2 s bound.
ACTION_TIMEOUT_S: Final = 10.0
#: Why an action stopped its fire: `timeout`, no return within `ACTION_TIMEOUT_S`; `error`, it
#: raised.
DispatchFailure = Literal["timeout", "error"]


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Fire:
    """One evaluation's actions on their way to dispatch, in IR order, and the emit each goes
    through. The caller picks it (`RulesService._on_fire`: the routing emitter for a fired result,
    the audit-only one for a scope-skipped one); a worker never chooses where an action goes."""

    rule_id: str
    run_id: UUID
    requests: tuple[ActionRequest, ...]
    emit: Callable[[ActionRequest], Awaitable[object]]


class FireDispatch:
    """The fire queue and its workers (24 §11.5 "The fire queue").

    **Bound and overflow (C-2.18).** At most `FIRE_QUEUE_BOUND` fires wait, all rules together.
    `offer` refuses a fire past it: the newest, never one already waiting. `refused` records it
    (each of its actions `blocked`, `backpressure`) and the first refusal of an episode pages; the
    episode ends when the queue next runs empty. No fire is dropped silently, and `offer` never
    awaits (C-2.20).

    **Order.** Striped by rule id: a rule's fires wait in its own lane, in the order offered, and
    one worker at a time holds a lane, so they run in fire order. The workers take the lanes in
    turn, so a rule whose sink is slow holds one worker and never another rule's lane. A fire's
    actions run one after another, in IR order (E5), each bounded by `ACTION_TIMEOUT_S`.

    **Tasks.** The workers belong to one `TaskGroup` under a supervisor task this owns; `stop()`
    drains them within its grace, then cancels them. A cancel is never swallowed."""

    def __init__(self, refused: Callable[[Fire], None]) -> None:
        self._refused = refused
        self._bound = FIRE_QUEUE_BOUND
        self._lanes: dict[str, deque[Fire]] = {}  # per rule with a fire waiting or running
        #: The lanes with a fire waiting and no worker: one per waiting fire at most, never full.
        self._ready: asyncio.Queue[str] = asyncio.Queue(maxsize=self._bound)
        self._queued = 0
        self._idle = asyncio.Event()
        self._idle.set()
        self._backlogged = False
        self._supervisor: asyncio.Task[None] | None = None
        #: The actions that stopped their fire, by `DispatchFailure`, until E35-T09 records each
        #: as an `ActionResult` (`unknown` after a timeout, `failed` otherwise).
        self.failed_total: Counter[DispatchFailure] = Counter()

    @property
    def queued(self) -> int:
        """The fires waiting for a worker."""
        return self._queued

    def start(self) -> None:
        if self._supervisor is None:
            self._supervisor = spawn(self._supervise(), name="rule-dispatch")
            self._supervisor.add_done_callback(self._ended)

    def offer(self, fire: Fire) -> bool:
        """On the tick, never awaited: `fire` waits behind its rule's earlier fires, or is refused
        when `FIRE_QUEUE_BOUND` fires wait already."""
        if self._queued >= self._bound:
            self._refused(fire)
            if not self._backlogged:
                self._backlogged = True
                _log().critical("rules.dispatch_backpressure", cv_page=True)
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

    async def stop(self, grace_s: float) -> None:
        """Drain within `grace_s` seconds, then end the workers. Past the grace they are cancelled,
        mid-action too, and the fires still waiting are dropped, counted in one log line (a restart
        loses queued fires by design). Call it once the tick has stopped offering."""
        supervisor, self._supervisor = self._supervisor, None
        if supervisor is None:
            return
        try:
            async with asyncio.timeout(grace_s):
                await self._idle.wait()
        except TimeoutError:
            _log().warning("rules.dispatch_stopped", dropped=self._queued)
        finally:
            supervisor.cancel()
            await asyncio.wait({supervisor})

    def _ended(self, task: asyncio.Task[None]) -> None:
        """Only `stop()` ends the workers, and it lets go of the supervisor first: any other end
        leaves the queued fires with no worker, so it pages at once, by the error's class alone
        (C-12.6). The error is retrieved either way."""
        error = None if task.cancelled() else task.exception()
        if task is self._supervisor:
            name = None if error is None else type(error).__name__
            _log().critical("rules.dispatch_ended", cv_page=True, error=name)

    async def _supervise(self) -> None:
        async with asyncio.TaskGroup() as group:
            for _ in range(DISPATCH_WORKERS):
                spawn_child(group, self._work(), name="rule-dispatch-worker")

    async def _work(self) -> None:
        """The next lane in turn, its oldest fire, then the lane back in the turn, behind the
        others, while it has fires waiting."""
        while True:
            rule_id = await self._ready.get()
            lane = self._lanes[rule_id]
            fire = lane.popleft()
            self._queued -= 1
            if self._queued == 0:
                self._backlogged = False  # the queue ran empty: the next refusal pages again
            try:
                await self._run(fire)
            finally:  # a cancel too: the lane stays whole
                if lane:
                    self._ready.put_nowait(rule_id)
                else:
                    del self._lanes[rule_id]
                    if not self._lanes:
                        self._idle.set()

    async def _run(self, fire: Fire) -> None:
        """The fire's actions strictly one after another, in IR order (E5): the next starts once
        the one before has returned. One that raises or outlasts `ACTION_TIMEOUT_S` stops the fire,
        as `abort_remaining` (24 §11.5's default) does until E35-T09's `on_error`; it is counted and
        logged by its class alone (C-12.6), and the worker goes on with the next fire."""
        for done, req in enumerate(fire.requests):
            try:
                async with asyncio.timeout(ACTION_TIMEOUT_S):
                    await fire.emit(req)
            except Exception as exc:  # never `CancelledError`, which is no `Exception`
                failure: DispatchFailure = "timeout" if isinstance(exc, TimeoutError) else "error"
                self.failed_total[failure] += 1
                _log().error(
                    "rules.action_failed", rule_id=fire.rule_id, run_id=str(fire.run_id),
                    node_id=req.payload.node_id, reason=failure, kind=type(exc).__name__,
                    not_run=len(fire.requests) - done - 1,
                )  # fmt: skip
                return
