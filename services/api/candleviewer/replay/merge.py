"""The ordered, gap-aware k-way merge of one replay's recorded streams (E26-T02).

**Order** (C-2.15; `24-internal-schemas.md` Sec.13.7): ascending
`(ts_us, rank, symbol ordinal, sequence-domain ordinal, seq, stream ordinal, tiebreak)`. `rank`
puts a control marker before the market events of its instant; the symbol ordinal is the
sorted-symbol position. A sequence domain is the streams whose `seq` share one sequence space:
the two book streams share their symbol's exchange `cross_seq`, every other stream is its own
domain, so `seq` is only ever compared inside one `(symbol, domain)`. The stream ordinal then
puts a snapshot before a delta of the same `cross_seq`, and `tiebreak` is the rest of the
stream's dedup key. Every component is stored data and the key is unique per event, so two
reads of one recorded window are identical whichever tier or storage order served them, never
the heap's incidental behaviour.

**Gaps.** Each symbol's `recording_gaps` rows that intersect the window (requested streams
only) are read once, before any event, and become `ReplayGap` markers at `max(gap_start, start)`
carrying the stored bounds and cause. A marker sorts on the same key as an event: rank 0, its
symbol and stream's domain ordinal, `seq` 0, its stream ordinal and `(gap_start, gap_end, cause)`
as the tiebreak, so identical rows report once. The read is bounded by `DEFAULT_MAX_ROWS_PER_READ`
rows per symbol: more is refused whole, never replayed with some gaps unreported. A gap table
that cannot be read fails the replay rather than hide its holes.

**Reading.** One cursor per `(symbol, stream)` reads `[start, end)` in adaptive windows, the
last one clipped to `end`. A window starts at `window_us` (ADR-0035: 30 s), doubles while the
stream is sparse (up to `max_window_us`), and halves and is re-read when a read hits the
cursor's row cap. Each window is sorted and duplicate rows are dropped, keeping the copy read
last: readers return a re-exported cold part's copies oldest first (21 Sec.5.3). A heap then
interleaves the cursors and the gap markers.

**Tiers.** A session reads one tier, never both (ADR-0035 decision 4, refined: a partly
archived range is refused, not read hot): `questdb` or `parquet`, or for `auto` the one the
cold manifests pick (roll-off manifests a partition before it may drop the hot day, 21
Sec.5.3): Parquet if every cursor's range is manifested whole, QuestDB if none of it is, else
`ReplayTierStraddle` before any event. A QuestDB session re-checks the manifests after every
read, so a span archived mid-session ends it with a typed error, never a hole. An explicit tier
is an operator override: no coverage checks, so a span it lacks reads empty.

**Anchor.** `anchor_at` is the seek engine's lookup (E26-T04): one row, so under `auto` it asks
both tiers and the latest by `order_key` wins, and the answer never depends on roll-off.

**Memory and failure.** The cursors share `budget_bytes`: each read is capped at its cursor's
share in rows and at `DEFAULT_MAX_ROWS_PER_READ` whatever the budget, so a stream too dense for
even a 1 µs window raises `ReplayMemoryCeilingExceeded` instead of growing memory (naming the
row ceiling when it, not the byte share, bound). Markers are at most that many rows a symbol,
outside the byte share. Every storage await is bounded by `io_timeout_s`. A failure while the
merge runs ends the replay after the events already merged: their batch is yielded first, then
the error is raised.
"""

from __future__ import annotations

import asyncio
import heapq
import math
import time
from collections.abc import AsyncIterator, Awaitable, Mapping, Sequence
from itertools import chain
from operator import itemgetter
from types import MappingProxyType
from typing import Any, Final, Literal

import structlog

from candleviewer.observability.metrics import Counter, Histogram
from candleviewer.replay.errors import (
    ReplayConfigInvalid,
    ReplayError,
    ReplayMemoryCeilingExceeded,
    ReplayRequestInvalid,
    ReplaySourceUnavailable,
    ReplayTierStraddle,
)
from candleviewer.replay.models import ReplayGap, ReplayItem, ReplayRequest, ReplayTiers
from candleviewer.storage.errors import StorageError
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.repositories.recorded import (
    REPLAYABLE_STREAMS,
    RecordedBookSnapshot,
    RecordedEvent,
    Tiebreak,
    order_key,
)

Tier = Literal["questdb", "parquet"]
US_PER_SECOND: Final = 1_000_000
type _Key = tuple[int, int, int, int, int, int, Tiebreak]
type _Entry = tuple[_Key, ReplayItem, int]

