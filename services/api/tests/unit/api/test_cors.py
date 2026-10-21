"""`cors_app`, its gate and the CSRF guard's refusals (ADR-0038 2b and 2c, #3519 S3a and S3b).

`cors_app` is driven through a bare ASGI app, so what is pinned is what it itself answers. The gate
and the guard run in small apps with the real `CsrfMiddleware` and a counting flag reader;
`create_app()` is checked for the mount and for what the real stack answers.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from starlette.responses import PlainTextResponse
from starlette.types import Receive, Scope, Send
from structlog.testing import capture_logs

from candleviewer.api.cors import (
    ALLOW_HEADERS,
    EXPOSE_HEADERS,
    FLAG_STATE_KEY,
    CorsGateMiddleware,
    CorsPolicy,
    cors_app,
    cors_on,
)
from candleviewer.api.csrf import CsrfMiddleware, RefusalAuditTracker
from candleviewer.api.idle_lock import IdleLockMiddleware
from candleviewer.app import create_app
from candleviewer.auth.csrf import CSRF_COOKIE, CSRF_HEADER, CsrfCodec
from tests.csrf_helpers import FakeBearerSessions, csrf_headers

_ORIGIN = "app://candleviewer"


async def _inner(scope: Scope, receive: Receive, send: Send) -> None:
    await PlainTextResponse("ok")(scope, receive, send)


def _client() -> TestClient:
    return TestClient(cors_app(CorsPolicy(frozenset({_ORIGIN})), _inner))


def _preflight(headers: dict[str, str]) -> Response:
    sent = {"Origin": _ORIGIN, "Access-Control-Request-Method": "POST", **headers}
    response: Response = _client().options("/", headers=sent)
    return response


def _cors(response: Response) -> dict[str, str]:
    """The `access-control-*` and `vary` headers of `response` (names are lower case)."""
    return {
        name: value
        for name, value in response.headers.items()
        if name.startswith("access-control-") or name == "vary"
    }


def test_cors_app_listed_origin_gets_exact_origin_credentials_exposed_headers_and_vary() -> None:
    response = _client().get("/", headers={"Origin": _ORIGIN})

    assert response.text == "ok"
    assert _cors(response) == {
        "access-control-allow-origin": _ORIGIN,
        "access-control-allow-credentials": "true",
        "access-control-expose-headers": ", ".join(EXPOSE_HEADERS),
        "vary": "Origin",
    }


def test_cors_app_preflight_allows_contract_methods_and_headers_for_600_s() -> None:
    response = _preflight({"Access-Control-Request-Headers": ", ".join(ALLOW_HEADERS)})

    cors = _cors(response)
    assert (response.status_code, response.text) == (200, "OK")
    assert cors["access-control-allow-origin"] == _ORIGIN
    assert cors["access-control-allow-credentials"] == "true"
    assert cors["access-control-allow-methods"] == "GET, HEAD, POST, PUT, PATCH, DELETE"
    assert set(ALLOW_HEADERS) <= set(cors["access-control-allow-headers"].split(", "))
    assert cors["access-control-max-age"] == "600"
    assert "Origin" in cors["vary"].split(", ")


def test_cors_app_takes_its_header_lists_from_the_policy_not_the_module() -> None:
    policy = CorsPolicy(
        frozenset({_ORIGIN}), allow_headers=("X-Only",), expose_headers=("X-Shown",)
    )
    client = TestClient(cors_app(policy, _inner))
    asked = {"Origin": _ORIGIN, "Access-Control-Request-Method": "POST"}

    simple = client.get("/", headers={"Origin": _ORIGIN})
    allowed = client.options("/", headers=asked | {"Access-Control-Request-Headers": "x-only"})
    module = client.options("/", headers=asked | {"Access-Control-Request-Headers": "x-csrf-token"})

    assert _cors(simple)["access-control-expose-headers"] == "X-Shown"
    assert "X-Only" in _cors(allowed)["access-control-allow-headers"].split(", ")
    assert (module.status_code, module.text) == (400, "Disallowed CORS headers")


@pytest.mark.parametrize(
    ("asked", "refusal"),
    [
        # `QUERY` is in Starlette's own `ALL_METHODS`: only the explicit method list refuses it.
        ({"Access-Control-Request-Method": "QUERY"}, "method"),
        ({"Access-Control-Request-Headers": "x-undeclared"}, "headers"),
        ({"Access-Control-Request-Private-Network": "true"}, "private-network"),
    ],
    ids=["method", "header", "private_network"],
)
def test_cors_app_preflight_undeclared_method_header_or_private_network_is_refused_400(
    asked: dict[str, str], refusal: str
) -> None:
    response = _preflight(asked)

    assert (response.status_code, response.text) == (400, f"Disallowed CORS {refusal}")
    assert "access-control-allow-private-network" not in response.headers


@pytest.mark.parametrize("origin", ["https://evil.example", "null", "app://other"])
def test_cors_app_never_allows_an_unlisted_origin_on_a_response_or_preflight(origin: str) -> None:
    # Starlette still adds credentials and the exposed headers to the response: what matters is that
    # `Access-Control-Allow-Origin` is never sent, so no `*`, regex or reflection is configured.
    response = _client().get("/", headers={"Origin": origin})
    preflight = _preflight({"Origin": origin})

    assert "access-control-allow-origin" not in response.headers
    assert (preflight.status_code, preflight.text) == (400, "Disallowed CORS origin")
    assert "access-control-allow-origin" not in preflight.headers


# -- the gate and the guard's refusals (ADR-0038 2c, #3519 S3b) -----------------------------------

_POLICY = CorsPolicy(frozenset({_ORIGIN}))
_CODEC = CsrfCodec(b"\x07" * 32)
#: Every way the `Origin` headers can fail the exact match: a stranger, a lookalike, a repeat.
_UNLISTED: dict[str, list[str]] = {
    "evil": ["https://evil.example"],
    "null": ["null"],
    "app_other": ["app://other"],
    "trailing_slash": [f"{_ORIGIN}/"],  # SR-042 trims it for its own check; the CORS match does not
    "uppercase": ["APP://candleviewer"],
    "absent": [],
    "repeated": [_ORIGIN, _ORIGIN],
}
_UNTOUCHED = {**_UNLISTED, "listed_flag_off": [_ORIGIN]}
#: Headers that make the guard refuse a `POST /w` from the listed origin, by the reason it audits.
_REFUSED: dict[str, dict[str, str]] = {
    "missing": {},
    "mismatch": {CSRF_HEADER: _CODEC.issue("a"), "Cookie": f"{CSRF_COOKIE}={_CODEC.issue('b')}"},
    "bad_mac": {CSRF_HEADER: "x", "Cookie": f"{CSRF_COOKIE}=x"},
    "wrong_session": csrf_headers(_CODEC, uuid.UUID(int=7)),  # well formed, bound to no session
}


class _Flag:
    """A flag reader double: answers `on` and counts its reads."""

    def __init__(self, on: bool) -> None:
        self.on = on
        self.reads = 0

    def __call__(self) -> bool:
        self.reads += 1
        return self.on


class _Audit:
    """An audit emitter double: keeps the `reason` of each record."""

    def __init__(self) -> None:
        self.reasons: list[str] = []

    async def emit(self, action: str, **fields: Any) -> None:
        self.reasons.append(fields["reason"])


async def _noop(*_args: Any) -> Any:
    return {}


def _stack(
    flag: _Flag | None = None,
    audit: _Audit | None = None,
    cap: int = 64,
    listed: frozenset[str] = _POLICY.origins,
) -> TestClient:
    """`GET /r` and `POST /w` behind the real CSRF guard, which admits the `listed` origins. With a
    `flag`, the stack S3b mounts: the gate inside the guard, both from one policy and one reader.
    Without, today's stack."""
    app = FastAPI()

    @app.get("/r")
    async def read() -> dict[str, str]:
        return {"ok": "r"}

    @app.post("/w")
    async def write() -> dict[str, str]:
        return {"ok": "w"}

    sessions = FakeBearerSessions("good")
    if flag is not None:
        app.add_middleware(CorsGateMiddleware, policy=_POLICY, enabled=flag)
    app.add_middleware(
        CsrfMiddleware,
        codec=_CODEC,
        sessions=lambda: sessions,
        audit=audit or _Audit(),
        allowed_origins=listed,
        tracker=RefusalAuditTracker(cap),
        cors=None if flag is None else _POLICY,
        cors_enabled=flag,
    )
    return TestClient(app)


