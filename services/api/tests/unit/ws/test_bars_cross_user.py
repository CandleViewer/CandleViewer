"""BR-23 (E12 STRIDE model; E12-T06, #399 R3 gap 2): two users on one shared bar series learn
nothing of each other through it. User B holds the shared series and two of its own on the same
symbol; user A joins the shared series and asks for one more, which the shared registry's
per-symbol cap refuses. A's `sub_ok`, the refusal in it and A's snapshot and deltas on the shared
series carry nothing of B's: no user id, session, connection, request id, private topic or
spec hash of B's, and A's own `history` and `include_delta`, never B's. Wired as `create_app`
wires `bars.*` (`test_bars_socket`), over the real `/ws` socket; the registry is the real
`SpecLeases` bookkeeping, with no builder behind it."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.bars.emit import EmitRouter
from candleviewer.bars.leases import SpecCaps, SpecLeases
from candleviewer.bars.models import BarSpec, BarUpdate
from candleviewer.bars.reader import BarTail
from candleviewer.bars.series_store import SeriesStore
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.bars_publish import BarsPublisher
from candleviewer.ws.bars_source import BarsSnapshotSource
from candleviewer.ws.gateway import make_ws_router
from candleviewer.ws.permissions import ConnectionRegistry, SubscriptionServices
from candleviewer.ws.revocation import RevocationHub
from candleviewer.ws.sequencing import SequencingHub
from candleviewer.ws.upstream import UpstreamRefs
from candleviewer.ws_wiring import default_snapshot_router
from tests.unit.ws._seq_support import Clock, principal
from tests.unit.ws.test_bars_source import CH, SPEC, SYM, _bar, _up
from tests.unit.ws.test_lifecycle_socket import JSON, ORIGIN
from tests.unit.ws.test_sequencing_socket import _rx

USER_A, USER_B = uuid.UUID(int=0xA11CE), uuid.UUID(int=0xB0B)
TOKENS = {"good-a": ("sess-a", USER_A), "good-b": ("sess-b", USER_B)}
#: B's own series on the shared series' symbol, held by B alone.
B_OWN = {"bars.BTCUSDT.time.15": BarSpec(kind="time", interval_ms=900_000),
         "bars.BTCUSDT.time.60": BarSpec(kind="time", interval_ms=3_600_000)}  # fmt: skip
#: A's extra series: new on a symbol at its cap of 3 (the shared one and B's two).
A_EXTRA = "bars.BTCUSDT.time.30"


class _Leases:
    """The `bars` service surface over the real lease bookkeeping: one registry for every user."""

    def __init__(self, caps: SpecCaps) -> None:
        self.leases = SpecLeases(caps)

    def check(self, spec: BarSpec, symbol: str, user: str | None = None) -> None:
        self.leases.check((symbol, spec.spec_hash), user)

    async def register(
        self, spec: BarSpec, symbol: str, consumer: str, user: str | None = None
    ) -> None:
        self.leases.acquire((symbol, spec.spec_hash), consumer, user)

    def release(self, spec_hash: str, symbol: str, consumer: str) -> None:
        self.leases.release((symbol, spec_hash), consumer, 0)


class _World:
    def __init__(self) -> None:
        rows = tuple((7, _bar(i)) for i in range(5))  # five stored bars on every series

        async def tail(symbol: str, spec: BarSpec, limit: int) -> BarTail:
            return BarTail(list(rows))

        hub = SequencingHub()
        self.bars = _Leases(SpecCaps(per_symbol=3))
        self.store = SeriesStore(tail, release_grace_s=0.0, clock=lambda: 0.0)
        publisher = BarsPublisher(hub, lambda _s: (1, 3), swap_reason="generation_swap")
        self.router = EmitRouter([self.store, publisher])
        source = BarsSnapshotSource(self.store, lambda _s: (1, 3), seed=publisher.note_generation)
        services = SubscriptionServices(
            upstream=UpstreamRefs(), bars=self.bars, series=self.store, sequencing=hub,
            snapshots=default_snapshot_router({"bars": source}), clock=lambda: 0.0,
        )  # fmt: skip

        async def resolve(uid: uuid.UUID) -> PrincipalSnapshot:
            return principal(user=uid)

        async def authenticate(token: str) -> tuple[str, uuid.UUID, datetime]:
            session, user = TOKENS[token]
            return session, user, datetime(2100, 1, 1, tzinfo=UTC)

        app = FastAPI()
        app.include_router(make_ws_router(
            authenticate=authenticate, registry=ConnectionRegistry(resolve, lambda: 1, services),
            revocation_hub=RevocationHub(), allowed_origins=frozenset({ORIGIN}), clock=Clock(),
            tick_s=0.005, backpressure=BackpressureConfig(),
        ))  # fmt: skip
        self.client = TestClient(app, headers={"origin": ORIGIN})

    def emit(self, spec: BarSpec, *updates: BarUpdate) -> None:
        portal = self.client.portal
        assert portal is not None  # set while the client context is open
        portal.call(self.router.emit, spec, updates, 7)


def _open(ws: Any, token: str) -> None:
    ws.send_json({"t": "hello", "id": "h"})
    assert _rx(ws)["t"] == "welcome"
    ws.send_json({"t": "auth", "id": "a", "p": {"access_token": token}})
    assert _rx(ws)["t"] == "auth_ok"


def _sub(ws: Any, rid: str, *entries: dict[str, Any]) -> list[dict[str, Any]]:
    """`sub_ok`'s results, then the `snap` of each topic it took, in order."""
    ws.send_json({"t": "sub", "id": rid, "p": {"topics": list(entries)}})
    ok = _rx(ws)
    assert (ok["t"], ok["id"]) == ("sub_ok", rid), ok
    results: list[dict[str, Any]] = ok["p"]["results"]
    return [ok, *(_rx(ws) for r in results if r["ok"])]