replay_events_read_total = Counter(
    "replay_events_read_total", "Recorded events replay sources read.", ["stream", "tier"]
)
replay_gap_warnings_total = Counter(
    "replay_gap_warnings_total", "ReplayGap markers replay sources emitted."
)
replay_source_read_seconds = Histogram(
    "replay_source_read_seconds", "Replay storage read latency.", ["tier"]
)

#: The sequence domains in merge order (the `stream_kind` enum order, 21 Sec.1.2), each with its
#: streams in stream-ordinal order. The book streams share `cross_seq`: one domain, snapshot first.
_DOMAINS: Final = (
    (StreamKind.TRADES,),
    (StreamKind.ORDERBOOK_SNAPSHOT, StreamKind.ORDERBOOK_DELTA),
    (StreamKind.TICKERS,),
    (StreamKind.KLINES,),
    (StreamKind.LIQUIDATIONS,),
    (StreamKind.OPEN_INTEREST,),
    (StreamKind.FUNDING_RATES,),
)
#: Sequence-domain ordinal of each recorded stream; `seq` is compared inside one domain only.
SEQUENCE_DOMAIN: Final[Mapping[StreamKind, int]] = MappingProxyType(
    {stream: ordinal for ordinal, streams in enumerate(_DOMAINS) for stream in streams}
)
#: Stream ordinal, after `seq` in the key: it only ever separates the two book streams.
STREAM_ORDINAL: Final[Mapping[StreamKind, int]] = MappingProxyType(
    {stream: ordinal for ordinal, stream in enumerate(chain.from_iterable(_DOMAINS))}
)
DEFAULT_WINDOW_US: Final = 30 * US_PER_SECOND
DEFAULT_MAX_WINDOW_US: Final = 3_600 * US_PER_SECOND
DEFAULT_IO_TIMEOUT_S: Final = 30.0
#: How far before a seek target the anchor lookup searches: 60x the 60 s snapshot cadence.
ANCHOR_LOOKBACK_US: Final = 3_600 * US_PER_SECOND
#: Rows one storage read may return whatever the memory budget (threat model Sec.4): bounds the
#: synchronous sort and dedup of one window on the event loop (C-2.17's 50 ms; 8 193 shuffled
#: book deltas took 11 ms median, 25 ms worst of 15 on a Windows laptop). One symbol's
#: `recording_gaps` read is held to it too.
DEFAULT_MAX_ROWS_PER_READ: Final = 8_192
_RANK_GAP: Final = 0
_RANK_EVENT: Final = 1
#: Order-of-magnitude bytes per buffered event (E26-K01 measured ~0.4 KB/event) and per
#: snapshot level (two Decimals and a tuple).
_EVENT_BYTES: Final = 512
_LEVEL_BYTES: Final = 128


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def approx_bytes(event: RecordedEvent) -> int:
    """Estimated resident size of one buffered event."""
    payload = event.payload
    if isinstance(payload, RecordedBookSnapshot):
        return _EVENT_BYTES + _LEVEL_BYTES * (len(payload.bids) + len(payload.asks))
    return _EVENT_BYTES


def row_bytes(stream: StreamKind, depth: int) -> int:
    """Pre-read size estimate of one row of `stream` (a snapshot holds up to 2 x depth levels)."""
    if stream is StreamKind.ORDERBOOK_SNAPSHOT:
        return _EVENT_BYTES + _LEVEL_BYTES * 2 * depth
    return _EVENT_BYTES


