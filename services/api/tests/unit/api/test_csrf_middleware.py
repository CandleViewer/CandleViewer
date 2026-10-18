"""`CsrfMiddleware` edges not reachable through the auth routers (#2090). No I/O."""

from __future__ import annotations

import asyncio
import gc
import uuid
import weakref
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.api.csrf import (
    CsrfMiddleware,
    CsrfRefusal,
    RefusalAuditTracker,
    is_exempt,
    is_unsafe,
    route_path,
    verify_refresh_csrf,
)
from candleviewer.auth.csrf import CSRF_COOKIE, CSRF_HEADER, CsrfCodec
from candleviewer.auth.metrics import CSRF_AUDIT_REASONS, auth_csrf_refused_total
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.throttle import PerIpLoginThrottle
from candleviewer.ws.lifecycle import origin_refusal

_CODEC = CsrfCodec(b"\x07" * 32)
_SID = uuid.uuid4()
_ORIGIN = "https://app.example"


_NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


def _rec(
    sid: uuid.UUID = _SID,
    *,
    revoked: bool = False,
    expired: bool = False,
    ttl_expired: bool = False,
    idle_locked: bool = False,
) -> SessionRecord:
    """A real record; each flag breaks exactly one `is_live_session` condition."""
    issued = _NOW - (timedelta(minutes=13) if ttl_expired else timedelta(minutes=1))
    return SessionRecord(
        id=sid,
        user_id=sid,
        refresh_token_hash="x",  # noqa: S106 - inert placeholder
        access_token_jti=None,
        issued_at=issued,
        last_seen_at=_NOW - (timedelta(hours=1) if idle_locked else timedelta(seconds=5)),
        expires_at=_NOW - timedelta(seconds=1) if expired else _NOW + timedelta(hours=1),
        revoked_at=_NOW if revoked else None,
        revoked_reason="logout" if revoked else None,
        ip=None,
        user_agent=None,
        device_label=None,
        is_electron=False,
        mfa_satisfied_at=None,
    )


_BEARERS = {
    "good": _rec(),
    "revoked": _rec(revoked=True),
    "expired": _rec(expired=True),
    "ttl_expired": _rec(ttl_expired=True),
    "idle_locked": _rec(idle_locked=True),
}


class _Sessions:
    async def peek_access_token(self, token: str) -> Any:
        return _BEARERS.get(token)


class _Audit:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def emit(self, action: str, **kw: Any) -> None:
        self.calls.append({"action": action, **kw})


class _Hangs:
    async def emit(self, action: str, **kw: Any) -> None:
        await asyncio.Event().wait()  # never set: the guard must time out, not hang


class _Raises:
    async def emit(self, action: str, **kw: Any) -> None:
        raise RuntimeError("sink down")


def _app(
    sessions: Any = None,
    audit: Any = None,
    anon_max: int = 1000,
    timeout_s: float = 2.0,
    session_max: int = 1000,
) -> tuple[TestClient, Any]:
    app = FastAPI()
    audit = audit if audit is not None else _Audit()

    @app.post("/auth/refresh")
    async def refresh() -> dict[str, str]:
        return {"route": "refresh"}  # the real route verifies the binding (verify_refresh_csrf)

    @app.post("/w/{item}")
    async def w(item: str) -> dict[str, str]:
        return {"ok": item}

    @app.api_route("/purge", methods=["PURGE"])
    async def purge() -> dict[str, str]:
        return {"ok": "purged"}

    @app.post("/auth/login")
    async def login() -> dict[str, str]:
        return {"ok": "login"}

    app.add_middleware(
        CsrfMiddleware,
        codec=_CODEC,
        sessions=lambda: sessions,
        audit=audit,
        allowed_origins=frozenset({_ORIGIN}),
        operations=frozenset({("POST", "/w/{item}"), ("POST", "/auth/login"), ("PURGE", "/purge")}),
        anon_throttle=PerIpLoginThrottle(max_attempts=anon_max, window_s=60.0, clock=lambda: 0.0),
        session_throttle=PerIpLoginThrottle(
            max_attempts=session_max, window_s=60.0, clock=lambda: 0.0
        ),
        audit_timeout_s=timeout_s,
        clock=lambda: _NOW,
    )
    return TestClient(app, raise_server_exceptions=False), audit


def _pair(sid: uuid.UUID = _SID) -> dict[str, str]:
    t = _CODEC.issue(str(sid))
    return {CSRF_HEADER: t, "Cookie": f"{CSRF_COOKIE}={t}"}


def _code(r: Any) -> str | None:
    try:
        return str(r.json().get("code"))
    except ValueError:
        return None


# -- classification ---------------------------------------------------------------


def test_route_path_unsafe_methods_and_exact_exemptions() -> None:
    assert route_path("/api/v1/auth/login") == "/auth/login"
    assert route_path("/api/v1") == "/"
    assert route_path("/api/v10/x") == "/api/v10/x"
    assert not is_unsafe("GET") and not is_unsafe("head") and not is_unsafe("OPTIONS")
    assert is_unsafe("TRACE")  # contract "Exempt" lists GET/HEAD/OPTIONS only
    assert is_unsafe("PURGE") and is_unsafe("PROPFIND")  # allow-list of safe methods only
    assert is_exempt("post", "/api/v1/invites/t/confirm")
    assert not is_exempt("PUT", "/auth/login")  # exemption is POST only
    assert not is_exempt("DELETE", "/invites/t")
    for path in ("/auth/login\n", "/auth/login/", "/auth/login/x", "/invites/a/b/confirm"):
        assert not is_exempt("POST", path), repr(path)


def test_non_standard_unsafe_method_is_guarded() -> None:
    client, _ = _app(_Sessions())
    r = client.request("PURGE", "/purge")
    assert r.status_code == 403 and _code(r) == "csrf_token_invalid"
    ok = client.request("PURGE", "/purge", headers={**_pair(), "Authorization": "Bearer good"})
    assert ok.status_code == 200


# -- SR-041 binding -----------------------------------------------------------------


