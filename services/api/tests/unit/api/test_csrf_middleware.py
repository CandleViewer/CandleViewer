"""`CsrfMiddleware` edges not reachable through the auth routers (#2090). No I/O."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.api.csrf import (
    CsrfMiddleware,
    CsrfRefusal,
    is_exempt,
    is_unsafe,
    route_path,
    verify_refresh_csrf,
)
from candleviewer.auth.csrf import CSRF_COOKIE, CSRF_HEADER, CsrfCodec
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.throttle import PerIpLoginThrottle

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


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example"},
        {"Sec-Fetch-Site": "cross-site"},
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


def test_allowed_origin_and_same_site_pass() -> None:
    client, _ = _app(_Sessions())
    h = {**_pair(), "Authorization": "Bearer good"}
    assert client.post("/w/x", headers={**h, "Origin": _ORIGIN + "/"}).status_code == 200
    assert client.post("/w/x", headers={**h, "Sec-Fetch-Site": "same-origin"}).status_code == 200
    assert client.post("/w/x", headers={**h, "Sec-Fetch-Site": "none"}).status_code == 200
    assert client.post("/auth/login", headers={"Origin": _ORIGIN}).status_code == 200


# -- audit flood / failure -------------------------------------------------------------------


def test_over_budget_refusals_stay_403_without_audit_but_counted() -> None:
    """Over the per-IP budget only the audit write is skipped: the reply stays the same
    403 csrf_token_invalid (+Retry-After) so client recovery keeps working."""
    from candleviewer.auth.metrics import auth_csrf_refused_total

    client, audit = _app(_Sessions(), anon_max=3)
    before = auth_csrf_refused_total.labels(reason="missing")._value.get()
    rs = [client.post("/w/x") for _ in range(6)]
    assert [r.status_code for r in rs] == [403] * 6
    assert all(_code(r) == "csrf_token_invalid" for r in rs)
    assert "retry-after" not in rs[2].headers and int(rs[3].headers["retry-after"]) >= 1
    assert len(audit.calls) == 3  # no audit write once over the per-IP budget
    assert auth_csrf_refused_total.labels(reason="missing")._value.get() == before + 6


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

    asyncio.run(drive())
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
    `audit_throttled` and still get the same 403."""
    import threading

    from candleviewer.api.csrf import RefusalAuditTracker
    from candleviewer.auth.metrics import auth_csrf_refused_total

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
        before = auth_csrf_refused_total.labels(reason="audit_throttled")._value.get()
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
        throttled = auth_csrf_refused_total.labels(reason="audit_throttled")._value.get()
        assert throttled - before == 60 - cap
        release.set()
        assert await mw.tracker.drain(5) == 0
        assert wal.records == cap

    asyncio.run(drive())
    assert set(statuses) == {403}


def test_tracker_drain_is_bounded_and_reports_leftovers() -> None:
    from candleviewer.api.csrf import RefusalAuditTracker

    async def never() -> None:
        await asyncio.Event().wait()

    async def drive() -> int:
        tracker = RefusalAuditTracker(cap=2)
        task = tracker.track(never())
        left = await tracker.drain(0.01)
        task.cancel()
        return left

    assert asyncio.run(drive()) == 1


def test_late_audit_failure_is_logged_with_its_type_only_after_timeout() -> None:
    from structlog.testing import capture_logs

    from candleviewer.api.csrf import RefusalAuditTracker

    async def boom() -> None:
        await asyncio.sleep(0)
        raise RuntimeError("disk gone")

    async def drive() -> None:
        tracker = RefusalAuditTracker()
        awaited = tracker.track(boom())  # its failure is handled by the awaiting caller
        late = tracker.track(boom())
        tracker.mark_timed_out(late)
        await asyncio.wait({awaited, late})
        for t in (awaited, late):
            t.exception()  # retrieved: no "never retrieved" noise

    with capture_logs() as logs:
        asyncio.run(drive())
    late_logs = [e for e in logs if e["event"] == "auth.csrf_refused.audit_failed_late"]
    assert len(late_logs) == 1 and late_logs[0]["error"] == "RuntimeError"
