"""E15-T01 layout security: the IDOR matrix over layout paths, audited 403s, 401/503 on every
layout route and the real `create_app()` behind CSRF (session-resolved callers)."""

from __future__ import annotations

from typing import Any

import _workspaces_api_env as fakes
import pytest
from _workspaces_api_env import LAYOUT, MISSING, SID, USER_A, USER_B, VIEWER, Env, wire
from fastapi import FastAPI
from fastapi.testclient import TestClient

import candleviewer.app as appmod
from candleviewer.api.workspaces import make_workspaces_router
from candleviewer.storage.errors import StorageTierUnavailable
from tests.csrf_helpers import arm_csrf

ACTORS = {"owner": USER_A, "other": USER_B, "viewer": VIEWER}
#: method -> status for (owner, other, viewer) on a path that names A's own layout.
OWN: dict[str, tuple[int, int, int]] = {"GET": (200, 404, 404), "PUT": (200, 404, 403),
                                        "DELETE": (204, 404, 403)}  # fmt: skip
TARGETS = ["layout", "layout_in_other_workspace", "foreign_layout_under_own_workspace"]


def _body(method: str) -> Any:
    return wire(LAYOUT | {"name": "Renamed"}, "LayoutInput") if method == "PUT" else None


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("actor", list(ACTORS))
@pytest.mark.parametrize("method", list(OWN))
def test_idor_matrix_on_layouts(method: str, actor: str, target: str) -> None:
    env = Env()
    w1, w2 = env.create("One")["id"], env.create("Two")["id"]
    lay = env.make_layout(w1)["id"]
    wb = env.as_user(USER_B).create("Theirs")["id"]
    env.as_user(ACTORS[actor])
    own = {"owner": w2, "other": wb, "viewer": MISSING}[actor]  # the actor's own workspace path
    path = {
        "layout": f"/workspaces/{w1}/layouts/{lay}",
        "layout_in_other_workspace": f"/workspaces/{w2}/layouts/{lay}",
        "foreign_layout_under_own_workspace": f"/workspaces/{own}/layouts/{lay}",
    }[target]
    snapshot, calls = dict(env.repo.layouts), len(env.repo.calls)
    r = env.c.request(method, path, json=_body(method))
    expect = OWN[method][list(ACTORS).index(actor)]
    if target != "layout":  # the layout is not reachable through this path for anyone
        expect = 403 if actor == "viewer" and method != "GET" else 404
    assert r.status_code == expect, r.text
    if expect in (200, 204):
        return
    assert env.repo.layouts == snapshot and not env.repo.deleted
    reasons = [c["reason"] for c in env.audit.denied()]
    if expect == 403:  # refused before the store is touched
        assert r.json()["required_permissions"] == ["workspaces:write"]
        assert reasons == ["missing_permission:workspaces:write:self"]
        assert env.repo.calls[calls:] == []
        return
    mode = "read" if method == "GET" else "write"
    own_data = actor == "owner"  # A's own layout on a wrong path of A's own: not a foreign hit
    assert reasons == ([] if own_data else [f"not_owner:workspaces:{mode}:self"])
    if not own_data:
        assert (env.audit.denied()[0]["object_kind"], env.audit.denied()[0]["object_id"]) == (
            "layout", lay)  # fmt: skip
    missing = env.c.request(method, path.rsplit("/", 1)[0] + f"/{MISSING}", json=_body(method))
    assert missing.status_code == 404 and missing.content == r.content  # byte-identical
    assert _headers(missing) == _headers(r)


def _headers(r: Any) -> dict[str, str]:
    """Response headers without the per-request correlation id."""
    return {k: v for k, v in r.headers.items() if k not in ("x-request-id", "x-correlation-id")}


def test_a_foreign_workspace_with_a_missing_layout_audits_the_workspace_once() -> None:
    env = Env()
    wa = env.create("Mine")["id"]
    env.as_user(USER_B).create("Theirs")
    for method in ("GET", "PUT", "DELETE"):
        r = env.c.request(method, f"/workspaces/{wa}/layouts/{MISSING}", json=_body(method))
        assert r.status_code == 404
    kinds = [(c["object_kind"], c["object_id"]) for c in env.audit.denied()]
    assert kinds == [("workspace", wa)] * 3  # one record per foreign hit


