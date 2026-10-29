"""E21-T02 (#605) bench: the heatmap engine's column build and its kind-6 encode, per 100 ms
column, at the row cap (512 rows), against budget #6 (<= 20 ms backend-added latency per column)
and budget #14 (the 100 ms cadence sustained) of `06-performance-and-load-standard.md`.

A live book of 257 bid and 255 ask levels on contiguous ticks around the mid, so every column fills
all 512 rows of its window (G-07a's worst case) and has no off-window total, runs through the
production `BookEngine` and `HeatmapTopic` on a clock that moves 100 ms per column. Between two
columns a seeded random walk changes `--changes` levels as book deltas. Each column's cost is the
turn that closes it (`tick`: integrate, window, build the §14.5 column and its kind-6 part) plus
the CVWB encode of that part (`ws.binary.encode`). No socket, no network, no fixture (C-13.5): the
input is synthetic and seeded, so a run repeats.

`--capture PATH` (or `CV_HEATMAP_BENCH_CAPTURE`) replays a recorded depth-200 JSONL capture of the
fixture corpus instead, read as plain JSON (`b` / `a` price-size lists, `u`), one frame a column.

Run: `uv run python bench/heatmap_columns.py [--columns 3000] [--out report.json]`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import statistics
import time
import tracemalloc
from array import array
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final, cast
from uuid import UUID

import numpy as np

from candleviewer.book.resync import BookEngine
from candleviewer.bus.bus import Bus
from candleviewer.domain.primitives import EventId
from candleviewer.exchange.base.models import BookDelta, BookLevel, BookSnapshot
from candleviewer.orderflow.heatmap import (
    COLUMN_MS,
    FAMILY,
    ROWS,
    HeatmapColumn,
    HeatmapSpec,
    HeatmapTopic,
    _Entry,
    rebucket,
    window_column,
)
from candleviewer.ws import sequencing
from candleviewer.ws.binary import decode, encode, encode_b64
from candleviewer.ws.outbound import json_payload
from candleviewer.ws.permissions import Subscription
from candleviewer.ws.sequencing import SnapshotBody, SnapshotCache, TopicEmitter, render
from candleviewer.ws.topics import effective_options, parse_topic
from candleviewer.ws_wiring import heatmap_part

SYMBOL = "BTCUSDT"
TICK, QTY_STEP = Decimal("0.1"), Decimal("0.001")
T0 = 1_700_000_000_000
BUDGET_6_MS = 20.0
CADENCE_MS = float(COLUMN_MS)
_EID = EventId(UUID(int=1))


@dataclass
class Report:
    columns: int
    rows_p50: float
    build_ms_p50: float
    build_ms_p95: float
    build_ms_p99: float
    encode_ms_p95: float
    total_ms_p95: float
    budget_6_ms: float
    budget_6_pass: bool
    budget_14_pass: bool
    source: str
    # Fable M-1 (#605): a `sub` at the full G-03 budget and a 2 000-column re-seed.
    snapshot_columns: int = 0
    snapshot_build_ms: float = 0.0
    snapshot_encode_ms: float = 0.0
    #: The gateway's render of that snapshot (`sequencing.render`, one loop turn), 20 runs:
    #: packed parts (#605) against the same parts unpacked (the render before #605).
    render_packed_ms_p95: float = 0.0
    render_packed_ms_max: float = 0.0
    render_plain_ms_p95: float = 0.0
    render_plain_ms_max: float = 0.0
    hold_ms: float = 0.0
    #: The gateway's whole snapshot emission (render, chunking, encoding, queueing) per loop turn,
    #: at the G-03 bound, binary and structured: in one turn (as before #605's slicing) and in
    #: `SNAPSHOT_TURN_S` slices; p95 and max of the turns, and the turns it took.
    emit_binary_one_turn_ms: float = 0.0
    emit_binary_sliced_p95_ms: float = 0.0
    emit_binary_sliced_max_ms: float = 0.0
    emit_binary_turns: int = 0
    emit_structured_one_turn_ms: float = 0.0
    emit_structured_sliced_p95_ms: float = 0.0
    emit_structured_sliced_max_ms: float = 0.0
    emit_structured_turns: int = 0
    emit_structured_columns: int = 0
    #: The same turns' CPU (`time.thread_time`), which a loaded host's preemption does not inflate.
    emit_binary_sliced_cpu_max_ms: float = 0.0
    emit_structured_sliced_cpu_max_ms: float = 0.0
    #: m-C: eight connections' snapshots at once, one shared budget a turn.
    emit_binary_8_connections_turn_max_ms: float = 0.0
    emit_binary_8_connections_cpu_max_ms: float = 0.0
    emit_structured_8_connections_turn_max_ms: float = 0.0
    emit_structured_8_connections_cpu_max_ms: float = 0.0
    emit_binary_8_connections_asking_turn_cpu_ms: float = 0.0
    emit_binary_8_connections_later_turn_cpu_max_ms: float = 0.0
    emit_structured_8_connections_asking_turn_cpu_ms: float = 0.0
    emit_structured_8_connections_later_turn_cpu_max_ms: float = 0.0
    #: M-B: a ring entry's bytes and a spec's ring at 2 000 columns x 512 rows (tracemalloc).
    ring_entry_bytes: int = 0
    ring_spec_mib: float = 0.0
    #: m-B: the re-seed's CPU, 1 000 columns of 512 rows re-bucketed 1 -> 2: by `window_column`
    #: (the dict path before #605's vectorising) and by `rebucket`.
    rebucket_dict_ms: float = 0.0
    rebucket_numpy_ms: float = 0.0
    reseed_turns: int = 0
    reseed_turn_p95_ms: float = 0.0
    reseed_turn_max_ms: float = 0.0
    reseed_total_ms: float = 0.0
    #: One core's share at the G-02 cap: 32 specs x 10 columns/s x the close cost (`tick` p50).
    steady_core_share_at_cap: float = 0.0


class _Hub:
    def __init__(self) -> None:
        self.parts: list[Any] = []

    def publish(self, ch: str, body: Mapping[str, Any] | None = None, **kw: Any) -> int:
        self.parts.append(kw.get("part"))
        return 1

    def flush_pending(self, match: Any = None) -> int:
        return 0


@dataclass
class _Sub:
    heatmap_lease: Any
    ch: str = f"heatmap.{SYMBOL}"
    effective: dict[str, Any] = field(default_factory=dict)
    replay_session_id: str | None = None
    snapshot_pending: bool = False


def _level(ticks: int, qty: Decimal) -> BookLevel:
    return BookLevel(price=Decimal(ticks) * TICK, qty=qty, price_ticks=ticks)


def _snapshot(u: int, bids: list[BookLevel], asks: list[BookLevel]) -> BookSnapshot:
    return BookSnapshot(
        event_id=_EID, ts_event=u, ts_ingest=u, source="live", symbol=SYMBOL, depth=500,
        bids=tuple(bids), asks=tuple(asks), update_id=u, cross_seq=u, ts_match=u,
        reason="subscribe",
    )  # fmt: skip


def _delta(u: int, bids: list[BookLevel], asks: list[BookLevel]) -> BookDelta:
    return BookDelta(
        event_id=_EID, ts_event=u, ts_ingest=u, source="live", symbol=SYMBOL, depth=500,
        bids=tuple(bids), asks=tuple(asks), update_id=u, prev_update_id=u - 1, cross_seq=u,
        ts_match=u,
    )  # fmt: skip


def _synthetic(columns: int, changes: int, seed: int) -> list[BookSnapshot | BookDelta]:
    rng = random.Random(seed)  # noqa: S311 - seeded synthetic book, not crypto
    best_bid = 631_180
    half = ROWS // 2
    events: list[BookSnapshot | BookDelta] = [
        _snapshot(
            1,
            [_level(best_bid - i, Decimal(rng.randint(1, 9000)) / 1000) for i in range(half + 1)],
            [
                _level(best_bid + 1 + i, Decimal(rng.randint(1, 9000)) / 1000)
                for i in range(half - 1)
            ],
        )
    ]
    for u in range(2, columns + 2):
        bids = [
            _level(best_bid - rng.randrange(half + 1), Decimal(rng.randint(1, 9000)) / 1000)
            for _ in range(changes // 2)
        ]
        asks = [
            _level(best_bid + 1 + rng.randrange(half - 1), Decimal(rng.randint(1, 9000)) / 1000)
            for _ in range(changes - changes // 2)
        ]
        events.append(_delta(u, bids, asks))
    return events


def _recorded(path: Path, columns: int) -> list[BookSnapshot | BookDelta]:
    out: list[BookSnapshot | BookDelta] = []
    for line in path.read_text(encoding="utf-8").splitlines()[: columns + 1]:
        rec = json.loads(line)
        data = rec["data"]
        sides = [
            [_level(int(Decimal(p) / TICK), Decimal(q)) for p, q in data[s]] for s in ("b", "a")
        ]
        if rec["type"] == "snapshot":
            out.append(_snapshot(int(data["u"]), *sides))
        else:
            out.append(_delta(int(data["u"]), *sides))
    return out


async def run(events: list[BookSnapshot | BookDelta], source: str) -> Report:
    now = [float(T0)]
    hub = _Hub()
    engines: dict[str, BookEngine] = {}

    async def publish(_ev: object) -> None:
        return None

    async def resub() -> None:
        return None

    eng = BookEngine(symbol=SYMBOL, depth=500, publish=publish, resubscribe=resub,
                     now_us=lambda: int(now[0] * 1000))  # fmt: skip
    engines[SYMBOL] = eng
    await eng.start()
    topic = HeatmapTopic(
        hub, engine=engines.get, steps=lambda _s: (TICK, QTY_STEP), part=heatmap_part,
        body=SnapshotBody, bus=Bus(), env="live", queue_bytes=8_388_608, queue_frames=2_000,
        clock_ms=lambda: now[0],
    )  # fmt: skip
    await eng.on_event(events[0])
    topic.hold("bench", HeatmapSpec(SYMBOL, depth=500, time_bucket_ms=COLUMN_MS))
    build, enc, rows = [], [], []
    for i, ev in enumerate(events[1:], start=1):
        await eng.on_event(ev)
        topic.offer(ev)
        now[0] = T0 + i * CADENCE_MS
        before = len(hub.parts)
        t0 = time.perf_counter()
        topic.tick()
        t1 = time.perf_counter()
        for part in hub.parts[before:]:
            if part is not None:
                encode(part)
                rows.append(len(part.records))
        t2 = time.perf_counter()
        build.append((t1 - t0) * 1000)
        enc.append((t2 - t1) * 1000)
    total = [b + e for b, e in zip(build, enc, strict=True)]
    q = statistics.quantiles

    def pct(xs: list[float], k: int) -> float:
        return q(xs, n=100)[k - 1] if len(xs) > 1 else (xs[0] if xs else 0.0)

    p95 = pct(total, 95)
    return Report(
        columns=len(build), rows_p50=statistics.median(rows) if rows else 0.0,
        build_ms_p50=statistics.median(build), build_ms_p95=pct(build, 95),
        build_ms_p99=pct(build, 99), encode_ms_p95=pct(enc, 95), total_ms_p95=p95,
        budget_6_ms=BUDGET_6_MS, budget_6_pass=p95 <= BUDGET_6_MS,
        budget_14_pass=max(total) < CADENCE_MS, source=source,
    )  # fmt: skip


#: The b64 budget of one outbound frame at the 4 MiB cap, less a generous envelope (§3.6).
RENDER_BUDGET: Final = 3 * 1_048_576


@dataclass
class _RenderSub:
    """The fields of a binary live `heatmap` subscription `render` reads."""

    topic: Any = field(
        default_factory=lambda: SimpleNamespace(family=SimpleNamespace(family=FAMILY))
    )
    effective: dict[str, Any] = field(default_factory=lambda: {"encoding": "binary"})
    replay_session_id: str | None = None


def _emit_turns(
    topic: HeatmapTopic, lease: Any, encoding: str, sliced: bool, connections: int = 1
) -> tuple[list[float], list[float]]:
    """Every loop turn's wall time and CPU of `connections` concurrent `snap`s of `lease`'s spec
    through the gateway's emitters, ms: the turn that asked (every inline slice together) and
    each turn of the shared budget (`sequencing._Turns`). The frames go to a queue that encodes
    as the pipeline does (`json_payload`)."""

    async def run_all() -> tuple[list[float], list[float]]:
        parsed = parse_topic(f"heatmap.{SYMBOL}")
        opts = {"encoding": encoding, "window_seconds": 900}
        left = [connections]
        done = asyncio.Event()

        def finished(frame: dict[str, Any]) -> None:
            if frame.get("s") is not None:
                left[0] -= 1
                if not left[0]:
                    done.set()

        def push(frame: dict[str, Any]) -> None:
            json_payload(frame)  # the queue encodes at push
            finished(frame)

        def push_encoded(frame: dict[str, Any], payload: str | bytes, _r: float | None) -> None:
            finished(frame)

        pairs = []
        for n in range(connections):
            sub = Subscription(f"s{n}", parsed, opts, effective_options(parsed, opts))
            sub.heatmap_lease = lease
            emitter = TopicEmitter(push, connection_id=f"bench{n}", wall_ms=lambda: T0,
                                   clock=time.monotonic, source=cast(Any, topic),
                                   cache=SnapshotCache(max_bytes=0))  # fmt: skip
            if sliced:
                emitter.push_encoded, emitter.encode_payload = push_encoded, json_payload
                emitter.wire = "json"
            else:
                emitter.turn_s = 1e9
            pairs.append((emitter, sub))
        wall: list[float] = []
        cpu: list[float] = []
        turn = sequencing._Turns._turn

        def timed(self: Any) -> None:
            began, began_cpu = time.perf_counter(), time.thread_time()
            turn(self)
            wall.append((time.perf_counter() - began) * 1000)
            cpu.append((time.thread_time() - began_cpu) * 1000)

        sequencing._Turns._turn = timed  # type: ignore[method-assign]  # timed for the bench
        try:
            began, began_cpu = time.perf_counter(), time.thread_time()
            for emitter, sub in pairs:
                emitter.snapshot(sub, "initial")
            wall.insert(0, (time.perf_counter() - began) * 1000)
            cpu.insert(0, (time.thread_time() - began_cpu) * 1000)
            await asyncio.wait_for(done.wait(), 300)
        finally:
            sequencing._Turns._turn = turn  # type: ignore[method-assign]
        return wall, cpu

    return asyncio.run(run_all())


def emit_scenario(report: Report, topic: HeatmapTopic, lease: Any) -> Report:
    for encoding in ("binary", "structured"):
        one, _ = _emit_turns(topic, lease, encoding, sliced=False)
        turns, cpu = _emit_turns(topic, lease, encoding, sliced=True)
        setattr(report, f"emit_{encoding}_sliced_cpu_max_ms", max(cpu))
        many, many_cpu = _emit_turns(topic, lease, encoding, sliced=True, connections=8)
        setattr(report, f"emit_{encoding}_8_connections_turn_max_ms", max(many))
        setattr(report, f"emit_{encoding}_8_connections_cpu_max_ms", max(many_cpu))
        # the turn that asked runs each request's own slice; the shared budget covers the rest
        setattr(report, f"emit_{encoding}_8_connections_asking_turn_cpu_ms", many_cpu[0])
        setattr(report, f"emit_{encoding}_8_connections_later_turn_cpu_max_ms", max(many_cpu[1:]))
        p95 = statistics.quantiles(turns, n=100)[94] if len(turns) > 1 else turns[0]
        setattr(report, f"emit_{encoding}_one_turn_ms", max(one))
        setattr(report, f"emit_{encoding}_sliced_p95_ms", p95)
        setattr(report, f"emit_{encoding}_sliced_max_ms", max(turns))
        setattr(report, f"emit_{encoding}_turns", len(turns))
    opts = {"encoding": "structured", "window_seconds": 900}
    parsed = parse_topic(f"heatmap.{SYMBOL}")
    sub = Subscription("s2", parsed, opts, effective_options(parsed, opts))
    sub.heatmap_lease = lease
    body = topic.build(cast(Any, sub))
    report.emit_structured_columns = len(body.structured["columns"]) if body else 0
    return report


def snapshot_and_seed(report: Report, seed: int) -> Report:
    """Fable M-1: `build()` for a binary `sub` at the default budget (8 MiB, 2 000 frames) over a
    full ring of 2 000 cached 512-row columns, the CVWB encode of its parts (what the gateway's
    render then does, once per generation), `hold()` of a coarser grouping and every loop turn of
    its re-seed."""
    rng = random.Random(seed)  # noqa: S311 - seeded synthetic columns, not crypto
    hub = _Hub()
    topic = HeatmapTopic(
        hub, engine=lambda _s: None, steps=lambda _s: (TICK, QTY_STEP), part=heatmap_part,
        body=SnapshotBody, bus=Bus(), env="live", queue_bytes=8_388_608, queue_frames=2_000,
        clock_ms=lambda: float(T0),
    )  # fmt: skip
    spec = HeatmapSpec(SYMBOL, time_bucket_ms=COLUMN_MS)
    lease = topic.hold("a", spec)
    st = topic._symbols[SYMBOL]
    st.tier = 500  # as a live book would set it
    state = st.specs[spec]
    raw = [
        np.asarray([rng.randint(0, 9_000) / 1_000 for _ in range(2 * ROWS)]).tobytes()
        for _ in range(2_000)
    ]
    tracemalloc.start()
    before = tracemalloc.get_traced_memory()[0]
    for i, data in enumerate(raw):  # M-B: what the ring holds per column, measured
        bids, asks = array("d"), array("d")
        bids.frombytes(data[: 8 * ROWS])
        asks.frombytes(data[8 * ROWS :])
        column = HeatmapColumn(T0 + 100 * i, 100, 630_924, 1, bids, asks, 631_180, 631_181, 0.0,
                               0.0, False, 1, 1)  # fmt: skip
        state.ring.append(_Entry(column))
    held = tracemalloc.get_traced_memory()[0] - before
    tracemalloc.stop()
    report.ring_entry_bytes = held // len(raw)
    report.ring_spec_mib = held / 2**20
    columns = [e.column for e in list(state.ring)[:1_000]]
    began = time.perf_counter()
    for c in columns:  # the dict path `rebucket` took before it was vectorised
        prices = [c.price_origin_ticks + i * c.price_step_ticks for i in range(c.rows)]
        window_column(ts_ms=c.ts_ms, bucket_ms=c.bucket_ms, step=2,
                      bids=dict(zip(prices, c.bid_sizes, strict=True)),
                      asks=dict(zip(prices, c.ask_sizes, strict=True)),
                      best_bid=c.best_bid_ticks, best_ask=c.best_ask_ticks, estimated=False,
                      samples=1, expected=1, origin_hint=c.price_origin_ticks)  # fmt: skip
    report.rebucket_dict_ms = (time.perf_counter() - began) * 1000
    began = time.perf_counter()
    for c in columns:
        rebucket(c, 2)
    report.rebucket_numpy_ms = (time.perf_counter() - began) * 1000
    sub = _Sub(lease, effective={"encoding": "binary", "window_seconds": 900})
    t0 = time.perf_counter()
    body = topic.build(sub)
    t1 = time.perf_counter()
    if not isinstance(body, SnapshotBody):
        raise RuntimeError("the spec is ready, so a snapshot is built")
    for frame in body.parts:
        encode_b64(frame)
    t2 = time.perf_counter()
    encode_ms = (t2 - t1) * 1000
    plain = replace(body, parts=tuple(decode(encode(p)) for p in body.parts))
    for name, snap in (("packed", body), ("plain", plain)):
        runs = []
        for _ in range(20):
            began = time.perf_counter()
            render(cast(Any, _RenderSub()), snap, RENDER_BUDGET)
            runs.append((time.perf_counter() - began) * 1000)
        setattr(report, f"render_{name}_ms_p95", statistics.quantiles(runs, n=100)[94])
        setattr(report, f"render_{name}_ms_max", max(runs))
    t2 = time.perf_counter()
    emit_scenario(report, topic, lease)
    t2 = time.perf_counter()
    topic.hold("b", HeatmapSpec(SYMBOL, price_grouping=2, time_bucket_ms=COLUMN_MS))
    t3 = time.perf_counter()
    turns: list[float] = []
    while any(s.seed for s in st.specs.values()):
        began = time.perf_counter()
        topic._seed_turn()
        turns.append((time.perf_counter() - began) * 1000)
    report.snapshot_columns = len(body.parts)
    report.snapshot_build_ms = (t1 - t0) * 1000
    report.snapshot_encode_ms = encode_ms
    report.hold_ms = (t3 - t2) * 1000
    report.reseed_turns = len(turns)
    report.reseed_turn_p95_ms = statistics.quantiles(turns, n=100)[94] if len(turns) > 1 else 0.0
    report.reseed_turn_max_ms = max(turns, default=0.0)
    report.reseed_total_ms = sum(turns)
    report.steady_core_share_at_cap = 32 * 10 * report.build_ms_p50 / 1000
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--columns", type=int, default=3000)
    ap.add_argument("--changes", type=int, default=40, help="levels changed per column")
    ap.add_argument("--seed", type=int, default=605)
    ap.add_argument("--capture", default=os.environ.get("CV_HEATMAP_BENCH_CAPTURE"))
    ap.add_argument("--out")
    args = ap.parse_args()
    if args.capture:
        events, source = _recorded(Path(args.capture), args.columns), f"capture:{args.capture}"
    else:
        events, source = _synthetic(args.columns, args.changes, args.seed), "synthetic"
    report = snapshot_and_seed(asyncio.run(run(events, source)), args.seed)
    text = json.dumps(asdict(report), indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
