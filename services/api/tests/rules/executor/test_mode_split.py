"""E35-S03 K1a (#4999): a fire is routed by the stored row's mode, and read again at dispatch.

24 §11.5: the IR's own `mode` is never read for routing (BQ-12). The rig is a `RulesService` over an
in-memory store, the evaluator on and the clocks frozen: `executor` is the sink an OMS would sit
behind (E35-T09 to E35-T12), `simulated` the simulation sink. The evaluator stays off by default:
`test_evaluator_wiring.py::test_evaluator_not_constructed_when_flag_off` pins it.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, get_args

import pytest
from structlog.testing import capture_logs

from candleviewer.observability.health import HealthStatus
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.rules import service as rules_service
from candleviewer.rules.evaluator.engine import EvaluationResult
from candleviewer.rules.ir.models import MetricRef, RuleScope
from candleviewer.rules.manager import (
    Actor,
    InMemoryRuleStore,
    RuleRow,
    RulesManager,
    StoredMode,
)
from candleviewer.rules.runner import EvalTick, RuleEvaluationRunner
from candleviewer.rules.scope import ActionRequest, ScopeInstanceRef
from candleviewer.rules.service import RereadFailure, RulesService
from tests.rules.executor.request_builders import action_request
from tests.rules.test_evaluator import Clock
from tests.rules.test_scope_wiring import OWNER, Source
from tests.rules.test_scope_wiring import A as ACCOUNT

ACTOR = Actor(str(OWNER), "s1", frozenset({"rules:arm_live"}), is_owner=True, step_up_fresh=True)
FIXTURE = Path(__file__).parents[2] / "fixtures/rule_ir/form_simple_0.json"
PRICE = MetricRef.model_validate({"metric": "price", "params": {"n": 14}})
NOTE: dict[str, Any] = {"channel": "ui", "severity": "info", "template": "x"}
ONE_ACTION: tuple[dict[str, Any], ...] = (
    {"node_id": "a1", "type": "send_notification", "params": NOTE},
)


@dataclass
class Rig:
    svc: RulesService
    mgr: RulesManager
    store: InMemoryRuleStore
    runner: RuleEvaluationRunner
    clock: Clock
    executor: list[ActionRequest]
    simulated: list[ActionRequest]

    async def row(self, rid: str) -> RuleRow:
        row = await self.store.get(rid)
        assert row is not None
        return row

    async def add(
        self,
        mode: str,
        *,
        ir_mode: str = "simulate",
        actions: Sequence[dict[str, Any]] = ONE_ACTION,
    ) -> str:
        """A rule on ACCOUNT whose stored row is in `mode` while its stored IR says `ir_mode`."""
        raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
        raw["name"] = f"rule-{len(await self.store.all())}"
        raw["conditions"]["right"]["const"] = 100
        raw["actions"] = [dict(a) for a in actions]
        raw["scope"] = {"level": "account", "account_ids": [str(ACCOUNT)], "symbols": ["BTCUSDT"]}
        rid = str((await self.mgr.create(raw, ACTOR))["id"])
        row = await self.row(rid)
        row.mode, row.armed_by = mode, (str(OWNER) if mode == "armed" else None)
        row.versions[0].ir["mode"] = ir_mode
        return rid

    async def fire(self, price: str = "150") -> None:
        """One tick: the rules evaluate and their actions are scheduled, not yet run."""
        self.clock.t += 2_000  # past the default cooldown
        assert self.svc.metric_source is not None
        self.svc.metric_source.push(PRICE, Decimal(price), self.clock.t)
        await self.runner.process(EvalTick("on_price_update", "BTCUSDT"))

    async def settle(self) -> None:
        await asyncio.gather(*self.svc._tasks)


@pytest.fixture
async def rig(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Rig]:
    clock = Clock()
    monkeypatch.setattr(rules_service, "default_clocks", lambda: (clock, clock))
    executor: list[ActionRequest] = []
    simulated: list[ActionRequest] = []

    async def to_executor(req: ActionRequest) -> None:
        executor.append(req)

    async def to_simulation(req: ActionRequest) -> None:
        simulated.append(req)

    async def audit(event: str, data: dict[str, str]) -> None:
        return None

    store = InMemoryRuleStore()
    svc = RulesService()
    svc.bind(store=store, action_sink=to_executor, simulation_sink=to_simulation)
    svc.wire_scope(Source(), "demo", audit)
    await svc.refresh_scope(OWNER)
    ctx: Any = SimpleNamespace(settings=SimpleNamespace(rules_evaluator_enabled=True))
    await svc.start(ctx)  # the module reads only `settings.rules_evaluator_enabled`
    mgr, runner = svc.manager(), svc.runner
    assert mgr is not None and runner is not None
    try:
        yield Rig(svc, mgr, store, runner, clock, executor, simulated)
    finally:
        await svc.stop(1.0)


async def test_a_simulate_rule_never_reaches_the_oms_sink(rig: Rig) -> None:
    """Scenario: a simulate rule never reaches the OMS sink (failure case)."""
    rid = await rig.add("simulate", ir_mode="armed")  # the stored row says simulate, its IR armed
    await rig.fire()
    await rig.settle()
    assert rig.executor == []
    assert [(r.rule_id, r.mode) for r in rig.simulated] == [(rid, "simulate")]
    assert not rig.svc.actions_blocked_total  # a simulate action is never an armed fire dropped
    assert (await rig.row(rid)).simulation_fires == 1  # and the evaluation is still recorded


async def test_a_rule_switched_to_simulate_after_arming_emits_to_the_simulated_sink_only(
    rig: Rig,
) -> None:
    rid = await rig.add("armed")
    await rig.fire()
    await rig.settle()
    assert [r.mode for r in rig.executor] == ["armed"] and rig.simulated == []
    row = await rig.row(rid)
    row.mode = "simulate"  # switched after arming, while the rule's evaluator is still cached
    await rig.fire()
    await rig.settle()
    assert len(rig.executor) == 1  # the second fire never reached it
    assert [(r.mode, r.armed_by) for r in rig.simulated] == [("simulate", None)]
    assert rig.simulated[0].run_id != rig.executor[0].run_id  # a fire of its own


async def test_an_armed_rules_result_reaches_the_executor_sink(rig: Rig) -> None:
    rid = await rig.add("armed")
    await rig.fire()
    await rig.settle()
    (req,) = rig.executor
    version = (await rig.row(rid)).versions[0]
    stored = (req.mode, req.rule_id, req.version, req.ir_hash, req.armed_by)
    assert stored == ("armed", rid, 1, version.ir_hash, str(OWNER))
    assert (req.action_type, req.payload.node_id, req.owner) == ("send_notification", "a1", OWNER)
    assert (req.environment, req.instance.key) == ("demo", f"BTCUSDT@{ACCOUNT}")
    assert isinstance(req.run_id, uuid.UUID)
    assert rig.simulated == []


@pytest.mark.parametrize("target", ["simulate", "disabled"])
async def test_a_mode_change_between_evaluation_and_dispatch_is_honoured_at_dispatch(
    rig: Rig, target: str
) -> None:
    """Scenario: a mode change between evaluation and dispatch is honoured (edge case)."""
    rid = await rig.add("armed")
    await rig.fire()  # evaluated as armed: its action's task is scheduled and has not run
    assert rig.svc._tasks and rig.executor == []
    (await rig.row(rid)).mode = target  # the stored row is switched before dispatch
    await rig.settle()
    assert rig.executor == [] and rig.simulated == []  # dropped: it reached neither sink
    assert dict(rig.svc.actions_blocked_total) == {"mode_changed": 1}


def _new_active_version(row: RuleRow) -> None:
    row.versions.append(dataclasses.replace(row.versions[0], id="v2", version=2))
    row.active_version_id = "v2"


def _new_content_at_the_same_version(row: RuleRow) -> None:
    row.versions[0] = dataclasses.replace(row.versions[0], ir_hash="f" * 64)


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(_new_active_version, id="new_active_version"),
        pytest.param(_new_content_at_the_same_version, id="new_ir_hash_same_version"),
        pytest.param(lambda row: setattr(row, "active_version_id", "v9"), id="no_stored_version"),
        pytest.param(lambda row: setattr(row, "deleted", True), id="deleted"),
    ],
)
async def test_a_changed_row_between_evaluation_and_dispatch_drops_the_fire(
    rig: Rig, change: Callable[[RuleRow], None]
) -> None:
    """The row is armed still, but no longer the rule the fire was evaluated for."""
    rid = await rig.add("armed")
    await rig.fire()
    change(await rig.row(rid))
    await rig.settle()
    assert rig.executor == [] and rig.simulated == []
    assert dict(rig.svc.actions_blocked_total) == {"mode_changed": 1}


async def test_an_action_in_flight_when_the_service_stops_drops(rig: Rig) -> None:
    """A stopped service has no manager to read the row with: the action drops as `mode_changed`.
    (`stop()` runs a queued action before it clears the manager; K1b's workers reach this arm.)"""
    await rig.add("armed")
    await rig.fire()
    manager, rig.svc._manager = rig.svc._manager, None
    await rig.settle()
    rig.svc._manager = manager  # for the fixture's `stop()`
    assert rig.executor == [] and rig.simulated == []
    assert dict(rig.svc.actions_blocked_total) == {"mode_changed": 1}


def _fail_the_dispatch_read(
    monkeypatch: pytest.MonkeyPatch,
    store: InMemoryRuleStore,
    failure: Callable[[], Awaitable[None]],
) -> None:
    """The store's point read runs `failure` first inside the task that emits an action, the
    dispatch's re-read; the evaluation's own recording, a task of its own, reads as usual."""
    read = store.get

    async def get(rule_id: str) -> RuleRow | None:
        task = asyncio.current_task()
        if task is not None and task.get_name() == "rule-action-emit":
            await failure()
        return await read(rule_id)

    monkeypatch.setattr(store, "get", get)


async def _store_down() -> None:
    raise ConnectionError("the rule store is unreachable")


async def _store_stalled() -> None:
    """Never answers: only the read's bound ends it (0 s here, at its first wait)."""
    await asyncio.Event().wait()


@pytest.mark.parametrize(
    ("failure", "bound", "reason"),
    [(_store_down, 2.0, "store_error"), (_store_stalled, 0.0, "timeout")],
)
async def test_a_failed_reread_at_dispatch_sends_nothing_and_is_counted(
    rig: Rig,
    monkeypatch: pytest.MonkeyPatch,
    failure: Callable[[], Awaitable[None]],
    bound: float,
    reason: RereadFailure,
) -> None:
    """Fail closed (24 §11.5 check 1): the action reaches neither sink and is counted under its
    reason, logged once with the rule id and that reason only; nothing raises out of its task."""
    rid = await rig.add("armed")
    await rig.fire()  # evaluated as armed: its action's task is scheduled and has not run
    _fail_the_dispatch_read(monkeypatch, rig.store, failure)
    monkeypatch.setattr(rules_service, "REREAD_TIMEOUT_S", bound)
    with capture_logs() as logs:
        await rig.settle()
    assert rig.executor == [] and rig.simulated == []
    assert dict(rig.svc.dispatch_reread_failed_total) == {reason: 1}
    assert not rig.svc.actions_blocked_total  # 24 §11.9 has no `blocked_by` for it yet (K2)
    skipped = {"event": "rules.action_skipped", "log_level": "warning"}
    assert [e for e in logs if e.get("rule_id") == rid] == [
        skipped | {"rule_id": rid, "reason": reason}
    ]


async def test_a_cancelled_reread_is_never_swallowed(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancellation is no failed read: the emit task ends cancelled, nothing sent or counted."""
    await rig.add("armed")
    await rig.fire()

    async def cancelled_mid_read() -> None:
        task = asyncio.current_task()
        assert task is not None
        task.cancel()  # delivered at the read's next wait, as any cancel of the task is
        await asyncio.Event().wait()

    _fail_the_dispatch_read(monkeypatch, rig.store, cancelled_mid_read)
    (emit,) = [t for t in rig.svc._tasks if t.get_name() == "rule-action-emit"]
    await asyncio.gather(*rig.svc._tasks, return_exceptions=True)
    assert emit.cancelled()
    assert rig.executor == [] and rig.simulated == []
    assert not rig.svc.dispatch_reread_failed_total and not rig.svc.actions_blocked_total


def test_the_reread_failure_counter_is_catalogued_with_its_closed_reasons() -> None:
    (spec,) = [s for s in CATALOGUE if s.name == "rule_dispatch_reread_failed_total"]
    assert (spec.kind, spec.labels, spec.status) == ("counter", ("reason",), "planned")
    assert spec.max_series == len(get_args(RereadFailure)) == 2


@pytest.mark.parametrize(
    ("stored", "ir_mode"),
    [("simulate", "armed"), ("simulate", "disabled"), ("armed", "simulate"), ("armed", "disabled")],
)
async def test_the_ir_mode_field_is_never_read_for_routing(
    rig: Rig, stored: str, ir_mode: str
) -> None:
    """Whatever the stored IR says, the stored row's mode decides where the fire goes (BQ-12)."""
    await rig.add(stored, ir_mode=ir_mode)
    await rig.fire()
    await rig.settle()
    both = (rig.executor, rig.simulated)
    reached, other = both if stored == "armed" else both[::-1]
    assert [r.mode for r in reached] == [stored]
    assert other == []


def test_action_request_has_no_default_mode() -> None:
    """`mode` is required (BQ-12), as is the rest of the fire's identity (24 §11.9)."""
    req = action_request(RuleScope(level="account"), OWNER, ScopeInstanceRef("*@*", None, None))
    fields = {f.name: getattr(req, f.name) for f in dataclasses.fields(req)}
    for name in ("mode", "rule_id", "version", "ir_hash", "run_id", "armed_by"):
        with pytest.raises(TypeError, match=name):
            ActionRequest(**{k: v for k, v in fields.items() if k != name})


async def test_dry_run_only_action_is_recorded_as_simulated_in_an_armed_rule(rig: Rig) -> None:
    """Scenario: a dry-run action in an armed rule is simulated."""
    dry = {"node_id": "a1", "type": "send_notification", "params": NOTE, "dry_run_only": True}
    live = {"node_id": "a2", "type": "send_notification", "params": NOTE}
    await rig.add("armed", actions=[dry, live])
    await rig.fire()
    await rig.settle()
    assert [r.payload.node_id for r in rig.simulated] == ["a1"]
    assert [r.payload.node_id for r in rig.executor] == ["a2"]
    assert {r.mode for r in rig.simulated + rig.executor} == {"armed"}
    assert len({r.run_id for r in rig.simulated + rig.executor}) == 1  # one fire, one run id


async def test_an_evaluation_that_does_not_fire_emits_no_action(rig: Rig) -> None:
    await rig.add("armed")
    await rig.fire(price="50")
    await rig.settle()
    assert rig.executor == [] and rig.simulated == []


async def test_a_rule_without_an_owner_emits_no_action(rig: Rig) -> None:
    """Fail closed: no owner, no scope to resolve, no action, though the scope gate skipped."""
    rid = await rig.add("armed")
    row = await rig.row(rid)
    row.owner, row.versions[0].ir["created_by"] = "not-a-user", None
    await rig.fire()
    await rig.settle()
    assert rig.executor == [] and rig.simulated == []


async def test_evaluable_rules_carry_the_stored_mode_armed_by_version_and_hash(rig: Rig) -> None:
    armed = await rig.add("armed", ir_mode="simulate")
    simulating = await rig.add("simulate", ir_mode="armed")
    (await rig.row(simulating)).armed_by = str(OWNER)  # a store that fills it for every row
    await rig.add("disabled")
    items = {str(i.rule.rule_id): i for i in await rig.mgr.evaluable_rules()}
    assert set(items) == {armed, simulating}
    for rid, item in items.items():
        version = (await rig.row(rid)).versions[0]
        assert (item.version_id, item.ir_hash) == (version.id, version.ir_hash)
    assert (items[armed].mode, items[armed].armed_by) == ("armed", str(OWNER))
    assert (items[simulating].mode, items[simulating].armed_by) == ("simulate", None)
    only = await rig.mgr.evaluable_rules(("simulate",))
    assert [str(i.rule.rule_id) for i in only] == [simulating]


async def test_a_stored_mode_outside_the_two_is_never_evaluated(rig: Rig) -> None:
    """Membership is explicit: a row in any other mode gets no work-list entry, so it is never
    dispatched, even for a caller that asks for that mode."""
    armed = await rig.add("armed")
    await rig.add("disabled")
    await rig.add("paused")  # no such mode, but a row a store could hold
    asked: Any = ("simulate", "armed", "disabled", "paused")  # wider than `EvaluableMode`
    items = await rig.mgr.evaluable_rules(asked)
    assert [(str(i.rule.rule_id), i.mode) for i in items] == [(armed, "armed")]


async def test_current_mode_reads_the_stored_row_again(rig: Rig) -> None:
    rid = await rig.add("armed")
    row = await rig.row(rid)
    h = row.versions[0].ir_hash
    assert await rig.mgr.current_mode(rid) == StoredMode("armed", 1, h)
    row.mode = "simulate"
    assert await rig.mgr.current_mode(rid) == StoredMode("simulate", 1, h)
    row.active_version_id = "v9"  # names no stored version
    assert await rig.mgr.current_mode(rid) == StoredMode("simulate", None, None)


def test_a_second_bind_keeps_what_the_first_one_set() -> None:
    """`bind` sets only what it is given: a later call (E35-S05's simulation sink, the executor's
    handlers) never drops the store, the hooks or a sink of an earlier one."""

    async def audit(_event: str, _data: dict[str, Any]) -> None:
        return None

    async def broadcast(_payload: dict[str, Any]) -> None:
        return None

    async def sink(_req: ActionRequest) -> None:
        return None

    store, svc = InMemoryRuleStore(), RulesService()
    svc.bind(store=store, audit=audit, broadcast=broadcast, action_sink=sink)
    svc.bind(simulation_sink=sink)
    kept = (svc._store, svc._audit, svc._broadcast, svc._action_sink, svc._simulation_sink)
    assert kept == (store, audit, broadcast, sink, sink)


async def test_an_unstarted_service_is_stopped_and_refuses_an_ungated_emitter() -> None:
    """Fail closed (C-2.21): no scope wiring, no emitter; a stopped module drops a result."""

    async def nowhere(_req: ActionRequest) -> None:
        return None

    svc = RulesService()
    assert svc.health().status is HealthStatus.STOPPED
    with pytest.raises(RuntimeError, match="not wired"):
        svc.action_emitter(nowhere)
    svc.evaluation_sink()(EvaluationResult("r", 1, "*@*", "on_price_update", 0, False, None))
    assert svc.manager() is None
