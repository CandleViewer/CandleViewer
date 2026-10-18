"""E17-T03 (#412), with `CV_WS_BACKPRESSURE_ENABLED` on: the `connection_quality` notice
(`23-ws-protocol.md` §8.3) and the RTT probe (§9.1) through a socket, under both wires (#3150's
`wire` fixture). `Client.recv` validates every frame against the §13-§15 schemas, so the notice is
checked against §15.9's `SystemUpdate` and the probe against the heartbeat payload as they arrive.
"""

from __future__ import annotations

from typing import Any

from candleviewer.ws.backpressure_config import BackpressureConfig
from tests.contract.ws._harness import Client, World, connect, entry


def _answer(c: Client, probe: str) -> None:
    """Reply to the probe, fenced by a `ping` of the client's own: once its `pong` is back, the
    server has the reply, so the fake clock may move on."""
    c.send({"t": "pong", "id": probe})
    c.send({"t": "ping", "id": "fence"})
    assert c.next_of("pong")["id"] == "fence"


def _tick(w: World, c: Client, now: float) -> tuple[list[dict[str, Any]], str]:
    """Move the fake clock to the classification at `now`: what was sent before its probe
    `ping`, and the probe's id."""
    w.clock.now = now
    before: list[dict[str, Any]] = []
    while (frame := c.recv(skip_ping=False))["t"] != "ping":
        before.append(frame)
    return before, frame["id"]


def test_connection_quality_validates_against_15_9() -> None:
    """A client that stops answering the probe reads `saturated` at the first classification after
    the probe's age passes 500 ms (D12), and the notice names the multiplier and the degraded
    topics; once it answers again the class recovers after two healthy samples, announced as
    well. Both notices and every probe are schema-valid."""
    w = World(backpressure=BackpressureConfig())
    with connect(w) as c:
        c.sub(entry("heatmap", ("symbol",)), entry("profile", ("symbol", "profile_kind")))
        c.drain(2)  # the two snapshots
        before, first = _tick(w, c, 1.0)  # healthy, no sample yet; left unanswered
        assert before == []
        w.clock.now = 2.0  # 1 s old: `saturated`, and no new probe while it is outstanding
        saturated = c.next_of("d")
        _answer(c, first)  # late: a 1 000 ms sample, still `saturated`
        for now in (3.0, 4.0):  # then one 0 ms sample: no change yet
            before, probe = _tick(w, c, now)
            assert before == []
            _answer(c, probe)
        [healthy], _ = _tick(w, c, 5.0)  # the second
    degraded = ["heatmap.BTCUSDT", "profile.BTCUSDT.volume"]
    assert (saturated["ch"], saturated["p"]) == (
        "system",
        {
            "kind": "connection_quality",
            "class": "saturated",
            "queue_pct": 0,
            "rtt_ms": 1000,
            "applied": {
                "throttle_multiplier": 4,
                "forced_coalesce": True,
                "degraded_topics": degraded,
            },
        },
    )
    assert (healthy["p"]["class"], healthy["p"]["applied"]) == (
        "healthy",
        {"throttle_multiplier": 1, "forced_coalesce": False, "degraded_topics": []},
    )
