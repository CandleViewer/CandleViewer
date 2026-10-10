"""#377 E17 wiring through the real `create_app()`: composition, kill-switch revocation,
planned shutdown and the `cv_ws_*` catalogue (no network, no sleeps, no I/O in create_app)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from prometheus_client import generate_latest
from prometheus_client.parser import text_string_to_metric_families

from candleviewer.app import create_app
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.settings import Environment, Settings
from candleviewer.ws.gateway import GatewayHub
from candleviewer.ws.metrics import CV_WS_NAMES
from candleviewer.ws.sequencing import SequencingHub
from candleviewer.ws.upstream import UpstreamRefs
from candleviewer.ws_wiring import (
    IngestionUpstreamSink,
    PendingSnapshotSource,
    SnapshotRouter,
    WsEvents,
    WsRuntime,
)

USER = uuid.uuid4()
ACC = uuid.uuid4()
JSON = ["cv.v1.json"]


class _Kill:
    """Principal source: while the kill switch is engaged this test's policy withdraws
    `orders:read`, so the re-evaluation must revoke the `orders` subscription."""

    def __init__(self) -> None:
        self.engaged = False

    async def load(self, uid: uuid.UUID) -> PrincipalSnapshot:
        perms = {Permission.MARKETDATA_READ}
        if not self.engaged:
            perms.add(Permission.ORDERS_READ)
        grants = (AccountGrant(ACC, True, True, False),)
        return PrincipalSnapshot(uid, frozenset({"manager"}), frozenset(perms), grants)


async def _authenticate(token: str) -> tuple[str, uuid.UUID]:
    if token != "tok":  # noqa: S105 - test vector, not a credential
        raise PermissionError("bad token")
    return "sess-1", USER


def _settings() -> Settings:
    return Settings(
        environment=Environment.DEMO,
        git_sha="cafe123",
        version="4.5.6",
        ws_shutdown_grace_ms=0,
        ws_shutdown_expected_downtime_ms=7000,
    )


@pytest.fixture
def world() -> Iterator[tuple[TestClient, _Kill]]:
    k = _Kill()
    app = create_app(_settings(), snapshot_loader=k.load, ws_authenticate=_authenticate)
    client = TestClient(app, client=("127.0.0.1", 50000))
    with client:  # opens the portal; create_app's own lifespan only (no supervisor)
        yield client, k


def _open(ws: Any) -> dict[str, Any]:
    ws.send_json({"t": "hello", "id": "h", "p": {"clock_ms": 1}})
    welcome: dict[str, Any] = ws.receive_json()
    ws.send_json({"t": "auth", "id": "a", "p": {"access_token": "tok"}})
    assert ws.receive_json()["t"] == "auth_ok"
    return welcome


def test_create_app_composes_gateway_services(world: tuple[TestClient, _Kill]) -> None:
    client, _ = world
    st = client.app.state  # type: ignore[attr-defined]  # Starlette app typed as ASGIApp
    svc = st.ws_registry.services
    assert isinstance(svc.upstream, UpstreamRefs)
    assert isinstance(svc.upstream._sink, IngestionUpstreamSink)
    assert isinstance(svc.sequencing, SequencingHub)
    assert isinstance(svc.snapshots, SnapshotRouter)
    assert svc.audit is not None and svc.instrument_known is not None
    assert svc.instrument_known("BTCUSDT") is True  # no catalogue yet: grammar only
    assert isinstance(st.ws_hub, GatewayHub)
    assert isinstance(st.ws_events, WsEvents) and st.ws_events.registry is st.ws_registry
    assert isinstance(st.ws_runtime, WsRuntime) and st.ws_runtime.hub is st.ws_hub


def test_welcome_carries_settings_build_info(world: tuple[TestClient, _Kill]) -> None:
    client, _ = world
    with client.websocket_connect("/ws", subprotocols=JSON) as ws:
        p = _open(ws)["p"]
    assert (p["server_version"], p["git_sha"]) == ("4.5.6", "cafe123")


def test_pending_snapshot_adapter_reports_pending_not_crash(
    world: tuple[TestClient, _Kill],
) -> None:
    client, _ = world
    with client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _open(ws)
        ws.send_json({"t": "sub", "id": "s", "p": {"topics": ["book.BTCUSDT.50"]}})
        result = ws.receive_json()["p"]["results"][0]
        assert result["ok"] is True and result["snapshot_pending"] is True
        ws.send_json({"t": "ping", "id": "p"})
        assert ws.receive_json()["t"] == "pong"  # no snap was emitted in between


def test_pending_source_raises_and_router_maps_to_none() -> None:
    src = PendingSnapshotSource("book", "#2196")
    sub: Any = object()
    with pytest.raises(NotImplementedError, match="#2196"):
        src.build(sub)


def test_router_turns_pending_into_none_and_no_continuity() -> None:
    sub: Any = SimpleNamespace(topic=SimpleNamespace(family=SimpleNamespace(family="book")))
    router = SnapshotRouter({"book": PendingSnapshotSource("book", "#2196")})
    assert router.build(sub) is None
    assert router.generation(sub) == 0 and router.continuity(sub, None) is False
    other: Any = SimpleNamespace(topic=SimpleNamespace(family=SimpleNamespace(family="trades")))
    assert router.build(other) is None and router.continuity(other, 1) is False


class _Stream:
    def __init__(self, refuse: bool = False) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.refuse = refuse

    def acquire(self, consumer: str, symbol: str) -> None:
        if self.refuse:
            raise ValueError(symbol)
        self.calls.append(("acquire", consumer, symbol))

    def release(self, consumer: str, symbol: str) -> None:
        self.calls.append(("release", consumer, symbol))


async def test_ingestion_sink_leases_one_consumer_per_key_and_tolerates_refusal() -> None:
    stream = _Stream()
    sink = IngestionUpstreamSink(lambda fam: stream if fam == "trades" else None)
    await sink.open(("BTCUSDT", "trades", ()))
    await sink.drop(("BTCUSDT", "trades", ()))
    await sink.open(("BTCUSDT", "footprint", ("time", "1m")))  # no stream: no-op
    assert stream.calls == [
        ("acquire", "ws:trades:", "BTCUSDT"),
        ("release", "ws:trades:", "BTCUSDT"),
    ]
    refusing = IngestionUpstreamSink(lambda _f: _Stream(refuse=True))
    await refusing.open(("NOPEUSDT", "book", ("50",)))  # logged, never raised


def test_kill_switch_event_pushes_system_then_revokes(world: tuple[TestClient, _Kill]) -> None:
    client, k = world
    events: WsEvents = client.app.state.ws_events  # type: ignore[attr-defined]
    with client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _open(ws)
        ws.send_json({"t": "sub", "id": "s", "p": {"topics": ["system"]}})
        assert ws.receive_json()["t"] == "sub_ok"
        orders = {"ch": "orders", "opts": {"exchange_account_ids": [str(ACC)]}}
        ws.send_json({"t": "sub", "id": "o", "p": {"topics": [orders]}})
        assert ws.receive_json()["p"]["results"][0]["ok"] is True
        k.engaged = True
        assert client.portal is not None
        client.portal.call(lambda: events.kill_switch_changed(engaged=True, reason="halt"))
        sys_frame = ws.receive_json()
        assert (sys_frame["t"], sys_frame["ch"]) == ("d", "system")
        assert sys_frame["p"]["kind"] == "kill_switch"
        assert sys_frame["p"]["kill_switch"]["engaged"] is True
        change = ws.receive_json()
        assert change["t"] == "permission_change"
        assert "orders:read" not in change["p"]["permissions"]
        revoked = ws.receive_json()
        assert (revoked["t"], revoked["ch"]) == ("revoked", "orders")
        assert revoked["p"]["reason"] == "permission_revoked"
        # the live provider now reports engaged on a fresh auth_ok
        ws.send_json({"t": "auth", "id": "a2", "p": {"access_token": "tok"}})
        assert ws.receive_json()["p"]["kill_switch"]["engaged"] is True


def test_user_disabled_event_sends_bye_4403(world: tuple[TestClient, _Kill]) -> None:
    client, _ = world
    events: WsEvents = client.app.state.ws_events  # type: ignore[attr-defined]
    with client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _open(ws)
        assert client.portal is not None
        assert client.portal.call(events.user_disabled, USER) == 1
        bye = ws.receive_json()
        assert (bye["t"], bye["p"]["reason"], bye["p"]["code"]) == ("bye", "user_disabled", 4403)


def test_runtime_stop_sends_shutdown_notice_then_1001(world: tuple[TestClient, _Kill]) -> None:
    client, _ = world
    runtime: WsRuntime = client.app.state.ws_runtime  # type: ignore[attr-defined]
    with client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _open(ws)
        assert client.portal is not None
        notified = client.portal.call(runtime.stop)
        notice = ws.receive_json()
        assert (notice["ch"], notice["p"]["kind"]) == ("system", "shutdown_notice")
        assert notice["p"]["expected_downtime_ms"] == 7000
        bye = ws.receive_json()
        assert (bye["t"], bye["p"]["reason"], bye["p"]["code"]) == ("bye", "shutdown", 1001)
    assert notified == 1


def test_every_cv_ws_metric_is_catalogued_and_served(world: tuple[TestClient, _Kill]) -> None:
    client, _ = world
    catalogued = {s.name for s in CATALOGUE if s.name.startswith("cv_ws_")}
    assert catalogued == CV_WS_NAMES and len(CV_WS_NAMES) == 14
    with client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _open(ws)
        ws.send_json({"t": "auth", "id": "x", "p": {}})  # one failed re-auth
        assert ws.receive_json()["p"]["code"] == "auth_failed"
        ws.send_json({"t": "sub", "id": "s", "p": {"topics": ["book.BTCUSDT.50"]}})
        ws.receive_json()
        ws.send_json(
            {"t": "resync", "id": "r", "ch": "book.BTCUSDT.50", "p": {"reason": "sequence_gap"}}
        )
        ws.send_json({"t": "ping", "id": "p"})
        assert ws.receive_json()["t"] == "pong"
        for _ in range(2):  # attempts 2 and 3 -> bye auth_failed + 4401 (cv_ws_closes_total)
            ws.send_json({"t": "auth", "id": "x", "p": {}})
        assert ws.receive_json()["p"]["code"] == "auth_failed"
        assert ws.receive_json()["t"] == "bye"
    reg = client.app.state.app_context.metrics  # type: ignore[attr-defined]
    text = generate_latest(reg).decode()
    families = {f.name: f for f in text_string_to_metric_families(text)}
    served = {n for n in CV_WS_NAMES if n.removesuffix("_total") in families}
    assert served == CV_WS_NAMES
    for name in (
        "cv_ws_handshake_seconds",
        "cv_ws_auth_failures",
        "cv_ws_clock_skew_ms",
        "cv_ws_subscribe",
        "cv_ws_sequence_gaps_detected",
        "cv_ws_closes",
    ):
        samples = families[name].samples
        assert samples and all(x.labels["env"] == "demo" for x in samples), name
