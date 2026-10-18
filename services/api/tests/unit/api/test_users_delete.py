"""DELETE /users/{userId} (E42-T04 S6, #965; `deleteUser`, the disable).

The route over the real `UserDisableService` and S3 store, on `test_user_disable.py`'s world: what
is under test is the order of the guards and the problem each refusal becomes. The deployed app:
`tests/unit/architecture/test_owner_routes_composition.py`.
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
from candleviewer.api.step_up import make_read_only_guard
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


class _NoStepUp(_Auth):
    step_up_is_active = False


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


def _client(
    w: _World, snap: PrincipalSnapshot | None, *, guarded: bool = False, **wired: Any
) -> TestClient:
    """`wired` replaces the router's arguments (`user_disable=None`, `auth=_Auth(...)`, ...);
    `guarded` mounts the deployed app's path guard (`make_read_only_guard`) in front."""
    args: dict[str, Any] = {
        "store": None,
        "emitter": w,
        "principal_resolver": SimpleNamespace(resolve=lambda request: snap),
        "notifier": object(),
        "auth": _Auth(w.log),
        "user_disable": w.svc,
    } | wired
    app = FastAPI()
    if guarded:
        app.middleware("http")(make_read_only_guard(args["auth"]))
    app.include_router(make_users_router(**args))
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
    """R7: the step-up is asked once, then the counts are read and `users.disable` written ahead."""
    w = _World()
    r = _client(w, _principal("owner", spec)).delete(_PATH.format(TARGET))
    assert r.status_code == 204 and r.content == b""
    _conforms(spec, r)
    assert w.log[:4] == ["step_up", "positions", "orders", "users.disable"] and w.rel.committed
    (record,) = w.of("users.disable")
    assert (record["actor_user_id"], record["object_id"]) == (CALLER, str(TARGET))
    assert record["after_state"]["positions_decision"] == "leave" and w.post_commit()


_DENIED, _STEP = ("rbac.denied",), ("step_up",)  # the log of a refusal, of a passed step-up
_ORDER = [  # role, target, elevated, query, status, code, log, challenges issued
    ("manager", TARGET, False, "", 403, "forbidden", _DENIED, 0),
    ("viewer", TARGET, True, "?purge=true", 403, "forbidden", _DENIED, 0),
    ("owner", CALLER, False, "", 403, "forbidden", _DENIED, 0),
    ("owner", TARGET, False, "", 403, "step_up_required", _STEP, 1),
    ("owner", TARGET, False, "?purge=true", 403, "step_up_required", _STEP, 1),
    ("owner", TARGET, True, "?purge=true", 400, "validation_failed", _STEP, 0),
    ("owner", TARGET, True, _BAD_ACK, 400, "validation_failed", _STEP, 0),
    ("owner", TARGET, False, "?bogus=1", 403, "step_up_required", _STEP, 1),
    ("owner", TARGET, True, "?purge=true&bogus=1", 422, "validation_failed", _STEP, 0),
]


@pytest.mark.parametrize(
    "case",
    _ORDER,
    ids=[
        *("role", "role-then-query", "self", "step-up", "step-up-then-query", "purge", "ack"),
        *("step-up-then-names", "names-then-values"),
    ],
)
def test_guard_order_before_change(case: tuple[Any, ...], spec: dict[str, Any]) -> None:
    """UL1-S1, SR-025: `users:write`, a self-target (audited), the step-up, the query, then the
    change. No refusal reads or writes a row, and only the step-up's issues a challenge."""
    role, target, elevated, query, status, code, log, challenges = case
    w = _World()
    auth = _Auth(w.log, elevated=elevated)
    r = _client(w, _principal(role, spec), auth=auth).delete(_PATH.format(target) + query)
    assert (r.status_code, r.json()["code"]) == (status, code)
    _conforms(spec, r)
    assert tuple(w.log) == log and _untouched(w)
    assert auth.pending == [(str(SESSION), "users")] * challenges


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
    """AC6, SR-055: one's own account is refused and audited before any read, step-up or not."""
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
    """AC8, C-2.9, UL-AC05: audit down is 503 `audit_unavailable` with `Retry-After` and nothing
    changed: the write-ahead record rolls the change back, and an unrecorded refusal is no 403."""
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
    ("value", "status"),
    [
        *[("true", 400), ("True", 400), ("1", 400), ("", 400), ("maybe", 400), ("False", 400)],
        *[("0", 400), ("false&purge=false", 400), ("false", 204)],
    ],
)
def test_purge_400_flag_off(value: str, status: int, spec: dict[str, Any]) -> None:
    """UL4-D1: `?purge=true` is E42-T10's (S14): 400 until it serves it, flag or none (R8, #2710).
    A boolean is `true` or `false`, once: `False`, `0` and a repeat, which a lenient parse reads
    as false, are 400 too and disable nothing."""
    w = _World()
    r = _client(w, _principal("owner", spec)).delete(_PATH.format(TARGET) + f"?purge={value}")
    assert r.status_code == status and w.rel.committed == (status == 204)
    _conforms(spec, r)


