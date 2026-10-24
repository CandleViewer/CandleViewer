"""E35-S04: runtime scope enforcement. Scenario names in docstrings."""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

import pytest

from candleviewer.rules.errors import ScopeForbiddenError
from candleviewer.rules.ir.models import RuleScope
from candleviewer.rules.scope import AccountState, ScopeResolver, summarize_scope

OWNER = uuid.UUID(int=1)
A, B, C = (uuid.UUID(int=i) for i in (10, 11, 12))


class FakeState:
    def __init__(self) -> None:
        self.grants = {OWNER: {A, B}}
        self.accounts = {A: AccountState("demo"), B: AccountState("demo"), C: AccountState("demo")}
        self.frozen: set[uuid.UUID] = set()
        self.live_open = False
        self.arm_live = False

    def granted_accounts(self, owner: UUID) -> frozenset[UUID]:
        return frozenset(self.grants.get(owner, set()))

    def account(self, owner: UUID, account_id: UUID) -> AccountState | None:
        return self.accounts.get(account_id)  # one owner per fake: `accounts` is OWNER's view

    def owner_frozen(self, owner: UUID) -> bool:
        return owner in self.frozen

    def live_gate_open(self) -> bool:
        return self.live_open

    def can_arm_live(self, owner: UUID) -> bool:
        return self.arm_live


async def _noop(_a: str, _d: dict[str, str]) -> None:
    return None


def _rec(out: list[str]) -> Any:
    async def f(a: str, _d: dict[str, str]) -> None:
        out.append(a)

    return f


def _rec2(out: list[tuple[str, dict[str, str]]]) -> Any:
    async def f(a: str, d: dict[str, str]) -> None:
        out.append((a, d))

    return f


def scope(**kw: Any) -> RuleScope:
    return RuleScope.model_validate({"level": "account", **kw})


def test_scope_is_rechecked_on_every_action() -> None:
    """Scenario: Scope is re-checked on every action"""
    st = FakeState()
    r = ScopeResolver(st, _noop)
    sc = scope(account_ids=[str(A), str(B)])
    res = r.resolve(sc, OWNER, "demo")
    assert len(res.instances) == 2
    st.grants[OWNER].discard(B)  # revoked after arming, no re-save
    ia = next(i for i in res.instances if i.account_id == A)
    ib = next(i for i in res.instances if i.account_id == B)
    assert r.check_action(sc, OWNER, "demo", ia) is None
    assert r.check_action(sc, OWNER, "demo", ib) == "grant_revoked"
    nxt = r.resolve(sc, OWNER, "demo")
    assert [s.reason for s in nxt.suppressed] == ["grant_revoked"]
    assert nxt.suppressed[0].skipped_reason == "scope"
    assert r.suppressions_total["grant_revoked"] == 2


async def test_out_of_permission_account_is_invisible_and_forbidden() -> None:
    """Scenario: Out-of-permission account is invisible and unusable"""
    st = FakeState()
    audits: list[str] = []
    r = ScopeResolver(st, _rec(audits))
    assert C not in r.listable_accounts(OWNER)
    with pytest.raises(ScopeForbiddenError) as ex1:
        await r.authorize_accounts(OWNER, [C])
    with pytest.raises(ScopeForbiddenError) as ex2:
        await r.authorize_accounts(OWNER, [uuid.UUID(int=999)])  # nonexistent
    assert str(ex1.value) == str(ex2.value) == "Forbidden"
    assert audits == ["rule_scope_denied", "rule_scope_denied"]


def test_a_frozen_grant_is_not_listed_but_the_runtime_still_names_it() -> None:
    """A frozen grant is no access (C-12.4): the account picker omits it, as `/me` does.
    `granted_accounts` keeps it, so the runtime tells `manager_frozen` from `grant_revoked`."""
    st = FakeState()
    st.accounts[B] = AccountState("demo", frozen=True)
    r = ScopeResolver(st, _noop)
    assert r.listable_accounts(OWNER) == [A]
    assert st.granted_accounts(OWNER) == frozenset({A, B})
    res = r.resolve(scope(account_ids=[str(B)]), OWNER, "demo")
    assert [s.reason for s in res.suppressed] == ["manager_frozen"]


