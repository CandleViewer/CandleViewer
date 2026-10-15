"""E09-S06: server-evaluated checklist - state derivation, degradation, tamper, dismissal."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api.onboarding import make_onboarding_router
from candleviewer.api.onboarding_checklist import StepResult, bybit_key_restriction
from candleviewer.auth.scopes import PrincipalSnapshot

UID = uuid.uuid4()


class _Resolver:
    def resolve(self, request: Request) -> PrincipalSnapshot | None:
        if not request.headers.get("authorization"):
            return None
        return PrincipalSnapshot(UID, frozenset({"viewer"}), frozenset())


class _Store:
    def __init__(self) -> None:
        self.dismissed = False

    async def is_dismissed(self, user_id: Any) -> bool:
        return self.dismissed

    async def dismiss(self, user_id: Any) -> None:
        self.dismissed = True


class _M:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def inc(self, name: str, **labels: str) -> None:
        self.calls.append((name, labels))


def _ok(_u: Any) -> Any:
    async def f(_u: Any) -> StepResult:
        return StepResult("ok")

    return f


def _client(probes: dict[str, Any], flags: dict[str, bool], store: _Store, m: _M) -> TestClient:
    app = FastAPI()
    app.include_router(make_onboarding_router(store, _Resolver(), probes, flags, m))
    return TestClient(app)


_H = {"authorization": "Bearer x"}
_ALL_OK = {
    k: _ok(None)
    for k in ("tailscale", "totp", "sub_account", "api_key", "profile_limits", "demo_session")
}


def test_first_sign_in_lists_six_steps_server_evaluated() -> None:
    probes = {"totp": _ok(None)}
    r = _client(probes, {}, _Store(), _M()).get("/onboarding/checklist", headers=_H)
    body = r.json()
    assert [i["key"] for i in body["items"]] == [
        "tailscale",
        "totp",
        "sub_account",
        "api_key",
        "profile_limits",
        "demo_session",
    ]
    states = {i["key"]: i["state"] for i in body["items"]}
    assert states["totp"] == "ok" and states["tailscale"] == "pending"
    assert body["complete"] is False


def test_unshipped_epic_flag_renders_pending_with_reason() -> None:
    probes = {"api_key": _ok(None)}
    r = _client(probes, {"api_key": False}, _Store(), _M()).get("/onboarding/checklist", headers=_H)
    item = next(i for i in r.json()["items"] if i["key"] == "api_key")
    assert item["state"] == "pending" and "oming soon" in item["reason"]


def test_bybit_restriction_carries_utc_unblock_time() -> None:
    created = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    res = bybit_key_restriction(created, created + timedelta(hours=1))
    assert res is not None and res.state == "blocked"
    assert res.unblock_at == created + timedelta(hours=48)
    assert bybit_key_restriction(created, created + timedelta(hours=48)) is None


def test_blocked_probe_exposes_unblock_at_in_response() -> None:
    at = datetime(2026, 10, 3, tzinfo=UTC)

    async def blocked(_u: Any) -> StepResult:
        return StepResult("blocked", "wait", at)

    r = _client({"api_key": blocked}, {}, _Store(), _M()).get("/onboarding/checklist", headers=_H)
    item = next(i for i in r.json()["items"] if i["key"] == "api_key")
    assert item["state"] == "blocked" and item["unblock_at"].startswith("2026-10-03")


def test_failing_and_slow_probes_degrade_only_their_step() -> None:
    async def boom(_u: Any) -> StepResult:
        raise RuntimeError("down")

    async def slow(_u: Any) -> StepResult:
        await asyncio.sleep(5)
        return StepResult("ok")

    m = _M()
    r = _client({"totp": boom, "sub_account": slow, "tailscale": _ok(None)}, {}, _Store(), m).get(
        "/onboarding/checklist", headers=_H
    )
    states = {i["key"]: i["state"] for i in r.json()["items"]}
    assert r.status_code == 200
    assert states["totp"] == "error" and states["sub_account"] == "error"
    assert states["tailscale"] == "ok"
    assert ("onboarding_probe_timeouts_total", {"step": "sub_account"}) in m.calls


def test_client_cannot_fake_a_step() -> None:
    c = _client({}, {}, _Store(), _M())
    r = c.get("/onboarding/checklist", headers={**_H, "x-totp": "ok"})
    item = next(i for i in r.json()["items"] if i["key"] == "totp")
    assert item["state"] == "pending"
    # SR-026 (#2632): a step state in the query is not ignored but refused, like any undeclared key
    assert c.get("/onboarding/checklist?totp=ok", headers=_H).status_code == 422


@pytest.mark.parametrize("param", ["user_id", "userId", "USER_ID", "uid", "user-id", "email"])
def test_checklist_with_an_undeclared_query_parameter_is_422_before_any_state_is_read(
    param: str,
) -> None:
    seen: list[str] = []

    class _Watched(_Store):
        async def is_dismissed(self, user_id: Any) -> bool:
            seen.append("store")
            return False

    async def probe(_u: Any) -> StepResult:
        seen.append("probe")
        return StepResult("ok")

    m = _M()
    c = _client({"totp": probe}, {}, _Watched(), m)
    r = c.get("/onboarding/checklist", params={param: str(uuid.uuid4())}, headers=_H)
    assert r.status_code == 422, f"?{param}=: refused, not silently ignored"
    assert r.headers["content-type"] == "application/problem+json"
    body = r.json()
    assert body["code"] == "validation_failed"
    rule = "target_user_not_accepted" if param in ("user_id", "userId") else "undeclared_parameter"
    assert [(e["field"], e["rule"]) for e in body["errors"]] == [(f"query.{param}", rule)]
    assert param in body["detail"] and "items" not in body
    assert seen == [] and m.calls == [], "no probe, store read or metric for a refused request"


def test_checklist_with_a_target_user_parameter_unauthenticated_is_401() -> None:
    c = _client({}, {}, _Store(), _M())
    assert c.get("/onboarding/checklist", params={"user_id": str(UID)}).status_code == 401


def test_dismiss_rejected_until_complete_then_persists() -> None:
    store = _Store()
    flags = {k: True for k in _ALL_OK}
    incomplete = _client({"totp": _ok(None)}, flags, store, _M())
    assert incomplete.post("/onboarding/checklist/dismiss", headers=_H).status_code == 409
    assert store.dismissed is False
    done = _client(_ALL_OK, flags, store, _M())
    assert done.get("/onboarding/checklist", headers=_H).json()["complete"] is True
    assert done.post("/onboarding/checklist/dismiss", headers=_H).status_code == 204
    again = done.get("/onboarding/checklist", headers=_H).json()
    assert again["dismissed"] is True


def test_unauthenticated_is_401_and_unwired_is_501() -> None:
    assert _client({}, {}, _Store(), _M()).get("/onboarding/checklist").status_code == 401
    app = FastAPI()
    app.include_router(make_onboarding_router(None, None, {}, {}))
    assert TestClient(app).get("/onboarding/checklist").status_code == 501
