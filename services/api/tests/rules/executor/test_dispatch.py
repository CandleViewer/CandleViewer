"""E35-S03 K1b (#4999): bounded, ordered fire dispatch off the evaluation tick (24 §11.5).

K1a's rig (`test_mode_split.Rig`), its executor sink a `Sink` that logs each action as it goes in
and comes out and holds a gated rule's actions until the test releases them. Fire n's run id is
`UUID(int=n)`, minted in tick order. No sleeps: every wait is on an event, under a guard bound, so
a regression fails rather than hangs. Since E35-T09 a worker hands each fire to the executor, which
records each action's result (`records`) and counts it (`counted`).
"""

from __future__ import annotations

import asyncio
import functools
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, MutableMapping
from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import Any

import pytest
from structlog.testing import capture_logs
from structlog.typing import EventDict

from candleviewer.rules import service as rules_service
from candleviewer.rules.executor import dispatch
from candleviewer.rules.executor.engine import ActionExecutor
from candleviewer.rules.executor.gates import Gates, scope_refusal
from candleviewer.rules.ir.models import Action, RuleScope
from candleviewer.rules.manager import InMemoryRuleStore
from candleviewer.rules.runner import EvalTick
from candleviewer.rules.scope import ActionRequest, ScopeInstanceRef
from candleviewer.rules.service import RulesService
from candleviewer.settings import Settings
from tests.rules.executor.request_builders import (
    Counted,
    Principals,
    Records,
    Switches,
    action_request,
)
from tests.rules.executor.test_mode_split import NOTE, Rig
from tests.rules.test_evaluator import Clock
from tests.rules.test_scope_wiring import OWNER, A, B, Source

GUARD_S = 10.0  # a wait's bound: only a regression reaches it
RULE = str(uuid.UUID(int=7))  # the rule of the fires built without a rig
AUDIT = "audit"  # the gate of the scope gate's audit writes


def _actions(*nodes: str) -> list[dict[str, Any]]:
    return [{"node_id": n, "type": "send_notification", "params": NOTE} for n in nodes]


class Sink:
    """The executor's downstream: logs each action in and out as (way, fire, node); a gated rule's
    actions each wait in it for a `release`, as the scope gate's audit writes do once `AUDIT` is."""

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
        await self.passing(req.rule_id)
        self._note("out", req, self.left)

    async def passing(self, key: str) -> None:
        """Wakes `until`, then waits for a `release` while `key` is gated."""
        self._moved.set()
        if (gate := self._gates.get(key)) is not None:
            await gate.acquire()

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
            await sink.passing(AUDIT)

        async def to_simulation(req: ActionRequest) -> None:
            simulated.append(req)

        store, svc, records, counted = InMemoryRuleStore(), RulesService(), Records(), Counted()
        svc.bind(store=store, action_sink=sink, simulation_sink=to_simulation)
        svc.bind(records=(records, records), metrics=counted.metrics, switches=Switches())
        svc.bind(principal=Principals(frozenset({A, B})))
        svc.wire_scope(source, "demo", audit)
        await svc.refresh_scope(OWNER)
        ctx: Any = SimpleNamespace(settings=SimpleNamespace(rules_evaluator_enabled=True))
        await svc.start(ctx)
        services.append(svc)
        mgr, runner = svc.manager(), svc.runner
        assert mgr is not None and runner is not None
        return DispatchRig(
            svc, mgr, store, runner, clock, sink.entered, simulated, records, counted, sink,
            source, audits,
        )  # fmt: skip

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
    assert rig.counted.blocked() == {"backpressure": 2}  # each of its actions
    refused = {"event": "rules.blocked", "log_level": "warning", "rule_id": rid}
    assert [e for e in logs if e["event"] == "rules.blocked"] == [
        refused | {"run_id": str(uuid.UUID(int=4)), "reason": "backpressure", "actions": 2}
    ]
    rig.sink.release(rid, 6)
    await rig.settle()
    assert sorted({run for _, run, _ in rig.sink.log}) == [1, 2, 3]  # never the newest
    run = uuid.UUID(int=4)  # its records, off the tick (BQ-4): the run row closed `throttled`
    assert rig.records.closed[run] == ("throttled", 0)
    backpressure = [(p["node_id"], p["outcome"], p["blocked_by"], p["account_id"])
                    for r, e in rig.records.events if r == run for p in [e.payload]]  # fmt: skip
    assert backpressure == [(n, "blocked", "backpressure", None) for n in ("a1", "a2")]


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
    """Past its grace `stop()` cancels the workers, mid-action too, and logs the fires it drops:
    the waiting ones counted by rule, each one in flight by its rule and run."""
    rules = [await rig.add("armed"), await rig.add("armed")]
    for rid in rules:
        rig.sink.gate(rid)  # never released: each rule's first fire outlasts the grace in the sink
    for _ in range(2):
        await rig.fire()
    await rig.sink.reached(2)
    with capture_logs() as logs:
        await rig.svc.stop(0.0)
    assert [way for way, _, _ in rig.sink.log] == ["in", "in"]  # cancelled; the second fires wait
    stopped = {"event": "rules.dispatch_stopped", "log_level": "warning", "queue": "rule-dispatch"}
    assert [e for e in logs if e["event"] == "rules.dispatch_stopped"] == [
        stopped | {"dropped": 2, "inflight": 2, "waiting": dict.fromkeys(rules, 1)}
    ]
    cancelled = [e for e in logs if e["event"] == "rules.fire_cancelled"]
    assert sorted((e["rule_id"], e["run_id"]) for e in cancelled) == sorted(
        (r.rule_id, str(r.run_id)) for r in rig.sink.entered
    )
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
        if task is not None and task.get_name().startswith("rule-dispatch"):  # either queue's
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
    assert rig.counted.blocked() == {"backpressure": 3}
    assert [e["run_id"] for e in logs if e["event"] == "rules.blocked"] == [
        str(uuid.UUID(int=n)) for n in (3, 6)
    ]  # the rule's first refusal of each episode; the rest are counted only


