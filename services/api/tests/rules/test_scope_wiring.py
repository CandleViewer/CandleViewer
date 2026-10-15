"""E35-S04: scope enforcement wired through RulesService, the router and the evaluator."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.api.rules import make_rules_router
from candleviewer.auth.generated_permissions import Permission
from candleviewer.rules.ir.models import RuleScope
from candleviewer.rules.scope import ScopeInstanceRef, summarize_scope
from candleviewer.rules.service import RulesService
from candleviewer.rules.vocabulary import default_registry
from tests.rules.test_validator_endpoints import PRICE, _cmp, _doc

OWNER = uuid.UUID(int=1)
A, B, C = (uuid.UUID(int=i) for i in (10, 11, 12))


class Source:
    def __init__(self) -> None:
        self.grants = [(A, True, False), (B, True, False)]
        self.perms: frozenset[str] = frozenset({"rules:read"})

    async def load_grants(self, owner: uuid.UUID) -> list[tuple[uuid.UUID, bool, bool]]:
        return list(self.grants)

    async def load_permissions(self, owner: uuid.UUID) -> frozenset[str]:
        return self.perms


class Principal:
    user_id = OWNER

    def has(self, p: str) -> bool:
        return p == "rules:read"


class Resolver:
    def resolve(self, request: object) -> Principal:
        return Principal()


def _svc(src: Source, audits: list[str]) -> RulesService:
    async def audit(event: str, data: dict[str, str]) -> None:
        audits.append(event)

    svc = RulesService()
    svc.wire_scope(src, "demo", audit)
    return svc


def _client(svc: RulesService | None) -> TestClient:
    app = FastAPI()
    kw: dict[str, Any] = {}
    if svc is not None:
        kw = {"scope_resolver": svc.scope_resolver, "scope_refresh": svc.refresh_scope}
    reg = default_registry()
    app.include_router(make_rules_router(lambda: reg, principal_resolver=Resolver(), **kw))
    return TestClient(app)


def _body(**scope: Any) -> dict[str, Any]:
    rule = _doc(_cmp(PRICE, {"const": 1}), scope={"level": "account", **scope})
    return {"ir": rule.model_dump(mode="json")}


def test_unwired_router_fails_closed_for_scoped_rule() -> None:
    r = _client(None).post("/rules/validate", json=_body(account_ids=[str(A)]))
    assert r.status_code == 501


def test_granted_account_validates_and_ungranted_is_403_without_leak() -> None:
    audits: list[str] = []
    c = _client(_svc(Source(), audits))
    assert c.post("/rules/validate", json=_body(account_ids=[str(A)])).status_code == 200
    r1 = c.post("/rules/validate", json=_body(account_ids=[str(C)]))  # exists, not granted
    r2 = c.post("/rules/validate", json=_body(account_ids=[str(uuid.UUID(int=999))]))
    assert r1.status_code == r2.status_code == 403
    assert r1.json() == r2.json()
    assert audits == ["rule_scope_denied", "rule_scope_denied"]


def test_live_requires_arm_permission_through_app_wiring() -> None:
    src, audits = Source(), list[str]()
    c = _client(_svc(src, audits))
    live = _body(account_ids=[str(A)], environments=["demo", "live"])
    assert c.post("/rules/validate", json=live).status_code == 403
    src.perms = frozenset({"rules:read", Permission.RULES_ARM_LIVE})  # seeded code, #2624
    assert c.post("/rules/validate", json=live).status_code == 200
    assert "rule_live_scope_armed" not in audits  # a dry run is not an arming


def test_revoked_grant_is_picked_up_on_next_request() -> None:
    src = Source()
    c = _client(_svc(src, []))
    assert c.post("/rules/validate", json=_body(account_ids=[str(B)])).status_code == 200
    src.grants = [(A, True, False)]
    assert c.post("/rules/validate", json=_body(account_ids=[str(B)])).status_code == 403


async def test_production_evaluator_is_always_gated() -> None:
    from candleviewer.rules.evaluator import SnapshotBuilder
    from tests.rules.test_evaluator import Clock, cmp, rule
    from tests.rules.test_evaluator import Source as Mkt

    src = Source()
    svc = _svc(src, [])
    await svc.refresh_scope(OWNER)
    clk = Clock()
    r = rule(cmp("c1", "gt", {"metric": "last_price"}, {"const": 1}), cooldown_ms=0)
    r = r.model_copy(
        update={"scope": RuleScope.model_validate({"level": "account", "account_ids": [str(B)]})}
    )
    ev = svc.build_evaluator(
        r, SnapshotBuilder(Mkt(clk, last_price=100)), clk, clk, owner=OWNER, environment="demo"
    )
    inst = f"BTCUSDT@{B}"
    ev._snapshots.new_tick()
    assert ev.on_trigger(inst, "on_price_update").fired
    src.grants = [(B, True, True)]  # manager frozen
    await svc.refresh_scope(OWNER)
    ev._snapshots.new_tick()
    assert ev.on_trigger(inst, "on_price_update").skipped_reason == "scope"
    with pytest.raises(RuntimeError):
        RulesService().build_evaluator(
            r, SnapshotBuilder(Mkt(clk, last_price=1)), clk, clk, owner=OWNER, environment="demo"
        )


@given(
    n=st.integers(0, 3),
    syms=st.lists(st.sampled_from(["BTCUSDT", "ETHUSDT"]), unique=True, max_size=2),
    applies=st.sampled_from(["any", "account", "open_positions", "pending_orders"]),
    envs=st.sampled_from([["demo"], ["demo", "live"]]),
)
async def test_summary_matches_enforcement(
    n: int, syms: list[str], applies: str, envs: list[str]
) -> None:
    """Property: the server-derived chip never claims more than resolution enforces."""
    src = Source()
    svc = _svc(src, [])
    await svc.refresh_scope(OWNER)
    ids = [uuid.UUID(int=10 + i) for i in range(n)]
    sc = RuleScope.model_validate(
        {
            "level": "account",
            "account_ids": [str(i) for i in ids],
            "symbols": syms,
            "applies_to": applies,
            "environments": envs,
        }
    )
    chip = summarize_scope(sc)
    res = svc.scope_resolver.resolve(sc, OWNER, "demo")  # type: ignore[union-attr]
    permitted = {i for i in ids if i in (A, B)} if ids else {A, B}  # empty = all granted
    assert {i.account_id for i in res.instances} <= permitted
    assert len(res.instances) + len(res.suppressed) == len(permitted | set(ids)) * max(len(syms), 1)
    assert (f"{n} account" in chip) if ids else ("all permitted accounts" in chip)
    for s in syms:
        assert s in chip
    for i in res.instances:
        assert isinstance(i, ScopeInstanceRef)


async def test_action_gate_denies_foreign_account_audits_and_follows_scope_change() -> None:
    from candleviewer.app import create_app
    from candleviewer.rules.scope import ActionRequest
    from candleviewer.settings import Settings

    ctx = create_app(Settings()).state.app_context  # real composition root
    src, audits = Source(), list[str]()
    seen: list[ActionRequest] = []

    async def audit(event: str, data: dict[str, str]) -> None:
        audits.append(f"{event}:{data['reason']}")

    async def sink(req: ActionRequest) -> None:
        seen.append(req)

    ctx.rules.wire_scope(src, "demo", audit)
    await ctx.rules.refresh_scope(OWNER)
    emitter = ctx.rules.action_emitter(sink)
    scope_a = RuleScope.model_validate({"level": "account", "account_ids": [str(A)]})
    inst = ScopeInstanceRef(f"BTCUSDT@{B}", "BTCUSDT", B)

    def req(scope: RuleScope, i: ScopeInstanceRef) -> ActionRequest:
        return ActionRequest(scope, OWNER, "demo", i, "flatten_position")

    assert await emitter.emit(req(scope_a, inst)) is False  # targets B, scoped to A
    assert seen == [] and audits == ["rule_action_scope_denied:out_of_scope"]
    assert emitter.denied_total == 1
    ok = ScopeInstanceRef(f"BTCUSDT@{A}", "BTCUSDT", A)
    assert await emitter.emit(req(scope_a, ok)) is True
    scope_b = RuleScope.model_validate({"level": "account", "account_ids": [str(B)]})
    assert await emitter.emit(req(scope_b, inst)) is True  # new scope, no restart
    assert await emitter.emit(req(scope_b, ok)) is False


async def _e2e(target: uuid.UUID) -> tuple[list[str], list[Any]]:
    """create_app (real evaluator + scope gate) -> simulate/armed rule scoped to A fires."""
    import asyncio
    import json
    import time
    from decimal import Decimal
    from pathlib import Path

    from candleviewer.app import create_app
    from candleviewer.rules.ir.models import MetricRef
    from candleviewer.rules.manager import Actor, InMemoryRuleStore
    from candleviewer.settings import Settings

    audits: list[str] = []
    seen: list[Any] = []

    async def audit(event: str, data: dict[str, str]) -> None:
        audits.append(f"{event}:{data.get('reason')}")

    async def sink(req: Any) -> None:
        seen.append(req)

    ctx = create_app(Settings(rules_evaluator_enabled=True)).state.app_context
    ctx.rules.bind(store=InMemoryRuleStore(), action_sink=sink)
    ctx.rules.wire_scope(Source(), "demo", audit)
    await ctx.rules.refresh_scope(OWNER)
    await ctx.rules.start(ctx)
    try:
        fix = Path(__file__).parents[1] / "fixtures/rule_ir/form_simple_0.json"
        raw = json.loads(fix.read_text(encoding="utf-8"))
        raw["conditions"]["right"]["const"] = 100
        raw["actions"][0]["params"] = {"channel": "ui", "severity": "info", "template": "x"}
        raw["scope"] = {"level": "account", "account_ids": [str(A)], "symbols": ["BTCUSDT"]}
        actor = Actor(str(OWNER), "s1", frozenset({"rules:arm_live"}), is_owner=True,
                      step_up_fresh=True)  # fmt: skip
        mgr = ctx.rules.manager()
        assert mgr is not None and ctx.rules.runner is not None
        rid = (await mgr.create(raw, actor))["id"]
        await mgr.set_mode(rid, "simulate", actor, "k")
        src = ctx.rules.metric_source
        assert src is not None
        src.push(
            MetricRef.model_validate({"metric": "price", "params": {"n": 14}}),
            Decimal("150"), time.time_ns() // 1_000_000,
        )  # fmt: skip
        # Fake snapshot: the evaluator's scope instance is forced onto `target`.
        runner = ctx.rules.runner
        from candleviewer.rules.evaluator.engine import scope_instance

        ev_rules = await mgr.evaluable_rules(("simulate",))
        ev = runner._factory(ev_rules[0], runner._snapshots)
        ev.on_trigger(scope_instance("BTCUSDT", str(target)), "on_price_update")
        async with asyncio.timeout(2):
            while ctx.rules._tasks:  # noqa: ASYNC110 - drains scheduled emits
                await asyncio.sleep(0.005)
    finally:
        await ctx.rules.stop(1.0)
    return audits, seen


async def test_create_app_evaluator_drops_action_targeting_other_account() -> None:
    audits, seen = await _e2e(B)  # rule scoped to A, instance targets B
    assert seen == [] and "rule_action_scope_denied:out_of_scope" in audits


async def test_create_app_evaluator_delivers_in_scope_action() -> None:
    audits, seen = await _e2e(A)
    assert len(seen) == 1 and seen[0].instance.account_id == A
    assert not any(a.startswith("rule_action_scope_denied") for a in audits)


def test_account_list_excludes_ungranted_and_tracks_revocation() -> None:
    src = Source()
    c = _client(_svc(src, []))
    got = c.get("/rules/accounts").json()["accounts"]
    assert sorted(got) == sorted([str(A), str(B)])
    assert str(C) not in got
    src.grants = [(A, True, False)]
    assert c.get("/rules/accounts").json()["accounts"] == [str(A)]


async def test_runtime_refresh_applies_revocation_without_api_call() -> None:
    from types import SimpleNamespace

    src = Source()
    svc = _svc(src, [])
    rules = [SimpleNamespace(created_by=str(OWNER))]
    await svc._refresh_scope_for(rules)  # type: ignore[arg-type]  # test double
    assert svc.scope_state is not None and B in svc.scope_state.granted_accounts(OWNER)
    src.grants = [(A, True, False)]
    await svc._refresh_scope_for(rules)  # type: ignore[arg-type]  # test double
    assert B not in svc.scope_state.granted_accounts(OWNER)
    assert svc.scope_state.account(B) is None


async def test_failed_refresh_fails_closed() -> None:
    from types import SimpleNamespace

    src = Source()
    svc = _svc(src, [])
    rules = [SimpleNamespace(created_by=str(OWNER))]
    await svc._refresh_scope_for(rules)  # type: ignore[arg-type]  # test double

    async def boom(owner: uuid.UUID) -> list[tuple[uuid.UUID, bool, bool]]:
        raise OSError("db down")

    src.load_grants = boom  # type: ignore[method-assign]  # test double
    await svc._refresh_scope_for(rules)  # type: ignore[arg-type]  # test double
    assert svc.scope_state is not None and not svc.scope_state.granted_accounts(OWNER)
