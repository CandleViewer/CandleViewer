"""The idle lock end to end (#2300; contract info "Idle lock"; Gherkin of the ticket).

The real `create_app()` over the in-memory auth stack of `_stack.py`, so the CSRF guard, the
read-only guard, the routes and an audit writer that refuses unregistered actions all run as
deployed. No network, no sleeps (C-13.5, C-13.7).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from candleviewer.api.sessions import REFRESH_COOKIE
from candleviewer.auth.csrf import CSRF_COOKIE
from candleviewer.auth.models import MintedSession
from candleviewer.auth.session_service import ACCESS_TOKEN_TTL
from tests.csrf_helpers import csrf_headers

from ._stack import ORIGIN, Stack

_IDLE_S = 300  # locks while the 12 min access token still lives


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


def _code(response: Any) -> Any:
    try:
        return response.json().get("code")
    except ValueError:
        return None


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
