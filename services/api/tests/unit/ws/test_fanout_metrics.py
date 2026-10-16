"""E17-T06: the WS fan-out series `cv_ws_fanout_seconds` (budget #6, `20-architecture.md` section
12.1), sampled one data frame of a subscription in `SAMPLE_EVERY`.

The hub stamps the data frame whose `s` is a multiple of `SAMPLE_EVERY`, and no other: the rest
read no clock and are queued bare. The writer observes a stamped frame with that weight once
`send_text` has returned. The span runs through the real `/ws` router, hub, queue and writer, on a
fake clock that both ends of the span read; no test sleeps. `_on_loop` runs a function on the
app's loop, where nothing else runs until it returns, so the writer cannot interleave with it. A
`pong` is a barrier: the single writer finished every frame queued before it, observation
included.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from prometheus_client import REGISTRY

from candleviewer.observability.metrics_catalogue import CATALOGUE, live_specs
from candleviewer.ws.metrics import CV_WS_NAMES, SAMPLE_EVERY, SAMPLE_MASK, cv_ws_fanout_seconds
from candleviewer.ws.pacing import Pacer
from tests.unit.ws import test_sequencing_socket as sequencing_socket
from tests.unit.ws._seq_support import ACC_A, Book, Clock, Conn, Source
from tests.unit.ws.test_lifecycle_socket import JSON, _closed, _recv
from tests.unit.ws.test_sequencing import _footprint_body
from tests.unit.ws.test_sequencing_socket import _open, _rx, _World

FANOUT = "cv_ws_fanout_seconds"
CH = "book.BTCUSDT.50"
BODY = {"symbol": "BTCUSDT", "bids": [["100.0", "1.500"]], "asks": []}
ENTRY = {"ch": CH, "opts": {"encoding": "structured"}}
N = SAMPLE_EVERY


def _obs() -> tuple[float, float]:
    """(observation count, sum) of the fan-out histogram: the count is weighted."""
    count = REGISTRY.get_sample_value(f"{FANOUT}_count")
    total = REGISTRY.get_sample_value(f"{FANOUT}_sum")
    assert count is not None and total is not None
    return count, total


def _on_loop(w: _World, fn: Callable[[], Any]) -> Any:
    assert w.client.portal is not None
    return w.client.portal.call(fn)


def _barrier(ws: Any) -> None:
    ws.send_json({"t": "ping", "id": "barrier"})
    assert _rx(ws)["t"] == "pong"


def _sub(ws: Any) -> None:
    """Subscribe: `sub_ok`, then the subscription's first frame, a `snap` with `s` 1."""
    ws.send_json({"t": "sub", "id": "s1", "p": {"topics": [{"ch": CH, "opts": {}}]}})
    assert _rx(ws)["t"] == "sub_ok"
    snap = _rx(ws)
    assert (snap["t"], snap["s"]) == ("snap", 1)


def _publish(w: _World, count: int, taken: float = 0.0, sent: float = 0.0) -> None:
    """`count` deltas through the hub in one burst on the loop: the hub takes them at `taken` on
    the fake clock, and the writer reads `sent` once the socket has them."""

    def burst() -> None:
        w.clock.now = taken
        for _ in range(count):
            assert w.hub.publish(CH, BODY) == 1
        w.clock.now = sent

    _on_loop(w, burst)


def _read(ws: Any, first_s: int, count: int) -> list[dict[str, Any]]:
    frames = [_rx(ws) for _ in range(count)]
    assert [(f["t"], f["s"]) for f in frames] == [("d", s) for s in range(first_s, first_s + count)]
    return frames


class _CountingClock(Clock):
    def __init__(self) -> None:
        super().__init__()
        self.reads = 0

    def __call__(self) -> float:
        self.reads += 1
        return self.now


# -- registration: the contract with dashboards and alerts -----------------------------------


