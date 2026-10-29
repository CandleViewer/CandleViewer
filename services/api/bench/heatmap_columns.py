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
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from candleviewer.book.resync import BookEngine
from candleviewer.bus.bus import Bus
from candleviewer.domain.primitives import EventId
from candleviewer.exchange.base.models import BookDelta, BookLevel, BookSnapshot
from candleviewer.orderflow.heatmap import COLUMN_MS, ROWS, HeatmapSpec, HeatmapTopic
from candleviewer.ws.binary import encode
from candleviewer.ws.sequencing import SnapshotBody
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
    report = asyncio.run(run(events, source))
    text = json.dumps(asdict(report), indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