@pytest.mark.parametrize(
    "query", ["?Purge=true", "?purge[]=true", "?bogus=1", "?userId=me", "?purge=false&x="]
)
def test_undeclared_query_key_422(query: str, spec: dict[str, Any]) -> None:
    """SR-026 on this owner route (S7; the S6 security review's Low 8): a key `deleteUser` does
    not declare is a 422 for any value, decided on the names after the step-up and before a value
    is read, so nothing is disabled; a target-user key is one more undeclared key (the path names
    the target)."""
    w = _World()
    r = _client(w, _principal("owner", spec)).delete(_PATH.format(TARGET) + query)
    assert (r.status_code, r.json()["code"]) == (422, "validation_failed")
    _conforms(spec, r)
    assert w.log == ["step_up"] and _untouched(w)
    assert {e["rule"] for e in r.json()["errors"]} == {"undeclared_parameter"}
    assert r.json()["detail"].endswith("takes only the query parameters its operation declares.")


@pytest.mark.parametrize(
    ("wired", "status", "code"),
    [
        ({"principal_resolver": SimpleNamespace(resolve=lambda r: None)}, 401, "unauthenticated"),
        ({"auth": _Auth([], session_error=SessionNotFound("gone"))}, 401, "unauthenticated"),
        ({"user_disable": None}, 501, "not_implemented"),
        ({"auth": None}, 501, "not_implemented"),
        ({"auth": SimpleNamespace(sessions_is_active=False)}, 501, "not_implemented"),
        ({"auth": _NoStepUp([])}, 503, "service_unavailable"),
    ],
    ids=["no-session", "session-gone", "no-service", "no-auth", "no-session-store", "no-step-up"],
)
def test_unauthenticated_or_unwired_is_refused_before_any_read(
    wired: dict[str, Any], status: int, code: str, spec: dict[str, Any]
) -> None:
    """Never an unchecked disable: 501 on the fake backend, 503 for sessions without a step-up."""
    w = _World()
    r = _client(w, _principal("owner", spec), **wired).delete(_PATH.format(TARGET))
    assert (r.status_code, r.json()["code"]) == (status, code)
    assert _untouched(w) and w.calls == []


def test_an_unwired_step_up_answers_as_the_deployed_guard(spec: dict[str, Any]) -> None:
    """S7, one answer (the S6 review's Low 6): sessions wired without a step-up are a wiring
    fault, `503 service_unavailable`, whether the deployed path guard answers it in front of the
    route or the route's own fallback does; the bodies match and nothing is read."""
    w, owner = _World(), _principal("owner", spec)
    own = _client(w, owner, auth=_NoStepUp([])).delete(_PATH.format(TARGET))
    guard = _client(w, owner, guarded=True, auth=_NoStepUp([])).delete(_PATH.format(TARGET))
    assert (own.status_code, own.json()["code"]) == (503, "service_unavailable")
    _conforms(spec, own)
    assert own.json() == guard.json() and _untouched(w) and w.calls == []


@pytest.mark.parametrize(
    ("world", "status", "code"),
    [
        (lambda: _World(_Rel(status=None)), 404, "not_found"),
        (lambda: _World(_Rel(commit_error=OSError("10.1.2.3 reset"))), 503, "store_unavailable"),
    ],
    ids=["unknown-user", "store-outage"],
)
def test_store_answers_map_to_their_problem(
    world: Any, status: int, code: str, spec: dict[str, Any]
) -> None:
    """A missing user is 404; an outage is a retryable 503 with no driver text (outcome unknown)."""
    r = _client(world(), _principal("owner", spec)).delete(_PATH.format(MISSING))
    assert (r.status_code, r.json()["code"]) == (status, code)
    _conforms(spec, r)
    assert "10.1.2.3" not in r.text and str(MISSING) not in r.text
    # `Retry-After` mirrors the body's `retry_after_seconds`, and is absent when there is none
    assert r.headers.get("Retry-After", "") == str(r.json().get("retry_after_seconds", ""))


@pytest.mark.parametrize("error", [ValueError("bad"), UserLifecycleError("new")])
def test_anything_else_is_a_500(error: Exception, spec: dict[str, Any]) -> None:
    """A defect, or a refusal this route does not know, is a 500 that names no id."""
    w = _World(fail={"users.disable": [error]})
    r = _client(w, _principal("owner", spec)).delete(_PATH.format(MISSING))
    assert r.status_code == 500 and str(MISSING) not in r.text
