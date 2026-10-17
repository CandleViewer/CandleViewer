"""DELETE /users/{userId} (E42-T04 S6, #965; contract `deleteUser`, the disable).

The route over the REAL `UserDisableService` and the S3 store on its fake unit of work (the world
of `tests/unit/admin/test_user_disable.py`): guards, audit records and nothing-changed cases are
production code's, so what is under test is the order the route puts them in and the problem each
refusal becomes. `_World.log` orders every port call and audit record; the step-up fake adds
`step_up`. The deployed app: `tests/unit/architecture/test_owner_routes_composition.py`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import jsonschema
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.admin.errors import UserLifecycleError
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.users import make_users_router
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.auth.errors import SessionNotFound, StepUpRequired
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.auth.step_up import CHALLENGE_WINDOW, StepUpChallenge
from candleviewer.storage.repositories import user_lifecycle_sqlalchemy as store_module
from candleviewer.storage.repositories.owner_floor_sqlalchemy import LOCK_USER
from tests.unit.admin.test_user_disable import _TARGET, _World
from tests.unit.storage.test_user_lifecycle_sqlalchemy import _Rel

CALLER, MISSING, SESSION, TARGET = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), _TARGET
_PATH = "/users/{}"
_HELD = (AccountGrant(uuid.uuid4(), True, True, False),)
_BAD_ACK = "?acknowledge_unknown_positions=yes"


class _Auth:
    """The step-up and session seams of `test_users_router.py`; `step_up` joins the world's log."""

    step_up_is_active = sessions_is_active = True

    def __init__(
        self, log: list[str], *, elevated: bool = True, session_error: Exception | None = None
    ) -> None:
        self.log, self.elevated, self.session_error = log, elevated, session_error
        self.pending: list[tuple[str, str]] = []
        self.step_up = self.sessions = self

    async def authenticate_access_token(self, token: str) -> Any:
        if self.session_error is not None:
            raise self.session_error
        return SimpleNamespace(id=SESSION, user_id=CALLER)

    async def require_elevation(self, session_id: str, action_class: str) -> None:
        self.log.append("step_up")
        if not self.elevated:
            raise StepUpRequired(action_class)

    async def record_pending(self, session_id: str, action_class: str) -> StepUpChallenge:
        self.pending.append((session_id, action_class))
        return StepUpChallenge(uuid.uuid4(), action_class, datetime.now(UTC) + CHALLENGE_WINDOW)


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    loaded: dict[str, Any] = load_openapi_spec()
    return loaded


def _principal(
    role: str, spec: dict[str, Any], grants: tuple[AccountGrant, ...] = ()
) -> PrincipalSnapshot:
    """The caller as the contract's `x-permissions` define the role (the owner holds every code)."""
    codes = frozenset(Permission) if role == "owner" else None
    perms = codes or frozenset(Permission(p) for p in spec["x-permissions"][role])
    return PrincipalSnapshot(CALLER, frozenset({role}), perms, grants)


def _client(w: _World, snap: PrincipalSnapshot | None, **wired: Any) -> TestClient:
    """`wired` replaces the router's arguments (`user_disable=None`, `auth=_Auth(...)`, ...)."""
    args: dict[str, Any] = {
        "store": None,
        "emitter": w,
        "principal_resolver": SimpleNamespace(resolve=lambda request: snap),
        "notifier": object(),
        "auth": _Auth(w.log),
        "user_disable": w.svc,
    }
    app = FastAPI()
    app.include_router(make_users_router(**(args | wired)))
    return TestClient(app, headers={"Authorization": "Bearer tok"}, raise_server_exceptions=False)


def _conforms(spec: dict[str, Any], r: Any) -> None:
    """The answer is one the operation declares, and a refusal is the contract's `Problem`."""
    assert str(r.status_code) in spec["paths"]["/users/{userId}"]["delete"]["responses"]
    if r.status_code != 204:
        problem = {"$ref": "#/components/schemas/Problem", "components": spec["components"]}
        assert jsonschema.Draft202012Validator(problem).is_valid(r.json())


def _untouched(w: _World) -> bool:
    """Nothing was looked up, written or recorded as a change (a refusal's own record aside)."""
    return not w.rel.ran and not w.rel.committed and not w.of("users.disable")


def test_disable_answers_204_with_no_body_after_the_guards_in_order(spec: dict[str, Any]) -> None:
    """The guards pass silently, the step-up is consulted once, and only then are the counts
    read and `users.disable` written ahead of the commit (R7)."""
    w = _World()
    r = _client(w, _principal("owner", spec)).delete(_PATH.format(TARGET))
    assert r.status_code == 204 and r.content == b""
    _conforms(spec, r)
    assert w.log[:4] == ["step_up", "positions", "orders", "users.disable"] and w.rel.committed
    (record,) = w.of("users.disable")
    assert (record["actor_user_id"], record["object_id"]) == (CALLER, str(TARGET))
    assert record["after_state"]["positions_decision"] == "leave" and w.post_commit()