def test_foreign_workspace_collections_are_404_and_audited_once_each() -> None:
    env = Env()
    wa = env.create("Mine")["id"]
    env.make_layout(wa)
    env.as_user(USER_B).create("Theirs")
    assert env.c.get(f"/workspaces/{wa}/layouts").status_code == 404
    post = env.c.post(f"/workspaces/{wa}/layouts", json=wire(LAYOUT, "LayoutInput"))
    assert post.status_code == 404 and len(env.repo.layouts) == 1
    assert [c["reason"] for c in env.audit.denied()] == [
        "not_owner:workspaces:read:self",
        "not_owner:workspaces:write:self",
    ]
    env.as_user(VIEWER)
    assert (
        env.c.post(f"/workspaces/{wa}/layouts", json=wire(LAYOUT, "LayoutInput")).status_code == 403
    )


def test_deleted_layout_is_404_and_never_audited_as_a_layout() -> None:
    env = Env()
    wa = env.create("Mine")["id"]
    lay = env.make_layout(wa)["id"]
    assert env.c.delete(f"/workspaces/{wa}/layouts/{lay}").status_code == 204
    for user in (USER_A, USER_B):
        env.as_user(user)
        assert env.c.get(f"/workspaces/{wa}/layouts/{lay}").status_code == 404
    # the deleted layout is never a hit; B probing A's still-live workspace is, once
    assert [(c["object_kind"], c["object_id"]) for c in env.audit.denied()] == [("workspace", wa)]


CALLS: list[tuple[str, str, Any]] = [
    ("GET", f"/workspaces/{MISSING}/layouts", None),
    ("POST", f"/workspaces/{MISSING}/layouts", LAYOUT),
    ("GET", f"/workspaces/{MISSING}/layouts/{MISSING}", None),
    ("PUT", f"/workspaces/{MISSING}/layouts/{MISSING}", LAYOUT),
    ("DELETE", f"/workspaces/{MISSING}/layouts/{MISSING}", None),
    ("GET", "/layout-presets", None),
    ("GET", "/workspaces", None),
]


@pytest.mark.parametrize(("method", "path", "body"), CALLS)
def test_every_route_401_without_a_session(method: str, path: str, body: Any) -> None:
    env = Env()
    env.user = None
    r = env.c.request(method, path, json=body)
    assert r.status_code == 401 and r.json()["code"] == "unauthenticated"
    assert env.repo.calls == [] and env.audit.denied() == []
    assert Env(wired=False).c.request(method, path, json=body).status_code == 401


@pytest.mark.parametrize(("method", "path", "body"), CALLS[:5] + CALLS[6:])
@pytest.mark.parametrize("fault", [None, OSError("down"), StorageTierUnavailable("down")])
def test_store_unavailable_is_503(method: str, path: str, body: Any, fault: Any) -> None:
    env = Env()

    async def boom(*_a: Any, **_k: Any) -> Any:
        raise fault

    if fault is None:
        app = FastAPI()
        app.include_router(make_workspaces_router(lambda: None, _resolver(env), env.audit))
        env.c = TestClient(app)
    else:
        for name in ("list_workspaces", "list_layouts", "create_layout", "get_layout",
                     "replace_layout", "soft_delete_layout", "exists_for_other_owner"):  # fmt: skip
            setattr(env.repo, name, boom)
    r = env.c.request(method, path, json=body and wire(body, "LayoutInput"))
    assert r.status_code == 503 and r.json()["code"] == "store_unavailable", r.text
    assert r.headers["content-type"] == "application/problem+json"


def _resolver(env: Env) -> Any:
    from candleviewer.audit.access import AuditPrincipal

    class R:
        async def resolve(self, _r: Any) -> AuditPrincipal:
            assert env.user is not None
            return AuditPrincipal(env.user, "u", frozenset(fakes.PERMS[env.user]), session_id=SID)

    return R()


# -- the real composition root -------------------------------------------------------------


def test_production_create_app_resolves_callers_from_the_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """As `main.py` (no `principal_resolver`): session-resolved callers, else fail closed."""
    ok, peer = {"Authorization": "Bearer tok-a"}, ("127.0.0.1", 1)
    url = "/layout-presets"
    assert TestClient(appmod.create_app(), client=peer).get(url, headers=ok).status_code == 401
    monkeypatch.setattr(appmod, "build_identity_provider", lambda _settings: fakes.Identity())
    app = appmod.create_app()
    app.state.app_context.auth._sessions = fakes.Sessions()
    app.state.workspaces_repository = fakes.FakeWorkspaceRepo()
    c = TestClient(app, client=peer)
    assert c.get(url, headers=ok).json()["meta"]["count"] == 6
    assert c.get("/workspaces", headers=ok).json()["items"] == []
    for headers in ({}, {"Authorization": "Bearer x"}):
        assert c.get(url, headers=headers).status_code == 401