def test_valid_bound_token_passes() -> None:
    client, audit = _app(_Sessions())
    r = client.post("/w/x", headers={**_pair(), "Authorization": "Bearer good"})
    assert r.json() == {"ok": "x"} and not audit.calls


@pytest.mark.parametrize("bearer", [None, "Bearer bad", "Basic abc"])
def test_no_resolvable_session_is_refused_even_with_header_equal_cookie(
    bearer: str | None,
) -> None:
    client, audit = _app(_Sessions())
    headers = _pair() if bearer is None else {**_pair(), "Authorization": bearer}
    r = client.post("/w/x", headers=headers)
    assert r.status_code == 403 and _code(r) == "csrf_token_invalid"
    assert audit.calls[-1]["reason"] == "wrong_session"


def test_sessions_backend_not_wired_fails_closed() -> None:
    client, _ = _app(None)
    r = client.post("/w/x", headers={**_pair(), "Authorization": "Bearer good"})
    assert r.status_code == 403 and _code(r) == "csrf_token_invalid"


def test_refusal_audit_is_bounded_and_carries_no_token_value() -> None:
    client, audit = _app(_Sessions())
    h = _pair(uuid.uuid4())
    r = client.post("/w/" + "x" * 3000, headers={**h, "Authorization": "Bearer good"})
    assert r.status_code == 403
    rec = audit.calls[-1]
    assert rec["action"] == "auth.csrf_refused" and rec["reason"] == "wrong_session"
    assert h[CSRF_HEADER] not in repr(rec) and h[CSRF_HEADER] not in r.text
    assert rec["after_state"] == {"method": "POST", "path": "/w/{item}"}  # template, not input
    assert rec["actor_ip"] == "testclient"
    client.post("/nowhere/" + "y" * 100, headers=h)
    assert audit.calls[-1]["after_state"]["path"] == "(unmatched)"
    client.request("X" * 4000, "/w/x", headers=h)
    assert audit.calls[-1]["after_state"]["method"] == "(other)"  # closed method set


# -- refresh: the route owns the binding check ------------------------------------------


def test_refresh_is_delegated_whole_to_the_route() -> None:
    """The route verifies presence, equality and the binding to the refresh token's
    own session (after reuse detection); the middleware passes the exact path on."""
    client, audit = _app(_Sessions())
    assert client.post("/auth/refresh").json() == {"route": "refresh"}
    assert client.post("/api/v1/auth/refresh").status_code == 404  # not mounted here
    assert not audit.calls
    r = client.post("/auth/refresh", headers={"Origin": "https://evil.example"})
    assert _code(r) == "csrf_token_invalid"  # SR-042 still applies first


# -- logout: the route binds only a cookie-identified one (contract "Idle lock", #2300) ---------


def _with_logout(client: TestClient) -> TestClient:
    async def logout() -> dict[str, str]:
        return {"route": "logout"}  # the real route binds a cookie-identified logout itself

    app = client.app
    assert isinstance(app, FastAPI)  # TestClient.app is typed as bare ASGI
    app.add_api_route("/auth/logout", logout, methods=["POST"])
    return client


def _refresh_cookie(pair: dict[str, str]) -> dict[str, str]:
    return {**pair, "Cookie": f"{pair['Cookie']}; cv_refresh=opaque"}


def test_a_logout_identified_by_its_refresh_cookie_is_bound_by_the_route() -> None:
    """No access token inside its lifetime (none, or past `ACCESS_TOKEN_TTL`) and the
    `cv_refresh` cookie present: the route binds the token to the cookie's session. The
    session-independent checks (presence, equality, shape) still run here."""
    client, audit = _app(_Sessions())
    _with_logout(client)
    other = _refresh_cookie(_pair(uuid.uuid4()))
    for bearer in (None, "Bearer ttl_expired"):
        headers = other if bearer is None else {**other, "Authorization": bearer}
        assert client.post("/auth/logout", headers=headers).json() == {"route": "logout"}
    assert not audit.calls
    r = client.post("/auth/logout", headers={"Cookie": "cv_refresh=opaque"})
    assert _code(r) == "csrf_token_invalid" and audit.calls[-1]["reason"] == "missing"


@pytest.mark.parametrize("bearer", ["Bearer good", "Bearer bad"])
def test_a_logout_with_a_live_or_unknown_access_token_is_bound_here(bearer: str) -> None:
    """A live access token identifies the logout, so another session's cookie cannot move
    the binding; a never-issued one resolves no session and is refused as before."""
    client, audit = _app(_Sessions())
    _with_logout(client)
    other = _refresh_cookie(_pair(uuid.uuid4()))
    r = client.post("/auth/logout", headers={**other, "Authorization": bearer})
    assert r.status_code == 403 and _code(r) == "csrf_token_invalid"
    assert audit.calls[-1]["reason"] == "wrong_session"


def test_a_bearer_logout_bound_to_its_own_session_passes_with_the_cookie_present() -> None:
    client, audit = _app(_Sessions())
    _with_logout(client)
    headers = {**_refresh_cookie(_pair()), "Authorization": "Bearer good"}
    assert client.post("/auth/logout", headers=headers).json() == {"route": "logout"}
    assert not audit.calls


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/auth/logout/"),
        ("POST", "/auth/logoutx"),
        ("POST", "/auth/logout/all"),
        ("POST", "/api/v2/auth/logout"),
        ("PUT", "/auth/logout"),
    ],
)
def test_only_a_post_to_the_exact_logout_path_is_deferred_to_the_route(
    method: str, path: str
) -> None:
    """The cookie deferral is `POST /auth/logout` exactly: a cookie-only request to a
    neighbouring path, or with another method, is bound here like any other write."""
    client, audit = _app(_Sessions())
    _with_logout(client)
    r = client.request(method, path, headers=_refresh_cookie(_pair(uuid.uuid4())))
    assert r.status_code == 403 and _code(r) == "csrf_token_invalid"
    assert audit.calls[-1]["reason"] == "wrong_session"


