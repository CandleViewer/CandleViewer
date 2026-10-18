"""E35-S01 end to end over HTTP: /rules routes, RBAC, step-up, audit, WS publish."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api.rules_crud import make_rules_crud_router
from candleviewer.rules.limits import LIMIT_CAPS, LIMIT_DEFAULTS
from candleviewer.rules.manager import Actor, InMemoryRuleStore, RuleError, RulesManager
from candleviewer.rules.vocabulary import default_registry

FIX = Path(__file__).parents[1] / "fixtures/rule_ir"
ARM = "rules:arm_live"
LIVE = {"level": "symbol", "symbols": ["BTCUSDT"], "environments": ["demo", "live"]}
BASE = {"rules:read", "rules:write", ARM}


def _ir(threshold: str = "65000.50", **over: Any) -> dict[str, Any]:
    raw = json.loads((FIX / "form_simple_0.json").read_text(encoding="utf-8"), parse_float=str)
    raw["conditions"]["right"]["const"] = threshold
    raw["actions"][0]["params"] = {"channel": "ui", "severity": "info", "template": "x"}
    return {**raw, **over}


class _Env:
    def __init__(
        self,
        perms: set[str] | None = None,
        *,
        owner: bool = True,
        granted: frozenset[str] = frozenset(),
        mgr: RulesManager | None = None,
        uid: str = "u1",
    ) -> None:
        self.audits: list[tuple[str, dict[str, Any]]] = []
        self.bcs: list[dict[str, Any]] = []
        self.grants = 1
        self.perms = frozenset(perms or BASE)
        self.anon = False

        async def audit(a: str, p: dict[str, Any]) -> None:
            self.audits.append((a, p))

        async def bc(p: dict[str, Any]) -> None:
            self.bcs.append(p)

        self.mgr = mgr or RulesManager(
            InMemoryRuleStore(), default_registry(), audit=audit, broadcast=bc
        )

        async def consume() -> bool:
            if self.grants <= 0:  # as the real resolver: refuse with the challenge it issued
                raise RuleError(403, "step_up_required", "Step-up required.")
            self.grants -= 1
            return True

        def resolve(_r: Request) -> Actor | None:
            if self.anon:
                return None
            return Actor(
                uid,
                "s1",
                self.perms,
                granted_accounts=granted,
                is_owner=owner,
                step_up_fresh=True,
                consume_step_up=consume,
            )

        app = FastAPI()
        app.include_router(make_rules_crud_router(lambda: self.mgr, resolve))
        self.c = TestClient(app)

    def create(self, **over: Any) -> str:
        r = self.c.post("/rules", json={"ir": _ir(**over)})
        assert r.status_code == 201, r.text
        return str(r.json()["id"])

    def mode(self, rid: str, mode: str, key: str) -> Any:
        return self.c.put(
            f"/rules/{rid}/mode", json={"mode": mode}, headers={"Idempotency-Key": key}
        )

    def ready(self, rid: str) -> None:
        """simulate + a completed simulation on the active ir_hash (E35-S05 writes this)."""
        assert self.mode(rid, "simulate", f"sim-{rid}").status_code == 200
        h = self.c.get(f"/rules/{rid}/versions").json()["items"][0]["ir_hash"]
        row = self.mgr._s._rows[rid]  # type: ignore[attr-defined]
        row.simulated_hashes.add(h)
        row.simulation_fires = 5


def test_unauthenticated_and_forbidden() -> None:
    e = _Env()
    e.anon = True
    assert e.c.get("/rules").status_code == 401
    ro = _Env({"rules:read"})
    assert ro.c.post("/rules", json={"ir": _ir()}).status_code == 403
    assert ro.c.get("/rules").status_code == 200


def test_create_always_disabled_v1_and_list_pagination() -> None:
    e = _Env()
    rid = e.create()
    e.create(name="second")
    body = e.c.get(f"/rules/{rid}").json()
    assert body["mode"] == "disabled" and body["latest_version"] == 1
    page = e.c.get("/rules?limit=1").json()
    assert page["meta"]["count"] == 1 and page["meta"]["has_more"] is True
    assert e.c.get("/rules?mode=armed").json()["items"] == []


def test_put_mode_armed_without_simulation_is_422_and_stays() -> None:
    """Scenario: Arming requires proof the rule was simulated (HTTP)"""
    e = _Env()
    rid = e.create()
    assert e.mode(rid, "simulate", "a").status_code == 200
    r = e.mode(rid, "armed", "b")
    assert r.status_code == 422 and r.json()["code"] == "simulation_required"
    assert e.c.get(f"/rules/{rid}").json()["mode"] == "simulate"


def test_mode_requires_idempotency_key_and_valid_body() -> None:
    e = _Env()
    rid = e.create()
    assert e.c.put(f"/rules/{rid}/mode", json={"mode": "simulate"}).status_code == 400
    r = e.c.put(f"/rules/{rid}/mode", json={"nope": 1}, headers={"Idempotency-Key": "x"})
    assert r.status_code == 400
    assert e.mode(rid, "armed", "y").status_code == 422  # disabled -> armed is illegal


def test_live_arm_needs_permission_then_step_up_then_audits_and_publishes() -> None:
    """Scenario: Arming live needs step-up and is provably audited (HTTP)"""
    e = _Env({"rules:read", "rules:write"})
    rid = e.create(scope=LIVE)
    e.ready(rid)
    r = e.mode(rid, "armed", "k1")
    assert r.status_code == 403 and r.json()["code"] == "permission_required"
    e.perms = frozenset(BASE)
    e.grants = 0
    r = e.mode(rid, "armed", "k2")
    assert r.status_code == 403 and r.json()["code"] == "step_up_required"
    e.grants = 1
    r = e.mode(rid, "armed", "k3")
    assert r.status_code == 200 and r.json()["mode"] == "armed"
    armed = next(p for a, p in e.audits if a == "rule.armed")
    assert armed["ir_hash"] and "live" in armed["environments"] and armed["scope"] == "symbol"
    assert e.bcs[-1]["topic"] == "rules" and e.bcs[-1]["mode"] == "armed"
    assert e.grants == 0  # one-shot grant consumed by exactly this arming
    assert e.mode(rid, "disabled", "k4").status_code == 200
    # B9 has no `disarmed -> simulating` arm: the chart (not a matrix) refuses it.
    r = e.mode(rid, "simulate", "k5")
    assert r.status_code == 422 and r.json()["code"] == "illegal_transition"
    r = e.mode(rid, "armed", "k6")  # B9 `disarmed --ARM_REQUESTED--> armed`
    assert r.status_code == 403 and r.json()["code"] == "step_up_required"  # no free re-arm


def test_delete_armed_is_409_then_204_after_disarm() -> None:
    """Scenario: An armed rule cannot be deleted (HTTP)"""
    e = _Env()
    rid = e.create()
    e.ready(rid)
    assert e.mode(rid, "armed", "a").status_code == 200
    r = e.c.delete(f"/rules/{rid}")
    assert r.status_code == 409 and "Disarm" in r.json()["detail"]
    assert e.c.get(f"/rules/{rid}/versions").json()["meta"]["count"] == 1
    assert e.mode(rid, "disabled", "b").status_code == 200
    assert e.c.delete(f"/rules/{rid}").status_code == 204
    assert e.c.get(f"/rules/{rid}").status_code == 404


def test_update_creates_version_and_conflict_names_session() -> None:
    """Scenarios: new immutable version; concurrent edit rejected (HTTP)"""
    e = _Env()
    rid = e.create()
    r = e.c.put(f"/rules/{rid}", json={"ir": _ir("2")}, headers={"If-Match": '"1"'})
    assert r.status_code == 200 and r.json()["version"]["version"] == 2
    stale = e.c.put(f"/rules/{rid}", json={"ir": _ir("3")}, headers={"If-Match": "1"})
    assert stale.status_code == 409
    body = stale.json()
    assert body["code"] == "version_conflict" and body["session"] == "s1"
    assert body["action"] == "reload_and_reapply"
    same = e.c.put(f"/rules/{rid}", json={"ir": _ir("2")}, headers={"If-Match": "2"})
    assert same.json()["created"] is False
    assert e.c.put(f"/rules/{rid}", json={"ir": _ir("4")}).status_code == 400


def test_versions_and_active_version_rollback() -> None:
    e = _Env()
    rid = e.create()
    e.c.put(f"/rules/{rid}", json={"ir": _ir("2")}, headers={"If-Match": "1"})
    first = e.c.get(f"/rules/{rid}/versions").json()["items"][-1]["id"]
    full = e.c.get(f"/rules/{rid}/versions/{first}").json()
    assert full["version"] == 1 and "ir" in full
    r = e.c.put(f"/rules/{rid}/active-version", json={"version_id": first, "note": "back"})
    assert r.status_code == 200 and r.json()["active_version_id"] == first
    assert e.c.put(f"/rules/{rid}/active-version", json={}).status_code == 400
    missing = "00000000-0000-4000-8000-000000000000"
    assert e.c.get(f"/rules/{rid}/versions/{missing}").status_code == 404


def test_invalid_ir_422_and_bad_bodies() -> None:
    e = _Env()
    assert e.c.post("/rules", json={"ir": {"name": "x"}}).status_code == 422
    assert e.c.post("/rules", json={"nope": 1}).status_code == 400
    bad = e.c.post("/rules", content="[1]", headers={"content-type": "application/json"})
    assert bad.status_code == 400


def test_unwired_unavailable_and_bad_id() -> None:
    app = FastAPI()
    app.include_router(make_rules_crud_router(lambda: None, None))
    assert TestClient(app).get("/rules").status_code == 501
    app2 = FastAPI()
    actor = Actor("u", "s", frozenset({"rules:read"}))
    app2.include_router(make_rules_crud_router(lambda: None, lambda _r: actor))
    assert TestClient(app2).get("/rules").status_code == 503
    assert _Env().c.get("/rules/not-a-uuid").status_code == 422


A1, A2 = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"


def _scoped(*accts: str) -> dict[str, Any]:
    return {"scope": {**LIVE, "account_ids": list(accts)}}


def test_manager_cannot_target_ungranted_accounts_on_create_or_update() -> None:
    owner = _Env()
    mgr = _Env(owner=False, granted=frozenset({A1}), mgr=owner.mgr)
    assert mgr.c.post("/rules", json={"ir": _ir(**_scoped(A2))}).status_code == 403
    assert mgr.c.post("/rules", json={"ir": _ir(**_scoped(A1, A2))}).status_code == 403
    rid = mgr.create(**_scoped(A1))
    bad = {"ir": _ir(name="renamed", **_scoped(A2)), "expected_version": 1}
    assert mgr.c.put(f"/rules/{rid}", json=bad).status_code == 403
    assert owner.c.get(f"/rules/{rid}").json()["latest_version"] == 1


def test_manager_gets_404_on_another_accounts_rule_everywhere() -> None:
    owner = _Env()
    rid = owner.create(**_scoped(A2))
    vid = owner.c.get(f"/rules/{rid}/versions").json()["items"][0]["id"]
    m = _Env(owner=False, granted=frozenset({A1}), mgr=owner.mgr)
    hdr = {"Idempotency-Key": "k1"}
    ir = {"ir": _ir(**_scoped(A1)), "expected_version": 1}
    assert m.c.get(f"/rules/{rid}").status_code == 404
    assert m.c.put(f"/rules/{rid}", json=ir).status_code == 404
    assert m.c.delete(f"/rules/{rid}").status_code == 404
    assert m.c.get(f"/rules/{rid}/versions").status_code == 404
    assert m.c.get(f"/rules/{rid}/versions/{vid}").status_code == 404
    assert m.c.put(f"/rules/{rid}/active-version", json={"version_id": vid}).status_code == 404
    assert m.c.put(f"/rules/{rid}/mode", json={"mode": "simulate"}, headers=hdr).status_code == 404
    assert m.c.get("/rules").json()["items"] == []
    assert owner.c.get(f"/rules/{rid}").status_code == 200


def _budget(field: str, value: int) -> dict[str, Any]:
    return {"ir": _ir(limits={field: value})}


def test_create_raised_limits_by_a_manager_is_a_403_forbidden_problem() -> None:
    """#3232 (04 §7.2.2 row 26): the refusal names each raised field; nothing is stored."""
    hour = "max_fires_per_hour"
    e = _Env(owner=False, granted=frozenset({A1}))
    r = e.c.post("/rules", json=_budget(hour, LIMIT_DEFAULTS[hour] + 1))
    assert (r.status_code, r.headers["content-type"]) == (403, "application/problem+json")
    body = r.json()
    assert (body["code"], body["type"]) == (
        "forbidden",
        "https://candleviewer.local/errors/forbidden",
    )
    assert [(x["field"], x["rule"]) for x in body["errors"]] == [
        ("limits.max_fires_per_hour", "owner_only_above_default")
    ]
    assert e.c.get("/rules").json()["items"] == []


def test_create_limits_above_the_cap_is_a_422_rule_ir_invalid_problem() -> None:
    day = "max_fires_per_day"
    r = _Env().c.post("/rules", json=_budget(day, LIMIT_CAPS[day] + 1))
    assert (r.status_code, r.json()["code"]) == (422, "rule_ir_invalid")
    (issue,) = r.json()["issues"]
    assert (issue["path"], issue["code"], issue["class"]) == (
        "limits.max_fires_per_day",
        "schema_error",
        "safety",
    )


def test_viewer_saving_raised_limits_is_refused_at_the_permission_gate() -> None:
    hour = "max_fires_per_hour"
    viewer = _Env({"rules:read"}, owner=False, granted=frozenset({A1}))
    r = viewer.c.post("/rules", json=_budget(hour, LIMIT_DEFAULTS[hour] + 1))
    assert (r.status_code, r.json()["detail"]) == (403, "requires rules:write")
    assert viewer.audits == []
