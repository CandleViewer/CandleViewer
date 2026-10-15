"""E35-S01: store, version and mode-switch rules (manager + B9-driven mode lifecycle)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from candleviewer.rules.arming import ArmingFacts, check_arming
from candleviewer.rules.manager import Actor, InMemoryRuleStore, RuleError, RulesManager
from candleviewer.rules.vocabulary import default_registry
from candleviewer.statechart.bindings.b09_rule_instance import promotion_gate_met

FIX = Path(__file__).parents[1] / "fixtures/rule_ir"
OWNER = Actor("u1", "s1", frozenset({"rules:arm_live"}), is_owner=True, step_up_fresh=True)
MGR = Actor("u2", "s2", frozenset({"orders:write"}), frozenset({"acc1"}))


def _ir(threshold: str = "65000.50", **over: Any) -> dict[str, Any]:
    raw = json.loads((FIX / "form_simple_0.json").read_text(encoding="utf-8"), parse_float=str)
    raw["conditions"]["right"]["const"] = threshold
    raw["actions"][0]["params"] = {"channel": "ui", "severity": "info", "template": "x"}
    return {**raw, **over}


def _mgr() -> tuple[RulesManager, list[tuple[str, dict[str, Any]]], list[dict[str, Any]]]:
    audits: list[tuple[str, dict[str, Any]]] = []
    bcs: list[dict[str, Any]] = []

    async def _audit(a: str, p: dict[str, Any]) -> None:
        audits.append((a, p))

    async def _bc(p: dict[str, Any]) -> None:
        bcs.append(p)

    m = RulesManager(
        InMemoryRuleStore(),
        default_registry(),
        audit=_audit,
        broadcast=_bc,
    )
    return m, audits, bcs


async def _active_hash(m: RulesManager, rid: str) -> str:
    active = (await m.get(rid, OWNER))["active_version_id"]
    return str(next(v["ir_hash"] for v in await m.versions(rid) if v["id"] == active))


async def _ready_to_arm(m: RulesManager, rid: str) -> None:
    await m.set_mode(rid, "simulate", OWNER, "k-sim")
    await m.record_simulation(rid, await _active_hash(m, rid), 5, 0.0)


async def test_create_stores_version_1_disabled() -> None:
    m, audits, _ = _mgr()
    out = await m.create(_ir(), OWNER)
    assert out["mode"] == "disabled" and out["version"]["version"] == 1
    assert audits[0][0] == "rule.created"


async def test_every_save_is_a_new_immutable_version() -> None:
    """Scenario: Every save is a new immutable version"""
    m, _, _ = _mgr()
    rid = (await m.create(_ir(), OWNER))["id"]
    for i, n in enumerate(("1", "2", "3"), start=2):
        assert (await m.update(rid, _ir(n), i - 1, OWNER))["version"]["version"] == i
    v3 = (await m.versions(rid))[1]
    assert v3["version"] == 3 and v3["compiler_version"]
    assert (await m.update(rid, _ir("9"), 4, OWNER))["version"]["version"] == 5
    assert (await m.versions(rid))[2]["ir_hash"] == v3["ir_hash"]


async def test_version_chain_and_rollback() -> None:
    m, _, _ = _mgr()
    rid = (await m.create(_ir(), OWNER))["id"]
    for i in range(1, 10):
        await m.update(rid, _ir(str(i)), i, OWNER)
    vs = await m.versions(rid)
    assert [v["version"] for v in vs] == list(range(10, 0, -1))
    first = vs[-1]["id"]
    await m.set_active_version(rid, first, "rollback", OWNER)
    assert (await m.get(rid, OWNER))["active_version_id"] == first
    assert (await m.version(rid, first))["ir"]["version"] == 1


async def test_armed_rule_keeps_active_version_when_saved() -> None:
    """Scenario: Every save is a new immutable version (armed keeps running it)"""
    m, _, _ = _mgr()
    rid = (await m.create(_ir(), OWNER))["id"]
    await _ready_to_arm(m, rid)
    await m.set_mode(rid, "armed", OWNER, "k-arm")
    active = (await m.get(rid, OWNER))["active_version_id"]
    await m.update(rid, _ir("7"), 1, OWNER)
    assert (await m.get(rid, OWNER))["active_version_id"] == active
    assert (await m.get(rid, OWNER))["mode"] == "armed"
    other = (await m.versions(rid))[0]["id"]
    assert (await m.set_active_version(rid, other, "n", OWNER))["mode"] == "simulate"


async def test_arming_requires_simulation_on_exact_hash() -> None:
    """Scenario: Arming requires proof the rule was simulated"""
    m, _, _ = _mgr()
    rid = (await m.create(_ir(), OWNER))["id"]
    await m.set_mode(rid, "simulate", OWNER, "ks")
    with pytest.raises(RuleError) as e:
        await m.set_mode(rid, "armed", OWNER, "k1")
    assert e.value.status == 422 and e.value.code == "simulation_required"
    assert "Run a simulation" in e.value.message
    assert (await m.get(rid, OWNER))["mode"] == "simulate"


async def test_arming_live_is_audited_with_ir_hash_and_broadcast_first() -> None:
    """Scenario: Arming live needs step-up and is provably audited"""
    m, audits, bcs = _mgr()
    scope = {"level": "symbol", "symbols": ["BTCUSDT"], "environments": ["demo", "live"]}
    rid = (await m.create(_ir(scope=scope), OWNER))["id"]
    await _ready_to_arm(m, rid)
    stale = Actor("u1", "s1", frozenset({"rules:arm_live"}), is_owner=True)
    with pytest.raises(RuleError) as e:
        await m.set_mode(rid, "armed", stale, "k0")
    assert e.value.code == "step_up_required"
    noperm = Actor("u1", "s1", frozenset(), is_owner=True, step_up_fresh=True)
    with pytest.raises(RuleError) as e2:
        await m.set_mode(rid, "armed", noperm, "k00")
    assert e2.value.code == "permission_required"
    await m.set_mode(rid, "armed", OWNER, "k1")
    armed = next(p for a, p in audits if a == "rule.armed")
    assert armed["ir_hash"] == await _active_hash(m, rid) and "live" in armed["environments"]
    assert bcs[-1]["mode"] == "armed" and bcs[-1]["topic"] == "rules"
    assert any(a == "rule.mode_refused" for a, _ in audits)


async def test_concurrent_edit_is_rejected_naming_other_session() -> None:
    """Scenario: Concurrent edits never silently overwrite"""
    m, _, _ = _mgr()
    rid = (await m.create(_ir(), OWNER))["id"]
    await m.update(rid, _ir("2"), 1, OWNER)
    other = Actor("u3", "s-other", frozenset(), is_owner=True)
    with pytest.raises(RuleError) as e:
        await m.update(rid, _ir("3"), 1, other)
    assert e.value.status == 409 and e.value.code == "version_conflict"
    assert e.value.extra["session"] == "s1"
    assert e.value.extra["action"] == "reload_and_reapply"


async def test_unchanged_save_creates_nothing() -> None:
    """Scenario: Saving an unchanged rule creates nothing"""
    m, _, _ = _mgr()
    rid = (await m.create(_ir(), OWNER))["id"]
    r = await m.update(rid, _ir(), 1, OWNER)
    assert r["created"] is False and r["version"]["version"] == 1
    assert len(await m.versions(rid)) == 1


async def test_corrupt_stored_rule_is_quarantined() -> None:
    """Scenario: A corrupt stored rule is quarantined"""
    m, _, _ = _mgr()
    rid = (await m.create(_ir(), OWNER))["id"]
    row = await m._s.get(rid)
    assert row is not None
    row.versions[0].ir["conditions"] = {"bogus": 1}
    row.mode = "armed"
    view = await m.get(rid, OWNER)
    assert view["read_only"] and view["mode"] == "disabled"
    assert view["failing_path"].startswith("/") and "export_json" in view
    with pytest.raises(RuleError):
        await m.set_mode(rid, "simulate", OWNER, "kq")


async def test_armed_rule_cannot_be_deleted_and_soft_delete_reuses_name() -> None:
    """Scenario: An armed rule cannot be deleted"""
    m, _, _ = _mgr()
    rid = (await m.create(_ir(), OWNER))["id"]
    await _ready_to_arm(m, rid)
    await m.set_mode(rid, "armed", OWNER, "ka")
    with pytest.raises(RuleError) as e:
        await m.delete(rid, OWNER)
    assert e.value.status == 409 and "Disarm" in e.value.message
    await m.set_mode(rid, "disabled", OWNER, "kd")
    await m.delete(rid, OWNER)
    assert (await m.create(_ir(), OWNER))["mode"] == "disabled"
    kept = await m._s.get(rid)
    assert kept is not None and len(kept.versions) == 1


async def test_mode_endpoint_requires_idempotency_key_and_replays() -> None:
    m, audits, _ = _mgr()
    rid = (await m.create(_ir(), OWNER))["id"]
    with pytest.raises(RuleError) as e:
        await m.set_mode(rid, "simulate", OWNER, None)
    assert e.value.status == 400
    a = await m.set_mode(rid, "simulate", OWNER, "same")
    n = len(audits)
    assert await m.set_mode(rid, "simulate", OWNER, "same") == a and len(audits) == n


async def test_list_is_account_scoped_filterable_and_paginated() -> None:
    m, _, _ = _mgr()
    await m.create(_ir(name="open"), OWNER)
    acct = {"level": "account", "account_ids": ["00000000-0000-4000-8000-0000000000a2"]}
    await m.create(_ir(name="acct", scope=acct), OWNER)
    names = [r["name"] for r in (await m.list_rules(MGR))["items"]]
    assert names == ["open"]
    assert len((await m.list_rules(OWNER, mode="disabled"))["items"]) == 2
    assert len((await m.list_rules(OWNER, scope="account"))["items"]) == 1
    assert (await m.list_rules(OWNER, limit=1))["next_cursor"] is not None


async def test_invalid_ir_rejected_422() -> None:
    m, _, _ = _mgr()
    with pytest.raises(RuleError) as e:
        await m.create({"name": "x"}, OWNER)
    assert e.value.status == 422


def _facts(**kw: Any) -> ArmingFacts:
    base: dict[str, Any] = {
        "has_valid_active_version": True,
        "validation_errors": 0,
        "open_safety_warnings": 0,
        "simulated_on_ir_hash": True,
        "simulation_fires": 5,
        "simulation_hours": 0.0,
        "environments": ("demo",),
        "sends_orders": False,
        "has_flatten_all": False,
    }
    return ArmingFacts(**{**base, **kw})


@pytest.mark.parametrize(
    ("kw", "code"),
    [
        ({"has_valid_active_version": False}, "rule_invalid"),
        ({"validation_errors": 1}, "rule_invalid"),
        ({"open_safety_warnings": 1}, "safety_warning_open"),
        ({"simulated_on_ir_hash": False}, "simulation_required"),
        ({"simulation_fires": 1}, "promotion_gate"),
        ({"sends_orders": True}, "orders_write_required"),
        (
            {
                "sends_orders": True,
                "perms": frozenset({"orders:write"}),
                "unauthorised_accounts": ("a",),
            },
            "orders_write_required",
        ),
        ({"environments": ("live",)}, "permission_required"),
        ({"environments": ("live",), "perms": frozenset({"rules:arm_live"})}, "step_up_required"),
        ({"has_flatten_all": True}, "acknowledgement_required"),
    ],
)
def test_each_arming_precondition_refuses(kw: dict[str, Any], code: str) -> None:
    r = check_arming(_facts(**kw))
    assert r is not None and r.code == code


def test_arming_ok_override_and_gate() -> None:
    assert check_arming(_facts()) is None
    assert check_arming(_facts(simulation_fires=0, simulation_hours=24)) is None
    owner = _facts(simulation_fires=0, is_owner=True, owner_override_reason="why")
    assert check_arming(owner) is None
    assert not promotion_gate_met(4, 23.9)


async def test_set_active_version_on_armed_rule_always_demotes_even_if_simulated() -> None:
    m, _, _ = _mgr()
    rid = (await m.create(_ir(), OWNER))["id"]
    await _ready_to_arm(m, rid)
    await m.set_mode(rid, "armed", OWNER, "k-arm")
    await m.update(rid, _ir("7"), 1, OWNER)
    first = (await m.versions(rid))[0]
    await m.record_simulation(rid, first["ir_hash"], 5, 0.0)  # simulated, still must not stay armed
    out = await m.set_active_version(rid, first["id"], "n", OWNER)
    assert out["mode"] == "simulate"


async def test_set_active_version_requires_grants_for_target_version() -> None:
    m, _, _ = _mgr()
    rid = (
        await m.create(
            _ir(scope={"level": "global", "account_ids": ["00000000-0000-0000-0000-000000000001"]}),
            OWNER,
        )
    )["id"]
    await m.update(
        rid,
        _ir(
            "7",
            scope={
                "level": "global",
                "account_ids": [
                    "00000000-0000-0000-0000-000000000001",
                    "00000000-0000-0000-0000-000000000002",
                ],
            },
        ),
        1,
        OWNER,
    )
    first = (await m.versions(rid))[0]["id"]
    second = (await m.versions(rid))[1]["id"]
    mgr = Actor(
        "u2", "s2", frozenset({"orders:write"}), frozenset({"00000000-0000-0000-0000-000000000001"})
    )
    with pytest.raises(RuleError) as e:  # rule has a version touching acc2 -> hidden from MGR
        await m.set_active_version(rid, first, "n", mgr)
    assert e.value.status == 404
    assert second


async def test_visible_version_hides_an_unseen_rule_before_the_version_lookup() -> None:
    """#2574: on a rule the actor cannot see, a real version, a missing version and a missing
    rule are the same 404 (no existence oracle); the refusal on the unseen rule is audited."""
    m, audits, _ = _mgr()
    acc2 = "00000000-0000-0000-0000-000000000002"
    rid = (await m.create(_ir(scope={"level": "global", "account_ids": [acc2]}), OWNER))["id"]
    vid = (await m.versions(rid))[0]["id"]
    audits.clear()
    seen: list[tuple[int, str, str]] = []
    for r, v in ((rid, vid), (rid, "no-such-version"), ("no-such-rule", vid)):
        with pytest.raises(RuleError) as e:
            await m.visible_version(r, v, MGR, "set_active_version")
        seen.append((e.value.status, e.value.code, e.value.message))
    assert seen == [(404, "not_found", "That rule does not exist.")] * 3
    refused = [(p["op"], p["reason"]) for a, p in audits if a == "rule.scope_refused"]
    assert refused == [("set_active_version", "rule_not_visible")] * 2
    assert (await m.visible_version(rid, vid, OWNER, "set_active_version"))["id"] == vid
    with pytest.raises(RuleError) as e:  # a visible rule may say which part is missing
        await m.visible_version(rid, "no-such-version", OWNER, "set_active_version")
    assert (e.value.status, e.value.message) == (404, "That version does not exist.")


async def test_visibility_considers_every_version_not_just_latest() -> None:
    m, _, _ = _mgr()
    mgr = Actor(
        "u2", "s2", frozenset({"orders:write"}), frozenset({"00000000-0000-0000-0000-000000000001"})
    )
    rid = (
        await m.create(
            _ir(scope={"level": "global", "account_ids": ["00000000-0000-0000-0000-000000000002"]}),
            OWNER,
        )
    )["id"]
    await m.update(
        rid,
        _ir(
            "7", scope={"level": "global", "account_ids": ["00000000-0000-0000-0000-000000000001"]}
        ),
        1,
        OWNER,
    )
    with pytest.raises(RuleError) as e:
        await m.get(rid, mgr)
    assert e.value.status == 404


async def test_live_arming_consumes_step_up_exactly_once() -> None:
    m, _, _ = _mgr()
    calls: list[int] = []

    async def consume() -> bool:
        calls.append(1)
        return True

    actor = Actor(
        "u1",
        "s1",
        frozenset({"rules:arm_live"}),
        is_owner=True,
        step_up_fresh=True,
        consume_step_up=consume,
    )
    scope = {"level": "symbol", "symbols": ["BTCUSDT"], "environments": ["demo", "live"]}
    rid = (await m.create(_ir(scope=scope), OWNER))["id"]
    await _ready_to_arm(m, rid)
    await m.set_mode(rid, "armed", actor, "k1")
    assert calls == [1]


class _CopyStore(InMemoryRuleStore):
    """Persists/loads detached copies, like a DB: nothing survives except stored fields."""

    async def get(self, rule_id: str) -> Any:
        row = await super().get(rule_id)
        return copy.deepcopy(row) if row else None

    async def put(self, row: Any) -> None:
        await super().put(copy.deepcopy(row))

    async def all(self) -> list[Any]:
        return [copy.deepcopy(r) for r in await super().all()]


async def test_conflict_names_session_after_service_rebuild_from_store() -> None:
    """Session A edits; a service rebuilt over the same store still names A on a stale edit."""
    store = _CopyStore()
    m = RulesManager(store, default_registry())
    rid = (await m.create(_ir(), OWNER))["id"]
    await m.update(rid, _ir("2"), 1, OWNER)
    rebuilt = RulesManager(store, default_registry())
    other = Actor("u3", "s-other", frozenset(), is_owner=True)
    with pytest.raises(RuleError) as e:
        await rebuilt.update(rid, _ir("3"), 1, other)
    assert e.value.extra["session"] == "s1"


def _res(rid: str, fired: bool, ts: int = 0, **kw: Any) -> Any:
    from candleviewer.rules.evaluator.engine import EvaluationResult

    return EvaluationResult(rid, 1, "BTCUSDT@*", "tick", ts, fired, None, **kw)


async def test_simulating_rule_results_are_recorded_with_matching_hash() -> None:
    m, _, _ = _mgr()
    rid = (await m.create(_ir(), OWNER))["id"]
    await m.set_mode(rid, "simulate", OWNER, "k-sim")
    assert await m.consume_evaluation(_res(rid, True))
    row = await m._row(rid)
    assert await _active_hash(m, rid) in row.simulated_hashes and row.simulation_fires == 1


async def test_disarmed_rule_results_are_not_recorded() -> None:
    m, _, _ = _mgr()
    rid = (await m.create(_ir(), OWNER))["id"]
    assert not await m.consume_evaluation(_res(rid, True))
    assert (await m._row(rid)).simulated_hashes == set()


async def test_arm_gated_on_simulation_count_then_succeeds() -> None:
    m, _, _ = _mgr()
    rid = (await m.create(_ir(), OWNER))["id"]
    await m.set_mode(rid, "simulate", OWNER, "k-sim")
    for _ in range(4):
        await m.consume_evaluation(_res(rid, True))
    with pytest.raises(RuleError) as e:
        await m.set_mode(rid, "armed", OWNER, "k-a1")
    assert e.value.status == 422 and e.value.code == "promotion_gate"
    await m.consume_evaluation(_res(rid, True))
    assert (await m.set_mode(rid, "armed", OWNER, "k-a2"))["mode"] == "armed"