def _asked(client: TestClient, origins: list[str]) -> list[Response]:
    """A GET, a POST and a preflight, each sent with `origins` as its `Origin`. The guard passes
    the POST for a listed origin and refuses it as `cross_origin` for a stranger: either way the
    layer must leave the answer alone."""
    sent = [("Origin", origin) for origin in origins]
    write = [*sent, ("Authorization", "Bearer good"), *csrf_headers(_CODEC).items()]
    return [
        client.get("/r", headers=sent),
        client.post("/w", headers=write),
        client.options("/r", headers=[*sent, ("Access-Control-Request-Method", "POST")]),
    ]


def _plain(response: Response) -> tuple[int, bytes, list[tuple[str, str]]]:
    """Status, body and the headers that are not CORS ones: what the layer must leave alone."""
    cors = _cors(response)
    kept = [(name, value) for name, value in response.headers.multi_items() if name not in cors]
    return response.status_code, response.content, kept


@pytest.mark.parametrize("origins", _UNTOUCHED.values(), ids=list(_UNTOUCHED))
def test_cors_gate_unlisted_absent_repeated_origin_or_flag_off_answers_as_without_it(
    origins: list[str],
) -> None:
    listed = origins == [_ORIGIN]
    flag = _Flag(not listed)  # the flag is on for every origin that must not match

    gated, today = _asked(_stack(flag), origins), _asked(_stack(), origins)

    assert [_plain(r) for r in gated] == [_plain(r) for r in today]
    assert [_cors(r) for r in gated] == [{}, {}, {}]  # no access-control-* and no Vary
    assert flag.reads == (3 if listed else 0)  # one read per request, and only after a match


