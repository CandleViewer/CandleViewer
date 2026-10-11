"""Seek stages for E26-K01, timed separately (`24-internal-schemas.md` Sec.13.7 algorithm).

Stage names are the metric label values proposed for `replay_seek_duration_ms{stage=...}`:
`anchor_load`, `delta_apply`, `builder_restore`, `warmup`. All four use the real engines:
`candleviewer.book.state.BookState` (snapshot rebuild + per-frame `apply`, invariants checked per
frame) and `candleviewer.bars` (`TimeBarBuilder` + `StateStore` file round-trip).
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import numpy as np
import pyarrow as pa

from bench.replay_seek.sources import Source
from bench.replay_seek.synth import SPAN0_US, SYMBOL
from candleviewer.bars.models import BarSpec
from candleviewer.bars.state_store import StateStore, StoredState
from candleviewer.bars.time_builder import TimeBarBuilder
from candleviewer.book.state import BookState
from candleviewer.exchange.base.models import BookLevel, TradeEvent
from candleviewer.storage.models import StreamKind

STAGES = ("anchor_load", "delta_apply", "builder_restore", "warmup")
CHECKPOINT_S = 60  # BuilderState checkpoint cadence (24-internal Sec.3.2 / Sec.13.7 step 4)
WARMUP_BARS = 20  # max(warmup_bars) assumed for the indicator set (1 m bars)
SPEC = BarSpec(kind="time", interval_ms=60_000)
_TICK = Decimal("0.1")
_EID = uuid.UUID(int=0xE26)


def _lvl(price: float, qty: float) -> BookLevel:
    ticks = round(price * 10)
    return BookLevel.model_construct(
        price=Decimal(ticks) * _TICK, qty=Decimal(str(qty)), price_ticks=ticks
    )


def book_from_snapshot(row: dict[str, object], depth: int) -> BookState:
    bids = [_lvl(float(p), float(q)) for p, q in json.loads(str(row["bids"]))]
    asks = [_lvl(float(p), float(q)) for p, q in json.loads(str(row["asks"]))]
    return BookState.from_levels(depth, bids, asks)


def apply_deltas(book: BookState, t: pa.Table) -> int:
    """Group level-rows into frames by `update_id` and `apply` each frame; returns frame count."""
    if t.num_rows == 0:
        return 0
    uid = t.column("update_id").to_numpy()
    side = np.asarray(t.column("side").to_pylist())
    price = t.column("price").to_numpy()
    size = t.column("size").to_numpy()
    cuts = np.flatnonzero(np.diff(uid)) + 1
    frames = 0
    for a, b in zip(np.r_[0, cuts], np.r_[cuts, len(uid)], strict=True):
        bids: list[BookLevel] = []
        asks: list[BookLevel] = []
        for i in range(int(a), int(b)):
            (bids if side[i] == "bid" else asks).append(_lvl(float(price[i]), float(size[i])))
        book.apply(bids, asks)
        frames += 1
    return frames


def apply_collapsed(book: BookState, t: pa.Table) -> tuple[BookState, int]:
    """Seek-only mitigation: keep the last write per `(side, price)`, then rebuild the book once
    (intermediate frames are never observed during a seek). Returns `(book, collapsed levels)`."""
    if t.num_rows == 0:
        return book, 0
    is_ask = np.asarray(t.column("side").to_pylist()) == "ask"
    ticks = np.rint(t.column("price").to_numpy() * 10).astype(np.int64)
    key = is_ask.astype(np.int64) * (1 << 40) + ticks
    _, rev_first = np.unique(key[::-1], return_index=True)
    last = len(key) - 1 - rev_first
    size = t.column("size").to_numpy()
    bids, asks = book.as_dicts()
    for i in last.tolist():
        side = asks if is_ask[i] else bids
        q = Decimal(str(float(size[i])))
        if q == 0:
            side.pop(int(ticks[i]), None)
        else:
            side[int(ticks[i])] = q

    def lv(d: dict[int, Decimal]) -> list[BookLevel]:
        return [
            BookLevel.model_construct(price=Decimal(k) * _TICK, qty=v, price_ticks=k)
            for k, v in d.items()
        ]

    return BookState.from_levels(book.depth, lv(bids), lv(asks)), len(last)


def _trades(t: pa.Table) -> list[TradeEvent]:
    ts = t.column("ts").cast(pa.int64()).to_numpy()
    px = t.column("price").to_numpy()
    sz = t.column("size").to_numpy()
    sd = t.column("side").to_pylist()
    seq = t.column("seq").to_numpy()
    out = []
    for i in range(t.num_rows):
        ticks = round(float(px[i]) * 10)
        price, qty = Decimal(ticks) * _TICK, Decimal(str(float(sz[i])))
        out.append(
            TradeEvent.model_construct(
                schema_version=1,
                event_id=_EID,
                ts_event=int(ts[i]),
                ts_ingest=int(ts[i]),
                source="replay",
                category="linear",
                symbol=SYMBOL,
                trade_id=f"t{int(seq[i]):x}",
                price=price,
                qty=qty,
                side="buy" if sd[i] == "Buy" else "sell",
                is_block_trade=False,
                price_ticks=ticks,
                notional=price * qty,
                seq=int(seq[i]),
            )
        )
    return out


async def write_checkpoint(src: Source, store: StateStore, ckpt_us: int) -> int:
    """Pre-seek setup (not timed): the BuilderState persisted at `ckpt_us`."""
    b = TimeBarBuilder(SPEC, SYMBOL)
    for t in _trades(src.range(StreamKind.TRADES, SPAN0_US, ckpt_us)):
        b.on_trade(t)
    await store.save(StoredState(b.snapshot(), None))
    return store.path(SYMBOL, SPEC.spec_hash).stat().st_size


@dataclass(slots=True)
class SeekResult:
    target_us: int
    anchor_us: int
    frames: int
    delta_rows: int
    trades_replayed: int
    stage_ms: dict[str, float]
    book_ok: bool


async def seek(
    src: Source,
    store: StateStore,
    depth: int,
    target_us: int,
    interval_s: int,
    truth: BookState | None = None,
    collapse: bool = False,
) -> SeekResult:
    ms: dict[str, float] = {}
    rel = target_us - SPAN0_US
    anchor = SPAN0_US + rel - rel % (interval_s * 1_000_000)
    t0 = time.perf_counter()
    book = book_from_snapshot(src.snapshot_at(anchor), depth)
    t1 = time.perf_counter()
    ms["anchor_load"] = (t1 - t0) * 1e3
    deltas = src.range(StreamKind.ORDERBOOK_DELTA, anchor, target_us + 1)
    if collapse:
        book, frames = apply_collapsed(book, deltas)
    else:
        frames = apply_deltas(book, deltas)
    t2 = time.perf_counter()
    ms["delta_apply"] = (t2 - t1) * 1e3
    ckpt = SPAN0_US + rel - rel % (CHECKPOINT_S * 1_000_000)
    stored, why = await store.load(SYMBOL, SPEC.spec_hash)
    if stored is None:
        raise RuntimeError(f"checkpoint {why}")
    builder = TimeBarBuilder(SPEC, SYMBOL)
    builder.restore(stored.state)
    trades = _trades(src.range(StreamKind.TRADES, ckpt, target_us + 1))
    for t in trades:
        builder.on_trade(t)
    t3 = time.perf_counter()
    ms["builder_restore"] = (t3 - t2) * 1e3
    # warm-up: rebuild WARMUP_BARS closed 1 m bars before the checkpoint and run an EMA over them
    w0 = max(SPAN0_US, ckpt - WARMUP_BARS * 60_000_000)
    warm = TimeBarBuilder(SPEC, SYMBOL)
    closes: list[Decimal] = []
    for t in _trades(src.range(StreamKind.TRADES, w0, ckpt)):
        closes += [u.bar.close for u in warm.on_trade(t) if u.kind == "close"]
    ema, k = None, Decimal(2) / Decimal(15)
    for c in closes:
        ema = c if ema is None else ema + k * (c - ema)
    ms["warmup"] = (time.perf_counter() - t3) * 1e3
    ok = truth is None or truth.as_dicts() == book.as_dicts()
    return SeekResult(target_us, anchor, frames, deltas.num_rows, len(trades), ms, ok)


def run_seek(
    src: Source, store_root: Path, depth: int, target_us: int, interval_s: int
) -> SeekResult:
    store = StateStore(store_root)

    async def go() -> SeekResult:
        rel = target_us - SPAN0_US
        await write_checkpoint(src, store, SPAN0_US + rel - rel % (CHECKPOINT_S * 1_000_000))
        return await seek(src, store, depth, target_us, interval_s)

    return asyncio.run(go())
