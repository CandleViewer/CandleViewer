"""SR-042 / SR-183: the `Origin` check on the WS upgrade (#2239).

`23-ws-protocol.md` §2.5: the check runs before negotiation, `accept`, any frame, auth or
store access, and the allow-list decides (`Sec-Fetch-Site` only labels the refusal of an
unlisted origin). A refusal is a close `4403` before `accept` (HTTP 403 on the wire, no
`bye`), counted, and logged with a cap. No network, no sleeps: TestClient sessions, direct
ASGI drives and an injected clock.
"""

from __future__ import annotations

import inspect
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import strategies as st
from starlette.types import Message, Scope
from starlette.websockets import WebSocketDisconnect
from structlog.testing import capture_logs

from candleviewer.app import create_app
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.settings import Settings
from candleviewer.ws.gateway import GatewayHub, make_ws_router
from candleviewer.ws.lifecycle import (
    ORIGIN_FORBIDDEN,
    REFUSAL_LOG_LIMIT,
    REFUSAL_LOG_WINDOW_S,
    OriginRefusal,
    RefusalLog,
    RefusalLogLimiter,
    header_values,
    origin_refusal,
)
from candleviewer.ws.metrics import cv_ws_closes_total, cv_ws_connections_in_use
from candleviewer.ws.permissions import ConnectionRegistry
from candleviewer.ws.revocation import RevocationHub

ORIGIN = "http://testserver"  # the TestClient's own origin
EVIL = "https://evil.example"
ALLOWED = frozenset({ORIGIN})
JSON = ["cv.v1.json"]
USER = uuid.uuid4()
REFUSED_LINE = "ws upgrade refused"
SUMMARY_LINE = "ws upgrade refusals suppressed"


def _sample(metric: Any, name: str, **labels: str) -> float:
    for family in metric.collect():
        for s in family.samples:
            if s.name == name and all(s.labels.get(k) == v for k, v in labels.items()):
                return float(s.value)
    return 0.0


def _refusals() -> float:
    return _sample(cv_ws_closes_total, "cv_ws_closes_total", reason=ORIGIN_FORBIDDEN)


def _open_sockets() -> float:
    return _sample(cv_ws_connections_in_use, "cv_ws_connections_in_use")


