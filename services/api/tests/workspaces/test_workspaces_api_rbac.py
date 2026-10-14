"""E15-T01 /workspaces security: IDOR matrix, audited 403s, 401/503 everywhere, production wiring
(session-resolved callers, CSRF) through the real `create_app()`."""

from __future__ import annotations

from typing import Any

import _workspaces_api_env as fakes
import pytest
from _workspaces_api_env import MISSING, SID, USER_A, USER_B, VIEWER, Env, wire
from fastapi.testclient import TestClient

from candleviewer.storage.errors import StorageTierUnavailable

ACTORS = {"owner": USER_A, "other": USER_B, "viewer": VIEWER}
#: method -> status for (owner, other, viewer); user A owns the target workspace.
IDOR: dict[str, tuple[int, int, int]] = {"GET": (200, 404, 404), "PUT": (200, 404, 403),
                                         "DELETE": (204, 404, 403)}  # fmt: skip


def _send(env: Env, method: str, wid: str) -> Any:
    body = wire({"name": "Renamed"}) if method == "PUT" else None
    return env.c.request(method, f"/workspaces/{wid}", json=body)


@pytest.mark.parametrize("actor", list(ACTORS))
@pytest.mark.parametrize("method", list(IDOR))
def test_idor_matrix_on_workspaces(method: str, actor: str) -> None:
    env = Env()
    mine = env.create("Mine")
    env.create("Spare")  # so DELETE is not the last-workspace refusal
    env.as_user(USER_B).create("Theirs")
    env.as_user(USER_A)
    snapshot, calls = dict(env.repo.rows), len(env.repo.calls)
    env.as_user(ACTORS[actor])
    r = _send(env, method, mine["id"])
    assert r.status_code == IDOR[method][list(ACTORS).index(actor)], r.text
    if actor == "owner":
        return
    assert env.repo.rows == snapshot and not env.repo.deleted
    reasons = [c["reason"] for c in env.audit.denied()]
    if actor == "viewer" and method != "GET":  # refused before the store is touched
        assert r.json()["required_permissions"] == ["workspaces:write"]
        assert reasons == ["missing_permission:workspaces:write:self"]
        assert env.repo.calls[calls:] == []
        return
    mode = "read" if method == "GET" else "write"
    assert reasons == [f"not_owner:workspaces:{mode}:self"]
    assert env.audit.denied()[0]["object_kind"] == "workspace"
    assert env.audit.denied()[0]["object_id"] == mine["id"]
    missing = _send(env, method, MISSING)  # byte-identical to a missing id, and not audited
    assert missing.status_code == 404 and missing.content == r.content
    assert len(env.audit.denied()) == 1


CALLS: list[tuple[str, str, Any]] = [
    ("POST", "/workspaces", {"name": "A"}),
    ("GET", f"/workspaces/{MISSING}", None),
    ("PUT", f"/workspaces/{MISSING}", {"name": "A"}),
    ("DELETE", f"/workspaces/{MISSING}", None),
]


@pytest.mark.parametrize(("method", "path", "body"), CALLS)
def test_every_route_401_without_a_session(method: str, path: str, body: Any) -> None:
    env = Env()
    env.user = None
    r = env.c.request(method, path, json=body)
    assert r.status_code == 401 and r.json()["code"] == "unauthenticated"
    assert env.repo.calls == [] and env.audit.denied() == []
    assert Env(wired=False).c.request(method, path, json=body).status_code == 401  # fail closed


@pytest.mark.parametrize(("method", "path", "body"), CALLS)
@pytest.mark.parametrize("fault", [None, OSError("down"), StorageTierUnavailable("down")])
def test_store_unavailable_is_503(method: str, path: str, body: Any, fault: Any) -> None:
    env = Env()
    if fault is None:
        env.c.app.router.routes.clear()  # rebuilt below with no store
        from fastapi import FastAPI

        from candleviewer.api.workspaces import make_workspaces_router

        app = FastAPI()
        app.include_router(make_workspaces_router(lambda: None, _resolver(env), env.audit))
        env.c = TestClient(app)
    else:

        async def boom(*_a: Any, **_k: Any) -> Any:
            raise fault

        names = "list_workspaces get_workspace_detail create_workspace update_workspace".split()
        for name in [*names, "soft_delete_workspace", "exists_for_other_owner"]:
            setattr(env.repo, name, boom)
    r = env.c.request(method, path, json=body and wire(body))
    assert r.status_code == 503 and r.json()["code"] == "store_unavailable", r.text
    assert r.headers["retry-after"] == "5"
    assert r.headers["content-type"] == "application/problem+json"


def _resolver(env: Env) -> Any:
    from candleviewer.audit.access import AuditPrincipal

    class R:
        async def resolve(self, _r: Any) -> AuditPrincipal:
            return AuditPrincipal(env.user, "u", frozenset(fakes.PERMS[env.user]), session_id=SID)

    return R()
