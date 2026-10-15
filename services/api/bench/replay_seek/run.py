"""E26-K01 harness: seek cost, source throughput, merge cost, read-ahead RSS. Seeded, no network.

Run from `services/api` (input is a SYNTHETIC 200-depth day - see `synth.py`):

    PYTHONPATH=. python -m bench.replay_seek.run --rows 3000000 --depth 200 \
        --snapshot-interval 300 --snapshot-interval 60 --snapshot-interval 30 --out out.json

`--rows` sizes the synthetic span (delta level-rows); the span never drops below what the largest
interval's worst case needs. Results are per synthetic span and are extrapolated to a 24 h day in
the note, never here. The hot column is an IN-MEMORY STAND-IN unless run by the integration bench.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import heapq
import json
import logging
import math
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import psutil
import pyarrow as pa
import pyarrow.parquet as pq
import structlog

from bench.replay_seek import seek as sk
from bench.replay_seek import synth
from bench.replay_seek.sources import ColdSource, HotStandIn, Source, export_cold
from candleviewer.bars.state_store import StateStore
from candleviewer.storage.models import StreamKind

SCHEMA_VERSION = 1
BUFFER_WINDOWS_S = (5, 30, 120)
SPEED = 100
DAY_S = 86_400
LABEL = "SYNTHETIC 200-depth day (no E16 recorded day exists); laptop, not WSL/docker target"


def _pct(xs: list[float], q: float) -> float:
    s = sorted(xs)
    return s[min(len(s) - 1, math.ceil(q * len(s)) - 1)]


def _summary(xs: list[float]) -> dict[str, float]:
    return {
        "p50": round(statistics.median(xs), 2),
        "p95": round(_pct(xs, 0.95), 2),
        "max": round(max(xs), 2),
    }


def min_span_s(intervals: list[int]) -> int:
    """Span covering the window that contains the busiest minute, for every interval."""
    end = synth.BUSY_OFFSET_S + 60
    return max(math.ceil(end / i) * i for i in intervals)


def _tables(s: synth.Synth) -> dict[StreamKind, pa.Table]:
    return {
        StreamKind.ORDERBOOK_DELTA: s.deltas,
        StreamKind.ORDERBOOK_SNAPSHOT: s.snapshots,
        StreamKind.TRADES: s.trades,
    }


def measure_seek(
    src: Source, depth: int, interval: int, repeats: int, work: Path, collapse: bool = False
) -> dict[str, Any]:
    """Worst case: target = 1 us before the next snapshot, in the window holding the busiest minute;
    plus the same in the first (calm) window. Ground truth = the next snapshot. `collapse` uses the
    last-write-wins delta mitigation (`seek.apply_collapsed`) instead of frame-by-frame apply."""
    out: dict[str, Any] = {"interval_s": interval}
    busy_w = (synth.BUSY_OFFSET_S // interval) * interval
    for name, w0 in (("busy_window", busy_w), ("calm_window", 0)):
        end = synth.SPAN0_US + (w0 + interval) * 1_000_000
        truth = sk.book_from_snapshot(src.snapshot_at(end), depth)
        store = StateStore(work / f"state-{interval}-{name}")
        rel = end - 1 - synth.SPAN0_US
        ckpt = synth.SPAN0_US + rel - rel % (sk.CHECKPOINT_S * 1_000_000)
        blob = asyncio.run(sk.write_checkpoint(src, store, ckpt))
        runs = [
            asyncio.run(sk.seek(src, store, depth, end - 1, interval, truth, collapse))
            for _ in range(repeats)
        ]
        totals = [sum(r.stage_ms.values()) for r in runs]
        out[name] = {
            "window_start_s": w0,
            "frames": runs[0].frames,
            "delta_rows": runs[0].delta_rows,
            "trades_replayed": runs[0].trades_replayed,
            "builder_blob_bytes": blob,
            "book_matches_next_snapshot": all(r.book_ok for r in runs),
            "total_ms": _summary(totals),
            "stage_ms": {st: _summary([r.stage_ms[st] for r in runs]) for st in sk.STAGES},
        }
    return out


def snapshot_disk_cost(s: synth.Synth, intervals: list[int], work: Path) -> list[dict[str, Any]]:
    """Recorder disk per day for each interval: modelled QuestDB bytes (UTF-16 STRING, Sec.11.1
    convention) and measured ZSTD Parquet bytes/row of the synthetic snapshots."""
    snaps = s.snapshots
    json_chars = statistics.mean(
        len(b) + len(a)
        for b, a in zip(
            snaps.column("bids").to_pylist(), snaps.column("asks").to_pylist(), strict=True
        )
    )
    hot_row = 2 * json_chars + 2 * 12 + 8 * 7 + 4 * 4
    p = work / "snap.parquet"
    pq.write_table(snaps, p, compression="zstd", compression_level=6)
    pq_row = p.stat().st_size / snaps.num_rows
    out = []
    for i in intervals:
        rows = DAY_S // i
        out.append(
            {
                "interval_s": i,
                "rows_per_day": rows,
                "hot_mb_per_day_modelled": round(rows * hot_row / 1e6, 1),
                "parquet_mb_per_day": round(rows * pq_row / 1e6, 1),
                "hot_bytes_per_row": round(hot_row),
                "parquet_bytes_per_row": round(pq_row),
            }
        )
    return out


def _events(t: pa.Table, kind: int) -> Iterator[tuple[int, int, int]]:
    ts = t.column("ts").cast(pa.int64()).to_numpy()
    seq = t.column("update_id" if kind == 0 else "seq").to_numpy()
    return zip(ts.tolist(), seq.tolist(), [kind] * len(ts), strict=True)


def merge_cost(d: pa.Table, t: pa.Table) -> dict[str, float]:
    """`heapq.merge` of the delta and trade streams on `(ts_event, seq)`; Python-level per event."""
    t0 = time.perf_counter()
    n = sum(1 for _ in heapq.merge(_events(d, 0), _events(t, 1)))
    dt = time.perf_counter() - t0
    return {"events": n, "seconds": round(dt, 3), "events_per_s": round(n / dt)}


def throughput(cold: ColdSource, hot: HotStandIn, s: synth.Synth, repeats: int) -> dict[str, Any]:
    end = synth.SPAN0_US + s.span_s * 1_000_000
    b0 = (
        synth.SPAN0_US + synth.BUSY_OFFSET_S * 1_000_000
    )  # hot dict rows: busiest minute only (RSS)
    res: dict[str, Any] = {}
    for label, fn in (
        (
            "cold_pyarrow_range",
            lambda: cold.range(StreamKind.ORDERBOOK_DELTA, synth.SPAN0_US, end).num_rows,
        ),
        ("cold_duckdb_scan", lambda: cold.duckdb_scan(StreamKind.ORDERBOOK_DELTA)),
        (
            "hot_standin_rows_busiest_minute",
            lambda: hot.range(StreamKind.ORDERBOOK_DELTA, b0, b0 + 60_000_000).num_rows,
        ),
    ):
        rates = []
        for _ in range(repeats):
            t0 = time.perf_counter()
            n = fn()
            rates.append(n / (time.perf_counter() - t0))
        res[label] = {"rows": n, "events_per_s": _summary(rates)}
    res["merge"] = merge_cost(s.deltas, s.trades)
    return res


def busiest_minute(s: synth.Synth) -> dict[str, Any]:
    lo = synth.SPAN0_US + synth.BUSY_OFFSET_S * 1_000_000
    hi = lo + 60_000_000
    ts_d, ts_t = s.deltas.column("ts").to_numpy(), s.trades.column("ts").to_numpy()
    nd = int(np.count_nonzero((ts_d >= lo) & (ts_d < hi)))
    nt = int(np.count_nonzero((ts_t >= lo) & (ts_t < hi)))
    return {
        "delta_rows": nd,
        "trades": nt,
        "events": nd + nt,
        "required_events_per_s_at_100x": round((nd + nt) * SPEED / 60),
    }


def buffer_needed(busy: dict[str, Any], sustained: float, bytes_per_event: float) -> dict[str, Any]:
    """Prefetched buffer that keeps the 100x clock from stalling across the busiest minute, given a
    reader sustaining `sustained` events/s: deficit = events - sustained * 60 s / SPEED."""
    wall = 60 / SPEED
    deficit = max(0.0, busy["events"] - sustained * wall)
    return {
        "sustained_events_per_s": round(sustained),
        "busy_wall_s_at_100x": wall,
        "deficit_events": round(deficit),
        "buffer_mb": round(deficit * bytes_per_event / 1e6, 1),
        "buffer_replay_s": round(deficit / max(1.0, busy["events"] / 60), 1),
        "stalls_without_buffer": deficit > 0,
    }


def rss_probe(cold_root: str, window_s: int) -> dict[str, float]:
    """Subprocess body: hold `window_s` of the busiest region as Arrow (prefetched window) and as
    decoded event tuples; report peak RSS growth."""
    from candleviewer.storage.cold.layout import DatasetRegistry

    proc = psutil.Process()
    cold = ColdSource(DatasetRegistry(cold_root), synth.SYMBOL)
    cold.files(StreamKind.ORDERBOOK_DELTA)
    gc.collect()
    base = proc.memory_info().rss
    lo = synth.SPAN0_US + synth.BUSY_OFFSET_S * 1_000_000
    t = cold.range(StreamKind.ORDERBOOK_DELTA, lo, lo + window_s * 1_000_000)
    arrow = proc.memory_info().rss
    ev = list(_events(t, 0))
    peak = proc.memory_info().rss
    return {
        "window_s": window_s,
        "rows": t.num_rows,
        "arrow_mb": round((arrow - base) / 1e6, 1),
        "arrow_plus_tuples_mb": round((peak - base) / 1e6, 1),
        "events_held": len(ev),
    }


def read_ahead(cold_root: Path) -> list[dict[str, float]]:
    out = []
    for w in BUFFER_WINDOWS_S:
        cmd = [
            sys.executable,
            "-m",
            "bench.replay_seek.run",
            "--rss-probe",
            str(w),
            "--cold-root",
            str(cold_root),
        ]
        res = subprocess.run(  # noqa: S603 - fixed argv: this interpreter + this module
            cmd,
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).resolve().parents[2],
            env={**os.environ, "PYTHONPATH": "."},
        )
        out.append(json.loads(res.stdout.strip().splitlines()[-1]))
    return out


def machine() -> dict[str, Any]:
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu": platform.processor(),
        "logical_cpus": os.cpu_count(),
        "ram_gb": round(psutil.virtual_memory().total / 1e9, 1),
    }


def run(
    rows: int,
    depth: int,
    intervals: list[int],
    profile: str,
    repeats: int,
    seed: int,
    work: Path,
    probe_rss: bool = True,
) -> dict[str, Any]:
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))
    p = synth.PROFILES[profile]
    span = synth.span_for_rows(p, rows, min_span_s(intervals))
    t0 = time.perf_counter()
    s = synth.generate(p, depth, span, seed)
    gen_s = time.perf_counter() - t0
    tables = _tables(s)
    end = synth.SPAN0_US + span * 1_000_000 + 1
    cold_root = work / "cold"
    t0 = time.perf_counter()
    registry = asyncio.run(
        export_cold(cold_root, synth.SYMBOL, tables, synth.SPAN0_US, end, 250_000)
    )
    export_s = time.perf_counter() - t0
    cold, hot = ColdSource(registry, synth.SYMBOL), HotStandIn(tables)
    seeks = {
        src.label: [measure_seek(src, depth, i, repeats, work) for i in intervals]
        for src in (cold, hot)
    }
    seeks[cold.label + " + collapsed deltas (mitigation)"] = [
        measure_seek(cold, depth, i, repeats, work, collapse=True) for i in intervals
    ]
    busy = busiest_minute(s)
    thr = throughput(cold, hot, s, repeats)
    bpe = s.deltas.nbytes / s.deltas.num_rows
    sustained = min(thr["cold_pyarrow_range"]["events_per_s"]["p50"], thr["merge"]["events_per_s"])
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "label": LABEL,
        "machine": machine(),
        "params": {
            "rows": rows,
            "depth": depth,
            "intervals": intervals,
            "profile": profile,
            "repeats": repeats,
            "seed": seed,
            "span_s": span,
        },
        "corpus": {
            "delta_rows": s.deltas.num_rows,
            "trades": s.trades.num_rows,
            "snapshots": s.snapshots.num_rows,
            "generate_s": round(gen_s, 1),
            "cold_export_s": round(export_s, 1),
            "arrow_bytes_per_delta_row": round(bpe, 1),
            "delta_rows_per_frame": round(s.deltas.num_rows / (span * 10), 1),
            "scale_to_24h": round(DAY_S / span, 1),
        },
        "seek": seeks,
        "snapshot_disk": snapshot_disk_cost(s, intervals, work),
        "throughput": thr,
        "busiest_minute": busy,
        "buffer_100x": buffer_needed(busy, sustained, bpe),
        "read_ahead_rss": read_ahead(cold_root) if probe_rss else [],
        "peak_rss_mb": round(psutil.Process().memory_info().rss / 1e6),
    }
    return report


def to_markdown(r: dict[str, Any]) -> str:
    lines = [
        f"Label: **{r['label']}** (span {r['params']['span_s']} s, profile "
        f"{r['params']['profile']}, x{r['corpus']['scale_to_24h']} to 24 h)",
        "",
        "| source | interval s | window | frames | p50 ms | p95 ms | max ms | anchor | delta | "
        "builder | warmup | book ok |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for src, rows in r["seek"].items():
        for row in rows:
            for w in ("busy_window", "calm_window"):
                x = row[w]
                st = " | ".join(str(x["stage_ms"][k]["p50"]) for k in sk.STAGES)
                lines.append(
                    f"| {src} | {row['interval_s']} | {w} | {x['frames']} | "
                    f"{x['total_ms']['p50']} | {x['total_ms']['p95']} | {x['total_ms']['max']}"
                    f" | {st} | {x['book_matches_next_snapshot']} |"
                )
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rows", type=int, default=3_000_000)
    ap.add_argument("--depth", type=int, default=200)
    ap.add_argument("--snapshot-interval", type=int, action="append", choices=(300, 60, 30))
    ap.add_argument("--profile", choices=sorted(synth.PROFILES), default="dense")
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--seed", type=int, default=26_001)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--rss-probe", type=int, help=argparse.SUPPRESS)
    ap.add_argument("--cold-root", help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.rss_probe:
        print(json.dumps(rss_probe(a.cold_root, a.rss_probe)))
        return
    with tempfile.TemporaryDirectory() as tmp:
        r = run(
            a.rows,
            a.depth,
            a.snapshot_interval or [300, 60, 30],
            a.profile,
            a.repeats,
            a.seed,
            Path(tmp),
        )
    text = json.dumps(r, indent=2)
    if a.out:
        a.out.write_text(text + "\n", encoding="utf-8")
        a.out.with_suffix(".md").write_text(to_markdown(r), encoding="utf-8")
    print(to_markdown(r))


if __name__ == "__main__":
    main()
