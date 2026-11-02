"""A `RulesService` rig for E35-T13's engine-internal actions (24 §11.5): the evaluator on, its
runner driven by hand (`process`, never its task), the clocks frozen, the records and the `rules`
broadcasts in memory and the checks' ports open, so each fire's actions run through the real
executor and the engine's own handlers. `drain` runs every waiting signal through the runner, until
none waits. A rule may be stored past the validator (`trigger`, `owner`), as a version saved before
a check or brought in by an upcaster would be (BQ-4 of #5005)."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from candleviewer.rules import manager as manager_module
from candleviewer.rules import service as rules_service
from candleviewer.rules.executor import control as control_module
from candleviewer.rules.executor.control import NotificationHandler, NotifyRow
from candleviewer.rules.executor.signals import SignalBus
from candleviewer.rules.ir.models import MetricRef
from candleviewer.rules.manager import Actor, InMemoryRuleStore, RuleRow, RulesManager
from candleviewer.rules.runner import EvalTick, RuleEvaluationRunner
from candleviewer.rules.scope import ActionRequest
from candleviewer.rules.service import RulesService
from tests.rules.executor.request_builders import Counted, Principals, Records, Switches
from tests.rules.test_evaluator import Clock
from tests.rules.test_scope_wiring import OWNER, Source
from tests.rules.test_scope_wiring import A as ACCOUNT

OTHER = uuid.UUID(int=2)  # another owner
ACTOR = Actor(str(OWNER), "s1", frozenset({"rules:arm_live"}), is_owner=True, step_up_fresh=True)
FIXTURE = Path(__file__).parents[2] / "fixtures/rule_ir/form_simple_0.json"
PRICE = MetricRef.model_validate({"metric": "price", "params": {"n": 14}})
#: The most signals one `drain` runs: a chain that never ends fails the test, never hangs it.
DRAIN_CAP = 64


def emit(node: str, name: str = "go", **params: Any) -> dict[str, Any]:
    return {"node_id": node, "type": "emit_signal", "params": {"signal_name": name, **params}}


def set_var(node: str, name: str, value: Any = 1, **params: Any) -> dict[str, Any]:
    return {
        "node_id": node,
        "type": "set_variable",
        "params": {"name": name, "value": value, **params},
    }


def act(node: str, action_type: str, **params: Any) -> dict[str, Any]:
    return {"node_id": node, "type": action_type, "params": params}


class FakeOutbox:
    """The outbox writer in memory: one row per key, as `ux_outbox_dedup` keeps it. `delivered` is
    what a delivery would set, which nothing here does: a handler that awaited it would hang."""

    def __init__(self) -> None:
        self.rows: dict[str, NotifyRow] = {}
        self.writes = 0
        self.delivered = asyncio.Event()

    async def enqueue(self, row: NotifyRow) -> None:
        self.writes += 1
        self.rows.setdefault(row.dedupe_key, row)


class AskedStops:
    """Check 8's port (`StopCheck`), admitting and recording each action that asks it: an action
    that touches no stop never does."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def admits(self, req: ActionRequest, account_id: uuid.UUID | None) -> bool:
        self.asked.append(req.action_type)
        return True


