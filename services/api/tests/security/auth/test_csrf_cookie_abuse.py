"""E09-X02 CSRF / cookie-flag abuse cases (AC-CSRF-*) against the real session router.

These exercise the session router on its own (no `CsrfMiddleware` mounted), i.e. the
SameSite=Strict + Origin allow-list controls that stay in place as additional defences. The
SR-041 double-submit token (finding F-1, #2090) is covered end to end through `create_app()` in
`test_csrf_double_submit.py`.
"""

from __future__ import annotations

import uuid

from candleviewer.api.sessions import REFRESH_COOKIE
from tests.csrf_helpers import arm_csrf
from tests.unit.api.test_sessions_router import _CSRF_CODEC, _Env, _h

_ORIGIN = "https://app.example"


async def test_ac_csrf_01_cookie_refresh_without_or_foreign_origin_refused() -> None:
    env = _Env(origins=frozenset({_ORIGIN}))
    m = await env.mint(uuid.uuid4())
    url = "/api/v1/auth/refresh"
    for headers in ({}, {"Origin": "https://evil.example"}, {"Origin": "null"}):
        env.client.cookies.clear()
        r = env.client.post(url, cookies={REFRESH_COOKIE: m.refresh_token}, headers=headers)
        assert r.status_code == 403, headers
    rec = await env.repo.find_by_id(str(m.session_id))
    assert rec is not None and not rec.is_revoked  # CSRF attempts did not burn the token


async def test_ac_csrf_02_empty_allowlist_refuses_every_origin() -> None:
    env = _Env(origins=frozenset())
    m = await env.mint(uuid.uuid4())
    r = env.client.post(
        "/api/v1/auth/refresh",
        cookies={REFRESH_COOKIE: m.refresh_token},
        headers={"Origin": _ORIGIN},
    )
    assert r.status_code == 403


async def test_ac_csrf_03_refresh_cookie_flags_not_downgradable() -> None:  # SR-012
    env = _Env(origins=frozenset({_ORIGIN}))
    m = await env.mint(uuid.uuid4())
    env.client.cookies.delete(REFRESH_COOKIE, path="/api/v1/auth")  # keep the SR-041 pair
    r = env.client.post(
        "/api/v1/auth/refresh",
        cookies={REFRESH_COOKIE: m.refresh_token},
        headers={"Origin": _ORIGIN, "X-Forwarded-Proto": "http"},
    )
    assert r.status_code == 200
    cookie = next(h for h in r.headers.get_list("set-cookie") if h.startswith(REFRESH_COOKIE))
    for flag in ("httponly", "secure", "samesite=strict"):
        assert flag in cookie.lower()


async def test_ac_csrf_04_cookie_logout_needs_origin_and_bound_token_revoke_needs_bearer() -> None:
    """A cookie alone signs its session out once the `Origin` is allowed and the SR-041 token
    binds to that session; revoking a session still needs a bearer."""
    env = _Env(origins=frozenset({_ORIGIN}))
    m = await env.mint(uuid.uuid4())
    env.client.cookies.set(REFRESH_COOKIE, m.refresh_token)
    hdr = {"Origin": _ORIGIN}
    revoke = env.client.request("DELETE", f"/api/v1/me/sessions/{m.session_id}", headers=hdr)
    assert revoke.status_code == 401  # revoking a session needs a bearer
    # Contract "Idle lock" (#2300): `cv_refresh` identifies a logout with no live access token,
    # under the SR-042 Origin and SR-041 checks of `/auth/refresh`, so a cookie alone is refused.
    for headers in ({}, {"Origin": "https://evil.example"}):
        assert env.client.post("/api/v1/auth/logout", headers=headers).status_code == 403
    arm_csrf(env.client, _CSRF_CODEC, uuid.uuid4())  # a token bound to another session
    assert env.client.post("/api/v1/auth/logout", headers=hdr).status_code == 403
    rec = await env.repo.find_by_id(str(m.session_id))
    assert rec is not None and not rec.is_revoked
    arm_csrf(env.client, _CSRF_CODEC, m.session_id)
    assert env.client.post("/api/v1/auth/logout", headers=hdr).status_code == 204


async def test_ac_csrf_05_idor_cannot_revoke_other_users_session() -> None:  # O1/O7 on sessions
    env = _Env()
    victim = await env.mint(uuid.uuid4())
    attacker = await env.mint(uuid.uuid4())
    r = env.client.delete(
        f"/api/v1/me/sessions/{victim.session_id}", headers=_h(attacker.access_token)
    )
    assert r.status_code in (403, 404)
    rec = await env.repo.find_by_id(str(victim.session_id))
    assert rec is not None and not rec.is_revoked
    listing = env.client.get("/api/v1/auth/sessions", headers=_h(attacker.access_token)).json()
    assert str(victim.session_id) not in str(listing)
