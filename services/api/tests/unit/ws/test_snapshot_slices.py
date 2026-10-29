"""#605: a snapshot whose render, chunking and encoding take more than one loop turn's CPU
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
    assemble_steps,
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
    assert _finish(assemble_steps(frame, chunk, wire)) == want  # type: ignore[arg-type]


def test_a_chunk_with_a_value_json_cannot_carry_is_never_assembled() -> None:
    [chunk] = _finish(_split_steps({"columns": [1.0, math.nan]}, 10**6))
    assert chunk.texts is None
    with pytest.raises(ValueError, match="not assembled"):
        _finish(assemble_steps({"p": chunk.payload}, chunk, "json"))


def _big(columns: int = 60, rows: int = 200) -> SnapshotBody:
    cols = [
        {"t_ms": 1_700_000_000_000 + 100 * i, "price_min": "100.0", "price_step": "0.1",
         "bids": [0.123456789 * (j + 1) for j in range(rows)],
         "asks": [1.987654321 * (j + 1) for j in range(rows)], "complete": True}
        for i in range(columns)
    ]  # fmt: skip
    return SnapshotBody({"symbol": "BTCUSDT", "time_bucket_ms": 100, "columns": cols})


class _Catching(Source):
    """A source that can tell what changed during a spread snapshot (here: nothing)."""

    def catch_up(self, sub: Any, since: int) -> list[Any]:
        return []


def _conn(body: SnapshotBody, turn_s: float, max_frame_bytes: int | None = None) -> Conn:
    source = _Catching()
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
    whole = _conn(_big(), turn_s=math.inf, max_frame_bytes=64_000)  # no bound: all at once
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
    conn = _conn(_big(columns=2, rows=4), turn_s=math.inf)
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
    conn = _conn(_big(columns=2, rows=4), turn_s=math.inf)
    queued: list[Any] = []
    conn.emitter.push_encoded = lambda f, p, r: queued.append(p)
    conn.emitter.encode_payload, conn.emitter.wire = json_payload, "json"
    sub = _sub(conn)
    assert conn.emitter.snapshot(sub, "initial")
    assert queued == [] and len(conn.out) == 1  # as before: the dict, the queue encodes it


# -- one turn budget, shared -----------------------------------------------------------------------


async def test_concurrent_snapshots_share_one_turn_budget_round_robin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three large snapshots on three connections run under one budget a loop turn (here
    one step a turn), taking turns, never three slices in one turn."""
    from candleviewer.ws import sequencing

    conns = [_conn(_big(), turn_s=0.0, max_frame_bytes=64_000) for _ in range(3)]
    subs = [_sub(c) for c in conns]
    per_turn: list[list[str]] = []
    real = sequencing.TopicEmitter._step

    def counted(self: Any, job: Any) -> bool:
        per_turn[-1].append(job.sub.sub_id + str(id(self)))
        return bool(real(self, job))

    turn = sequencing._Turns._turn

    def marked(self: Any) -> None:
        per_turn.append([])
        turn(self)

    monkeypatch.setattr(sequencing.TopicEmitter, "_step", counted)
    monkeypatch.setattr(sequencing._Turns, "_turn", marked)
    for conn, sub in zip(conns, subs, strict=True):
        assert conn.emitter.snapshot(sub, "initial")
    for _ in range(100_000):
        await asyncio.sleep(0)
        if all(c.out for c in conns):
            break
    assert all(c.out for c in conns)
    stepped = [t for t in per_turn if t]
    assert stepped and all(len(t) == 1 for t in stepped)  # one step a turn, all jobs together
    order = [t[0] for t in stepped[:6]]
    assert len(set(order[:3])) == 3  # round-robin: each job in turn


# -- what changed meanwhile follows the snapshot ---------------------------------------------------


class _Moving(Source):
    """A source whose state moves while its snapshot is under way and that cannot tell what."""

    def catch_up(self, sub: Any, since: int) -> None:
        return None

    def build_steps(self, sub: Any) -> Any:
        body = self.build(sub)
        for _ in range(20):
            yield
        self.gen += 1  # an update the snapshot does not hold
        return body