class _Clock:
    """Monotonic seconds, advanced only by the test."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class _Spy:
    """Stand-ins for the session store (`authenticate`) and the principal store (`resolve`)."""

    def __init__(self) -> None:
        self.tokens: list[str] = []
        self.resolved: list[uuid.UUID] = []

    async def authenticate(self, token: str) -> tuple[str, uuid.UUID, datetime]:
        self.tokens.append(token)
        return "sess-1", USER, datetime(2100, 1, 1, tzinfo=UTC)

    async def resolve(self, uid: uuid.UUID) -> PrincipalSnapshot:
        self.resolved.append(uid)
        perms = frozenset({Permission.MARKETDATA_READ})
        return PrincipalSnapshot(uid, frozenset({"viewer"}), perms)


def _app(spy: _Spy, hub: GatewayHub, *, clock: Callable[[], float] = time.monotonic) -> FastAPI:
    app = FastAPI()
    app.include_router(
        make_ws_router(
            authenticate=spy.authenticate,
            registry=ConnectionRegistry(spy.resolve, lambda: 1),
            revocation_hub=RevocationHub(),
            allowed_origins=ALLOWED,
            hub=hub,
            clock=clock,
            tick_s=0.005,
        )
    )
    return app


def _refuse(client: TestClient, headers: dict[str, str]) -> int:
    """Open `/ws` with `headers`; the close code of the refused upgrade."""
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws", subprotocols=JSON, headers=dict(headers)) as ws:
            ws.send_json({"t": "auth", "id": "a", "p": {"access_token": "t"}})
    return int(exc.value.code)


def _lines(logs: Sequence[Mapping[str, Any]], event: str) -> list[Mapping[str, Any]]:
    return [e for e in logs if e.get("event") == event]


# -- the pure §2.5 decision: the allow-list decides ---------------------------------------------


@pytest.mark.parametrize(
    ("origins", "sites", "expected"),
    [
        ([], [], OriginRefusal.ORIGIN_MISSING),
        ([], ["same-origin"], OriginRefusal.ORIGIN_MISSING),
        (["null"], [], OriginRefusal.ORIGIN_NULL),
        (["NULL"], [], OriginRefusal.ORIGIN_NULL),
        (["null/"], ["same-origin"], OriginRefusal.ORIGIN_NULL),
        ([EVIL], ["cross-site"], OriginRefusal.CROSS_SITE),
        ([EVIL], ["same-site"], OriginRefusal.CROSS_SITE),
        ([EVIL], ["Cross-Site "], OriginRefusal.CROSS_SITE),
        ([EVIL], ["same-origin", "cross-site"], OriginRefusal.CROSS_SITE),
        ([EVIL], [], OriginRefusal.ORIGIN_NOT_ALLOWED),
        ([EVIL], ["same-origin"], OriginRefusal.ORIGIN_NOT_ALLOWED),
        (["http://testserver.evil.example"], [], OriginRefusal.ORIGIN_NOT_ALLOWED),
        (["https://testserver"], [], OriginRefusal.ORIGIN_NOT_ALLOWED),
        (["http://testserver:8443"], [], OriginRefusal.ORIGIN_NOT_ALLOWED),
        ([""], [], OriginRefusal.ORIGIN_NOT_ALLOWED),
        ([ORIGIN, ORIGIN], [], OriginRefusal.ORIGIN_NOT_ALLOWED),
        ([ORIGIN, EVIL], ["same-origin"], OriginRefusal.ORIGIN_NOT_ALLOWED),
    ],
)
def test_origin_refusal_section_2_5_cases_are_refused(
    origins: list[str], sites: list[str], expected: OriginRefusal
) -> None:
    assert origin_refusal(origins, sites, ALLOWED) is expected


@pytest.mark.parametrize(
    ("origins", "sites"),
    [
        ([ORIGIN], []),
        ([ORIGIN], ["same-origin"]),
        ([ORIGIN], ["none"]),
        ([ORIGIN], ["cross-site"]),  # a listed app origin on another site (`app://` shell)
        ([ORIGIN], ["same-site"]),  # a listed dev page on another port
        ([f"{ORIGIN}/"], ["Cross-Site"]),
    ],
)
def test_origin_refusal_listed_origin_is_admitted_whatever_the_fetch_site(
    origins: list[str], sites: list[str]
) -> None:
    assert origin_refusal(origins, sites, ALLOWED) is None


def test_origin_refusal_null_is_refused_even_when_listed() -> None:
    listed = frozenset({"null", ORIGIN})
    assert origin_refusal(["null"], ["same-origin"], listed) is OriginRefusal.ORIGIN_NULL


def test_origin_refusal_empty_allow_list_refuses_everything() -> None:
    refused = origin_refusal([ORIGIN], ["same-origin"], frozenset())
    assert refused is OriginRefusal.ORIGIN_NOT_ALLOWED


_printable = st.text(st.characters(min_codepoint=0x20, max_codepoint=0x7E), max_size=40)
_SITES = ("cross-site", "same-site", "same-origin", "none")


@given(
    origins=st.lists(
        st.sampled_from([ORIGIN, f"{ORIGIN}/", "null", EVIL]) | _printable, max_size=3
    ),
    sites=st.lists(st.sampled_from(_SITES) | _printable, max_size=2),
)
def test_origin_refusal_admits_exactly_one_listed_non_null_origin_whatever_the_fetch_site(
    origins: list[str], sites: list[str]
) -> None:
    listed = ALLOWED | {"null"}  # a mis-configured `null` entry must still never admit
    refused = origin_refusal(origins, sites, listed)
    one = origins[0].strip().rstrip("/") if len(origins) == 1 else None
    assert (refused is None) is (one is not None and one in listed and one.lower() != "null")
    cross = any(s.strip().lower() in ("cross-site", "same-site") for s in sites)
    if refused is not None and one is not None and one.lower() != "null":
        assert (refused is OriginRefusal.CROSS_SITE) is cross  # the label, never the verdict


def test_header_values_match_names_case_insensitively() -> None:
    raw = [
        (b"Origin", b"http://a.example"),
        (b"sec-fetch-site", b"cross-site"),
        (b"ORIGIN", b"http://b.example"),
        (b"origin-agent-cluster", b"?1"),
    ]
    assert header_values(raw, b"origin") == ["http://a.example", "http://b.example"]
    assert header_values(raw, b"sec-fetch-site") == ["cross-site"]
    assert header_values([], b"origin") == []


def test_make_ws_router_has_no_default_allow_list() -> None:
    """No `None` / default path that could skip the check (C-4.14 intent)."""
    param = inspect.signature(make_ws_router).parameters["allowed_origins"]
    assert param.default is inspect.Parameter.empty


# -- the refusal log cap -------------------------------------------------------------------------


def test_refusal_log_limiter_logs_n_then_one_summary_then_nothing_until_the_window_ends() -> None:
    limiter = RefusalLogLimiter(limit=2, window_s=60.0)
    cause = OriginRefusal.CROSS_SITE
    got = [limiter.admit(cause, now=float(t)) for t in range(5)]
    assert got == [
        RefusalLog.LINE,
        RefusalLog.LINE,
        RefusalLog.SUMMARY,
        RefusalLog.NONE,
        RefusalLog.NONE,
    ]
    assert limiter.admit(cause, now=59.9) is RefusalLog.NONE
    assert limiter.admit(cause, now=60.0) is RefusalLog.LINE  # a new window starts


def test_refusal_log_limiter_counts_each_cause_separately() -> None:
    limiter = RefusalLogLimiter(limit=1, window_s=60.0)
    assert limiter.admit(OriginRefusal.CROSS_SITE, now=0.0) is RefusalLog.LINE
    assert limiter.admit(OriginRefusal.CROSS_SITE, now=1.0) is RefusalLog.SUMMARY
    assert limiter.admit(OriginRefusal.ORIGIN_MISSING, now=1.0) is RefusalLog.LINE


# -- socket level: refused before accept, auth and the stores ----------------------------------

_REFUSED = [
    pytest.param({"origin": EVIL, "sec-fetch-site": "cross-site"}, "cross_site", id="cross-site"),
    pytest.param({"origin": EVIL, "sec-fetch-site": "same-site"}, "cross_site", id="same-site"),
    pytest.param({"origin": EVIL}, "origin_not_allowed", id="bad-origin"),
    pytest.param({"origin": "null"}, "origin_null", id="null-origin"),
    pytest.param({}, "origin_missing", id="missing-origin"),
]


@pytest.mark.parametrize(("headers", "check"), _REFUSED)
def test_upgrade_refused_4403_before_accept_auth_and_store(
    headers: dict[str, str], check: str
) -> None:
    spy, hub = _Spy(), GatewayHub()
    refusals, sockets = _refusals(), _open_sockets()
    with TestClient(_app(spy, hub)) as client, capture_logs() as logs:
        assert _refuse(client, headers) == 4403
    assert spy.tokens == [] and spy.resolved == []  # no auth, no principal lookup
    assert len(hub) == 0 and _open_sockets() == sockets  # never accepted or registered
    assert _refusals() == refusals + 1
    entries = _lines(logs, REFUSED_LINE)
    assert [(e["reason"], e["check"], e["log_level"], e["source_ip"]) for e in entries] == [
        (ORIGIN_FORBIDDEN, check, "warning", "testclient")  # no MeshOnly here: the peer
    ]
    assert not any(v in str(entries) for v in (ORIGIN, EVIL, "cross-site", "same-site"))


@pytest.mark.parametrize("site", [None, "same-origin", "none", "cross-site", "same-site"])
def test_upgrade_from_allowed_origin_is_accepted_whatever_the_fetch_site(
    site: str | None,
) -> None:
    spy = _Spy()
    headers = {"origin": ORIGIN} | ({"sec-fetch-site": site} if site else {})
    with TestClient(_app(spy, GatewayHub())) as client:
        with client.websocket_connect("/ws", subprotocols=JSON, headers=headers) as ws:
            assert ws.accepted_subprotocol == "cv.v1.json"
            ws.send_json({"t": "hello", "id": "h"})
            assert ws.receive_json()["t"] == "welcome"
            ws.send_json({"t": "auth", "id": "a", "p": {"access_token": "t"}})
            assert ws.receive_json()["t"] == "auth_ok"
    assert spy.tokens == ["t"] and spy.resolved == [USER]


def test_origin_is_checked_before_subprotocol_negotiation() -> None:
    with TestClient(_app(_Spy(), GatewayHub())) as client:
        with pytest.raises(WebSocketDisconnect) as exc:
            headers = {"origin": EVIL}
            with client.websocket_connect("/ws", subprotocols=["cv.v2.json"], headers=headers):
                pass
    assert exc.value.code == 4403  # not 1002: a foreign page learns nothing about negotiation


def test_refusal_log_is_capped_per_cause_then_one_summary_line() -> None:
    clock, refusals = _Clock(), _refusals()
    total = REFUSAL_LOG_LIMIT + 3
    with TestClient(_app(_Spy(), GatewayHub(), clock=clock)) as client, capture_logs() as logs:
        for _ in range(total):
            assert _refuse(client, {"origin": EVIL, "sec-fetch-site": "cross-site"}) == 4403
        assert _refuse(client, {}) == 4403  # another cause has its own budget
        clock.now += REFUSAL_LOG_WINDOW_S
        assert _refuse(client, {"origin": EVIL, "sec-fetch-site": "cross-site"}) == 4403
    events = (REFUSED_LINE, SUMMARY_LINE)
    seen = [(e["event"], e["check"]) for e in logs if e.get("event") in events]
    assert seen == [(REFUSED_LINE, "cross_site")] * REFUSAL_LOG_LIMIT + [
        (SUMMARY_LINE, "cross_site"),
        (REFUSED_LINE, "origin_missing"),
        (REFUSED_LINE, "cross_site"),  # the next window logs again
    ]
    summary = _lines(logs, SUMMARY_LINE)[0]
    assert (summary["limit"], summary["window_s"]) == (REFUSAL_LOG_LIMIT, REFUSAL_LOG_WINDOW_S)
    assert _refusals() == refusals + total + 2  # the counter still sees every refusal


# -- raw ASGI: the pre-`accept` close, and header names in any case ------------------------------


def _scope(headers: list[tuple[bytes, bytes]]) -> Scope:
    return {
        "type": "websocket",
        "asgi": {"version": "3.0"},
        "scheme": "ws",
        "path": "/ws",
        "raw_path": b"/ws",
        "root_path": "",
        "query_string": b"",
        "headers": [*headers, (b"sec-websocket-protocol", b"cv.v1.json")],
        "subprotocols": ["cv.v1.json"],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
        "state": {},
    }


async def _drive(headers: list[tuple[bytes, bytes]]) -> list[Message]:
    """Run one upgrade through the router; the client disconnects right after `accept`."""
    sent: list[Message] = []
    inbox: list[Message] = [{"type": "websocket.connect"}, {"type": "websocket.disconnect"}]

    async def receive() -> Message:
        return inbox.pop(0) if inbox else {"type": "websocket.disconnect"}

    async def send(message: Message) -> None:
        sent.append(message)

    await _app(_Spy(), GatewayHub())(_scope(headers), receive, send)
    return sent


async def test_refusal_is_a_close_before_accept_on_the_asgi_wire() -> None:
    """ASGI: `websocket.close` before `websocket.accept` makes the server answer HTTP 403."""
    sent = await _drive([(b"origin", EVIL.encode())])
    assert [(m["type"], m.get("code")) for m in sent] == [("websocket.close", 4403)]


@pytest.mark.parametrize(
    ("headers", "first"),
    [
        ([(b"Origin", ORIGIN.encode())], "websocket.accept"),
        ([(b"ORIGIN", ORIGIN.encode()), (b"Sec-Fetch-Site", b"cross-site")], "websocket.accept"),
        ([(b"Origin", EVIL.encode())], "websocket.close"),
        ([(b"Origin", ORIGIN.encode()), (b"origin", EVIL.encode())], "websocket.close"),
    ],
)
async def test_header_names_in_any_case_are_read(
    headers: list[tuple[bytes, bytes]], first: str
) -> None:
    """Never `origin_missing` just because a server kept the header name's case."""
    sent = await _drive(headers)
    assert sent[0]["type"] == first


