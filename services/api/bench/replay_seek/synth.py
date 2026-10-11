"""Deterministic SYNTHETIC 200-depth book + tape for E26-K01 (no recorded E16 day exists yet).

The E16 recorder is not wired (#2210/#2188), so there is no real 200-depth symbol-day. This module
generates a seeded stand-in shaped by the documented figures (exception #1778 A pattern):

- `dense`: 220 changed levels per 100 ms frame on average, i.e. `21-database-schema.md` Sec.11.1's
  ~190 M level-rows/day / 864 k frames (BTCUSDT-class, 200 depth).
- `thin`: 5 changed levels per frame, the mean of the recorded corpus
  `packages/fixtures/bybit/2026-10-05/ws/orderbook_BTCUSDT.jsonl` (4.95/frame) - thin contrast.

Both use a busiest-minute spike (`burst_mult`) at `BUSY_OFFSET_S` and an E12-T04-style random walk
of the mid (`vol_ticks`, scaled by sqrt(burst)). Trades come from the E12-T04 generator
(`bench.bar_determinism.generator.iter_trades`), with its rate raised in the busiest minute.
Every delta keeps the book valid (never crossed, at most `depth` levels a side) so the real
`BookState` can apply it.
"""

from __future__ import annotations

import json
import math
import random
import zlib
from array import array
from dataclasses import dataclass, replace

import numpy as np
import pyarrow as pa

from bench.bar_determinism.generator import GenConfig, iter_trades

SYMBOL = "BTCUSDT"
FRAME_US = 100_000  # Bybit orderbook.200 push cadence
SNAP_GRID_S = 30  # every candidate interval (30/60/300 s) is a multiple of this
DAY0_US = 1_791_158_400_000_000  # 2026-10-05T00:00:00Z
SPAN0_US = DAY0_US + 12 * 3_600 * 1_000_000  # span starts 12:00Z
BUSY_OFFSET_S = 600  # busiest minute = [600 s, 660 s) of the span; aligned to every interval
_SIDE = ("bid", "ask")


@dataclass(frozen=True, slots=True)
class Profile:
    name: str
    levels_mean: float  # mean changed levels per 100 ms frame (session average)
    burst_mult: float  # busiest-minute multiplier on levels/frame and trades/s
    trades_per_s: float  # session-average prints/s
    vol_ticks: float  # stdev of the per-frame mid step, in ticks (E12-T04 knob)


DENSE = Profile("dense", 220.0, 3.0, 29.0, 1.6)  # Sec.11.1: 190 M rows/day, 2.5 M trades/day
THIN = Profile("thin", 5.0, 3.0, 2.0, 0.6)  # corpus orderbook_BTCUSDT.jsonl shape
PROFILES = {p.name: p for p in (DENSE, THIN)}


@dataclass(slots=True)
class Synth:
    profile: Profile
    depth: int
    span_s: int
    deltas: pa.Table  # orderbook_deltas columns (21-database-schema.md Sec.4)
    snapshots: pa.Table  # orderbook_snapshots, one every SNAP_GRID_S
    trades: pa.Table  # trades columns


def _mult(t_s: float, p: Profile) -> float:
    if BUSY_OFFSET_S <= t_s < BUSY_OFFSET_S + 60:
        return p.burst_mult
    return 1.0 + 0.25 * math.sin(2 * math.pi * t_s / 1_800)


def _levels_json(side: dict[int, int], descending: bool) -> str:
    keys = sorted(side, reverse=descending)
    return json.dumps([[f"{k / 10:.1f}", f"{side[k] / 1000:.3f}"] for k in keys])


def _gen_book(p: Profile, depth: int, span_s: int, seed: int) -> tuple[pa.Table, pa.Table]:
    rng = random.Random(seed)  # noqa: S311 - reproducible bench data, not crypto
    nrng = np.random.default_rng(seed)
    mid = 631_200
    bids = {mid - k: 1_000 for k in range(1, depth + 1)}
    asks = {mid + k: 1_000 for k in range(1, depth + 1)}
    ts_c, side_c, tick_c, lots_c, act_c, uid_c = (array("q") for _ in range(6))
    s_rows: list[tuple[int, int, str, str, int]] = []

    def emit(ts: int, s: int, tick: int, lots: int, act: int, uid: int) -> None:
        for col, v in zip(
            (ts_c, side_c, tick_c, lots_c, act_c, uid_c), (ts, s, tick, lots, act, uid), strict=True
        ):
            col.append(v)

    for f in range(span_s * 10):
        ts, uid = SPAN0_US + f * FRAME_US, f + 1
        if f % (SNAP_GRID_S * 10) == 0:  # snapshot = book state before the frame at `ts`
            s_rows.append((ts, uid - 1, _levels_json(bids, True), _levels_json(asks, False), 0))
        m = _mult(f / 10, p)
        step = max(-20, min(20, round(rng.gauss(0.0, p.vol_ticks * math.sqrt(m)))))
        new = mid + step
        gone: list[tuple[int, int]] = []
        if step > 0:
            gone += [(1, t) for t in range(mid + 1, new + 1) if t in asks]
            gone += [(0, t) for t in range(mid - depth, new - depth) if t in bids]
        elif step < 0:
            gone += [(0, t) for t in range(new, mid) if t in bids]
            gone += [(1, t) for t in range(new + depth + 1, mid + depth + 1) if t in asks]
        for s, t in gone:
            (bids if s == 0 else asks).pop(t)
            emit(ts, s, t, 0, 2, uid)
        mid = new
        n = min(2 * depth, int(nrng.poisson(p.levels_mean * m)))
        for slot in nrng.choice(2 * depth, size=n, replace=False).tolist():
            s, k = divmod(slot, depth)
            book = bids if s == 0 else asks
            tick = mid - (k + 1) if s == 0 else mid + (k + 1)
            if tick in book and rng.random() < 0.15:
                book.pop(tick)
                emit(ts, s, tick, 0, 2, uid)
            else:
                lots = max(1, int(rng.lognormvariate(0.0, 1.1) * 400))
                emit(ts, s, tick, lots, 1 if tick in book else 0, uid)
                book[tick] = lots
    # the closing snapshot lets a seek to the last frame be checked against ground truth
    end = SPAN0_US + span_s * 10 * FRAME_US
    s_rows.append((end, span_s * 10, _levels_json(bids, True), _levels_json(asks, False), 0))
    return _delta_table(depth, ts_c, side_c, tick_c, lots_c, act_c, uid_c), _snap_table(
        depth, s_rows
    )