async def test_a_source_that_cannot_catch_up_is_snapshotted_again_when_it_moved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    source = _Moving()
    source.bodies["heatmap"] = _big(columns=2, rows=4)
    conn = Conn(source, cache=SnapshotCache())
    conn.emitter.turn_s = 0.0
    sub = _sub(conn)
    assert conn.emitter.snapshot(sub, "initial")
    for _ in range(100_000):
        await asyncio.sleep(0)
        if len([f for f in conn.out if f["t"] == "snap"]) >= 2:
            break
    snaps = [f for f in conn.out if f["t"] == "snap"]
    assert [f["s"] for f in snaps][:2] == [1, 2]  # the state it missed comes as a new snap


# -- the snapshot cache's byte bound ---------------------------------------------------------------


def test_the_snapshot_cache_is_bounded_by_bytes_oldest_out_first() -> None:
    from candleviewer.ws.sequencing import SNAPSHOT_CACHE_MAX_BYTES

    assert SNAPSHOT_CACHE_MAX_BYTES == 64 * 1024 * 1024
    source = Source()
    source.bodies["heatmap"] = _big(columns=10, rows=40)
    cache = SnapshotCache()
    conns = [Conn(source, cache=cache) for _ in range(3)]
    for i, conn in enumerate(conns):
        if i == 1:  # room for two of them
            cache.max_bytes = cache.bytes * 5 // 2
        result, sub = conn.authz.admit(
            {"ch": CH, "opts": {"encoding": "structured", "window_seconds": 100 + i}}
        )
        assert sub is not None, result
        sub.announced = True
        assert conn.emitter.snapshot(sub, "initial")
    sizes = [r.nbytes for _, r in cache._entries.values()]
    assert len(cache) == 2 and cache.bytes == sum(sizes) <= cache.max_bytes
    assert sizes[0] > 10_000  # its JSON's estimate (`Rendered.nbytes`), not a count
    cache.invalidate(CH)
    assert (len(cache), cache.bytes) == (0, 0)
    tiny = SnapshotCache(max_bytes=1_000)  # a render larger than the whole bound: used, not kept
    conn = Conn(source, cache=tiny)
    sub = _sub(conn)
    assert conn.emitter.snapshot(sub, "initial") and len(tiny) == 0 and tiny.bytes == 0


async def test_a_source_that_cannot_catch_up_is_never_spread() -> None:
    """Spreading needs `catch_up` (§7.1: nothing may be lost while pending): any other source's
    snapshot finishes in the call that asked for it, as before #605, whatever its size."""
    source = Source()
    source.bodies["heatmap"] = _big()
    conn = Conn(source, cache=SnapshotCache(), max_frame_bytes=64_000)
    conn.emitter.turn_s = 0.0
    sub = _sub(conn)
    assert conn.emitter.snapshot(sub, "initial") and conn.out and not conn.emitter._jobs


async def test_a_request_once_the_turns_budget_is_spent_waits_for_a_later_turn() -> None:
    """A request's inline slice runs only while the loop turn's shared budget has room;
    once it is spent, a later request of that turn runs nothing inline and takes its steps in a
    later turn. The budget is the turn's: in the next turn a request is emitted at once."""
    from candleviewer.ws import sequencing

    conn = _conn(_big(columns=2, rows=4), turn_s=10.0)
    turns = sequencing._Turns.of(asyncio.get_running_loop())
    turns.charge(10.0)  # this turn's budget, spent by what ran before
    sub = _sub(conn)
    assert conn.emitter.snapshot(sub, "initial") is True
    assert conn.out == [] and sub.snapshot_pending and sub.sub_id in conn.emitter._jobs
    conn.emitter.turn_s = math.inf  # unbounded from here: the next turn finishes it, whatever
    await asyncio.sleep(0)  # the next turn: the budget is reset, then the job steps
    assert len(conn.out) == 1 and conn.out[0]["s"] == 1 and not conn.emitter._jobs
    assert turns.remaining(10.0) > 0
    late = _conn(_big(columns=2, rows=4), turn_s=math.inf)
    other = _sub(late)
    await asyncio.sleep(0)
    assert late.emitter.snapshot(other, "initial") and len(late.out) == 1  # room again: inline


