"""E21-T01 (#604) bench: the book engine and its WS publisher against budgets #5, #6 and #8 of
`06-performance-and-load-standard.md`, on the recorded depth-200 BTCUSDT capture.

The capture (5 400 frames, the 2026-10-05 fixture corpus) is replayed in process through the
production `BookStream` (parser, engine, quote, bus) and `BookTopic` (windows at depths 1, 50 and
200, kind 2 parts), with an in-process hub that counts what each `d` would carry. The clock the
publisher reads moves 100 ms per frame: the venue's depth-200 cadence. No socket, no network
(C-13.5). Only the clean window is replayed (up to the seeded `u` hole at frame 2700).

- **#5, ingestion throughput** (depth 200 at 100 ms, zero dropped messages): every frame is
  applied (no resync, no rejected frame, no bus overflow marker) and the replay rate is far above
  the 10 frames/s the cadence asks for.
- **#6, backend-added latency** (book update to outbound frame, <= 20 ms p95): per frame, the time
  to apply it (`handle_frame`) plus, when a window is due, the time to diff, encode and publish it
  (`pump` + `tick`). The publisher's own conflation hold (20 / 50 / 100 ms, BQ-4) is reported apart:
  it is the contract's cadence, not processing latency. In the app, `cv_ws_fanout_seconds` times the
  hop after the publish.
- **#8, memory per symbol** (<= 300 MB resident): `tracemalloc` of a live 200-level book with its
  engine, quote and three publisher windows, per symbol, over 20 symbols.

Run: `uv run python bench/book_publisher.py [--frames 2700] [--out report.json]`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
import tracemalloc
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from candleviewer.book.snapshot_source import BookSnapshotSource
from candleviewer.book.ws_topic import BookTopic
from candleviewer.bus.bus import Bus
from candleviewer.bus.models import QueuePolicy, StreamInvalidated, TopicPattern

# nosemgrep: cv-adapter-isolation reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.orderbook import book_topic, parse_book_frame
from candleviewer.orderbook_wiring import BookStream

ROOT = Path(__file__).resolve().parents[3]
# nosemgrep: cv-adapter-isolation reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31
CAPTURE = ROOT / "packages/fixtures/bybit/2026-10-05/ws/orderbook_BTCUSDT.jsonl"
SYMBOL = "BTCUSDT"
TICK, QTY_STEP = Decimal("0.1"), Decimal("0.001")
CADENCE_S = 0.1  # the depth-200 stream's cadence
DEPTHS = (1, 50, 200)
HOLE_AT = 2700
BUDGET_6_MS = 20.0
BUDGET_8_MB = 300.0


@dataclass
class _T:
    symbol: str
    depth: int


@dataclass
class _Sub:
    ch: str
    topic: _T
    replay_session_id: str | None = None
    snapshot_pending: bool = False
    ended: bool = False


@dataclass
class _Hub:
    subs: list[_Sub] = field(default_factory=list)
    frames: int = 0
    levels: int = 0
    desyncs: int = 0

    def subscriptions(self, ch: str) -> list[_Sub]:
        return [s for s in self.subs if s.ch == ch]

    def publish(
        self,
        ch: str,
        body: Mapping[str, Any] | None = None,
        *,
        part: Any = None,
        coalesced_count: int = 1,
    ) -> int:
        if body is None:
            raise ValueError("a book `d` carries a structured body")
        self.frames += 1
        self.levels += len(body["bids"]) + len(body["asks"])
        return 1

    def upstream_desync(self, symbol: str) -> int:
        self.desyncs += 1
        return 0

    def flush_pending(self, match: Any = None) -> int:
        return 0


def _body(structured: Mapping[str, Any], records: Any, trailer: Any, **kw: Any) -> Any:
    return structured


async def _noop(_: object = None) -> None:
    return None


def _world(symbol: str, clock: Any) -> tuple[BookStream, BookTopic[Any], _Hub, Any]:
    bus = Bus()
    stream = BookStream(
        bus=bus, env="live", set_desired=lambda _t: None, topic_for=book_topic,
        parse_frame=lambda f: parse_book_frame(f, lambda _s: TICK), resubscribe=_noop,
        is_listed=lambda _s: True, touch=lambda _t: None, clock=clock, now_us=lambda: 0,
        rand=lambda: 0.0,
    )  # fmt: skip
    stream.acquire("bench", symbol)
    hub = _Hub([_Sub(f"book.{symbol}.{d}", _T(symbol, d)) for d in DEPTHS])
    source = BookSnapshotSource(stream.engine, lambda _s: (TICK, QTY_STEP), _body)
    topic: BookTopic[Any] = BookTopic(
        source, hub.subscriptions, hub.publish, hub.upstream_desync, hub.flush_pending,
        lambda r, ps, qs: r, bus=bus, env="live", clock=clock,
    )  # fmt: skip
    topic.open()
    overflow = bus.subscribe(
        "bench-overflow", TopicPattern(env="live", domain="md", symbol=symbol, detail="book"),
        QueuePolicy.INVALIDATE_ON_FULL, maxsize=16_384,
    )  # fmt: skip
    return stream, topic, hub, overflow


def _snap(topic: BookTopic[Any], hub: _Hub) -> None:
    for s in hub.subs:
        if topic.build(s) is None:
            raise RuntimeError(f"{s.ch}: no live book to snap")


def _pct(xs: list[float], q: float) -> float:
    return statistics.quantiles(xs, n=100)[round(q) - 1] if len(xs) > 1 else (xs or [0.0])[0]


async def replay(frames: int = HOLE_AT) -> dict[str, Any]:
    lines = CAPTURE.read_text(encoding="utf-8").splitlines()[:frames]
    now = [0.0]
    stream, topic, hub, overflow = _world(SYMBOL, lambda: now[0])
    await stream.handle_frame(lines[0])
    _snap(topic, hub)  # every depth snapped: its window is held
    added: list[float] = []
    invalidated = 0
    started = time.perf_counter()
    for line in lines[1:]:
        now[0] += CADENCE_S
        t0 = time.perf_counter()
        await stream.handle_frame(line)
        topic.pump()
        topic.tick()
        added.append((time.perf_counter() - t0) * 1000.0)
        while overflow.qsize():  # a reader as fast as the publisher's: any marker is a drop
            invalidated += isinstance(overflow.get_nowait(), StreamInvalidated)
    wall = time.perf_counter() - started
    engine = stream.engine(SYMBOL)
    return {
        "frames": len(lines),
        "deltas_applied": (engine.last_u - 1) if engine is not None else 0,
        "resyncs": engine.resync_count if engine is not None else -1,
        "bus_overflow_markers": invalidated,
        "frames_per_s": round((len(lines) - 1) / wall, 1),
        "budget_5_cadence_frames_per_s": 1 / CADENCE_S,
        "added_ms_p50": round(_pct(added, 50), 4),
        "added_ms_p95": round(_pct(added, 95), 4),
        "added_ms_p99": round(_pct(added, 99), 4),
        "added_ms_max": round(max(added), 4),
        "budget_6_ms": BUDGET_6_MS,
        "conflation_hold_ms": {str(d): w * 1000 for d, w in ((1, 0.02), (50, 0.05), (200, 0.1))},
        "d_frames": hub.frames,
        "d_levels": hub.levels,
        "publisher_resyncs": hub.desyncs,
    }


async def memory(symbols: int = 20) -> dict[str, Any]:
    line = CAPTURE.read_text(encoding="utf-8").splitlines()[0]
    tracemalloc.start()
    base = tracemalloc.take_snapshot()
    held = []
    for i in range(symbols):
        sym = f"S{i:02d}USDT"
        stream, topic, hub, _ = _world(sym, lambda: 0.0)
        await stream.handle_frame(line.replace(SYMBOL, sym))
        _snap(topic, hub)
        held.append((stream, topic, hub))
    after = tracemalloc.take_snapshot()
    tracemalloc.stop()
    grown = sum(s.size_diff for s in after.compare_to(base, "filename"))
    per_symbol_mb = grown / symbols / 1024 / 1024
    return {
        "symbols": symbols,
        "bytes_per_symbol": round(grown / symbols),
        "mb_per_symbol": round(per_symbol_mb, 3),
        "budget_8_mb": BUDGET_8_MB,
    }


@dataclass
class Report:
    throughput_latency: dict[str, Any]
    memory: dict[str, Any]
    verdict: dict[str, bool]


async def run(frames: int = HOLE_AT, symbols: int = 20) -> Report:
    tl = await replay(frames)
    mem = await memory(symbols)
    verdict = {
        "budget_5": tl["resyncs"] == 0 and tl["bus_overflow_markers"] == 0
        and tl["deltas_applied"] == tl["frames"] - 1
        and tl["frames_per_s"] >= tl["budget_5_cadence_frames_per_s"],
        "budget_6": tl["added_ms_p95"] <= BUDGET_6_MS,
        "budget_8": mem["mb_per_symbol"] <= BUDGET_8_MB,
    }  # fmt: skip
    return Report(tl, mem, verdict)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, default=HOLE_AT)
    parser.add_argument("--symbols", type=int, default=20)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = asdict(asyncio.run(run(args.frames, args.symbols)))
    text = json.dumps(report, indent=2)
    print(text)
    if args.out is not None:
        args.out.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
