"""The idle lock end to end (#2300; contract info "Idle lock"; Gherkin of the ticket).

The real `create_app()` over the in-memory auth stack of `_stack.py`, so the CSRF guard, the
idle-lock gate, the read-only guard, the routes, the real B16 chart and an audit writer that
refuses unregistered actions all run as deployed. No network, no sleeps (C-13.5, C-13.7).
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any, cast

from fastapi import FastAPI

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.idle_lock import ungated_operations
from candleviewer.api.sessions import REFRESH_COOKIE
from candleviewer.auth.models import MintedSession
from candleviewer.auth.session_service import ACCESS_TOKEN_TTL
from tests.csrf_helpers import csrf_headers

from ._stack import ORIGIN, PW, Stack

_IDLE_S = 300  # locks while the 12 min access token still lives
_HTTP = ("get", "put", "post", "patch", "delete")
#: The state-changing operations the ticket names explicitly (contract test scope).
_NAMED = {
    ("POST", "/orders"),
    ("PATCH", "/orders/{orderId}"),
    ("DELETE", "/orders/{orderId}"),
    ("POST", "/orders/cancel-all"),
    ("POST", "/trade-groups"),
    ("POST", "/trade-groups/{tradeGroupId}/cancel"),
    ("POST", "/positions/close-all"),
    ("POST", "/positions/{positionId}/close"),
    ("POST", "/trading/kill-switch"),
    ("POST", "/settings/arm"),
    ("POST", "/session/environment"),
    ("POST", "/auth/step-up"),
}


def _session(stack: Stack, username: str) -> MintedSession:
    uid, _ = stack.add_user(username)
    minted: MintedSession = stack.call(stack.auth.sessions.mint, str(uid), idle_timeout_s=_IDLE_S)
    return minted


def _headers(stack: Stack, minted: MintedSession) -> dict[str, str]:
    """The access token and the SR-041 pair the browser holds for that session."""
    csrf = csrf_headers(stack.state.csrf_codec, minted.session_id)
    return {"Authorization": f"Bearer {minted.access_token}", **csrf}


def _lock(stack: Stack) -> None:
    stack.clock.now += timedelta(seconds=_IDLE_S + 1)


def _fill(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "00000000-0000-4000-8000-0000000000ff", path)


def _code(response: Any) -> Any:
    try:
        return response.json().get("code")
    except ValueError:
        return None


def test_every_contract_operation_but_the_allowed_ones_refuses_a_locked_session(
    stack: Stack,
) -> None:
    """AC "Locked session is recognisable", over the whole contract: every operation answers
    `401 session_idle_locked`, not `unauthenticated`, and nothing runs or is audited."""
    spec = load_openapi_spec()
    ungated = ungated_operations(spec)
    gated = sorted(
        (method.upper(), path)
        for path, item in spec["paths"].items()
        for method in _HTTP
        if isinstance(item.get(method), dict) and (method.upper(), path) not in ungated
    )
    assert _NAMED <= set(gated)
    minted = _session(stack, "locked")
    _lock(stack)
    headers = _headers(stack, minted)
    answers = {
        (method, path): (r.status_code, _code(r))
        for method, path in gated
        for r in [
            stack.client.request(
                method,
                _fill(path),
                headers=headers,
                json={} if method in ("POST", "PUT", "PATCH") else None,
            )
        ]
    }
    assert set(answers.values()) == {(401, "session_idle_locked")}, {
        op: a for op, a in answers.items() if a != (401, "session_idle_locked")
    }
    assert stack.audit.records == []


def test_the_kill_switch_cannot_be_driven_from_a_locked_session(stack: Stack) -> None:
    """AC "Kill switch cannot be driven from a locked session": engage and release are refused
    before the handler runs, so no transition and no audit row (a stub handler stands in for
    E39's route and is reachable from a live session)."""
    calls: list[Any] = []

    async def kill_switch(body: dict[str, Any]) -> dict[str, str]:
        calls.append(body)
        return {"state": "engaged"}

    cast(FastAPI, stack.client.app).add_api_route(
        "/trading/kill-switch", kill_switch, methods=["POST"]
    )
    live = _session(stack, "owner-live")
    reached = stack.client.post(
        "/trading/kill-switch", headers=_headers(stack, live), json={"action": "engage"}
    )
    assert reached.status_code == 200 and len(calls) == 1
    locked = _session(stack, "owner-locked")
    _lock(stack)
    for action in ("engage", "release"):
        r = stack.client.post(
            "/trading/kill-switch", headers=_headers(stack, locked), json={"action": action}
        )
        assert (r.status_code, _code(r)) == (401, "session_idle_locked")
        assert "idle_locked_at" in r.json()
    assert len(calls) == 1 and stack.audit.records == []


def test_a_locked_session_reads_itself_and_unlocks_with_the_password_only(stack: Stack) -> None:
    """AC "Unlock with the password only", through the real guards, chart and audit writer."""
    minted = _session(stack, "returning")
    _lock(stack)
    headers = _headers(stack, minted)
    info = stack.client.get("/auth/session", headers=headers)
    assert info.status_code == 200 and info.json()["session"]["locked"] is True
    r = stack.client.post("/auth/unlock", headers=headers, json={"password": PW})
    assert r.status_code == 200, r.text
    assert r.json()["session"]["locked"] is False and r.json()["step_up_expires_at"] is None
    assert [rec["action"] for rec in stack.audit.records] == [
        "auth.idle_locked",
        "auth.session_unlocked",
    ]
    after = stack.client.get("/auth/sessions", headers=headers)
    assert after.status_code == 200  # the gate lets the unlocked session through again


def test_after_a_reload_the_cookie_alone_unlocks_through_the_csrf_guard(stack: Stack) -> None:
    minted = _session(stack, "reloaded")
    stack.clock.now += ACCESS_TOKEN_TTL  # locked, and the access token is gone
    csrf = csrf_headers(stack.state.csrf_codec, minted.session_id)
    cookie = f"{csrf['Cookie']}; {REFRESH_COOKIE}={minted.refresh_token}"
    stack.client.cookies.clear()
    headers = {**csrf, "Cookie": cookie, "Origin": ORIGIN}
    assert stack.client.get("/auth/session", headers=headers).json()["session"]["locked"]
    refresh = stack.client.post("/auth/refresh", headers=headers)
    assert (refresh.status_code, _code(refresh)) == (401, "session_idle_locked")
    r = stack.client.post("/auth/unlock", headers=headers, json={"password": PW})
    assert r.status_code == 200, r.text
    rotated = stack.client.post("/auth/refresh", headers=headers)
    assert rotated.status_code == 200, rotated.text


def test_an_expired_access_token_of_a_locked_session_stays_unauthenticated(
    stack: Stack,
) -> None:
    minted = _session(stack, "stale")
    stack.clock.now += ACCESS_TOKEN_TTL
    r = stack.client.get("/auth/sessions", headers=_headers(stack, minted))
    assert r.status_code == 401 and _code(r) != "session_idle_locked"


def test_sign_out_instead_still_ends_the_locked_session(stack: Stack) -> None:
    minted = _session(stack, "leaving")
    _lock(stack)
    r = stack.client.post("/auth/logout", headers=_headers(stack, minted))
    assert r.status_code == 204, r.text
    row = stack.call(stack.auth.sessions.peek_access_token, minted.access_token)
    assert row is not None and row.revoked_reason == "logout"