_DENIED, _STEP = ("rbac.denied",), ("step_up",)  # the log of a refusal, of a passed step-up
_ORDER = [  # role, target, elevated, query, status, code, log
    ("manager", TARGET, False, "", 403, "forbidden", _DENIED),
    ("viewer", TARGET, True, "?purge=true", 403, "forbidden", _DENIED),
    ("owner", CALLER, False, "", 403, "forbidden", _DENIED),
    ("owner", TARGET, False, "", 403, "step_up_required", _STEP),
    ("owner", TARGET, False, "?purge=true", 403, "step_up_required", _STEP),
    ("owner", TARGET, True, "?purge=true", 400, "validation_failed", _STEP),
    ("owner", TARGET, True, _BAD_ACK, 400, "validation_failed", _STEP),
]


@pytest.mark.parametrize(
    "case",
    _ORDER,
    ids=["role", "role-then-query", "self", "step-up", "step-up-then-query", "purge", "ack"],
)
def test_guard_order_before_change(case: tuple[Any, ...], spec: dict[str, Any]) -> None:
    """UL1-S1, SR-025: `users:write`, then a self-target (refusals no step-up can cure, audited,
    before any read), then the step-up, then the query, then the change. No refusal reads or
    writes a row, and only the step-up refusal issues a challenge."""
    role, target, elevated, query, status, code, log = case
    w = _World()
    auth = _Auth(w.log, elevated=elevated)
    r = _client(w, _principal(role, spec), auth=auth).delete(_PATH.format(target) + query)
    assert (r.status_code, r.json()["code"]) == (status, code)
    _conforms(spec, r)
    assert tuple(w.log) == log and _untouched(w)
    assert auth.pending == ([(str(SESSION), "users")] if code == "step_up_required" else [])


@pytest.mark.parametrize(
    ("role", "grants"),
    [("manager", ()), ("manager", _HELD), ("viewer", ())],
    ids=["manager-without-grant", "manager-with-grant", "viewer"],
)
def test_forbidden_manager_viewer_audited(
    role: str, grants: tuple[AccountGrant, ...], spec: dict[str, Any]
) -> None:
    """D1, UL1-E1, UL-AC06, C-12.4: a Manager or Viewer, grant or none, gets one 403 body for an
    existing and a missing id (U25), audited naming each target, before anything is looked up."""
    w = _World()
    client = _client(w, _principal(role, spec, grants))
    seen = [client.delete(_PATH.format(x) + "?purge=true") for x in (TARGET, MISSING)]
    assert [r.status_code for r in seen] == [403, 403] and seen[0].json() == seen[1].json()
    assert seen[0].json()["reason"] == "forbidden_role"
    _conforms(spec, seen[0])
    assert _untouched(w)
    assert [(c["action"], c["actor_user_id"]) for c in w.calls] == [("rbac.denied", CALLER)] * 2
    assert [(c["object_kind"], c["object_id"]) for c in w.calls] == [
        ("user", str(TARGET)),
        ("user", str(MISSING)),
    ]
    assert {c["reason"] for c in w.calls} == {"missing_permission:users:write:none"}


def test_self_target_403(spec: dict[str, Any]) -> None:
    """AC6, SR-055: disabling oneself is refused and audited before anything is read (never a
    challenge, whatever the step-up: the guard-order case `self`)."""
    w = _World()
    r = _client(w, _principal("owner", spec)).delete(_PATH.format(CALLER))
    assert (r.status_code, r.json()["reason"]) == (403, "self_target")
    _conforms(spec, r)
    assert _untouched(w) and w.log == ["rbac.denied"]
    (record,) = w.calls
    assert (record["reason"], record["outcome"]) == ("self_target", "denied")
    assert (record["actor_user_id"], record["object_id"]) == (CALLER, str(CALLER))


def test_last_owner_409(spec: dict[str, Any]) -> None:
    """AC6, SR-055, D6: the last active owner is not disabled, and nothing is written for it."""
    w = _World(_Rel(roles=("owner",), owners=1))
    r = _client(w, _principal("owner", spec)).delete(_PATH.format(TARGET))
    assert (r.status_code, r.json()["code"]) == (409, "conflict")
    _conforms(spec, r)
    assert not w.rel.committed and w.calls == [] and w.post_commit() == []


@pytest.mark.parametrize(
    ("failing", "role", "target"),
    [
        ("users.disable", "owner", TARGET),
        ("rbac.denied", "manager", TARGET),
        ("rbac.denied", "owner", CALLER),
    ],
    ids=["write-ahead-record", "refusal-of-a-role", "refusal-of-a-self-target"],
)
def test_audit_down_503(failing: str, role: str, target: uuid.UUID, spec: dict[str, Any]) -> None:
    """AC8, C-2.9, UL-AC05: with the audit writer down the call is 503 `audit_unavailable` with
    `Retry-After`, and nothing changes: the write-ahead record rolls the transaction back, and a
    refusal that cannot be recorded is not told 403, with nothing read."""
    w = _World(fail={failing: [AuditUnavailable("wal at 10.1.2.3 unwritable")]})
    r = _client(w, _principal(role, spec)).delete(_PATH.format(target))
    assert (r.status_code, r.json()["code"]) == (503, "audit_unavailable")
    _conforms(spec, r)
    assert r.headers["Retry-After"] == str(r.json()["retry_after_seconds"])
    assert "10.1.2.3" not in r.text and not w.rel.committed and w.post_commit() == []
    assert all(c["outcome"] != "success" for c in w.of("users.disable"))
    assert (w.rel.ran == []) == (failing == "rbac.denied")


