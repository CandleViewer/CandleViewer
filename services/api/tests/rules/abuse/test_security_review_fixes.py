"""E35-X02 security-review regressions (PR #1811): protected-rule bypasses and account-id
leaks across export/import. Each refusal asserts no state change and an audit row."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import BaseModel

from candleviewer.rules.ir import models as ir_models
from candleviewer.rules.ir.accounts import (
    collect_account_ids,
    is_account_key,
    model_account_fields,
    redact_account_ids,
)
from candleviewer.rules.manager import Actor, RuleError, is_reserved_name
from tests.rules.abuse.test_abuse_cases import _audit_actions, _seed_system_rule
from tests.rules.test_rules_routes import _Env, _ir
from tests.rules.test_scope import A, B, C

OWNER = Actor("u1", "s1", frozenset({"rules:read", "rules:write"}), is_owner=True)
LOW = Actor("u2", "s2", frozenset({"rules:write"}), granted_accounts=frozenset({str(A)}))
SYS = "sys.native_sl_watchdog"


def _metric_ir(acct: str, **over: Any) -> dict[str, Any]:
    """Rule whose condition reads a metric pinned to `acct` (MetricRef.account_id)."""
    ir = _ir(**over)
    ir["conditions"]["left"] = {**ir["conditions"]["left"], "account_id": acct}
    return ir


def _ir_models() -> list[type[BaseModel]]:
    return [
        m
        for m in vars(ir_models).values()
        if isinstance(m, type) and issubclass(m, BaseModel) and m.__module__ == ir_models.__name__
    ]


# ----- 1. set_active_version on a protected rule ------------------------------------------
async def test_set_active_version_on_system_rule_is_refused_and_audited() -> None:
    e = _Env()
    rid = await _seed_system_rule(e, SYS)
    row = e.mgr._s._rows[rid]  # type: ignore[attr-defined]
    before = row.active_version_id
    with pytest.raises(RuleError) as ei:
        await e.mgr.set_active_version(rid, row.versions[0].id, "switch", OWNER)
    assert ei.value.code == "system_rule_protected"
    assert row.active_version_id == before and row.mode == "armed"
    refused = [p for a, p in e.audits if a == "rule.system_rule_refused"]
    assert refused and refused[-1]["op"] == "set_active_version"


# ----- 2. renames into / out of the reserved namespace --------------------------------------
@pytest.mark.parametrize(
    "name",
    ["sys.native_sl_watchdog", "SYS.mine", "  sys.x", "\uff53\uff59\uff53.mine", "Sys\uff0ex"],
)
def test_is_reserved_name_normalises_case_whitespace_and_lookalikes(name: str) -> None:
    assert is_reserved_name(name)


def test_is_reserved_name_allows_ordinary_names() -> None:
    assert not is_reserved_name("system watch") and not is_reserved_name("my.sys.rule")


@pytest.mark.parametrize(
    "name", ["sys.native_sl_watchdog", "SYS.spoof", "\uff53\uff59\uff53.spoof"]
)
def test_update_cannot_rename_into_reserved_prefix(name: str) -> None:
    e = _Env()
    rid = e.create(name="mine")
    r = e.c.put(f"/rules/{rid}", json={"ir": _ir(name=name)}, headers={"If-Match": "1"})
    assert r.status_code == 403 and r.json()["code"] == "system_rule_reserved"
    got = e.c.get(f"/rules/{rid}").json()
    assert got["name"] == "mine" and got["latest_version"] == 1
    assert "rule.system_rule_refused" in _audit_actions(e)


@pytest.mark.parametrize("name", ["SYS.mine", " sys.mine", "\uff53\uff59\uff53.mine"])
def test_create_refuses_reserved_prefix_variants(name: str) -> None:
    e = _Env()
    r = e.c.post("/rules", json={"ir": _ir(name=name)})
    assert r.status_code == 403 and r.json()["code"] == "system_rule_reserved"


async def test_update_cannot_rename_a_system_rule_even_if_unprotected() -> None:
    e = _Env()
    rid = await _seed_system_rule(e, "sys.other_builtin")  # sys.* but not in PROTECTED set
    r = e.c.put(f"/rules/{rid}", json={"ir": _ir(name="plain")}, headers={"If-Match": "1"})
    assert r.status_code == 403 and r.json()["code"] == "system_rule_reserved"
    assert e.mgr._s._rows[rid].name == "sys.other_builtin"  # type: ignore[attr-defined]
    assert "rule.system_rule_refused" in _audit_actions(e)


def test_update_rename_onto_existing_name_is_conflict() -> None:
    e = _Env()
    e.create(name="taken")
    rid = e.create(name="mine")
    r = e.c.put(f"/rules/{rid}", json={"ir": _ir(name="taken")}, headers={"If-Match": "1"})
    assert r.status_code == 409 and r.json()["code"] == "name_taken"


# ----- 3. export: no account id anywhere ----------------------------------------------------
def test_walker_covers_every_account_field_on_the_ir_models() -> None:
    fields = model_account_fields(*_ir_models())
    assert {"account_id", "account_ids"} <= fields  # MetricRef + RuleScope today
    for m in _ir_models():
        for name in m.model_fields:
            if "account" in name.lower():
                assert is_account_key(name), f"{m.__name__}.{name} escapes the walker"
    doc = {f: "acct-1" for f in fields} | {"nested": [{f: ["acct-2"]} for f in fields]}
    assert set(collect_account_ids(doc)) == {"acct-1", "acct-2"}
    assert collect_account_ids(redact_account_ids(doc)) == ()


async def test_export_strips_metric_and_action_param_account_ids() -> None:
    e = _Env()
    ir = _metric_ir(
        str(B), scope={"level": "account", "account_ids": [str(A)], "environments": ["demo"]}
    )
    ir["actions"][0]["params"] = {**ir["actions"][0]["params"], "target_account_id": str(C)}
    rid = (await e.mgr.create(ir, OWNER))["id"]
    bundle = await e.mgr.export_rule(rid, OWNER)
    blob = json.dumps(bundle)
    for acct in (A, B, C):
        assert str(acct) not in blob
    assert collect_account_ids(bundle) == ()


# ----- 4. import: grant-check the whole tree --------------------------------------------------
async def test_import_with_ungranted_metric_account_is_refused_and_audited() -> None:
    e = _Env()
    with pytest.raises(RuleError) as ei:
        await e.mgr.import_rule({"ir": _metric_ir(str(C), name="imp")}, LOW)
    assert ei.value.status == 403
    assert "rule.import_refused" in _audit_actions(e)
    assert await e.mgr._s.all() == []


async def test_import_with_granted_metric_account_keeps_it() -> None:
    e = _Env()
    out = await e.mgr.import_rule({"ir": _metric_ir(str(A), name="imp")}, LOW)
    ir = e.mgr._s._rows[out["id"]].versions[0].ir  # type: ignore[attr-defined]
    assert out["mode"] == "disabled" and collect_account_ids(ir) == (str(A),)


async def test_non_owner_create_with_metric_account_outside_grants_is_refused() -> None:
    e = _Env()
    with pytest.raises(RuleError) as ei:
        await e.mgr.create(_metric_ir(str(C), name="x"), LOW)
    assert ei.value.status == 403


async def test_non_owner_without_any_grant_cannot_pass_vacuously() -> None:
    e = _Env()
    nobody = Actor("u3", "s3", frozenset({"rules:write"}))
    with pytest.raises(RuleError) as ei:
        await e.mgr.create(_ir(name="empty"), nobody)  # scope has no account_ids
    assert ei.value.status == 403
    assert (await e.mgr.create(_ir(name="ok"), LOW))["mode"] == "disabled"  # granted: allowed


# ----- non-blocking: boot-time tamper check writes through the bound audit writer -----------
async def test_service_start_audits_tampered_system_rule_via_bound_writer() -> None:
    from candleviewer.rules.manager import InMemoryRuleStore, RuleRow
    from candleviewer.rules.service import RulesService

    store = InMemoryRuleStore()
    await store.put(RuleRow("r-sys", SYS, "system", mode="disabled"))
    seen: list[tuple[str, dict[str, Any]]] = []

    async def audit(a: str, p: dict[str, Any]) -> None:
        seen.append((a, p))

    svc = RulesService()
    svc.bind(store=store, audit=audit)
    await svc.start(None)  # type: ignore[arg-type]
    assert [a for a, _ in seen] == ["rule.system_rule_tampered"]
    assert seen[0][1]["name"] == SYS


def test_production_audit_maps_refusal_events_to_denied() -> None:
    from candleviewer.api.rules_actor import _ACTIONS

    for ev in ("rule.system_rule_refused", "rule.system_rule_tampered", "rule.import_refused"):
        assert ev in _ACTIONS  # never silently degraded to "rules.version_create"