async def test_a_source_that_cannot_catch_up_is_synchronous_whatever_the_turns_budget() -> None:
    """Only a source with `catch_up` waits for room; any other's snapshot is emitted in
    the call, as before #605, even when the turn's budget is spent."""
    from candleviewer.ws import sequencing

    source = Source()
    source.bodies["heatmap"] = _big(columns=2, rows=4)
    conn = Conn(source, cache=SnapshotCache())
    sequencing._Turns.of(asyncio.get_running_loop()).charge(10.0)
    sub = _sub(conn)
    assert conn.emitter.snapshot(sub, "initial") and len(conn.out) == 1
    assert not conn.emitter._jobs


class _Uncached(_Catching):
    """A source whose snapshots never enter the shared cache (#605: heatmap)."""

    def cacheable(self, sub: Any) -> bool:
        return False


async def test_a_source_that_opts_out_never_enters_the_snapshot_cache() -> None:
    """A source saying `cacheable` False is built for each request and never cached, so
    its renders evict no other family's entry; any other public source is cached as before."""
    for source, cached in ((_Uncached(), 0), (_Catching(), 1)):
        source.bodies["heatmap"] = _big(columns=2, rows=4)
        cache = SnapshotCache()
        conn = Conn(source, cache=cache)
        sub = _sub(conn)
        assert conn.emitter.snapshot(sub, "initial") and len(conn.out) == 1
        assert len(cache) == cached and cache.bytes == (0 if not cached else cache.bytes)


