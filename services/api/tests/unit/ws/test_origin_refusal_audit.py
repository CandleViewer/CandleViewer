"""#2269: a refused WS upgrade writes one bounded `auth.ws_origin_refused` record (C-2.9).

`23-ws-protocol.md` §2.5: each upgrade refused by the SR-042 / SR-183 `Origin` check (close
`4403` before `accept`) is audited with the source address MeshOnly admitted (`actor_ip`) and
the bounded check (`reason`), never a header value. The writes are bounded as the REST CSRF
refusals are (C-2.18): a per-source budget, the app's shared in-flight cap
(`RefusalAuditTracker`) and a shielded write awaited for at most a timeout. Over a bound the
upgrade is still refused and counted; a slow or failed write never admits it.

No network, no sleeps: in-memory audit fakes, an injected budget clock, TestClient sessions and
direct ASGI drives. The stall cases use a short write timeout, as the REST guard's tests do.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.types import Message, Scope
from starlette.websockets import WebSocketDisconnect
from structlog.testing import capture_logs

from candleviewer.api.csrf import RefusalAuditTracker
from candleviewer.app import create_app
from candleviewer.audit.actions import validate_action
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.auth.throttle import PerIpLoginThrottle
from candleviewer.settings import Settings
from candleviewer.ws.gateway import GatewayHub, make_ws_router
from candleviewer.ws.lifecycle import ORIGIN_FORBIDDEN, OriginRefusal
from candleviewer.ws.metrics import cv_ws_closes_total
from candleviewer.ws.origin_audit import (
    OBJECT_KIND,
    REFUSAL_AUDIT_TIMEOUT_S,
    REFUSAL_AUDIT_WINDOW_S,
    REFUSAL_AUDITS_PER_WINDOW,
    OriginRefusalAudit,
)
from candleviewer.ws.permissions import ConnectionRegistry
from candleviewer.ws.revocation import RevocationHub

ORIGIN = "http://testserver"  # the TestClient's own origin
EVIL = "https://evil.example"
JSON = ["cv.v1.json"]
USER = uuid.uuid4()
PEER = "testclient"  # the TestClient's peer address (no MeshOnly in a bare router)
SLOW_S = 0.01  # write timeout for the stall cases
WS_ORIGIN_REFUSED = "auth.ws_origin_refused"


def _record(check: str, actor_ip: str | None) -> dict[str, Any]:
    """The whole record a refusal writes: these fields and nothing else (no header value)."""
    return {
        "action": WS_ORIGIN_REFUSED,
        "actor_label": "(unknown)",
        "actor_ip": actor_ip,
        "object_kind": OBJECT_KIND,
        "outcome": AuditOutcome.FAILURE,
        "severity": Severity.WARNING,
        "reason": check,
    }


class _Audit:
    """Records each write; refuses an unregistered action as `AuditWriter.emit` does."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    async def emit(self, action: str, **kw: Any) -> None:
        validate_action(action)
        self.records.append({"action": action, **kw})


class _FailingAudit:
    def __init__(self) -> None:
        self.calls = 0

    async def emit(self, action: str, **kw: Any) -> None:
        self.calls += 1
        raise OSError("audit WAL unavailable")


class _StalledAudit:
    """A write that blocks (in a worker thread, like a stalled WAL append) until released."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.records: list[dict[str, Any]] = []

    async def emit(self, action: str, **kw: Any) -> None:
        await asyncio.to_thread(self.release.wait, 5)
        self.records.append({"action": action, **kw})


class _Clock:
    """Monotonic seconds, advanced only by the test."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _budget(
    clock: Callable[[], float], per_window: int = REFUSAL_AUDITS_PER_WINDOW
) -> PerIpLoginThrottle:
    return PerIpLoginThrottle(max_attempts=per_window, window_s=REFUSAL_AUDIT_WINDOW_S, clock=clock)


def _closes() -> float:
    for family in cv_ws_closes_total.collect():
        for s in family.samples:
            if s.name == "cv_ws_closes_total" and s.labels.get("reason") == ORIGIN_FORBIDDEN:
                return float(s.value)
    return 0.0


def _events(logs: Sequence[Mapping[str, Any]], event: str) -> list[Mapping[str, Any]]:
    return [e for e in logs if e.get("event") == event]


# -- the auditor on its own ----------------------------------------------------------------------


async def test_record_spends_the_source_budget_then_writes_nothing_until_the_window_ends() -> None:
    clock, audit = _Clock(), _Audit()
    auditor = OriginRefusalAudit(audit, tracker=RefusalAuditTracker(), budget=_budget(clock))
    written = [
        await auditor.record(OriginRefusal.CROSS_SITE, "100.64.0.7")
        for _ in range(REFUSAL_AUDITS_PER_WINDOW + 5)
    ]
    assert written == [True] * REFUSAL_AUDITS_PER_WINDOW + [False] * 5
    assert len(audit.records) == REFUSAL_AUDITS_PER_WINDOW
    clock.now += REFUSAL_AUDIT_WINDOW_S + 1  # the window has passed: the source is audited again
    assert await auditor.record(OriginRefusal.CROSS_SITE, "100.64.0.7") is True
    assert len(audit.records) == REFUSAL_AUDITS_PER_WINDOW + 1


