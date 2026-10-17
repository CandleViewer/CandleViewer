"""E12-T06 slice D2 (#399): `bars.*` through the real `/ws` socket, wired as `create_app` wires it:
the store, then the publisher, on the emit path; the store behind the snapshots and the hold; the
trades lease. Every receive is bounded (`_recv`, 5 s); emissions run on the app's loop (portal)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, Final

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.bars.emit import EmitRouter
from candleviewer.bars.models import Bar, BarSpec, BarUpdate
from candleviewer.bars.reader import BarTail
from candleviewer.bars.series_store import SeriesStore
from candleviewer.ws.bars_publish import BarsPublisher
from candleviewer.ws.bars_source import BarsSnapshotSource
from candleviewer.ws.binary import decode_b64
from candleviewer.ws.cvwb_vectors import structured
from candleviewer.ws.gateway import make_ws_router
from candleviewer.ws.permissions import ConnectionRegistry, SubscriptionServices
from candleviewer.ws.revocation import RevocationHub
from candleviewer.ws.sequencing import SequencingHub
from candleviewer.ws.upstream import UpstreamRefs
from candleviewer.ws_wiring import IngestionUpstreamSink, default_snapshot_router, ingestion_streams
from tests.unit.ws._seq_support import Clock, principal, validate
from tests.unit.ws.test_app_wiring import _Stream
from tests.unit.ws.test_bars_source import CH, SPEC, SYM, _bar, _up
from tests.unit.ws.test_lifecycle_socket import JSON, ORIGIN, _recv
from tests.unit.ws.test_sequencing_socket import _open
from tests.unit.ws.test_subscriptions import _Bars

KEY: Final = (SYM, "bars", ("time", "5"))


class _World:
    def __init__(self, rows: tuple[tuple[int, Bar], ...] = ()) -> None:
        """`rows`: the series' stored tail, which a first hold hydrates from."""

        async def tail(symbol: str, spec: BarSpec, limit: int) -> BarTail:
            return BarTail(list(rows))

        self.now = 0.0
        self.bars, self.trades, hub = _Bars(), _Stream(), SequencingHub()
        self.store = SeriesStore(tail, release_grace_s=0.0, clock=lambda: self.now)
        publisher = BarsPublisher(hub, lambda _s: (1, 3), swap_reason="generation_swap")
        self.router = EmitRouter([self.store, publisher])
        source = BarsSnapshotSource(self.store, lambda _s: (1, 3), seed=publisher.note_generation)
        ctx: Any = SimpleNamespace(ingestion=SimpleNamespace(trades=self.trades))
        self.upstream = UpstreamRefs(IngestionUpstreamSink(ingestion_streams(ctx)))
        services = SubscriptionServices(
            upstream=self.upstream, bars=self.bars, series=self.store, sequencing=hub,
            snapshots=default_snapshot_router({"bars": source}), clock=lambda: self.now,
        )  # fmt: skip

        async def resolve(uid: uuid.UUID) -> PrincipalSnapshot:
            return principal()

        async def authenticate(token: str) -> tuple[str, uuid.UUID, datetime]:
            return "sess-1", principal().user_id, datetime(2100, 1, 1, tzinfo=UTC)

        app = FastAPI()
        app.include_router(
            make_ws_router(
                authenticate=authenticate,
                registry=ConnectionRegistry(resolve, lambda: 1, services),
                revocation_hub=RevocationHub(),
                allowed_origins=frozenset({ORIGIN}),
                clock=Clock(),
                tick_s=0.005,
            )
        )
        self.client = TestClient(app, headers={"origin": ORIGIN})

    def call(self, fn: Any, *args: Any) -> Any:
        portal = self.client.portal
        assert portal is not None  # set while the client context is open
        return portal.call(fn, *args)

    def emit(self, generation: int, *updates: BarUpdate) -> None:
        self.call(self.router.emit, SPEC, updates, generation)


def _rx(ws: Any) -> dict[str, Any]:
    while True:
        frame = _recv(ws)
        if frame["t"] != "ping":
            validate(frame)
            return frame


def _subscribe(ws: Any, opts: dict[str, Any]) -> dict[str, Any]:  # the `snap` after `sub_ok`
    _open(ws)
    ws.send_json({"t": "sub", "id": "s", "p": {"topics": [{"ch": CH, "opts": opts}]}})
    assert _rx(ws)["p"]["results"][0]["ok"] is True
    return _rx(ws)


