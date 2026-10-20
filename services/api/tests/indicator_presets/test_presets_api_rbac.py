"""`/indicator-presets` security through the router (E13-T03, #427): the authorization matrix
(S5: owner, manager and viewer x own, another user's and a built-in x list, create, update and
delete), A1 (built-ins immutable, 403 `builtin_immutable`), A2 (another user's preset is 404,
identical to a missing one, and audited), SR-026 and the fail-closed denial audit.
`tests/contract/rbac` drives the real app for every role, CSRF included."""

from __future__ import annotations

from typing import Any

import pytest
from _presets_env import EMA9, PERMS, USER_A, USER_B, VIEWER, Env, body
from prometheus_client import REGISTRY

from candleviewer.audit.writer import AuditUnavailable

MISSING = "00000000-0000-4000-8000-0000000000ff"
ROLES = ("owner", "manager", "viewer")
TARGETS = ("own", "other", "builtin")
#: (role, target, operation) -> status. The caller is user A (owner and manager) or the viewer;
#: "other" is user B's preset. The Owner role has no override over another user's preset.
_WRITE = {"own": None, "other": 404, "builtin": 403}


def _expected(role: str, target: str, op: str) -> int:
    if op == "list":
        return 200
    if role == "viewer":
        return 403  # no workspaces:write: refused before any target is looked at
    if op == "create":
        return 201
    status = _WRITE[target]
    if status is not None:
        return status
    return 200 if op == "update" else 204


def _env(role: str) -> tuple[Env, dict[str, str]]:
    env = Env()
    if role == "viewer":
        env.user = VIEWER
    if role == "owner":
        env.owner, env.grants = True, set(PERMS[USER_A])  # as seeded: explicit codes
    me = VIEWER if role == "viewer" else USER_A
    targets = {"own": env.repo.seed(me, "Mine"), "other": env.repo.seed(USER_B, "Theirs"),
               "builtin": EMA9}  # fmt: skip
    return env, targets


def _send(env: Env, op: str, preset_id: str) -> Any:
    if op == "list":
        return env.c.get("/indicator-presets")
    if op == "create":
        return env.c.post("/indicator-presets", json=body(name="New"))
    if op == "update":
        return env.c.put(f"/indicator-presets/{preset_id}", json=body(name="Changed"))
    return env.c.delete(f"/indicator-presets/{preset_id}")


@pytest.mark.parametrize("op", ["list", "create", "update", "delete"])
@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("role", ROLES)
def test_matrix(role: str, target: str, op: str) -> None:
    env, targets = _env(role)
    rows_before = dict(env.repo.rows)
    r = _send(env, op, targets[target])
    assert r.status_code == _expected(role, target, op), r.text
    for name, preset_id in targets.items():  # only an allowed write changes its own target
        if not (op in ("update", "delete") and r.status_code < 400 and name == target):
            assert env.repo.rows[preset_id] == rows_before[preset_id], name
    if op == "list":
        ids = {item["id"] for item in r.json()["items"]}
        assert targets["own"] in ids and targets["builtin"] in ids
        assert targets["other"] not in ids  # never another user's row, whatever the role


def test_unauthenticated_is_401_and_touches_nothing() -> None:
    env = Env()
    env.user = None
    for r in (env.c.get("/indicator-presets"), env.c.post("/indicator-presets", json=body()),
              env.c.put(f"/indicator-presets/{EMA9}", json=body()),
              env.c.delete(f"/indicator-presets/{EMA9}")):  # fmt: skip
        assert (r.status_code, r.json()["code"]) == (401, "unauthenticated")
    assert env.repo.calls == [] and env.audit.calls == []


def test_no_resolver_wired_fails_closed_with_401() -> None:
    assert Env(wired=False).c.get("/indicator-presets").status_code == 401


def test_viewer_writes_are_403_audited_with_the_permission_and_never_reach_the_store() -> None:
    """IR-40, AC-19."""
    env, _ = _env("viewer")
    calls = len(env.repo.calls)
    r = env.c.post("/indicator-presets", json=body())
    assert r.json()["required_permissions"] == ["workspaces:write"]
    assert [c["reason"] for c in env.audit.denied()] == ["missing_permission:workspaces:write:self"]
    assert env.repo.calls[calls:] == []


@pytest.mark.parametrize("role", ["owner", "manager"])
def test_put_and_delete_builtin_is_403_builtin_immutable(role: str) -> None:
    """A1: the mutation is refused with 403, the built-in unchanged, `rbac.denied` audited."""
    env, _ = _env(role)
    before = env.repo.rows[EMA9]
    put = env.c.put(f"/indicator-presets/{EMA9}", json=body(indicator_code="ema",
                                                             params={"n": 10}))  # fmt: skip
    delete = env.c.delete(f"/indicator-presets/{EMA9}")
    for r in (put, delete):
        assert (r.status_code, r.json()["code"]) == (403, "forbidden")
        assert r.json()["errors"] == [{"field": "presetId", "rule": "builtin_immutable",
                                       "message": "Built-in presets cannot be changed; save a "
                                                  "copy instead."}]  # fmt: skip
        assert "required_permissions" not in r.json()
    assert env.repo.rows[EMA9] == before and EMA9 not in env.repo.deleted
    denied = env.audit.denied()
    assert [(c["object_kind"], c["object_id"], c["reason"]) for c in denied] == [
        ("indicator_preset", EMA9, "builtin_immutable:workspaces:write:self")
    ] * 2
    assert env.metrics.denied.values == {("builtin_immutable",): 2}


