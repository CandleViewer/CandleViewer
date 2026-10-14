"""The ordered, gap-aware k-way merge of one replay's recorded streams (E26-T02).

**Order** (C-2.15; `24-internal-schemas.md` Sec.13.7): ascending
`(ts_us, rank, seq, stream ordinal, symbol ordinal, tiebreak)`. `rank` puts a gap marker
before the market events of its instant; `seq` is the stored exchange sequence; the stream
ordinal is the `stream_kind` enum order; the symbol ordinal is the sorted-symbol position;
`tiebreak` is the rest of the stream's dedup key. Every component is stored data and the key
is unique per event, so two reads of one recorded window are identical whichever tier or
storage order served them, never the heap's incidental behaviour.

**Reading.** One cursor per `(symbol, stream)` reads `[start, end)` in adaptive windows. A
window starts at `window_us` (ADR-0035: 30 s) and doubles while the stream is sparse. A read
that hits the cursor's row cap returns the earliest rows (the reader contract), so every
instant before the last one it returned is complete: those rows are kept, the next read starts
at that last instant, and the window shrinks to the span that filled the cap. Nothing is re-read
or lost. Each window is sorted and duplicate rows
are dropped, keeping the one read last (the cold tier may hold a re-exported part twice, 21
Sec.5.3). A heap then interleaves the cursors and the gap markers.

**Tiers.** A session reads one tier, never both (ADR-0035 decision 4): `questdb` or `parquet`,
or for `auto` the one the cold manifests pick (roll-off manifests a partition before it may drop
the hot day, 21 Sec.5.3): Parquet if every cursor's range is manifested whole, QuestDB if none
of it is, else `ReplayTierStraddle` before any event. A QuestDB session re-checks the manifests
after every read, so a span archived mid-session ends it with a typed error, never a hole. An
explicit tier is an operator override: no coverage checks, so a span it lacks reads empty.

**Gaps.** `recording_gaps` rows that intersect the window (requested streams only) become
`ReplayGap` markers at `max(gap_start, start)`, carrying the stored bounds and cause.

**Memory.** The cursors share `budget_bytes`: each read is capped at its cursor's share in rows,
so a stream too dense for even a 1 µs window raises `ReplayMemoryCeilingExceeded` instead of
growing memory. Tiers map rows off the event loop; a read is also capped at
`max_rows_per_read` rows so the sort and dedup the merge then does on the loop stays short
(C-2.17). Every storage await is bounded by `io_timeout_s`.
"""

from __future__ import annotations

import asyncio
import heapq
import time
from collections.abc import AsyncGenerator, Awaitable, Sequence
from operator import itemgetter
from typing import Any, Final, Literal

import structlog

