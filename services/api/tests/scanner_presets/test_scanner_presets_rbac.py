"""`/scanner/presets*` security through the router (E08-T09 PR 2a, #4708): the authorization
matrix (owner, manager and viewer x own and another user's preset x list, create, update and
delete), another user's preset answered as a missing one (404, identical bytes) and audited
`rbac.denied`, 401 without a session and the fail-closed denial audit. `tests/contract/rbac`
drives the real app for every role, CSRF included."""

from __future__ import annotations

from typing import Any

import pytest
from _scanner_env import MISSING, PERMS, USER_A, USER_B, VIEWER, Env, body

from candleviewer.audit.writer import AuditUnavailable

ROLES = ("owner", "manager", "viewer")


def _env(role: str) -> tuple[Env, dict[str, str]]:
    env = Env()
    if role == "viewer":
        env.user = VIEWER
    if role == "owner":
        env.owner, env.grants = True, set(PERMS[USER_A])
    me = VIEWER if role == "viewer" else USER_A
    return env, {"own": env.repo.seed(me, "Mine"), "other": env.repo.seed(USER_B, "Theirs")}


def _expected(role: str, target: str, op: str) -> int:
    if op == "list":
        return 200
    if role == "viewer":
        return 403  # no workspaces:write: refused before any target is looked at
    if op == "create":
        return 201
    if target == "other":
        return 404  # the Owner role has no override over another user's preset
    return 200 if op == "update" else 204


def _send(env: Env, op: str, preset_id: str) -> Any:
    if op == "list":
        return env.c.get("/scanner/presets")
    if op == "create":
        return env.c.post("/scanner/presets", json=body(name="New"))
    if op == "update":
        return env.c.put(f"/scanner/presets/{preset_id}", json=body(name="Changed"))
    return env.c.delete(f"/scanner/presets/{preset_id}")


@pytest.mark.parametrize("op", ["list", "create", "update", "delete"])
@pytest.mark.parametrize("target", ["own", "other"])
@pytest.mark.parametrize("role", ROLES)
def test_matrix(role: str, target: str, op: str) -> None:
    env, targets = _env(role)
    before = dict(env.repo.rows)
    r = _send(env, op, targets[target])
    assert r.status_code == _expected(role, target, op), r.text
    for name, preset_id in targets.items():  # only an allowed write changes its own target
        if not (op in ("update", "delete") and r.status_code < 400 and name == target):
            assert env.repo.rows.get(preset_id) == before[preset_id], name
    if op == "list":
        ids = {item["id"] for item in r.json()["items"]}
        assert ids == {targets["own"]}  # never another user's row, whatever the role


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
def test_another_users_preset_is_404_byte_identical_to_a_missing_one(method: str) -> None:
    """Gherkin: a Manager requesting the Owner's preset id answers 404."""
    env, targets = _env("manager")
    foreign = env.c.request(method, f"/scanner/presets/{targets['other']}", json=body())
    missing = env.c.request(method, f"/scanner/presets/{MISSING}", json=body())
    assert foreign.status_code == missing.status_code == 404
    assert foreign.content == missing.content
    assert foreign.headers["content-type"] == missing.headers["content-type"]
    assert targets["other"] not in foreign.text


def test_a_foreign_write_is_audited_rbac_denied_and_a_missing_id_is_not() -> None:
    env, targets = _env("manager")
    foreign = targets["other"]
    env.c.put(f"/scanner/presets/{foreign}", json=body())
    env.c.delete(f"/scanner/presets/{foreign}")
    env.c.delete(f"/scanner/presets/{MISSING}")
    denied = env.audit.denied()
    assert [(c["object_kind"], c["object_id"], c["reason"], c["outcome"]) for c in denied] == [
        ("scanner_preset", foreign, "not_owner:workspaces:write:self", "denied")
    ] * 2
    assert all(c["actor_user_id"] == USER_A for c in denied)
    assert not any(a.startswith("scanner_preset.") for a in env.audit.actions())


def test_a_foreign_denial_that_cannot_be_audited_is_503_and_changes_nothing() -> None:
    env, targets = _env("manager")
    env.audit.fail = AuditUnavailable("down")
    r = env.c.delete(f"/scanner/presets/{targets['other']}")
    assert (r.status_code, r.json()["code"]) == (503, "audit_unavailable")
    assert targets["other"] in env.repo.rows


def test_unauthenticated_is_401_and_touches_nothing() -> None:
    env = Env()
    env.user = None
    for r in (env.c.get("/scanner/presets"), env.c.get("/scanner/criteria"),
              env.c.post("/scanner/presets", json=body()),
              env.c.put(f"/scanner/presets/{MISSING}", json=body()),
              env.c.delete(f"/scanner/presets/{MISSING}")):  # fmt: skip
        assert (r.status_code, r.json()["code"]) == (401, "unauthenticated")
    assert env.repo.calls == [] and env.audit.calls == []


def test_no_resolver_wired_fails_closed_with_401() -> None:
    assert Env(wired=False).c.get("/scanner/presets").status_code == 401


def test_viewer_writes_are_403_audited_with_the_permission_and_never_reach_the_store() -> None:
    env, _ = _env("viewer")
    calls = len(env.repo.calls)
    r = env.c.post("/scanner/presets", json=body())
    assert (r.status_code, r.json()["required_permissions"]) == (403, ["workspaces:write"])
    assert [c["reason"] for c in env.audit.denied()] == ["missing_permission:workspaces:write:self"]
    assert env.repo.calls[calls:] == []


@pytest.mark.parametrize("path", ["/scanner/presets", "/scanner/criteria"])
def test_reads_need_marketdata_read(path: str) -> None:
    env = Env()
    env.grants = {"workspaces:read", "workspaces:write"}
    r = env.c.get(path)
    assert (r.status_code, r.json()["required_permissions"]) == (403, ["marketdata:read"])


def test_a_wildcard_grant_is_not_a_permission() -> None:
    env = Env()
    env.grants = {"*"}
    assert env.c.get("/scanner/presets").status_code == 403
