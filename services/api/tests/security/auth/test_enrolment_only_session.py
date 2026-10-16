"""Enrolment-only session on the composed app (#2295 slice 2/3; contract #2661).

Real `create_app()` over the in-memory auth stack of `_stack.py`: the real session service and
user store, the real middleware order and the real WS path (`_session_authenticator` -> `/ws`).
Sessions are minted directly, as the sign-in slice will mint them; no endpoint changes here.
One fake instant drives the auth stack and the gateway's clocks.
"""

from __future__ import annotations

import functools
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

import candleviewer.app as appmod
from candleviewer.auth.models import MintedSession, UserRecord
from candleviewer.auth.session_service import ENROLMENT_ONLY_LIFETIME
from candleviewer.ws import gateway
from candleviewer.ws.metrics import AUTH_FAILURE_REASONS, cv_ws_auth_failures_total
from tests.csrf_helpers import csrf_headers
from tests.unit.auth.auth_fakes import make_user
from tests.unit.ws.test_lifecycle_socket import _closed, _recv, _recv_type

from ._stack import ORIGIN, T0, Stack, open_stack

_CODE = "mfa_enrollment_required"
_INERT_DIGEST = "unused"  # stored-hash placeholder: these users never sign in with a password
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@pytest.fixture
def stack(monkeypatch: pytest.MonkeyPatch) -> Iterator[Stack]:
    """`_stack.py`, with the gateway's monotonic and wall clocks on the stack's fake instant."""
    live: list[Stack] = []
    monkeypatch.setattr(
        appmod,
        "make_ws_router",
        functools.partial(
            gateway.make_ws_router,
            clock=lambda: (live[0].clock.now - T0).total_seconds(),
            wall_ms=lambda: (live[0].clock.now - _EPOCH) // timedelta(milliseconds=1),
            tick_s=0.005,
        ),
    )
    with open_stack(monkeypatch) as s:
        live.append(s)
        yield s


def _mint(stack: Stack, user: UserRecord, **kw: Any) -> tuple[MintedSession, dict[str, str]]:
    """A session minted the way the sign-in slice will: no MFA, 15 minutes at most."""
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
    return headers, next(u for u in stack.users.users.values() if u.username == "member")


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
    """`DELETE /me/sessions/{sessionId}` accepts a locked session; the guard still refuses."""
    user = _enrolling(stack)
    _, headers = _mint(stack, user, idle_timeout_s=300)
    other, _ = _mint(stack, user)
    stack.clock.now += timedelta(minutes=6)  # past the 5-minute idle lock, inside the lifetime

    resp = stack.client.delete(f"/me/sessions/{other.session_id}", headers=headers)

    assert (resp.status_code, resp.json()["code"]) == (403, _CODE)
    assert stack.call(stack.auth.sessions.require_active, str(other.session_id))  # still live


def test_the_restriction_follows_the_user_state_on_every_request(stack: Stack) -> None:
    headers, user = _member(stack)
    assert stack.client.get("/auth/sessions", headers=headers).status_code == 200

    stack.users.add(user.model_copy(update={"mfa_methods": ()}))  # e.g. a recovery sign-in
    resp = stack.client.get("/auth/sessions", headers=headers)

    # Minted for 12 h, so never an enrolment-only session (Q7): refused like an expired one.
    assert (resp.status_code, resp.json()["code"]) == (401, "unauthenticated")
    assert stack.client.post("/auth/logout", headers=headers).status_code == 204


# -- WebSocket -------------------------------------------------------------------------------


def _failures() -> float:
    total: float = sum(
        cv_ws_auth_failures_total.labels(reason=r)._value.get() for r in AUTH_FAILURE_REASONS
    )
    return total


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


def test_ws_cross_user_serves_a_full_session_then_refuses_its_re_auth_once_it_must_enrol(
    stack: Stack,
) -> None:
    _enrolling(stack)  # another user needing enrolment changes nothing here
    headers, user = _member(stack)
    token = headers["Authorization"].removeprefix("Bearer ")

    with _socket(stack) as ws:
        assert _hello_auth(ws, token)["t"] == "auth_ok"
        stack.users.add(user.model_copy(update={"mfa_methods": ()}))
        ws.send_json({"t": "auth", "id": "a2", "p": {"access_token": token}})
        bye = _recv_type(ws, "bye")
        code = _closed(ws)

    assert (bye["p"]["reason"], code) == (_CODE, 4403)
