"""#605 (M-1): a snapshot whose render, chunking and encoding take more than one loop turn's CPU
(`SNAPSHOT_TURN_S`) is finished in later turns, a slice each, by `TopicEmitter`, for any family.
Its frames are the same frames, queued together in its last slice, in order, the last with `s`;
until then the subscription stays pending, so no `d` of it precedes them (23 §7.1, §3.6). One
that fits a slice is emitted at once, as before. A structured chunk's frame is assembled from its
items' JSON as the queue's encoder writes it, byte for byte, in both wire encodings."""

from __future__ import annotations

import asyncio
import json
import math
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.ws.outbound import json_payload
from candleviewer.ws.pipeline import msgpack_payload
from candleviewer.ws.sequencing import (
    SnapshotBody,
    SnapshotCache,
    _split_steps,
    assemble_chunk,
    split_structured,
)
from tests.unit.ws._seq_support import Conn, Source, validate

CH = "heatmap.BTCUSDT"
EMPTY: dict[str, Any] = {"symbol": "BTCUSDT", "time_bucket_ms": 100, "columns": []}


def _finish(gen: Any) -> Any:
    while True:
        try:
            next(gen)
        except StopIteration as done:
            return done.value


ITEMS = st.recursive(
    st.one_of(st.integers(-(2**53), 2**53), st.floats(allow_nan=False, allow_infinity=False),
              st.text(max_size=12), st.booleans(), st.none()),
    lambda inner: st.lists(inner, max_size=4) | st.dictionaries(st.text(max_size=6), inner,
                                                                 max_size=4),
    max_leaves=12,
)  # fmt: skip
PAYLOADS = st.fixed_dictionaries(
    {"symbol": st.text(max_size=8), "columns": st.lists(ITEMS, max_size=30)},
    optional={"extra": st.lists(ITEMS, max_size=10), "n": st.integers(0, 10**9)},
)


@settings(max_examples=300, deadline=None)
@given(PAYLOADS, st.integers(60, 2_000))
def test_the_sliced_split_cuts_the_chunks_split_structured_cuts(
    payload: dict[str, Any], budget: int
) -> None:
    try:
        want = split_structured(payload, budget)
    except Exception as exc:  # the same refusal
        with pytest.raises(type(exc)):
            _finish(_split_steps(payload, budget))
        return
    got = _finish(_split_steps(payload, budget))
    assert [c.payload for c in got] == want
    for chunk in got:
        text = json.dumps(chunk.payload, separators=(",", ":"))
        assert chunk.size == len(text)


@settings(max_examples=300, deadline=None)
@given(PAYLOADS, st.booleans(), st.sampled_from(["json", "msgpack"]))
def test_an_assembled_chunk_is_the_queue_encoders_bytes(
    payload: dict[str, Any], last: bool, wire: str
) -> None:
    [chunk] = _finish(_split_steps(payload, 10**9))
    frame: dict[str, Any] = {"t": "snap", "id": "snap-1", "ch": CH, "s": 7 if last else None}
    frame |= {"ts": 1, "meta": {"reason": "initial"}, "e": "j", "p": chunk.payload}
    if last:
        frame["sp"] = "a" * 16  # a sampled last chunk carries its span after `p`
    want = json_payload(frame) if wire == "json" else msgpack_payload(frame)
    assert assemble_chunk(frame, chunk, wire) == want  # type: ignore[arg-type]


def test_a_chunk_with_a_value_json_cannot_carry_is_never_assembled() -> None:
    [chunk] = _finish(_split_steps({"columns": [1.0, math.nan]}, 10**6))
    assert chunk.texts is None
    with pytest.raises(ValueError, match="not assembled"):
        assemble_chunk({"p": chunk.payload}, chunk, "json")


def _big(columns: int = 60, rows: int = 200) -> SnapshotBody:
    cols = [
        {"t_ms": 1_700_000_000_000 + 100 * i, "price_min": "100.0", "price_step": "0.1",
         "bids": [0.123456789 * (j + 1) for j in range(rows)],
         "asks": [1.987654321 * (j + 1) for j in range(rows)], "complete": True}
        for i in range(columns)
    ]  # fmt: skip
    return SnapshotBody({"symbol": "BTCUSDT", "time_bucket_ms": 100, "columns": cols})


def _conn(body: SnapshotBody, turn_s: float, max_frame_bytes: int | None = None) -> Conn:
    source = Source()
    source.bodies["heatmap"] = body
    conn = Conn(source, cache=SnapshotCache(), max_frame_bytes=max_frame_bytes)
    conn.emitter.turn_s = turn_s
    return conn


def _sub(conn: Conn) -> Any:
    result, sub = conn.authz.admit({"ch": CH, "opts": {"encoding": "structured"}})
    assert sub is not None, result
    sub.announced = True
    return sub


