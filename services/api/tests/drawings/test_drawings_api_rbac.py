"""E14-T01 /drawings security: IDOR matrix, audited 403s and the production (session) wiring;
`tests/contract/rbac` drives the real app for every role, CSRF included."""

from __future__ import annotations

from typing import Any

import _drawings_api_env as fakes
import pytest
from _drawings_api_env import TRENDLINE, USER_A, USER_B, VIEWER, Env, wire
from fastapi.testclient import TestClient

import candleviewer.app as appmod

ACTORS = {"owner": USER_A, "other": USER_B, "viewer": VIEWER}
#: operation -> HTTP status for (owner, other, viewer); user A owns the target drawing.
IDOR: dict[str, tuple[int, int, int]] = {
    "read:list": (200, 200, 200),
    "write:create": (201, 201, 403),
    "write:put": (200, 404, 403),
    "delete:delete": (204, 404, 403),
}


def _request(op: str, d: dict[str, Any]) -> tuple[str, str, Any]:
    return {
        "read:list": ("GET", "/drawings?symbol=BTCUSDT", None),
        "write:create": ("POST", "/drawings", wire(TRENDLINE)),
        "write:put": ("PUT", f"/drawings/{d['id']}", wire(TRENDLINE)),
        "delete:delete": ("DELETE", f"/drawings/{d['id']}", None),
    }[op]


@pytest.mark.parametrize("actor", list(ACTORS))
@pytest.mark.parametrize("op", list(IDOR))
def test_idor_matrix(op: str, actor: str) -> None:
    env = Env()
    mine = env.create()  # user A's drawing
    row_before, calls_before = env.repo.rows[mine["id"]], len(env.repo.calls)
    env.user = ACTORS[actor]
    method, path, body = _request(op, mine)
    r = env.c.request(method, path, json=body)
    assert r.status_code == IDOR[op][list(ACTORS).index(actor)], r.text
    if actor == "owner":
        return
    if op == "read:list":
        assert r.json()["items"] == []  # never listed for anyone else
    assert env.repo.rows[mine["id"]] == row_before and mine["id"] not in env.repo.deleted
    reasons = [c["reason"] for c in env.audit.denied()]
    if actor == "viewer" and op != "read:list":  # refused before the store is touched
        assert r.json()["required_permissions"] == ["workspaces:write"]
        assert reasons == ["missing_permission:workspaces:write:self"]
        assert env.repo.calls[calls_before:] == []
    else:
        foreign_probe = op in ("write:put", "delete:delete")
        assert reasons == (["not_owner:workspaces:write:self"] if foreign_probe else [])


def test_production_create_app_resolves_callers_from_the_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """As `main.py` (no `principal_resolver`): session-resolved callers, else fail closed."""
    url, ok, peer = "/drawings?symbol=BTCUSDT", {"Authorization": "Bearer tok-a"}, ("127.0.0.1", 1)
    assert TestClient(appmod.create_app(), client=peer).get(url, headers=ok).status_code == 401
    monkeypatch.setattr(appmod, "build_identity_provider", lambda _settings: fakes.Identity())
    app = appmod.create_app()
    app.state.app_context.auth._sessions = fakes.Sessions()
    app.state.drawings_repository = fakes.FakeDrawingRepo()
    c = TestClient(app, client=peer)
    assert c.get(url, headers=ok).json()["items"] == []  # 200: resolved through the session
    for headers in ({}, {"Authorization": "Bearer x"}):  # no / unknown bearer: no session
        assert c.get(url, headers=headers).status_code == 401
