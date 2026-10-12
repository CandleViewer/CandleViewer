"""E17-S03 through the real `/ws` socket: `sub_ok` then `snap` before any `d`, `ctl` re-snapshot,
client `resync` and the 6th-in-a-minute revocation. Every receive is bounded by `_recv` (5 s)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.ws.gateway import make_ws_router
from candleviewer.ws.permissions import ConnectionRegistry, SubscriptionServices
from candleviewer.ws.revocation import RevocationHub
from candleviewer.ws.sequencing import SequencingHub, SnapshotBody
from candleviewer.ws.upstream import UpstreamRefs
from tests.unit.ws._seq_support import Book, Clock, Source, principal, validate
from tests.unit.ws.test_lifecycle_socket import JSON, ORIGIN, _recv


class _World:
    def __init__(self) -> None:
        self.source = Source()
        book = Book("BTCUSDT")
        book.apply([["100.0", "1.000"]], [["101.0", "2.000"]])
        self.source.books["BTCUSDT"] = book
        self.source.bodies["heatmap"] = SnapshotBody(
            {"symbol": "BTCUSDT", "time_bucket_ms": 500, "columns": []}
        )
        self.hub = SequencingHub()
        self.clock = Clock()

        async def resolve(uid: uuid.UUID) -> PrincipalSnapshot:
            return principal()

        async def authenticate(token: str) -> tuple[str, uuid.UUID]:
            if token != "good":  # noqa: S105 - fake test token, not a credential
                raise PermissionError("bad token")
            return "sess-1", principal().user_id

        services = SubscriptionServices(
            upstream=UpstreamRefs(), snapshots=self.source, sequencing=self.hub
        )
        registry = ConnectionRegistry(resolve, lambda: 1, services)
        app = FastAPI()
        app.include_router(
            make_ws_router(
                authenticate=authenticate,
                registry=registry,
                revocation_hub=RevocationHub(),
                allowed_origins=frozenset({ORIGIN}),
                clock=self.clock,
                tick_s=0.005,
            )
        )
        self.client = TestClient(app, headers={"origin": ORIGIN})


def _rx(ws: Any) -> dict[str, Any]:
    while True:
        frame = _recv(ws)
        if frame["t"] != "ping":
            validate(frame)
            return frame


def _open(ws: Any) -> None:
    ws.send_json({"t": "hello", "id": "h"})
    assert _rx(ws)["t"] == "welcome"
    ws.send_json({"t": "auth", "id": "a", "p": {"access_token": "good"}})
    assert _rx(ws)["t"] == "auth_ok"


def test_socket_snap_follows_sub_ok_and_resync_loop_is_revoked() -> None:
    w = _World()
    with w.client, w.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _open(ws)
        topic = {"ch": "book.BTCUSDT.50", "opts": {"encoding": "structured"}}
        ws.send_json({"t": "sub", "id": "s1", "p": {"topics": [topic]}})
        assert _rx(ws)["t"] == "sub_ok"
        snap = _rx(ws)
        assert (snap["t"], snap["s"], snap["meta"]["reason"]) == ("snap", 1, "initial")
        assert snap["p"]["bids"] == [["100.0", "1.000"]]
        for i in range(5):
            w.clock.now = float(i)
            ws.send_json(
                {"t": "resync", "id": f"r{i}", "ch": "book.BTCUSDT.50", "p": {"reason": "manual"}}
            )
            again = _rx(ws)
            assert (again["t"], again["s"], again["meta"]["reason"]) == (
                "snap",
                i + 2,
                "client_resync",
            )
        ws.send_json(
            {"t": "resync", "id": "r6", "ch": "book.BTCUSDT.50", "p": {"reason": "manual"}}
        )
        err, revoked = _rx(ws), _rx(ws)
        assert err["p"]["code"] == "resync_rate_limited"
        assert revoked["p"]["reason"] == "resync_rate_limited"


def test_socket_ctl_identity_change_emits_reconfigure_snap() -> None:
    w = _World()
    with w.client, w.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _open(ws)
        ws.send_json({"t": "sub", "id": "s1", "p": {"topics": ["heatmap.BTCUSDT"]}})
        assert _rx(ws)["t"] == "sub_ok"
        assert _rx(ws)["s"] == 1
        ws.send_json(
            {"t": "ctl", "id": "c1", "ch": "heatmap.BTCUSDT", "p": {"time_bucket_ms": 1000}}
        )
        ok = _rx(ws)
        assert ok["t"] == "ctl_ok" and ok["p"]["resnapshot"] is True
        snap = _rx(ws)
        assert snap["meta"] == {"reason": "reconfigure", "source": "live", "previous_seq": 1}
        assert len(w.hub) == 1
    assert len(w.hub) == 0  # unregistered on close
