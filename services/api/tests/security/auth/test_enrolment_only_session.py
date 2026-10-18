"""Enrolment-only session on the composed app (#2295; contract #2661).

Real `create_app()` over the in-memory auth stack of `_stack.py`: the real session service and
user store and the real middleware order. Sessions are minted directly, as sign-in does; of
the endpoints only refresh changes here (it classifies the presented session). One fake instant
drives the auth stack. Each refusal must leave a trail: the audit record and the scraped metric.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from candleviewer.api.enrolment_guard import REFUSAL_ACTION
from candleviewer.auth.models import MfaMethodKind, MintedSession, UserRecord, UserStatus
from candleviewer.auth.session_service import ENROLMENT_ONLY_LIFETIME
from tests.csrf_helpers import csrf_headers
from tests.unit.auth.auth_fakes import make_user
from tests.unit.auth.session_fakes import FakeSessionRepository

from ._stack import T0, Stack

_CODE = "mfa_enrollment_required"
_INERT_DIGEST = "unused"  # stored-hash placeholder: these users never sign in with a password


def _mint(stack: Stack, user: UserRecord, **kw: Any) -> tuple[MintedSession, dict[str, str]]:
    """A session minted directly, as sign-in does: no MFA, 15 minutes at most."""
    expires_at = stack.clock.now + ENROLMENT_ONLY_LIFETIME
    minted: MintedSession = stack.call(
        stack.auth.sessions.mint, str(user.id), mfa_satisfied=False, expires_at=expires_at, **kw
    )
    return minted, _headers(stack, minted)


def _headers(stack: Stack, minted: MintedSession) -> dict[str, str]:
    csrf = csrf_headers(stack.state.csrf_codec, minted.session_id)
    return {"Authorization": f"Bearer {minted.access_token}", **csrf}


def _enrolling(stack: Stack) -> UserRecord:
    """A user with `mfa_required` and no confirmed method."""
    user = make_user(username="enrolling", password_hash=_INERT_DIGEST, mfa_methods=())
    stack.users.add(user)
    return user


def _member(stack: Stack) -> tuple[dict[str, str], UserRecord]:
    """A full session (TOTP confirmed) and its user."""
    headers, _ = stack.principal("member", "viewer")
    return headers, _user(stack, "member")


def _user(stack: Stack, username: str) -> UserRecord:
    return next(u for u in stack.users.users.values() if u.username == username)


def _lose_every_method(stack: Stack, user: UserRecord) -> None:
    stack.users.add(user.model_copy(update={"mfa_methods": ()}))  # e.g. a recovery sign-in


def _refusals(stack: Stack, transport: str, reason: str) -> float:
    """`auth_enrolment_refused_total` as the scraped app registry serves it (SR-125)."""
    return stack.scraped("auth_enrolment_refused_total", transport=transport, reason=reason)


def _refresh(stack: Stack, minted: MintedSession, *, csrf: bool = True) -> Any:
    """`POST /auth/refresh` with the body token alone, as a client that lost its access handle
    sends it; `csrf=False` leaves out the SR-041 header."""
    stack.client.cookies.clear()
    headers = csrf_headers(stack.state.csrf_codec, minted.session_id) if csrf else {}
    return stack.client.post(
        "/auth/refresh", headers=headers, json={"refresh_token": minted.refresh_token}
    )


# -- HTTP ------------------------------------------------------------------------------------


def test_refresh_never_extends_the_fifteen_minute_lifetime(stack: Stack) -> None:
    minted, headers = _mint(stack, _enrolling(stack))
    assert stack.client.get("/auth/session", headers=headers).status_code == 200
    assert stack.client.get("/auth/sessions", headers=headers).json()["code"] == _CODE

    stack.clock.now += timedelta(minutes=10)
    successor: MintedSession = stack.call(stack.auth.sessions.refresh, minted.refresh_token).minted
    headers = _headers(stack, successor)
    assert successor.expires_at == T0 + ENROLMENT_ONLY_LIFETIME
    assert stack.client.get("/auth/session", headers=headers).status_code == 200
    stack.clock.now = T0 + ENROLMENT_ONLY_LIFETIME
    assert stack.client.get("/auth/session", headers=headers).status_code == 401


def test_an_idle_locked_enrolment_only_session_cannot_end_its_other_sessions(
    stack: Stack,
) -> None:
    """The idle-lock gate (#2300), mounted outside the guard, refuses a locked session on
    `DELETE /me/sessions/{sessionId}` first; either way the other session stays live."""
    user = _enrolling(stack)
    _, headers = _mint(stack, user, idle_timeout_s=300)
    other, _ = _mint(stack, user)
    stack.clock.now += timedelta(minutes=6)  # past the 5-minute idle lock, inside the lifetime

    resp = stack.client.delete(f"/me/sessions/{other.session_id}", headers=headers)

    assert (resp.status_code, resp.json()["code"]) == (401, "session_idle_locked")
    assert stack.call(stack.auth.sessions.require_active, str(other.session_id))  # still live


def test_the_restriction_follows_the_user_state_on_every_request(stack: Stack) -> None:
    headers, user = _member(stack)
    assert stack.client.get("/auth/sessions", headers=headers).status_code == 200

    _lose_every_method(stack, user)
    resp = stack.client.get("/auth/sessions", headers=headers)

    # Minted for 12 h, so never an enrolment-only session (Q7): refused like an expired one.
    assert (resp.status_code, resp.json()["code"]) == (401, "unauthenticated")
    assert stack.client.post("/auth/logout", headers=headers).status_code == 204


def test_a_password_only_session_stays_restricted_after_its_user_enrols(stack: Stack) -> None:
    """Defence in depth behind revoke-all at confirm: a session minted on the password alone
    never turns full, while one that proved the second factor is served."""
    user = _enrolling(stack)
    _, password_only = _mint(stack, user)
    stack.users.add(user.model_copy(update={"mfa_methods": (MfaMethodKind.TOTP,)}))
    proved: MintedSession = stack.call(stack.auth.sessions.mint, str(user.id))

    resp = stack.client.get("/auth/sessions", headers=password_only)

    assert (resp.status_code, resp.json()["code"]) == (403, _CODE)
    assert stack.client.get("/auth/sessions", headers=_headers(stack, proved)).status_code == 200


def test_http_refusal_is_audited_and_counted_on_the_scraped_registry(stack: Stack) -> None:
    user = _enrolling(stack)
    minted, headers = _mint(stack, user)
    before = _refusals(stack, "http", "enrolment_only")

    stack.client.get("/auth/sessions", headers=headers)

    (record,) = stack.audit.of(REFUSAL_ACTION)
    assert (record["actor_user_id"], record["session_id"], record["actor_ip"]) == (
        user.id,
        minted.session_id,
        "127.0.0.1",
    )
    assert record["after_state"] == {"channel": "http", "method": "GET", "path": "/auth/sessions"}
    assert _refusals(stack, "http", "enrolment_only") == before + 1


def test_a_carried_enrolment_only_bearer_never_blocks_sign_in_and_is_audited(
    stack: Stack,
) -> None:
    """Sign-in needs no session, so the guard leaves it alone: a client still holding the
    15-minute token signs in, and the carried foreign bearer is audited (E09-X02 AC2)."""
    _, carried = _mint(stack, _enrolling(stack))
    victim, seed = stack.add_user("victim")

    stack.sign_in("victim", seed, carried)  # asserts 200 for both steps

    (row,) = stack.audit.of("auth.session_fixation_attempt")
    assert (row["reason"], row["actor_user_id"]) == ("foreign_session", victim)
    assert stack.audit.of(REFUSAL_ACTION) == []


def test_refresh_ends_an_overlong_session_without_a_bearer(stack: Stack) -> None:
    """Q7: refresh does not keep a session the guard answers 401 alive until its 12 h expiry;
    it is refused before any audit write or rotation, so the client signs in again."""
    uid, _ = stack.add_user("member")
    minted: MintedSession = stack.call(stack.auth.sessions.mint, str(uid))
    _lose_every_method(stack, _user(stack, "member"))
    before = _refusals(stack, "http", "expired")

    resp = _refresh(stack, minted)

    assert (resp.status_code, resp.json()["detail"]) == (401, "refresh_token_invalid")
    assert stack.audit.of("auth.session_refreshed") == []
    presented = stack.call(stack.auth.sessions.peek_refresh, minted.refresh_token)
    assert presented is not None and not presented.is_revoked  # nothing rotated
    assert _refusals(stack, "http", "expired") == before + 1


def test_refresh_fails_closed_when_the_session_cannot_be_classified(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    minted, _ = _mint(stack, _enrolling(stack))

    async def unreachable(user_id: str) -> UserRecord | None:
        raise OSError("user store unreachable")

    monkeypatch.setattr(stack.users, "find_by_id", unreachable)
    before = _refusals(stack, "http", "unclassified")

    resp = _refresh(stack, minted)

    assert resp.status_code == 503 and "unreachable" not in resp.text
    assert (resp.json()["code"], resp.headers["Retry-After"]) == ("store_unavailable", "5")
    assert stack.audit.of("auth.session_refreshed") == []
    presented = stack.call(stack.auth.sessions.peek_refresh, minted.refresh_token)
    assert presented is not None and not presented.is_revoked  # nothing rotated
    assert _refusals(stack, "http", "unclassified") == before + 1


def test_refresh_checks_csrf_before_it_classifies_the_session(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SR-041 comes first: a refresh without the token reads no user store and counts nothing."""
    uid, _ = stack.add_user("member")
    minted: MintedSession = stack.call(stack.auth.sessions.mint, str(uid))
    _lose_every_method(stack, _user(stack, "member"))  # overlong: classified, it counts `expired`
    reads = AsyncMock(wraps=stack.users.find_by_id)
    monkeypatch.setattr(stack.users, "find_by_id", reads)
    before = _refusals(stack, "http", "expired")

    resp = _refresh(stack, minted, csrf=False)

    assert (resp.status_code, resp.json()["code"]) == (403, "csrf_token_invalid")
    reads.assert_not_called()
    assert _refusals(stack, "http", "expired") == before


def test_refresh_leaves_a_disabled_users_session_to_the_audited_refusal(stack: Stack) -> None:
    """A disabled user's session is #2911's to refuse: the denied `auth.session_refreshed` row is
    written, and the refusal is not counted as an expired enrolment-only session."""
    uid, _ = stack.add_user("member")
    minted: MintedSession = stack.call(stack.auth.sessions.mint, str(uid))
    stack.users.add(_user(stack, "member").model_copy(update={"status": UserStatus.DISABLED}))
    repo = cast(FakeSessionRepository, stack.auth._session_repository)
    repo.user_statuses[str(uid)] = UserStatus.DISABLED  # production reads one `users` row for both
    before = _refusals(stack, "http", "expired")

    resp = _refresh(stack, minted)

    assert (resp.status_code, resp.json()["detail"]) == (401, "refresh_token_invalid")
    denied = [r for r in stack.audit.of("auth.session_refreshed") if r["outcome"] == "denied"]
    assert [r["reason"] for r in denied] == ["user_disabled"]
    assert _refusals(stack, "http", "expired") == before


def test_refresh_rotates_an_enrolment_only_session_inside_its_window(stack: Stack) -> None:
    minted, _ = _mint(stack, _enrolling(stack))
    stack.clock.now += timedelta(minutes=5)

    resp = _refresh(stack, minted)

    assert resp.status_code == 200
    successor = stack.call(stack.auth.sessions.peek_refresh, resp.json()["tokens"]["refresh_token"])
    assert successor.expires_at == minted.expires_at  # refresh never extends it (Q7)