def _items(frame: dict[str, Any]) -> list[tuple[int, int, bool]]:
    bars = structured(decode_b64(frame["p"]))["bars"] if frame["e"] == "b64" else frame["p"]["bars"]
    return [(b["generation"], b["index"], b["confirm"]) for b in bars]


@pytest.mark.parametrize("before", ["nothing", "an emission", "a hold, then an emission"])
def test_bars_snapshot_then_a_generation_swap_then_deltas_in_both_encodings(before: str) -> None:
    """Rows at 7; the publisher saw nothing, or 9 while no hold kept the series (a `footprint`
    lessee): the snapshot's 7 is its baseline, so 9 is a swap, never a `d` (§7.1 guarantee 3)."""
    w = _World(rows=((7, _bar(0)), (7, _bar(1))))
    with w.client:
        if before.startswith("a hold"):  # its snapshot seeds 7, then the socket's end frees it
            with w.client.websocket_connect("/ws", subprotocols=JSON) as ws:
                _subscribe(ws, {})
            assert _freed(w)
        if before != "nothing":
            w.emit(9, _up("open", 0))  # held by no one: only the publisher sees generation 9
        with (
            w.client.websocket_connect("/ws", subprotocols=JSON) as j,
            w.client.websocket_connect("/ws", subprotocols=JSON) as b,
        ):
            flows = ((j, True), (b, False))
            snaps = [_subscribe(j, {"encoding": "structured", "include_delta": True}),
                     _subscribe(b, {"encoding": "binary"})]  # fmt: skip
            assert [s["e"] for s in snaps] == ["j", "b64"]
            for snap, (_, flow) in zip(snaps, flows, strict=True):
                owner = {"spec_hash": SPEC.spec_hash, "build_version": 1, "include_delta": flow}
                assert snap["meta"] == {"reason": "initial", "source": "live", **owner}
                assert _items(snap) == [(7, 0, True), (7, 1, True)]
            w.emit(9, _up("open", 0))  # the new epoch reaches the held series: index 0 again
            for ws, _ in flows:
                snap = _rx(ws)
                meta = snap["meta"]
                assert (snap["t"], snap["s"], meta.get("reason"), meta.get("previous_seq")) == (
                    "snap", 2, "generation_swap", 1)  # fmt: skip
                assert _items(snap) == [(9, 0, False)]  # the whole series replaced
            w.emit(9, _up("close", 0))
            for ws, flow in flows:
                d = _rx(ws)
                assert (d["t"], d["s"], d["e"], d["meta"]) == ("d", 3, "j" if flow else "b64",
                                                               {"include_delta": flow})  # fmt: skip
                assert _items(d) == [(9, 0, True)]
    assert w.trades.calls == [("acquire", "ws:bars:time:5", SYM)]  # one lease for every socket
    assert len(w.bars.registered) == 2 + before.startswith("a hold")


def _freed(w: _World) -> bool:  # whether the store let the series go
    w.now += 1.0  # past its 0 s grace: the next `ensure` frees an expired series
    w.call(w.store.ensure, "ETHUSDT", SPEC)
    return w.store.latest(SYM, SPEC.spec_hash, 1) is None


def test_unsub_and_the_socket_end_release_the_hold_the_lease_and_the_trades_ref() -> None:
    w = _World()
    with w.client:
        with w.client.websocket_connect("/ws", subprotocols=JSON) as ws:
            assert _items(_subscribe(ws, {})) == []  # no tape yet: an empty kind-4 snapshot
            ws.send_json({"t": "unsub", "id": "u", "p": {"topics": [CH]}})
            assert _rx(ws)["t"] == "unsub_ok"
            assert (len(w.bars.released), w.upstream.consumers(KEY), _freed(w)) == (1, 0, True)
            ws.send_json({"t": "sub", "id": "s2", "p": {"topics": [CH]}})
            assert _rx(ws)["p"]["results"][0]["ok"] is True  # the socket's end releases this one
        assert (len(w.bars.released), w.upstream.consumers(KEY), _freed(w)) == (2, 0, True)
        w.call(w.upstream.sweep, w.now + 30.0)  # past the upstream grace
    assert w.trades.calls == [
        ("acquire", "ws:bars:time:5", SYM),
        ("release", "ws:bars:time:5", SYM),
    ]