def test_cors_gate_listed_origin_with_the_flag_on_is_answered_as_cors_app_answers() -> None:
    flag = _Flag(True)
    client = _stack(flag)

    simple = client.get("/r", headers={"Origin": _ORIGIN})
    preflight = client.options(
        "/r", headers={"Origin": _ORIGIN, "Access-Control-Request-Method": "POST"}
    )

    assert simple.json() == {"ok": "r"}
    assert _cors(simple) == _cors(_client().get("/", headers={"Origin": _ORIGIN}))
    assert (preflight.status_code, preflight.text) == (200, "OK")  # answered, never reaches the app
    assert _cors(preflight) == _cors(_preflight({}))
    assert _cors(simple)["access-control-allow-origin"] == _ORIGIN
    assert flag.reads == 2


@pytest.mark.parametrize("on", [True, False])
def test_cors_gate_keeps_the_flag_in_the_scope_and_a_later_cors_on_reads_it_no_more(
    on: bool,
) -> None:
    seen: list[tuple[object, bool]] = []

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append((scope["state"].get(FLAG_STATE_KEY, "absent"), cors_on(scope, _POLICY, flag)))
        await PlainTextResponse("ok")(scope, receive, send)

    flag = _Flag(on)
    client = TestClient(CorsGateMiddleware(inner, policy=_POLICY, enabled=flag))

    client.get("/", headers={"Origin": _ORIGIN})
    client.get("/", headers={"Origin": "https://evil.example"})

    # What ADR-0038 S4 finds: the value, from the gate's one read; nothing for a stranger.
    assert seen == [(on, on), ("absent", False)]
    assert flag.reads == 1


def test_cors_on_bare_scope_reads_once_and_a_stored_flag_never_admits_a_stranger() -> None:
    flag = _Flag(True)
    bare: Scope = {"type": "http", "headers": [(b"origin", _ORIGIN.encode())]}
    stranger: Scope = {
        "type": "http",
        "headers": [(b"origin", b"https://evil.example")],
        "state": {FLAG_STATE_KEY: True},  # a stored "on" from elsewhere: the match still decides
    }

    assert (cors_on(bare, _POLICY, flag), cors_on(bare, _POLICY, flag)) == (True, True)
    assert (bare["state"], flag.reads) == ({FLAG_STATE_KEY: True}, 1)
    assert (cors_on(stranger, _POLICY, flag), flag.reads) == (False, 1)


async def test_cors_gate_websocket_and_lifespan_scopes_pass_through_without_a_flag_read() -> None:
    seen: list[Scope] = []

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(scope)

    flag = _Flag(True)
    gate = CorsGateMiddleware(inner, policy=_POLICY, enabled=flag)
    upgrade: Scope = {"type": "websocket", "headers": [(b"origin", _ORIGIN.encode())]}
    lifespan: Scope = {"type": "lifespan"}

    for scope in (upgrade, lifespan):
        await gate(scope, _noop, _noop)

    assert seen == [upgrade, lifespan]
    assert flag.reads == 0 and "state" not in upgrade


def test_cors_gate_with_an_empty_allow_list_is_inert() -> None:
    flag = _Flag(True)  # the production default: nothing listed, so no origin ever matches
    client = TestClient(CorsGateMiddleware(_inner, policy=CorsPolicy(frozenset()), enabled=flag))

    response = client.get("/", headers={"Origin": _ORIGIN})

    assert (response.text, _cors(response), flag.reads) == ("ok", {}, 0)


