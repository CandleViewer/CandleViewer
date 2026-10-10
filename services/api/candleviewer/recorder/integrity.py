"""Daily recorder integrity job + kline-derived partial backfill marking (E16-T04).

Integrity (per symbol and stream, over the last day):
- sequence continuity: every break reported by `StoredData.seq_breaks` (orderbook update-id
  discontinuities in QuestDB) must lie inside a gap row; an unexplained break is written as a
  `seq_jump` gap (explained by the data itself).
- stored intervals reconcile with session windows: data stored OUTSIDE every session window,
  or a hole inside a session window that no gap row explains, cannot be attributed to a
  cause; it is raised as a `recorder.integrity_anomaly` system event (never silently fixed).

Kline backfill: a gap that E08's REST kline backfill could (partly) fill gets
`backfilled=true, backfill_source='kline'`. The gap window itself is never shrunk or deleted,
so tick-level coverage keeps reporting it missing; the klines written are bar-derived
(`sources: exchange_rest`).

Recorder may not import ingestion (C-3.1): both sources are injected Protocols. Every await
is bounded; the clock is injected.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, Protocol

import structlog

from candleviewer.observability.health_probes import SystemEvent, SystemEventWriter
from candleviewer.recorder.intervals import Span, subtract, union
from candleviewer.recorder.metrics import recorder_integrity_anomalies_total
from candleviewer.recorder.sessions import to_dt, to_us

_DAY_US: Final = 86_400_000_000
ANOMALY_KIND: Final = "recorder.integrity_anomaly"
KLINE_SOURCE: Final = "kline"


def logger() -> structlog.stdlib.BoundLogger:
    return structlog.get_logger("candleviewer.recorder.integrity")  # type: ignore[no-any-return]  # structlog: Any


class IntegrityStore(Protocol):
    async def sessions_in(
        self, symbol: str, lo: datetime, hi: datetime
    ) -> list[dict[str, Any]]: ...

    async def gaps_in(self, symbol: str, lo: datetime, hi: datetime) -> list[dict[str, Any]]: ...

    async def record_gap(
        self,
        *,
        session_id: str,
        symbol: str,
        stream: str,
        gap_start: datetime,
        gap_end: datetime,
        cause: str,
    ) -> int: ...

    async def mark_gap_backfilled(self, gap_id: int, source: str) -> bool: ...


class StoredData(Protocol):
    """Hot-tier facts (QuestDB; binds via `ts_param`, naive UTC)."""

    async def stored_spans(
        self, symbol: str, stream: str, lo: int, hi: int
    ) -> list[tuple[int, int]]: ...

    async def seq_breaks(self, symbol: str, lo: int, hi: int) -> list[tuple[int, int]]: ...


class KlineBackfill(Protocol):
    """E08 `KlineBackfillService.backfill_range`, adapted to µs: returns how many confirmed
    bars were written for `[lo, hi)`."""

    async def __call__(self, symbol: str, lo: int, hi: int) -> int: ...


@dataclass(slots=True)
class IntegrityReport:
    checked: int = 0
    gaps_written: int = 0
    anomalies: list[dict[str, str]] = field(default_factory=list)


def _sessions_for(rows: Sequence[dict[str, Any]], stream: str, lo: int, hi: int) -> list[Span]:
    out: list[Span] = []
    for s in rows:
        if stream not in (s.get("streams") or ()):
            continue
        a = max(lo, to_us(s["started_at"]))
        b = min(hi, to_us(s["ended_at"]) if s.get("ended_at") else hi)
        if b > a:
            out.append(Span(a, b))
    return out


def _session_at(rows: Sequence[dict[str, Any]], at: int) -> str | None:
    for s in rows:
        end = s.get("ended_at")
        if to_us(s["started_at"]) <= at and (end is None or at < to_us(end)):
            return str(s["id"])
    return None


class IntegrityJob:
    """Run once a day (or on admin demand) over `[now - 1 day, now)`."""

    def __init__(
        self,
        store: IntegrityStore,
        data: StoredData,
        events: SystemEventWriter,
        *,
        now_us: Callable[[], int],
        timeout_s: float = 30.0,
        on_write: Callable[[str], None] | None = None,
    ) -> None:
        self._store, self._data, self._events = store, data, events
        self._now_us = now_us
        self._timeout_s = timeout_s
        self._on_write = on_write or (lambda _symbol: None)

    async def run(self, symbols: Sequence[str], streams: Sequence[str]) -> IntegrityReport:
        hi = self._now_us()
        lo = hi - _DAY_US
        report = IntegrityReport()
        for symbol in symbols:
            async with asyncio.timeout(self._timeout_s):
                sessions = await self._store.sessions_in(symbol, to_dt(lo), to_dt(hi))
                gaps = await self._store.gaps_in(symbol, to_dt(lo), to_dt(hi))
            for stream in streams:
                report.checked += 1
                await self._check(symbol, stream, lo, hi, sessions, gaps, report)
        return report

    async def _check(
        self,
        symbol: str,
        stream: str,
        lo: int,
        hi: int,
        sessions: list[dict[str, Any]],
        gaps: list[dict[str, Any]],
        report: IntegrityReport,
    ) -> None:
        windows = union(_sessions_for(sessions, stream, lo, hi))
        holes = [
            Span(to_us(g["gap_start"]), to_us(g["gap_end"])) for g in gaps if g["stream"] == stream
        ]
        async with asyncio.timeout(self._timeout_s):
            stored = [Span(a, b) for a, b in await self._data.stored_spans(symbol, stream, lo, hi)]
        outside = subtract(stored, windows)
        if outside:
            await self._anomaly(symbol, stream, "data_outside_session", outside, report)
        expected = subtract(windows, holes)
        missing = subtract(expected, stored)
        if missing:
            await self._anomaly(symbol, stream, "unexplained_hole", missing, report)
        if stream == "orderbook_delta":
            await self._seq(symbol, lo, hi, sessions, holes, report)

    async def _seq(
        self,
        symbol: str,
        lo: int,
        hi: int,
        sessions: list[dict[str, Any]],
        holes: list[Span],
        report: IntegrityReport,
    ) -> None:
        async with asyncio.timeout(self._timeout_s):
            breaks = await self._data.seq_breaks(symbol, lo, hi)
        for a, b in breaks:
            if b <= a or not subtract([Span(a, b)], holes):
                continue  # already explained by a gap row
            sid = _session_at(sessions, a)
            if sid is None:
                await self._anomaly(symbol, "orderbook_delta", "seq_break_outside_session",
                                    [Span(a, b)], report)  # fmt: skip
                continue
            async with asyncio.timeout(self._timeout_s):
                await self._store.record_gap(
                    session_id=sid,
                    symbol=symbol,
                    stream="orderbook_delta",
                    gap_start=to_dt(a),
                    gap_end=to_dt(b),
                    cause="seq_jump",
                )
            report.gaps_written += 1
            recorder_integrity_anomalies_total.labels(kind="gap").inc()
            self._on_write(symbol)

    async def _anomaly(
        self, symbol: str, stream: str, kind: str, spans: Sequence[Span], report: IntegrityReport
    ) -> None:
        recorder_integrity_anomalies_total.labels(kind="event").inc()
        first, last = spans[0], spans[-1]
        details = {
            "symbol": symbol,
            "stream": stream,
            "anomaly": kind,
            "start_us": str(first.lo),
            "end_us": str(last.hi),
            "count": str(len(spans)),
        }
        report.anomalies.append(details)
        logger().error(ANOMALY_KIND, **details)
        event = SystemEvent(
            component="recorder",
            kind=ANOMALY_KIND,
            severity="critical",
            message=f"{kind} for {stream}/{symbol}: {len(spans)} window(s)",
            details=details,
        )
        try:
            async with asyncio.timeout(self._timeout_s):
                await self._events.write(event)
        except Exception as exc:
            logger().error("recorder_event_write_failed", symbol=symbol, error=type(exc).__name__)


async def mark_kline_backfill(
    store: IntegrityStore,
    backfill: KlineBackfill,
    symbol: str,
    lo: int,
    hi: int,
    *,
    timeout_s: float = 60.0,
    on_write: Callable[[str], None] | None = None,
) -> list[int]:
    """Fill each `trades` gap in `[lo, hi)` from REST klines; mark the gaps that got bars as
    `backfilled=true, backfill_source='kline'`. Gap windows are untouched (tick coverage stays
    missing). Returns the marked gap ids."""
    async with asyncio.timeout(timeout_s):
        gaps = await store.gaps_in(symbol, to_dt(lo), to_dt(hi))
    marked: list[int] = []
    for g in gaps:
        if g["stream"] != "trades" or g.get("backfilled"):
            continue
        async with asyncio.timeout(timeout_s):
            written = await backfill(symbol, to_us(g["gap_start"]), to_us(g["gap_end"]))
            if written <= 0:
                continue
            await store.mark_gap_backfilled(int(g["id"]), KLINE_SOURCE)
        marked.append(int(g["id"]))
    if marked and on_write is not None:
        on_write(symbol)
    return marked
