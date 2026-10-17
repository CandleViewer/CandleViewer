"""E17-Q01 conformance for §16.1 S14 (23-ws-protocol.md §3.1; E17-T06 #571 slice D2): `sp` rides
only a sampled `snap` or `d` that carries `s`, drawn fresh for each, and only while latency
telemetry is on (the world's `span_ids`, which `create_app` sets from `CV_TELEMETRY_ENABLED`).
Through the real router on both subprotocols; every frame the client receives is validated against
§13, whose envelope admits `sp` only on such a frame. Chunks and sizing: `test_span_id.py` (unit).
"""

from __future__ import annotations

from typing import Any

from candleviewer.ws.metrics import SAMPLE_EVERY
from candleviewer.ws.sequencing import new_span_id
from tests.contract.ws._harness import SYM, World, connect, publish
from tests.contract.ws._support import SAMPLES

N = SAMPLE_EVERY
CH = f"book.{SYM}.50"


def _session(w: World) -> list[dict[str, Any]]:
    """`sub` (its `snap` is `s` 1), deltas `s` 2 to 2N - 1, a client resync (its `snap` is `s`
    2N), N + 1 `system` notices (their `s` passes N) and a ping: every frame received, in order."""
    with connect(w) as c:
        c.sub({"ch": CH, "opts": {"encoding": "binary"}})
        c.next_of("snap")
        for _ in range(2 * N - 2):
            publish(w, "book", CH, "binary")
        c.drain(2 * N - 2)
        c.send({"t": "resync", "id": "r", "ch": CH, "p": {"reason": "manual"}})
        c.next_of("snap")
        for _ in range(N + 1):
            w.call(w.gateway.broadcast_system, dict(SAMPLES["system"][1]))
        c.drain(N + 1)
        c.send({"t": "ping", "id": "p"})
        c.next_of("pong")
        return c.seen


def test_s14_sp_rides_only_the_sampled_data_frames_and_is_fresh_for_each() -> None:
    w = World()
    w.registry.services.span_ids = new_span_id
    frames = _session(w)
    sampled = [f for f in frames if "sp" in f]
    assert [(f["t"], f["ch"], f["s"]) for f in sampled] == [("d", CH, N), ("snap", CH, 2 * N)]
    assert len({f["sp"] for f in sampled}) == len(sampled)
    assert max(f["s"] for f in frames if f.get("ch") == "system") > N  # a sampled number, no `sp`


def test_s14_no_frame_carries_sp_while_latency_telemetry_is_off() -> None:
    frames = _session(World())
    assert [f for f in frames if "sp" in f] == []
    assert {(f["t"], f["s"]) for f in frames if f.get("ch") == CH} >= {("d", N), ("snap", 2 * N)}
