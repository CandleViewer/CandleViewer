"""Enrolment-only sweep over every mounted route of the RBAC matrix (#2295 slice 2/3, SR-018).

The pack's real `create_app()` world, where the owner is a user with `mfa_required` and no
confirmed method. The owner holds every permission, so any refusal here is the enrolment guard's
and never RBAC's (forbidden-role case: no role lifts it); every other actor keeps TOTP and sees no
change (cross-user case). Parametrised over the rows of every mounted route: the pack's totality
test makes a newly mounted route's row `executed`, and from then on this sweep covers it. A
`public: true` row needs no session, so the owner's bearer changes nothing there. A refused
request writes only the guard's own `auth.mfa_enrollment_required` record (within its budget):
no handler ran.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
import yaml

from candleviewer.api.enrolment_guard import ENROLMENT_OPERATIONS, REFUSAL_ACTION
from candleviewer.auth.models import MfaMethodKind, SessionRecord
from candleviewer.auth.session_service import ENROLMENT_ONLY_LIFETIME
from tests.contract.rbac.rbac_harness import (
    ACTORS,
    INERT_DIGEST,
    MATRIX_PATH,
    World,
    bearer,
    fill_path,
    user_id_of,
)
from tests.unit.auth.auth_fakes import FakeUserRepository, make_user

with MATRIX_PATH.open(encoding="utf-8") as _fh:
    _OPS: dict[str, dict[str, Any]] = yaml.safe_load(_fh)["operations"]
_MOUNTED = sorted(k for k, row in _OPS.items() if row["state"] != "not_mounted")
_ALLOWED = {f"{method} {path}" for method, path in ENROLMENT_OPERATIONS}
_PUBLIC = {k for k, row in _OPS.items() if row.get("public") is True}
_CODE = "mfa_enrollment_required"
_OWNER = user_id_of("owner")


class _EnrolmentSessions:
    """The pack's session seam; the owner's sessions get the 15-minute lifetime of a session
    minted enrolment-only (Q7)."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    async def authenticate_access_token(self, token: str, **kw: Any) -> SessionRecord:
        record: SessionRecord = await self._inner.authenticate_access_token(token, **kw)
        if record.user_id != _OWNER:
            return record
        return record.model_copy(update={"expires_at": record.issued_at + ENROLMENT_ONLY_LIFETIME})

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


@pytest.fixture
def enrolling(world: World) -> Iterator[World]:
    auth = world.app.state.app_context.auth
    users = FakeUserRepository()
    for actor in ACTORS[:4]:
        methods = () if actor == "owner" else (MfaMethodKind.TOTP,)
        user = make_user(username=actor, password_hash=INERT_DIGEST, mfa_methods=methods)
        users.add(user.model_copy(update={"id": user_id_of(actor)}))
    inner, seeded = auth._sessions, auth._repository
    auth._sessions, auth._repository = _EnrolmentSessions(inner), users
    try:
        yield world
    finally:
        auth._sessions, auth._repository = inner, seeded


def _call(world: World, key: str, actor: str) -> Any:
    method, path = key.split(" ", 1)
    req = _OPS[key].get("request", {})
    body = req.get("json")
    return world.client.request(
        method,
        fill_path(path, req.get("path")),
        params=req.get("params"),
        json=body if body is not None else ({} if method in ("POST", "PUT", "PATCH") else None),
        headers={**bearer(actor), **req.get("headers", {})},
    )


def _code(resp: Any) -> object:
    try:
        return resp.json().get("code")
    except (ValueError, AttributeError):
        return None


def _handler_actions(world: World) -> list[str]:
    """Audit actions written by anything but the guard's own refusal record."""
    return [r["action"] for r in world.audit.records if r["action"] != REFUSAL_ACTION]


@pytest.mark.parametrize("key", _MOUNTED)
def test_enrolment_only_owner_reaches_only_the_allow_list(enrolling: World, key: str) -> None:
    resp = _call(enrolling, key, "owner")

    refused = resp.status_code == 403 and _code(resp) == _CODE
    expected = key not in _ALLOWED and key not in _PUBLIC
    assert refused is expected, f"{key}: {resp.status_code} {_code(resp)}"
    assert refused is False or _handler_actions(enrolling) == [], f"{key}: ran behind the refusal"


@pytest.mark.parametrize("actor", ["manager_with_grant", "manager_without_grant", "viewer"])
def test_cross_user_actors_with_a_method_are_untouched(enrolling: World, actor: str) -> None:
    for key in ("GET /auth/sessions", "GET /rules", "GET /admin/audit", "GET /health/live"):
        assert _code(_call(enrolling, key, actor)) != _CODE, f"{key} as {actor}"
    assert _call(enrolling, "GET /auth/sessions", actor).status_code == 200


def test_cross_user_enrolment_only_owner_cannot_end_another_users_session(
    enrolling: World,
) -> None:
    other = uuid.uuid5(user_id_of("viewer"), "session")

    resp = enrolling.client.delete(f"/me/sessions/{other}", headers=bearer("owner"))

    assert (resp.status_code, _code(resp)) == (403, _CODE)


def test_forbidden_role_dangerous_route_refuses_before_any_step_up_challenge(
    enrolling: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard sits outside the step-up guard: no pending challenge, no audit record."""
    challenged: list[str] = []

    async def record_pending(session_id: str, action_class: str) -> None:
        challenged.append(action_class)

    enrolling.step_up.elevated = False
    monkeypatch.setattr(enrolling.step_up, "record_pending", record_pending)
    target = user_id_of("viewer")

    resp = enrolling.client.post(f"/users/{target}/mfa/reset", headers=bearer("owner"), json={})

    assert (resp.status_code, _code(resp), challenged) == (403, _CODE, [])
    assert _handler_actions(enrolling) == []  # no reset record: the handler never ran