def test_foreign_put_delete_are_404_identical_to_missing() -> None:
    """A2: another user's preset is answered exactly as a missing id (no existence oracle)."""
    env, targets = _env("manager")
    foreign, missing = targets["other"], MISSING
    for method in ("PUT", "DELETE"):
        a = env.c.request(method, f"/indicator-presets/{foreign}", json=body())
        b = env.c.request(method, f"/indicator-presets/{missing}", json=body())
        assert a.status_code == b.status_code == 404
        assert a.content == b.content and a.headers["content-type"] == b.headers["content-type"]
        assert foreign not in a.text


def test_foreign_write_audits_rbac_denied_and_counts() -> None:
    env, targets = _env("manager")
    foreign = targets["other"]
    env.c.put(f"/indicator-presets/{foreign}", json=body())
    env.c.delete(f"/indicator-presets/{foreign}")
    env.c.delete(f"/indicator-presets/{MISSING}")  # a missing id is not a denial
    assert [(c["object_kind"], c["object_id"], c["reason"], c["actor_user_id"])
            for c in env.audit.denied()] == [
        ("indicator_preset", foreign, "not_owner:workspaces:write:self", USER_A)
    ] * 2  # fmt: skip
    assert env.metrics.denied.values == {("not_owner",): 2}
    assert env.repo.rows[foreign].name == "Theirs" and foreign not in env.repo.deleted


def test_list_never_contains_another_users_rows() -> None:
    """AC-02, IR-01: the owner filter is applied by the store, for every role."""
    for role in ROLES:
        env, targets = _env(role)
        listed = env.c.get("/indicator-presets").json()["items"]
        owners = {item["owner_user_id"] for item in listed}
        assert str(USER_B) not in owners and targets["other"] not in {i["id"] for i in listed}


@pytest.mark.parametrize(
    ("query", "rule"),
    [("owner_user_id=" + str(USER_B), "undeclared_parameter"),
     ("user_id=" + str(USER_B), "target_user_not_accepted"), ("limit=5", "undeclared_parameter")],
)  # fmt: skip
def test_list_rejects_owner_user_id_query_with_422(query: str, rule: str) -> None:
    """SR-026: no `/indicator-presets*` operation takes a query parameter."""
    env = Env()
    r = env.c.get(f"/indicator-presets?{query}")
    assert (r.status_code, r.json()["errors"][0]["rule"]) == (422, rule)
    assert str(USER_B) not in r.text and env.repo.calls == []
    assert env.c.delete(f"/indicator-presets/{MISSING}?{query}").status_code == 422


def test_owner_role_has_no_override() -> None:
    env, targets = _env("owner")
    assert env.c.put(f"/indicator-presets/{targets['other']}", json=body()).status_code == 404
    assert env.c.delete(f"/indicator-presets/{targets['other']}").status_code == 404


@pytest.mark.parametrize("owner", [False, True])
@pytest.mark.parametrize("grants", [{"*"}, {"workspaces:*"}, {"WORKSPACES:READ",
                                                               "Workspaces:Write"}])  # fmt: skip
def test_wildcard_unknown_and_case_variant_codes_grant_nothing(
    grants: set[str], owner: bool
) -> None:
    env = Env()
    env.grants, env.owner = grants, owner
    assert env.c.get("/indicator-presets").status_code == 403
    assert env.c.post("/indicator-presets", json=body()).status_code == 403
    assert env.repo.calls == []


@pytest.mark.parametrize("case", ["permission", "builtin", "foreign"])
def test_a_denial_whose_audit_record_cannot_be_written_is_503_and_changes_nothing(
    case: str,
) -> None:
    """C-2.9 fail closed: a 403 or 404 is only sent once its `rbac.denied` record is durable."""
    env, targets = _env("viewer" if case == "permission" else "manager")
    preset_id = {"permission": targets["own"], "builtin": EMA9, "foreign": targets["other"]}[case]
    before = dict(env.repo.rows)
    env.audit.fail = AuditUnavailable("down")
    counted = REGISTRY.get_sample_value("authz_denied_total",
                                        {"permission": "workspaces:write"}) or 0.0  # fmt: skip
    r = env.c.delete(f"/indicator-presets/{preset_id}")
    assert (r.status_code, r.json()["code"]) == (503, "audit_unavailable")
    assert r.headers["retry-after"] == "5" and env.repo.rows == before and not env.repo.deleted
    if case == "permission":  # SR-125: counted before the audit write, so never lost
        after = REGISTRY.get_sample_value("authz_denied_total", {"permission": "workspaces:write"})
        assert after == counted + 1