async def test_record_budget_is_per_source_address_and_one_for_unknown_sources() -> None:
    audit = _Audit()
    auditor = OriginRefusalAudit(audit, tracker=RefusalAuditTracker(), budget=_budget(_Clock(), 1))
    assert await auditor.record(OriginRefusal.CROSS_SITE, "100.64.0.7") is True
    assert await auditor.record(OriginRefusal.CROSS_SITE, "100.64.0.7") is False
    assert await auditor.record(OriginRefusal.ORIGIN_MISSING, "100.64.0.9") is True
    assert await auditor.record(OriginRefusal.ORIGIN_NULL, None) is True
    assert await auditor.record(OriginRefusal.ORIGIN_NULL, None) is False
    assert audit.records == [
        _record("cross_site", "100.64.0.7"),
        _record("origin_missing", "100.64.0.9"),
        _record("origin_null", None),
    ]


async def test_record_skips_the_write_while_the_in_flight_cap_is_full() -> None:
    """The shared cap (C-2.18): no new write while it is full, and the source's budget is
    not spent on a refusal that wrote nothing."""
    stalled, clock = _StalledAudit(), _Clock()
    tracker = RefusalAuditTracker(cap=1)
    budget = _budget(clock, 1)
    auditor = OriginRefusalAudit(stalled, tracker=tracker, budget=budget, timeout_s=SLOW_S)
    assert await auditor.record(OriginRefusal.CROSS_SITE, "100.64.0.7") is True  # stalls
    assert len(tracker) == 1 and tracker.full
    assert await auditor.record(OriginRefusal.CROSS_SITE, "100.64.0.9") is False
    stalled.release.set()
    assert await tracker.drain(5) == 0
    assert await auditor.record(OriginRefusal.CROSS_SITE, "100.64.0.9") is True
    assert [r["actor_ip"] for r in stalled.records] == ["100.64.0.7", "100.64.0.9"]


async def test_record_returns_at_the_timeout_and_leaves_a_stalled_write_tracked() -> None:
    stalled, tracker = _StalledAudit(), RefusalAuditTracker()
    auditor = OriginRefusalAudit(stalled, tracker=tracker, timeout_s=SLOW_S)
    with capture_logs() as logs:
        assert await auditor.record(OriginRefusal.CROSS_SITE, "100.64.0.7") is True
    assert stalled.records == [] and len(tracker) == 1  # not cancelled: still writing
    assert [e["check"] for e in _events(logs, "auth.ws_origin_refused.audit_slow")] == [
        "cross_site"
    ]
    stalled.release.set()
    assert await tracker.drain(5) == 0  # the shutdown drain lets it land
    assert stalled.records == [_record("cross_site", "100.64.0.7")]


async def test_record_logs_a_failed_write_by_type_and_never_raises() -> None:
    failing = _FailingAudit()
    auditor = OriginRefusalAudit(failing, tracker=RefusalAuditTracker())
    with capture_logs() as logs:
        assert await auditor.record(OriginRefusal.ORIGIN_MISSING, "100.64.0.7") is True
    assert failing.calls == 1
    entries = _events(logs, "auth.ws_origin_refused.audit_unavailable")
    assert [(e["check"], e["error"], e["log_level"]) for e in entries] == [
        ("origin_missing", "OSError", "error")
    ]
    assert "WAL" not in str(entries)  # the type only, never the message


async def test_record_cancelled_while_waiting_propagates_and_never_cuts_the_write() -> None:
    stalled, tracker = _StalledAudit(), RefusalAuditTracker()
    auditor = OriginRefusalAudit(stalled, tracker=tracker, timeout_s=5.0)
    waiting = asyncio.create_task(auditor.record(OriginRefusal.CROSS_SITE, "100.64.0.7"))
    await asyncio.sleep(0)  # one loop turn: the write is tracked and being awaited
    assert len(tracker) == 1
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    assert len(tracker) == 1  # shielded: the write goes on
    stalled.release.set()
    assert await tracker.drain(5) == 0
    assert len(stalled.records) == 1