def test_verify_refresh_csrf_reasons() -> None:
    t = _CODEC.issue(str(_SID))
    assert verify_refresh_csrf(_CODEC, t, t, str(_SID)) is None
    assert verify_refresh_csrf(_CODEC, None, t, str(_SID)) is CsrfRefusal.MISSING
    assert verify_refresh_csrf(_CODEC, t, "x.y", str(_SID)) is CsrfRefusal.MISMATCH
    assert verify_refresh_csrf(_CODEC, "x.y", "x.y", str(_SID)) is CsrfRefusal.BAD_MAC
    other = str(uuid.uuid4())
    assert verify_refresh_csrf(_CODEC, t, t, other) is CsrfRefusal.WRONG_SESSION


@pytest.mark.parametrize(
    "path", ["/auth/refresh%0A", "/api/v1/auth/refresh%0a", "/w/x%0D", "/w/%00"]
)
def test_control_characters_in_the_path_are_refused_400(path: str) -> None:
    client, _ = _app(_Sessions())
    r = client.post(path, headers={**_pair(), "Authorization": "Bearer good"})
    assert r.status_code == 400 and _code(r) == "validation_failed"


# -- cookies (Starlette's lenient parser, same as the routes) --------------------------------


def test_sibling_cookie_with_space_does_not_hide_the_csrf_cookie() -> None:
    client, _ = _app(_Sessions())
    t = _CODEC.issue(str(_SID))
    cookie = f"o=a b; {CSRF_COOKIE}={t}"
    r = client.post(
        "/w/x", headers={CSRF_HEADER: t, "Authorization": "Bearer good", "Cookie": cookie}
    )
    assert r.status_code == 200


def test_duplicate_csrf_cookie_last_value_wins_like_request_cookies() -> None:
    client, _ = _app(_Sessions())
    good = _CODEC.issue(str(_SID))
    stale = _CODEC.issue(str(uuid.uuid4()))
    h = {CSRF_HEADER: good, "Authorization": "Bearer good"}
    ok = client.post(
        "/w/x", headers={**h, "Cookie": f"{CSRF_COOKIE}={stale}; {CSRF_COOKIE}={good}"}
    )
    assert ok.status_code == 200
    bad = client.post(
        "/w/x", headers={**h, "Cookie": f"{CSRF_COOKIE}={good}; {CSRF_COOKIE}={stale}"}
    )
    assert bad.status_code == 403  # header != effective cookie: mismatch, fail closed


# -- SR-042 -----------------------------------------------------------------------------------

#: `Sec-Fetch-Site` absent, plus every value a browser sends.
_SITES = [None, "same-origin", "none", "same-site", "cross-site"]


def _with_site(origin: str | None, site: str | None) -> dict[str, str]:
    headers = {} if origin is None else {"Origin": origin}
    return headers if site is None else {**headers, "Sec-Fetch-Site": site}


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example"},
        {"Sec-Fetch-Site": "cross-site"},  # no Origin: not a listed one, so still refused
        {"Sec-Fetch-Site": "Cross-Site"},  # header values are matched case-insensitively
        {"Sec-Fetch-Site": "same-site"},  # a sibling host (e.g. another *.ts.net node)
        {"Origin": "null"},
    ],
)
def test_cross_origin_unsafe_requests_are_refused_including_exempt_routes(
    headers: dict[str, str],
) -> None:
    client, audit = _app(_Sessions())
    for path in ("/auth/login", "/w/x"):
        r = client.post(path, headers={**_pair(), "Authorization": "Bearer good", **headers})
        assert r.status_code == 403 and _code(r) == "csrf_token_invalid", path
        assert audit.calls[-1]["reason"] == "cross_origin"


@pytest.mark.parametrize("site", _SITES)
def test_listed_origin_is_admitted_whatever_sec_fetch_site_says(site: str | None) -> None:
    """#2274, SR-042: the allow-list decides, as on the WS upgrade (`23-ws-protocol.md` §2.5).
    A listed app origin on another site (the packaged Electron `app://`, a dev page on another
    port) arrives as `cross-site` / `same-site`; a foreign page cannot make a browser send a
    listed `Origin`, so the fetch metadata adds nothing for it."""
    client, audit = _app(_Sessions())
    headers = _with_site(_ORIGIN, site)
    bound = client.post("/w/x", headers={**_pair(), "Authorization": "Bearer good", **headers})
    login = client.post("/auth/login", headers=headers)  # exempt: the Origin is its only guard
    assert (bound.status_code, login.status_code) == (200, 200)
    assert not audit.calls


@pytest.mark.parametrize("site", _SITES)
@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.example",
        "null",  # an opaque origin is never listed
        "http://app.example",  # the listed host, another scheme
        "https://app.example:8443",  # the listed host, another port
        "https://app.example.evil.example",  # the listed host as a prefix
    ],
)
def test_unlisted_origin_is_refused_whatever_sec_fetch_site_says(
    origin: str, site: str | None
) -> None:
    client, audit = _app(_Sessions())
    for path in ("/auth/login", "/w/x"):
        headers = {**_pair(), "Authorization": "Bearer good", **_with_site(origin, site)}
        r = client.post(path, headers=headers)
        assert r.status_code == 403 and _code(r) == "csrf_token_invalid", path
        assert audit.calls[-1]["reason"] == "cross_origin"


@pytest.mark.parametrize("site", ["cross-site", "same-site"])
def test_listed_origin_on_another_site_still_needs_the_bound_token(site: str) -> None:
    """Admission by the allow-list is not admission to the write: SR-041 still binds it."""
    client, audit = _app(_Sessions())
    headers = {"Origin": _ORIGIN, "Sec-Fetch-Site": site, "Authorization": "Bearer good"}
    assert client.post("/w/x", headers=headers).status_code == 403
    assert audit.calls[-1]["reason"] == "missing"
    other = client.post("/w/x", headers={**headers, **_pair(uuid.uuid4())})  # another session's
    assert other.status_code == 403
    assert audit.calls[-1]["reason"] == "wrong_session"
    assert client.post("/w/x", headers={**headers, **_pair()}).status_code == 200


