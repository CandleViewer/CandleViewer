"""E35-S03 K1b (#4999): bounded, ordered fire dispatch off the evaluation tick (24 §11.5).

K1a's rig (`test_mode_split.Rig`), its executor sink a `Sink` that logs each action as it goes in
and comes out and holds a gated rule's actions until the test releases them. Fire n's run id is
`UUID(int=n)`, minted in tick order. No sleeps: every wait is on an event, under a guard bound, so
a regression fails rather than hangs.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, MutableMapping
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.rules import service as rules_service
from candleviewer.rules.executor import dispatch
from candleviewer.rules.ir.models import Action, RuleScope
from candleviewer.rules.manager import InMemoryRuleStore
from candleviewer.rules.scope import ActionRequest, ScopeInstanceRef
from candleviewer.rules.service import RulesService
from candleviewer.settings import Settings
from tests.rules.executor.request_builders import action_request
from tests.rules.executor.test_mode_split import NOTE, Rig
from tests.rules.test_evaluator import Clock
from tests.rules.test_scope_wiring import OWNER, B, Source

GUARD_S = 2.0  # a wait's bound: only a regression reaches it
RULE = str(uuid.UUID(int=7))  # the rule of the fires built without a rig


def _actions(*nodes: str) -> list[dict[str, Any]]:
    return [{"node_id": n, "type": "send_notification", "params": NOTE} for n in nodes]


class Sink:
    """The executor's downstream: logs each action in and out as (way, fire, node); a gated rule's
    actions each wait in it for a `release`."""

    def __init__(self) -> None:
        self.log: list[tuple[str, int, str]] = []
        self.entered: list[ActionRequest] = []
        self.left: list[ActionRequest] = []
        self._gates: dict[str, asyncio.Semaphore] = {}
        self._moved = asyncio.Event()

    def gate(self, rule_id: str) -> None:
        self._gates[rule_id] = asyncio.Semaphore(0)

    def release(self, rule_id: str, n: int = 1) -> None:
        for _ in range(n):
            self._gates[rule_id].release()

    async def __call__(self, req: ActionRequest) -> None:
        self._note("in", req, self.entered)
        gate = self._gates.get(req.rule_id)
        if gate is not None:
            await gate.acquire()
        self._note("out", req, self.left)

    def _note(self, way: str, req: ActionRequest, into: list[ActionRequest]) -> None:
        into.append(req)
        self.log.append((way, req.run_id.int, req.payload.node_id))
        self._moved.set()

    async def until(self, met: Callable[[], bool]) -> None:
        async with asyncio.timeout(GUARD_S):
            while not met():
                self._moved.clear()
                await self._moved.wait()

    async def reached(self, n: int) -> None:
        """Until `n` actions have gone in."""
        await self.until(lambda: len(self.entered) >= n)


@dataclass
class DispatchRig(Rig):
    sink: Sink
    source: Source
    audits: list[tuple[str, dict[str, str]]]


Start = Callable[[], Awaitable[DispatchRig]]


@pytest.fixture
async def start(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Start]:
    """Builds and starts a rig when called, so a test can set the queue's bound first."""
    clock = Clock()
    monkeypatch.setattr(rules_service, "default_clocks", lambda: (clock, clock))
    runs = iter(range(1, 10_000))
    monkeypatch.setattr(rules_service, "uuid4", lambda: uuid.UUID(int=next(runs)))
    services: list[RulesService] = []

    async def build() -> DispatchRig:
        sink, source = Sink(), Source()
        audits: list[tuple[str, dict[str, str]]] = []
        simulated: list[ActionRequest] = []

        async def audit(event: str, data: dict[str, str]) -> None:
            audits.append((event, data))

        async def to_simulation(req: ActionRequest) -> None:
            simulated.append(req)

        store, svc = InMemoryRuleStore(), RulesService()
        svc.bind(store=store, action_sink=sink, simulation_sink=to_simulation)
        svc.wire_scope(source, "demo", audit)
        await svc.refresh_scope(OWNER)
        ctx: Any = SimpleNamespace(settings=SimpleNamespace(rules_evaluator_enabled=True))
        await svc.start(ctx)
        services.append(svc)
        mgr, runner = svc.manager(), svc.runner
        assert mgr is not None and runner is not None
        return DispatchRig(
            svc, mgr, store, runner, clock, sink.entered, simulated, sink, source, audits
        )

    yield build
    for svc in services:
        await svc.stop(1.0)


