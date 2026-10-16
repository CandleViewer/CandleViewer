"""Ending sessions while idle-locked (#2300; contract info "Idle lock"): `POST /auth/logout`
by access token or `cv_refresh` cookie, and `DELETE /me/sessions/{sessionId}`."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import httpx

from candleviewer.api.csrf import SESSION_REFUSALS_PER_WINDOW
from candleviewer.api.sessions import REFRESH_COOKIE
from candleviewer.auth.csrf import CSRF_COOKIE

from ._world import (
    _IDLE_S,
    _T0,
    World,
    _bearer,
    _cookie,
)


async def _logout(
    w: World, headers: dict[str, str], body: dict[str, Any] | None = None
) -> httpx.Response:
    return await w.client.post("/api/v1/auth/logout", json=body, headers=headers)


async def test_a_locked_session_cannot_sign_out_every_session(w: World) -> None:
    """#2389 gap H / decision 8 (#2290 ruling, rule 3b): whoever is at a locked terminal has
    not proved who they are. `all_sessions` is `401 session_idle_locked`: no session ends,
    nothing is audited or published, no cookie is cleared. Ending itself still works."""
    uid = await w.add_user()
    locked = await w.mint(uid)
    elsewhere = await w.mint(uid, idle_timeout_s=3600)  # the owner's live session elsewhere
    w.lock()
    r = await _logout(w, _bearer(locked), {"all_sessions": True})
    assert (r.status_code, r.json()["code"]) == (401, "session_idle_locked")
    assert r.json()["idle_locked_at"] == (_T0 + timedelta(seconds=_IDLE_S)).isoformat()
    assert not (await w.row(locked)).is_revoked and not (await w.row(elsewhere)).is_revoked
    assert w.audit.writer.records == [] and w.published == []
    assert "set-cookie" not in r.headers
    alone = await _logout(w, _bearer(locked))  # SCR-005 "Sign out instead"
    assert alone.status_code == 204, alone.text
    assert (await w.row(locked)).revoked_reason == "logout"
    assert not (await w.row(elsewhere)).is_revoked


async def test_after_a_reload_the_refresh_cookie_alone_signs_the_locked_session_out(
    w: World,
) -> None:
    """#2389 decision 9: with no access token inside its lifetime, `cv_refresh` identifies the
    session, so "Sign out instead" works for the whole lock: it revokes the session, writes
    `auth.logout` and `auth.session_revoked` and clears both cookies."""
    minted = await w.mint(await w.add_user(), idle_timeout_s=900)
    w.lock(900)  # 15 min: the 12 min access token is gone too
    assert (await _logout(w, _bearer(minted))).status_code == 401
    r = await _logout(w, _cookie(minted))
    assert r.status_code == 204, r.text
    assert w.audit.writer.actions() == ["auth.logout", "auth.session_revoked"]
    assert (await w.row(minted)).revoked_reason == "logout"
    assert w.published == [(str(minted.session_id), "logout")]
    cleared = r.headers.get_list("set-cookie")
    for name in (REFRESH_COOKIE, CSRF_COOKIE):
        (cookie,) = [c for c in cleared if c.startswith(f"{name}=")]
        assert "max-age=0" in cookie.lower()


async def test_the_refresh_cookie_alone_never_signs_out_every_session(w: World) -> None:
    """Ending every session needs an access token: with only the cookie, `all_sessions` is
    `session_idle_locked` for a locked session, else the uniform 401, and revokes nothing."""
    uid = await w.add_user()
    locked = await w.mint(uid, idle_timeout_s=900)
    unlocked = await w.mint(uid, idle_timeout_s=3600)
    w.lock(900)
    for minted, code in ((locked, "session_idle_locked"), (unlocked, None)):
        r = await _logout(w, _cookie(minted), {"all_sessions": True})
        assert (r.status_code, r.json().get("code")) == (401, code)
    assert not (await w.row(locked)).is_revoked and not (await w.row(unlocked)).is_revoked
    assert w.audit.writer.records == [] and w.published == []


async def test_cookie_logout_without_an_allowed_origin_is_refused_before_any_record(
    w: World,
) -> None:
    minted = await w.mint(await w.add_user(), idle_timeout_s=900)
    w.lock(900)
    for origin in (None, "https://evil.example"):
        assert (await _logout(w, _cookie(minted, origin=origin))).status_code == 403  # SR-042
    assert not (await w.row(minted)).is_revoked and w.audit.writer.records == []


async def test_cookie_logout_with_a_csrf_token_of_another_session_is_refused_and_audited(
    w: World,
) -> None:
    """SR-041 against the session the cookie identifies (the contract's CSRF "Validation")."""
    uid = await w.add_user()
    minted = await w.mint(uid, idle_timeout_s=900)
    other = await w.mint(uid, idle_timeout_s=900)
    w.lock(900)
    r = await _logout(w, _cookie(minted, csrf_for=other.session_id))
    assert (r.status_code, r.json()["code"]) == (403, "csrf_token_invalid")
    (refused,) = w.audit.writer.records
    assert (refused["action"], refused["reason"]) == ("auth.csrf_refused", "wrong_session")
    assert refused["session_id"] == minted.session_id
    assert not (await w.row(minted)).is_revoked and not (await w.row(other)).is_revoked


async def test_route_checked_csrf_refusals_are_audited_within_a_per_session_budget(
    w: World,
) -> None:
    """Contract "CSRF", "Refusal": a cookie-identified logout has no request throttle, so its
    refusals are audited up to the per-session budget; past it the same 403, no record."""
    minted = await w.mint(await w.add_user(), idle_timeout_s=900)
    w.lock(900)
    forged = _cookie(minted, csrf_for=uuid.uuid4())
    replies = [await _logout(w, forged) for _ in range(SESSION_REFUSALS_PER_WINDOW + 1)]
    assert {(r.status_code, r.json()["code"]) for r in replies} == {(403, "csrf_token_invalid")}
    assert w.audit.writer.actions() == ["auth.csrf_refused"] * SESSION_REFUSALS_PER_WINDOW
    assert "retry-after" not in replies[0].headers
    assert int(replies[-1].headers["retry-after"]) >= 1
    assert not (await w.row(minted)).is_revoked


async def test_logout_of_a_session_past_its_lifetime_is_the_uniform_401(w: World) -> None:
    """#2389 gap J at the edge: an expired session is refused like a revoked one by the
    allow-locked routes, even while its access token lives; nothing is audited."""
    uid = await w.add_user()
    minted = await w.sessions.mint(str(uid), expires_at=_T0 + timedelta(minutes=5))
    w.clock.now = _T0 + timedelta(minutes=5)
    r = await w.client.post("/api/v1/auth/logout", headers=_bearer(minted))
    assert r.status_code == 401 and w.audit.writer.records == [] and w.published == []


async def test_cookie_logout_with_an_undeclared_query_parameter_is_422_revoking_nothing(
    w: World,
) -> None:
    """SR-026 (#2742) holds for a cookie-identified logout too: it is refused after the
    route's Origin and SR-041 checks and before the body is read; nothing ends or is audited."""
    minted = await w.mint(await w.add_user(), idle_timeout_s=900)
    w.lock(900)
    r = await w.client.post(
        "/api/v1/auth/logout", params={"user_id": str(uuid.uuid4())}, headers=_cookie(minted)
    )
    assert (r.status_code, r.json()["code"]) == (422, "validation_failed")
    assert [e["field"] for e in r.json()["errors"]] == ["query.user_id"]
    assert not (await w.row(minted)).is_revoked
    assert w.audit.writer.records == [] and w.published == []


async def test_a_locked_session_cannot_revoke_another_session(w: World) -> None:
    """#2389 gap F: refused by the route itself, not only by `IdleLockMiddleware` (absent
    here), so the router never relies on how it is mounted; nothing is audited."""
    uid = await w.add_user()
    locked = await w.mint(uid)
    elsewhere = await w.mint(uid, idle_timeout_s=3600)
    w.lock()
    r = await w.client.delete(
        f"/api/v1/me/sessions/{elsewhere.session_id}", headers=_bearer(locked)
    )
    assert (r.status_code, r.json()["code"]) == (401, "session_idle_locked")
    assert not (await w.row(elsewhere)).is_revoked
    assert w.audit.writer.records == [] and w.published == []