@pytest.mark.parametrize("site", _SITES)
@pytest.mark.parametrize("origin", [_ORIGIN, _ORIGIN + "/", "https://evil.example", "null"])
def test_rest_and_ws_let_the_allow_list_decide_alike(origin: str, site: str | None) -> None:
    """SR-042: for one present `Origin`, the REST guard and the WS upgrade (`23-ws-protocol.md`
    §2.5) refuse exactly the same requests. They differ only on a missing or repeated `Origin`,
    deliberately (SR-042)."""
    client, _ = _app(_Sessions())
    rest_refused = client.post("/auth/login", headers=_with_site(origin, site)).status_code == 403
    fetch_sites = [] if site is None else [site]
    ws_refused = origin_refusal([origin], fetch_sites, frozenset({_ORIGIN})) is not None
    assert rest_refused == ws_refused


def test_allowed_origin_and_same_site_pass() -> None:
    client, _ = _app(_Sessions())
    h = {**_pair(), "Authorization": "Bearer good"}
    assert client.post("/w/x", headers={**h, "Origin": _ORIGIN + "/"}).status_code == 200
    assert client.post("/w/x", headers={**h, "Sec-Fetch-Site": "same-origin"}).status_code == 200
    assert client.post("/w/x", headers={**h, "Sec-Fetch-Site": "none"}).status_code == 200
    assert client.post("/auth/login", headers={"Origin": _ORIGIN}).status_code == 200


# -- audit flood / failure -------------------------------------------------------------------


def _snapshot() -> dict[str, float]:
    """The audit bookkeeping counters (`auth_csrf_refused_total{reason=audit_*}`) right now."""
    return {
        r: float(auth_csrf_refused_total.labels(reason=r)._value.get()) for r in CSRF_AUDIT_REASONS
    }


def _delta(before: dict[str, float]) -> dict[str, float]:
    """What changed since `before`; unchanged reasons are left out, so an equality check also
    proves that no other bookkeeping reason moved."""
    now = _snapshot()
    return {r: now[r] - before[r] for r in now if now[r] != before[r]}


def test_over_budget_refusals_stay_403_without_audit_but_counted() -> None:
    """Over the per-IP budget only the audit write is skipped: the reply stays the same
    403 csrf_token_invalid (+Retry-After) so client recovery keeps working."""
    client, audit = _app(_Sessions(), anon_max=3)
    before = auth_csrf_refused_total.labels(reason="missing")._value.get()
    bookkeeping = _snapshot()
    rs = [client.post("/w/x") for _ in range(6)]
    assert [r.status_code for r in rs] == [403] * 6
    assert all(_code(r) == "csrf_token_invalid" for r in rs)
    assert "retry-after" not in rs[2].headers and int(rs[3].headers["retry-after"]) >= 1
    assert len(audit.calls) == 3  # no audit write once over the per-IP budget
    assert auth_csrf_refused_total.labels(reason="missing")._value.get() == before + 6
    assert _delta(bookkeeping) == {"audit_throttled": 3}  # a budget, not the in-flight cap


@pytest.mark.parametrize("bearer", ["revoked", "expired", "ttl_expired", "idle_locked"])
def test_dead_session_refusals_share_the_per_ip_budget(bearer: str) -> None:
    """A revoked / absolute-expired record still has its MAC checked, but its refusals
    are not 'session-bound' for audit: an old leaked bearer cannot flood the audit log."""
    client, audit = _app(_Sessions(), anon_max=2)
    h = {**_pair(uuid.uuid4()), "Authorization": f"Bearer {bearer}"}
    codes = [client.post("/w/x", headers=h).status_code for _ in range(5)]
    assert codes == [403] * 5 and len(audit.calls) == 2


def test_live_session_refusals_have_their_own_per_session_budget() -> None:
    """Not capped by the per-IP budget, but bounded per session (#2238 r3)."""
    client, audit = _app(_Sessions(), anon_max=1, session_max=3)
    h = {**_pair(uuid.uuid4()), "Authorization": "Bearer good"}
    rs = [client.post("/w/x", headers=h) for _ in range(5)]
    assert [r.status_code for r in rs] == [403] * 5
    assert len(audit.calls) == 3 and "retry-after" in rs[-1].headers


@pytest.mark.parametrize("sink", [_Hangs(), _Raises()])
def test_audit_hang_or_failure_still_refuses_promptly(sink: Any) -> None:
    client, _ = _app(_Sessions(), audit=sink, timeout_s=0.05)
    r = client.post("/w/x")
    assert r.status_code == 403 and _code(r) == "csrf_token_invalid"


def test_slow_audit_is_never_cancelled_mid_append() -> None:
    """Review #2238 r2: a timed-out refusal audit must not cancel `AuditWriter.emit`
    (cancelling releases the WAL lock while the append thread still runs). The emit
    runs as a shielded, tracked task: the request is refused at the timeout, the lock
    stays held until the append returns, and the record still lands."""
    import threading

    release = threading.Event()
    seen: dict[str, Any] = {}

    class _SlowWal:
        def __init__(self) -> None:
            self.lock = asyncio.Lock()
            self.records: list[str] = []

        async def emit(self, action: str, **kw: Any) -> None:
            async with self.lock:  # stands in for AuditWriter._wal_lock
                await asyncio.to_thread(release.wait, 5)  # the blocking WAL append
                self.records.append(action)

    wal = _SlowWal()

    async def inner(scope: Any, receive: Any, send: Any) -> None:
        raise AssertionError("refused requests never reach the app")

    mw = CsrfMiddleware(
        inner,
        codec=_CODEC,
        sessions=lambda: None,
        audit=wal,
        allowed_origins=frozenset(),
        audit_timeout_s=0.05,
        clock=lambda: _NOW,
    )
    sent: list[Any] = []

    async def recv() -> Any:
        return {"type": "http.request", "body": b""}

    async def send(msg: Any) -> None:
        sent.append(msg)

    async def drive() -> None:
        scope = {"type": "http", "method": "POST", "path": "/w/x", "headers": []}
        await mw(scope, recv, send)  # returns at the timeout, refused
        seen["status"] = sent[0]["status"]
        seen["locked_after_refusal"] = wal.lock.locked()
        seen["pending"] = len(mw.tracker)
        release.set()  # the "disk" finishes the append
        assert await mw.tracker.drain(5) == 0  # the tracked task completes on its own
        seen["records"] = list(wal.records)
        seen["locked_at_end"] = wal.lock.locked()

    before = _snapshot()
    asyncio.run(drive())
    assert _delta(before) == {"audit_slow": 1}  # slow once, and the record landed: not lost
    assert seen["status"] == 403
    assert seen["locked_after_refusal"] is True  # NOT released by a cancellation
    assert seen["pending"] == 1  # tracked (strong reference)
    assert seen["records"] == ["auth.csrf_refused"] and seen["locked_at_end"] is False


