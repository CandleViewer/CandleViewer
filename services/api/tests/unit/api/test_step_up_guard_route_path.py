"""#2752: the step-up / read-only guard (`make_read_only_guard`) classifies the
routed path, and fails closed when it cannot check.

Under an ASGI `root_path` (`uvicorn --root-path /api/v1`, the contract
`servers` base) the scope `path` carries the prefix - uvicorn prepends it, as
the ASGI spec says - while the router matches with it stripped. A guard that
reads `request.url.path` matches no `DANGEROUS_ROUTES` pattern there, so every
path-gated step-up is skipped. `TestClient(app, root_path=...)` does not add
the prefix itself, so these tests request `/api/v1/...` exactly as uvicorn
would hand it to the app.
"""

from __future__ import annotations

import uuid
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.api.step_up import make_read_only_guard
from candleviewer.auth.step_up import StepUpService
from tests.unit.api.test_step_up_router import _H, _PW, _build, _code, _record, _Sessions

_ROOT = "/api/v1"


def _rooted(c: TestClient) -> TestClient:
    """The same app, served the way `uvicorn --root-path /api/v1` serves it."""
    return TestClient(c.app, root_path=_ROOT)


@pytest.mark.parametrize(
    ("method", "path", "action_class"),
    [
        ("PUT", "/users/u1/roles", "users"),
        ("POST", "/exchange-accounts/a1/keys/k1/rotate", "keys"),
        ("DELETE", "/exchange-accounts/a1/keys/k1", "keys"),
    ],
)
async def test_guard_under_root_path_demands_step_up_on_path_gated_route(
    method: str, path: str, action_class: str
) -> None:
    c, em, *_ = await _build()
    r = _rooted(c).request(method, _ROOT + path, headers=_H)
    assert r.status_code == 403 and r.json()["code"] == "step_up_required", path
    assert r.json()["action_class"] == action_class
    assert "auth.step_up_required" in em.actions()


async def test_guard_under_root_path_admits_the_session_once_elevated() -> None:
    c, _em, seed, clock, _ = await _build()
    rc = _rooted(c)
    path = f"{_ROOT}/users/{uuid.uuid4()}/roles"
    assert rc.put(path, headers=_H).status_code == 403
    body = {"code": _code(seed, clock), "password": _PW}
    ok = rc.post(f"{_ROOT}/auth/step-up", headers=_H, json=body)
    assert ok.status_code == 200 and ok.json()["action_class"] == "users"
    assert rc.put(path, headers=_H).status_code == 200
    assert rc.post(f"{_ROOT}/orders", headers=_H).status_code == 200  # ordinary write


async def test_guard_under_root_path_keeps_logout_open_in_read_only_downgrade() -> None:
    c, *_ = await _build()

    @cast(FastAPI, c.app).post("/auth/logout")
    async def logout() -> dict[str, bool]:
        return {"ok": True}

    rc = _rooted(c)
    bad = {"code": "000000", "password": _PW, "action_class": "keys"}
    tries = [rc.post(f"{_ROOT}/auth/step-up", headers=_H, json=bad) for _ in range(3)]
    assert [t.status_code for t in tries] == [401, 401, 403]
    assert rc.post(f"{_ROOT}/orders", headers=_H).json()["code"] == "session_read_only"
    assert rc.post(f"{_ROOT}/auth/logout", headers=_H).status_code == 200  # exempt


class _Unwired:
    """The `AuthService` facade with nothing wired (the fake backend). Reading
    a service raises, as on the real facade, so a guard touching one 500s."""

    step_up_is_active = False
    sessions_is_active = False

    @property
    def step_up(self) -> StepUpService:
        raise RuntimeError("AuthService.start() has not wired step-up")

    @property
    def sessions(self) -> _Sessions:
        raise RuntimeError("AuthService.start() has not wired a SessionRepository")


class _SessionsOnly(_Unwired):
    """Sessions wired, step-up not: a wiring fault, never "step-up not needed"."""

    sessions_is_active = True

    @property
    def sessions(self) -> _Sessions:
        return _Sessions({"tok": _record(uuid.uuid4())})


def _stub_app(auth: _Unwired) -> FastAPI:
    app = FastAPI()
    app.middleware("http")(make_read_only_guard(auth))

    @app.put("/users/{uid}/roles")
    async def roles(uid: str) -> dict[str, bool]:
        return {"ok": True}

    @app.get("/exchange-accounts/{aid}/keys/{kid}/reveal-scope")
    async def reveal(aid: str, kid: str) -> dict[str, bool]:
        return {"ok": True}

    @app.post("/orders")
    async def orders() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/trading/kill-switch")
    async def kill_switch() -> dict[str, bool]:
        return {"ok": True}

    return app


@pytest.mark.parametrize("root", ["", _ROOT])
def test_guard_fails_closed_when_sessions_are_wired_but_step_up_is_not(root: str) -> None:
    c = TestClient(_stub_app(_SessionsOnly()), root_path=root)
    for method, path in (
        ("PUT", "/users/u1/roles"),
        ("GET", "/exchange-accounts/a1/keys/k1/reveal-scope"),  # a path-gated read
    ):
        r = c.request(method, root + path, headers=_H)
        assert r.status_code == 503, path
        assert r.headers["content-type"] == "application/problem+json"
        assert r.json()["code"] == "service_unavailable"
        assert r.json()["detail"] == "step-up not wired"
    assert c.put(root + "/users/u1/roles").status_code == 503  # no token: still refused
    # Only the path-gated routes: ordinary writes and the kill-switch (engage
    # never waits for a code; its release is gated in the handler) pass.
    assert c.post(root + "/orders", headers=_H).status_code == 200
    assert c.post(root + "/trading/kill-switch", headers=_H).status_code == 200


@pytest.mark.parametrize("root", ["", _ROOT])
def test_guard_defers_to_the_routes_when_no_session_store_is_wired(root: str) -> None:
    """The fake backend: nothing can authenticate, and every dangerous route
    fails closed on its own (501/503), so the guard leaves the request alone."""
    c = TestClient(_stub_app(_Unwired()), root_path=root)
    assert c.put(root + "/users/u1/roles", headers=_H).status_code == 200
    assert c.post(root + "/orders", headers=_H).status_code == 200