from candleviewer.observability.metrics import Counter, Histogram
from candleviewer.replay.errors import (
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
type _Key = tuple[int, int, int, int, int, Tiebreak]
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

#: Tie-break ordinal of each recorded stream: the `stream_kind` enum order (21 Sec.1.2).
STREAM_ORDINAL: Final[dict[StreamKind, int]] = {s: i for i, s in enumerate(REPLAYABLE_STREAMS)}
#: How far before a seek target the anchor lookup searches (60x the 60 s snapshot cadence).
ANCHOR_LOOKBACK_US: Final = 3_600 * US_PER_SECOND
DEFAULT_WINDOW_US: Final = 30 * US_PER_SECOND
DEFAULT_MAX_WINDOW_US: Final = 3_600 * US_PER_SECOND
DEFAULT_IO_TIMEOUT_S: Final = 30.0
#: Rows one read may return. Sorting and deduplicating this many on the event loop took
#: ~8 ms on a laptop, well inside C-2.17's 50 ms (the tiers map rows off the loop).
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


class _Input:
    """A merge input: `buf[pos:]` are its next entries, already in merge order."""

    __slots__ = ("buf", "pos")

    def __init__(self, entries: list[_Entry] | None = None) -> None:
        self.buf: list[_Entry] = entries or []
        self.pos = 0

    @property
    def more(self) -> bool:
        """Whether storage still holds entries past `buf` (gap markers are loaded whole)."""
        return False


class _Cursor(_Input):
    """One `(symbol, stream)`: adaptive read windows, each sorted and deduplicated."""

    __slots__ = (
        "_end_us",
        "_next_us",
        "_ords",
        "_width",
        "dup_warned",
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
        super().__init__()
        self.symbol = symbol
        self.stream = stream
        self._ords = (STREAM_ORDINAL[stream], symbol_ord)
        self._next_us = start_us
        self._end_us = end_us
        self._width = width_us
        self.row_cap = row_cap
        self.dup_warned = False

    @property
    def more(self) -> bool:
        return self._next_us < self._end_us

    def window(self) -> tuple[int, int]:
        return self._next_us, min(self._end_us, self._next_us + self._width)

    def fit(self, span_us: int) -> None:
        """After a capped read: the next window spans what filled the cap (at least 1 µs)."""
        self._width = max(1, span_us)

    def load(self, hi_us: int, events: Sequence[RecordedEvent], max_width_us: int) -> int:
        """Install the window ending at `hi_us`, merge-sorted with the last duplicate kept, and
        grow the next window while the stream is sparse. Returns the duplicates dropped."""
        stream_ord, symbol_ord = self._ords
        keyed = sorted(
            (
                (
                    (e.ts_us, _RANK_EVENT, e.seq, stream_ord, symbol_ord, e.tiebreak),
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
                buf[-1] = entry  # stable sort: the row read last (the newest export) wins
            else:
                buf.append(entry)
        self.buf, self.pos, self._next_us = buf, 0, hi_us
        if len(events) * 4 < self.row_cap:
            self._width = min(self._width * 2, max_width_us)
        return len(keyed) - len(buf)


class RecordedMerge:
    """Every `(symbol, stream)` cursor of one request, merged with its gap markers.

    Single pass: `batches()` may be iterated once; a seek builds a new merge from the target."""

    def __init__(
        self,
        request: ReplayRequest,
        tiers: ReplayTiers,
        *,
        budget_bytes: int,
        window_us: int = DEFAULT_WINDOW_US,
        max_window_us: int = DEFAULT_MAX_WINDOW_US,
        io_timeout_s: float = DEFAULT_IO_TIMEOUT_S,
        max_rows_per_read: int = DEFAULT_MAX_ROWS_PER_READ,
    ) -> None:
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
                row_cap = min(share // row_bytes(stream, request.depth), max_rows_per_read)
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

    async def batches(self, *, max_events: int, max_bytes: int) -> AsyncGenerator[list[ReplayItem]]:
        """The merged items in order, cut into batches of at most `max_events` items or about
        `max_bytes` estimated bytes, whichever binds first. If a read fails, the items merged
        before it are yielded first and the typed error is raised after them."""
        await self.tier()  # refuse a straddling `auto` session before reading any event
        inputs: list[_Input] = [*self._cursors, _Input(await self._gap_markers())]
        marker_index = len(inputs) - 1
        heap: list[tuple[_Key, int]] = []
        for index, source in enumerate(inputs):
            await self._fill(source)
            if source.pos < len(source.buf):
                heap.append((source.buf[source.pos][0], index))
        heapq.heapify(heap)
        batch: list[ReplayItem] = []
        size = 0
        while heap:
            index = heap[0][1]
            source = inputs[index]
            _, item, item_bytes = source.buf[source.pos]
            source.pos += 1
            batch.append(item)
            size += item_bytes
            if index == marker_index:
                replay_gap_warnings_total.inc()
            if source.pos >= len(source.buf) and source.more:
                try:
                    await self._fill(source)
                except ReplayError:
                    yield batch  # holds at least the item just merged; all of it is in order
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

    async def _fill(self, source: _Input) -> None:
        """Read windows until `source` has an entry or its range is exhausted."""
        if not isinstance(source, _Cursor):
            return
        while source.pos >= len(source.buf) and source.more:
            lo_us, hi_us = source.window()
            events = await self._read_window(source, lo_us, hi_us)
            if len(events) > source.row_cap:
                # The earliest rows came back: every instant before the last one is complete.
                last_us = max(event.ts_us for event in events)
                events = [event for event in events if event.ts_us < last_us]
                if not events:  # one instant alone exceeds the cap
                    raise ReplayMemoryCeilingExceeded(
                        budget_bytes=self._budget_bytes,
                        symbol=source.symbol,
                        stream=source.stream,
                    )
                source.fit(last_us - lo_us)
                hi_us = last_us
            dropped = source.load(hi_us, events, self._max_window_us)
            if dropped and not source.dup_warned:
                source.dup_warned = True
                _log().warning(
                    "replay_source_duplicates_dropped",
                    symbol=source.symbol,
                    stream=source.stream.value,
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
        """One read of one tier, one past the cap (a full read means "truncated")."""
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
        """Every storage await is time-bounded; a failure becomes one typed error."""
        try:
            async with asyncio.timeout(self._io_timeout_s):
                result = await awaitable
        except TimeoutError as exc:
            raise ReplaySourceUnavailable(
                tier=tier, symbol=symbol, stream=stream, reason="timeout"
            ) from exc
        except StorageError as exc:
            raise ReplaySourceUnavailable(
                tier=tier, symbol=symbol, stream=stream, reason=exc.code
            ) from exc
        return result

    async def _gap_markers(self) -> list[_Entry]:
        start_us, end_us = self._request.start_us, self._request.end_us
        window = TimeRange(start_us=start_us, end_us=end_us)
        wanted = {cursor.stream for cursor in self._cursors}
        markers: dict[_Key, ReplayGap] = {}
        for symbol_ord, symbol in enumerate(self._symbols):
            read = self._tiers.gaps.recording_gaps(symbol, window)
            gaps = await self._guarded(read, tier="recording_gaps", symbol=symbol, stream=None)
            for gap in gaps:
                if gap.symbol != symbol or gap.stream not in wanted:
                    continue
                if gap.start_us >= end_us or gap.end_us <= start_us:
                    continue
                at_us = max(gap.start_us, start_us)
                tiebreak: Tiebreak = (gap.start_us, gap.end_us, gap.cause)
                key = (at_us, _RANK_GAP, 0, STREAM_ORDINAL[gap.stream], symbol_ord, tiebreak)
                markers[key] = ReplayGap(
                    at_us, symbol, gap.stream, gap.start_us, gap.end_us, gap.cause
                )
        return [(key, marker, _EVENT_BYTES) for key, marker in sorted(markers.items())]

    async def anchor_at(self, symbol: str, at_us: int) -> RecordedEvent | None:
        """Seek anchor (E26-T04): the latest `orderbook_snapshot` of `symbol` at the replay's
        depth with `at_us - ANCHOR_LOOKBACK_US <= ts_us <= at_us`. It is one row, not a stream:
        under `auto` both tiers are asked and the latest by `order_key` wins (a row both hold
        maps identically), so the answer never depends on how far roll-off has got."""
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
