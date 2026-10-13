"""Recorded-event read surface over the hot and cold tiers (E26-T02).

One interface, two tiers: the replay source (M12) reads recorded market data only through
`RecordedStreamReader`. The QuestDB and Parquet/DuckDB implementations live beside the other
tier clients and are injected at composition time, so a tier swap stays a swap (ADR-0003).
Every dataset is addressed by `StreamKind` (the registered dataset id), symbol and time range,
never by a filesystem path (SR-097).

A `RecordedEvent` is tier-independent: prices and sizes are `Decimal` (C-2.2: never `float`),
`ts_us` is integer microseconds UTC, and `seq` plus `tiebreak` carry the stream's recorded
order. `seq` is the exchange sequence the recorder stores (0 for streams without one) and
`tiebreak` is the rest of the `21-database-schema.md` Sec.4 dedup key, so
`(ts_us, seq, tiebreak)` is unique per `(symbol, stream)`. How the replay merge combines them
across streams is documented in `24-internal-schemas.md` Sec.13.7.

No storage driver is imported here, so the replay module may depend on it (ADR-0003).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Protocol, runtime_checkable

from candleviewer.storage.models import StreamKind, TimeRange

#: Postgres `stream_kind` value -> storage stream, in enum declaration order (21 Sec.1.2).
#: The order is the replay tie-break ordinal for events sharing `(ts_event, seq)`.
STREAM_BY_DB_KIND: Final[dict[str, StreamKind]] = {
    "trades": StreamKind.TRADES,
    "orderbook_delta": StreamKind.ORDERBOOK_DELTA,
    "orderbook_snapshot": StreamKind.ORDERBOOK_SNAPSHOT,
    "tickers": StreamKind.TICKERS,
    "klines": StreamKind.KLINES,
    "liquidations": StreamKind.LIQUIDATIONS,
    "open_interest": StreamKind.OPEN_INTEREST,
    "funding": StreamKind.FUNDING_RATES,
}

#: The raw recorded streams a replay can read (derived streams are rebuilt, never replayed).
REPLAYABLE_STREAMS: Final[tuple[StreamKind, ...]] = tuple(STREAM_BY_DB_KIND.values())

#: Book streams are recorded per order-book depth; a read selects exactly one depth.
BOOK_STREAMS: Final[frozenset[StreamKind]] = frozenset(
    {StreamKind.ORDERBOOK_DELTA, StreamKind.ORDERBOOK_SNAPSHOT}
)

#: Final ordering component; `None` columns read as -1 / "" so tuples stay comparable.
type Tiebreak = tuple[int | str | Decimal, ...]
type Level = tuple[Decimal, Decimal]


@dataclass(frozen=True, slots=True)
class RecordedTrade:
    side: str
    price: Decimal
    size: Decimal
    trade_id: str
    is_block: bool | None


@dataclass(frozen=True, slots=True)
class RecordedBookDelta:
    """One changed level; `size == 0` removes it."""

    depth: int
    side: str
    price: Decimal
    size: Decimal
    update_id: int
    cross_seq: int | None


@dataclass(frozen=True, slots=True)
class RecordedBookSnapshot:
    """A full book at `depth`, best level first; the seek anchor (`24` Sec.13.7)."""

    depth: int
    update_id: int
    cross_seq: int | None
    bids: tuple[Level, ...]
    asks: tuple[Level, ...]


@dataclass(frozen=True, slots=True)
class RecordedTicker:
    last_price: Decimal | None
    mark_price: Decimal | None
    index_price: Decimal | None
    bid1_price: Decimal | None
    bid1_size: Decimal | None
    ask1_price: Decimal | None
    ask1_size: Decimal | None
    open_interest: Decimal | None
    funding_rate: Decimal | None


@dataclass(frozen=True, slots=True)
class RecordedKline:
    interval: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    turnover: Decimal | None
    confirmed: bool


@dataclass(frozen=True, slots=True)
class RecordedLiquidation:
    """`side` is the closing order's side, as stored (21 Sec.4.6)."""

    side: str
    price: Decimal
    size: Decimal
    batch_index: int | None


@dataclass(frozen=True, slots=True)
class RecordedOpenInterest:
    open_interest: Decimal
    open_interest_value: Decimal | None
    interval: str
    source: str | None