async def test_defaults_match_the_rest_refusal_bounds() -> None:
    """Same per-source budget and write bound as the REST CSRF refusals (`api/csrf.py`)."""
    from candleviewer.api.csrf import (
        ANON_REFUSAL_WINDOW_S,
        ANON_REFUSALS_PER_WINDOW,
        AUDIT_TIMEOUT_S,
    )

    assert REFUSAL_AUDITS_PER_WINDOW == ANON_REFUSALS_PER_WINDOW
    assert REFUSAL_AUDIT_WINDOW_S == ANON_REFUSAL_WINDOW_S
    assert REFUSAL_AUDIT_TIMEOUT_S == AUDIT_TIMEOUT_S


# -- socket level: the router refuses, counts and audits -------------------------------------------


class _Spy:
    """Stand-ins for the session store (`authenticate`) and the principal store (`resolve`)."""

    def __init__(self) -> None:
        self.tokens: list[str] = []

    async def authenticate(self, token: str) -> tuple[str, uuid.UUID, datetime]:
        self.tokens.append(token)
        return "sess-1", USER, datetime(2100, 1, 1, tzinfo=UTC)

    async def resolve(self, uid: uuid.UUID) -> PrincipalSnapshot:
        return PrincipalSnapshot(
            uid, frozenset({"viewer"}), frozenset({Permission.MARKETDATA_READ})
        )


