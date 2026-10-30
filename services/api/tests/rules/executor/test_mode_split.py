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
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from candleviewer.observability.health import HealthStatus
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
from candleviewer.rules.service import RulesService
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


@pytest.mark.parametrize("change", [_new_active_version, lambda row: setattr(row, "deleted", True)])
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


async def test_current_mode_reads_the_stored_row_again(rig: Rig) -> None:
    rid = await rig.add("armed")
    assert await rig.mgr.current_mode(rid) == StoredMode("armed", 1)
    (await rig.row(rid)).mode = "simulate"
    assert await rig.mgr.current_mode(rid) == StoredMode("simulate", 1)


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
