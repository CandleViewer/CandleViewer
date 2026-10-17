"""E40-T02 /alerts over HTTP: the six Gherkin scenarios plus RBAC, IDOR and edge cases."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from _alert_api_env import PRICE_CROSS, USER_B, Env
from fastapi.testclient import TestClient

from candleviewer.domain.text import UNSTORABLE_TEXT

ACTION = {"node_id": "a1", "type": "place_order", "params": {"side": "buy", "qty": "1"}}


@pytest.fixture
def env() -> Env:
    return Env()


# Scenario: A valid price alert compiles and persists
def test_create_price_cross_201_hash_enabled_audited(env: Env) -> None:
    r = env.c.post("/alerts", json=PRICE_CROSS)
    assert r.status_code == 201, r.text
    body = r.json()
    assert len(body["condition_hash"]) == 64 and body["enabled"] is True
    assert body["estimated_metrics"] == [] and body["webhook_url"] is None
    assert r.headers["etag"] == f'"{env.repo.rows[body["id"]].etag}"'
    assert env.audit.actions() == ["alert.created"]
    assert env.audit.calls[0][1]["object_id"] == body["id"] and env.compiles == [None]


# Scenario: An action-bearing payload is rejected (failure)
def _with_ir(mut: Any) -> dict[str, Any]:
    doc = copy.deepcopy(PRICE_CROSS)
    mut(doc["condition_ir"])
    return doc


@pytest.mark.parametrize(
    ("mut", "node_id"),
    [
        (lambda ir: ir.__setitem__("actions", [ACTION]), None),
        (lambda ir: ir.__setitem__("variables", {"v": ACTION}), "a1"),
        (lambda ir: ir["conditions"].__setitem__("right", ACTION), "a1"),
        (lambda ir: ir.__setitem__("\u0430ctions", [ACTION]), None),
    ],
)
def test_create_action_bearing_ir_422_nothing_persisted(env: Env, mut: Any, node_id: Any) -> None:
    r = env.c.post("/alerts", json=_with_ir(mut))
    assert r.status_code == 422 and r.json()["code"] == "rule_ir_invalid"
    err = r.json()["errors"][0]
    assert err.get("node_id") == node_id and err["rule"] == "not_permitted"
    assert env.repo.rows == {} and env.audit.calls == [] and env.compiles == ["action_node"]


def test_create_actions_key_at_body_level_rejected(env: Env) -> None:
    r = env.c.post("/alerts", json=PRICE_CROSS | {"actions": [ACTION]})
    assert r.status_code == 422 and env.repo.rows == {}


def test_create_name_with_nul_is_the_field_422_nothing_persisted(env: Env) -> None:
    r = env.c.post("/alerts", json=PRICE_CROSS | {"name": "price\x00cross"})
    assert r.status_code == 422 and r.json()["code"] == "validation_failed"
    message = f"Value error, {UNSTORABLE_TEXT}"
    assert r.json()["errors"] == [{"field": "name", "rule": "value_error", "message": message}]
    assert env.repo.rows == {} and env.audit.calls == []


def test_router_module_never_imports_the_oms() -> None:
    import candleviewer.alerts.compiler as comp
    import candleviewer.api.alerts as mod

    for m in (mod, comp):
        src = open(m.__file__ or "", encoding="utf-8").read()
        assert "candleviewer.oms" not in src and "place_order(" not in src


# Scenario: Unknown metric is refused with a usable message (failure)
def test_create_unknown_metric_422_names_metric_node_and_suggestions(env: Env) -> None:
    r = env.c.post(
        "/alerts",
        json=_with_ir(lambda ir: ir["conditions"].__setitem__("left", {"metric": "last_price"})),
    )
    assert r.status_code == 422
    err = r.json()["errors"][0]
    assert "last_price" in err["message"] and err["node_id"] == "c1"
    assert "price" in err["suggestions"] and env.repo.rows == {}


# Scenario: Concurrent edits do not silently overwrite (edge)
def test_put_with_stale_etag_412_and_not_applied(env: Env) -> None:
    a = env.create()
    etag = env.c.get(f"/alerts/{a['id']}").headers["etag"]
    first = env.c.put(
        f"/alerts/{a['id']}", json=PRICE_CROSS | {"name": "one"}, headers={"If-Match": etag}
    )
    assert first.status_code == 200 and first.json()["name"] == "one"
    second = env.c.put(
        f"/alerts/{a['id']}", json=PRICE_CROSS | {"name": "two"}, headers={"If-Match": etag}
    )
    assert second.status_code == 412 and second.json()["code"] == "version_conflict"
    assert env.c.get(f"/alerts/{a['id']}").json()["name"] == "one"
    assert env.audit.actions() == ["alert.created", "alert.updated"]


def test_put_garbage_etag_412_and_missing_etag_is_last_write_wins(env: Env) -> None:
    a = env.create()
    bad = env.c.put(f"/alerts/{a['id']}", json=PRICE_CROSS, headers={"If-Match": '"nope"'})
    assert bad.status_code == 412
    ok = env.c.put(f"/alerts/{a['id']}", json=PRICE_CROSS | {"name": "lww"})
    assert ok.status_code == 200 and ok.json()["name"] == "lww"


# Scenario: Cross-user access is impossible (failure)
@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("GET", "", None),
        ("PUT", "", PRICE_CROSS | {"name": "pwned"}),
        ("DELETE", "", None),
        ("PUT", "/enabled", {"enabled": False}),
    ],
)
def test_cross_user_404_no_change_denial_audited(
    env: Env, method: str, suffix: str, body: Any
) -> None:
    b = env.create()
    before = env.repo.rows[b["id"]]
    env.user = USER_B
    r = env.c.request(method, f"/alerts/{b['id']}{suffix}", json=body)
    assert r.status_code == 404 and r.json()["code"] == "not_found"
    assert env.repo.rows[b["id"]] == before and b["id"] not in env.repo.deleted
    action, kw = env.audit.calls[-1]
    assert action == "alert.denied" and kw["outcome"].value == "denied"
    assert env.c.get("/alerts").json()["items"] == []


# Scenario: A template cannot exfiltrate a secret (failure)
@pytest.mark.parametrize("tpl", ["{{secrets.api_key}}", "{{alert.webhook_secret}}", "{{env.X}}"])
def test_create_template_outside_allow_list_422(env: Env, tpl: str) -> None:
    r = env.c.post("/alerts", json=PRICE_CROSS | {"message_template": tpl})
    assert r.status_code == 422 and "message_template" == r.json()["errors"][0]["field"]
    assert tpl.strip("{}") in r.json()["errors"][0]["message"] and env.repo.rows == {}


def test_audit_write_failure_means_no_state_change(env: Env) -> None:
    a = env.create()
    snapshot = dict(env.repo.rows)

    async def boom(action: str, **kw: Any) -> None:
        raise RuntimeError("audit down")

    env.audit.emit = boom  # type: ignore[method-assign]
    c = TestClient(env.c.app, raise_server_exceptions=False)
    assert c.post("/alerts", json=PRICE_CROSS | {"name": "new"}).status_code == 500
    assert c.put(f"/alerts/{a['id']}", json=PRICE_CROSS | {"name": "ren"}).status_code == 500
    assert c.put(f"/alerts/{a['id']}/enabled", json={"enabled": False}).status_code == 500
    assert c.delete(f"/alerts/{a['id']}").status_code == 500
    assert env.repo.rows == snapshot and a["id"] not in env.repo.deleted
