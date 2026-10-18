"""Enrolment-only session on the composed app (#2295; contract #2661).

Real `create_app()` over the in-memory auth stack of `_stack.py`: the real session service and
user store, the real middleware order and the real WS path (`_session_authenticator` -> `/ws`).
Sessions are minted directly, as sign-in does; of the endpoints only refresh changes here (it
classifies the presented session). One fake instant drives the auth stack and the gateway's
wall clock. Each refusal must leave a trail: the audit record and the scraped metric.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from structlog.testing import capture_logs

from candleviewer.api.enrolment_guard import REFUSAL_ACTION
from candleviewer.audit.models import AuditOutcome
from candleviewer.auth.models import MfaMethodKind, MintedSession, UserRecord, UserStatus
from candleviewer.auth.session_service import ENROLMENT_ONLY_LIFETIME
from candleviewer.ws.metrics import (
    AUTH_FAILURE_REASONS,
    cv_ws_auth_failures_total,
    cv_ws_closes_total,
)
from tests.csrf_helpers import csrf_headers
from tests.unit.auth.auth_fakes import make_user
from tests.unit.auth.session_fakes import FakeSessionRepository
from tests.unit.ws.test_lifecycle_socket import _closed, _recv, _recv_type

from ._stack import ORIGIN, T0, Stack

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


def _session_row(stack: Stack, minted: MintedSession) -> Any:
    return stack.auth._session_repository.sessions[str(minted.session_id)]


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


def test_a_full_session_whose_user_lost_every_method_cannot_enrol_even_near_its_expiry(
    stack: Stack,
) -> None:
    """It proved a second factor its user no longer has, so it was not minted enrolment-only
    (C-12.4): inside 15 minutes of its expiry too it gets the expired 401, never the enrolment
    operations, so it cannot enrol another TOTP (#2295 review)."""
    uid, _ = stack.add_user("member")
    expires_at = stack.clock.now + ENROLMENT_ONLY_LIFETIME
    minted: MintedSession = stack.call(stack.auth.sessions.mint, str(uid), expires_at=expires_at)
    _lose_every_method(stack, _user(stack, "member"))

    resp = stack.client.post("/auth/mfa/enroll", headers=_headers(stack, minted), json={})

    assert (resp.status_code, resp.json()["code"]) == (401, "unauthenticated")


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


def _dead_successor(stack: Stack) -> tuple[MintedSession, dict[str, str]]:
    """Refreshed at minute 10, its access handle lives to minute 22; the session ends at 15."""
    minted, _ = _mint(stack, _enrolling(stack))
    stack.clock.now += timedelta(minutes=10)
    successor: MintedSession = stack.call(stack.auth.sessions.refresh, minted.refresh_token).minted
    stack.clock.now = T0 + timedelta(minutes=16)
    return successor, _headers(stack, successor)


def test_a_dead_enrolment_only_session_is_refused_as_expired_not_as_enrolment_only(
    stack: Stack,
) -> None:
    successor, headers = _dead_successor(stack)
    before = _refusals(stack, "http", "expired")

    resp = stack.client.get("/auth/sessions", headers=headers)

    # #3183 (gap J): the guard's lookup refuses a session past its absolute expiry, so the route
    # answers 401 and revokes it as `expired`; it is never classified, so nothing counts here.
    assert resp.status_code == 401
    assert _session_row(stack, successor).revoked_reason == "expired"
    assert _refusals(stack, "http", "expired") == before
    assert stack.audit.of(REFUSAL_ACTION) == []  # a dead session, not an authorisation denial


def test_refresh_of_a_dead_enrolment_only_session_is_refused_before_any_audit(
    stack: Stack,
) -> None:
    successor, _ = _dead_successor(stack)

    resp = _refresh(stack, successor)

    assert (resp.status_code, resp.json()["detail"]) == (401, "refresh_token_invalid")
    assert stack.audit.of("auth.session_refreshed") == []  # refused before the write-ahead row


def test_refresh_rotates_an_enrolment_only_session_inside_its_window(stack: Stack) -> None:
    minted, _ = _mint(stack, _enrolling(stack))
    stack.clock.now += timedelta(minutes=5)

    resp = _refresh(stack, minted)

    assert resp.status_code == 200
    successor = stack.call(stack.auth.sessions.peek_refresh, resp.json()["tokens"]["refresh_token"])
    assert successor.expires_at == minted.expires_at  # refresh never extends it (Q7)


# -- WebSocket -------------------------------------------------------------------------------


def _failures() -> float:
    total: float = sum(
        cv_ws_auth_failures_total.labels(reason=r)._value.get() for r in AUTH_FAILURE_REASONS
    )
    return total


def _closes() -> float:
    """Sockets closed with `bye mfa_enrollment_required` (the gateway counts the close first)."""
    return float(cv_ws_closes_total.labels(reason=_CODE)._value.get())


def _hello_auth(ws: Any, token: str) -> dict[str, Any]:
    ws.send_json({"t": "hello", "id": "h", "p": {}})
    assert _recv(ws)["t"] == "welcome"
    ws.send_json({"t": "auth", "id": "a", "p": {"access_token": token}})
    return _recv(ws)


def _socket(stack: Stack) -> Any:
    headers = {"origin": ORIGIN}
    return stack.client.websocket_connect("/ws", subprotocols=["cv.v1.json"], headers=headers)


def test_ws_refuses_an_enrolment_only_session_at_auth_and_never_registers_it(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    minted, _ = _mint(stack, _enrolling(stack))
    registered: list[object] = []
    for target in (stack.state.revocation_hub, stack.state.ws_registry):
        monkeypatch.setattr(target, "register", lambda *a, **_k: registered.append(a))
    before = _failures()

    with _socket(stack) as ws:
        bye = _hello_auth(ws, minted.access_token)
        code = _closed(ws)

    assert (bye["t"], bye["p"]["reason"], bye["p"]["code"], code) == ("bye", _CODE, 4403, 4403)
    assert bye["p"]["reconnect"] is False
    assert _failures() == before  # not a failed `auth`
    assert registered == []


def test_ws_refusal_is_audited_and_counted_on_the_scraped_registry(stack: Stack) -> None:
    """The socket refusal leaves the trail the HTTP one does, source address included, though
    the socket never authenticated (its close is not audited: `ws.connection.closed` needs a
    user)."""
    user = _enrolling(stack)
    minted, _ = _mint(stack, user)
    before = _refusals(stack, "ws", "enrolment_only")

    with capture_logs() as logs, _socket(stack) as ws:
        _hello_auth(ws, minted.access_token)
        _closed(ws)

    (record,) = stack.audit.of(REFUSAL_ACTION)
    assert (record["actor_user_id"], record["session_id"], record["actor_ip"]) == (
        user.id,
        minted.session_id,
        "127.0.0.1",
    )
    assert record["after_state"] == {"channel": "ws", "method": "GET", "path": "/ws"}
    assert _refusals(stack, "ws", "enrolment_only") == before + 1
    (line,) = [e for e in logs if e["event"] == "ws auth refused"]
    assert (line["reason"], line["source_ip"]) == (_CODE, "127.0.0.1")


def test_ws_cross_user_serves_a_full_session_then_refuses_a_password_only_re_auth(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refused at once (§4.3): the socket is sealed before the refusal's audit write starts, so
    nothing of the earlier identity waits on a slow writer, whose record still lands. The re-auth
    presents a session of the same user minted on the password alone: enrolment-only."""
    _enrolling(stack)  # another user needing enrolment changes nothing here
    uid, _ = stack.add_user("member")
    full: MintedSession = stack.call(stack.auth.sessions.mint, str(uid))
    password_only, _ = _mint(stack, _user(stack, "member"))
    release, emit, closes, sealed_first = asyncio.Event(), stack.audit.emit, _closes(), []

    async def slow(action: str, **kw: Any) -> None:
        if action == REFUSAL_ACTION:  # held until the client has its `bye`
            sealed_first.append(_closes() == closes + 1)
            await release.wait()
        await emit(action, **kw)

    monkeypatch.setattr(stack.audit, "emit", slow)

    with _socket(stack) as ws:
        assert _hello_auth(ws, full.access_token)["t"] == "auth_ok"
        ws.send_json({"t": "auth", "id": "a2", "p": {"access_token": password_only.access_token}})
        bye = _recv_type(ws, "bye")
        code = _closed(ws)
        stack.call(release.set)

    assert (bye["p"]["reason"], code) == (_CODE, 4403)
    assert sealed_first == [True]
    assert stack.call(stack.state.csrf_refusal_audits.drain) == 0
    assert len(stack.audit.of(REFUSAL_ACTION)) == 1


def test_ws_serves_a_full_verdict_only(stack: Stack, monkeypatch: pytest.MonkeyPatch) -> None:
    """Deny by default (C-12.4), as the HTTP guard's allow-list: a verdict the socket does not
    know (a later class, or a fake's plain string) is a failed `auth`, never `auth_ok`."""
    headers, _ = _member(stack)

    async def unknown(_session: Any) -> Any:
        return "full"  # equal to `SessionClass.FULL`, yet not that member

    monkeypatch.setattr(stack.auth, "classify", unknown)
    before = _refusals(stack, "ws", "expired")

    with _socket(stack) as ws:
        reply = _hello_auth(ws, headers["Authorization"].removeprefix("Bearer "))

    assert (reply["t"], reply["p"]["code"]) == ("err", "auth_failed")
    assert _refusals(stack, "ws", "expired") == before + 1


def test_ws_auth_fails_closed_when_the_session_cannot_be_classified(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deny by default (C-12.4), the twin of the HTTP 503: a live token whose user cannot be
    read gets a failed `auth`, counted and logged as `unclassified`, never `auth_ok`."""
    uid, _ = stack.add_user("member")
    minted: MintedSession = stack.call(stack.auth.sessions.mint, str(uid))

    async def unreachable(user_id: str) -> UserRecord | None:
        raise OSError("user store unreachable")

    monkeypatch.setattr(stack.users, "find_by_id", unreachable)
    failures, before = _failures(), _refusals(stack, "ws", "unclassified")

    with capture_logs() as logs, _socket(stack) as ws:
        reply = _hello_auth(ws, minted.access_token)

    assert (reply["t"], reply["p"]["code"]) == ("err", "auth_failed")
    assert _failures() == failures + 1
    assert _refusals(stack, "ws", "unclassified") == before + 1
    (line,) = [e for e in logs if e["event"] == "auth.enrolment_only.unclassified"]
    assert (line["log_level"], line["channel"], line["error"]) == ("error", "ws", "OSError")
    assert (line["session_id"], line["user_id"]) == (str(minted.session_id), str(uid))
    assert "unreachable" not in f"{reply}{logs}"  # the failure text reaches no one


def test_ws_refuses_an_overlong_session_like_an_expired_token(stack: Stack) -> None:
    """HTTP answers 401 ("sign in again"), so the socket does not say "enrol, then connect":
    a failed `auth` (§4.3), counted, the socket left open for another attempt."""
    headers, user = _member(stack)
    token = headers["Authorization"].removeprefix("Bearer ")
    _lose_every_method(stack, user)
    before, expired = _failures(), _refusals(stack, "ws", "expired")

    with _socket(stack) as ws:
        err = _hello_auth(ws, token)
        ws.send_json({"t": "ping", "id": "p"})
        pong = _recv_type(ws, "pong")

    assert (err["t"], err["p"]["code"], pong["t"]) == ("err", "auth_failed", "pong")
    assert _failures() == before + 1
    assert _refusals(stack, "ws", "expired") == expired + 1
    assert stack.audit.of(REFUSAL_ACTION) == []


def test_ws_re_auth_of_an_overlong_session_fails_like_any_failed_re_auth(stack: Stack) -> None:
    """§4.3 as built: a failed re-`auth` keeps the prior identity until its token expires."""
    headers, user = _member(stack)
    token = headers["Authorization"].removeprefix("Bearer ")

    with _socket(stack) as ws:
        assert _hello_auth(ws, token)["t"] == "auth_ok"
        _lose_every_method(stack, user)
        ws.send_json({"t": "auth", "id": "a2", "p": {"access_token": token}})
        err = _recv_type(ws, "err")
        ws.send_json({"t": "ping", "id": "p"})
        pong = _recv_type(ws, "pong")

    assert (err["p"]["code"], pong["t"]) == ("auth_failed", "pong")


# -- #2911 answers a disabled or deleted user's session (USER_INACTIVE) ------------------------


def _deactivate(stack: Stack, user: UserRecord, status: UserStatus | None) -> None:
    """Disable *user* (`None`: delete it) in the user store and the session store's join alike,
    as the one Postgres `users` row reads in both (#2911)."""
    stack.auth._session_repository.user_statuses[str(user.id)] = status
    if status is None:
        del stack.users.users[str(user.id)]
    else:
        stack.users.add(user.model_copy(update={"status": status}))


def _full_session(stack: Stack) -> tuple[MintedSession, UserRecord]:
    """A full 12-hour session whose user then loses every method (a missed disable's state)."""
    uid, _ = stack.add_user("member")
    minted: MintedSession = stack.call(stack.auth.sessions.mint, str(uid))
    return minted, _user(stack, "member")


@pytest.mark.parametrize("status", [None, UserStatus.DISABLED])
def test_a_deleted_or_disabled_users_session_is_revoked_by_its_next_request(
    stack: Stack, status: UserStatus | None
) -> None:
    """SR-029, not the enrolment gate: the route's `require_active` revokes the session as
    `user_disabled`, counts the breach signal and ends its open socket (`bye user_disabled`)."""
    minted, user = _full_session(stack)
    before = stack.scraped("auth_disabled_user_sessions_revoked_total")

    with _socket(stack) as ws:
        assert _hello_auth(ws, minted.access_token)["t"] == "auth_ok"
        _lose_every_method(stack, user)
        _deactivate(stack, _user(stack, "member"), status)
        with capture_logs() as logs:
            resp = stack.client.get("/auth/sessions", headers=_headers(stack, minted))
        bye = _recv_type(ws, "bye")
        code = _closed(ws)

    assert resp.status_code == 401
    assert (bye["p"]["reason"], bye["p"]["code"], code) == ("user_disabled", 4403, 4403)
    assert _session_row(stack, minted).revoked_reason == "user_disabled"
    assert stack.scraped("auth_disabled_user_sessions_revoked_total") == before + 1
    assert stack.audit.of(REFUSAL_ACTION) == []
    assert [e for e in logs if e["event"].startswith("auth.enrolment_only.")] == []


@pytest.mark.parametrize("status", [None, UserStatus.DISABLED])
def test_refresh_of_a_deleted_or_disabled_users_session_writes_the_2911_denial(
    stack: Stack, status: UserStatus | None
) -> None:
    """Refresh's classification leaves the session to `refresh`, whose #2911 check refuses it
    after the intent record and records the denied `user_disabled` outcome (C-2.9)."""
    minted, user = _full_session(stack)
    _lose_every_method(stack, user)
    _deactivate(stack, _user(stack, "member"), status)
    before = _refusals(stack, "http", "expired")

    resp = _refresh(stack, minted)

    assert (resp.status_code, resp.json()["detail"]) == (401, "refresh_token_invalid")
    denied = [r for r in stack.audit.of("auth.session_refreshed") if r.get("reason")]
    assert [(r["outcome"], r["reason"]) for r in denied] == [(AuditOutcome.DENIED, "user_disabled")]
    assert _refusals(stack, "http", "expired") == before


def test_ws_auth_of_a_user_gone_since_its_lookup_is_closed_as_disabled_uncounted(
    stack: Stack,
) -> None:
    """The socket's strict lookup refuses a disabled or deleted user's session first; a user gone
    from the user store since then is closed as a late registration is (#3413): `bye
    user_disabled`, 4403, counted neither as a failed `auth` nor as an enrolment refusal."""
    minted, user = _full_session(stack)
    del stack.users.users[str(user.id)]  # the session row still reads it active: a race
    failures, expired = _failures(), _refusals(stack, "ws", "expired")

    with _socket(stack) as ws:
        bye = _hello_auth(ws, minted.access_token)
        code = _closed(ws)

    assert (bye["t"], bye["p"]["reason"], bye["p"]["reconnect"], code) == (
        "bye",
        "user_disabled",
        False,
        4403,
    )
    assert (_failures(), _refusals(stack, "ws", "expired")) == (failures, expired)
    assert stack.audit.of(REFUSAL_ACTION) == []