def test_series_is_live_catalogued_registered_once_re_exported_and_unlabelled() -> None:
    spec = next(s for s in live_specs() if s.name == FANOUT)
    assert spec.exported and FANOUT in CV_WS_NAMES
    assert [f.name for f in REGISTRY.collect()].count(FANOUT) == 1
    assert spec.labels == () == cv_ws_fanout_seconds.labelnames  # no symbol, user, ch
    assert cv_ws_fanout_seconds.buckets == spec.buckets
    assert "ws_fanout_latency_seconds" not in {s.name for s in CATALOGUE}  # renamed, not added
    sampled = f"sampled 1 in {SAMPLE_EVERY} (weighted)"
    documentation = next(f.documentation for f in REGISTRY.collect() if f.name == FANOUT)
    assert sampled in documentation and spec.help == documentation  # one text, as catalogued
    assert spec.buckets[0] < 1e-3  # a p95 under 1 ms is not flat
    assert SAMPLE_EVERY == 32 and SAMPLE_MASK == SAMPLE_EVERY - 1  # a power of two: `n & mask`


# -- the fan-out span: hub takes a data frame -> the writer handed it to the socket -------------


def test_fanout_counts_the_weight_for_each_sampled_delta_and_times_it_hub_to_socket() -> None:
    w = _World()
    with w.client, w.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _open(ws)
        _sub(ws)
        _barrier(ws)
        n0, t0 = _obs()
        _publish(w, 2 * N - 1, taken=10.0, sent=10.5)  # `s` 2 to 2N: two sampled frames
        frames = _read(ws, 2, 2 * N - 1)
        _barrier(ws)
        n1, t1 = _obs()
    assert n1 - n0 == 2 * N  # `N` times the sampled frames, not the frames
    assert t1 - t0 == pytest.approx(2 * N * 0.5)  # the clock read at the socket minus the hub's
    assert set(frames[N - 2]) == {
        "t",
        "ch",
        "s",
        "ts",
        "e",
        "p",
    }  # the stamp never reaches the wire


def test_fanout_observes_a_sampled_snapshot_but_no_control_frame() -> None:
    w = _World()
    with w.client, w.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _open(ws)
        _barrier(ws)
        n0, _ = _obs()
        _sub(ws)  # `sub_ok` is control; the `snap` after it is data, but only the 1st frame
        _barrier(ws)  # a `pong`
        n1, _ = _obs()
        _publish(w, N - 2)
        _read(ws, 2, N - 2)
        _on_loop(w, lambda: w.hub.resnapshot(lambda sub: True, "upstream_desync"))
        resync = _rx(ws)  # the sampled frame, this time a `snap`
        assert (resync["t"], resync["s"]) == ("snap", N)
        _barrier(ws)
        n2, _ = _obs()
        ws.send_json({"t": "unsub", "id": "u1", "p": {"topics": [CH]}})
        assert _rx(ws)["t"] == "unsub_ok"
        _barrier(ws)
        n3, _ = _obs()
    assert (n1 - n0, n2 - n1, n3 - n2) == (0, N, 0)


def test_fanout_ignores_a_frame_the_writer_drops_when_the_identity_ends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A token an hour out: the fake monotonic clock passes its expiry at 3600 s.
    monkeypatch.setattr(sequencing_socket, "_EXPIRES", datetime.now(UTC) + timedelta(hours=1))
    w = _World()
    with w.client, w.client.websocket_connect("/ws", subprotocols=JSON) as ws:
        _open(ws)
        _sub(ws)
        _publish(w, N - 2)
        _read(ws, 2, N - 2)
        _barrier(ws)
        before = _obs()

        def publish_then_expire() -> None:
            assert w.hub.publish(CH, BODY) == 1  # the sampled frame, queued with its stamp ...
            w.clock.now = 4000.0  # ... the token expires before the writer sends it: sealed

        _on_loop(w, publish_then_expire)
        assert _recv(ws)["t"] == "bye"
        _closed(ws)
    assert _obs() == before


# -- the stamp itself: where the hub takes it ------------------------------------------------


def _stamped(conn: Conn) -> dict[tuple[str, int], float | None]:
    """Route what the emitter hands over WITH a receipt time through a recorder: `(ch, s)` of the
    frame -> its time. An unsampled frame must not arrive here at all."""
    stamps: dict[tuple[str, int], float | None] = {}

    def push_data(frame: dict[str, Any], received: float | None) -> None:
        stamps[(frame["ch"], frame["s"])] = received
        conn.push(frame)

    conn.emitter.push_data = push_data
    return stamps


def _book_conn(clock: Clock, source: Source) -> Conn:
    source.books["BTCUSDT"] = Book("BTCUSDT")
    return Conn(source, ACC_A, clock=clock)