def test_create_app_serves_workspaces_and_layouts_behind_csrf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(appmod, "build_identity_provider", lambda _settings: fakes.Identity())
    app = appmod.create_app()  # as main.py: no principal_resolver
    app.state.app_context.auth._sessions = fakes.Sessions()
    writer = app.state.app_context.audit._writer = fakes.Audit()
    h, peer = {"Authorization": "Bearer tok-a"}, ("127.0.0.1", 50000)
    c = arm_csrf(TestClient(app, client=peer), app.state.csrf_codec, SID)
    gone = f"/workspaces/{MISSING}/layouts"
    assert c.post(gone, json=wire(LAYOUT, "LayoutInput"), headers=h).status_code == 503  # fake db
    app.state.workspaces_repository = repo = fakes.FakeWorkspaceRepo()
    plain = TestClient(app, client=peer)
    made = c.post("/workspaces", json=wire({"name": "A"}), headers=h).json()
    url = f"/workspaces/{made['id']}/layouts"
    refused = plain.post(url, json=wire(LAYOUT, "LayoutInput"), headers=h)
    assert refused.status_code == 403 and refused.json()["code"] == "csrf_token_invalid"
    assert repo.layouts == {}
    lay = c.post(url, json=wire(LAYOUT, "LayoutInput"), headers=h)
    assert lay.status_code == 201, lay.text
    assert c.get(url, headers=h).json()["items"] == [lay.json()]
    assert c.get(f"{url}/{lay.json()['id']}", headers=h).json() == lay.json()
    assert c.delete(f"{url}/{lay.json()['id']}", headers=h).status_code == 204
    assert [w["action"] for w in writer.calls] == ["auth.csrf_refused"]


UNSAFE = [
    ("POST", "/workspaces", {"name": "A"}, "WorkspaceInput"),
    ("PUT", f"/workspaces/{MISSING}", {"name": "A"}, "WorkspaceInput"),
    ("DELETE", f"/workspaces/{MISSING}", None, ""),
    ("POST", f"/workspaces/{MISSING}/layouts", LAYOUT, "LayoutInput"),
    ("PUT", f"/workspaces/{MISSING}/layouts/{MISSING}", LAYOUT, "LayoutInput"),
    ("DELETE", f"/workspaces/{MISSING}/layouts/{MISSING}", None, ""),
]


@pytest.mark.parametrize(("method", "path", "body", "model"), UNSAFE)
def test_every_unsafe_route_refuses_a_request_without_a_csrf_pair(
    monkeypatch: pytest.MonkeyPatch, method: str, path: str, body: Any, model: str
) -> None:
    monkeypatch.setattr(appmod, "build_identity_provider", lambda _settings: fakes.Identity())
    app = appmod.create_app()
    app.state.app_context.auth._sessions = fakes.Sessions()
    writer = app.state.app_context.audit._writer = fakes.Audit()
    app.state.workspaces_repository = repo = fakes.FakeWorkspaceRepo()
    c = TestClient(app, client=("127.0.0.1", 50000))
    r = c.request(method, path, json=body and wire(body, model),
                  headers={"Authorization": "Bearer tok-a"})  # fmt: skip
    assert r.status_code == 403 and r.json()["code"] == "csrf_token_invalid", r.text
    assert repo.calls == [] and repo.rows == {} and repo.layouts == {}
    assert [w["action"] for w in writer.calls] == ["auth.csrf_refused"]


@pytest.mark.parametrize("bad_first", [True, False])
def test_grid_child_errors_name_the_failing_child_without_union_labels(bad_first: bool) -> None:
    """S2 stops at the first failing child (FailFast): the path names that child, no `leaf`."""
    env = Env()
    ws = env.create("Home")["id"]
    ok = {"type": "leaf", "slot": 0}
    bad = {"type": "leaf", "slot": "x"} if bad_first else {"type": "nope"}
    kids = [bad, ok] if bad_first else [ok, bad]
    node = {"type": "row", "sizes": [0.5, 0.5], "children": kids}
    spec = {"version": 1, "root": node}
    r = env.c.post(f"/workspaces/{ws}/layouts", json={"name": "X", "grid_preset": "custom",
                                                       "grid_spec": spec, "panes": []})  # fmt: skip
    assert r.status_code == 422
    assert [e["field"] for e in r.json()["errors"]] == [
        "grid_spec.root.children.0.slot" if bad_first else "grid_spec.root.children.1"]  # fmt: skip
