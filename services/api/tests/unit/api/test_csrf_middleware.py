"""`CsrfMiddleware` edges not reachable through the auth routers (#2090). No I/O."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
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
from candleviewer.auth.throttle import PerIpLoginThrottle

_CODEC = CsrfCodec(b"\x07" * 32)
_SID = uuid.uuid4()
_ORIGIN = "https://app.example"


class _Sessions:
    async def peek_access_token(self, token: str) -> Any:
        return SimpleNamespace(id=_SID, user_id=_SID) if token == "good" else None  # noqa: S105


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
    sessions: Any = None, audit: Any = None, anon_max: int = 1000, timeout_s: float = 2.0
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
        anon_throttle=PerIpLoginThrottle(max_attempts=anon_max, window_s=60.0, clock=lambda: 0.0),
        audit_timeout_s=timeout_s,
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
    assert not is_unsafe("GET") and not is_unsafe("trace") and not is_unsafe("OPTIONS")
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


# -- refresh: the route owns the binding check ------------------------------------------


def test_refresh_gets_presence_equality_and_shape_checks_then_the_route() -> None:
    client, _ = _app(_Sessions())
    assert _code(client.post("/auth/refresh")) == "csrf_token_invalid"  # missing
    t = _CODEC.issue("whatever")
    r = client.post("/auth/refresh", headers={CSRF_HEADER: t, "Cookie": f"{CSRF_COOKIE}={t}"})
    assert r.json() == {"route": "refresh"}  # route verifies against presented_record.id


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
    [{"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}, {"Origin": "null"}],
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
    assert client.post("/auth/login", headers={"Origin": _ORIGIN}).status_code == 200


# -- audit flood / failure -------------------------------------------------------------------


def test_unauthenticated_refusals_are_throttled_without_audit_but_counted() -> None:
    from candleviewer.auth.metrics import auth_csrf_refused_total

    client, audit = _app(_Sessions(), anon_max=3)
    before = auth_csrf_refused_total.labels(reason="missing")._value.get()
    codes = [client.post("/w/x").status_code for _ in range(6)]
    assert codes == [403, 403, 403, 429, 429, 429]
    assert len(audit.calls) == 3  # no audit write once over the per-IP budget
    assert auth_csrf_refused_total.labels(reason="missing")._value.get() == before + 6


def test_session_bound_refusals_are_audited_one_for_one() -> None:
    client, audit = _app(_Sessions(), anon_max=1)
    h = {**_pair(uuid.uuid4()), "Authorization": "Bearer good"}
    codes = [client.post("/w/x", headers=h).status_code for _ in range(4)]
    assert codes == [403] * 4 and len(audit.calls) == 4


@pytest.mark.parametrize("sink", [_Hangs(), _Raises()])
def test_audit_hang_or_failure_still_refuses_promptly(sink: Any) -> None:
    client, _ = _app(_Sessions(), audit=sink, timeout_s=0.05)
    r = client.post("/w/x")
    assert r.status_code == 403 and _code(r) == "csrf_token_invalid"


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
        await mw({"type": "http", "method": "GET", "path": "/x", "headers": []}, noop, noop)

    asyncio.run(drive())
    assert seen == ["websocket:", "lifespan:", "http:GET"]


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