@pytest.fixture
async def rig(start: Start) -> DispatchRig:
    return await start()


def _dispatch_tasks() -> list[asyncio.Task[Any]]:
    return [t for t in asyncio.all_tasks() if t.get_name().startswith("rule-dispatch")]


def _pages(logs: list[MutableMapping[str, Any]]) -> int:
    page = {"event": "rules.dispatch_backpressure", "log_level": "critical", "cv_page": True}
    return sum(1 for e in logs if e == page)


async def test_actions_of_one_fire_dispatch_in_ir_order(rig: DispatchRig) -> None:
    """Scenario: Fires and actions dispatch in order: one fire's actions strictly in IR order."""
    rid = await rig.add("armed", actions=_actions("a1", "a2", "a3"))
    rig.sink.gate(rid)
    await rig.fire()
    for n in (1, 2, 3):
        await rig.sink.reached(n)  # the next action goes in only once the one before is out
        rig.sink.release(rid)
    await rig.settle()
    assert rig.sink.log == [(way, 1, a) for a in ("a1", "a2", "a3") for way in ("in", "out")]


async def test_two_fires_of_one_rule_dispatch_in_fire_order(rig: DispatchRig) -> None:
    """Scenario: Fires and actions dispatch in order: an earlier fire of the rule goes first."""
    rid = await rig.add("armed")
    rig.sink.gate(rid)
    for _ in range(3):
        await rig.fire()  # three fires of one rule, queued before any worker runs
    await rig.sink.reached(1)
    assert rig.dispatch.queued == 2  # the later two wait behind the first, which is in the sink
    rig.sink.release(rid, 3)
    await rig.settle()
    assert rig.sink.log == [(way, run, "a1") for run in (1, 2, 3) for way in ("in", "out")]


