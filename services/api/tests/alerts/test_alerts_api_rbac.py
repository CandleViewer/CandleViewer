"""E40-T02 /alerts: RBAC matrix, lifecycle (soft delete frees the name), filters, edges."""

from __future__ import annotations

from typing import Any

import pytest
from _alert_api_env import PRICE_CROSS, USER_A, Env

ROUTES: list[tuple[str, str, Any, str]] = [
    ("GET", "/alerts", None, "alerts:read"),
    ("POST", "/alerts", PRICE_CROSS, "alerts:write"),
    ("GET", "/alerts/{id}", None, "alerts:read"),
    ("PUT", "/alerts/{id}", PRICE_CROSS, "alerts:write"),
    ("DELETE", "/alerts/{id}", None, "alerts:write"),
    ("PUT", "/alerts/{id}/enabled", {"enabled": False}, "alerts:write"),
    ("PUT", "/alerts/{id}/snooze", {"until": None}, "alerts:write"),
]


@pytest.fixture
def env() -> Env:
    return Env()


@pytest.mark.parametrize(("method", "path", "body", "perm"), ROUTES)
def test_every_route_forbidden_without_its_permission(
    env: Env, method: str, path: str, body: Any, perm: str
) -> None:
    aid = env.create()["id"]
    env.perms = frozenset({"alerts:read", "alerts:write"} - {perm})
    r = env.c.request(method, path.format(id=aid), json=body)
    assert r.status_code == 403 and r.json()["required_permissions"] == [perm]
    assert len(env.repo.rows) == 1 and not env.repo.deleted


@pytest.mark.parametrize(("method", "path", "body", "perm"), ROUTES)
def test_every_route_401_without_session(
    env: Env, method: str, path: str, body: Any, perm: str
) -> None:
    aid = env.create()["id"]
    env.user = None
    r = env.c.request(method, path.format(id=aid), json=body)
    assert r.status_code == 401 and r.headers["content-type"] == "application/problem+json"


def test_unwired_resolver_fails_closed_501() -> None:
    assert Env(wired=False).c.get("/alerts").status_code == 501


def test_store_or_registry_down_503(env: Env) -> None:
    env.registry_up = False
    assert env.c.post("/alerts", json=PRICE_CROSS).status_code == 503
    env.repo_up = False
    assert env.c.get("/alerts").status_code == 503


def test_lifecycle_soft_delete_frees_unique_name(env: Env) -> None:
    a = env.create()
    dup = env.c.post("/alerts", json=PRICE_CROSS | {"name": PRICE_CROSS["name"].upper()})
    assert dup.status_code == 409 and dup.json()["code"] == "conflict"
    assert env.c.delete(f"/alerts/{a['id']}").status_code == 204
    assert env.c.get(f"/alerts/{a['id']}").status_code == 404
    assert env.c.delete(f"/alerts/{a['id']}").status_code == 404
    again = env.create()
    assert again["id"] != a["id"] and again["name"] == PRICE_CROSS["name"]
    assert env.audit.actions() == [
        "alert.created",
        "alert.created",  # write-ahead: the refused duplicate attempt is audited too
        "alert.deleted",
        "alert.created",
    ]


def test_put_rename_onto_existing_name_409(env: Env) -> None:
    env.create(name="x")
    b = env.create(name="y")
    r = env.c.put(f"/alerts/{b['id']}", json=PRICE_CROSS | {"name": "X"})
    assert r.status_code == 409


def test_enabled_toggle_audited_with_before_after(env: Env) -> None:
    a = env.create()
    r = env.c.put(f"/alerts/{a['id']}/enabled", json={"enabled": False})
    assert r.status_code == 200 and r.json()["enabled"] is False
    action, kw = env.audit.calls[-1]
    assert action == "alert.disabled"
    assert kw["before_state"] == {"enabled": True} and kw["after_state"] == {"enabled": False}
    assert env.c.put(f"/alerts/{a['id']}/enabled", json={"enabled": 1, "x": 2}).status_code == 422
    assert env.c.put(f"/alerts/{a['id']}/enabled", content=b"{").status_code == 422


def test_list_filters_and_pagination(env: Env) -> None:
    a = env.create(name="a")
    env.create(name="b", symbol="ETHUSDT")
    env.c.put(f"/alerts/{a['id']}/enabled", json={"enabled": False})

    def names(q: str) -> list[str]:
        return sorted(i["name"] for i in env.c.get(f"/alerts{q}").json()["items"])

    assert names("") == ["a", "b"]
    assert names("?enabled=false") == ["a"] and names("?symbol=ETHUSDT") == ["b"]
    page = env.c.get("/alerts?limit=1").json()
    assert page["meta"] == {"next_cursor": "next", "has_more": True, "count": 1}
    assert env.c.get("/alerts?cursor=bad").status_code == 400
    assert env.c.get("/alerts?limit=0").status_code == 422
    assert env.c.get("/alerts?symbol=btc").status_code == 422


@pytest.mark.parametrize(
    "over",
    [
        {"name": ""},
        {"channels": []},
        {"channels": ["sms"]},
        {"symbol": "BTCUSD"},
        {"trigger_mode": "forever"},
        {"severity": "panic"},
        {"actions": []},
        {"webhook_url": "https://example.invalid/x"},
        {"channels": ["webhook"]},
    ],
)
def test_create_invalid_body_422(env: Env, over: dict[str, Any]) -> None:
    r = env.c.post("/alerts", json=PRICE_CROSS | over)
    assert r.status_code == 422 and r.json()["code"] == "validation_failed"
    assert env.repo.rows == {}


def test_create_non_json_body_422(env: Env) -> None:
    assert env.c.post("/alerts", content=b"not json").status_code == 422


def test_create_on_ungranted_account_403(env: Env) -> None:
    acct = "00000000-0000-4000-8000-0000000000ff"
    r = env.c.post("/alerts", json=PRICE_CROSS | {"exchange_account_id": acct})
    assert r.status_code == 403 and env.repo.rows == {}


def test_create_estimated_metric_flagged_in_response(env: Env) -> None:
    ir = {
        "ir_version": 1,
        "trigger": {"type": "on_bar_close", "timeframe": "5m"},
        "conditions": {"node_id": "c1", "op": "is_true", "left": {"metric": "absorption"}},
    }
    a = env.create(condition_ir=ir)
    assert a["estimated_metrics"] == ["absorption"] and a["owner_user_id"] == USER_A


def test_bad_alert_id_is_422_not_500(env: Env) -> None:
    assert env.c.get("/alerts/not-a-uuid").status_code == 422
