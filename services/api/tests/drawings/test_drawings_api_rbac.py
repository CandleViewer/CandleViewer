"""E14-T01 /drawings security: IDOR matrix, audited 403s and the production (session) wiring;
`tests/contract/rbac` drives the real app for every role, CSRF included."""

from __future__ import annotations

from typing import Any

import _drawings_api_env as fakes
import pytest
from _drawings_api_env import BATCH, TRENDLINE, USER_A, USER_B, VIEWER, Env, wire
from fastapi.testclient import TestClient

import candleviewer.app as appmod

ACTORS = {"owner": USER_A, "other": USER_B, "viewer": VIEWER}
#: operation -> HTTP status for (owner, other, viewer); user A owns the target drawing.
IDOR: dict[str, tuple[int, int, int]] = {
    "read:list": (200, 200, 200),
    "write:create": (201, 201, 403),
    "write:put": (200, 404, 403),
    "write:batch_update": (200, 409, 403),
    "delete:delete": (204, 404, 403),
    "delete:batch_delete": (200, 409, 403),
}


def _request(op: str, d: dict[str, Any]) -> tuple[str, str, Any]:
    update = {"op": "update", "id": d["id"], "if_match": d["updated_at"], "drawing": TRENDLINE}
    delete = {"op": "delete", "id": d["id"], "if_match": d["updated_at"]}
    return {
        "read:list": ("GET", "/drawings?symbol=BTCUSDT", None),
        "write:create": ("POST", "/drawings", wire(TRENDLINE)),
        "write:put": ("PUT", f"/drawings/{d['id']}", wire(TRENDLINE)),
        "write:batch_update": ("POST", "/drawings/batch", wire({"operations": [update]}, BATCH)),
        "delete:delete": ("DELETE", f"/drawings/{d['id']}", None),
        "delete:batch_delete": ("POST", "/drawings/batch", wire({"operations": [delete]}, BATCH)),
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
        probes = ("write:put", "delete:delete", "write:batch_update", "delete:batch_delete")
        assert reasons == (["not_owner:workspaces:write:self"] if op in probes else [])


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


@pytest.mark.parametrize("owner", [False, True])
@pytest.mark.parametrize("grants", [{"*"}, {"workspaces:*"}, {"workspaces"},
                                    {"WORKSPACES:READ", "Workspaces:Write"}])  # fmt: skip
def test_wildcard_unknown_and_case_variant_codes_grant_nothing(
    grants: set[str], owner: bool
) -> None:
    env = Env()
    env.grants, env.owner = grants, owner  # the decision point knows exact codes only
    assert env.c.get("/drawings?symbol=BTCUSDT").status_code == 403
    assert env.c.post("/drawings", json=wire(TRENDLINE)).status_code == 403
    assert [c["reason"].split(":", 1)[0] for c in env.audit.denied()] == ["missing_permission"] * 2
    assert env.repo.calls == []


def test_owner_with_explicit_codes_is_allowed() -> None:
    env = Env()
    env.grants, env.owner = {"workspaces:read", "workspaces:write"}, True  # as seeded (0001 :348)
    assert env.c.post("/drawings", json=wire(TRENDLINE)).status_code == 201
    assert len(env.listed()) == 1 and env.audit.denied() == []