def test_bars_a_user_s_ack_refusal_and_frames_carry_nothing_of_another_user_s_series() -> None:
    w = _World()
    with (
        w.client,
        w.client.websocket_connect("/ws", subprotocols=JSON) as wb,
        w.client.websocket_connect("/ws", subprotocols=JSON) as wa,
    ):
        _open(wb, "good-b")
        b_ok, *b_snaps = _sub(
            wb, "s-bee-77",
            {"ch": CH, "opts": {"encoding": "structured", "history": 5, "include_delta": True}},
            *({"ch": ch, "opts": {"encoding": "structured"}} for ch in B_OWN),
        )  # fmt: skip
        assert [r["ok"] for r in b_ok["p"]["results"]] == [True, True, True]
        assert len(b_snaps) == 3 and len(b_snaps[0]["p"]["bars"]) == 5
        _open(wa, "good-a")
        a_ok, a_snap = _sub(
            wa, "s-a",
            {"ch": CH, "opts": {"encoding": "structured", "history": 2}},
            {"ch": A_EXTRA, "opts": {"encoding": "structured"}},
        )  # fmt: skip
        joined, refused = a_ok["p"]["results"]
        assert joined["ok"]  # sub ids are per connection (`s_01`): B's says nothing of B's
        assert (refused["ok"], refused["error"]["code"]) == (False, "subscription_limit")
        # one registry series, two holders: A joined B's, and B's own two are B's alone
        holders = w.bars.leases._series[(SYM, SPEC.spec_hash)].holders
        assert sorted(str(u) for u in holders.values()) == sorted([str(USER_A), str(USER_B)])
        b_conns = {c.split("/")[0] for c, u in holders.items() if u == str(USER_B)}
        w.emit(B_OWN["bars.BTCUSDT.time.15"], _up("open", 5))  # B's own series: never A's
        w.emit(SPEC, _up("open", 5))  # the shared series
        a_delta, b_delta = _rx(wa), _rx(wb)
        assert (a_delta["t"], a_delta["ch"], b_delta["ch"]) == ("d", CH, "bars.BTCUSDT.time.15")
        assert _rx(wb)["ch"] == CH  # B gets the shared series' delta too, after its own

    # A's view is A's own: its history (2 of the 5 stored bars) and its include_delta (off),
    # whatever B asked of the same series
    assert len(a_snap["p"]["bars"]) == 2 and a_snap["meta"]["include_delta"] is False
    assert a_delta["meta"] == {"include_delta": False}
    b_marks = {str(USER_B), "sess-b", "s-bee-77", *B_OWN}
    b_marks |= {s.spec_hash for s in B_OWN.values()}
    b_marks |= b_conns  # B's connection id, the head of each of B's consumer keys
    a_text = json.dumps([a_ok, a_snap, a_delta])
    assert [m for m in sorted(b_marks) if m in a_text] == []