def test_live_requires_explicit_opt_in() -> None:
    """Scenario: Live requires explicit opt-in"""
    st = FakeState()
    st.accounts[A] = AccountState("live")
    r = ScopeResolver(st, _noop)
    res = r.resolve(scope(account_ids=[str(A)]), OWNER, "live")
    assert res.env_skipped and not res.instances
    assert r.env_skips_total == 1


def test_live_gate_closed_blocks_even_when_scoped() -> None:
    st = FakeState()
    st.accounts[A] = AccountState("live")
    st.arm_live = True
    r = ScopeResolver(st, _noop)
    sc = scope(account_ids=[str(A)], environments=["live"])
    assert r.resolve(sc, OWNER, "live").env_skipped
    st.live_open = True
    res = r.resolve(sc, OWNER, "live")
    assert len(res.instances) == 1
    st.live_open = False
    assert r.check_action(sc, OWNER, "live", res.instances[0]) == "live_gate"


async def test_live_scope_needs_arm_permission_and_audit() -> None:
    st = FakeState()
    audits: list[tuple[str, dict[str, str]]] = []
    r = ScopeResolver(st, _rec2(audits))
    sc = scope(environments=["demo", "live"])
    with pytest.raises(ScopeForbiddenError):
        await r.authorize_environments(OWNER, sc)
    st.arm_live = True
    await r.authorize_environments(OWNER, sc)
    assert audits[-1] == ("rule_live_scope_armed", {"caller": str(OWNER), "severity": "high"})