async def test_a_slow_snapshot_finishes_in_later_turns_with_the_same_frames() -> None:
    """Whatever the slicing, the frames are the ones one call emits, queued in one turn, in
    order, the last with `s`; in between the subscription is pending and refuses every `d`."""
    whole = _conn(_big(), turn_s=10.0, max_frame_bytes=64_000)
    sub_whole = _sub(whole)
    assert whole.emitter.snapshot(sub_whole, "initial") and len(whole.out) > 1
    sliced = _conn(_big(), turn_s=0.0, max_frame_bytes=64_000)  # every step its own turn
    sub = _sub(sliced)
    assert sliced.emitter.snapshot(sub, "initial") is True
    assert sliced.out == [] and sub.snapshot_pending and sub.seq == 0
    turns = 0
    for turns in range(1, 100_000):  # noqa: B007 - read after the loop
        assert not sliced.emitter.delta(sub, EMPTY)  # §7.1: nothing before its last frame
        await asyncio.sleep(0)  # one loop turn: the job's next slice
        if sliced.out:
            break
    assert turns > 10 and not sub.snapshot_pending and sub.seq == 1
    for frame in sliced.out:
        validate(frame)
    assert [{k: v for k, v in f.items() if k != "id"} for f in sliced.out] == [
        {k: v for k, v in f.items() if k != "id"} for f in whole.out
    ]
    assert [f["s"] for f in sliced.out] == [None] * (len(sliced.out) - 1) + [1]
    assert sliced.emitter.delta(sub, EMPTY)
    assert sliced.out[-1]["s"] == 2


async def test_a_request_while_one_is_under_way_is_that_one_unless_something_changed() -> None:
    conn = _conn(_big(), turn_s=0.0)
    sub = _sub(conn)
    assert conn.emitter.snapshot(sub, "initial")
    job = conn.emitter._jobs[sub.sub_id]
    assert conn.emitter.snapshot(sub, "initial") and conn.emitter._jobs[sub.sub_id] is job
    conn.emitter.source.gen += 1  # type: ignore[union-attr]  # the state moved: a new one
    assert conn.emitter.snapshot(sub, "initial") and conn.emitter._jobs[sub.sub_id] is not job
    for _ in range(100_000):
        await asyncio.sleep(0)
        if conn.out:
            break
    assert len([f for f in conn.out if f["s"] is not None]) == 1  # one snapshot, not two


async def test_a_subscription_that_ends_mid_snapshot_gets_nothing() -> None:
    conn = _conn(_big(), turn_s=0.0)
    sub = _sub(conn)
    assert conn.emitter.snapshot(sub, "initial")
    sub.ended = True
    for _ in range(50):
        await asyncio.sleep(0)
    assert conn.out == [] and sub.sub_id not in conn.emitter._jobs


async def test_a_snapshot_that_fits_a_slice_is_emitted_at_once() -> None:
    conn = _conn(_big(columns=2, rows=4), turn_s=10.0)
    sub = _sub(conn)
    assert conn.emitter.snapshot(sub, "initial")
    assert len(conn.out) == 1 and conn.out[0]["s"] == 1 and not conn.emitter._jobs


def test_without_a_running_loop_a_slow_snapshot_finishes_in_the_call() -> None:
    conn = _conn(_big(), turn_s=0.0)
    sub = _sub(conn)
    assert conn.emitter.snapshot(sub, "initial") and conn.out and not conn.emitter._jobs


@pytest.mark.parametrize("wire", ["json", "msgpack"])
@pytest.mark.parametrize("encoding", ["structured", "binary"])
async def test_a_large_snapshot_queues_frames_encoded_as_the_queue_would_encode_them(
    wire: str, encoding: str
) -> None:
    """With the flag on, a large snapshot's frames are encoded in its slices, each the bytes the
    queue's encoder gives the frame (`json_payload` / `msgpack_payload`), then queued together."""
    from candleviewer.ws.binary import HEATMAP_COLUMN, Frame, pack

    body = _big()
    if encoding == "binary":
        parts = tuple(
            pack(
                Frame(
                    HEATMAP_COLUMN,
                    ((i, i),) * 200,
                    0,
                    1,
                    3,
                    1_700_000_000_000 + 100 * i,
                    prefix=(0, 1000, 1),
                )
            )
            for i in range(60)
        )
        body = SnapshotBody(body.structured, parts, 1, 3)
    conn = _conn(body, turn_s=0.0, max_frame_bytes=64_000)
    queued: list[tuple[dict[str, Any], Any, float | None]] = []
    encoder = json_payload if wire == "json" else msgpack_payload
    conn.emitter.push_encoded = lambda f, p, r: queued.append((f, p, r))
    conn.emitter.encode_payload, conn.emitter.wire = encoder, wire  # type: ignore[assignment]
    result, sub = conn.authz.admit({"ch": CH, "opts": {"encoding": encoding}})
    assert sub is not None, result
    sub.announced = True
    assert conn.emitter.snapshot(sub, "initial")
    for _ in range(100_000):
        await asyncio.sleep(0)
        if queued:
            break
    assert len(queued) > 1 and conn.out == []
    for frame, payload, _ in queued:
        assert payload == encoder(frame)
    assert [f["s"] for f, _, _ in queued] == [None] * (len(queued) - 1) + [1]


def test_a_small_snapshot_is_left_to_the_queues_encoder() -> None:
    conn = _conn(_big(columns=2, rows=4), turn_s=10.0)
    queued: list[Any] = []
    conn.emitter.push_encoded = lambda f, p, r: queued.append(p)
    conn.emitter.encode_payload, conn.emitter.wire = json_payload, "json"
    sub = _sub(conn)
    assert conn.emitter.snapshot(sub, "initial")
    assert queued == [] and len(conn.out) == 1  # as before: the dict, the queue encodes it
