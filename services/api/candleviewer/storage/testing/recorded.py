"""In-memory recorded-tier fakes (E26-T02) — the public test surface for replay consumers.

They satisfy the `storage.repositories.recorded` Protocols structurally and mirror the real
tiers' contract: half-open ranges, the book-depth filter, the row `limit` (earliest first; a
`limit` below 1 is refused like the real reader refuses it, gap reads included), an inclusive
`not_before_us`, and storage order (insertion order here) rather than a sorted one: equal
timestamps are never sorted by key, so callers cannot rely on an order the real tiers do not
give.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.repositories.recorded import (
    BOOK_STREAMS,
    RecordedBookDelta,
    RecordedBookSnapshot,
    RecordedEvent,
    RecordedGap,
    RecordedQueryRejected,
    covered_parts,
    order_key,
)


def _depth_of(event: RecordedEvent) -> int | None:
    payload = event.payload
    if isinstance(payload, RecordedBookDelta | RecordedBookSnapshot):
        return payload.depth
    return None


class InMemoryRecordedTier:
    """`RecordedStreamReader` over a fixed event list; `reads` counts storage calls."""

    def __init__(self, events: Iterable[RecordedEvent] = ()) -> None:
        self._events: list[RecordedEvent] = list(events)
        self.reads = 0

    def add(self, *events: RecordedEvent) -> None:
        self._events.extend(events)

    async def read(
        self, symbol: str, stream: StreamKind, rng: TimeRange, *, depth: int, limit: int
    ) -> list[RecordedEvent]:
        if isinstance(limit, bool) or limit < 1:
            raise RecordedQueryRejected("limit must be an int >= 1")
        self.reads += 1
        out: list[RecordedEvent] = []
        for event in self._events:
            if event.symbol != symbol or event.stream is not stream:
                continue
            if not rng.start_us <= event.ts_us < rng.end_us:
                continue
            if stream in BOOK_STREAMS and _depth_of(event) != depth:
                continue
            out.append(event)
        # Stable sort on `ts_us` alone: equal timestamps keep storage (insertion) order.
        out.sort(key=lambda e: e.ts_us)
        return out[:limit]

    async def snapshot_at(
        self, symbol: str, depth: int, at_us: int, *, not_before_us: int
    ) -> RecordedEvent | None:
        self.reads += 1
        found = [
            event
            for event in self._events
            if event.symbol == symbol
            and event.stream is StreamKind.ORDERBOOK_SNAPSHOT
            and _depth_of(event) == depth
            and not_before_us <= event.ts_us <= at_us
        ]
        return max(found, key=order_key, default=None)


class StaticManifestCoverage:
    """`ManifestCoverage` over fixed manifested spans; `archive` adds one, as a roll-off would.
    `calls` counts lookups."""

    def __init__(
        self, spans: Mapping[tuple[str, StreamKind], Iterable[TimeRange]] | None = None
    ) -> None:
        self._spans = {key: list(parts) for key, parts in (spans or {}).items()}
        self.calls = 0

    def archive(self, symbol: str, stream: StreamKind, rng: TimeRange) -> None:
        self._spans.setdefault((symbol, stream), []).append(rng)

    async def archived(self, symbol: str, stream: StreamKind, rng: TimeRange) -> list[TimeRange]:
        self.calls += 1
        spans = self._spans.get((symbol, stream), [])
        return covered_parts(((s.start_us, s.end_us) for s in spans), rng)


class StaticGapReader:
    """`RecordingGapReader` over a fixed `recording_gaps` list: the half-open intersections of
    one symbol, the earliest `limit` by start (storage order on equal starts). A `limit` below 1
    is refused like `read`'s; `limits` and `windows` record the `limit` and the range of every
    accepted read."""

    def __init__(self, gaps: Iterable[RecordedGap] = ()) -> None:
        self._gaps = list(gaps)
        self.limits: list[int] = []
        self.windows: list[TimeRange] = []

    async def recording_gaps(self, symbol: str, rng: TimeRange, *, limit: int) -> list[RecordedGap]:
        if isinstance(limit, bool) or limit < 1:
            raise RecordedQueryRejected("limit must be an int >= 1")
        self.limits.append(limit)
        self.windows.append(rng)
        hits = [
            g
            for g in self._gaps
            if g.symbol == symbol and g.start_us < rng.end_us and g.end_us > rng.start_us
        ]
        hits.sort(key=lambda g: g.start_us)
        return hits[:limit]