def test_per_symbol_instances_are_independent() -> None:
    """Scenario: Per-symbol instances are independent"""
    r = ScopeResolver(FakeState(), _noop)
    res = r.resolve(
        scope(level="symbol", account_ids=[str(A)], symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"]),
        OWNER,
        "demo",
    )
    keys = {i.key for i in res.instances}
    assert len(keys) == 3 and f"BTCUSDT@{A}" in keys


def test_frozen_manager_stops_acting() -> None:
    """Scenario: A frozen manager's rules stop acting"""
    st = FakeState()
    r = ScopeResolver(st, _noop)
    sc = scope(account_ids=[str(A)])
    inst = r.resolve(sc, OWNER, "demo").instances[0]
    st.frozen.add(OWNER)
    assert r.check_action(sc, OWNER, "demo", inst) == "manager_frozen"
    assert r.resolve(sc, OWNER, "demo").suppressed[0].reason == "manager_frozen"


def test_disabled_account_and_symbol_allowlist() -> None:
    st = FakeState()
    st.accounts[A] = AccountState("demo", allowed_symbols=frozenset({"BTCUSDT"}))
    st.accounts[B] = AccountState("demo", enabled=False)
    r = ScopeResolver(st, _noop)
    res = r.resolve(
        scope(account_ids=[str(A), str(B)], symbols=["BTCUSDT", "ETHUSDT"]), OWNER, "demo"
    )
    assert sorted(s.reason for s in res.suppressed) == [
        "account_disabled",
        "account_disabled",
        "symbol_not_allowed",
    ]
    assert len(res.instances) == 1


def test_applies_to_and_algo_children() -> None:
    r = ScopeResolver(FakeState(), _noop)
    sc = scope(account_ids=[str(A)], applies_to="open_positions")
    inst = r.resolve(sc, OWNER, "demo").instances[0]
    assert r.check_action(sc, OWNER, "demo", inst, "open_position") is None
    assert r.check_action(sc, OWNER, "demo", inst, "pending_order") == "applies_to"
    assert (
        r.check_action(sc, OWNER, "demo", inst, "open_position", is_algo_child=True) == "algo_child"
    )
    sc2 = scope(account_ids=[str(A)], exclude_algo_children=False)
    assert r.check_action(sc2, OWNER, "demo", inst, "open_position", is_algo_child=True) is None


def test_summary_matches_scope() -> None:
    s = summarize_scope(
        scope(account_ids=[str(A), str(B)], symbols=["BTCUSDT"], applies_to="open_positions")
    )
    assert s == "2 accounts · BTCUSDT · open positions only · demo"
    assert "all permitted accounts" in summarize_scope(scope(), account_count=None)
    assert summarize_scope(scope(), account_count=1).startswith("1 account ·")


# --- end-to-end wiring (evaluator gate, action dispatch, HTTP 403, audit sink) -------------


def _evaluator(st: FakeState, sc: RuleScope) -> Any:
    from candleviewer.rules.evaluator import Evaluator, SnapshotBuilder
    from candleviewer.rules.evaluator.engine import scope_instance
    from candleviewer.rules.scope import make_scope_gate
    from tests.rules.test_evaluator import Clock, Source, cmp, rule

    clk = Clock()
    src = Source(clk, last_price=100)
    cond = cmp("c1", "gt", {"metric": "last_price"}, {"const": 1})
    r = ScopeResolver(st, _noop)
    ev = Evaluator(
        rule(cond, cooldown_ms=60_000),
        SnapshotBuilder(src),
        clk,
        clk,
        scope_gate=make_scope_gate(r, sc, OWNER, "demo"),
    )
    return ev, clk, scope_instance("BTCUSDT", str(B))


def _tick(ev: Any, inst: str) -> Any:
    ev._snapshots.new_tick()
    return ev.on_trigger(inst, "on_price_update")


def test_evaluator_skips_with_scope_reason_when_grant_revoked_and_counts() -> None:
    st = FakeState()
    ev, _clk, inst = _evaluator(st, scope(account_ids=[str(A), str(B)]))
    assert _tick(ev, inst).fired
    st.grants[OWNER].discard(B)
    res = _tick(ev, inst)
    assert not res.fired and res.skipped_reason == "scope"
    assert ev.stats.skipped["scope"] == 1


def test_frozen_manager_suppressed_immediately_and_cooldown_not_consumed() -> None:
    """Freeze applies on the very next trigger (inside 2 s); suppression burns no limits."""
    st = FakeState()
    ev, clk, inst = _evaluator(st, scope(account_ids=[str(B)]))
    st.frozen.add(OWNER)
    clk.t += 1_999
    assert _tick(ev, inst).skipped_reason == "scope"
    st.frozen.clear()
    assert _tick(ev, inst).fired  # the suppressed trigger did not start a cooldown
    assert _tick(ev, inst).skipped_reason == "cooldown"


async def test_fire_scoped_dispatches_only_when_scope_holds() -> None:
    from candleviewer.rules.scope import fire_scoped

    st = FakeState()
    r = ScopeResolver(st, _noop)
    sc = scope(account_ids=[str(A)])
    inst = r.resolve(sc, OWNER, "demo").instances[0]
    sent: list[str] = []

    async def dispatch(i: Any) -> None:
        sent.append(i.key)

    ok = await fire_scoped(r, sc, OWNER, "demo", inst, dispatch)
    assert ok.fired and sent == [inst.key]
    st.frozen.add(OWNER)
    out = await fire_scoped(r, sc, OWNER, "demo", inst, dispatch)
    assert not out.fired and out.skipped_reason == "scope" and out.suppressed == "manager_frozen"
    assert sent == [inst.key] and r.suppressions_total["manager_frozen"] == 1


async def test_audit_writer_sink_emits_registered_actions() -> None:
    from candleviewer.admin.wiring import audit_writer_sink
    from candleviewer.audit.actions import validate_action

    calls: list[tuple[str, dict[str, Any]]] = []

    class W:
        async def emit(self, action: str, **kw: Any) -> None:
            validate_action(action)
            calls.append((action, kw))

    r = ScopeResolver(FakeState(), audit_writer_sink(W(), acting=str))
    with pytest.raises(ScopeForbiddenError):
        await r.authorize_accounts(OWNER, [C])
    assert calls[0][0] == "rules.scope_denied" and calls[0][1]["object_id"] == str(C)


async def test_a_scope_denial_while_viewing_as_the_caller_names_the_viewer() -> None:
    """#3085 (#4177 security L-1): with the app's `acting_user`, a request viewing as the caller
    writes the viewer as the record's actor, so the emitter's tripwire never sees the target."""
    from candleviewer.admin.wiring import audit_writer_sink
    from candleviewer.api.view_as_subject import acting_user
    from candleviewer.auth.view_as import ViewAsPhase, ViewAsRequestContext, bound_view_as

    viewer = UUID(int=0x3085)
    calls: list[dict[str, Any]] = []

    class W:
        async def emit(self, action: str, **kw: Any) -> None:
            calls.append(kw)

    view = ViewAsRequestContext(
        viewer_user_id=viewer,
        viewer_session_id=uuid.uuid4(),
        viewer_label="ana",
        target_user_id=OWNER,
        context_id=uuid.uuid4(),
        subject_user_id=OWNER,
        phase=ViewAsPhase.LIVE,
    )
    r = ScopeResolver(FakeState(), audit_writer_sink(W(), acting=acting_user))
    with bound_view_as(view), pytest.raises(ScopeForbiddenError):
        await r.authorize_accounts(OWNER, [C])
    assert (calls[0]["actor_user_id"], calls[0]["actor_label"]) == (str(viewer), str(viewer))


def _http(st: FakeState, sink: Any = _noop) -> Any:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from candleviewer.api.rules import make_rules_router
    from candleviewer.rules.vocabulary import default_registry

    class P:
        user_id = OWNER

        def has(self, p: str) -> bool:
            return True

    class R:
        def resolve(self, request: object) -> P:
            return P()

    app = FastAPI()
    app.include_router(
        make_rules_router(
            default_registry, principal_resolver=R(), scope_resolver=ScopeResolver(st, sink)
        )
    )
    return TestClient(app)


def _ir(**scope_over: Any) -> dict[str, Any]:
    import json
    from pathlib import Path

    p = Path(__file__).parents[1] / "fixtures/rule_ir/form_simple_0.json"
    raw = json.loads(p.read_text("utf-8"))
    raw["scope"] = {"level": "account", **scope_over}
    return raw  # type: ignore[no-any-return]


def test_http_403_for_crafted_foreign_or_absent_account_identical_bodies() -> None:
    """Scenario: Out-of-permission account is invisible and unusable (IDOR, C-12.4)."""
    c = _http(FakeState())
    foreign = c.post("/rules/validate", json={"ir": _ir(account_ids=[str(C)])})
    absent = c.post("/rules/validate", json={"ir": _ir(account_ids=[str(uuid.UUID(int=999))])})
    assert foreign.status_code == absent.status_code == 403
    assert foreign.json() == absent.json()
    assert c.post("/rules/validate", json={"ir": _ir(account_ids=[str(A)])}).status_code == 200


def test_http_a_scope_refusal_that_cannot_be_recorded_is_503() -> None:
    """C-2.9 (#4177 security L-1): an unwritable scope record refuses the request, never a 500. The
    problem carries the code the CRUD routes give it (`audit_unavailable`, 22 `x-error-codes`)."""
    from candleviewer.audit.writer import AuditUnavailable

    async def unwritable(_event: str, _data: dict[str, str]) -> None:
        raise AuditUnavailable("audit WAL unwritable")

    c = _http(FakeState(), unwritable)
    response = c.post("/rules/validate", json={"ir": _ir(account_ids=[str(C)])})
    assert (response.status_code, response.json()["code"]) == (503, "audit_unavailable")


def test_http_live_forbidden_without_arm_live() -> None:
    c = _http(FakeState())
    live = c.post("/rules/validate", json={"ir": _ir(environments=["demo", "live"])})
    assert live.status_code == 403


class _AllGranted(FakeState):
    def __init__(self, ids: list[str]) -> None:
        super().__init__()
        u = [uuid.UUID(i) for i in ids]
        self.grants = {OWNER: set(u)}
        self.accounts = {x: AccountState("demo") for x in u}


def test_summary_matches_enforced_scope_property() -> None:
    from hypothesis import given, settings
    from hypothesis import strategies as st_

    @settings(deadline=None)
    @given(
        n=st_.integers(0, 3),
        syms=st_.lists(st_.sampled_from(["BTCUSDT", "ETHUSDT"]), unique=True, max_size=2),
    )
    def check(n: int, syms: list[str]) -> None:
        ids = [str(uuid.UUID(int=100 + i)) for i in range(n)]
        sc = scope(account_ids=ids, symbols=syms)
        res = ScopeResolver(_AllGranted(ids), _noop).resolve(sc, OWNER, "demo")
        text = summarize_scope(sc)
        assert len(res.instances) == n * max(len(syms), 1)
        assert (f"{n} account" in text) if n else ("all permitted accounts" in text)
        assert all(s in text for s in syms) and ("all symbols" in text) == (not syms)

    check()
