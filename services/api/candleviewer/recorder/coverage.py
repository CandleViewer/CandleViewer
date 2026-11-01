"""`CoverageService` — what recorded data exists, per stream and tier (E16-T04).

Backs `GET /market/data-coverage` (22-api `DataCoverage`) and the `recording_started_at`
resolution behind `no_data_recorded` (422). Downstream R2 consumers (E18 footprint, E19
profiles, E23 CVD, E26 replay) query `coverage()` before rendering a historical window.

Covered = session windows minus gaps (`intervals.coverage`), split at the roll-off watermark
(E16-T05 `WatermarkStore`): older than the watermark -> `parquet`, newer -> `questdb`. Gap
rows marked `backfilled` (kline) STAY in the gap list: bars-derived backfill never makes a
tick-level window covered (ADR-0015 d7 "no interpolation, ever").

Cached per `(symbol, stream)` for the last `CACHE_DAYS`; any session/gap write for the symbol
invalidates it (`invalidate`). Older ranges fall through to SQL. `rows` is omitted: row
estimates need QuestDB partition metadata (not wired yet; the field is optional).

Reconcile (E16-FR-03, #1739, threat model R-T1): with a `presence` port, the hot-tier
(`questdb`) intervals of a `RECONCILE_TOLERANCE_US` stream are checked against the minutes that
hold stored rows, so a deleted or shrunk gap row cannot make absent data read as present. A span
claimed covered but holding no rows, longer than the stream's tolerance, is taken out of the
intervals and listed as a gap with cause `unverified_data` (no contract `reason`: the route
omits it). A presence read that fails reports the whole hot-tier span that way (fail closed),
logged, never raised; the symbol's hot tier then reads that way without a new read for
`PRESENCE_RETRY_US`, so a slow or down QuestDB is not re-scanned on every request. Presence is
cached per `(symbol, stream)` for `PRESENCE_TTL_US`, and `invalidate` drops it (not the failure
back-off: session and gap writes are frequent). The cold tier is trusted through its roll-off
watermark and manifest.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Final, Literal, Protocol

import structlog

from candleviewer.recorder.intervals import Span, coverage, split_at, subtract, union
from candleviewer.recorder.metrics import recorder_coverage_reconcile_mismatch_total
from candleviewer.recorder.rolloff import WatermarkStore
from candleviewer.recorder.sessions import to_dt, to_us
from candleviewer.storage.models import StreamKind

Tier = Literal["questdb", "parquet"]
Source = Literal["recorded", "archive"]
#: The only stream a public trade archive can cover (E16-T10): book/ticker/liquidation
#: coverage is never inferred from an archive window.
ARCHIVE_STREAMS: Final = frozenset({StreamKind.TRADES.value})
#: Coverage cache horizon (ticket technical notes).
CACHE_DAYS: Final = 90
_DAY_US: Final = 86_400_000_000
_CACHE_MAX: Final = 4096
#: Cache entries span `[now - CACHE_DAYS, +inf)`; open sessions end at `now` at read time, and
#: every session/gap write invalidates, so the far-future upper bound never goes stale.
_FAR_FUTURE_US: Final = 253_402_300_799_000_000  # 9999-12-31T23:59:59Z
#: DB `recording_gaps.cause` -> 22-api `DataCoverage.gaps[].reason` (open-ended for readers,
#: #2216). A cause with no contract value is NOT mapped: the route omits `reason` (optional in
#: the schema) rather than mislabel it.
GAP_REASON: Final[dict[str, str]] = {
    "ws_disconnect": "ws_disconnect",
    "process_restart": "backend_restart",
    "exchange_outage": "exchange_outage",
    "seq_jump": "seq_jump",
    "backpressure_drop": "backpressure_drop",
}
#: E16-FR-03: the gap cause of hot-tier coverage that stored data does not back.
UNVERIFIED_CAUSE: Final = "unverified_data"
#: E16-FR-03: the streams reconciled against stored rows, and the longest absent span each
#: tolerates (start-up latency, a quiet market, the 1-minute presence buckets, ingest lag).
#: Sparse streams (liquidations, funding, open interest, klines, anchors) are not reconciled:
#: an empty minute there is normal.
RECONCILE_TOLERANCE_US: Final[Mapping[str, int]] = MappingProxyType(
    {"orderbook_delta": 90_000_000, "tickers": 90_000_000, "trades": 900_000_000}
)
#: Data arrives without a session or gap write, so presence is re-read at least this often.
PRESENCE_TTL_US: Final = 60_000_000
#: After a failed presence read, every reconciled stream of the symbol fails closed without a
#: new read for this long: one timeout per symbol, not one per stream and request.
PRESENCE_RETRY_US: Final = 10_000_000


def logger() -> structlog.stdlib.BoundLogger:
    return structlog.get_logger("candleviewer.recorder.coverage")  # type: ignore[no-any-return]  # structlog: Any


class CoverageStore(Protocol):
    async def sessions_in(
        self, symbol: str, lo: datetime, hi: datetime
    ) -> list[dict[str, Any]]: ...

    async def gaps_in(self, symbol: str, lo: datetime, hi: datetime) -> list[dict[str, Any]]: ...

    async def earliest_first_event(self, symbol: str) -> datetime | None: ...


class StoredPresence(Protocol):
    """Hot-tier presence, `[lo, hi)` microseconds: the merged spans that hold stored rows
    (`storage.questdb.stored_presence.QuestDbStoredPresence`; the integrity job's `StoredData`
    has the same method)."""

    async def stored_spans(
        self, symbol: str, stream: str, lo: int, hi: int
    ) -> list[tuple[int, int]]: ...


class ArchiveCoverage(Protocol):
    """Imported archive windows (E16-T10 ledger), `[lo, hi)` microseconds, sorted."""

    async def archive_windows(self, symbol: str, lo: int, hi: int) -> list[tuple[int, int]]: ...


#: The E16-T05 roll-off watermark API (`recorder.rolloff.WatermarkStore`; production impl
#: `storage.cold.watermarks.FileWatermarkStore`). Only `get` is used here.
WatermarkReader = WatermarkStore


@dataclass(frozen=True, slots=True)
class CoveredInterval:
    lo: int
    hi: int
    tier: Tier
    source: Source = "recorded"


@dataclass(frozen=True, slots=True)
class GapInterval:
    lo: int
    hi: int
    cause: str
    backfilled: bool = False
    backfill_source: str | None = None


@dataclass(frozen=True, slots=True)
class StreamCoverage:
    stream: str
    intervals: tuple[CoveredInterval, ...]
    gaps: tuple[GapInterval, ...]


def _stream_kind(stream: str) -> StreamKind | None:
    try:
        return StreamKind(stream)
    except ValueError:
        return None


def attribute_tiers(spans: Sequence[Span], watermark_us: int) -> list[CoveredInterval]:
    """Spans older than the watermark are `parquet`, newer `questdb`; a span across it splits."""
    out: list[CoveredInterval] = []
    for s in spans:
        cold, hot = split_at(s, watermark_us)
        if cold is not None:
            out.append(CoveredInterval(cold.lo, cold.hi, "parquet"))
        if hot is not None:
            out.append(CoveredInterval(hot.lo, hot.hi, "questdb"))
    return out


def _span(lo: int, hi: int) -> Span | None:
    return Span(lo, hi) if hi > lo else None


def _without(tiers: Sequence[CoveredInterval], absent: Sequence[Span]) -> list[CoveredInterval]:
    """`tiers` with the hot-tier parts in `absent` taken out; the cold tier is untouched."""
    out: list[CoveredInterval] = []
    for i in tiers:
        if i.tier != "questdb":
            out.append(i)
            continue
        out += [
            CoveredInterval(s.lo, s.hi, i.tier, i.source)
            for s in subtract([Span(i.lo, i.hi)], absent)
        ]
    return out


class CoverageService:
    """Session windows minus gaps, tier-attributed; cached per (symbol, stream)."""

    def __init__(
        self,
        store: CoverageStore,
        *,
        now_us: Callable[[], int],
        watermarks: WatermarkReader | None = None,
        archive: ArchiveCoverage | None = None,
        presence: StoredPresence | None = None,
        timeout_s: float = 5.0,
    ) -> None:
        self._store = store
        self._presence = presence
        #: symbol -> stream -> (read_at, lo, hi, spans): the last presence read.
        self._seen: OrderedDict[str, dict[str, tuple[int, int, int, list[Span]]]] = OrderedDict()
        #: symbol -> the time of its last failed presence read (`PRESENCE_RETRY_US`).
        self._failed: OrderedDict[str, int] = OrderedDict()
        self._archive = archive
        self._now_us = now_us
        self._marks = watermarks
        self._timeout_s = timeout_s
        #: symbol -> (cache_lo, cache_hi, sessions, gaps) over the last CACHE_DAYS.
        self._cache: OrderedDict[str, tuple[int, int, list[dict[str, Any]], list[dict[str, Any]]]]
        self._cache = OrderedDict()

    def invalidate(self, symbol: str) -> None:
        """Called on every session or gap write for `symbol` (SessionManager hook)."""
        self._cache.pop(symbol, None)
        self._seen.pop(symbol, None)

    async def recording_started_at_us(self, symbol: str) -> int | None:
        """Earliest `first_event_ts` across sessions for the symbol (`no_data_recorded`)."""
        async with asyncio.timeout(self._timeout_s):
            first = await self._store.earliest_first_event(symbol)
        return None if first is None else to_us(first)

    async def _rows(
        self, symbol: str, lo: int, hi: int, now: int
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        horizon = now - CACHE_DAYS * _DAY_US
        if lo >= horizon:
            hit = self._cache.get(symbol)
            if hit is None or lo < hit[0]:
                c_hi = _FAR_FUTURE_US
                async with asyncio.timeout(self._timeout_s):
                    sess = await self._store.sessions_in(symbol, to_dt(horizon), to_dt(c_hi))
                    gaps = await self._store.gaps_in(symbol, to_dt(horizon), to_dt(c_hi))
                hit = (horizon, c_hi, sess, gaps)
                self._cache[symbol] = hit
                while len(self._cache) > _CACHE_MAX:
                    self._cache.popitem(last=False)
            return hit[2], hit[3]
        async with asyncio.timeout(self._timeout_s):  # older than the cache: straight SQL
            sess = await self._store.sessions_in(symbol, to_dt(lo), to_dt(hi))
            gaps = await self._store.gaps_in(symbol, to_dt(lo), to_dt(hi))
        return sess, gaps

    async def _watermark(self, symbol: str, stream: str) -> int:
        kind = _stream_kind(stream)
        if self._marks is None or kind is None:
            return 0
        async with asyncio.timeout(self._timeout_s):
            mark = await self._marks.get(symbol, kind)
        return int(mark.archived_through_us)

    async def coverage_recent(
        self, symbol: str, streams: Sequence[str]
    ) -> tuple[int, int, list[StreamCoverage]]:
        """The `/market/data-coverage` window: the last `CACHE_DAYS` up to now, always served
        from the per-symbol cache (one clock read, so `lo` is exactly the cache horizon)."""
        now = self._now_us()
        lo = now - CACHE_DAYS * _DAY_US
        return lo, now, await self.coverage(symbol, streams, lo, now, _now=now)

    async def coverage(
        self, symbol: str, streams: Sequence[str], lo: int, hi: int, *, _now: int | None = None
    ) -> list[StreamCoverage]:
        if hi <= lo:
            raise ValueError("coverage window must have from < to")
        now = self._now_us() if _now is None else _now
        sessions, gaps = await self._rows(symbol, lo, hi, now)
        out: list[StreamCoverage] = []
        for stream in streams:
            windows: list[Span] = []
            for s in sessions:
                if stream not in (s.get("streams") or ()):
                    continue
                end = s.get("ended_at")
                w = _span(max(lo, to_us(s["started_at"])), min(hi, to_us(end) if end else now))
                if w is not None:
                    windows.append(w)
            g_rows = [
                g for g in gaps
                if g["stream"] == stream and to_us(g["gap_start"]) < hi
                and to_us(g["gap_end"]) > lo
            ]  # fmt: skip
            g_spans = [Span(to_us(g["gap_start"]), to_us(g["gap_end"])) for g in g_rows]
            covered = coverage(windows, g_spans)
            tiers = attribute_tiers(covered, await self._watermark(symbol, stream))
            absent = await self._unverified(symbol, stream, tiers, now)
            if absent:
                covered = subtract(covered, absent)
                tiers = _without(tiers, absent)
            if stream in ARCHIVE_STREAMS:
                tiers = sorted(
                    tiers + await self._archive_only(symbol, lo, hi, covered),
                    key=lambda i: i.lo,
                )
            gaps_out = [
                GapInterval(
                    max(lo, to_us(g["gap_start"])),
                    min(hi, to_us(g["gap_end"])),
                    str(g["cause"]),
                    bool(g.get("backfilled")),
                    g.get("backfill_source"),
                )
                for g in g_rows
            ]
            if absent:
                gaps_out += [GapInterval(a.lo, a.hi, UNVERIFIED_CAUSE) for a in absent]
                gaps_out.sort(key=lambda g: (g.lo, g.hi))
            out.append(StreamCoverage(stream=stream, intervals=tuple(tiers), gaps=tuple(gaps_out)))
        return out

    async def _unverified(
        self, symbol: str, stream: str, tiers: Sequence[CoveredInterval], now: int
    ) -> list[Span]:
        """The hot-tier spans claimed covered that stored data does not back (E16-FR-03)."""
        tol = RECONCILE_TOLERANCE_US.get(stream)
        hot = [Span(i.lo, i.hi) for i in tiers if i.tier == "questdb"]
        presence = self._presence
        if presence is None or tol is None or not hot:
            return []
        failed_at = self._failed.get(symbol)
        if failed_at is not None and now - failed_at < PRESENCE_RETRY_US:
            return union(hot)  # still backing off: fail closed without a read (or a log line)
        try:
            stored, fresh = await self._stored(presence, symbol, stream, hot[0].lo, hot[-1].hi, now)
        except Exception as exc:  # fail closed: unverifiable coverage is not reported covered
            self._failed[symbol] = now
            self._failed.move_to_end(symbol)
            while len(self._failed) > _CACHE_MAX:
                self._failed.popitem(last=False)
            logger().error(
                "recorder_coverage_reconcile_failed",
                symbol=symbol,
                stream=stream,
                error=type(exc).__name__,
            )
            return union(hot)
        self._failed.pop(symbol, None)
        absent = [a for a in subtract(hot, stored) if a.hi - a.lo > tol]
        if absent and fresh:
            recorder_coverage_reconcile_mismatch_total.labels(stream=stream).inc()
            logger().warning(
                "recorder_coverage_reconcile_mismatch",
                symbol=symbol,
                stream=stream,
                spans=len(absent),
                first_us=absent[0].lo,
                last_us=absent[-1].hi,
            )
        return absent

    async def _stored(
        self, presence: StoredPresence, symbol: str, stream: str, lo: int, hi: int, now: int
    ) -> tuple[list[Span], bool]:
        """Presence over `[lo, hi)`, from the last read when it is younger than the TTL, starts
        no later and reached `hi` or its own read time; True when read now. Rows stored after a
        cached read count as absent, within the tolerance, until the TTL lapses."""
        held = self._seen.get(symbol, {}).get(stream)
        if (
            held is not None
            and now - held[0] < PRESENCE_TTL_US
            and held[1] <= lo
            and held[2] >= min(hi, held[0])
        ):
            return held[3], False
        async with asyncio.timeout(self._timeout_s):
            raw = await presence.stored_spans(symbol, stream, lo, hi)
        spans = [s for a, b in raw if (s := _span(a, b)) is not None]
        self._seen.setdefault(symbol, {})[stream] = (now, lo, hi, spans)
        self._seen.move_to_end(symbol)
        while len(self._seen) > _CACHE_MAX:
            self._seen.popitem(last=False)
        return spans, True

    async def recorded_windows(
        self, symbol: str, lo: int, hi: int, stream: str = StreamKind.TRADES.value
    ) -> list[tuple[int, int]]:
        """What the recorder actually covers for `stream` in `[lo, hi)`: session windows MINUS
        that stream's recorder gaps, by the same `coverage()` algebra `coverage()` reports
        (E16-T04). The archive importer discards rows only inside these windows (recorded
        wins) and writes rows that fall in a recorder gap, so `coverage()` then labels that
        gap window `source='archive'` truthfully."""
        now = self._now_us()
        async with asyncio.timeout(self._timeout_s):
            rows = await self._store.sessions_in(symbol, to_dt(lo), to_dt(hi))
            gap_rows = await self._store.gaps_in(symbol, to_dt(lo), to_dt(hi))
        g_spans = [
            sp for g in gap_rows if g["stream"] == stream
            and (sp := _span(to_us(g["gap_start"]), to_us(g["gap_end"]))) is not None
        ]  # fmt: skip
        spans: list[Span] = []
        for s in rows:
            if stream not in (s.get("streams") or ()):
                continue
            end = s.get("ended_at")
            w = _span(max(lo, to_us(s["started_at"])), min(hi, to_us(end) if end else now))
            if w is not None:
                spans.append(w)
        return [(s.lo, s.hi) for s in coverage(spans, g_spans)]

    async def _archive_only(
        self, symbol: str, lo: int, hi: int, recorded: Sequence[Span]
    ) -> list[CoveredInterval]:
        """Archive windows minus recorded coverage (recorded wins), always cold tier."""
        if self._archive is None:
            return []
        async with asyncio.timeout(self._timeout_s):
            raw = await self._archive.archive_windows(symbol, lo, hi)
        spans = [s for a, b in raw if (s := _span(a, b)) is not None]
        return [
            CoveredInterval(s.lo, s.hi, "parquet", "archive")
            for s in subtract(union(spans), list(recorded))
        ]