def test_positions_unknown_409(spec: dict[str, Any]) -> None:
    """AC7, O2, UL-AC04: an unknown open-position count needs `acknowledge_unknown_positions=true`;
    without it the call is 409 and nothing changes, with it the disable records `leave`."""
    w = _World(positions=None)
    c = _client(w, _principal("owner", spec))
    refused = c.delete(_PATH.format(TARGET))
    assert (refused.status_code, refused.json()["code"]) == (409, "positions_unknown")
    _conforms(spec, refused)
    assert not w.rel.committed and w.of("users.disable") == [] and w.post_commit() == []
    assert c.delete(_PATH.format(TARGET) + "?acknowledge_unknown_positions=true").status_code == 204
    (record,) = w.of("users.disable")
    after = record["after_state"]
    assert (after["positions_decision"], after["open_position_count"]) == ("leave", None)
    assert after["acknowledged_unknown_positions"] is True and w.rel.committed


def test_twice_204_one_audit(spec: dict[str, Any]) -> None:
    """AC5: a repeat is a 204 that changes nothing and writes no further `users.disable`."""
    w = _World()
    c = _client(w, _principal("owner", spec))
    first = c.delete(_PATH.format(TARGET))
    w.rel.rows[LOCK_USER] = [("disabled",)]  # what the commit left behind
    assert (first.status_code, c.delete(_PATH.format(TARGET)).status_code) == (204, 204)
    assert len(w.of("users.disable")) == 1
    assert w.rel.order().count(store_module._DISABLE) == 1  # the status was written once


@pytest.mark.parametrize(
    "value", ["true", "True", "1", "", "maybe", "False", "0", "false&purge=false", "false"]
)
def test_purge_400_flag_off(value: str, spec: dict[str, Any]) -> None:
    """UL4-D1: `?purge=true` is E42-T10's (S14), so until it serves it the answer is 400, flag or
    no flag (R8's `users_purge_enabled` is undecided, #2710, and none exists), and the disable is
    not done either. The boolean is strict: `true` or `false`, once. `False`, `0` and a repeat are
    what a lenient parse reads as false and would disable, so each is a 400 too."""
    status = 204 if value == "false" else 400
    w = _World()
    r = _client(w, _principal("owner", spec)).delete(_PATH.format(TARGET) + f"?purge={value}")
    assert r.status_code == status
    _conforms(spec, r)
    assert w.rel.committed == (status == 204)


@pytest.mark.parametrize(
    ("wired", "status", "code"),
    [
        ({"principal_resolver": SimpleNamespace(resolve=lambda r: None)}, 401, "unauthenticated"),
        ({"auth": "session-gone"}, 401, "unauthenticated"),
        ({"user_disable": None}, 501, "not_implemented"),
        ({"auth": None}, 501, "not_implemented"),
    ],
    ids=["no-session", "session-gone-at-the-gate", "no-service", "no-step-up"],
)
def test_unauthenticated_or_unwired_is_refused_before_any_read(
    wired: dict[str, Any], status: int, code: str, spec: dict[str, Any]
) -> None:
    """Nothing is wired on the fake backend (no store): never an unchecked disable."""
    w = _World()
    if wired.get("auth") == "session-gone":
        wired = {"auth": _Auth(w.log, session_error=SessionNotFound("gone"))}
    r = _client(w, _principal("owner", spec), **wired).delete(_PATH.format(TARGET))
    assert (r.status_code, r.json()["code"]) == (status, code)
    assert _untouched(w) and w.calls == []


@pytest.mark.parametrize(
    ("world", "status", "code"),
    [
        (lambda: _World(_Rel(status=None)), 404, "not_found"),
        (lambda: _World(_Rel(commit_error=OSError("10.1.2.3 reset"))), 503, "store_unavailable"),
        (lambda: _World(fail={"users.disable": [ValueError("bad")]}), 500, None),
        (lambda: _World(fail={"users.disable": [UserLifecycleError("new")]}), 500, None),
    ],
    ids=["unknown-user", "store-outage", "defect-is-no-outage", "unknown-refusal-is-a-defect"],
)
def test_store_answers_map_to_their_problem(
    world: Any, status: int, code: str | None, spec: dict[str, Any]
) -> None:
    """A missing user is 404; an outage is a retryable 503 without driver text (the commit's
    outcome is unknown, so a repeat is AC5's no-op if it landed); anything else, a refusal this
    route does not know too, is a 500."""
    r = _client(world(), _principal("owner", spec)).delete(_PATH.format(MISSING))
    assert r.status_code == status and "10.1.2.3" not in r.text and str(MISSING) not in r.text
    if code is not None:
        assert r.json()["code"] == code
        _conforms(spec, r)
    if status == 503:
        assert r.headers["Retry-After"] == str(r.json()["retry_after_seconds"])
