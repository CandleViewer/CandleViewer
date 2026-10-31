"""Drives the real `StreamWriter` with the E16-Q04 mix and measures it (no network by default).

Two clocks. `virtual` (the soak): the writer's clock is advanced in steps of its own flush interval
(200 ms) and every lane is pumped after each step, so every sample is a flush boundary, where a
healthy writer holds no backlog. `real` (the ingest load): the writer runs its own lane loops on
wall time while the feed is paced on the wall clock in 10 ms slices.

Flush time is the sink's `write_rows` .. `flush` pair on `perf_counter`, the span the writer's
`recorder_flush_duration_seconds` times. The default sink keeps nothing but counts and the modelled
hot-tier bytes of each row (the E16-K01 on-disk model, `bench/storage_measure.py`); `ilp=` writes to
a QuestDB ILP port on loopback instead (the CI pipeline's container), still counted the same way.
The store and the event sink are in memory: dropped rows come from the writer's own counters, so
the reconciliation (`budgets.check_reconciliation`) reads produced, written and gap-accounted rows
from three independent places.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final

import psutil

from bench.ingestion.budgets import Verdict
from bench.ingestion.config import machine_profile
from bench.ingestion.gate import compare, record
from bench.recorder import HARNESS_VERSION
from bench.recorder.budgets import RunResult
from bench.recorder.generator import Delta, Liquidation, Mix, Trade
from bench.storage_measure import DDL, modelled_row_bytes, parse_column_types
from candleviewer.observability.health_probes import SystemEvent
from candleviewer.recorder.writer import (
    STREAMS,
    DiskGate,
    RowSink,
    Stream,
    StreamWriter,
    WriterConfig,
)

LOOPBACK: Final = frozenset({"127.0.0.1", "::1", "localhost"})
T0_US: Final = 1_700_000_000_000_000
OPEN_GATE: Final = DiskGate(halted=lambda: False, position_open=lambda _s: True)
SAMPLE_EVERY_S: Final = 0.2
REAL_SLICE_S: Final = 0.01
BOUNDARY_NUDGE_S: Final = 1e-6


class CountingSink:
    """In-memory `RowSink`: counts rows per table, keeps none."""

    def __init__(self) -> None:
        self.rows: dict[str, int] = {}

    async def write_rows(self, table: str, rows: list[dict[str, object]], ts_us_key: str) -> None:
        self.rows[table] = self.rows.get(table, 0) + len(rows)

    async def flush(self, table: str | None = None) -> None:
        return None


class TimingSink:
    """Wraps a lane's sink: times each write..flush pair and models the rows' hot-tier bytes."""

    def __init__(self, inner: RowSink, perf: Callable[[], float] = time.perf_counter) -> None:
        self.inner, self._perf = inner, perf
        self.flush_ms: list[float] = []
        self.rows: dict[str, int] = {}
        self.hot_bytes = 0
        self._started: dict[str, float] = {}
        self._types: dict[str, dict[str, str]] = {}

    def _model(self, table: str, rows: list[dict[str, object]]) -> int:
        types = self._types.get(table)
        if types is None:
            types = self._types[table] = parse_column_types(DDL, table)
        return sum(modelled_row_bytes(types, row) for row in rows)

    async def write_rows(self, table: str, rows: list[dict[str, object]], ts_us_key: str) -> None:
        self._started.setdefault(table, self._perf())
        await self.inner.write_rows(table, rows, ts_us_key)
        self.rows[table] = self.rows.get(table, 0) + len(rows)
        self.hot_bytes += self._model(table, rows)

    async def flush(self, table: str | None = None) -> None:
        await self.inner.flush(table)
        began = self._started.pop(table, None) if table is not None else None
        if began is not None:
            self.flush_ms.append((self._perf() - began) * 1000)


class MemStore:
    """`RecorderStore` in memory: one live session per symbol, counters summed."""

    def __init__(self) -> None:
        self.dropped: dict[str, int] = {}
        self.received: dict[str, int] = {}
        self.gaps: list[tuple[str, str, datetime, datetime, str]] = []

    async def add_session_counters(
        self, symbol: str, *, env: str, messages_received: int, messages_dropped: int,
        bytes_written: int, reconnect_count: int,
    ) -> bool:  # fmt: skip
        self.received[symbol] = self.received.get(symbol, 0) + messages_received
        self.dropped[symbol] = self.dropped.get(symbol, 0) + messages_dropped
        return True

    async def record_live_gap(
        self, *, symbol: str, env: str, stream: str, gap_start: datetime, gap_end: datetime,
        cause: str,
    ) -> bool:  # fmt: skip
        self.gaps.append((symbol, stream, gap_start, gap_end, cause))
        return True


class MemEvents:
    def __init__(self) -> None:
        self.events: list[SystemEvent] = []

    async def write(self, event: SystemEvent) -> None:
        self.events.append(event)


class VirtualClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def assert_loopback(host: str) -> None:
    if host not in LOOPBACK:
        raise RuntimeError(f"ILP target {host!r} is not loopback (C-12.9, C-13.5)")


@dataclass(slots=True)
class LoadConfig:
    profile: str
    msgs_per_s: float
    duration_s: float
    symbols: tuple[str, ...]
    wal_dir: Path
    clock: str = "real"  # "real" | "virtual"
    seed: int = 7
    depth: int = 200
    ilp: str | None = None  # "host:port" on loopback; None: the counting sink
    rss: Callable[[], int] = field(default=lambda: psutil.Process(os.getpid()).memory_info().rss)


async def _ilp_sinks(target: str) -> dict[Stream, Any]:
    from candleviewer.storage.questdb.ilp_writer import IlpWriter
    from candleviewer.storage.questdb.schemas import ALL_SCHEMAS
    from candleviewer.storage.questdb.wiring import TcpIlpTransport

    host, _, port = target.rpartition(":")
    assert_loopback(host)
    sinks = {s: IlpWriter(TcpIlpTransport(host, int(port)), {s: ALL_SCHEMAS[s]}) for s in STREAMS}
    async with asyncio.timeout(30):
        for sink in sinks.values():
            await sink.start()
    return sinks


async def _dispatch(w: StreamWriter, kind: str, ev: Trade | Delta | Liquidation) -> None:
    if isinstance(ev, Trade):
        await w.on_trade(ev)
    elif isinstance(ev, Delta):
        await w.on_book_delta(ev)
    else:
        await w.on_liquidation(ev)


async def run(cfg: LoadConfig, *, mix: Mix | None = None) -> RunResult:
    """One run; returns what it measured (the verdict is `budgets`' to give). `mix` replaces the
    default phase mix (the soak's reference rates); it must name `cfg.symbols`."""
    if cfg.clock not in ("real", "virtual"):
        raise ValueError(f"clock {cfg.clock!r}: real or virtual")
    ilp = await _ilp_sinks(cfg.ilp) if cfg.ilp else None
    sinks = {s: TimingSink(ilp[s] if ilp else CountingSink()) for s in STREAMS}
    store, events = MemStore(), MemEvents()
    mix = mix or Mix(cfg.symbols, seed=cfg.seed, depth=cfg.depth)
    if mix.symbols != cfg.symbols:
        raise ValueError("the mix must feed the run's symbols")
    virtual = cfg.clock == "virtual"
    vclock = VirtualClock()
    clock: Callable[[], float] = vclock if virtual else time.monotonic
    wall_us: Callable[[], int] = (
        (lambda: T0_US + int(vclock.t * 1e6)) if virtual else (lambda: time.time_ns() // 1000)
    )
    writer = StreamWriter(
        lambda s: sinks[s], store, events, WriterConfig(wal_dir=cfg.wal_dir, env="demo"),
        clock=clock, wall_clock_us=wall_us, disk_gate=OPEN_GATE,
    )  # fmt: skip
    await writer.open()
    writer.seed(cfg.symbols)
    result = RunResult(cfg.profile, cfg.msgs_per_s, cfg.duration_s, cfg.symbols)
    drive = _drive_virtual if virtual else _drive_real
    try:
        result.duration_s = await drive(cfg, writer, mix, vclock, result)
    finally:
        await writer.stop()
        if ilp:
            for sink in ilp.values():
                await sink.stop()
    result.produced_msgs = mix.produced_msgs
    result.produced_rows = {"all": sum(mix.produced_rows.values())}
    result.written_rows = {"all": sum(sum(s.rows.values()) for s in sinks.values())}
    result.dropped_rows = {"all": sum(store.dropped.values())}
    result.flush_ms = [ms for s in sinks.values() for ms in s.flush_ms]
    result.hot_bytes = sum(s.hot_bytes for s in sinks.values())
    result.critical_events = sum(1 for e in events.events if e.severity == "critical")
    return result


def _sample(cfg: LoadConfig, writer: StreamWriter, r: RunResult) -> None:
    r.backlog_rows.append(writer.backlog_rows)
    r.spill_bytes.append(writer.spill_bytes)
    r.rss_bytes.append(cfg.rss())


async def _drive_virtual(
    cfg: LoadConfig, writer: StreamWriter, mix: Mix, clock: VirtualClock, r: RunResult
) -> float:
    """Feed one flush interval at a time, then pump every lane: each sample is a boundary. The
    clock is set just past each boundary (`BOUNDARY_NUDGE_S`), so a row admitted at a step's start
    is due by then whatever the float rounding of `t + 0.2 - t`; the next step's admissions read
    the boundary itself again (1 us earlier, which no writer deadline is near)."""
    step, carry = SAMPLE_EVERY_S, 0.0
    steps = max(1, round(cfg.duration_s / step))
    for i in range(steps):
        start = clock.t = i * step  # rows are admitted at the step's start
        carry += cfg.msgs_per_s * step
        n, carry = int(carry + 1e-9), carry - int(carry + 1e-9)
        for k in range(n):
            ts = T0_US + int((start + step * k / n) * 1e6)
            await _dispatch(writer, *mix.next(ts))
        clock.t = start + step + BOUNDARY_NUDGE_S
        for stream in STREAMS:
            await writer.pump(stream)
        await writer.tick()
        _sample(cfg, writer, r)
    return steps * step


async def _drive_real(
    cfg: LoadConfig,
    writer: StreamWriter,
    mix: Mix,
    _clock: VirtualClock,
    r: RunResult,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> float:
    """Pace the feed on the wall clock in 10 ms slices while the writer's own loops flush."""
    await writer.start()
    began = time.monotonic()
    sent, last_ts, next_sample = 0, 0, SAMPLE_EVERY_S
    while (elapsed := time.monotonic() - began) < cfg.duration_s:
        due = int(cfg.msgs_per_s * min(elapsed + REAL_SLICE_S, cfg.duration_s))
        for _ in range(due - sent):
            last_ts = max(last_ts + 1, time.time_ns() // 1000)
            await _dispatch(writer, *mix.next(last_ts))
        sent = max(sent, due)
        if elapsed >= next_sample:
            _sample(cfg, writer, r)
            next_sample += SAMPLE_EVERY_S
        await sleep(max(0.0, began + elapsed + REAL_SLICE_S - time.monotonic()))
    _sample(cfg, writer, r)
    return time.monotonic() - began


# --- the scripts' common ending -------------------------------------------------------------


BASELINES_DIR: Final = Path(__file__).resolve().parent.parent / "baselines" / "e16"


def load_baseline(name: str, root: Path = BASELINES_DIR) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((root / f"{name}.json").read_text(encoding="utf-8"))
    return data


#: The keys `gate.record` writes; every other key of a committed baseline (its provenance, the
#: E16-K01 figure) is carried over when a run is recorded.
_RECORDED: Final = frozenset({
    "scenario", "harness_version", "machine_profile", "gate", "run_profile", "higher_is_better",
    "profile_scaling", "metrics",
})  # fmt: skip


def record_baseline(
    verdict: Verdict, committed: dict[str, Any], run_profile: str, root: Path = BASELINES_DIR
) -> Path:
    """Record this run's metrics as the baseline, keeping the committed file's own keys. Refused
    under CI (`gate.record`): a baseline is a reviewed, local change."""
    extra = {k: v for k, v in committed.items() if k not in _RECORDED}
    return record(verdict, machine_profile(), "none", run_profile, root=root,
                  harness_version=HARNESS_VERSION, extra=extra)  # fmt: skip


def finish(
    verdict: Verdict,
    result: RunResult,
    *,
    out: Path | None,
    baseline: dict[str, Any] | None,
    machine_profile: str,
    print_: Callable[[str], None] = print,
) -> int:
    """Print every check beside its budget, compare with the baseline (WARN or FAIL bands, only a
    same-profile, non-warn-only one can FAIL), write the JSON report, and give the exit code:
    1 when a hard budget or the regression gate failed, else 0."""
    gate = compare(verdict, baseline, machine_profile, run_profile=result.profile,
                   harness_version=HARNESS_VERSION)  # fmt: skip
    for c in verdict.checks:
        mark = "PASS" if c.passed else ("FAIL" if c.hard else "WARN")
        line = f"{mark} {c.name}: {c.measured:.4g} {c.unit} (limit {c.limit:.4g}) {c.note}"
        print_(line.rstrip())
    for line in gate.warnings + gate.failures:
        print_(f"GATE {line}")
    ok = verdict.passed and not gate.failures
    print_(f"{verdict.scenario} [{result.profile}]: {'PASS' if ok else 'FAIL'} "
           f"({result.produced_msgs} msgs in {result.duration_s:.1f} s)")  # fmt: skip
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        body = verdict.as_dict() | {
            "harness_version": HARNESS_VERSION,
            "profile": result.profile,
            "machine_profile": machine_profile,
            "gate": {"status": gate.status, "reason": gate.reason, "diff": gate.diff},
            "run": {
                "target_msgs_per_s": result.target_msgs_per_s,
                "achieved_msgs_per_s": result.achieved_msgs_per_s,
                "duration_s": result.duration_s,
                "symbols": list(result.symbols),
                "produced_rows": result.produced_rows,
                "written_rows": result.written_rows,
                "dropped_rows": result.dropped_rows,
                "critical_events": result.critical_events,
            },
        }
        out.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if ok else 1