def _app(spy: _Spy, hub: GatewayHub, origin_audit: OriginRefusalAudit | None) -> FastAPI:
    app = FastAPI()
    app.include_router(
        make_ws_router(
            authenticate=spy.authenticate,
            registry=ConnectionRegistry(spy.resolve, lambda: 1),
            revocation_hub=RevocationHub(),
            allowed_origins=frozenset({ORIGIN}),
            hub=hub,
            origin_audit=origin_audit,
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


_REFUSED = [
    pytest.param({"origin": EVIL, "sec-fetch-site": "cross-site"}, "cross_site", id="cross-site"),
    pytest.param({"origin": EVIL, "sec-fetch-site": "same-site"}, "cross_site", id="same-site"),
    pytest.param({"origin": EVIL}, "origin_not_allowed", id="bad-origin"),
    pytest.param({"origin": "null"}, "origin_null", id="null-origin"),
    pytest.param({}, "origin_missing", id="missing-origin"),
]


@pytest.mark.parametrize(("headers", "check"), _REFUSED)
def test_refused_upgrade_writes_exactly_one_record_with_actor_ip_and_check(
    headers: dict[str, str], check: str
) -> None:
    """Scenario: a refused upgrade is audited (and the record holds no header value)."""
    spy, hub, audit = _Spy(), GatewayHub(), _Audit()
    auditor = OriginRefusalAudit(audit, tracker=RefusalAuditTracker())
    with TestClient(_app(spy, hub, auditor)) as client:
        assert _refuse(client, {**headers, "x-correlation-id": str(uuid.uuid4())}) == 4403
    assert audit.records == [_record(check, PEER)]
    assert spy.tokens == [] and len(hub) == 0  # still refused before accept, auth and stores


def test_admitted_upgrade_writes_no_refusal_record() -> None:
    audit = _Audit()
    auditor = OriginRefusalAudit(audit, tracker=RefusalAuditTracker())
    with TestClient(_app(_Spy(), GatewayHub(), auditor)) as client:
        with client.websocket_connect("/ws", subprotocols=JSON, headers={"origin": ORIGIN}) as ws:
            ws.send_json({"t": "hello", "id": "h"})
            assert ws.receive_json()["t"] == "welcome"
    assert audit.records == []


def test_refusal_flood_is_refused_and_counted_but_audited_only_within_the_budget() -> None:
    """Scenario: a refusal flood stays bounded."""
    clock, audit = _Clock(), _Audit()
    auditor = OriginRefusalAudit(audit, tracker=RefusalAuditTracker(), budget=_budget(clock))
    spy, hub, closes = _Spy(), GatewayHub(), _closes()
    flood = REFUSAL_AUDITS_PER_WINDOW + 7
    cross = {"origin": EVIL, "sec-fetch-site": "cross-site"}
    with TestClient(_app(spy, hub, auditor)) as client:
        codes = [_refuse(client, cross) for _ in range(flood)]
        assert len(audit.records) == REFUSAL_AUDITS_PER_WINDOW  # no rows past the budget
        clock.now += REFUSAL_AUDIT_WINDOW_S + 1
        codes.append(_refuse(client, cross))  # a new window audits again
    assert codes == [4403] * (flood + 1)  # every upgrade refused before accept
    assert spy.tokens == [] and len(hub) == 0
    assert _closes() == closes + flood + 1  # every refusal stays visible in the counter
    assert audit.records == [_record("cross_site", PEER)] * (REFUSAL_AUDITS_PER_WINDOW + 1)


def test_stalled_audit_writer_never_holds_the_4403_past_the_bound_nor_admits() -> None:
    """Scenario: the audit sink is slow. The close comes at the write timeout while the
    write is still blocked; the write is never cancelled and lands once released."""
    stalled, tracker, spy, hub = _StalledAudit(), RefusalAuditTracker(), _Spy(), GatewayHub()
    auditor = OriginRefusalAudit(stalled, tracker=tracker, timeout_s=SLOW_S)
    closes = _closes()
    with TestClient(_app(spy, hub, auditor)) as client, capture_logs() as logs:
        assert _refuse(client, {"origin": EVIL, "sec-fetch-site": "cross-site"}) == 4403
        assert stalled.records == [] and len(tracker) == 1  # closed while the write is blocked
        stalled.release.set()
        assert client.portal is not None
        assert client.portal.call(tracker.drain, 5.0) == 0
    assert stalled.records == [_record("cross_site", PEER)]
    assert spy.tokens == [] and len(hub) == 0 and _closes() == closes + 1
    assert len(_events(logs, "auth.ws_origin_refused.audit_slow")) == 1


def test_failing_audit_writer_still_refuses_4403_and_never_admits() -> None:
    """Scenario: the audit sink is down."""
    failing, spy, hub = _FailingAudit(), _Spy(), GatewayHub()
    auditor = OriginRefusalAudit(failing, tracker=RefusalAuditTracker())
    with TestClient(_app(spy, hub, auditor)) as client, capture_logs() as logs:
        assert _refuse(client, {"origin": EVIL}) == 4403
        assert _refuse(client, {}) == 4403
    assert failing.calls == 2 and spy.tokens == [] and len(hub) == 0
    assert len(_events(logs, "auth.ws_origin_refused.audit_unavailable")) == 2


# -- raw ASGI: the record is written before the close, and nothing is accepted -----------------


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
        "state": {"cv_mesh_source": "100.64.0.7"},  # what MeshOnly admitted
    }


async def test_record_lands_before_the_close_on_the_asgi_wire() -> None:
    order: list[str] = []

    class _Ordered(_Audit):
        async def emit(self, action: str, **kw: Any) -> None:
            await super().emit(action, **kw)
            order.append(action)

    audit = _Ordered()
    app = _app(_Spy(), GatewayHub(), OriginRefusalAudit(audit, tracker=RefusalAuditTracker()))

    async def receive() -> Message:
        return {"type": "websocket.connect"}

    async def send(message: Message) -> None:
        order.append(f"{message['type']}:{message.get('code')}")

    await app(_scope([(b"origin", EVIL.encode())]), receive, send)
    assert order == [WS_ORIGIN_REFUSED, "websocket.close:4403"]
    assert audit.records == [_record("origin_not_allowed", "100.64.0.7")]


# -- create_app: wired to the audit writer and the app's shared refusal-audit tracker -----------


class _TrackedAudit(_Audit):
    """Records each write and how many refusal audits the app's tracker held during it."""

    def __init__(self, tracker: RefusalAuditTracker) -> None:
        super().__init__()
        self.tracker = tracker
        self.in_flight: list[int] = []

    async def emit(self, action: str, **kw: Any) -> None:
        self.in_flight.append(len(self.tracker))
        await super().emit(action, **kw)


def _created(settings: Settings, spy: _Spy) -> tuple[TestClient, _TrackedAudit]:
    app = create_app(settings, snapshot_loader=spy.resolve, ws_authenticate=spy.authenticate)
    audit = _TrackedAudit(app.state.csrf_refusal_audits)
    app.state.app_context.audit._writer = audit  # the lazy emitters resolve it per call
    return TestClient(app, client=("127.0.0.1", 50000)), audit  # on-mesh source


def test_create_app_audits_a_refusal_with_the_address_mesh_only_admitted() -> None:
    """Behind the configured proxy, `actor_ip` is the right-most forwarded hop (#2275); the
    action passes the registry check the real writer applies."""
    settings = Settings(
        allowed_origins=ORIGIN,
        mesh_cidrs_csv="100.64.0.0/10",
        mesh_trusted_proxy_header="x-forwarded-for",
        mesh_trusted_proxy_address="127.0.0.1",
    )
    spy = _Spy()
    client, audit = _created(settings, spy)
    headers = {"origin": EVIL, "x-forwarded-for": "203.0.113.9, 100.64.1.2"}
    with client:
        assert _refuse(client, headers) == 4403
    assert audit.records == [_record("origin_not_allowed", "100.64.1.2")]
    assert spy.tokens == []


def test_create_app_tracks_the_write_with_the_rest_refusal_audits() -> None:
    """One in-flight cap and one shutdown drain (`main.py`) for REST and WS refusal audits."""
    client, audit = _created(Settings(allowed_origins=ORIGIN), _Spy())
    with client:
        assert _refuse(client, {"origin": EVIL, "sec-fetch-site": "cross-site"}) == 4403
    assert audit.in_flight == [1]  # the write ran as a task of the app's shared tracker
    assert [r["reason"] for r in audit.records] == ["cross_site"]