class _Cursor:
    """One `(symbol, stream)`: adaptive read windows, each sorted and deduplicated.
    `buf[pos:]` are its next entries, already in merge order."""

    __slots__ = (
        "_end_us",
        "_next_us",
        "_ords",
        "_width",
        "buf",
        "dup_warned",
        "pos",
        "row_cap",
        "stream",
        "symbol",
    )

    def __init__(
        self,
        symbol: str,
        symbol_ord: int,
        stream: StreamKind,
        *,
        start_us: int,
        end_us: int,
        width_us: int,
        row_cap: int,
    ) -> None:
        self.symbol = symbol
        self.stream = stream
        self._ords = (symbol_ord, SEQUENCE_DOMAIN[stream], STREAM_ORDINAL[stream])
        self._next_us = start_us
        self._end_us = end_us
        self._width = width_us
        self.row_cap = row_cap
        self.buf: list[_Entry] = []
        self.pos = 0
        self.dup_warned = False

    @property
    def more(self) -> bool:
        """Whether storage may still hold rows of this cursor past `buf`."""
        return self._next_us < self._end_us

    def window(self) -> tuple[int, int]:
        """The next read: `width` from where the last one ended, clipped to the replay end."""
        return self._next_us, min(self._end_us, self._next_us + self._width)

    def shrink(self, span_us: int) -> bool:
        """Halve the window after a truncated read; `False` once it is down to 1 µs."""
        if span_us <= 1:
            return False
        self._width = span_us // 2
        return True

    def load(self, hi_us: int, events: Sequence[RecordedEvent], max_width_us: int) -> int:
        """Install the window ending at `hi_us`, merge-sorted with the last duplicate kept, and
        grow the next window while the stream is sparse. Returns the duplicates dropped."""
        symbol_ord, domain_ord, stream_ord = self._ords
        keyed = sorted(
            (
                (
                    (e.ts_us, _RANK_EVENT, symbol_ord, domain_ord, e.seq, stream_ord, e.tiebreak),
                    e,
                    approx_bytes(e),
                )
                for e in events
            ),
            key=itemgetter(0),
        )
        buf: list[_Entry] = []
        for entry in keyed:
            if buf and buf[-1][0] == entry[0]:
                buf[-1] = entry  # stable sort: the copy read last (the newest export) wins
            else:
                buf.append(entry)
        self.buf, self.pos, self._next_us = buf, 0, hi_us
        if len(events) * 4 < self.row_cap:
            self._width = min(self._width * 2, max_width_us)
        return len(keyed) - len(buf)


class _Markers:
    """One symbol's gap markers, read whole before the first event; `buf[pos:]` are its next
    entries, already in merge order."""

    __slots__ = ("buf", "pos")

    def __init__(self, buf: list[_Entry]) -> None:
        self.buf = buf
        self.pos = 0


type _Source = _Cursor | _Markers


