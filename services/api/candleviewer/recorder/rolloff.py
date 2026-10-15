"""Nightly hot -> cold roll-off (E16-T05, US-REC-004, ADR-0015 decision 3).

`RollOffJob` orchestrates the existing cold tier (`ColdExporter`, manifest,
`verify_partition`, all via the storage-side `ColdArchiver`) into the nightly
roll-off. It never forks them and never imports a storage driver (ADR-0003):
everything it touches is a port injected at composition time.

Safety property (21 §5.3 invariant): a QuestDB DAY partition holds every
symbol, so it is dropped only when **every** symbol in it was archived and
verified (row count AND content checksum on read-back, plus manifest SHA-256).
Any failure -> the partition stays hot, `archive.verification_failed` is
raised by the archiver, the symbol is retried with bounded exponential backoff
and its watermark is not advanced. Days are processed newest-first so an
interrupted run leaves the oldest data hot. The drop is audited (write-ahead)
before it is issued. A drop QuestDB cannot be confirmed to have applied
(`StoragePartitionDropNotApplied`) is never reported dropped: the outcome is audited
(`rolloff.drop_unconfirmed`), the day is retained (it caps the watermark) and the stream
stops for this pass; the next nightly run retries it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, cast

import structlog

from candleviewer.observability import spawn
from candleviewer.observability.metrics import Counter, Gauge, Histogram
from candleviewer.storage.cold.observability import Severity, SystemEventSink
from candleviewer.storage.cold.watermarks import ArchiveOutcome, RollOffWatermark
from candleviewer.storage.errors import StorageError, StoragePartitionDropNotApplied
from candleviewer.storage.models import StreamKind, TimeRange

US_PER_DAY = 86_400_000_000
DOWNSAMPLE_AFTER_DAYS = 180
#: Streams the recorder writes to the hot tier and therefore rolls off.
ROLLOFF_STREAMS: tuple[StreamKind, ...] = (
    StreamKind.TRADES,
    StreamKind.ORDERBOOK_DELTA,
    StreamKind.TICKERS,
    StreamKind.LIQUIDATIONS,
)
DOWNSAMPLE_STREAMS: tuple[StreamKind, ...] = (StreamKind.ORDERBOOK_DELTA, StreamKind.HEATMAP_CELLS)

recorder_rolloff_bytes_total = Counter(
    "recorder_rolloff_bytes_total", "Parquet bytes verified by the nightly roll-off.", ["stream"]
)
recorder_rolloff_duration_seconds = Histogram(
    "recorder_rolloff_duration_seconds", "Wall time of one nightly roll-off run."
)
recorder_rolloff_failures_total = Counter(
    "recorder_rolloff_failures_total", "Roll-off archive attempts that failed.", ["reason"]
)
recorder_watermark_lag_days = Gauge(
    "recorder_watermark_lag_days", "Days between now and the roll-off watermark.", ["stream"]
)


def logger() -> structlog.stdlib.BoundLogger:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(__name__))


class HotPartitions(Protocol):
    async def closed_days(self, stream: StreamKind, before_us: int) -> list[int]: ...

    async def symbols_in(self, stream: StreamKind, rng: TimeRange) -> list[str]: ...

    async def row_counts(self, stream: StreamKind, rng: TimeRange) -> dict[str, int]:
        """`COUNT(*)` per symbol for the day."""
        ...

    async def snapshot(self, stream: StreamKind, rng: TimeRange) -> dict[str, tuple[int, str]]:
        """Per symbol `(count, value fingerprint)` in ONE query: the fingerprint
        (max ts + sum of a value column) also catches a dedup upsert that
        changes values without changing the count."""
        ...

    async def drop_day(self, stream: StreamKind, day_start_us: int) -> None: ...


class Archiver(Protocol):
    async def archive_day(
        self, symbol: str, stream: StreamKind, day: TimeRange
    ) -> ArchiveOutcome: ...


class Downsampler(Protocol):
    async def downsample_before(self, symbol: str, stream: StreamKind, before_us: int) -> int: ...


class WatermarkStore(Protocol):
    async def get(self, symbol: str, stream: StreamKind) -> RollOffWatermark: ...

    async def advance(
        self, symbol: str, stream: StreamKind, through_us: int, *, now_us: int
    ) -> RollOffWatermark: ...

    async def mark_downsampled(
        self, symbol: str, stream: StreamKind, through_us: int, *, now_us: int
    ) -> RollOffWatermark: ...


class ColdSymbols(Protocol):
    """Symbols with manifested cold partitions for a stream (downsample input)."""

    async def symbols(self, stream: StreamKind) -> list[str]: ...


#: `retention_policies.retain_days` for the hot tier; `None` = pinned (never roll off).
HotDays = Callable[[str, StreamKind], Awaitable[int | None]]


class AuditPort(Protocol):
    async def write(self, action: str, detail: dict[str, str | int]) -> None: ...


#: Audit actor for every roll-off purge (C-2.9): a system principal, never a user.
ROLLOFF_ACTOR = "system:rolloff"


class AuditEmitter(Protocol):
    async def emit(self, action: str, **kwargs: object) -> None: ...


class SystemAuditAdapter:
    """`AuditPort` over the hash-chained `AuditWriter.emit`, as `system:rolloff`."""

    def __init__(self, emitter: AuditEmitter) -> None:
        self._emitter = emitter

    async def write(self, action: str, detail: dict[str, str | int]) -> None:
        await self._emitter.emit(
            action,
            actor_label=ROLLOFF_ACTOR,
            object_kind="hot_partition",
            object_label=f"{detail.get('stream', '')}:{detail.get('range_start_us', '')}",
            after_state=dict(detail),
        )


class RunLock(Protocol):
    def hold(self, volume: str) -> AbstractAsyncContextManager[bool]: ...


@dataclass(frozen=True, slots=True)
class RollOffConfig:
    max_attempts: int = 3
    backoff_base_s: float = 30.0
    backoff_max_s: float = 600.0
    downsample_after_days: int = DOWNSAMPLE_AFTER_DAYS
    #: Bound on one archive attempt (C-2.18); the exporter has its own inner bound.
    attempt_timeout_s: float = 3600.0
    #: Extra days beyond `retain_days` before a day is eligible, so it is far past any
    #: plausible ingest/WAL-apply lag or late backfill (late-row race, review #2213).
    safety_margin_days: int = 1
    streams: tuple[StreamKind, ...] = ROLLOFF_STREAMS


@dataclass(slots=True)
class RollOffReport:
    dropped: list[tuple[StreamKind, int]] = field(default_factory=list)
    retained: list[tuple[StreamKind, int, str]] = field(default_factory=list)
    downsampled: list[tuple[str, StreamKind, int]] = field(default_factory=list)
    skipped_locked: list[StreamKind] = field(default_factory=list)


async def _real_sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class RollOffJob:
    """One nightly roll-off pass (`run()`); `RollOffTask` schedules it."""

    def __init__(
        self,
        *,
        hot: HotPartitions,
        archiver: Archiver,
        watermarks: WatermarkStore,
        hot_days: HotDays,
        audit: AuditPort,
        events: SystemEventSink,
        lock: RunLock,
        downsampler: Downsampler | None = None,
        cold_symbols: ColdSymbols | None = None,
        config: RollOffConfig | None = None,
        clock: Callable[[], datetime] = _utc_now,
        sleep: Callable[[float], Awaitable[None]] = _real_sleep,
    ) -> None:
        self._hot = hot
        self._archiver = archiver
        self._marks = watermarks
        self._hot_days = hot_days
        self._audit = audit
        self._events = events
        self._lock = lock
        self._downsampler = downsampler
        self._cold_symbols = cold_symbols
        self._cfg = config or RollOffConfig()
        self._clock = clock
        self._sleep = sleep

    def _now_us(self) -> int:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("RollOffJob clock must be tz-aware UTC")
        return int(now.timestamp() * 1_000_000)

    async def run(self) -> RollOffReport:
        report = RollOffReport()
        started = self._now_us()
        for stream in self._cfg.streams:
            async with self._lock.hold(f"rolloff:{stream.value}") as got:
                if not got:
                    logger().info("rolloff_skipped_locked", stream=stream.value)
                    report.skipped_locked.append(stream)
                    continue
                await self._roll_stream(stream, report)
        if self._downsampler is not None and self._cold_symbols is not None:
            await self._downsample(report)
        recorder_rolloff_duration_seconds.observe((self._now_us() - started) / 1_000_000)
        return report

    async def _eligible_days(self, stream: StreamKind) -> list[int]:
        now_us = self._now_us()
        # Coarse prefilter with the shortest plausible window (1 day); every
        # day is then re-checked against each present symbol's own window.
        return sorted(await self._hot.closed_days(stream, now_us - US_PER_DAY), reverse=True)

    async def _window_ok(self, symbols: Sequence[str], stream: StreamKind, day_end: int) -> bool:
        now_us = self._now_us()
        for symbol in symbols:
            days = await self._hot_days(symbol, stream)
            margin = days + self._cfg.safety_margin_days if days is not None else None
            if margin is None or day_end > now_us - margin * US_PER_DAY:
                return False
        return True

    async def _archive_with_retry(
        self, symbol: str, stream: StreamKind, day: TimeRange
    ) -> ArchiveOutcome:
        """Bounded exponential backoff; never raises for an archive failure."""
        outcome = ArchiveOutcome(symbol, stream, day.start_us, day.end_us, False, reason="")
        for attempt in range(self._cfg.max_attempts):
            if attempt:
                delay = self._cfg.backoff_base_s * 2 ** (attempt - 1)
                await self._sleep(min(self._cfg.backoff_max_s, delay))
            try:
                async with asyncio.timeout(self._cfg.attempt_timeout_s):
                    outcome = await self._archiver.archive_day(symbol, stream, day)
            except TimeoutError:
                outcome = ArchiveOutcome(
                    symbol, stream, day.start_us, day.end_us, False, reason="archive_write_failed"
                )
            if outcome.verified:
                return outcome
            recorder_rolloff_failures_total.labels(reason=outcome.reason or "unknown").inc()
            logger().warning(
                "rolloff_archive_failed",
                symbol=symbol,
                stream=stream.value,
                attempt=attempt + 1,
                code=outcome.reason,
            )
        return outcome

    async def _roll_stream(self, stream: StreamKind, report: RollOffReport) -> None:
        dropped: dict[str, list[int]] = {}
        retained: dict[str, list[int]] = {}
        for day_start in await self._eligible_days(stream):
            day = TimeRange(start_us=day_start, end_us=day_start + US_PER_DAY)
            before = await self._hot.snapshot(stream, day)
            symbols = sorted(before)
            if not symbols:  # nothing verified -> never drop (review #2213 E)
                continue
            if not await self._window_ok(symbols, stream, day.end_us):
                continue
            outcomes = [await self._archive_with_retry(s, stream, day) for s in symbols]
            failed = [o for o in outcomes if not o.verified]
            if failed:
                for o in failed:
                    retained.setdefault(o.symbol, []).append(day_start)
                report.retained.append((stream, day_start, failed[0].reason))
                continue
            rows = sum(o.rows for o in outcomes)
            detail: dict[str, str | int] = {
                "tier": "hot",
                "stream": stream.value,
                "symbols": ",".join(symbols),
                "range_start_us": day.start_us,
                "range_end_us": day.end_us,
                "rows": rows,
            }
            # Write-ahead audit (C-2.9) BEFORE the final re-check, so only the
            # DROP round-trip sits between the last snapshot and the drop.
            await self._audit.write("retention.purge", detail)
            after = await self._hot.snapshot(stream, day)
            exported = {o.symbol: o.rows for o in outcomes}
            counts = {sym: v[0] for sym, v in after.items()}
            if after != before or counts != exported:
                reason = "count_changed" if counts != exported else "values_changed"
                # The purge record is append-only and stands; record the abort.
                await self._audit.write("rolloff.drop_aborted", detail | {"reason": reason})
                await self._late_rows(stream, day, symbols, report, retained)
                continue
            try:
                await self._hot.drop_day(stream, day_start)
            except StoragePartitionDropNotApplied as exc:
                await self._drop_unconfirmed(stream, day, symbols, detail, exc, report, retained)
                break  # the older days wait for the next pass; `_advance` still runs below
            for o in outcomes:
                recorder_rolloff_bytes_total.labels(stream=stream.value).inc(o.bytes)
                dropped.setdefault(o.symbol, []).append(day_start)
            report.dropped.append((stream, day_start))
            await asyncio.sleep(0)  # yield between partitions (live ingestion first)
        await self._advance(stream, dropped, retained)

    async def _drop_unconfirmed(
        self,
        stream: StreamKind,
        day: TimeRange,
        symbols: Sequence[str],
        detail: dict[str, str | int],
        exc: StoragePartitionDropNotApplied,
        report: RollOffReport,
        retained: dict[str, list[int]],
    ) -> None:
        """The DROP was issued but could not be confirmed applied: the day may still be hot, so it
        is never reported dropped and it caps the watermark (`retained`)."""
        # The purge record is append-only and stands; record the outcome against the same day.
        await self._audit.write("rolloff.drop_unconfirmed", detail | {"reason": exc.reason})
        reason = f"drop_not_applied_{exc.reason}"
        recorder_rolloff_failures_total.labels(reason=reason).inc()
        # A timeout is usually WAL lag that clears by itself; the rest needs an operator.
        severity: Severity = "WARNING" if exc.reason == "timeout" else "CRITICAL"
        event: dict[str, str | int] = {
            "stream": stream.value,
            "range_start_us": day.start_us,
            "reason": exc.reason,
        }
        await self._events.emit(severity, "rolloff.drop_unconfirmed", event)
        for symbol in symbols:
            retained.setdefault(symbol, []).append(day.start_us)
        report.retained.append((stream, day.start_us, reason))

    async def _late_rows(
        self,
        stream: StreamKind,
        day: TimeRange,
        symbols: Sequence[str],
        report: RollOffReport,
        retained: dict[str, list[int]],
    ) -> None:
        recorder_rolloff_failures_total.labels(reason="late_rows").inc()
        detail: dict[str, str | int] = {"stream": stream.value, "range_start_us": day.start_us}
        detail["reason"] = "late_rows"
        await self._events.emit("CRITICAL", "archive.verification_failed", detail)
        for symbol in symbols:
            retained.setdefault(symbol, []).append(day.start_us)
        retained.setdefault("", []).append(day.start_us)
        report.retained.append((stream, day.start_us, "archive_verification_failed"))

    async def _advance(
        self, stream: StreamKind, dropped: dict[str, list[int]], retained: dict[str, list[int]]
    ) -> None:
        """Advance each symbol's watermark only over a contiguous dropped prefix:
        never past the start of any day of this stream still hot after a failure."""
        now_us = self._now_us()
        ceiling = min((d for days in retained.values() for d in days), default=None)
        for symbol, days in dropped.items():
            ends = [d + US_PER_DAY for d in days if ceiling is None or d + US_PER_DAY <= ceiling]
            if not ends:
                continue
            mark = await self._marks.advance(symbol, stream, max(ends), now_us=now_us)
            lag = (now_us - mark.archived_through_us) / US_PER_DAY
            recorder_watermark_lag_days.labels(stream=stream.value).set(lag)

    async def _downsample(self, report: RollOffReport) -> None:
        """Same discipline as the compactor: stream lock, replay lease (inside the
        downsampler), and a write-ahead audit record before any cold file is replaced."""
        if self._downsampler is None or self._cold_symbols is None:
            return
        before = self._now_us() - self._cfg.downsample_after_days * US_PER_DAY
        for stream in DOWNSAMPLE_STREAMS:
            async with self._lock.hold(f"rolloff:{stream.value}") as got:
                if not got:
                    report.skipped_locked.append(stream)
                    continue
                for symbol in await self._cold_symbols.symbols(stream):
                    await self._audit.write(
                        "retention.downsample",
                        {
                            "tier": "cold",
                            "stream": stream.value,
                            "symbol": symbol,
                            "before_us": before,
                            "phase": "intent",
                        },
                    )
                    try:
                        through = await self._downsampler.downsample_before(symbol, stream, before)
                    except (StorageError, OSError, ValueError) as exc:
                        recorder_rolloff_failures_total.labels(reason="downsample_failed").inc()
                        logger().warning("rolloff_downsample_failed", error=type(exc).__name__)
                        continue
                    if through:
                        await self._marks.mark_downsampled(
                            symbol, stream, through, now_us=self._now_us()
                        )
                        report.downsampled.append((symbol, stream, through))


ROLLOFF_INTERVAL_S = 24 * 3600.0


class RollOffTask:
    """Tracked, cancellable owner of the nightly loop (C-2.18); flag-gated by
    the caller (`retention_enabled`, C-4.13). A failing run is logged and
    retried next night; cancellation is honoured."""

    def __init__(
        self,
        job: RollOffJob,
        *,
        interval_s: float = ROLLOFF_INTERVAL_S,
        sleep: Callable[[float], Awaitable[None]] = _real_sleep,
    ) -> None:
        self._job = job
        self._interval_s = interval_s
        self._sleep = sleep
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def _loop(self) -> None:
        while True:
            try:
                await self._job.run()
            except Exception as exc:
                recorder_rolloff_failures_total.labels(reason="run_failed").inc()
                logger().error("rolloff_run_failed", error=type(exc).__name__)
            await self._sleep(self._interval_s)

    def start(self) -> None:
        if self._task is None:
            self._task = spawn(self._loop(), name="recorder-rolloff")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