class Frames:
    """The manager's `rules` broadcast hook, recording each frame it is given; it raises once a
    test sets `fail`, as a hub that is gone would, and waits while a test's `held` is unset."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.fail = False
        self.held: asyncio.Event | None = None

    async def __call__(self, payload: dict[str, Any]) -> None:
        if self.fail:
            raise ConnectionError("the hub is gone")
        if self.held is not None:
            await self.held.wait()
        self.sent.append(dict(payload))


@dataclass
class EngineRig:
    svc: RulesService
    mgr: RulesManager
    store: InMemoryRuleStore
    runner: RuleEvaluationRunner
    clock: Clock
    records: Records
    counted: Counted
    audits: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    outbox: FakeOutbox = field(default_factory=FakeOutbox)
    principals: Principals = field(default_factory=lambda: Principals(frozenset({ACCOUNT})))
    stops: AskedStops = field(default_factory=AskedStops)
    frames: Frames = field(default_factory=Frames)

    @property
    def bus(self) -> SignalBus:
        assert self.svc._signals is not None
        return self.svc._signals

    async def row(self, rid: str) -> RuleRow:
        row = await self.store.get(rid)
        assert row is not None
        return row

    async def add(
        self,
        mode: str = "armed",
        *,
        actions: Sequence[dict[str, Any]],
        trigger: str = "on_price_update",
        owner: uuid.UUID = OWNER,
        name: str | None = None,
    ) -> str:
        """A rule in `mode`, owned by `owner`, its stored trigger `trigger` (set past the
        validator), no cooldown, its condition true once the price is above 100."""
        raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
        raw["name"] = name or f"rule-{len(await self.store.all())}"
        raw["conditions"]["right"]["const"] = 100
        raw["actions"] = [dict(a) for a in actions]
        raw["scope"] = {"level": "account", "account_ids": [str(ACCOUNT)], "symbols": ["BTCUSDT"]}
        raw["limits"] = {"cooldown_ms": 0}
        rid = str((await self.mgr.create(raw, ACTOR))["id"])
        row = await self.row(rid)
        row.owner = str(owner)
        row.mode, row.armed_by = mode, (str(owner) if mode == "armed" else None)
        row.versions[0].ir["trigger"] = {"type": trigger}
        return rid

    async def fire(self, price: str = "150") -> None:
        """One market tick: the rules evaluate and their fires are queued."""
        self.clock.t += 2_000
        assert self.svc.metric_source is not None
        self.svc.metric_source.push(PRICE, Decimal(price), self.clock.t)
        await self.runner.process(EvalTick("on_price_update", "BTCUSDT"))

    async def settle(self, *, broadcasts: bool = True) -> None:
        """Every fire run and recorded, then (`broadcasts`) every move's `rules` broadcast, which
        runs beside the move as the manager's tracked task."""
        async with asyncio.timeout(10):  # a guard: a fire that never ends fails the test
            await asyncio.gather(*self.svc._tasks)
            for queue in (self.svc._dispatch, self.svc._audits):
                assert queue is not None
                await queue.idle()
            if broadcasts:
                await asyncio.gather(*self.mgr._stop_broadcasts)

    async def drain(self) -> list[int]:
        """Settle, then each waiting signal through the runner as its task would, settling after
        each; the depths of the signals run, in order."""
        await self.settle()
        depths: list[int] = []
        while (signal := self.bus.take()) is not None:
            assert len(depths) < DRAIN_CAP, "the signal chain never ended"
            depths.append(signal.depth)
            await self.runner.process(EvalTick("on_signal", signal=signal))
            await self.settle()
        return depths

    def results(self, rid: str | None = None) -> list[tuple[str, str, str | None]]:
        """`(action_type, outcome, error_code or blocked_by)` of each result, of `rid`'s fires."""
        runs = {r for r, run in self.records.runs.items() if rid is None or run.rule_id == rid}
        return [
            (e.payload["action_type"], e.payload["outcome"],
             e.payload["error_code"] or e.payload["blocked_by"])
            for r, e in self.records.events
            if r in runs and e.kind in ("action_ok", "action_fail")
        ]  # fmt: skip


@pytest.fixture
async def engine(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> AsyncIterator[EngineRig]:
    """The rig, started. A test parametrized with `indirect=True` hands it binds of its own
    (`signal_max_depth`, `handlers`), made after the rig's and before the start."""
    clock = Clock()
    monkeypatch.setattr(rules_service, "default_clocks", lambda: (clock, clock))
    monkeypatch.setattr(RuleEvaluationRunner, "start", lambda self: None)  # driven by hand
    # A control move's bound and a notification write's (2 s each) are tested at 0 by themselves,
    # and a moved rule's broadcast's own bound by #5002's stop tests; here they are lifted, so a
    # loaded host (coverage, a load average far above the cores) never decides a scenario, as
    # #5002's auto-disarm tests lift theirs.
    monkeypatch.setattr(control_module, "CONTROL_TIMEOUT_S", 60.0)
    monkeypatch.setattr(control_module, "NOTIFY_TIMEOUT_S", 60.0)
    monkeypatch.setattr(manager_module, "STOP_TIMEOUT_S", 60.0)
    audits: list[tuple[str, dict[str, Any]]] = []

    async def audit(event: str, data: dict[str, Any]) -> None:
        audits.append((event, dict(data)))

    async def scope_audit(_event: str, _data: dict[str, str]) -> None:
        return None

    store, records, counted, outbox = InMemoryRuleStore(), Records(), Counted(), FakeOutbox()
    frames = Frames()
    svc = RulesService()
    svc.bind(store=store, audit=audit, handlers={"send_notification": NotificationHandler(outbox)})
    svc.bind(records=(records, records), metrics=counted.metrics, switches=Switches())
    principals, stops = Principals(frozenset({ACCOUNT})), AskedStops()
    svc.bind(principal=principals, stop_check=stops, broadcast=frames)
    svc.bind(**getattr(request, "param", {}))
    svc.wire_scope(Source(), "demo", scope_audit)
    ctx: Any = SimpleNamespace(settings=SimpleNamespace(rules_evaluator_enabled=True))
    await svc.start(ctx)
    mgr, runner = svc.manager(), svc.runner
    assert mgr is not None and runner is not None
    try:
        yield EngineRig(
            svc, mgr, store, runner, clock, records, counted, audits, outbox, principals, stops,
            frames,
        )  # fmt: skip
    finally:
        await svc.stop(1.0)