# -- non-HTTP scopes and safe methods pass untouched ------------------------------------------


def test_websocket_lifespan_and_safe_methods_pass_untouched() -> None:
    seen: list[str] = []

    async def inner(scope: Any, receive: Any, send: Any) -> None:
        seen.append(scope["type"] + ":" + scope.get("method", ""))

    mw = CsrfMiddleware(
        inner, codec=_CODEC, sessions=lambda: None, audit=_Audit(), allowed_origins=frozenset()
    )

    async def noop(*_a: Any) -> Any:
        return {}

    async def drive() -> None:
        await mw({"type": "websocket", "path": "/ws", "headers": []}, noop, noop)
        await mw({"type": "lifespan"}, noop, noop)
        for method in ("GET", "HEAD", "OPTIONS"):
            await mw({"type": "http", "method": method, "path": "/x", "headers": []}, noop, noop)

    asyncio.run(drive())
    assert seen == ["websocket:", "lifespan:", "http:GET", "http:HEAD", "http:OPTIONS"]


def test_chunked_body_on_a_guarded_route_is_passed_through_intact() -> None:
    app = FastAPI()

    @app.post("/echo")
    async def echo(body: dict[str, Any]) -> dict[str, Any]:
        return body

    app.add_middleware(
        CsrfMiddleware,
        codec=_CODEC,
        sessions=_Sessions,
        audit=_Audit(),
        allowed_origins=frozenset(),
    )

    def chunks() -> Any:
        yield b'{"a": '
        yield b'"' + b"z" * 10_000 + b'"}'

    headers = {**_pair(), "Authorization": "Bearer good", "Content-Type": "application/json"}
    r = TestClient(app).post("/echo", content=chunks(), headers=headers)
    assert r.status_code == 200 and len(r.json()["a"]) == 10_000


def test_inflight_audits_are_capped_during_a_wal_stall() -> None:
    """C-2.18 (#2238 r3): with the writer stalled, a flood of refusals (each from its own
    live session, so no per-session/IP budget applies) never puts more than the cap in
    flight, nor more than the cap waiting on the WAL lock; the rest are counted
    `audit_saturated` (the cap, not a budget) and still get the same 403."""
    import threading

    release = threading.Event()
    waiters = {"max": 0, "now": 0}

    class _StalledWal:
        def __init__(self) -> None:
            self.lock = asyncio.Lock()
            self.records = 0

        async def emit(self, action: str, **kw: Any) -> None:
            waiters["now"] += 1
            waiters["max"] = max(waiters["max"], waiters["now"])
            try:
                async with self.lock:  # stands in for AuditWriter._wal_lock
                    await asyncio.to_thread(release.wait, 5)
                    self.records += 1
            finally:
                waiters["now"] -= 1

    class _ManySessions:
        async def peek_access_token(self, token: str) -> Any:
            return _rec(uuid.UUID(token))  # every bearer is its own live session

    cap = 8
    wal = _StalledWal()

    async def inner(scope: Any, receive: Any, send: Any) -> None:
        raise AssertionError("refused requests never reach the app")

    mw = CsrfMiddleware(
        inner,
        codec=_CODEC,
        sessions=_ManySessions,
        audit=wal,
        allowed_origins=frozenset(),
        audit_timeout_s=0.01,
        clock=lambda: _NOW,
        tracker=RefusalAuditTracker(cap=cap),
    )
    statuses: list[int] = []

    async def recv() -> Any:
        return {"type": "http.request", "body": b""}

    async def drive() -> None:
        before = _snapshot()
        peak = 0
        for _ in range(60):
            sid = uuid.uuid4()
            other = _CODEC.issue(str(uuid.uuid4()))  # bound to another session -> refused
            headers = [
                (b"authorization", f"Bearer {sid}".encode()),
                (b"x-csrf-token", other.encode()),
                (b"cookie", f"{CSRF_COOKIE}={other}".encode()),
            ]
            sent: list[Any] = []

            async def send(msg: Any, sent: list[Any] = sent) -> None:
                sent.append(msg)

            scope = {"type": "http", "method": "POST", "path": "/w/x", "headers": headers}
            await mw(scope, recv, send)
            statuses.append(sent[0]["status"])
            peak = max(peak, len(mw.tracker))
        assert peak <= cap and waiters["max"] <= cap
        moved = _delta(before)
        assert moved["audit_saturated"] == 60 - cap
        assert "audit_throttled" not in moved
        release.set()
        assert await mw.tracker.drain(5) == 0
        assert wal.records == cap

    asyncio.run(drive())
    assert set(statuses) == {403}


def test_tracker_drain_is_bounded_and_reports_leftovers() -> None:
    async def never() -> None:
        await asyncio.Event().wait()

    async def drive() -> int:
        tracker = RefusalAuditTracker(cap=2)
        task = tracker.track(never())
        left = await tracker.drain(0.01)
        task.cancel()
        return left

    assert asyncio.run(drive()) == 1