async def test_a_refusal_is_flagged_first_once_per_rule_and_episode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`refused` is told whether a refusal is its rule's first of the episode (logged on the
    tick), so every other rule's first is logged too, and the rest only counted."""
    monkeypatch.setattr(dispatch, "FIRE_QUEUE_BOUND", 1)
    flags: list[tuple[str, bool]] = []
    fires = dispatch.FireDispatch(
        lambda fire, first: flags.append((fire.rule_id, first)), _never_executed
    )
    other = str(uuid.UUID(int=8))
    for rule in (RULE, RULE, RULE, other, RULE):  # the first waits: no worker is started
        fires.offer(_fire(1, "a1", emit=_never_run, rule=rule))
    assert flags == [(RULE, True), (RULE, False), (other, True), (RULE, False)]


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


async def test_scope_skipped_audits_do_not_take_fire_slots(
    start: Start, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A scope-skipped evaluation's audit-only jobs wait on a queue of their own: with it full,
    an armed fire of another rule is still accepted."""
    monkeypatch.setattr(dispatch, "FIRE_QUEUE_BOUND", 1)
    monkeypatch.setattr(dispatch, "AUDIT_QUEUE_BOUND", 1)
    rig = await start()
    await rig.add("armed", accounts=(B,))  # skipped `scope` once the grant on B is withdrawn
    healthy = await rig.add("armed")
    rig.source.grants = [(A, True, False)]
    rig.sink.gate(AUDIT)  # an audit write never returns
    for n in (1, 2, 3):  # an audit-only job each: job 1 is held in its write, 2 waits, 3 is shed
        await rig.fire()
        await rig.sink.reached(n)  # and a fire of `healthy`, accepted
        await rig.sink.until(lambda: len(rig.audits) == 1)
    assert [r.rule_id for r in rig.sink.left] == [healthy] * 3 and rig.audit_queue.queued == 1
    assert rig.counted.blocked() == {"scope": 3}  # each counted as it is offered (BQ-5)
    assert rig.counted.shed() == {"scope_denial": 1}
    rig.sink.release(AUDIT, 2)
    await rig.settle()


async def test_a_shed_scope_audit_is_counted_under_scope(
    start: Start, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A full audit queue sheds the newest job: its actions were counted `scope` as it was
    offered, never `backpressure`, and the job is counted shed under its kind; its rule's first
    shed of the episode is logged, and nothing pages."""
    monkeypatch.setattr(dispatch, "AUDIT_QUEUE_BOUND", 1)
    rig = await start()
    rid = await rig.add("armed", actions=_actions("a1", "a2"))
    rig.source.grants = [(B, True, False)]  # the grant on the rule's account is withdrawn
    rig.sink.gate(AUDIT)
    await rig.fire()
    await rig.sink.until(lambda: len(rig.audits) == 1)  # job 1 is held in its first audit write
    with capture_logs() as logs:
        for _ in range(3):
            await rig.fire()  # job 2 waits; jobs 3 and 4 are shed
    assert rig.counted.blocked() == {"scope": 8} and rig.counted.shed() == {"scope_denial": 2}
    shed = {"event": "rules.records_shed", "log_level": "warning", "rule_id": rid}
    assert [e for e in logs if e["event"] == "rules.records_shed"] == [
        shed | {"run_id": str(uuid.UUID(int=3)), "actions": 2, "kind": "scope_denial"}
    ]
    assert _pages(logs) == 0
    rig.sink.release(AUDIT, 4)
    await rig.settle()
    assert len(rig.audits) == 4  # jobs 1 and 2, each action audited


async def test_a_healthy_instance_fires_while_a_denied_instances_audit_is_held(
    rig: DispatchRig,
) -> None:
    """One rule on two accounts, the grant on one withdrawn: that instance's audit-only job, held
    in its audit write, is on a lane of its own and never holds the other instance's fires."""
    await rig.add("armed", accounts=(A, B))
    rig.source.grants = [(A, True, False)]  # B's instance is skipped `scope` at every tick
    rig.sink.gate(AUDIT)  # its audit write never returns
    for _ in range(5):
        await rig.fire()
    await rig.sink.until(lambda: len(rig.sink.left) == 5)
    assert {r.instance.account_id for r in rig.sink.left} == {A}
    rig.sink.release(AUDIT, 5)
    await rig.settle()


async def test_stop_drains_every_lane_not_only_the_first_to_empty(
    rig: DispatchRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`stop()` waits for every lane: the first to empty does not end the drain."""
    held, free = await rig.add("armed"), await rig.add("armed")
    rig.sink.gate(held)
    await rig.fire()  # both fire; the held rule's action waits in the sink
    await rig.sink.until(lambda: [r.rule_id for r in rig.sink.left] == [free])  # its lane is gone
    draining, stop = asyncio.Event(), rig.dispatch.stop

    async def drain(grace_s: float) -> None:
        draining.set()
        await stop(grace_s)

    monkeypatch.setattr(rig.dispatch, "stop", drain)
    stopping = asyncio.create_task(rig.svc.stop(GUARD_S))
    async with asyncio.timeout(GUARD_S):
        await draining.wait()  # the drain has begun with the held rule's lane still there
    rig.sink.release(held)
    await stopping
    assert [r.rule_id for r in rig.sink.left] == [free, held]  # it ran, never cancelled


async def test_a_clean_stop_pages_nothing(rig: DispatchRig) -> None:
    """A stop that drains in time ends both queues' workers with nothing logged above info."""
    await rig.add("armed")
    await rig.fire()
    await rig.settle()
    with capture_logs() as logs:
        await rig.svc.stop(GUARD_S)
    assert [e for e in logs if e["log_level"] not in ("debug", "info")] == []


async def _noted(
    order: list[str], name: str, stop: Callable[..., Awaitable[None]], *args: float
) -> None:
    order.append(name)
    await stop(*args)


async def test_stop_stops_the_runner_before_the_dispatch(
    rig: DispatchRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The runner stops first, so no fire is offered once the queues drain."""
    order: list[str] = []
    parts: dict[str, Any] = {"runner": rig.runner, "fires": rig.dispatch, "audits": rig.audit_queue}
    for name, part in parts.items():
        monkeypatch.setattr(part, "stop", functools.partial(_noted, order, name, part.stop))
    await rig.svc.stop(GUARD_S)
    assert order[0] == "runner" and sorted(order[1:]) == ["audits", "fires"]


async def test_an_evaluation_that_does_not_fire_enqueues_nothing(rig: DispatchRig) -> None:
    """Neither fired nor skipped `scope`: nothing is offered to either queue."""
    await rig.add("armed")
    await rig.fire(price="50")  # under the threshold: the condition is false
    assert rig.dispatch.queued == 0 and rig.audit_queue.queued == 0


async def test_the_workers_take_the_lanes_in_turn(
    start: Start, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One worker, two rules with three fires each: the lanes take turns, a fire at a time."""
    monkeypatch.setattr(dispatch, "DISPATCH_WORKERS", 1)
    rig = await start()
    rules = [await rig.add("armed"), await rig.add("armed")]
    for rid in rules:
        rig.sink.gate(rid)  # held until all six are queued, whenever the one worker starts
    for _ in range(3):
        await rig.fire()
    for rid in rules:
        rig.sink.release(rid, 3)
    await rig.settle()
    assert [run for way, run, _ in rig.sink.log if way == "in"] == [1, 2, 3, 4, 5, 6]


async def test_no_dispatch_runs_while_the_evaluator_is_off() -> None:
    """The rollout gate (BQ-17): with the evaluator off, as by default, no fire queue is built."""
    svc = RulesService()
    ctx: Any = SimpleNamespace(settings=Settings())
    await svc.start(ctx)
    try:
        assert svc.runner is None and svc._dispatch is None and _dispatch_tasks() == []
    finally:
        await svc.stop(1.0)


async def test_a_fire_hands_its_run_rows_facts_to_the_records(rig: DispatchRig) -> None:
    """A fire carries its run row's facts from the tick (24 §11.5, 21 §3.4.3): the active version
    it was evaluated under, the `trigger_reason` its trigger maps to and the metric values its
    conditions saw, a decimal as its plain text."""
    rid = await rig.add("armed")
    row = await rig.row(rid)
    row.versions[0].ir["trigger"] = {"type": "on_order_fill"}  # a trigger whose reason is not tick
    await rig.fire(price="150.50", trigger="on_order_fill")
    await rig.settle()
    (run,) = rig.records.runs.values()
    assert (run.rule_id, run.version_id, run.mode) == (rid, row.active_version_id, "armed")
    assert (run.trigger_reason, dict(run.input_snapshot)) == ("fill", {"price": "150.5"})


async def test_the_recheck_before_a_retry_runs_check_one_then_the_scope_recheck(
    rig: DispatchRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The service's two hooks the executor asks again before `retry_once`'s retry, check 1 first
    (24 §11.9; E35-T10 runs checks 1 to 8 again in the executor): check 1, `_check_one`, finds a
    row no longer armed or on another `ir_hash` (`mode_changed`), or unread; check 4,
    `_scope_check`, answers the resolver's reason, read as `scope` with no resolver or a grant
    withdrawn since; else neither refuses."""
    rid = await rig.add("armed")
    row = await rig.row(rid)
    scope = RuleScope.model_validate(
        {"level": "account", "account_ids": [str(A)], "symbols": ["BTCUSDT"]}
    )
    req = action_request(
        scope, OWNER, ScopeInstanceRef(f"BTCUSDT@{A}", "BTCUSDT", A), rule_id=rid,
        version=row.versions[0].version, ir_hash=row.versions[0].ir_hash,
    )  # fmt: skip
    check_one, scope_check = rig.svc._check_one, rig.svc._scope_check
    resolver = rig.svc.scope_resolver
    assert await check_one(req) == "armed" and scope_check(req) is None
    rig.svc.scope_resolver = None
    refused = scope_check(req)  # no resolver: nothing passes the scope re-check
    assert refused is not None and scope_refusal(refused) == "scope"
    rig.svc.scope_resolver = resolver
    rig.source.grants = [(B, True, False)]  # the grant on A is withdrawn
    await rig.svc.refresh_scope(OWNER)
    refused = scope_check(req)
    assert refused is not None and scope_refusal(refused) == "scope"
    assert await check_one(replace(req, ir_hash="f" * 64)) == "mode_changed"
    row.mode = "disabled"
    assert await check_one(req) == "mode_changed"
    row.mode = "armed"

    async def unreadable(_rule_id: str) -> Any:
        raise ConnectionError("the rule store is unreachable")

    monkeypatch.setattr(rig.store, "get", unreadable)
    assert await check_one(req) == "unread"  # the executor skips the rest as `mode_changed`
    assert rig.counted.reread() == {"store_error": 1}


def _fire(
    run: int, *nodes: str, emit: Callable[[ActionRequest], Awaitable[object]], rule: str = RULE
) -> dispatch.Fire:
    scope = RuleScope(level="account")
    reqs = tuple(
        action_request(
            scope, OWNER, ScopeInstanceRef("*@*", None, None), run_id=uuid.UUID(int=run),
            action_type="send_notification",
            payload=Action(node_id=n, type="send_notification", params=NOTE),
        )
        for n in nodes
    )  # fmt: skip
    return dispatch.Fire(rule, uuid.UUID(int=run), reqs, emit)


def _never_refused(fire: dispatch.Fire, first: bool) -> None:
    raise AssertionError("no fire is refused here")


async def _never_executed(fire: dispatch.Fire) -> None:
    raise AssertionError("no fire is executed here")


async def _never_run(_req: ActionRequest) -> bool:
    raise AssertionError("no worker runs here")


@pytest.mark.parametrize("failure", ["timeout", "error"])
async def test_a_failed_action_stops_its_fire_and_the_worker_goes_on(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """Every action is bounded: one that outlasts `ACTION_TIMEOUT_S` (0 s here) or raises is
    recorded `failed`, the rest of its fire `skipped` (`abort_remaining`), logged by its class
    alone, and the next fire still runs (the K1b carry: `failed_total` became results)."""
    monkeypatch.setattr(dispatch, "ACTION_TIMEOUT_S", 0.0)
    seen: list[tuple[int, str]] = []
    records = Records()

    async def armed(_req: ActionRequest) -> Any:
        return "armed"

    async def passes(_req: ActionRequest) -> None:
        return None

    executor = ActionExecutor(
        check_one=armed, scope_check=lambda _req: None,
        gates=Gates(switches=Switches(), principal=Principals()), records=records, audit=records,
        stand_in=passes,
    )  # fmt: skip

    async def emit(req: ActionRequest) -> None:
        seen.append((req.run_id.int, req.payload.node_id))
        if seen == [(1, "a1")]:
            if failure == "timeout":
                await asyncio.Event().wait()  # never answers: only the bound ends it
            raise RuntimeError("the emitter failed")
        await executor.hand_over(req)  # `emit_checked`: None once the action went on

    fires = dispatch.FireDispatch(_never_refused, executor.execute)
    fires.start()
    with capture_logs() as logs:
        assert fires.offer(_fire(1, "a1", "a2", emit=emit))
        assert fires.offer(_fire(2, "a1", emit=emit))
        async with asyncio.timeout(GUARD_S):
            await fires.idle()
    await fires.stop(0.0)
    assert seen == [(1, "a1"), (2, "a1")]  # fire 1's a2 never ran; fire 2 did
    assert records.results() == [
        ("a1", "failed", None),
        ("a2", "skipped", None),
        ("a1", "ok", None),
    ]
    assert records.events[0][1].payload["error_code"] == failure
    kind = "TimeoutError" if failure == "timeout" else "RuntimeError"
    failed = {"event": "rules.action_failed", "log_level": "error", "queue": "rule-dispatch"}
    assert [e for e in logs if e["event"] == "rules.action_failed"] == [
        failed | {"rule_id": RULE, "run_id": str(uuid.UUID(int=1)), "node_id": "a1",
                  "reason": failure, "kind": kind}
    ]  # fmt: skip


async def test_workers_that_end_without_stop_page_at_once() -> None:
    """Only `stop()` ends the workers: any other end leaves the queued fires with no one to run
    them, so it pages at once, by the error's class alone."""

    async def emit(_req: ActionRequest) -> bool:
        return True

    fires = dispatch.FireDispatch(_never_refused, _never_executed)
    fires.offer(_fire(1, "a1", emit=emit))
    fires._lanes.clear()  # a broken invariant: the worker that takes the rule finds no lane
    with capture_logs() as logs:
        fires.start()
        async with asyncio.timeout(GUARD_S):
            await asyncio.wait(_dispatch_tasks())
    ended = {"event": "rules.dispatch_ended", "log_level": "critical", "cv_page": True}
    assert [e for e in logs if e["event"] == "rules.dispatch_ended"] == [
        ended | {"queue": "rule-dispatch", "error": "ExceptionGroup"}
    ]
    assert not [e for e in logs if e["event"] == "rules.dispatch_worker_lost"]  # group's cancels
    await fires.stop(0.0)


async def test_past_its_grace_stop_starts_no_waiting_fire(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fires still waiting leave their lanes and the turn before the stop line: a fire that
    ends in the pass after it, before its worker's cancel lands, starts none of them, its own
    rule's or another's, and `dropped` counts the fires that never start (#5231's carry RC-01)."""
    monkeypatch.setattr(dispatch, "DISPATCH_WORKERS", 1)
    entered, ended, started = asyncio.Event(), asyncio.Event(), list[int]()
    other = str(uuid.UUID(int=8))

    async def execute(fire: dispatch.Fire) -> None:
        started.append(fire.run_id.int)
        entered.set()
        await ended.wait()

    def end_on_the_stop_line(_logger: Any, _method: str, event: EventDict) -> EventDict:
        if event["event"] == "rules.dispatch_stopped":
            ended.set()  # fire 1 ends in the next pass, before the cancel reaches its worker
        return event

    fires = dispatch.FireDispatch(_never_refused, execute)
    fires.start()
    assert fires.offer(_fire(1, "a1", emit=_never_run))
    assert fires.offer(_fire(2, "a1", emit=_never_run))  # waits in the lane, behind fire 1
    assert fires.offer(_fire(3, "a1", emit=_never_run, rule=other))  # its lane waits its turn
    async with asyncio.timeout(GUARD_S):
        await entered.wait()
    (worker,) = [t for t in _dispatch_tasks() if "-worker-" in t.get_name()]
    with capture_logs(processors=[end_on_the_stop_line]) as logs:
        await fires.stop(0.0)
    assert started == [1] and fires.queued == 0
    stopped = [e for e in logs if e["event"] == "rules.dispatch_stopped"]
    assert [(e["dropped"], e["inflight"], e["waiting"]) for e in stopped] == [
        (2, 1, {RULE: 1, other: 1})
    ]
    assert worker.cancelled() and _dispatch_tasks() == []


async def test_a_stop_cancelled_mid_drain_ends_the_audit_queue_too(
    rig: DispatchRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cancel during the fire queue's drain goes on to the caller, and the audit queue's
    workers end with it, at once, its held job cut: no `rule-dispatch*` task outlives the module
    (#5231's carry RC-02)."""
    held = await rig.add("armed")
    await rig.add("armed", accounts=(B,))  # skipped `scope` once the grant on B is withdrawn
    rig.source.grants = [(A, True, False)]
    rig.sink.gate(held)  # its fire's action waits in the sink, so the drain waits for it
    rig.sink.gate(AUDIT)  # the other rule's audit write never returns
    await rig.fire()
    await rig.sink.reached(1)
    await rig.sink.until(lambda: len(rig.audits) == 1)
    draining, stop = asyncio.Event(), rig.dispatch.stop

    async def drain(grace_s: float) -> None:
        draining.set()
        await stop(grace_s)

    monkeypatch.setattr(rig.dispatch, "stop", drain)
    with capture_logs() as logs:
        stopping = asyncio.create_task(rig.svc.stop(GUARD_S))
        async with asyncio.timeout(GUARD_S):
            await draining.wait()
        stopping.cancel()
        with pytest.raises(asyncio.CancelledError):
            async with asyncio.timeout(GUARD_S / 2):  # well inside the grace left: at once
                await stopping
    assert _dispatch_tasks() == [] and rig.svc._audits is None
    stopped = [e["queue"] for e in logs if e["event"] == "rules.dispatch_stopped"]
    assert stopped == ["rule-dispatch-audit"]  # its held job cut; the fire queue's drain cancelled


async def test_the_audit_queue_drains_in_what_the_fire_queue_left_of_the_grace(
    rig: DispatchRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One grace for the module, counted from the start of `stop()`: the runner's stop takes its
    share of it, the fire queue drains in what is left, and the audit queue in what that leaves,
    never in a grace of its own (#5231's carry RC-02)."""
    now, graces = [1_000.0], list[tuple[str, float]]()
    monkeypatch.setattr(rules_service, "monotonic", lambda: now[0])
    runner_stop, fires_stop, audits_stop = rig.runner.stop, rig.dispatch.stop, rig.audit_queue.stop

    async def runner() -> None:
        now[0] += 2.0  # the runner's stop takes 2 s of the 10
        await runner_stop()

    async def fires(grace_s: float) -> None:
        graces.append(("fires", grace_s))
        now[0] += 3.0  # the fire queue's drain takes 3 s more
        await fires_stop(grace_s)

    async def audits(grace_s: float) -> None:
        graces.append(("audits", grace_s))
        await audits_stop(grace_s)

    monkeypatch.setattr(rig.runner, "stop", runner)
    monkeypatch.setattr(rig.dispatch, "stop", fires)
    monkeypatch.setattr(rig.audit_queue, "stop", audits)
    await rig.svc.stop(10.0)
    assert graces == [("fires", 8.0), ("audits", 5.0)]  # 10 less the runner's 2, then 3 more


async def test_a_stop_cancelled_while_the_runner_ends_goes_on_to_the_caller(
    rig: DispatchRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cancel aimed at `stop()`'s caller while the runner's task is still ending goes on to the
    caller, never absorbed by the runner's stop, and ends both queues' workers at once too: no
    `rule-dispatch*` task outlives the module (#5231's carry, the runner's
    `suppress(CancelledError)`, under RC-02's rule)."""
    reading, ending, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    every = rig.store.all

    async def read_all() -> Any:
        task = asyncio.current_task()
        if task is not None and task.get_name() == "rule-runner":
            reading.set()
            try:
                await asyncio.Event().wait()  # the tick's read, which the runner's stop cancels
            finally:
                ending.set()
                await release.wait()  # the runner's task ends only once released
        return await every()

    monkeypatch.setattr(rig.store, "all", read_all)
    runner = rig.runner._task
    rig.runner.submit(EvalTick("on_price_update", "BTCUSDT"))
    async with asyncio.timeout(GUARD_S):
        await reading.wait()
    stopping = asyncio.create_task(rig.svc.stop(GUARD_S))
    async with asyncio.timeout(GUARD_S):
        await ending.wait()  # the runner's task has its cancel and has not ended
    stopping.cancel()
    with pytest.raises(asyncio.CancelledError):
        async with asyncio.timeout(GUARD_S / 2):
            await stopping
    assert _dispatch_tasks() == [] and rig.svc._audits is None
    release.set()
    assert runner is not None
    async with asyncio.timeout(GUARD_S):
        await asyncio.wait({runner})
    assert runner.cancelled()


async def test_a_raise_execute_lets_through_is_logged_by_its_class_and_queue() -> None:
    """A raise `execute` lets through is a defect: logged by its class and its queue, never its
    text (C-12.6; #5231's carry RC-03), and the worker goes on with the next job."""

    async def broken(fire: dispatch.Fire) -> None:
        raise RuntimeError("the executor failed 64123.5")

    audits = dispatch.AuditDispatch(_never_refused, broken)
    audits.start()
    with capture_logs() as logs:
        for run in (1, 2):
            assert audits.offer(replace(_fire(run, "a1", emit=_never_run), kind="scope_denial"))
        async with asyncio.timeout(GUARD_S):
            await audits.idle()
    await audits.stop(0.0)
    failed = {"event": "rules.fire_failed", "log_level": "error", "queue": "rule-dispatch-audit"}
    assert [e for e in logs if e["event"] == "rules.fire_failed"] == [
        failed | {"rule_id": RULE, "run_id": str(uuid.UUID(int=run)), "kind": "RuntimeError"}
        for run in (1, 2)
    ]
    assert "64123.5" not in repr(logs)


async def test_every_worker_ends_cancelled_at_stop_idle_ones_too(rig: DispatchRig) -> None:
    """`stop()` cancels each worker of both queues and each re-raises it, an idle one too: none
    ends as if it had finished (#5231's carry RC-05)."""
    await rig.add("armed")
    await rig.fire()
    await rig.settle()  # every worker idle again
    workers = [t for t in _dispatch_tasks() if "-worker-" in t.get_name()]
    assert len(workers) == dispatch.DISPATCH_WORKERS + dispatch.AUDIT_WORKERS
    await rig.svc.stop(GUARD_S)
    assert [t.get_name() for t in workers if not t.cancelled()] == []


class _Held:
    """`execute` that logs each fire it runs and holds a fire of a `held` rule until released."""

    def __init__(self, *held: str) -> None:
        self.ran: list[tuple[str, int]] = []
        self.held = {rule: asyncio.Event() for rule in held}
        self.running = asyncio.Event()

    async def __call__(self, fire: dispatch.Fire) -> None:
        self.ran.append((fire.rule_id, fire.run_id.int))
        if (gate := self.held.get(fire.rule_id)) is not None:
            self.running.set()
            await gate.wait()


async def _idle(fires: dispatch.FireDispatch) -> None:
    async with asyncio.timeout(GUARD_S):
        await fires.idle()


async def _none(_req: ActionRequest) -> None:
    return None


async def test_drop_takes_a_rules_waiting_fires_and_nothing_else() -> None:
    """E35-T10 (24 §11.7): `drop` takes the rule's waiting fires out of its lane, oldest first, and
    leaves the fire that runs and every other rule's lane; dropping a rule with nothing waiting
    takes nothing."""
    other = str(uuid.UUID(int=9))
    held = _Held(RULE)
    fires = dispatch.FireDispatch(_never_refused, held)
    fires.start()
    for fire in (_fire(1, "a1", emit=_none), _fire(2, "a1", emit=_none),
                 _fire(3, "a1", emit=_none), _fire(4, "b1", emit=_none, rule=other)):  # fmt: skip
        assert fires.offer(fire)
    async with asyncio.timeout(GUARD_S):
        await held.running.wait()  # fire 1 runs; 2 and 3 wait in its rule's lane
    dropped = fires.drop(RULE)
    assert [f.run_id.int for f in dropped] == [2, 3] and fires.drop(RULE) == ()
    assert fires.drop("no-such-rule") == ()
    held.held[RULE].set()
    await _idle(fires)
    await fires.stop(0.0)
    assert sorted(held.ran) == sorted([(RULE, 1), (other, 4)])  # nothing dropped ever ran
    assert fires.queued == 0


async def test_a_dropped_lane_never_stalls_the_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    """A lane emptied while it waits its turn keeps it: the worker that meets it skips it, the
    queue still runs empty (`idle`), and the rule's next fire runs in a lane of its own."""
    monkeypatch.setattr(dispatch, "DISPATCH_WORKERS", 1)
    other = str(uuid.UUID(int=9))
    held = _Held(other)
    fires = dispatch.FireDispatch(_never_refused, held)
    fires.start()
    assert fires.offer(_fire(1, "b1", emit=_none, rule=other))
    async with asyncio.timeout(GUARD_S):
        await held.running.wait()  # the one worker is held: the rule's lane waits in the turn
    assert fires.offer(_fire(2, "a1", emit=_none))
    assert [f.run_id.int for f in fires.drop(RULE)] == [2]
    held.held[other].set()
    await _idle(fires)  # the emptied lane was skipped, never stalled
    assert fires.offer(_fire(3, "a1", emit=_none))
    await _idle(fires)
    await fires.stop(0.0)
    assert held.ran == [(other, 1), (RULE, 3)]
