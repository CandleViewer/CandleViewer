"""SR-041 double-submit CSRF through the real `create_app()` stack (#2090).

SR-152 negative cases (absent / mismatched / other session / tampered MAC / malformed),
the exempt pre-session routes, an SR-042 cross-origin login attempt, and the token
lifecycle: issue at login, rotate on refresh, re-issue on `GET /auth/session`, expire
on logout, multi-tab retry. Real `AuthService` / `SessionService` / `MfaService` over
in-memory fakes; fixed clock; no network.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

import candleviewer.app as appmod
from candleviewer.auth.csrf import CSRF_COOKIE, CSRF_HEADER, CsrfCodec, CsrfVerdict
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.metrics import auth_csrf_refused_total
from candleviewer.auth.models import MfaEnrollRequest, MfaMethodKind
from candleviewer.auth.service import AuthService
from candleviewer.auth.totp import generate_code, time_step_for
from tests.unit.auth.auth_fakes import FakeUserRepository, make_user
from tests.unit.auth.mfa_fakes import FakeMfaRepository
from tests.unit.auth.session_fakes import FakeSessionRepository

_CODEC_OTHER = CsrfCodec(b"\x09" * 32)  # an attacker's own key: never verifies here
_PW = "pw-canary-csrf-7"
_ORIGIN = "https://app.example.test"
_T0 = datetime(2026, 10, 9, 12, 0, 0, tzinfo=UTC)


class _Clock:
    def __init__(self) -> None:
        self.now = _T0

    def __call__(self) -> datetime:
        return self.now


class _Identity:
    async def user(self, user_id: str) -> dict[str, Any]:
        return {"id": user_id, "username": "basiltt", "roles": ["owner"], "status": "active"}

    async def session_info(self, user_id: str) -> dict[str, Any]:
        return {"permissions": ["*"], "account_scope": []}


class _Audit:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    async def emit(self, action: str, **kw: Any) -> None:
        self.records.append({"action": action, **kw})

    def of(self, action: str) -> list[dict[str, Any]]:
        return [r for r in self.records if r["action"] == action]


class _Stack:
    def __init__(self, client: TestClient, ctx: Any, audit: _Audit, clock: _Clock) -> None:
        self.client = client
        self.ctx = ctx
        self.audit = audit
        self.clock = clock
        self.seed = b""
        self.codec: CsrfCodec = client.app.state.csrf_codec  # type: ignore[attr-defined]  # TestClient.app is untyped ASGI

    def code(self, offset: int = 0) -> str:
        return generate_code(self.seed, time_step_for(self.clock.now.timestamp()) + offset)

    def login(self) -> Any:
        """Login + MFA verify; returns the verify response (tokens + cookies)."""
        r = self.client.post("/auth/login", json={"identifier": "basiltt", "password": _PW})
        assert r.status_code == 200, r.text
        r = self.client.post(
            "/auth/mfa/verify",
            json={"mfa_token": r.json()["mfa_token"], "method": "totp", "code": self.code()},
        )
        assert r.status_code == 200, r.text
        self.clock.now += timedelta(seconds=30)  # next TOTP step: codes are single-use
        return r


@pytest.fixture
def stack(monkeypatch: pytest.MonkeyPatch) -> Any:
    clock = _Clock()
    monkeypatch.setenv("CV_ALLOWED_ORIGINS", _ORIGIN)
    users, mfa_repo, sessions = FakeUserRepository(), FakeMfaRepository(), FakeSessionRepository()
    pepper = os.urandom(8).hex()
    auth = AuthService(
        users,
        pepper=pepper,
        mfa_repository=mfa_repo,
        totp_encryption_key=os.urandom(32),
        recovery_code_hmac_key=os.urandom(32),
        session_repository=sessions,
        clock=clock,
    )
    monkeypatch.setattr(appmod, "build_auth_service", lambda *_a, **_k: auth)
    monkeypatch.setattr(appmod, "build_identity_provider", lambda _s: _Identity())
    app = appmod.create_app(auth_clock=clock)
    ctx = app.state.app_context
    audit = _Audit()
    ctx.audit._writer = audit
    with TestClient(
        app, base_url=_ORIGIN, client=("127.0.0.1", 50000), raise_server_exceptions=False
    ) as client:
        assert client.portal is not None
        client.portal.call(ctx.auth.start, ctx)
        user = make_user(password_hash=client.portal.call(Hasher(pepper=pepper).hash, _PW))
        users.add(user)
        uid = str(user.id)
        mfa = ctx.auth.mfa
        res = client.portal.call(
            lambda: mfa.enroll(
                uid, MfaEnrollRequest(method=MfaMethodKind.TOTP, label=""), account_name="o"
            )
        )
        s = _Stack(client, ctx, audit, clock)
        s.seed = mfa._encryptor.decrypt(mfa_repo.methods[str(res.method_id)].secret_enc)
        client.portal.call(
            lambda: mfa.confirm_enrollment(uid, method_id=str(res.method_id), code=s.code(-1))
        )
        yield s


def _csrf(response: Any) -> str:
    token = response.cookies.get(CSRF_COOKIE)
    assert token, "the SR-041 cookie was not set"
    return str(token)


def _bearer(r: Any) -> str:
    return str(r.json()["tokens"]["access_token"])


def _post_logout(s: _Stack, access: str, header: str | None, cookie: str | None) -> Any:
    s.client.cookies.clear()
    headers = {"Authorization": f"Bearer {access}"}
    if header is not None:
        headers[CSRF_HEADER] = header
    cookies = {CSRF_COOKIE: cookie} if cookie is not None else {}
    return s.client.post("/auth/logout", headers=headers, cookies=cookies)


def _assert_refused(s: _Stack, r: Any, reason: str, *secrets_: str) -> None:
    assert r.status_code == 403, r.text
    body = r.json()
    assert body["code"] == "csrf_token_invalid"
    assert body["type"] == "https://candleviewer.local/errors/csrf_token_invalid"
    for v in secrets_:
        assert v not in r.text  # detail never echoes token or cookie values
    rec = s.audit.of("auth.csrf_refused")[-1]
    assert rec["reason"] == reason
    assert all(v not in repr(rec) for v in secrets_)


# -- issue -------------------------------------------------------------------------


def test_login_issues_host_cookie_with_the_contract_attributes(stack: _Stack) -> None:
    r = stack.login()
    raw = [h for h in r.headers.get_list("set-cookie") if h.startswith(CSRF_COOKIE + "=")]
    assert len(raw) == 1
    attrs = raw[0].lower()
    for flag in ("secure", "samesite=strict", "path=/;", f"max-age={12 * 3600}"):
        assert flag in attrs + ";", flag
    assert "httponly" not in attrs and "domain=" not in attrs
    assert r.json()["status"] == "authenticated"
    # the token is bound to the server-side session id (never the refresh token)
    portal = stack.client.portal
    assert portal is not None
    rec = portal.call(stack.ctx.auth.sessions.authenticate_access_token, _bearer(r))
    codec: CsrfCodec = stack.codec
    assert codec.verify(_csrf(r), str(rec.id)) is CsrfVerdict.OK


def test_mfa_recovery_mints_a_session_with_a_token_only_when_one_is_minted(stack: _Stack) -> None:
    # `/auth/mfa/recovery` mints no session in this codebase (it returns
    # `forced_totp_reenroll`), so no CSRF cookie may be issued for a non-session.
    r = stack.client.post("/auth/login", json={"identifier": "basiltt", "password": _PW})
    r = stack.client.post(
        "/auth/mfa/recovery", json={"mfa_token": r.json()["mfa_token"], "recovery_code": "x" * 10}
    )
    assert r.status_code in (200, 401)  # exempt: never a CSRF refusal
    assert r.json().get("code") != "csrf_token_invalid"


# -- SR-152 negative cases ---------------------------------------------------------


def test_missing_header_is_refused_and_audited(stack: _Stack) -> None:
    r = stack.login()
    access, token = _bearer(r), _csrf(r)
    before = auth_csrf_refused_total.labels(reason="missing")._value.get()
    out = _post_logout(stack, access, None, token)
    _assert_refused(stack, out, "missing", token)
    assert auth_csrf_refused_total.labels(reason="missing")._value.get() == before + 1
    assert stack.audit.of("auth.csrf_refused")[-1]["session_id"] is None


def test_missing_cookie_is_refused(stack: _Stack) -> None:
    r = stack.login()
    access, token = _bearer(r), _csrf(r)
    _assert_refused(stack, _post_logout(stack, access, token, None), "missing", token)


def test_header_not_equal_to_cookie_is_refused(stack: _Stack) -> None:
    r1 = stack.login()
    r2 = stack.login()
    access, t1, t2 = _bearer(r1), _csrf(r1), _csrf(r2)
    _assert_refused(stack, _post_logout(stack, access, t1, t2), "mismatch", t1, t2)


def test_token_of_another_session_is_refused_even_when_header_equals_cookie(
    stack: _Stack,
) -> None:
    victim = stack.login()
    attacker = stack.login()
    access, other = _bearer(victim), _csrf(attacker)
    out = _post_logout(stack, access, other, other)
    _assert_refused(stack, out, "wrong_session", other)
    rec = stack.audit.of("auth.csrf_refused")[-1]
    assert rec["session_id"] is not None  # the server-resolved session is recorded
    # the victim session was not logged out
    ok = stack.client.get("/auth/session", headers={"Authorization": f"Bearer {access}"})
    assert ok.status_code == 200


def test_tampered_mac_is_refused(stack: _Stack) -> None:
    r = stack.login()
    access, token = _bearer(r), _csrf(r)
    nonce, mac = token.split(".")
    flipped = ("B" if mac[0] == "A" else "A") + mac[1:]
    bad = f"{nonce}.{flipped}"
    _assert_refused(stack, _post_logout(stack, access, bad, bad), "wrong_session", bad, token)


@pytest.mark.parametrize(
    "bad", ["x", "a.b", "..", "Zm9v.YmFy", "a" * 300, "A" * 43 + "=" + "." + "A" * 43]
)
def test_malformed_token_is_refused_as_bad_mac(stack: _Stack, bad: str) -> None:
    r = stack.login()
    access = _bearer(r)
    s = stack
    s.client.cookies.clear()
    headers = {"Authorization": f"Bearer {access}", CSRF_HEADER: bad}
    out = s.client.post("/auth/logout", headers=headers, cookies={CSRF_COOKIE: bad})
    _assert_refused(stack, out, "bad_mac")


def test_forged_unbound_token_without_session_is_refused(stack: _Stack) -> None:
    """Contract: header == cookie alone is never sufficient. A canonical-shaped but
    unsigned token with no session is refused (403), not passed to the route."""
    forged = "A" * 43 + "." + "A" * 43
    stack.client.cookies.clear()
    out = stack.client.post(
        "/auth/logout", headers={CSRF_HEADER: forged}, cookies={CSRF_COOKIE: forged}
    )
    _assert_refused(stack, out, "wrong_session", forged)


def test_expired_access_token_still_gets_its_mac_verified_then_the_route_401(
    stack: _Stack,
) -> None:
    """Option (a): the guard binds to the session an expired bearer was issued for, so a
    correct token reaches the route (which answers 401, starting the refresh path) and a
    wrong one is refused 403 before it."""
    r = stack.login()
    access, token = _bearer(r), _csrf(r)
    stack.clock.now += timedelta(minutes=13)  # past the 12-min access-token TTL
    other = _csrf(stack.login())
    assert _post_logout(stack, access, token, token).status_code == 401
    _assert_refused(stack, _post_logout(stack, access, other, other), "wrong_session", other)


def test_idle_locked_session_logout_still_works_with_its_token(stack: _Stack) -> None:
    """`allow_locked`: the guard's session lookup ignores the idle lock, so logout of a
    locked session (with its own token) is not a CSRF refusal and succeeds."""
    r = stack.login()
    portal = stack.client.portal
    assert portal is not None
    rec = portal.call(stack.ctx.auth.sessions.authenticate_access_token, _bearer(r))
    repo = stack.ctx.auth.sessions._repository
    locked = rec.model_copy(update={"last_seen_at": stack.clock.now - timedelta(hours=1)})
    repo.sessions[str(rec.id)] = locked
    assert locked.is_idle_locked(now=stack.clock.now)
    out = _post_logout(stack, _bearer(r), _csrf(r), _csrf(r))
    assert out.status_code == 204, out.text


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/auth/step-up"),
        ("PUT", "/auth/password"),
        ("DELETE", f"/me/sessions/{uuid.uuid4()}"),
        ("POST", "/users"),
        ("PATCH", f"/rules/{uuid.uuid4()}"),
        ("POST", "/api/v1/auth/logout"),
    ],
)
def test_every_unsafe_method_without_token_is_refused(
    stack: _Stack, method: str, path: str
) -> None:
    access = _bearer(stack.login())
    stack.client.cookies.clear()
    out = stack.client.request(method, path, headers={"Authorization": f"Bearer {access}"}, json={})
    assert out.status_code == 403 and out.json()["code"] == "csrf_token_invalid", path


def test_no_bearer_exemption_and_no_cookie_only_bypass(stack: _Stack) -> None:
    r = stack.login()
    access = _bearer(r)
    stack.client.cookies.clear()
    out = stack.client.post("/auth/step-up", headers={"Authorization": f"Bearer {access}"}, json={})
    assert out.status_code == 403 and out.json()["code"] == "csrf_token_invalid"


# -- exempt routes and SR-042 --------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/auth/login",
        "/auth/mfa/verify",
        "/auth/mfa/recovery",
        "/invites/sometoken",
        "/invites/sometoken/confirm",
        "/api/v1/auth/login",
    ],
)
def test_pre_session_routes_are_exempt(stack: _Stack, path: str) -> None:
    stack.client.cookies.clear()
    out = stack.client.post(path, json={})
    assert out.status_code != 403 or out.json().get("code") != "csrf_token_invalid"
    assert not stack.audit.of("auth.csrf_refused")


def test_safe_methods_are_exempt(stack: _Stack) -> None:
    access = _bearer(stack.login())
    stack.client.cookies.clear()
    r = stack.client.get("/auth/session", headers={"Authorization": f"Bearer {access}"})
    assert r.status_code == 200


def test_exemption_is_exact_not_a_prefix(stack: _Stack) -> None:
    access = _bearer(stack.login())
    stack.client.cookies.clear()
    for path in ("/invites/a/b/confirm", "/auth/login/x", "/auth/mfa/verify/"):
        out = stack.client.post(path, headers={"Authorization": f"Bearer {access}"}, json={})
        assert out.status_code == 403 and out.json()["code"] == "csrf_token_invalid", path


def test_sr042_cross_origin_requests_are_refused_including_login(stack: _Stack) -> None:
    """SR-042 / SR-152 "wrong Origin": an Origin outside the allow-list, or
    `Sec-Fetch-Site: cross-site`, is refused on every unsafe method - including the
    exempt pre-session login - before anything else runs."""
    victim = stack.login()
    access, token = _bearer(victim), _csrf(victim)
    for evil in ({"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}):
        stack.client.cookies.clear()
        r = stack.client.post(
            "/auth/login", headers=evil, json={"identifier": "basiltt", "password": _PW}
        )
        _assert_refused(stack, r, "cross_origin")
        assert CSRF_COOKIE not in r.cookies and "cv_refresh" not in r.cookies
        # even with the victim's bearer and a valid token pair
        out = stack.client.post(
            "/auth/logout",
            headers={**evil, "Authorization": f"Bearer {access}", CSRF_HEADER: token},
            cookies={CSRF_COOKIE: token},
        )
        _assert_refused(stack, out, "cross_origin", token)
        rr = stack.client.post(
            "/auth/refresh",
            headers={**evil, CSRF_HEADER: token},
            cookies={"cv_refresh": victim.cookies["cv_refresh"], CSRF_COOKIE: token},
        )
        _assert_refused(stack, rr, "cross_origin", token)
    assert not stack.audit.of("auth.session_refreshed")
    # same-origin login still works
    stack.client.cookies.clear()
    ok = stack.client.post(
        "/auth/login", headers={"Origin": _ORIGIN}, json={"identifier": "basiltt", "password": _PW}
    )
    assert ok.json()["status"] == "mfa_required"


def test_off_mesh_unsafe_request_gets_the_mesh_403_and_no_csrf_audit(stack: _Stack) -> None:
    """Order: Correlation -> MeshOnly -> Csrf. Off-mesh traffic never reaches a session
    lookup or an `auth.csrf_refused` write."""
    app = stack.client.app
    off = TestClient(app, base_url=_ORIGIN, client=("203.0.113.9", 4000))  # type: ignore[arg-type]
    r = off.post("/auth/logout", headers={"Authorization": "Bearer x"})
    assert r.status_code == 403 and r.json() == {"detail": "Forbidden"}
    assert not stack.audit.of("auth.csrf_refused")


def test_middleware_order_is_correlation_mesh_csrf() -> None:
    from candleviewer.api.csrf import CsrfMiddleware
    from candleviewer.net import MeshOnlyMiddleware
    from candleviewer.observability.correlation import CorrelationMiddleware

    order = [m.cls for m in appmod.create_app().user_middleware]  # outermost first
    pos = {c: order.index(c) for c in (CorrelationMiddleware, MeshOnlyMiddleware, CsrfMiddleware)}
    assert pos[CorrelationMiddleware] < pos[MeshOnlyMiddleware] < pos[CsrfMiddleware]
    assert order[: pos[CsrfMiddleware] + 1][-3:] == [
        CorrelationMiddleware,
        MeshOnlyMiddleware,
        CsrfMiddleware,
    ]


# -- lifecycle ------------------------------------------------------------------------


def test_refresh_validates_against_the_refresh_session_then_rotates(stack: _Stack) -> None:
    r = stack.login()
    token, refresh = _csrf(r), r.cookies["cv_refresh"]
    stack.client.cookies.clear()
    ok = stack.client.post(
        "/auth/refresh",
        headers={"Origin": _ORIGIN, CSRF_HEADER: token},
        cookies={"cv_refresh": refresh, CSRF_COOKIE: token},
    )
    assert ok.status_code == 200, ok.text
    rotated = _csrf(ok)
    assert rotated != token
    access2 = _bearer(ok)
    # the old token no longer works for the new session; the rotated one does
    _assert_refused(stack, _post_logout(stack, access2, token, token), "wrong_session", token)
    assert _post_logout(stack, access2, rotated, rotated).status_code == 204


def test_refresh_with_another_sessions_token_is_refused_and_does_not_rotate(
    stack: _Stack,
) -> None:
    a = stack.login()
    b = stack.login()
    stack.client.cookies.clear()
    out = stack.client.post(
        "/auth/refresh",
        headers={"Origin": _ORIGIN, CSRF_HEADER: _csrf(b)},
        cookies={"cv_refresh": a.cookies["cv_refresh"], CSRF_COOKIE: _csrf(b)},
    )
    _assert_refused(stack, out, "wrong_session", _csrf(b))
    assert not stack.audit.of("auth.session_refreshed")  # nothing rotated


def test_body_refresh_resolves_the_session_from_the_body_token(stack: _Stack) -> None:
    r = stack.login()
    token, refresh = _csrf(r), r.cookies["cv_refresh"]
    stack.client.cookies.clear()
    ok = stack.client.post(
        "/auth/refresh",
        json={"refresh_token": refresh},
        headers={CSRF_HEADER: token},
        cookies={CSRF_COOKIE: token},
    )
    assert ok.status_code == 200, ok.text
    other = stack.login()
    stack.client.cookies.clear()
    bad = stack.client.post(
        "/auth/refresh",
        json={"refresh_token": ok.json()["tokens"]["refresh_token"]},
        headers={CSRF_HEADER: _csrf(other)},
        cookies={CSRF_COOKIE: _csrf(other)},
    )
    _assert_refused(stack, bad, "wrong_session")


def test_get_session_reissues_when_missing_or_invalid_but_not_when_valid(stack: _Stack) -> None:
    r = stack.login()
    access, token = _bearer(r), _csrf(r)
    auth = {"Authorization": f"Bearer {access}"}
    stack.client.cookies.clear()
    missing = stack.client.get("/auth/session", headers=auth)
    assert missing.status_code == 200 and _csrf(missing)
    stack.client.cookies.clear()
    other = _csrf(stack.login())
    stack.client.cookies.clear()
    wrong = stack.client.get("/auth/session", headers=auth, cookies={CSRF_COOKIE: other})
    reissued = _csrf(wrong)
    assert reissued != other
    assert _post_logout(stack, access, reissued, reissued).status_code == 204
    r2 = stack.login()
    stack.client.cookies.clear()
    valid = stack.client.get(
        "/auth/session", headers={"Authorization": f"Bearer {_bearer(r2)}"},
        cookies={CSRF_COOKIE: _csrf(r2)},
    )  # fmt: skip
    assert CSRF_COOKIE not in valid.cookies
    assert token  # first token remained a valid value for its session


def test_logout_expires_the_cookie(stack: _Stack) -> None:
    r = stack.login()
    out = _post_logout(stack, _bearer(r), _csrf(r), _csrf(r))
    assert out.status_code == 204
    raw = [h for h in out.headers.get_list("set-cookie") if h.startswith(CSRF_COOKIE + "=")]
    assert raw and ("max-age=0" in raw[0].lower() or "expires=" in raw[0].lower())
    assert "path=/" in raw[0].lower() and "secure" in raw[0].lower()


def test_multi_tab_old_token_refused_then_retry_with_reread_cookie_succeeds(
    stack: _Stack,
) -> None:
    """Tab A holds the pre-refresh token; tab B refreshed. A's first try is 403
    csrf_token_invalid, re-reading the (shared) cookie and retrying once succeeds."""
    r = stack.login()
    old = _csrf(r)
    stack.client.cookies.clear()
    b = stack.client.post(
        "/auth/refresh",
        headers={"Origin": _ORIGIN, CSRF_HEADER: old},
        cookies={"cv_refresh": r.cookies["cv_refresh"], CSRF_COOKIE: old},
    )
    shared_cookie, access = _csrf(b), _bearer(b)
    first = _post_logout(stack, access, old, shared_cookie)
    assert first.status_code == 403 and first.json()["code"] == "csrf_token_invalid"
    retry = _post_logout(stack, access, shared_cookie, shared_cookie)
    assert retry.status_code == 204


def test_audit_sink_down_still_refuses(stack: _Stack) -> None:
    r = stack.login()

    class _Down:
        async def emit(self, action: str, **kw: Any) -> None:
            raise RuntimeError("sink down")

    stack.ctx.audit._writer = _Down()
    out = _post_logout(stack, _bearer(r), None, None)
    assert out.status_code == 403 and out.json()["code"] == "csrf_token_invalid"


# -- review #2238 regressions --------------------------------------------------------------


def test_blocker_refresh_with_trailing_newline_path_is_refused_and_does_not_rotate(
    stack: _Stack,
) -> None:
    """`POST /auth/refresh%0A` (Starlette's `$` tolerates a trailing newline) used to skip
    the binding. Now: 400 at the edge, and even a plain path is bound by the route."""
    victim = stack.login()
    forged = _CODEC_OTHER.issue("anything")
    refresh = victim.cookies["cv_refresh"]
    for path in ("/auth/refresh%0A", "/api/v1/auth/refresh%0A"):
        stack.client.cookies.clear()
        r = stack.client.post(
            path,
            headers={"Origin": _ORIGIN, CSRF_HEADER: forged},
            cookies={"cv_refresh": refresh, CSRF_COOKIE: forged},
        )
        assert r.status_code == 400, (path, r.text)
    assert not stack.audit.of("auth.session_refreshed")


def test_blocker_padded_refresh_body_with_forged_token_is_refused_and_does_not_rotate(
    stack: _Stack,
) -> None:
    """A refresh body padded past the old 4 KiB peek used to resolve 'no session' and pass.
    The route now verifies the token against `presented_record.id` itself."""
    victim = stack.login()
    stack.client.cookies.clear()
    refreshed = stack.client.post(
        "/auth/refresh",
        headers={"Origin": _ORIGIN, CSRF_HEADER: _csrf(victim)},
        cookies={"cv_refresh": victim.cookies["cv_refresh"], CSRF_COOKIE: _csrf(victim)},
    )
    body_token = refreshed.json()["tokens"].get("refresh_token") or refreshed.cookies["cv_refresh"]
    forged = _CODEC_OTHER.issue("anything")
    payload = b'{"refresh_token": "' + body_token.encode() + b'"' + b" " * 5000 + b"}"
    stack.client.cookies.clear()
    before = len(stack.audit.of("auth.session_refreshed"))
    r = stack.client.post(
        "/auth/refresh",
        content=payload,
        headers={"Content-Type": "application/json", CSRF_HEADER: forged},
        cookies={CSRF_COOKIE: forged},
    )
    assert r.status_code == 403 and r.json()["code"] == "csrf_token_invalid", r.text
    assert len(stack.audit.of("auth.session_refreshed")) == before  # nothing rotated
    rec = stack.audit.of("auth.csrf_refused")[-1]
    assert rec["session_id"] is not None  # audited against the refresh token's session


def test_refresh_reuse_with_its_valid_token_still_reaches_reuse_detection(stack: _Stack) -> None:
    """A rotated-out refresh token presented with that session's own token is not swallowed
    by the guard: the route's family revocation (reuse detection) still runs."""
    r = stack.login()
    old_refresh, old_token = r.cookies["cv_refresh"], _csrf(r)
    stack.client.cookies.clear()
    ok = stack.client.post(
        "/auth/refresh",
        headers={"Origin": _ORIGIN, CSRF_HEADER: old_token},
        cookies={"cv_refresh": old_refresh, CSRF_COOKIE: old_token},
    )
    assert ok.status_code == 200
    stack.client.cookies.clear()
    replay = stack.client.post(
        "/auth/refresh",
        headers={"Origin": _ORIGIN, CSRF_HEADER: old_token},
        cookies={"cv_refresh": old_refresh, CSRF_COOKIE: old_token},
    )
    assert replay.status_code == 401
    assert stack.audit.of("auth.refresh_reuse_detected")


def test_revoking_another_session_keeps_the_callers_csrf_cookie(stack: _Stack) -> None:
    me = stack.login()
    other = stack.login()
    portal = stack.client.portal
    assert portal is not None
    other_rec = portal.call(stack.ctx.auth.sessions.authenticate_access_token, _bearer(other))
    stack.client.cookies.clear()
    h = {"Authorization": f"Bearer {_bearer(me)}", CSRF_HEADER: _csrf(me)}
    out = stack.client.delete(
        f"/me/sessions/{other_rec.id}", headers=h, cookies={CSRF_COOKIE: _csrf(me)}
    )
    assert out.status_code == 204, out.text
    assert not [c for c in out.headers.get_list("set-cookie") if c.startswith(CSRF_COOKIE)]
    nxt = _post_logout(stack, _bearer(me), _csrf(me), _csrf(me))
    assert nxt.status_code == 204  # the caller's next write still succeeds


def test_revoking_own_session_expires_the_csrf_cookie(stack: _Stack) -> None:
    me = stack.login()
    portal = stack.client.portal
    assert portal is not None
    rec = portal.call(stack.ctx.auth.sessions.authenticate_access_token, _bearer(me))
    stack.client.cookies.clear()
    h = {"Authorization": f"Bearer {_bearer(me)}", CSRF_HEADER: _csrf(me)}
    out = stack.client.delete(f"/me/sessions/{rec.id}", headers=h, cookies={CSRF_COOKIE: _csrf(me)})
    assert out.status_code == 204
    assert [c for c in out.headers.get_list("set-cookie") if c.startswith(CSRF_COOKIE)]


def test_unauthenticated_flood_stays_403_but_stops_writing_audit_rows(stack: _Stack) -> None:
    stack.client.cookies.clear()
    rs = [stack.client.post("/auth/logout") for _ in range(25)]
    assert {r.status_code for r in rs} == {403}
    assert {r.json()["code"] for r in rs} == {"csrf_token_invalid"}
    assert len(stack.audit.of("auth.csrf_refused")) == 20
    assert "retry-after" in rs[-1].headers


def test_production_audit_records_the_contract_route_template(stack: _Stack) -> None:
    """r2: under create_app (included routers) the audited path is the contract
    template, not `(unmatched)`."""
    r = stack.login()
    stack.client.cookies.clear()
    stack.client.post("/auth/logout", headers={"Authorization": f"Bearer {_bearer(r)}"})
    assert stack.audit.of("auth.csrf_refused")[-1]["after_state"]["path"] == "/auth/logout"
    sid = uuid.uuid4()
    stack.client.delete(f"/api/v1/me/sessions/{sid}", headers={"Authorization": "Bearer x"})
    rec = stack.audit.of("auth.csrf_refused")[-1]
    assert rec["after_state"]["path"] == "/me/sessions/{sessionId}"
    assert str(sid) not in repr(rec)


@pytest.mark.parametrize("csrf", ["missing", "wrong"])
def test_rotated_refresh_token_without_its_csrf_token_still_revokes_the_family(
    stack: _Stack, csrf: str
) -> None:
    """r2: reuse detection runs before the CSRF check (it only revokes, never mints).
    A thief replaying a rotated token without the old session's CSRF token still
    triggers the family revoke and the CRITICAL reuse audit."""
    r = stack.login()
    old_refresh, token = r.cookies["cv_refresh"], _csrf(r)
    stack.client.cookies.clear()
    ok = stack.client.post(
        "/auth/refresh",
        headers={"Origin": _ORIGIN, CSRF_HEADER: token},
        cookies={"cv_refresh": old_refresh, CSRF_COOKIE: token},
    )
    assert ok.status_code == 200
    successor_access = _bearer(ok)
    other = _CODEC_OTHER.issue("x")
    stack.client.cookies.clear()
    headers = {"Origin": _ORIGIN} if csrf == "missing" else {"Origin": _ORIGIN, CSRF_HEADER: other}
    cookies = {"cv_refresh": old_refresh}
    if csrf == "wrong":
        cookies[CSRF_COOKIE] = other
    replay = stack.client.post("/auth/refresh", headers=headers, cookies=cookies)
    assert replay.status_code == 401, replay.text
    reuse = stack.audit.of("auth.refresh_reuse_detected")
    assert reuse and reuse[-1]["severity"].value == "critical"
    stack.client.cookies.clear()
    gone = stack.client.get(
        "/auth/session", headers={"Authorization": f"Bearer {successor_access}"}
    )
    assert gone.status_code == 401  # successor revoked with the family


def test_refusal_is_visible_on_the_scraped_registry(stack: _Stack) -> None:
    """r2: `auth_csrf_refused_total` is re-exported onto ctx.metrics (what Prometheus
    scrapes via CV_METRICS_BIND), so the CsrfRefusals* alerts can fire."""
    from prometheus_client import generate_latest

    stack.client.cookies.clear()
    stack.client.post("/auth/logout")
    text = generate_latest(stack.ctx.metrics).decode()
    line = next((ln for ln in text.splitlines() if ln.startswith("auth_csrf_refused_total{")), "")
    assert 'reason="missing"' in text and 'env="' in line


def test_middleware_and_routers_share_one_codec(stack: _Stack) -> None:
    from candleviewer.api.csrf import CsrfMiddleware

    app = stack.client.app
    mw = next(m for m in app.user_middleware if m.cls is CsrfMiddleware)  # type: ignore[attr-defined]
    assert mw.kwargs["codec"] is app.state.csrf_codec  # type: ignore[attr-defined]


def test_key_rotation_through_create_app_keeps_open_tabs_working(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pydantic import SecretStr

    from candleviewer.settings import Settings

    old = "ab" * 32
    s_old = Settings(auth_csrf_key_hex=SecretStr(old))
    s_new = Settings(
        auth_csrf_key_hex=SecretStr("cd" * 32), auth_csrf_previous_key_hex=SecretStr(old)
    )
    token = appmod.create_app(s_old).state.csrf_codec.issue("sid")
    rotated = appmod.create_app(s_new).state.csrf_codec
    assert rotated.verify(token, "sid") is CsrfVerdict.OK
    assert rotated.issue("sid") != token


def test_audit_actor_ip_is_the_address_mesh_admitted_not_a_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Behind the configured trusted proxy, `actor_ip` is MeshOnly's resolved client;
    a client-supplied header from anyone else is ignored."""
    monkeypatch.setenv("CV_MESH_TRUSTED_PROXY_HEADER", "X-Forwarded-For")
    monkeypatch.setenv("CV_MESH_TRUSTED_PROXY_ADDRESS", "127.0.0.1")
    monkeypatch.setenv("CV_MESH_CIDRS_CSV", "100.64.0.0/10")
    app = appmod.create_app()
    audit = _Audit()
    app.state.app_context.audit._writer = audit
    via_proxy = TestClient(app, client=("127.0.0.1", 1), raise_server_exceptions=False)
    via_proxy.post("/auth/logout", headers={"X-Forwarded-For": "6.6.6.6, 100.64.0.7"})
    assert audit.of("auth.csrf_refused")[-1]["actor_ip"] == "100.64.0.7"
    direct = TestClient(app, client=("100.64.0.9", 1), raise_server_exceptions=False)
    direct.post("/auth/logout", headers={"X-Forwarded-For": "100.64.0.7"})
    assert audit.of("auth.csrf_refused")[-1]["actor_ip"] == "100.64.0.9"


@pytest.mark.parametrize("variant", ["no_header", "no_cookie", "mismatch"])
def test_refresh_route_refuses_missing_or_mismatched_pair_without_rotating(
    stack: _Stack, variant: str
) -> None:
    r = stack.login()
    token, refresh = _csrf(r), r.cookies["cv_refresh"]
    headers = {"Origin": _ORIGIN, CSRF_HEADER: token}
    cookies = {"cv_refresh": refresh, CSRF_COOKIE: token}
    if variant == "no_header":
        del headers[CSRF_HEADER]
    elif variant == "no_cookie":
        del cookies[CSRF_COOKIE]
    else:
        cookies[CSRF_COOKIE] = _CODEC_OTHER.issue("x")
    stack.client.cookies.clear()
    out = stack.client.post("/auth/refresh", headers=headers, cookies=cookies)
    reason = "mismatch" if variant == "mismatch" else "missing"
    _assert_refused(stack, out, reason, token)
    assert not stack.audit.of("auth.session_refreshed")
