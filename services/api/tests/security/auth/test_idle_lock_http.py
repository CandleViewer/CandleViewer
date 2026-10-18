"""The idle lock end to end (#2300; contract info "Idle lock"; Gherkin of the ticket).

The real `create_app()` over the in-memory auth stack of `_stack.py`, so the CSRF guard, the
idle-lock gate, the read-only guard, the routes and an audit writer that refuses unregistered
actions all run as deployed. No network, no sleeps (C-13.5, C-13.7).
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any, cast

import pytest
from fastapi import FastAPI
from structlog.testing import capture_logs

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.idle_lock import ungated_operations
from candleviewer.api.sessions import REFRESH_COOKIE
from candleviewer.auth.csrf import CSRF_COOKIE
from candleviewer.auth.models import MintedSession
from candleviewer.auth.session_service import ACCESS_TOKEN_TTL
from tests.csrf_helpers import csrf_headers

from ._stack import ORIGIN, Stack

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
    paths = spec["paths"]
    assert isinstance(paths, dict)
    gated = sorted(
        (method.upper(), path)
        for path, item in paths.items()
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


def test_an_expired_access_token_of_a_locked_session_stays_unauthenticated(
    stack: Stack,
) -> None:
    minted = _session(stack, "stale")
    stack.clock.now += ACCESS_TOKEN_TTL
    r = stack.client.get("/auth/sessions", headers=_headers(stack, minted))
    assert r.status_code == 401 and _code(r) != "session_idle_locked"


#: A stopping session store's failure text: never in an answer.
_STORE_FAILURE = "session store stopped"


def test_a_store_failing_under_the_gate_leaves_each_route_its_own_answer(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#3300 as deployed: a `RuntimeError` while the gate checks the token is answered by the
    route, as without the gate, never as a 500 by the gate: the `/me` routes their contracted
    `503 store_unavailable` with one `auth.me.session_backend_error` line, a resolver-backed read
    its uniform 401 (no principal). The failure's text is never echoed."""
    headers = _headers(stack, _session(stack, "stopping"))

    async def stopped(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError(_STORE_FAILURE)

    monkeypatch.setattr(stack.auth.sessions, "authenticate_access_token", stopped)
    for path in ("/me", "/me/preferences", "/me/keymap"):
        with capture_logs() as logs:
            r = stack.client.get(path, headers=headers)
        assert (r.status_code, _code(r)) == (503, "store_unavailable"), path
        errors = [e["event"] for e in logs if e["log_level"] == "error"]
        assert errors == ["auth.me.session_backend_error"] and _STORE_FAILURE not in r.text
    r = stack.client.get("/instruments", headers=headers)
    assert r.status_code == 401 and _STORE_FAILURE not in r.text


def test_sign_out_instead_still_ends_the_locked_session(stack: Stack) -> None:
    minted = _session(stack, "leaving")
    _lock(stack)
    r = stack.client.post("/auth/logout", headers=_headers(stack, minted))
    assert r.status_code == 204, r.text
    row = stack.call(stack.auth.sessions.peek_access_token, minted.access_token)
    assert row is not None and row.revoked_reason == "logout"


def _cookie_only(stack: Stack, minted: MintedSession, csrf_for: MintedSession) -> dict[str, str]:
    """A reloaded lock screen: no access token, the `cv_refresh` cookie, the Origin and the
    SR-041 pair (bound to *csrf_for*'s session)."""
    csrf = csrf_headers(stack.state.csrf_codec, csrf_for.session_id)
    stack.client.cookies.clear()
    cookie = f"{csrf['Cookie']}; {REFRESH_COOKIE}={minted.refresh_token}"
    return {**csrf, "Cookie": cookie, "Origin": ORIGIN}


def _live(stack: Stack, minted: MintedSession) -> bool:
    row = stack.call(stack.auth.sessions.peek_refresh, minted.refresh_token)
    return row is not None and not row.is_revoked


def test_a_locked_session_cannot_sign_out_every_session(stack: Stack) -> None:
    """#2389 gap H through the deployed stack (#2290 ruling, rule 3b): `all_sessions` from a
    locked session is `401 session_idle_locked`; no session ends, nothing is audited, no
    cookie is cleared. The calling session can still end itself."""
    uid, _ = stack.add_user("desk")
    locked = stack.call(stack.auth.sessions.mint, str(uid), idle_timeout_s=_IDLE_S)
    elsewhere = stack.call(stack.auth.sessions.mint, str(uid), idle_timeout_s=3600)
    _lock(stack)
    r = stack.client.post(
        "/auth/logout", headers=_headers(stack, locked), json={"all_sessions": True}
    )
    assert (r.status_code, _code(r)) == (401, "session_idle_locked")
    assert stack.audit.records == [] and "set-cookie" not in r.headers
    assert _live(stack, locked) and _live(stack, elsewhere)
    alone = stack.client.post("/auth/logout", headers=_headers(stack, locked))
    assert alone.status_code == 204, alone.text
    assert not _live(stack, locked) and _live(stack, elsewhere)


def test_after_a_reload_the_cookie_alone_signs_out_through_the_csrf_guard(stack: Stack) -> None:
    """#2389 decision 9: "Sign out instead" works for the whole lock and after a reload; the
    guard leaves the binding to the cookie's session to the route."""
    minted = _session(stack, "signing-out")
    stack.clock.now += ACCESS_TOKEN_TTL  # locked, and the access token is gone
    r = stack.client.post("/auth/logout", headers=_cookie_only(stack, minted, minted))
    assert r.status_code == 204, r.text
    assert [rec["action"] for rec in stack.audit.records] == ["auth.logout", "auth.session_revoked"]
    row = stack.call(stack.auth.sessions.peek_refresh, minted.refresh_token)
    assert row is not None and row.revoked_reason == "logout"
    cleared = {c.split("=", 1)[0] for c in r.headers.get_list("set-cookie")}
    assert {REFRESH_COOKIE, CSRF_COOKIE} <= cleared


def test_a_cookie_logout_bound_to_another_session_is_refused(stack: Stack) -> None:
    mine = _session(stack, "mine")
    theirs = _session(stack, "theirs")
    stack.clock.now += ACCESS_TOKEN_TTL
    r = stack.client.post("/auth/logout", headers=_cookie_only(stack, mine, theirs))
    assert (r.status_code, _code(r)) == (403, "csrf_token_invalid")
    assert [rec["action"] for rec in stack.audit.records] == ["auth.csrf_refused"]
    assert _live(stack, mine) and _live(stack, theirs)


def test_a_cookie_alone_never_revokes_a_session_through_the_csrf_guard(stack: Stack) -> None:
    """AC-CSRF-04's revoke half as deployed: with no access token the guard has no session to
    bind the SR-041 token to, so it refuses `DELETE /me/sessions/{sessionId}` before the route,
    without a CSRF header and with a pair bound to the cookie's session alike. The cookie
    identifies a logout only (#2300)."""
    minted = _session(stack, "kept")
    paired = _cookie_only(stack, minted, minted)
    for headers in ({"Cookie": paired["Cookie"], "Origin": ORIGIN}, paired):
        stack.client.cookies.clear()
        r = stack.client.delete(f"/me/sessions/{minted.session_id}", headers=headers)
        assert (r.status_code, _code(r)) == (403, "csrf_token_invalid")
    assert _live(stack, minted)
    assert "auth.session_revoked" not in [rec["action"] for rec in stack.audit.records]


def test_a_live_access_token_binds_logout_to_its_own_session_whatever_the_cookie(
    stack: Stack,
) -> None:
    """With an access token inside its lifetime the guard binds to that token's session, so
    another session's `cv_refresh` cookie and CSRF pair cannot redirect a logout."""
    mine = _session(stack, "mine")
    theirs = _session(stack, "theirs")
    headers = {
        **_cookie_only(stack, theirs, theirs),
        "Authorization": f"Bearer {mine.access_token}",
    }
    r = stack.client.post("/auth/logout", headers=headers)
    assert (r.status_code, _code(r)) == (403, "csrf_token_invalid")
    assert _live(stack, mine) and _live(stack, theirs)