def test_late_failures_and_drain_leftovers_are_reported_once_and_only_to_their_owner() -> None:
    """The tracker is shared (CSRF guard, session-fixation audit) and knows no metric: each
    write's own `on_lost` hears of it once, and a write without one moves no CSRF series."""
    lost: list[str] = []

    async def drive() -> tuple[int, list[str], dict[str, float]]:
        assert await RefusalAuditTracker().drain(0.01) == 0  # idle: nothing to wait for
        early, late = asyncio.Event(), asyncio.Event()

        async def fails_on(signal: asyncio.Event) -> None:
            await signal.wait()
            raise OSError("EIO")

        before = _snapshot()
        tracker = RefusalAuditTracker()
        gone = tracker.track(fails_on(early))  # no owner, like the session-fixation audit
        tracker.mark_timed_out(gone)
        early.set()
        await asyncio.gather(gone, return_exceptions=True)  # failed after its caller left
        owned = tracker.track(fails_on(late), on_lost=lambda: lost.append("owned"))
        ownerless = tracker.track(fails_on(late))
        tracker.mark_timed_out(owned)
        tracker.mark_timed_out(ownerless)
        left = await tracker.drain(0.01)
        at_drain = list(lost)
        late.set()
        await asyncio.gather(owned, ownerless, return_exceptions=True)  # both fail after it
        return left, at_drain, _delta(before)

    left, at_drain, moved = asyncio.run(drive())
    assert left == 2 and at_drain == ["owned"]
    assert lost == ["owned"]  # the later failure is not reported again
    assert moved == {}


def test_a_late_failure_is_logged_under_the_event_its_owner_named_else_the_csrf_one() -> None:
    # Shared by three audit paths, each naming its own late-failure line (#2319 review).
    from structlog.testing import capture_logs

    lost: list[str] = []

    async def drive() -> None:
        async def fails() -> None:
            raise OSError("EIO")

        tracker = RefusalAuditTracker()
        named = tracker.track(
            fails(),
            on_lost=lambda: lost.append("named"),
            late_failure_event="auth.other.audit_failed_late",
        )
        unnamed = tracker.track(fails())
        tracker.mark_timed_out(named)
        tracker.mark_timed_out(unnamed)
        await asyncio.gather(named, unnamed, return_exceptions=True)

    with capture_logs() as logs:
        asyncio.run(drive())
    assert sorted(e["event"] for e in logs) == [
        "auth.csrf_refused.audit_failed_late",
        "auth.other.audit_failed_late",
    ]
    assert lost == ["named"]  # the owner's own accounting is not replaced by the name


# -- a write that ended before its caller handed it over (#3054 item 2) ----------------------------

_OWNED_LATE_EVENT = "auth.other.audit_failed_late"


@pytest.mark.parametrize("window", ["done_callback_queued", "done_callback_ran"])
def test_a_write_that_failed_before_its_caller_handed_it_over_is_reported_once_to_its_owner(
    window: str,
) -> None:
    """The caller's cancel handler can run after the write has ended: in the very loop iteration it
    failed in (the tracker's done-callback is still queued), or after that callback ran without the
    write being marked. `mark_timed_out` reports the failure then, to the write's own owner and
    under its own event, as it would have when the write ended; handing it over twice does not
    report it twice."""
    from structlog.testing import capture_logs

    lost: list[str] = []

    async def drive() -> None:
        async def fails() -> None:
            raise OSError("EIO")

        tracker = RefusalAuditTracker()
        task = tracker.track(
            fails(), on_lost=lambda: lost.append("owned"), late_failure_event=_OWNED_LATE_EVENT
        )
        if window == "done_callback_ran":
            await asyncio.gather(task, return_exceptions=True)  # ended, settled, never marked
            assert len(tracker) == 0
        else:
            await asyncio.sleep(0)  # ended, its done-callback queued for the next loop iteration
            assert task.done() and len(tracker) == 1
        tracker.mark_timed_out(task)
        tracker.mark_timed_out(task)
        await asyncio.sleep(0)  # a queued done-callback runs now and has nothing left to report
        assert await tracker.drain(0.01) == 0

    with capture_logs() as logs:
        asyncio.run(drive())
    assert [(e["event"], e["log_level"], e["error"]) for e in logs] == [
        (_OWNED_LATE_EVENT, "error", "OSError")
    ]
    assert lost == ["owned"]


@pytest.mark.parametrize("ended", ["landed", "cancelled"])
def test_a_write_that_landed_or_was_cancelled_before_its_handover_reports_nothing(
    ended: str,
) -> None:
    from structlog.testing import capture_logs

    lost: list[str] = []

    async def drive() -> None:
        async def lands() -> None:
            return None

        async def hangs() -> None:
            await asyncio.Event().wait()

        tracker = RefusalAuditTracker()
        task = tracker.track(
            lands() if ended == "landed" else hangs(), on_lost=lambda: lost.append("owned")
        )
        if ended == "cancelled":
            await asyncio.sleep(0)  # started
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        tracker.mark_timed_out(task)  # nothing to report, and nothing raised for a cancelled task
        assert await tracker.drain(0.01) == 0

    with capture_logs() as logs:
        asyncio.run(drive())
    assert logs == [] and lost == []


def test_a_write_the_drain_gave_up_on_is_not_reported_again_by_a_late_handover() -> None:
    """The drain has already told the owner that the write may be lost; its caller, cancelled
    after that, hands over a write that has failed meanwhile: not a second report."""
    from structlog.testing import capture_logs

    lost: list[str] = []

    async def drive() -> int:
        fail = asyncio.Event()

        async def fails_on_signal() -> None:
            await fail.wait()
            raise OSError("EIO")

        tracker = RefusalAuditTracker()
        task = tracker.track(fails_on_signal(), on_lost=lambda: lost.append("owned"))
        left = await tracker.drain(0.01)
        fail.set()
        await asyncio.sleep(0)  # the write has failed; its done-callback is still queued
        assert task.done()
        tracker.mark_timed_out(task)
        await asyncio.gather(task, return_exceptions=True)
        return left

    with capture_logs() as logs:
        assert asyncio.run(drive()) == 1
    assert lost == ["owned"] and logs == []


def test_the_tracker_keeps_no_strong_reference_to_a_write_that_has_ended() -> None:
    """#3054 review: `_done` drops no owner for a write nobody handed over, so the owner map has to
    be weak. Refusals are triggered from outside: a plain dict would keep one finished task per
    audited refusal for as long as the tracker lives."""

    async def land_one(tracker: RefusalAuditTracker) -> weakref.ref[asyncio.Task[None]]:
        async def lands() -> None:
            return None

        task = tracker.track(lands())
        await asyncio.wait({task})  # ended and settled, never handed over
        return weakref.ref(task)  # the task stays in this frame, which is gone once it returns

    async def drive() -> tuple[bool, int]:
        tracker = RefusalAuditTracker()
        written = await land_one(tracker)
        await asyncio.sleep(0)  # the loop's queued callbacks for the ended write have run
        gc.collect()
        return written() is None, len(tracker)

    assert asyncio.run(drive()) == (True, 0)