# -- create_app: `CV_ALLOWED_ORIGINS` is the allow-list ----------------------------------------


def _created(settings: Settings, spy: _Spy) -> TestClient:
    app = create_app(settings, snapshot_loader=spy.resolve, ws_authenticate=spy.authenticate)
    return TestClient(app, client=("127.0.0.1", 50000))  # on-mesh source


def test_create_app_admits_an_origin_listed_in_cv_allowed_origins() -> None:
    settings = Settings(allowed_origins=f" {ORIGIN}/ ,https://other.example")
    with _created(settings, _Spy()) as client:
        with client.websocket_connect("/ws", subprotocols=JSON, headers={"origin": ORIGIN}) as ws:
            ws.send_json({"t": "hello", "id": "h"})
            assert ws.receive_json()["t"] == "welcome"


@pytest.mark.parametrize(("allowed", "origin"), [(ORIGIN, EVIL), ("", ORIGIN)])
def test_create_app_refuses_unlisted_origin_before_auth_and_store(
    allowed: str, origin: str
) -> None:
    spy, refusals = _Spy(), _refusals()
    with _created(Settings(allowed_origins=allowed), spy) as client:
        assert _refuse(client, {"origin": origin}) == 4403
    assert _refusals() == refusals + 1  # refused by this check, not by the mesh guard
    assert spy.tokens == [] and spy.resolved == []


def test_create_app_refusal_logs_the_address_mesh_only_admitted() -> None:
    """Behind the configured proxy the log names the right-most forwarded hop, not the peer."""
    settings = Settings(
        allowed_origins=ORIGIN,
        mesh_cidrs_csv="100.64.0.0/10",
        mesh_trusted_proxy_header="x-forwarded-for",
        mesh_trusted_proxy_address="127.0.0.1",
    )
    headers = {"origin": EVIL, "x-forwarded-for": "203.0.113.9, 100.64.1.2"}
    with _created(settings, _Spy()) as client, capture_logs() as logs:
        assert _refuse(client, headers) == 4403
    assert [e["source_ip"] for e in _lines(logs, REFUSED_LINE)] == ["100.64.1.2"]