@dataclass(frozen=True, slots=True)
class RecordedFunding:
    funding_rate: Decimal
    interval_min: int | None
    source: str | None


type RecordedPayload = (
    RecordedTrade
    | RecordedBookDelta
    | RecordedBookSnapshot
    | RecordedTicker
    | RecordedKline
    | RecordedLiquidation
    | RecordedOpenInterest
    | RecordedFunding
)


@dataclass(frozen=True, slots=True)
class RecordedEvent:
    """One recorded market event as stored; `ts_us` is the exchange event time (µs, UTC)."""

    ts_us: int
    seq: int
    symbol: str
    stream: StreamKind
    tiebreak: Tiebreak
    payload: RecordedPayload


def order_key(event: RecordedEvent) -> tuple[int, int, Tiebreak]:
    """`(ts_us, seq, tiebreak)`: unique per `(symbol, stream)`, and the order every tier and the
    replay merge share (24 Sec.13.7), so "latest" means the same row whichever tier answers."""
    return event.ts_us, event.seq, event.tiebreak


def covered_parts(spans: Iterable[tuple[int, int]], rng: TimeRange) -> list[TimeRange]:
    """`spans` clipped to `rng`, sorted, with overlapping or touching spans merged."""
    clipped = sorted(
        (max(lo, rng.start_us), min(hi, rng.end_us))
        for lo, hi in spans
        if lo < rng.end_us and hi > rng.start_us
    )
    merged: list[tuple[int, int]] = []
    for lo, hi in clipped:
        if merged and lo <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    return [TimeRange(start_us=lo, end_us=hi) for lo, hi in merged]


@dataclass(frozen=True, slots=True)
class RecordedGap:
    """A `recording_gaps` row: `stream` of `symbol` has no data in `[start_us, end_us)`.
    `cause` is the stored value verbatim (never relabelled)."""

    symbol: str
    stream: StreamKind
    start_us: int
    end_us: int
    cause: str


@runtime_checkable
class RecordedStreamReader(Protocol):
    """One tier's recorded events (QuestDB hot or Parquet cold), behind one interface."""

    async def read(
        self, symbol: str, stream: StreamKind, rng: TimeRange, *, depth: int, limit: int
    ) -> Sequence[RecordedEvent]:
        """Events of `(symbol, stream)` with `rng.start_us <= ts_us < rng.end_us`, at most
        `limit` of them (earliest first when the cap binds; callers pass `cap + 1` to detect
        truncation). Book streams are filtered to `depth`; other streams ignore it.

        Rows come in storage order, which does not order equal timestamps, and the cold tier
        may repeat a row a re-export appended (21 Sec.5.3 "dedup on read"): callers sort by
        `(ts_us, seq, tiebreak)` and keep the last of any duplicate."""
        ...

    async def snapshot_at(
        self, symbol: str, depth: int, at_us: int, *, not_before_us: int
    ) -> RecordedEvent | None:
        """Latest `orderbook_snapshot` of `(symbol, depth)` with
        `not_before_us <= ts_us <= at_us` (the bounded seek-anchor lookup), else `None`."""
        ...


@runtime_checkable
class ArchiveCoverage(Protocol):
    """What the cold tier's manifests cover: how `source_tier="auto"` picks a session's tier.

    Roll-off writes and verifies a partition's manifest before it may drop the hot day (21
    Sec.5.3), so a span with no manifest was never dropped holding data: QuestDB still has
    whatever was recorded there."""

    async def archived(
        self, symbol: str, stream: StreamKind, rng: TimeRange
    ) -> Sequence[TimeRange]:
        """The parts of `rng` that manifested cold partitions of `(symbol, stream)` cover,
        clipped to `rng`, ascending, with overlapping or touching parts merged."""
        ...


@runtime_checkable
class RecordingGapReader(Protocol):
    """Read side of `recording_gaps` (21 Sec.3.6.2)."""

    async def recording_gaps(self, symbol: str, rng: TimeRange) -> Sequence[RecordedGap]:
        """Gaps of `symbol` (any stream) with `start_us < rng.end_us` and
        `end_us > rng.start_us`."""
        ...