@pytest.mark.parametrize("on", [True, False], ids=["flag_on", "flag_off"])
@pytest.mark.parametrize(
    ("refusal", "cap"),
    [("missing", 64), ("mismatch", 64), ("bad_mac", 64), ("wrong_session", 64), ("missing", 0)],
    ids=["missing", "mismatch", "bad_mac", "wrong_session", "unaudited"],
)
def test_csrf_token_refusal_listed_origin_carries_a_simple_responses_cors_headers_iff_flag_on(
    refusal: str, cap: int, on: bool
) -> None:
    flag, audit = _Flag(on), _Audit()
    client = _stack(flag, audit, cap)
    sent = {"Origin": _ORIGIN, **_REFUSED[refusal]}
    passed = {"Origin": _ORIGIN, "Authorization": "Bearer good", **csrf_headers(_CODEC)}

    passing = client.post("/w", headers=passed)
    refused = client.post("/w", headers=sent)
    today = _stack(cap=cap).post("/w", headers=sent)

    assert (refused.status_code, refused.json()["code"]) == (403, "csrf_token_invalid")
    assert bool(_cors(passing)) == on  # what a simple response through the layer carries
    assert _cors(refused) == _cors(passing)
    assert _plain(refused) == _plain(today)  # headers only: status, body and Retry-After as today
    assert audit.reasons == ([] if cap == 0 else [refusal])
    assert ("retry-after" in refused.headers) == (cap == 0)  # the unaudited variant keeps it
    assert flag.reads == 2


@pytest.mark.parametrize("origins", _UNLISTED.values(), ids=list(_UNLISTED))
def test_csrf_refusal_unlisted_origin_carries_no_cors_header_and_reads_no_flag(
    origins: list[str],
) -> None:
    flag = _Flag(True)

    refused = _stack(flag).post("/w", headers=[("Origin", origin) for origin in origins])

    assert (refused.status_code, refused.json()["code"]) == (403, "csrf_token_invalid")
    assert _cors(refused) == {}
    assert flag.reads == 0


def test_csrf_cross_origin_refusal_never_carries_cors_headers_whatever_the_policy_lists() -> None:
    flag, audit = _Flag(True), _Audit()

    refused = _stack(flag, audit, listed=frozenset()).post("/w", headers={"Origin": _ORIGIN})

    assert (refused.status_code, audit.reasons) == (403, ["cross_origin"])
    assert (_cors(refused), flag.reads) == ({}, 0)  # the policy lists it and the flag is on


@pytest.mark.parametrize("entry", ["*", "null", "app://candleviewer/", "https://a.example/x"])
def test_cors_policy_refuses_an_entry_that_is_not_a_serialised_origin(entry: str) -> None:
    with pytest.raises(ValueError, match="not a serialised origin"):
        CorsPolicy(frozenset({_ORIGIN, entry}))


# -- the real stack: `create_app()` mounts the gate and gives the guard its policy and reader ------


def _app(monkeypatch: pytest.MonkeyPatch, on: bool) -> FastAPI:
    """`create_app()` listing the shell's origin; its flag reader, never started, answers `on`."""
    monkeypatch.setenv("CV_ALLOWED_ORIGINS", _ORIGIN)
    app = create_app()
    app.state.feature_flags.backend_connection.value = on
    return app


def test_create_app_stacks_cors_inside_csrf_outside_idle_lock_with_one_policy_and_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app(monkeypatch, True)
    order: list[object] = [m.cls for m in app.user_middleware]  # outermost first
    at = order.index(CsrfMiddleware)
    csrf: dict[str, Any] = app.user_middleware[at].kwargs
    gate: dict[str, Any] = app.user_middleware[at + 1].kwargs

    assert order[at : at + 3] == [CsrfMiddleware, CorsGateMiddleware, IdleLockMiddleware]
    assert csrf["cors"] is gate["policy"]
    assert csrf["allowed_origins"] == gate["policy"].origins == frozenset({_ORIGIN})
    assert csrf["cors_enabled"] is gate["enabled"] is app.state.feature_flags.backend_connection


@pytest.mark.parametrize("on", [True, False], ids=["flag_on", "flag_off"])
def test_create_app_guard_refusal_carries_a_simple_responses_cors_headers_iff_flag_on(
    monkeypatch: pytest.MonkeyPatch, on: bool
) -> None:
    client = TestClient(_app(monkeypatch, on), client=("127.0.0.1", 50000))
    asked = {"Origin": _ORIGIN}

    refused = client.post("/auth/logout", headers=asked)  # no token: the guard answers it
    simple = client.get("/healthz", headers=asked)

    assert (refused.status_code, refused.json()["code"]) == (403, "csrf_token_invalid")
    assert bool(_cors(simple)) == on
    assert _cors(refused) == _cors(simple)


def test_create_app_unhandled_error_500_is_redacted_without_cors_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(_settings: object) -> dict[str, str]:
        raise RuntimeError("canary-detail")

    monkeypatch.setattr("candleviewer.api.health._build_info", fail)
    client = TestClient(
        _app(monkeypatch, True), client=("127.0.0.1", 50000), raise_server_exceptions=False
    )

    with capture_logs():  # the handler logs the traceback; the default console renderer is slow
        response = client.get("/healthz", headers={"Origin": _ORIGIN})

    assert (response.status_code, response.json()["code"]) == (500, "internal_error")
    assert "canary-detail" not in response.text
    assert _cors(response) == {}  # ServerErrorMiddleware answers outside every layer (ADR 2c)
