"""SR-013 (#2101): a granted step-up rotates the session, at the router (the ruling's C-3 to C-8).

The `200` carries the new session's `tokens` and its rotated cookies, `no-store`, and
`X-CSRF-Token` under the desktop flag; the grants carry over and accumulate; the rotation is
audited after the grant, each record ahead of its change (`auth.session_revoked` through B16
`REVOKE`, then `auth.session_created`); the audit writer's readiness is checked before any
factor; a refused rotation record ends the grant (`503`); a lost claim or a failed mint voids the
announced session (`401`). Over `test_step_up_router._build`: the real `StepUpService`,
`SessionService` and B16 chart on the in-memory rows.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any, cast

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient

from candleviewer.api.cors import FLAG_STATE_KEY
from candleviewer.auth.csrf import CSRF_COOKIE, CSRF_HEADER, CsrfVerdict
from candleviewer.auth.models import SessionRecord, UserStatus
from candleviewer.auth.session_service import hash_access_token
from tests.unit.api.test_step_up_router import (
    _H,
    _PW,
    CSRF,
    _build,
    _code,
    _modal_body,
    _rotated,
)
from tests.unit.auth.session_fakes import FakeSessionRepository


def _rows(c: TestClient) -> FakeSessionRepository:
    rows: FakeSessionRepository = cast(FastAPI, c.app).state.rows
    return rows


def _live(c: TestClient, user: uuid.UUID) -> list[SessionRecord]:
    return [s for s in _rows(c).sessions.values() if s.user_id == user and s.revoked_at is None]


def _users_body(seed: bytes, clock: Any) -> dict[str, str]:
    return {"code": _code(seed, clock), "password": _PW, "action_class": "users"}


def _sid(c: TestClient, response: Any) -> str:
    """The session a step-up's new access token names."""
    jti = hash_access_token(response.json()["tokens"]["access_token"])
    (row,) = [s for s in _rows(c).sessions.values() if s.access_token_jti == jti]
    return str(row.id)


async def test_step_up_answers_with_the_rotated_session_its_cookies_and_no_store() -> None:
    c, _em, seed, clock, user = await _build()
    (old,) = _live(c, user)

    ok = c.post("/auth/step-up", headers=_H, json=_users_body(seed, clock))

    assert ok.status_code == 200
    tokens = ok.json()["tokens"]
    assert (tokens["token_type"], tokens["refresh_token"]) == ("Bearer", None)
    assert ok.headers["cache-control"] == "no-store"
    (new,) = _live(c, user)
    assert new.id != old.id and new.id == uuid.UUID(_sid(c, ok))
    assert _rows(c).sessions[str(old.id)].revoked_reason == "rotated"
    csrf = ok.cookies.get(CSRF_COOKIE)
    assert csrf is not None and CSRF.verify(csrf, str(new.id)) is CsrfVerdict.OK
    assert CSRF.verify(csrf, str(old.id)) is not CsrfVerdict.OK  # bound to the new session only
    assert ok.cookies.get("cv_refresh")
    assert CSRF_HEADER not in ok.headers  # the desktop flag is off for this request


async def test_step_up_sends_the_new_csrf_token_in_the_header_under_the_desktop_flag() -> None:
    """C-4 (ADR-0038 F5): with the flag kept on for a listed `Origin`, the eighth issuing
    operation carries the token it set, as refresh does."""
    c, _em, seed, clock, user = await _build()
    app = cast(FastAPI, c.app)

    @app.middleware("http")
    async def listed(request: Request, call_next: Any) -> Response:
        request.scope.setdefault("state", {})[FLAG_STATE_KEY] = True
        response: Response = await call_next(request)
        return response

    ok = TestClient(app).post("/auth/step-up", headers=_H, json=_users_body(seed, clock))

    assert ok.status_code == 200
    assert ok.headers[CSRF_HEADER] == ok.cookies.get(CSRF_COOKIE)
    (new,) = _live(c, user)
    assert CSRF.verify(ok.headers[CSRF_HEADER], str(new.id)) is CsrfVerdict.OK


async def test_step_up_grants_accumulate_across_two_rotations() -> None:
    """C-5: the second step-up's successor holds the first one's window and its own."""
    c, _em, seed, clock, user = await _build()
    keys = c.post(
        "/auth/step-up",
        headers=_H,
        json={"code": _code(seed, clock), "password": _PW, "action_class": "keys"},
    )
    clock.now = clock.now + timedelta(seconds=30)  # the next TOTP step: codes are single-use
    users = c.post("/auth/step-up", headers=_rotated(keys), json=_users_body(seed, clock))

    assert users.status_code == 200
    (new,) = _live(c, user)
    assert {"keys", "users"} <= set(new.step_up_elevations)
    h = _rotated(users)
    assert c.post("/exchange-accounts/a1/keys/k1/rotate", headers=h).status_code == 200
    assert c.post(f"/users/{uuid.uuid4()}/invite", headers=h).status_code == 200


