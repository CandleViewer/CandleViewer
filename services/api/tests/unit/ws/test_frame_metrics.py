"""E17-T06: frame encode seconds and bytes per kind (`cv_ws_frame_encode_seconds{kind}`,
`cv_ws_frame_bytes{kind}`; `20-architecture.md` section 12.1), sampled one frame in `SAMPLE_EVERY`.

`kind` is the six CVWB body kinds plus `json` and `msgpack`, a data frame as its connection's codec
sent it (23 section 2.2). The hub stamps one data frame of a subscription in `SAMPLE_EVERY` (its
`s` is a multiple of it): the encoder times and sizes that delta, and the writer the stamped frame
as the connection's codec encoded it (text on `cv.v1.json`, bytes on `cv.v1.msgpack`), each with
that weight; every other frame reads no timer. A snapshot chunk is observed exactly (weight 1). A
`perf_counter` stand-in counts the reads and makes every duration a known number. The encode
precedes the send, so a frame the client has received is already counted.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any

import msgpack
import pytest
from prometheus_client import REGISTRY

from candleviewer.observability.metrics_catalogue import CATALOGUE, live_specs
from candleviewer.ws import binary, cvwb_vectors, gateway
from candleviewer.ws._generated.cvwb_layout import KINDS
from candleviewer.ws.binary import BOOK_DELTA, Frame, FrameEncodeError
from candleviewer.ws.metrics import (
    CV_WS_NAMES,
    FRAME_KINDS,
    JSON_KIND,
    MSGPACK_KIND,
    SAMPLE_EVERY,
    FastHistogram,
    cv_ws_frame_bytes,
    cv_ws_frame_encode_seconds,
)
from tests.unit.ws._seq_support import ACC_A, Book, Conn, Source
from tests.unit.ws.test_lifecycle_socket import JSON, MSGPACK, _send
from tests.unit.ws.test_sequencing import _footprint_body
from tests.unit.ws.test_sequencing_socket import _World

ENCODE, BYTES = "cv_ws_frame_encode_seconds", "cv_ws_frame_bytes"
_SERIES: dict[str, FastHistogram] = {ENCODE: cv_ws_frame_encode_seconds, BYTES: cv_ws_frame_bytes}
SAMPLED = f"sampled 1 in {SAMPLE_EVERY} (weighted)"
CH = "book.BTCUSDT.50"
BODY = {"symbol": "BTCUSDT", "bids": [["100.0", "1.500"]], "asks": []}


class _Ticks:
    """A `perf_counter` stand-in: each read is `step` later than the one before, and counted."""

    def __init__(self, step: float) -> None:
        self.step, self.now, self.reads = step, 0.0, 0

    def __call__(self) -> float:
        self.reads += 1
        self.now += self.step
        return self.now


def _obs(name: str, **labels: str) -> tuple[float, float]:
    """(observation count, sum) of one histogram series: the count is weighted."""
    count = REGISTRY.get_sample_value(f"{name}_count", labels)
    total = REGISTRY.get_sample_value(f"{name}_sum", labels)
    assert count is not None and total is not None, (name, labels)
    return count, total


def _cost(kind: str) -> tuple[tuple[float, float], tuple[float, float]]:
    return _obs(ENCODE, kind=kind), _obs(BYTES, kind=kind)


def _encoded(kind: str) -> tuple[float, float]:
    """(frames, bytes) the encoder counted for a CVWB kind: every frame, sampled or not."""
    frames = REGISTRY.get_sample_value("cvwb_frames_encoded_total", {"kind": kind})
    nbytes = REGISTRY.get_sample_value("cvwb_bytes_encoded_total", {"kind": kind})
    assert frames is not None and nbytes is not None
    return frames, nbytes


def _all() -> dict[str, tuple[tuple[float, float], tuple[float, float]]]:
    return {k: _cost(k) for k in FRAME_KINDS}


def _writer() -> dict[str, tuple[tuple[float, float], tuple[float, float]]]:
    """The two kinds the writer observes. The CVWB kinds are the encoder's: a socket test also moves
    `book_snapshot`, since the snapshot chunk the hub renders is observed exactly."""
    return {k: _cost(k) for k in (JSON_KIND, MSGPACK_KIND)}


def _conn(source: Source | None = None) -> Conn:
    src = source or Source()
    src.books["BTCUSDT"] = Book("BTCUSDT")
    return Conn(src, ACC_A)


def _vector(kind: str) -> Frame:
    return next(f for _, f in cvwb_vectors.vector_frames() if KINDS[f.body_kind].name == kind)


def test_series_are_live_catalogued_registered_once_and_re_exported() -> None:
    families = {f.name: f for f in REGISTRY.collect()}
    assert [f.name for f in REGISTRY.collect()].count(ENCODE) == 1
    for name, metric in _SERIES.items():
        spec = next(s for s in live_specs() if s.name == name)
        assert spec.exported and name in CV_WS_NAMES, name
        assert [f.name for f in REGISTRY.collect()].count(name) == 1, name
        assert metric.labelnames == spec.labels and metric.buckets == spec.buckets, name
        assert spec.help == families[name].documentation and SAMPLED in spec.help, name
        assert JSON_KIND in spec.help and MSGPACK_KIND in spec.help, name  # it lists the kinds


def test_kind_is_the_six_body_kinds_plus_json_and_msgpack_and_nothing_identifies_a_series() -> None:
    assert set(FRAME_KINDS) == {k.name for k in KINDS.values()} | {JSON_KIND, MSGPACK_KIND}
    assert len(FRAME_KINDS) == 8
    assert [s.max_series for s in CATALOGUE if s.name in _SERIES] == [8, 8]
    identifying = {"ch", "channel", "symbol", "topic", "user", "user_id", "connection_id", "sub_id"}
    for name, metric in _SERIES.items():
        assert not set(metric.labelnames) & identifying, name
        served = {s.labels["kind"] for f in REGISTRY.collect() if f.name == name for s in f.samples}
        assert served == set(FRAME_KINDS), name  # every child pre-bound at import, none added later
        with pytest.raises(KeyError):
            metric.labels("ticker")  # a closed set: no child is ever added


def test_a_weighted_encode_is_observed_with_its_weight_under_its_own_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frames = cvwb_vectors.vector_frames()
    assert {KINDS[f.body_kind].name for _, f in frames} == set(FRAME_KINDS) - {
        JSON_KIND,
        MSGPACK_KIND,
    }
    for name, frame in frames:
        ticks = _Ticks(0.25)  # the encoder's one `perf_counter` pair: exactly 0.25 s apart
        monkeypatch.setattr(binary, "perf_counter", ticks)
        before = _all()
        size = len(binary.encode(frame, SAMPLE_EVERY))
        assert ticks.reads == 2, name
        for kind in FRAME_KINDS:
            (n0, t0), (c0, b0) = before[kind]
            (n1, t1), (c1, b1) = _cost(kind)
            if kind == KINDS[frame.body_kind].name:
                weight = SAMPLE_EVERY
                assert (n1 - n0, c1 - c0, b1 - b0) == (weight, weight, weight * size), name
                assert t1 - t0 == pytest.approx(weight * 0.25), name
            else:
                assert (n1, t1, c1, b1) == (n0, t0, c0, b0), (name, kind)


def test_an_unweighted_encode_reads_no_timer_and_the_frame_counters_still_count_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame, ticks = _vector("book_delta"), _Ticks(0.25)
    monkeypatch.setattr(binary, "perf_counter", ticks)
    before, counted = _all(), _encoded("book_delta")
    size = len(binary.encode(frame))
    assert ticks.reads == 0 and _all() == before
    assert _encoded("book_delta") == (counted[0] + 1, counted[1] + size)


def test_a_failed_encode_is_not_observed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(binary, "perf_counter", _Ticks(0.25))
    before = _all()
    with pytest.raises(FrameEncodeError):
        binary.encode(Frame(BOOK_DELTA, records=((0, 0, -1),)), SAMPLE_EVERY)
    assert _all() == before


def test_the_encoder_times_each_delta_the_hub_stamps_and_no_other(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _conn()
    _, sub = conn.sub({"ch": CH, "opts": {}})  # binary by default; the snapshot is `s` 1
    frame, ticks = _vector("book_delta"), _Ticks(0.25)
    size = len(binary.encode(frame))
    monkeypatch.setattr(binary, "perf_counter", ticks)
    before, counted = _cost("book_delta"), _encoded("book_delta")
    n, stamped = SAMPLE_EVERY, 3
    for _ in range(stamped * n - 1):  # `s` 2 to 3 x `n`: the hub stamps `n`, 2 x `n` and 3 x `n`
        assert conn.emitter.delta(sub, part=frame)
    assert ticks.reads == 2 * stamped  # a timer pair for each stamped delta, none for the rest
    (n0, t0), (c0, b0) = before
    (n1, t1), (c1, b1) = _cost("book_delta")
    assert (n1 - n0, c1 - c0, b1 - b0) == (stamped * n, stamped * n, stamped * n * size)
    assert t1 - t0 == pytest.approx(stamped * n * 0.25)
    # Sampling thins the histograms only: the frame and byte counters still see every frame.
    assert _encoded("book_delta") == (
        counted[0] + stamped * n - 1,
        counted[1] + (stamped * n - 1) * size,
    )


def test_two_subscriptions_of_a_kind_are_each_sampled_on_their_own_frames() -> None:
    """A counter per kind would walk the two in turn and always land on the same one."""
    conn = _conn()
    _, small = conn.sub({"ch": "book.BTCUSDT.50", "opts": {}})
    _, large = conn.sub({"ch": "book.BTCUSDT.200", "opts": {}})
    parts = Frame(BOOK_DELTA, records=((0, 1, 1),)), Frame(BOOK_DELTA, records=((0, 1, 1),) * 9)
    sizes = [len(binary.encode(f)) for f in parts]
    assert sizes[0] != sizes[1]
    (n0, _), (_, b0) = _cost("book_delta")
    for _ in range(SAMPLE_EVERY - 1):  # `s` 2 to `n` of both, in the same order every time
        assert conn.emitter.delta(small, part=parts[0]) and conn.emitter.delta(large, part=parts[1])
    (n1, _), (_, b1) = _cost("book_delta")
    assert (n1 - n0, b1 - b0) == (2 * SAMPLE_EVERY, SAMPLE_EVERY * sum(sizes))  # each, once


def test_every_snapshot_chunk_is_timed_and_sized_exactly() -> None:
    src = Source()
    src.bodies["footprint"] = _footprint_body(cells_per_bar=50, bars=40)
    conn = Conn(src, ACC_A, max_frame_bytes=20_000)
    before, counted = _cost("footprint"), _encoded("footprint")
    conn.sub({"ch": "footprint.BTCUSDT.time.1", "opts": {"encoding": "binary"}})
    chunks = len(conn.take())
    (n0, _), (c0, b0) = before
    (n1, _), (c1, b1) = _cost("footprint")
    frames, nbytes = _encoded("footprint")
    assert chunks > 1 and (n1 - n0, c1 - c0) == (chunks, chunks)  # weight 1 each, not `n`
    assert (frames - counted[0], b1 - b0) == (chunks, nbytes - counted[1])  # the same bytes


#: Each codec a connection can negotiate (23 section 2.2), by its subprotocol.
CODECS = pytest.mark.parametrize("subprotocol", [JSON, MSGPACK], ids=["json", "msgpack"])
_RECV_TIMEOUT_S = 5.0


def _wire(ws: Any) -> str | bytes:
    """The next message as the client's socket got it: the text of a `cv.v1.json` frame, the bytes
    of a `cv.v1.msgpack` one. Bounded like `_recv`, so a missing frame fails fast."""
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        message = pool.submit(ws.receive).result(timeout=_RECV_TIMEOUT_S)
    except FutureTimeout:
        pytest.fail(f"no WS frame within {_RECV_TIMEOUT_S}s")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    assert message["type"] == "websocket.send", message
    payload: bytes | None = message.get("bytes")
    text: str = message.get("text", "")
    return text if payload is None else payload


def _decoded(raw: str | bytes) -> dict[str, Any]:
    frame: dict[str, Any] = msgpack.unpackb(raw) if isinstance(raw, bytes) else json.loads(raw)
    return frame


def _size(raw: str | bytes) -> int:
    """Bytes on the wire: a JSON text is ASCII, so its characters are bytes."""
    return len(raw) if isinstance(raw, bytes) else len(raw.encode())


def _session(subprotocol: list[str], deltas: int) -> list[str | bytes]:
    """Every message a client gets on `subprotocol` from `hello` to the last of `deltas` deltas on
    `CH`, as it crossed the wire: `welcome`, `auth_ok`, `sub_ok`, the `snap` (`s` 1), the deltas."""
    w = _World()
    with w.client, w.client.websocket_connect("/ws", subprotocols=subprotocol) as ws:
        _send(ws, {"t": "hello", "id": "h"})
        wire = [_wire(ws)]  # `welcome`: a control frame
        _send(ws, {"t": "auth", "id": "a", "p": {"access_token": "good"}})
        wire.append(_wire(ws))  # `auth_ok`
        _send(ws, {"t": "sub", "id": "s1", "p": {"topics": [{"ch": CH, "opts": {}}]}})
        wire += [_wire(ws), _wire(ws)]  # `sub_ok`, then the `snap`: `s` 1
        assert w.client.portal is not None
        w.client.portal.call(lambda: [w.hub.publish(CH, BODY) for _ in range(deltas)])
        wire += [_wire(ws) for _ in range(deltas)]
    assert [_decoded(m)["t"] for m in wire[:4]] == ["welcome", "auth_ok", "sub_ok", "snap"]
    return wire


@CODECS
def test_the_writer_times_and_sizes_only_the_data_frames_the_hub_stamped(
    monkeypatch: pytest.MonkeyPatch, subprotocol: list[str]
) -> None:
    ticks = _Ticks(1.0)  # the writer's timer pair around the encode: exactly 1 s apart
    monkeypatch.setattr(gateway, "perf_counter", ticks)
    send = gateway._Connection.send_payload

    async def slow_send(conn: Any, payload: str | bytes) -> None:
        ticks.now += 10.0  # a send takes 10 s on the stand-in clock: it is not encode time
        await send(conn, payload)

    monkeypatch.setattr(gateway._Connection, "send_payload", slow_send)
    kind = MSGPACK_KIND if subprotocol == MSGPACK else JSON_KIND
    before = _writer()
    n = SAMPLE_EVERY
    wire = _session(subprotocol, deltas=2 * n - 1)  # `s` 2 to 2 x `n`: the hub stamps `n`, 2 x `n`
    after = _writer()
    frames = [_decoded(m) for m in wire]
    # Every frame crossed in the connection's own codec: text on `cv.v1.json`, bytes on msgpack.
    assert {type(m) for m in wire} == {bytes if kind == MSGPACK_KIND else str}
    stamped = [i for i, f in enumerate(frames) if f["t"] == "d" and f["s"] % n == 0]
    assert [frames[i]["s"] for i in stamped] == [n, 2 * n]
    assert ticks.reads == 2 * 2  # a timer pair for each stamped frame; none for any other frame
    # Only the connection's own kind moves (never the other codec's), and only for the stamped
    # frames: `n` times each, once. The size is the frame's length on the wire.
    assert {k for k in after if after[k] != before[k]} == {kind}
    (n0, t0), (c0, b0) = before[kind]
    (n1, t1), (c1, b1) = after[kind]
    assert (n1 - n0, c1 - c0) == (2 * n, 2 * n)
    assert t1 - t0 == pytest.approx(2 * n * 1.0)
    assert b1 - b0 == n * sum(_size(wire[i]) for i in stamped)


@CODECS
def test_a_frame_the_hub_did_not_stamp_observes_nothing_and_reads_no_timer(
    monkeypatch: pytest.MonkeyPatch, subprotocol: list[str]
) -> None:
    ticks = _Ticks(1.0)
    monkeypatch.setattr(gateway, "perf_counter", ticks)
    before = _writer()
    n = SAMPLE_EVERY
    wire = _session(subprotocol, deltas=n - 2)  # `s` 2 to `n` - 1: not one is stamped
    assert [f["s"] for f in map(_decoded, wire) if f["t"] == "d"] == [*range(2, n)]
    assert ticks.reads == 0 and _writer() == before  # neither codec observed anything