async def test_a_full_dispatch_queue_refuses_the_newest_fire_and_records_it(
    start: Start, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scenario: A full dispatch queue refuses the newest fire (failure case)."""
    monkeypatch.setattr(dispatch, "FIRE_QUEUE_BOUND", 2)
    rig = await start()
    rid = await rig.add("armed", actions=_actions("a1", "a2"))
    rig.sink.gate(rid)
    await rig.fire()
    await rig.sink.reached(1)  # fire 1 is in the sink, so no longer waiting
    with capture_logs() as logs:
        for _ in range(3):
            await rig.fire()  # fires 2 and 3 wait; fire 4 finds the queue full
    assert dict(rig.svc.actions_blocked_total) == {"backpressure": 2}  # each of its actions
    refused = {"event": "rules.blocked", "log_level": "warning", "rule_id": rid}
    assert [e for e in logs if e["event"] == "rules.blocked"] == [
        refused | {"run_id": str(uuid.UUID(int=4)), "reason": "backpressure", "actions": 2}
    ]
    rig.sink.release(rid, 6)
    await rig.settle()
    assert sorted({run for _, run, _ in rig.sink.log}) == [1, 2, 3]  # never the newest


async def test_the_evaluation_tick_never_awaits_dispatch(rig: DispatchRig) -> None:
    """Scenario: The evaluation tick never waits for dispatch (edge case): a blocked sink."""
    rid = await rig.add("armed")
    rig.sink.gate(rid)  # the executor's sink blocks
    await rig.fire()
    await rig.sink.reached(1)
    async with asyncio.timeout(GUARD_S):  # a tick that waited on the sink would never end
        await rig.fire()
        await rig.fire()
    assert rig.dispatch.queued == 2 and rig.sink.log == [("in", 1, "a1")]
    rig.sink.release(rid, 3)
    await rig.settle()


async def test_stop_drains_dispatch_workers_within_grace(rig: DispatchRig) -> None:
    """Scenario: The evaluation tick never waits for dispatch: stop() drains the workers."""
    rid = await rig.add("armed")
    rig.sink.gate(rid)
    for _ in range(3):
        await rig.fire()
    await rig.sink.reached(1)
    stopping = asyncio.create_task(rig.svc.stop(GUARD_S))  # each fire is released well within
    for n in (2, 3):
        rig.sink.release(rid)
        await rig.sink.reached(n)
        assert not stopping.done()  # the queued fires run before the workers end
    rig.sink.release(rid)
    await stopping
    assert rig.sink.log == [(way, run, "a1") for run in (1, 2, 3) for way in ("in", "out")]
    assert rig.svc._dispatch is None and _dispatch_tasks() == []


async def test_stop_past_its_grace_cancels_the_workers_and_logs_what_it_drops(
    rig: DispatchRig,
) -> None:
    """Past its grace `stop()` cancels the workers, mid-action too, and logs the fires it drops."""
    rid = await rig.add("armed")
    rig.sink.gate(rid)  # never released: fire 1 outlasts the grace in the sink
    for _ in range(2):
        await rig.fire()
    await rig.sink.reached(1)
    with capture_logs() as logs:
        await rig.svc.stop(0.0)
    assert rig.sink.log == [("in", 1, "a1")]  # cancelled in the sink, fire 2 never taken
    stopped = {"event": "rules.dispatch_stopped", "log_level": "warning", "dropped": 1}
    assert [e for e in logs if e["event"] == "rules.dispatch_stopped"] == [stopped]
    assert _dispatch_tasks() == []


async def test_a_scope_skipped_fire_is_audited_per_action_and_never_dispatched(
    rig: DispatchRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scenario: A scope-skipped fire is audited and never dispatched. Then the emitter's re-check
    is made to pass in the dispatch worker: the structure alone keeps the actions from a sink."""
    rid = await rig.add("armed", actions=_actions("a1", "a2"))
    rig.source.grants = [(B, True, False)]  # the grant on the rule's account is withdrawn
    await rig.fire()  # the evaluator's scope gate skips the evaluation as `scope`
    await rig.settle()
    denied = ("rule_action_scope_denied", "grant_revoked", "send_notification")
    assert [(e, d["reason"], d["action"]) for e, d in rig.audits] == [denied, denied]
    resolver = rig.svc.scope_resolver
    assert resolver is not None
    gate = resolver.check_action
    passed: list[str] = []

    def lenient(*args: Any, **kwargs: Any) -> Any:
        task = asyncio.current_task()
        if task is not None and task.get_name() == "rule-dispatch-worker":
            passed.append(rid)
            return None  # the re-check passes: only the tick's gate still refuses
        return gate(*args, **kwargs)

    monkeypatch.setattr(resolver, "check_action", lenient)
    await rig.fire()
    await rig.settle()
    assert passed == [rid, rid] and len(rig.audits) == 2  # re-checked per action, nothing denied
    assert rig.sink.entered == [] and rig.simulated == []


async def test_overflow_pages_once_per_episode(
    start: Start, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first refusal pages; the episode lasts until the queue next runs empty."""
    monkeypatch.setattr(dispatch, "FIRE_QUEUE_BOUND", 1)
    rig = await start()
    rid = await rig.add("armed")
    rig.sink.gate(rid)
    with capture_logs() as logs:
        await rig.fire()
        await rig.sink.reached(1)
        for _ in range(3):
            await rig.fire()  # fire 2 waits; fires 3 and 4 are refused
        assert _pages(logs) == 1
        rig.sink.release(rid)
        await rig.sink.reached(2)  # fire 2 is taken: the queue ran empty, the episode is over
        for _ in range(2):
            await rig.fire()  # fire 5 waits; fire 6 is refused: a new episode
        assert _pages(logs) == 2
    rig.sink.release(rid, 2)
    await rig.settle()
    assert dict(rig.svc.actions_blocked_total) == {"backpressure": 3}


async def test_fires_of_different_rules_do_not_wait_on_each_other(rig: DispatchRig) -> None:
    """A rule whose sink is slow holds one worker: another rule's fire dispatches meanwhile."""
    slow = await rig.add("armed")
    rig.sink.gate(slow)
    await rig.fire()
    await rig.sink.reached(1)  # the slow rule's fire is held in the sink
    other = await rig.add("armed")
    await rig.fire()  # both fire: the slow rule's second fire waits in its own lane
    await rig.sink.until(lambda: len(rig.sink.left) == 1)
    assert [r.rule_id for r in rig.sink.left] == [other]
    rig.sink.release(slow, 2)
    await rig.settle()


async def test_no_dispatch_runs_while_the_evaluator_is_off() -> None:
    """The rollout gate (BQ-17): with the evaluator off, as by default, no fire queue is built."""
    svc = RulesService()
    ctx: Any = SimpleNamespace(settings=Settings())
    await svc.start(ctx)
    try:
        assert svc.runner is None and svc._dispatch is None and _dispatch_tasks() == []
    finally:
        await svc.stop(1.0)


def _fire(run: int, *nodes: str, emit: Callable[[ActionRequest], Awaitable[bool]]) -> dispatch.Fire:
    scope = RuleScope(level="account")
    reqs = tuple(
        action_request(
            scope, OWNER, ScopeInstanceRef("*@*", None, None), run_id=uuid.UUID(int=run),
            payload=Action(node_id=n, type="send_notification", params=NOTE),
        )
        for n in nodes
    )  # fmt: skip
    return dispatch.Fire(RULE, uuid.UUID(int=run), reqs, emit)


def _never_refused(fire: dispatch.Fire) -> None:
    raise AssertionError("no fire is refused here")


@pytest.mark.parametrize("failure", ["timeout", "error"])
async def test_a_failed_action_stops_its_fire_and_the_worker_goes_on(
    monkeypatch: pytest.MonkeyPatch, failure: dispatch.DispatchFailure
) -> None:
    """Every sink await is bounded: an action that outlasts `ACTION_TIMEOUT_S` (0 s here) or
    raises stops the rest of its fire, is counted and logged by its class alone, and the next fire
    still runs."""
    monkeypatch.setattr(dispatch, "ACTION_TIMEOUT_S", 0.0)
    seen: list[tuple[int, str]] = []

    async def emit(req: ActionRequest) -> bool:
        seen.append((req.run_id.int, req.payload.node_id))
        if seen == [(1, "a1")]:
            if failure == "timeout":
                await asyncio.Event().wait()  # never answers: only the bound ends it
            raise RuntimeError("the sink failed")
        return True

    fires = dispatch.FireDispatch(_never_refused)
    fires.start()
    with capture_logs() as logs:
        assert fires.offer(_fire(1, "a1", "a2", emit=emit))
        assert fires.offer(_fire(2, "a1", emit=emit))
        async with asyncio.timeout(GUARD_S):
            await fires.idle()
    await fires.stop(0.0)
    assert seen == [(1, "a1"), (2, "a1")]  # fire 1's a2 never ran; fire 2 did
    assert dict(fires.failed_total) == {failure: 1}
    kind = "TimeoutError" if failure == "timeout" else "RuntimeError"
    failed = {"event": "rules.action_failed", "log_level": "error", "rule_id": RULE}
    assert [e for e in logs if e["event"] == "rules.action_failed"] == [
        failed | {"run_id": str(uuid.UUID(int=1)), "node_id": "a1", "reason": failure,
                  "kind": kind, "not_run": 1}
    ]  # fmt: skip


async def test_workers_that_end_without_stop_page_at_once() -> None:
    """Only `stop()` ends the workers: any other end leaves the queued fires with no one to run
    them, so it pages at once, by the error's class alone."""

    async def emit(_req: ActionRequest) -> bool:
        return True

    fires = dispatch.FireDispatch(_never_refused)
    fires.offer(_fire(1, "a1", emit=emit))
    fires._lanes.clear()  # a broken invariant: the worker that takes the rule finds no lane
    with capture_logs() as logs:
        fires.start()
        async with asyncio.timeout(GUARD_S):
            await asyncio.wait(_dispatch_tasks())
    ended = {"event": "rules.dispatch_ended", "log_level": "critical", "cv_page": True}
    assert [e for e in logs if e["event"] == "rules.dispatch_ended"] == [
        ended | {"error": "ExceptionGroup"}
    ]
    await fires.stop(0.0)