class RecordedMerge:
    """Every `(symbol, stream)` cursor of one request, merged with its gap markers.

    Single pass: `batches()` may be iterated once; a seek builds a new merge from the target.
    Out-of-bound windows, timeouts or budgets are refused with `ReplayConfigInvalid` before any
    storage read: a window under 1 µs would re-read one empty window forever."""

    def __init__(
        self,
        request: ReplayRequest,
        tiers: ReplayTiers,
        *,
        budget_bytes: int,
        window_us: int = DEFAULT_WINDOW_US,
        max_window_us: int = DEFAULT_MAX_WINDOW_US,
        io_timeout_s: float = DEFAULT_IO_TIMEOUT_S,
    ) -> None:
        if window_us < 1 or max_window_us < window_us:
            raise ReplayConfigInvalid("read windows need 1 µs <= window_us <= max_window_us")
        if not (math.isfinite(io_timeout_s) and io_timeout_s > 0):
            raise ReplayConfigInvalid("io_timeout_s must be a positive, finite number of seconds")
        if budget_bytes <= 0:
            raise ReplayConfigInvalid("budget_bytes must be positive")
        self._request = request
        self._tiers = tiers
        self._max_window_us = max_window_us
        self._io_timeout_s = io_timeout_s
        self._budget_bytes = budget_bytes
        self._tier: Tier | None = None
        self._symbols = tuple(sorted(request.symbols))
        streams = [s for s in REPLAYABLE_STREAMS if s in request.streams]
        share = budget_bytes // (len(self._symbols) * len(streams))
        self._cursors: list[_Cursor] = []
        for symbol_ord, symbol in enumerate(self._symbols):
            for stream in streams:
                row_cap = min(share // row_bytes(stream, request.depth), DEFAULT_MAX_ROWS_PER_READ)
                if row_cap < 1:
                    raise ReplayMemoryCeilingExceeded(
                        budget_bytes=budget_bytes, symbol=symbol, stream=stream
                    )
                cursor = _Cursor(
                    symbol,
                    symbol_ord,
                    stream,
                    start_us=request.start_us,
                    end_us=request.end_us,
                    width_us=window_us,
                    row_cap=row_cap,
                )
                self._cursors.append(cursor)

    async def batches(self, *, max_events: int, max_bytes: int) -> AsyncIterator[list[ReplayItem]]:
        """The merged items in order, cut into batches of at most `max_events` items or about
        `max_bytes` estimated bytes, whichever binds first. A replay failure while refilling a
        cursor first yields the items already merged, then is raised."""
        await self.tier()  # refuse a straddling `auto` session before reading any event
        cursors = self._cursors
        sources: list[_Source] = [*cursors]
        for symbol_ord, symbol in enumerate(self._symbols):
            sources.append(await self._markers(symbol_ord, symbol))
        for cursor in cursors:
            await self._fill(cursor)
        heap = [(source.buf[0][0], index) for index, source in enumerate(sources) if source.buf]
        heapq.heapify(heap)
        batch: list[ReplayItem] = []
        size = 0
        while heap:
            index = heap[0][1]
            source = sources[index]
            _, item, item_bytes = source.buf[source.pos]
            source.pos += 1
            batch.append(item)
            size += item_bytes
            if isinstance(source, _Markers):
                replay_gap_warnings_total.inc()
            elif source.pos >= len(source.buf) and source.more:
                try:
                    await self._fill(source)
                except ReplayError:
                    yield batch  # what was merged before the failure is delivered first
                    raise
            if source.pos < len(source.buf):
                heapq.heapreplace(heap, (source.buf[source.pos][0], index))
            else:
                heapq.heappop(heap)
            if len(batch) >= max_events or size >= max_bytes:
                yield batch
                batch, size = [], 0
        if batch:
            yield batch

    async def _fill(self, cursor: _Cursor) -> None:
        """Read windows until `cursor` has an entry or its range is exhausted. Terminates: a
        window is at least 1 µs wide, so each pass either moves past it or halves it."""
        while cursor.pos >= len(cursor.buf) and cursor.more:
            lo_us, hi_us = cursor.window()
            events = await self._read_window(cursor, lo_us, hi_us)
            if len(events) > cursor.row_cap:
                if not cursor.shrink(hi_us - lo_us):
                    # The row ceiling is named when it, not the byte share, set the cap.
                    by_rows = cursor.row_cap == DEFAULT_MAX_ROWS_PER_READ
                    raise ReplayMemoryCeilingExceeded(
                        budget_bytes=self._budget_bytes,
                        symbol=cursor.symbol,
                        stream=cursor.stream,
                        max_rows=DEFAULT_MAX_ROWS_PER_READ if by_rows else None,
                    )
                continue
            dropped = cursor.load(hi_us, events, self._max_window_us)
            if dropped and not cursor.dup_warned:
                cursor.dup_warned = True
                _log().warning(
                    "replay_source_duplicates_dropped",
                    symbol=cursor.symbol,
                    stream=cursor.stream.value,
                    count=dropped,
                )

    async def tier(self) -> Tier:
        """The session's one tier, resolved on first use (`auto` reads the manifests once)."""
        if self._tier is None:
            self._tier = await self._resolve_tier()
            _log().info("replay_source_tier", tier=self._tier, requested=self._request.source_tier)
        return self._tier

    async def _resolve_tier(self) -> Tier:
        req = self._request
        if req.source_tier != "auto":
            return req.source_tier
        whole = TimeRange(start_us=req.start_us, end_us=req.end_us)
        coverage = [(cursor, await self._archived(cursor, whole)) for cursor in self._cursors]
        if all(list(parts) == [whole] for _, parts in coverage):
            return "parquet"
        if not any(parts for _, parts in coverage):
            return "questdb"
        cursor, parts = next((c, p) for c, p in coverage if list(p) != [whole])
        raise ReplayTierStraddle(symbol=cursor.symbol, stream=cursor.stream, archived=parts)

    async def _read_window(self, cursor: _Cursor, lo_us: int, hi_us: int) -> list[RecordedEvent]:
        """One read of one tier, one past the row cap (a full read means "truncated")."""
        tier = await self.tier()
        rng = TimeRange(start_us=lo_us, end_us=hi_us)
        reader = self._tiers.hot if tier == "questdb" else self._tiers.cold
        started = time.perf_counter()
        read = reader.read(
            cursor.symbol, cursor.stream, rng, depth=self._request.depth, limit=cursor.row_cap + 1
        )
        rows = await self._guarded(read, tier=tier, symbol=cursor.symbol, stream=cursor.stream)
        replay_source_read_seconds.labels(tier=tier).observe(time.perf_counter() - started)
        replay_events_read_total.labels(stream=cursor.stream.value, tier=tier).inc(len(rows))
        auto_hot = tier == "questdb" and self._request.source_tier == "auto"
        # Roll-off manifests a span before it may drop it: one archived while this session ran
        # may be gone from QuestDB, so it ends the replay instead of reading as a hole.
        if auto_hot and await self._archived(cursor, rng):
            why = "archived_during_replay"
            raise ReplaySourceUnavailable(
                tier=tier, symbol=cursor.symbol, stream=cursor.stream, reason=why
            )
        return list(rows)

    async def _archived(self, cursor: _Cursor, rng: TimeRange) -> Sequence[TimeRange]:
        read = self._tiers.coverage.archived(cursor.symbol, cursor.stream, rng)
        return await self._guarded(
            read, tier="manifest", symbol=cursor.symbol, stream=cursor.stream
        )

    async def _guarded[T](
        self, awaitable: Awaitable[T], *, tier: str, symbol: str, stream: StreamKind | None
    ) -> T:
        """Every storage await is time-bounded; a failure becomes one typed error carrying the
        storage error's code, never its text. Raised after the handler, so neither `__cause__`
        nor `__context__` keeps a storage error whose text or chain may hold a path (RP-I02)."""
        try:
            async with asyncio.timeout(self._io_timeout_s):
                return await awaitable
        except TimeoutError:
            reason = "timeout"
        except StorageError as exc:
            reason = exc.code
        raise ReplaySourceUnavailable(tier=tier, symbol=symbol, stream=stream, reason=reason)

    async def _markers(self, symbol_ord: int, symbol: str) -> _Markers:
        """One symbol's gap markers: each `recording_gaps` row of a requested stream that
        intersects `[start, end)`, at `max(gap_start, start)`. The read asks for one row past the
        ceiling, and a symbol that fills it is refused whole rather than reported in part. The
        reader is not trusted to have filtered: symbol, stream and the half-open intersection are
        re-checked, and rows identical in symbol, stream, start, end and cause report once."""
        req = self._request
        start_us, end_us = req.start_us, req.end_us
        window = TimeRange(start_us=start_us, end_us=end_us)
        read = self._tiers.gaps.recording_gaps(symbol, window, limit=DEFAULT_MAX_ROWS_PER_READ + 1)
        rows = await self._guarded(read, tier="recording_gaps", symbol=symbol, stream=None)
        if len(rows) > DEFAULT_MAX_ROWS_PER_READ:
            raise ReplayMemoryCeilingExceeded(
                budget_bytes=self._budget_bytes,
                symbol=symbol,
                stream=None,
                max_rows=DEFAULT_MAX_ROWS_PER_READ,
            )
        found: dict[_Key, _Entry] = {}
        for gap in rows:
            if gap.symbol != symbol or gap.stream not in req.streams:
                continue
            if gap.start_us >= end_us or gap.end_us <= start_us:
                continue
            at_us = max(gap.start_us, start_us)
            key: _Key = (
                at_us,
                _RANK_GAP,
                symbol_ord,
                SEQUENCE_DOMAIN[gap.stream],
                0,
                STREAM_ORDINAL[gap.stream],
                (gap.start_us, gap.end_us, gap.cause),
            )
            marker = ReplayGap(at_us, symbol, gap.stream, gap.start_us, gap.end_us, gap.cause)
            found[key] = (key, marker, _EVENT_BYTES)
        return _Markers(sorted(found.values(), key=itemgetter(0)))

    async def anchor_at(self, symbol: str, at_us: int) -> RecordedEvent | None:
        """Seek anchor (E26-T04): the latest `orderbook_snapshot` of `symbol` at the replay's
        depth with `at_us - ANCHOR_LOOKBACK_US <= ts_us <= at_us`, else `None`. Bounded on both
        sides, so it never scans unbounded history. It is one row, not a stream: under `auto`
        both tiers are asked and the latest by `order_key` wins (a row both hold maps
        identically), so the answer never depends on how far roll-off has got; an explicit tier
        looks only there. A symbol outside the replay or an instant outside its window (the end
        included, where a finished replay sits) is refused with `ReplayRequestInvalid`."""
        req = self._request
        if symbol not in req.symbols:
            raise ReplayRequestInvalid("symbol is not part of this replay")
        if not req.start_us <= at_us <= req.end_us:
            raise ReplayRequestInvalid("anchor instant is outside the replay window")
        tiers: tuple[Tier, ...] = ("questdb", "parquet")
        if req.source_tier != "auto":
            tiers = (req.source_tier,)
        found: list[RecordedEvent] = []
        for tier in tiers:
            reader = self._tiers.hot if tier == "questdb" else self._tiers.cold
            lookup = reader.snapshot_at(
                symbol, req.depth, at_us, not_before_us=at_us - ANCHOR_LOOKBACK_US
            )
            stream = StreamKind.ORDERBOOK_SNAPSHOT
            hit = await self._guarded(lookup, tier=tier, symbol=symbol, stream=stream)
            if hit is not None:
                found.append(hit)
        return max(found, key=order_key, default=None)