def _delta_table(depth: int, *cols: array[int]) -> pa.Table:
    ts, side, tick, lots, act, uid = (np.frombuffer(c, dtype=np.int64) for c in cols)
    n = len(ts)
    action = np.array(["insert", "update", "delete"])[act]
    return pa.table(
        {
            "ts": pa.array(ts, pa.int64()),
            "recv_ts": pa.array(ts + 2_000, pa.int64()),
            "symbol": pa.array([SYMBOL] * n, pa.string()),
            "depth": pa.array(np.full(n, depth, dtype=np.int32)),
            "side": pa.array(np.array(_SIDE)[side]),
            "price": pa.array(tick / 10.0),
            "size": pa.array(lots / 1000.0),
            "action": pa.array(action),
            "update_id": pa.array(uid),
            "cross_seq": pa.array(uid * 7),
            "epoch_id": pa.array(np.ones(n, dtype=np.int64)),
        }
    )


def _snap_table(depth: int, rows: list[tuple[int, int, str, str, int]]) -> pa.Table:
    return pa.table(
        {
            "ts": pa.array([r[0] for r in rows], pa.int64()),
            "recv_ts": pa.array([r[0] + 2_000 for r in rows], pa.int64()),
            "symbol": [SYMBOL] * len(rows),
            "depth": pa.array([depth] * len(rows), pa.int32()),
            "epoch_id": pa.array([1] * len(rows), pa.int64()),
            "update_id": pa.array([r[1] for r in rows], pa.int64()),
            "cross_seq": pa.array([r[1] * 7 for r in rows], pa.int64()),
            "source": ["synthetic"] * len(rows),
            "bids": [r[2] for r in rows],
            "asks": [r[3] for r in rows],
            "level_count": pa.array([len(json.loads(r[2])) for r in rows], pa.int32()),
            "checksum": pa.array([zlib.crc32((r[2] + r[3]).encode()) for r in rows], pa.int64()),
        }
    )


def _gen_trades(p: Profile, span_s: int, seed: int) -> pa.Table:
    """E12-T04 generator, three segments: session / busiest minute (rate x burst) / session."""
    busy_end = min(span_s, BUSY_OFFSET_S + 60)
    segs = [(0, min(span_s, BUSY_OFFSET_S), 1.0), (BUSY_OFFSET_S, busy_end, p.burst_mult)]
    segs.append((busy_end, span_s, 1.0))
    base = GenConfig(seed=seed, vol_ticks=p.vol_ticks, p_late=0.0, p_duplicate=0.0)
    out: list[tuple[int, int, int, bool]] = []
    for i, (a, b, m) in enumerate(segs):
        if b <= a:
            continue
        rate = p.trades_per_s * m
        cfg = replace(
            base, seed=seed + i, n=max(1, int((b - a) * rate)), mean_dt_us=int(1e6 / rate)
        )
        t0 = None
        for t in iter_trades(cfg):
            t0 = t.ts_event if t0 is None else t0
            ts = SPAN0_US + a * 1_000_000 + (t.ts_event - t0)
            if ts < SPAN0_US + b * 1_000_000:
                out.append((ts, t.price_ticks, int(t.qty * 1000), t.side == "buy"))
    out.sort(key=lambda r: r[0])
    n = len(out)
    px = [r[1] / 10 for r in out]
    size = [r[2] / 1000 for r in out]
    return pa.table(
        {
            "ts": pa.array([r[0] for r in out], pa.int64()),
            "recv_ts": pa.array([r[0] + 2_000 for r in out], pa.int64()),
            "symbol": [SYMBOL] * n,
            "side": ["Buy" if r[3] else "Sell" for r in out],
            "price": px,
            "size": size,
            "notional": [a * b for a, b in zip(px, size, strict=True)],
            "trade_id": [f"t{i:x}" for i in range(n)],
            "tick_dir": ["ZeroPlusTick"] * n,
            "is_block": [False] * n,
            "seq": pa.array(range(n), pa.int64()),
        }
    )


def generate(p: Profile, depth: int, span_s: int, seed: int) -> Synth:
    deltas, snaps = _gen_book(p, depth, span_s, seed)
    return Synth(p, depth, span_s, deltas, snaps, _gen_trades(p, span_s, seed))


def span_for_rows(p: Profile, rows: int, min_span_s: int) -> int:
    """Seconds of synthetic book needed for ~`rows` delta rows (never below `min_span_s`)."""
    return max(min_span_s, math.ceil(rows / (p.levels_mean * 10)))