class _BrokenErrorLog:
    """What `csrf._log()` returns while the log pipeline is down for an error line."""

    def error(self, event: str, **kw: Any) -> None:
        raise RuntimeError("log pipeline down")


@pytest.mark.parametrize(
    ("breaks", "lines_logged"), [("owner_on_lost", 1), ("late_failure_log", 0)]
)
def test_a_report_that_raises_goes_to_the_loop_and_never_to_the_caller_handing_it_over(
    breaks: str, lines_logged: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#3054 review: a caller hands a write over from its `except asyncio.CancelledError:` block,
    where a raise would replace the cancellation. The report is two steps (the late-failure line,
    the owner's `on_lost`): one that raises is handed to the loop's exception handler and the other
    still runs, once. Only the report's own error goes there: the write's task would carry its
    failure text (`repr`), which the late-failure line deliberately leaves out."""
    from structlog.testing import capture_logs

    told: list[str] = []
    unhandled: list[dict[str, Any]] = []

    def on_lost() -> None:
        told.append("owner")
        if breaks == "owner_on_lost":
            raise RuntimeError("counter backend down")

    if breaks == "late_failure_log":
        monkeypatch.setattr("candleviewer.api.csrf._log", _BrokenErrorLog)

    async def drive() -> None:
        asyncio.get_running_loop().set_exception_handler(lambda _loop, ctx: unhandled.append(ctx))

        async def fails() -> None:
            raise OSError("EIO")

        tracker = RefusalAuditTracker()
        task = tracker.track(fails(), on_lost=on_lost)
        await asyncio.gather(task, return_exceptions=True)  # ended, settled, never marked
        tracker.mark_timed_out(task)  # returns: the caller's cancel goes on
        tracker.mark_timed_out(task)  # and a second hand-over reports nothing more

    with capture_logs() as logs:
        asyncio.run(drive())
    assert told == ["owner"] and len(logs) == lines_logged
    assert [(type(c["exception"]), set(c)) for c in unhandled] == [
        (RuntimeError, {"message", "exception"})
    ]
    assert "EIO" not in repr(unhandled)


# -- audit bookkeeping through the middleware (#2264) ---------------------------------------------


class _FailsWhenSignalled:
    """An audit sink that blocks until `fail` is set and then raises: a disk that errors late."""

    def __init__(self) -> None:
        self.started, self.fail = asyncio.Event(), asyncio.Event()

    async def emit(self, action: str, **kw: Any) -> None:
        self.started.set()
        await self.fail.wait()
        raise OSError("EIO")


def _middleware(
    audit: Any, *, timeout_s: float = 0.05, cap: int = 64, anon_max: int = 1000
) -> CsrfMiddleware:
    async def inner(scope: Any, receive: Any, send: Any) -> None:
        raise AssertionError("refused requests never reach the app")

    return CsrfMiddleware(
        inner,
        codec=_CODEC,
        sessions=lambda: None,
        audit=audit,
        allowed_origins=frozenset(),
        anon_throttle=PerIpLoginThrottle(max_attempts=anon_max, window_s=60.0, clock=lambda: 0.0),
        audit_timeout_s=timeout_s,
        clock=lambda: _NOW,
        tracker=RefusalAuditTracker(cap=cap),
    )


async def _refused_request(mw: CsrfMiddleware) -> dict[str, Any]:
    """One unauthenticated POST (always refused, `missing`); returns the response start."""
    sent: list[Any] = []

    async def recv() -> Any:
        return {"type": "http.request", "body": b""}

    async def send(msg: Any) -> None:
        sent.append(msg)

    scope = {"type": "http", "method": "POST", "path": "/w/x", "headers": []}
    await mw(scope, recv, send)
    start: dict[str, Any] = sent[0]
    return start


def _refuse_once(sink: Any) -> tuple[int, dict[str, float]]:
    """One refused request through a fresh middleware: (status, bookkeeping that moved)."""

    async def drive() -> tuple[int, dict[str, float]]:
        before = _snapshot()
        start = await _refused_request(_middleware(sink))
        return start["status"], _delta(before)

    return asyncio.run(drive())


def test_audit_failing_after_the_wait_counts_slow_at_the_wait_then_unavailable_once() -> None:
    """#2264 (1): a write that outlasts the wait and then fails is lost, not merely slow.
    Only its error type is logged, never its message."""
    from structlog.testing import capture_logs

    async def drive() -> tuple[int, dict[str, float], dict[str, float]]:
        sink, before = _FailsWhenSignalled(), _snapshot()
        mw = _middleware(sink)
        start = await _refused_request(mw)
        at_the_wait = _delta(before)
        sink.fail.set()
        assert await mw.tracker.drain(5) == 0
        return start["status"], at_the_wait, _delta(before)

    with capture_logs() as logs:
        status, at_the_wait, at_the_end = asyncio.run(drive())
    assert status == 403 and at_the_wait == {"audit_slow": 1}
    assert at_the_end == {"audit_slow": 1, "audit_unavailable": 1}
    late = [e for e in logs if e["event"] == "auth.csrf_refused.audit_failed_late"]
    assert [e["error"] for e in late] == ["OSError"]


def test_a_cancelled_request_still_accounts_for_its_audit_failing_later() -> None:
    """#2264 (1): with its request cancelled nobody awaits the write any more, so its later
    failure has to be counted by the tracker (the shield would swallow it)."""

    async def drive() -> dict[str, float]:
        sink, before = _FailsWhenSignalled(), _snapshot()
        mw = _middleware(sink, timeout_s=30)
        request = asyncio.ensure_future(_refused_request(mw))
        await sink.started.wait()  # the request is parked on its audit wait
        request.cancel()
        await asyncio.gather(request, return_exceptions=True)
        sink.fail.set()
        assert await mw.tracker.drain(5) == 0
        return _delta(before)

    assert asyncio.run(drive()) == {"audit_unavailable": 1}


class _FailsThenCancelsItsRequest(_FailsWhenSignalled):
    """Also cancels `request` from a done-callback of the write task, registered after the tracker's
    and the shield's own: the cancel then lands once both ran, ahead of the request's wake-up."""

    def __init__(self) -> None:
        super().__init__()
        self.request: asyncio.Future[Any] | None = None

    async def emit(self, action: str, **kw: Any) -> None:
        write = asyncio.current_task()
        assert write is not None
        write.add_done_callback(lambda _done: self.request and self.request.cancel())
        await super().emit(action, **kw)


async def _cancel_a_request_as_its_audit_fails(
    window: str,
) -> tuple[asyncio.Future[Any], dict[str, float]]:
    """One refused request whose audit write fails while the request is cancelled, in the window
    `window` names: in the very loop iteration of the cancel (the tracker's done-callback still
    queued), or after that callback ran (the write's last done-callback cancels). The tracker is
    drained before it returns; the result is the request and the series that moved."""
    sink, before = _FailsThenCancelsItsRequest(), _snapshot()
    mw = _middleware(sink, timeout_s=30)
    request = asyncio.ensure_future(_refused_request(mw))
    await sink.started.wait()  # the request is parked on its audit wait
    if window == "done_callback_ran":
        sink.request = request  # cancelled by the write's last done-callback
        sink.fail.set()
    else:
        sink.fail.set()  # the write fails in the next loop iteration ...
        request.cancel()  # ... and the request is cancelled in that same one
    await asyncio.gather(request, return_exceptions=True)
    assert await mw.tracker.drain(5) == 0
    return request, _delta(before)


@pytest.mark.parametrize("window", ["done_callback_queued", "done_callback_ran"])
def test_a_request_cancelled_as_its_audit_fails_still_counts_the_write_unavailable(
    window: str,
) -> None:
    """#3054 (2): the guard hands the write over from its cancel handler, and the shared tracker
    reports a write that has failed by then: in the loop iteration of the cancel (its own
    done-callback still queued), or after that callback ran without the write being marked."""
    from structlog.testing import capture_logs

    async def drive() -> dict[str, float]:
        request, moved = await _cancel_a_request_as_its_audit_fails(window)
        assert request.cancelled()
        return moved

    with capture_logs() as logs:
        assert asyncio.run(drive()) == {"audit_unavailable": 1}
    late = [e for e in logs if e["event"] == "auth.csrf_refused.audit_failed_late"]
    assert [(e["log_level"], e["error"]) for e in late] == [("error", "OSError")]


@pytest.mark.parametrize("window", ["done_callback_queued", "done_callback_ran"])
def test_a_request_cancelled_as_its_audit_fails_stays_cancelled_when_the_report_raises(
    window: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#3054 review: the guard hands the failed write over from its `except asyncio.CancelledError:`
    block, and the report (the counter, the log line) runs there. A raise would replace the
    cancellation with its own error: the server would see a failed request where it cancelled one.
    The request ends cancelled, and the report's error goes to the loop's exception handler."""
    unhandled: list[dict[str, Any]] = []

    def counter_down() -> None:
        raise RuntimeError("counter backend down")

    monkeypatch.setattr("candleviewer.api.csrf._count_audit_unavailable", counter_down)

    async def drive() -> tuple[asyncio.Future[Any], dict[str, float]]:
        asyncio.get_running_loop().set_exception_handler(lambda _loop, ctx: unhandled.append(ctx))
        return await _cancel_a_request_as_its_audit_fails(window)

    request, moved = asyncio.run(drive())
    assert request.cancelled()
    assert moved == {}  # the counter that raised did not move
    assert [type(c["exception"]) for c in unhandled] == [RuntimeError]


def test_a_writer_raising_timeout_itself_is_a_failure_not_slowness() -> None:
    """The same branch as `wait_for` reporting its timeout after the write has failed."""

    class _TimesOut:
        async def emit(self, action: str, **kw: Any) -> None:
            raise TimeoutError("fsync timed out")

    assert _refuse_once(_TimesOut()) == (403, {"audit_unavailable": 1})


def test_a_write_landing_in_the_turn_the_wait_ends_counts_slow_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The boundary: `wait_for` reports its timeout after the shielded write has finished."""

    class _Lands:
        async def emit(self, action: str, **kw: Any) -> None:
            await asyncio.sleep(0)

    async def lost_race(awaitable: Any, _wait: float | None) -> None:
        await awaitable
        raise TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", lost_race)
    assert _refuse_once(_Lands()) == (403, {"audit_slow": 1})


def test_a_full_tracker_skips_the_audit_as_saturated_and_spends_no_budget() -> None:
    """#2264 (1): with the in-flight cap full of stuck writes the audit is skipped on purpose,
    under a reason of its own (not the per-IP budget's) and without spending that budget:
    once the writes clear, the same client is audited again, in full."""

    async def drive() -> tuple[list[dict[str, Any]], list[str], dict[str, float]]:
        release, written = asyncio.Event(), []

        class _StuckUntilReleased:
            async def emit(self, action: str, **kw: Any) -> None:
                written.append(action)
                await release.wait()

        before = _snapshot()
        mw = _middleware(_StuckUntilReleased(), timeout_s=0.01, cap=1, anon_max=2)
        starts = [await _refused_request(mw)]  # audited (1 of 2), then stuck: the cap is full
        starts.append(await _refused_request(mw))  # saturated: skipped, spends nothing
        release.set()
        assert await mw.tracker.drain(5) == 0
        starts.append(await _refused_request(mw))  # audited again (2 of 2)
        starts.append(await _refused_request(mw))  # over the budget: throttled
        return starts, written, _delta(before)

    starts, written, moved = asyncio.run(drive())
    assert [s["status"] for s in starts] == [403] * 4
    assert [b"retry-after" in dict(s["headers"]) for s in starts] == [False, True, False, True]
    assert written == ["auth.csrf_refused"] * 2
    assert moved == {"audit_slow": 1, "audit_saturated": 1, "audit_throttled": 1}