async def test_step_up_rotation_drops_the_pending_challenge() -> None:
    c, _em, seed, clock, user = await _build()
    denied = c.post(f"/users/{uuid.uuid4()}/invite", headers=_H)

    ok = c.post("/auth/step-up", headers=_H, json=_modal_body(_code(seed, clock), denied))

    assert ok.status_code == 200
    (new,) = _live(c, user)
    assert not [k for k in new.step_up_elevations if k.startswith("pending:")]


async def test_step_up_audits_the_rotation_after_the_grant_each_record_ahead() -> None:
    """C-7: `auth.step_up_granted`, then `auth.session_revoked` (`rotated`, the old session),
    then `auth.session_created` naming the new session and the old one in `rotated_from`."""
    c, em, seed, clock, user = await _build()
    (old,) = _live(c, user)

    ok = c.post("/auth/step-up", headers=_H, json=_users_body(seed, clock))

    rows = [
        r
        for r in em.calls
        if r["action"] in ("auth.step_up_granted", "auth.session_revoked", "auth.session_created")
    ]
    assert [r["action"] for r in rows] == [
        "auth.step_up_granted",
        "auth.session_revoked",
        "auth.session_created",
    ]
    granted, revoked, created = rows
    new = _sid(c, ok)
    assert (granted["session_id"], revoked["session_id"]) == (str(old.id), str(old.id))
    assert revoked["reason"] == "rotated"
    assert str(created["session_id"]) == new
    assert created["after_state"] == {"rotated_from": str(old.id)}
    assert created["actor_user_id"] == user  # the cross-user case: the step-up's own user


async def test_step_up_with_the_audit_writer_down_is_503_before_any_factor() -> None:
    """C-7: no factor is checked, so no strike is counted and the code stays unspent."""
    c, em, seed, clock, user = await _build(audit_ok=False)
    code = _code(seed, clock)

    down = c.post("/auth/step-up", headers=_H, json={**_users_body(seed, clock), "code": code})

    assert (down.status_code, down.json()["code"]) == (503, "audit_unavailable")
    assert not em.calls
    (row,) = _live(c, user)
    assert row.step_up_failures == 0 and row.step_up_elevations == {}
    cast(FastAPI, c.app).state.audit_ok = True
    again = c.post("/auth/step-up", headers=_H, json={**_users_body(seed, clock), "code": code})
    assert again.status_code == 200  # the same code: the 503 spent none of it


@pytest.mark.parametrize("refused", ["auth.session_revoked", "auth.session_created"])
async def test_step_up_whose_rotation_record_is_refused_ends_the_grant_and_is_503(
    refused: str,
) -> None:
    """C-7: a rotation record refused after the grant: `503`, nothing elevated or rotated, and
    the old bearer still works, unelevated."""
    c, em, seed, clock, user = await _build()
    (old,) = _live(c, user)
    em.fail_on = frozenset({refused})

    r = c.post("/auth/step-up", headers=_H, json=_users_body(seed, clock))

    assert (r.status_code, r.json()["code"]) == (503, "audit_unavailable")
    assert "tokens" not in r.json()
    assert [s.id for s in _live(c, user)] == [old.id]
    assert "users" not in _rows(c).sessions[str(old.id)].step_up_elevations
    em.fail_on = frozenset()
    gated = c.post(f"/users/{uuid.uuid4()}/invite", headers=_H)
    assert (gated.status_code, gated.json()["code"]) == (403, "step_up_required")


async def test_step_up_that_loses_the_claim_voids_the_announced_session_and_is_401() -> None:
    """C-8: another request ended the session between the grant and the claim (a refresh, a
    logout): exactly one wins, so the step-up mints nothing and answers `401`."""
    c, em, seed, clock, user = await _build()
    (old,) = _live(c, user)
    rows = _rows(c)
    claim = rows.revoke

    async def raced(session_id: str, *, reason: str, now: Any) -> Any:
        await claim(session_id, reason="logout", now=now)  # the other request won
        return await claim(session_id, reason=reason, now=now)

    rows.revoke = raced  # type: ignore[method-assign]  # one claim, raced by a logout

    r = c.post("/auth/step-up", headers=_H, json=_users_body(seed, clock))

    assert (r.status_code, r.json()["code"]) == (401, "unauthenticated")
    assert not _live(c, user)
    (created,) = [x for x in em.calls if x["action"] == "auth.session_created"]
    (void,) = [x for x in em.calls if x["action"] == "auth.step_up_failed"]
    assert void["after_state"] == {
        "voids_session_created": str(created["session_id"]),
        "rotated_from": str(old.id),
    }
    assert void["session_id"] == created["session_id"]