async def test_a_job_step_is_a_batch_of_its_own_steps_up_to_step_s(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One `_step` of a job runs its own steps until `step_s` is spent, so a large snapshot
    takes few round-robin steps; with room for all of it, one."""
    from candleviewer.ws import sequencing

    conn = _conn(_big(), turn_s=0.0, max_frame_bytes=64_000)  # no inline slice: all deferred
    sub = _sub(conn)
    assert conn.emitter.snapshot(sub, "initial") and conn.out == []
    conn.emitter.turn_s, conn.emitter.step_s = math.inf, math.inf
    calls: list[int] = []
    real = sequencing.TopicEmitter._step

    def counted(self: Any, job: Any) -> bool:
        calls.append(1)
        return bool(real(self, job))

    monkeypatch.setattr(sequencing.TopicEmitter, "_step", counted)
    await asyncio.sleep(0)
    assert len(calls) == 1 and conn.out and conn.out[-1]["s"] == 1


T_MS = 1_700_000_000_000


def _column_body(g: int) -> dict[str, Any]:
    """One §14.5 column's `d` body, its `t_ms` naming generation `g`."""
    col = {"t_ms": T_MS + g, "price_min": "100.0", "price_step": "0.1", "bids": [1.0],
           "asks": [2.0], "complete": True}  # fmt: skip
    return {"symbol": "BTCUSDT", "time_bucket_ms": 100, "columns": [col]}


class _Following(Source):
    """A source whose state moves while its snapshot is under way and that tells what: each
    generation is one `d` body, built when read; what moves during the catch-up is its tail."""

    def __init__(self) -> None:
        super().__init__()
        self.read: list[int] = []

    def catch_up(self, sub: Any, since: int) -> Any:
        def items() -> Any:
            for g in range(since + 1, self.gen + 1):
                self.read.append(g)
                yield _column_body(g), None

        return items()


async def test_a_catch_up_runs_a_d_a_step_and_no_live_d_crosses_it() -> None:
    """§7.1: the catch-up's `d` frames follow the snapshot one per step, in order with
    consecutive `s`; a live `d` meanwhile is refused (its change is read as the tail), and the
    subscription takes live `d` frames again once the catch-up ends."""
    source = _Following()
    source.bodies["heatmap"] = _big()
    conn = Conn(source, cache=SnapshotCache(), max_frame_bytes=64_000)
    conn.emitter.turn_s, conn.emitter.step_s = 0.0, 0.0
    sub = _sub(conn)
    assert conn.emitter.snapshot(sub, "initial") and conn.out == []
    await asyncio.sleep(0)
    source.gen = 3  # three changes while it is under way
    for _ in range(100_000):  # one loop turn each: the job's steps
        if conn.out:
            break
        await asyncio.sleep(0)
    assert conn.out[-1]["s"] == 1 and sub.sub_id in conn.emitter._catching
    assert not conn.emitter.delta(sub, _column_body(99))  # refused: the catch-up is under way
    source.gen = 4  # one more: its tail
    for _ in range(100):
        await asyncio.sleep(0)
        if not conn.emitter._jobs:
            break
    deltas = [f for f in conn.out if f["t"] == "d"]
    assert [f["p"]["columns"][0]["t_ms"] - T_MS for f in deltas] == [1, 2, 3, 4]
    assert source.read == [1, 2, 3, 4]
    assert [f["s"] for f in deltas] == [2, 3, 4, 5] and not conn.emitter._catching
    assert conn.emitter.delta(sub, _column_body(99)) and conn.out[-1]["s"] == 6


async def test_a_job_dropped_mid_catch_up_lets_live_d_frames_through_again() -> None:
    """A snapshot replacing one in its catch-up (or the end of the subscription) ends that
    catch-up, and nothing of it holds the subscription's live `d` frames back."""
    source = _Following()
    source.bodies["heatmap"] = _big()
    conn = Conn(source, cache=SnapshotCache(), max_frame_bytes=64_000)
    conn.emitter.turn_s, conn.emitter.step_s = 0.0, 0.0
    sub = _sub(conn)
    assert conn.emitter.snapshot(sub, "initial")
    await asyncio.sleep(0)
    source.gen = 50
    for _ in range(100_000):
        if sub.sub_id in conn.emitter._catching:
            break
        await asyncio.sleep(0)
    conn.emitter._drop_job(sub.sub_id)
    assert not conn.emitter._catching and conn.emitter.delta(sub, _column_body(99))


def _no_close(reason: str, *, bye: dict[str, Any] | None = None) -> None:
    """A pipeline's `close` that closes nothing."""


async def test_a_large_snapshot_encoded_in_its_steps_keeps_its_encode_time_sample() -> None:
    """E17-T06 with #605: a large snapshot's frames are encoded in its own steps, not by the
    queue, so the encode-time sample of its stamped frame is taken there and handed over with
    it; the connection's `cv_ws_frame_encode_seconds{kind="json"}` still observes it, with the
    sampling weight."""
    from candleviewer.ws.backpressure_config import BackpressureConfig
    from candleviewer.ws.metrics import JSON_KIND, SAMPLE_EVERY, cv_ws_frame_encode_seconds
    from candleviewer.ws.pipeline import ConnectionPipeline

    conn = _conn(_big(), turn_s=0.0, max_frame_bytes=64_000)
    pipe = ConnectionPipeline(
        encoding="cv.v1.json",
        config=BackpressureConfig(),
        close=_no_close,
        wall_ms=lambda: T_MS,
        connection_id="ws_test",
    )
    pipe.attach(conn.authz, conn.emitter, lambda _body: None)
    conn.emitter.push_data = pipe.push
    sub = _sub(conn)
    sub.seq = SAMPLE_EVERY - 1  # its snapshot's `s` is the stamped one
    child = cv_ws_frame_encode_seconds.labels(JSON_KIND)
    before = child.reading()[0][-1]
    assert conn.emitter.snapshot(sub, "initial")
    for _ in range(100_000):
        await asyncio.sleep(0)
        if not conn.emitter._jobs:
            break
    assert len(pipe.queue) > 1 and sub.seq == SAMPLE_EVERY  # encoded in its steps, queued
    assert child.reading()[0][-1] - before == SAMPLE_EVERY


def test_a_closed_loop_and_its_turns_are_collected() -> None:
    """`_Turns` is kept per loop in a weak-keyed registry; it holds its loop weakly, so a closed
    and dropped loop, and its entry, are collected rather than kept for the process's life."""
    import gc
    import weakref

    from candleviewer.ws import sequencing

    loop = asyncio.new_event_loop()

    async def use() -> None:
        turns = sequencing._Turns.of(asyncio.get_running_loop())
        turns.charge(0.001)  # arms its turn-end callback on the loop

    loop.run_until_complete(use())
    loop.run_until_complete(asyncio.sleep(0))
    loop.close()
    gone = weakref.ref(loop)
    entries = len(sequencing._Turns._BY_LOOP)
    del loop
    gc.collect()
    # Other tests' dropped loops may be collected here too: at least this one's entry is gone.
    assert gone() is None, gc.get_referrers(gone())
    assert len(sequencing._Turns._BY_LOOP) <= entries - 1
