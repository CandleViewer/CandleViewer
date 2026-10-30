"""The scripted WS session of the E17-T06 (#571) metrics tests, and the scrape it is read through.

Five connections on the real `/ws` router, on the caller's loop behind `_Wire` (the rig of
`tests/unit/ws/test_pipeline_outbound.py`): no thread, no sleep, a fake clock, every wait bounded.
Every connection runs with the backpressure flag on (one connection per step that needs its own
queue, below); the last is a pass on MessagePack with a binary book, for the series only that codec
moves (#2409: it was the flag-off wiring's pass).

What a scrape sees is what the tests read: `export_ws_metrics` and `export_cvwb_metrics` on a
fresh registry (the ones `create_app` serves), rendered by `generate_latest` and parsed back from
the exposition text. The collectors are process-global, so every count is a delta between a scrape
before the session and one after it; test order never matters. The script is deterministic, so
the deltas are exact.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, Final, NamedTuple

import msgpack
from prometheus_client.parser import text_string_to_metric_families

from candleviewer.auth.generated_permissions import Permission
from candleviewer.observability.context import spawn
from candleviewer.observability.metrics import CollectorRegistry, generate_latest
from candleviewer.ws.backpressure_config import BackpressureConfig
from candleviewer.ws.metrics import SAMPLE_EVERY, export_cvwb_metrics, export_ws_metrics
from candleviewer.ws.sequencing import SnapshotBody
from candleviewer.ws.upstream import cv_ws_upstream_consumers_in_use  # noqa: F401  (registers it)
from tests.unit.ws._seq_support import ACC_A, USER
from tests.unit.ws.test_lifecycle_socket import BASE_MS
from tests.unit.ws.test_pipeline_outbound import (
    _BOOK,
    _DEADLINE_S,
    _JSON,
    _MSGPACK,
    _no_sleep,
    _Rig,
    _Wire,
)

_TRADES = "trades.BTCUSDT"
_BODY: Final = {"symbol": "BTCUSDT", "depth": 50, "asks": []}
#: Frames the sampler stamps: one in `SAMPLE_EVERY` per subscription, weighted by it.
_DELTAS = 2 * SAMPLE_EVERY

Key = tuple[str, frozenset[tuple[str, str]]]


class Scrape(dict[Key, float]):
    """One scrape: (sample name, labels without `env`) -> value."""

    def value(self, name: str, **labels: str) -> float:
        return self.get((name, frozenset(labels.items())), 0.0)

    def names(self) -> set[str]:
        return {name for name, _ in self}


def scrape() -> Scrape:
    """The WS series as `/metrics` serves them: the exporters on a fresh registry, rendered as
    the exposition text and parsed back."""
    registry = CollectorRegistry()
    export_ws_metrics(registry, env="test")
    export_cvwb_metrics(registry, env="test")
    out = Scrape()
    for family in text_string_to_metric_families(generate_latest(registry).decode()):
        for s in family.samples:
            labels = frozenset((k, v) for k, v in s.labels.items() if k != "env")
            out[(s.name, labels)] = s.value
    return out


class Run(NamedTuple):
    before: Scrape
    mid: Scrape  # connection 1 open, subscribed to three topics
    after: Scrape

    def delta(self, name: str, **labels: str) -> float:
        return self.after.value(name, **labels) - self.before.value(name, **labels)

    def up(self, name: str, **labels: str) -> float:
        """A gauge while connection 1 was open, against before."""
        return self.mid.value(name, **labels) - self.before.value(name, **labels)


def _delta_of(book: int, **extra: Any) -> dict[str, Any]:
    return {**_BODY, "bids": [[f"{100 + book}.0", "1.000"]], **extra}


async def _ticks(sock: _Wire, rig: _Rig, n: int, publish: Callable[[int], Any]) -> None:
    """`n` deltas, one at a time and 1.5 s apart on the fake clock, so each leaves its throttle
    window alone and the classification (1 s) runs between them; the frame is awaited."""
    for i in range(n):
        rig.clock.now += 1.5
        publish(i)
        await sock.next()


async def _flag_on_connection() -> Scrape:
    """Connection 1: hello, auth, three subscribes (public book, public trades, private orders),
    64 deltas (two sampled), a client resync, a merged window, an overflow that the ladder drops
    and re-snapshots (a parked writer, a budget of 8 frames), an unsub, a planned shutdown."""
    rig = _Rig(BackpressureConfig(max_frames=8, classify_interval_ms=1000))
    rig.source.bodies["trades"] = SnapshotBody({"symbol": "BTCUSDT", "trades": []})
    sock = _Wire(_JSON)
    async with asyncio.timeout(_DEADLINE_S):
        handler, conn = await rig.open(sock)
        await rig.sub(sock)
        await rig.sub(sock, _TRADES)
        await rig.sub(sock, "orders")
        mid = scrape()
        await _ticks(sock, rig, _DELTAS, lambda i: rig.sequencing.publish(_BOOK, _delta_of(i)))
        sock.feed({"t": "resync", "id": "r", "ch": _BOOK, "p": {"reason": "manual"}})
        assert [f["t"] for f in await sock.next()] == ["snap"]
        # Three book deltas inside one throttle window merge into one frame.
        for i in range(3):
            rig.sequencing.publish(_BOOK, _delta_of(i))
        rig.clock.now += 1.0
        assert [f["t"] for f in await sock.next()] == ["d"]
        # Overflow: park the writer, fill the 8-frame budget past it; the ladder drops the book's
        # queued deltas (step 1), then queues its `backpressure` snapshot once the queue is below
        # half (step 2). Nothing closes.
        sock.hold()
        rig.hub.broadcast_system({"kind": "held"})
        await sock.parked.wait()
        for _ in range(4):
            rig.hub.broadcast_system({"kind": "tick"})
        for i in range(5):
            rig.book_delta(i)
        sock.release()
        assert [f["t"] for f in await sock.next(6)] == ["d"] * 5 + ["snap"]
        # One more classification, answered by the wire's `pong`.
        rig.clock.now += 1.5
        rig.sequencing.publish(_BOOK, _delta_of(0))
        await sock.next()
        sock.feed({"t": "unsub", "id": "u", "p": {"topics": [_TRADES]}})
        assert [f["t"] for f in await sock.next()] == ["unsub_ok"]
        await rig.hub.shutdown(grace_ms=0, sleep=_no_sleep)
        await handler
    assert conn.closing and sock.pings  # the RTT probe pinged and the wire answered
    return mid


async def _slow_consumer_connection() -> None:
    """Connection 2: nine frames in one turn against a budget of eight (§8.4 step 3)."""
    rig, sock = _Rig(BackpressureConfig(max_frames=8)), _Wire(_JSON)
    async with asyncio.timeout(_DEADLINE_S):
        handler, _ = await rig.open(sock)
        for i in range(9):
            rig.hub.broadcast_system({"kind": "tick", "n": i})
        (bye,) = await sock.next()
        await handler
    assert bye["p"]["reason"] == "slow_consumer"


async def _withdrawn_connection() -> None:
    """Connection 3: the permission of `orders` is removed while frames of it are queued behind a
    parked writer: they are dropped (`withdrawn`), the topic is revoked (`permission_revoked`)."""
    rig, sock = _Rig(BackpressureConfig()), _Wire(_JSON)
    async with asyncio.timeout(_DEADLINE_S):
        handler, _ = await rig.open(sock)
        await rig.sub(sock)
        await rig.sub(sock, "orders")
        sock.hold()
        rig.hub.broadcast_system({"kind": "held"})
        await sock.parked.wait()
        for i in range(3):
            rig.sequencing.publish("orders", {"orders": [], "n": i}, account=ACC_A)
        rig.perms = rig.perms - {Permission.ORDERS_READ}
        await rig.registry.roles_changed(USER)
        sock.release()
        sent: list[dict[str, Any]] = []
        while not any(f["t"] == "revoked" for f in sent):
            sent += await sock.next()
        assert [f["t"] for f in sent] == [
            "d",
            "permission_change",
            "revoked",
        ]  # the held `system` frame
        sock.inbound.put_nowait({"type": "websocket.disconnect", "code": 1000})
        await handler


async def _failed_auth_connection() -> None:
    """Connection 4: an `auth` frame with no token."""
    rig, sock = _Rig(BackpressureConfig()), _Wire(_JSON)
    async with asyncio.timeout(_DEADLINE_S):
        handler = spawn(rig.endpoint(sock), name="ws-metrics-failed-auth")
        sock.feed({"t": "hello", "id": "h", "p": {"clock_ms": BASE_MS}})
        assert [f["t"] for f in await sock.next()] == ["welcome"]
        sock.feed({"t": "auth", "id": "a", "p": {"access_token": ""}})
        (failed,) = await sock.next()
        sock.inbound.put_nowait({"type": "websocket.disconnect", "code": 1000})
        await handler
    assert (failed["t"], failed["p"]["code"]) == ("err", "auth_failed")


async def _msgpack_connection() -> None:
    """Connection 5, on `cv.v1.msgpack`: the pipeline encodes and observes its stamped frame on
    that codec; a binary book snapshot feeds the CVWB series. Each delta is published 250 ms after
    the last, past its book window, so it leaves alone; no classification is due in the session
    (the interval is a minute), so it adds no probe and no depth sample."""
    rig, sock = _Rig(BackpressureConfig(classify_interval_ms=60_000)), _Wire(_MSGPACK)
    async with asyncio.timeout(_DEADLINE_S):
        handler, _ = await rig.open(sock)
        sock.feed({"t": "sub", "id": "s", "p": {"topics": [{"ch": _BOOK, "opts": {}}]}})
        await sock.next(2)
        for i in range(SAMPLE_EVERY):
            rig.clock.now += 0.25
            rig.sequencing.publish(_BOOK, _delta_of(i))
            await sock.next()
        await rig.hub.shutdown(grace_ms=0, sleep=_no_sleep)
        await handler
    assert sock.raw and all(kind == "bytes" for kind, _ in sock.raw)
    assert msgpack.unpackb(sock.raw[-1][1])["t"] == "bye"


async def run_session() -> Run:
    """The scripted session: a scrape before, one while connection 1 is open, and one after every
    connection has closed."""
    before = scrape()
    mid = await _flag_on_connection()
    await _slow_consumer_connection()
    await _withdrawn_connection()
    await _failed_auth_connection()
    await _msgpack_connection()
    return Run(before, mid, scrape())


def run_session_once() -> Run:
    """`run_session` on its own loop, for a module-scoped fixture (every connection of the script
    is closed and awaited before it returns, so nothing outlives the loop)."""
    return asyncio.run(run_session())