async def test_step_up_whose_mint_is_refused_after_the_claim_voids_and_is_401() -> None:
    """C-7: the user was disabled after the claim: the claim stands, no successor exists."""
    c, em, seed, clock, user = await _build()
    (old,) = _live(c, user)
    _rows(c).user_statuses[str(user)] = UserStatus.DISABLED

    r = c.post("/auth/step-up", headers=_H, json=_users_body(seed, clock))

    assert (r.status_code, r.json()["code"]) == (401, "unauthenticated")
    assert _rows(c).sessions[str(old.id)].revoked_reason == "rotated"
    assert len(_rows(c).sessions) == 1
    assert [x["reason"] for x in em.calls if x["action"] == "auth.step_up_failed"] == ["unrotated"]


async def test_step_up_whose_claim_meets_a_store_outage_ends_the_grant_and_is_401() -> None:
    """Whether the claim landed is unknown: the announced session is voided, the grant ended on
    the row the claim may have left live, and the answer is `401`."""
    c, em, seed, clock, user = await _build()
    (old,) = _live(c, user)
    rows = _rows(c)

    async def down(session_id: str, *, reason: str, now: Any) -> Any:
        raise OSError("the store is unreachable")

    rows.revoke = down  # type: ignore[method-assign]  # the claim's store is down

    r = c.post("/auth/step-up", headers=_H, json=_users_body(seed, clock))

    assert (r.status_code, r.json()["code"]) == (401, "unauthenticated")
    assert "users" not in rows.sessions[str(old.id)].step_up_elevations
    assert [x["reason"] for x in em.calls if x["action"] == "auth.step_up_failed"] == ["unrotated"]


@pytest.mark.parametrize("password", ["wrong", _PW])
async def test_step_up_refused_rotates_nothing(password: str) -> None:
    """A wrong factor, or a wrong code: `401`, no rotation, the old bearer keeps working."""
    c, em, seed, clock, user = await _build()
    (old,) = _live(c, user)
    body = {"code": "000000" if password == _PW else _code(seed, clock), "password": password}

    r = c.post("/auth/step-up", headers=_H, json={**body, "action_class": "users"})

    assert r.status_code == 401 and r.json()["code"] == "mfa_invalid"
    assert [s.id for s in _live(c, user)] == [old.id]
    assert "auth.session_created" not in em.actions()


async def test_read_only_session_step_up_rotates_nothing() -> None:
    c, em, seed, clock, user = await _build()
    (old,) = _live(c, user)
    wrong = {"code": "000000", "password": _PW, "action_class": "users"}
    for _ in range(3):
        c.post("/auth/step-up", headers=_H, json=wrong)

    r = c.post("/auth/step-up", headers=_H, json=_users_body(seed, clock))

    assert (r.status_code, r.json()["code"]) == (403, "session_read_only")
    assert [s.id for s in _live(c, user)] == [old.id]
    assert "auth.session_created" not in em.actions()


async def test_a_non_owner_step_up_rotates_and_the_owner_route_still_refuses_403() -> None:
    """The forbidden-role case: a step-up proves who the caller is and grants no authority."""
    c, _em, seed, clock, user = await _build(owner_role=False)

    ok = c.post("/auth/step-up", headers=_H, json=_users_body(seed, clock))

    assert ok.status_code == 200
    r = c.post(f"/users/{uuid.uuid4()}/mfa/reset", headers=_rotated(ok))
    assert (r.status_code, r.json()["code"]) == (403, "forbidden")
    assert len(_live(c, user)) == 1


async def test_a_step_up_leaves_another_users_sessions_alone() -> None:
    """The cross-user case: only the caller's session rotates."""
    other = uuid.uuid4()
    c, em, seed, clock, user = await _build(target=other)
    (theirs,) = _live(c, other)

    ok = c.post("/auth/step-up", headers=_H, json=_users_body(seed, clock))

    assert ok.status_code == 200
    assert [s.id for s in _live(c, other)] == [theirs.id]
    assert {x["actor_user_id"] for x in em.calls if x["action"] == "auth.session_created"} == {user}