def _bid(price: str) -> dict[str, Any]:
    return {"symbol": "BTCUSDT", "depth": 50, "bids": [[price, "1"]], "asks": []}


def test_the_hub_stamps_every_sampled_frame_of_a_subscription_and_reads_no_other_clock() -> None:
    clock = _CountingClock()
    conn = _book_conn(clock, Source())
    stamps = _stamped(conn)
    _, sub = conn.sub(ENTRY)  # the snapshot is `s` 1
    assert stamps == {} and clock.reads == 0  # not sampled: no stamp, no clock read
    conn.take()
    for i in range(3 * N):  # `s` 2 to 3N + 1: three sampled frames
        clock.now = 100.0 + i
        assert conn.emitter.delta(sub, _bid(str(100 + i)))
    assert [f["s"] for f in conn.take()] == list(range(2, 3 * N + 2))  # every frame left
    assert stamps == {(CH, s): 100.0 + s - 2 for s in (N, 2 * N, 3 * N)}
    assert clock.reads == 3  # one read for each stamp, none for the other frames


def test_each_subscription_counts_its_own_frames() -> None:
    """The cycle is the subscription's `s`, so frames of another subscription cannot shift it."""
    conn = _book_conn(_CountingClock(), Source())
    stamps = _stamped(conn)
    _, books = conn.sub(ENTRY)
    _, other = conn.sub({"ch": "book.BTCUSDT.1", "opts": {"encoding": "structured"}})
    for _ in range(N - 1):  # `s` 2 to `N` of `books`, and of `other`
        assert conn.emitter.delta(books, _bid("100"))
        assert conn.emitter.delta(other, _bid("100"))
    assert set(stamps) == {(CH, N), ("book.BTCUSDT.1", N)}


def test_a_snapshot_is_stamped_before_it_is_built() -> None:
    class SlowSource(Source):
        def build(self, sub: Any) -> Any:
            clock.now += 0.3  # the build takes 300 ms
            return super().build(sub)

    clock = _CountingClock()
    conn = _book_conn(clock, SlowSource())
    stamps = _stamped(conn)
    clock.now = 100.0
    _, sub = conn.authz.admit(ENTRY)
    assert sub is not None
    sub.seq = N - 1  # the snapshot is the subscription's `N`th frame: sampled
    conn.emitter.flush_pending([sub])
    assert stamps == {(CH, N): 100.0} and clock.now == pytest.approx(100.3) and clock.reads == 1


def test_a_sampled_chunked_snapshot_is_stamped_on_the_chunk_that_carries_s_only() -> None:
    src, ch = Source(), "footprint.BTCUSDT.time.1"
    src.bodies["footprint"] = _footprint_body(cells_per_bar=50, bars=40)
    conn = Conn(src, ACC_A, clock=_CountingClock(), max_frame_bytes=20_000)
    stamps = _stamped(conn)
    _, sub = conn.authz.admit({"ch": ch, "opts": {"encoding": "structured"}})
    assert sub is not None
    sub.seq = N - 1  # the snapshot is the subscription's `N`th frame: sampled
    conn.emitter.flush_pending([sub])
    assert len(conn.take()) > 1 and set(stamps) == {(ch, N)}  # one stamp, not one per chunk


def test_a_paced_frame_is_timed_from_its_release_not_its_sources() -> None:
    """Budget #6 is the fan-out add-on: a throttle window's deliberate hold (50-250 ms, §6.1)
    is configuration, not fan-out latency, so a coalesced frame is timed from its release."""
    clock = Clock()
    conn = _book_conn(clock, Source())
    stamps = _stamped(conn)
    clock.now = 100.0
    pacer = Pacer(conn.emitter)
    _, sub = conn.sub(ENTRY)
    conn.take()
    sub.seq = N - 2  # the first update below is just before a sampled `s`: the release
    pacer.offer(sub, _bid("100"))  # the first update after a quiet window leaves at once
    for at, price in ((100.01, "101"), (100.03, "102")):
        clock.now = at
        pacer.offer(sub, _bid(price))
    clock.now = 100.05
    assert pacer.tick(100.05) == 1
    assert conn.take()[-1]["p"]["coalesced_count"] == 2
    assert stamps == {(CH, N): 100.05}  # the release, not a source (100.01 or 100.03)
