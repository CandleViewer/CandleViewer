"""Recorded-event read surface over the hot and cold tiers (E26-T02).

One interface, two tiers: the replay source (M12) reads recorded market data only through
`RecordedStreamReader`. The QuestDB and Parquet/DuckDB implementations live beside the other
tier clients and are injected at composition time, so a tier swap stays a swap (ADR-0003).
Every dataset is addressed by `StreamKind` (the registered dataset id), symbol and time range,
never by a filesystem path (SR-097).

Why a third read surface over the same tiers: `MarketDataRepository.read_*` serves hot-path
row types (unbounded reads, a subset of the streams, rows without the full dedup key, `"auto"`
resolved per call by the router) and `ColdTierRepository.query` returns unbounded, untyped cold
dicts. A replay needs one contract both tiers answer identically for all eight recorded
streams: bounded (`limit`, a bounded anchor lookup), typed (`Decimal` payloads) and ordered
(`order_key`).

A `RecordedEvent` is tier-independent: prices and sizes are `Decimal` (`AGENTS.md` §5.2),
`ts_us` is integer microseconds UTC, and `seq` plus `tiebreak` order the events of one stream.
`seq` is not one sequence space across streams: `trades.seq` is the per-process, per-symbol
ingest counter the recorder stores (24 Sec.2.1), book `cross_seq` is the exchange's own
sequence, and streams that store none read 0. `tiebreak` is the rest of the
`21-database-schema.md` Sec.4 dedup key, so `(ts_us, seq, tiebreak)` is unique, and the order
total, within one `(symbol, stream)` only. Across symbols and streams at equal `ts_us` the
replay merge decides, and the symbol and sequence-domain ordinals sit before `seq` there (the
two book streams share `cross_seq`, one domain; every other stream is its own), so `seq` is
only ever compared inside one sequence space (`24-internal-schemas.md` Sec.13.7).

`event_from_row` is the single canonical mapping from a stored row to a `RecordedEvent`. A
QuestDB PGWire record and a Parquet row carry the same Sec.4 columns and both tiers go through
it, so one recorded row yields an equal event whichever tier served it: a DOUBLE converts once
via `Decimal(float.__repr__(x))` (the shortest round-trip text, whatever float subclass the
driver returns), decimal text converts exactly, and a timestamp may arrive as a naive or aware
datetime or an int. Per stream, `seq` is `trades.seq` (the ingest counter), book `cross_seq`
(else `update_id`) or 0, each meaningful within its own stream only, and `tiebreak` puts the
recorded-order column first.

No storage driver is imported here (stdlib and `orjson` only), so the replay module may depend
on it (ADR-0003).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Final, Protocol, runtime_checkable

import orjson

from candleviewer.domain.sql_names import ts_us_from_row
from candleviewer.storage.errors import StorageError, StorageRecordInvalid
from candleviewer.storage.models import StreamKind, TimeRange

#: Postgres `stream_kind` value -> storage stream, in enum declaration order (21 Sec.1.2).
#: The replay merge orders the sequence domains of one instant by it (24 Sec.13.7).
#: Read-only: the order is a contract.
STREAM_BY_DB_KIND: Final[Mapping[str, StreamKind]] = MappingProxyType(
    {
        "trades": StreamKind.TRADES,
        "orderbook_delta": StreamKind.ORDERBOOK_DELTA,
        "orderbook_snapshot": StreamKind.ORDERBOOK_SNAPSHOT,
        "tickers": StreamKind.TICKERS,
        "klines": StreamKind.KLINES,
        "liquidations": StreamKind.LIQUIDATIONS,
        "open_interest": StreamKind.OPEN_INTEREST,
        "funding": StreamKind.FUNDING_RATES,
    }
)

#: The raw recorded streams a replay can read (derived streams are rebuilt, never replayed).
REPLAYABLE_STREAMS: Final[tuple[StreamKind, ...]] = tuple(STREAM_BY_DB_KIND.values())

#: Book streams are recorded per order-book depth; a read selects exactly one depth.
BOOK_STREAMS: Final[frozenset[StreamKind]] = frozenset(
    {StreamKind.ORDERBOOK_DELTA, StreamKind.ORDERBOOK_SNAPSHOT}
)

#: Final ordering component; `None` columns read as -1 / "" so one stream's tuples stay
#: comparable (two streams' tuples need not be: see `order_key`).
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
    """Every `tickers` column the recorder writes (`recorder/writer.py` `ticker_records`), so a
    replay re-emits the recorded ticker losslessly (24 Sec.13.7); `None` is a column the row
    did not carry. `next_funding_ts` is µs UTC. The last five default to `None` only so the
    payload can be built positionally from the first nine."""

    last_price: Decimal | None
    mark_price: Decimal | None
    index_price: Decimal | None
    bid1_price: Decimal | None
    bid1_size: Decimal | None
    ask1_price: Decimal | None
    ask1_size: Decimal | None
    open_interest: Decimal | None
    funding_rate: Decimal | None
    open_interest_value: Decimal | None = None
    turnover_24h: Decimal | None = None
    volume_24h: Decimal | None = None
    price_24h_pcnt: Decimal | None = None
    next_funding_ts: int | None = None


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
    """One recorded market event as stored; `ts_us` is the exchange event time (µs, UTC).
    `seq` and `tiebreak` order it among the events of its own `(symbol, stream)` only."""

    ts_us: int
    seq: int
    symbol: str
    stream: StreamKind
    tiebreak: Tiebreak
    payload: RecordedPayload


def order_key(event: RecordedEvent) -> tuple[int, int, Tiebreak]:
    """`(ts_us, seq, tiebreak)`: unique, so a total order, within one `(symbol, stream)`, and
    the same whichever tier served the row, so "latest" means the same row in both tiers.

    Compare keys of one `(symbol, stream)` only: `seq` is not one sequence space across
    streams, and two streams' tiebreaks need not even be comparable (`TypeError`). Across
    symbols and streams at equal `ts_us` the replay merge decides: the symbol and
    sequence-domain ordinals sit before `seq` (24 Sec.13.7)."""
    return event.ts_us, event.seq, event.tiebreak


def covered_parts(spans: Iterable[tuple[int, int]], rng: TimeRange) -> list[TimeRange]:
    """`spans` (half-open `[lo, hi)`) clipped to `rng`, sorted, with overlapping or touching
    spans merged; a span with no width inside `rng` contributes nothing.

    An inverted span (`hi < lo`) is corrupt coverage metadata: it raises `StorageError` (the
    replay maps the storage family to a typed failure) wherever it lies, never a bare
    validation error, and it is never silently dropped."""
    clipped: list[tuple[int, int]] = []
    for lo, hi in spans:
        if hi < lo:
            raise StorageError("a coverage span ends before it starts")
        start, end = max(lo, rng.start_us), min(hi, rng.end_us)
        if start < end:
            clipped.append((start, end))
    clipped.sort()
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


class RecordedQueryRejected(ValueError):
    """A read refused before any storage call because its arguments break the reader contract
    (a `limit` below 1). A caller bug, not a storage failure: deliberately outside the
    `StorageError` family that the replay maps to "source unavailable"."""


@runtime_checkable
class RecordedStreamReader(Protocol):
    """One tier's recorded events (QuestDB hot or Parquet cold), behind one interface."""

    async def read(
        self, symbol: str, stream: StreamKind, rng: TimeRange, *, depth: int, limit: int
    ) -> Sequence[RecordedEvent]:
        """Events of `(symbol, stream)` with `rng.start_us <= ts_us < rng.end_us`, at most
        `limit` of them (earliest first when the cap binds; callers pass `cap + 1` to detect
        truncation). Book streams are filtered to `depth`; other streams ignore it. A `limit`
        below 1 (or a bool) raises `RecordedQueryRejected` before storage is read.

        Rows come in storage order, which does not order equal timestamps, and the cold tier
        may repeat a row a re-export appended (21 Sec.5.3 "dedup on read"): callers sort by
        `order_key` (one read is one `(symbol, stream)`) and keep the last of any duplicate."""
        ...

    async def snapshot_at(
        self, symbol: str, depth: int, at_us: int, *, not_before_us: int
    ) -> RecordedEvent | None:
        """Latest `orderbook_snapshot` of `(symbol, depth)` with
        `not_before_us <= ts_us <= at_us` (the bounded seek-anchor lookup), else `None`."""
        ...


@runtime_checkable
class ManifestCoverage(Protocol):
    """What the cold tier's manifests cover: how `source_tier="auto"` picks a session's tier.
    (Not `recorder.coverage.ArchiveCoverage`, the E16-T10 imported-archive ledger port.)

    Roll-off writes and verifies a partition's manifest before it may drop the hot day (21
    Sec.5.3), so a span with no manifest was never dropped holding data: QuestDB still has
    whatever was recorded there."""

    async def archived(
        self, symbol: str, stream: StreamKind, rng: TimeRange
    ) -> Sequence[TimeRange]:
        """The parts of `rng` that manifested cold partitions of `(symbol, stream)` cover, as
        `covered_parts` shapes them: clipped to `rng`, ascending, non-empty, with overlapping
        or touching parts merged."""
        ...


@runtime_checkable
class RecordingGapReader(Protocol):
    """Read side of `recording_gaps` (21 Sec.3.6.2)."""

    async def recording_gaps(self, symbol: str, rng: TimeRange) -> Sequence[RecordedGap]:
        """Gaps of `symbol` (any stream) with `start_us < rng.end_us` and
        `end_us > rng.start_us`."""
        ...


# --- stored row -> RecordedEvent ----------------------------------------------------------------

type _Row = Mapping[str, object]
type _Mapped = tuple[int, Tiebreak, RecordedPayload]


def _invalid(column: str) -> StorageRecordInvalid:
    return StorageRecordInvalid(f"recorded row has no usable {column!r}")


# A failed conversion raises *after* its handler, so neither `__cause__` nor `__context__`
# holds the stored value that failed (the error names the column, never the value).

#: Closed `side` sets as stored (21 Sec.4): a taker or closing-order side, and a book side.
_ORDER_SIDES: Final = frozenset({"buy", "sell"})
_BOOK_SIDES: Final = frozenset({"bid", "ask"})


def _decimal(value: object, column: str) -> Decimal | None:
    """`None`, NaN and infinities read as missing; a non-numeric value is invalid. A float
    converts through `float.__repr__`, never a subclass's `repr` (`np.float64(0.1)`)."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise _invalid(column)
    if isinstance(value, float):
        return Decimal(float.__repr__(value)) if math.isfinite(value) else None
    if not isinstance(value, Decimal | int | str):
        raise _invalid(column)
    try:
        number: Decimal | None = Decimal(value)
    except InvalidOperation:
        number = None
    if number is None:
        raise _invalid(column)
    return number if number.is_finite() else None


def _opt_decimal(row: _Row, column: str) -> Decimal | None:
    return _decimal(row.get(column), column)


def _req_decimal(row: _Row, column: str) -> Decimal:
    value = _decimal(row.get(column), column)
    if value is None:
        raise _invalid(column)
    return value


def _opt_int(row: _Row, column: str) -> int | None:
    value = row.get(column)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise _invalid(column)
    try:
        number: int | None = int(value)
    except ValueError:
        number = None
    if number is None:
        raise _invalid(column)
    return number


def _req_int(row: _Row, column: str) -> int:
    value = _opt_int(row, column)
    if value is None:
        raise _invalid(column)
    return value


def _opt_id(row: _Row, column: str) -> int | None:
    """An optional id whose missing value orders as -1: a stored negative id would tie with a
    missing one, so it is invalid."""
    value = _opt_int(row, column)
    if value is not None and value < 0:
        raise _invalid(column)
    return value


def _opt_ts(row: _Row, column: str) -> int | None:
    """A TIMESTAMP as integer µs UTC: a naive (PGWire, UTC) or aware (Parquet) datetime, or an
    int (an ILP-shaped row)."""
    value = row.get(column)
    if value is None:
        return None
    try:
        ts_us: int | None = ts_us_from_row(value)
    except (TypeError, ValueError):
        ts_us = None
    if ts_us is None:
        raise _invalid(column)
    return ts_us


def _req_ts(row: _Row, column: str) -> int:
    value = _opt_ts(row, column)
    if value is None:
        raise _invalid(column)
    return value


def _opt_str(row: _Row, column: str) -> str | None:
    value = row.get(column)
    if value is None or isinstance(value, str):
        return value
    raise _invalid(column)


def _req_str(row: _Row, column: str) -> str:
    value = _opt_str(row, column)
    if not value:
        raise _invalid(column)
    return value


def _req_member(row: _Row, column: str, allowed: frozenset[str]) -> str:
    """A closed-set text column: any value outside `allowed` is invalid."""
    value = _req_str(row, column)
    if value not in allowed:
        raise _invalid(column)
    return value


def _opt_bool(row: _Row, column: str) -> bool | None:
    value = row.get(column)
    if value is None or isinstance(value, bool):
        return value
    raise _invalid(column)


def _levels(row: _Row, column: str) -> tuple[Level, ...]:
    """A snapshot side: JSON `[[price, size], ...]` with text or numeric values."""
    raw = row.get(column)
    if not isinstance(raw, str | bytes):
        raise _invalid(column)
    try:
        parsed: object = orjson.loads(raw)
    except orjson.JSONDecodeError:
        parsed = None
    if not isinstance(parsed, list):
        raise _invalid(column)
    levels: list[Level] = []
    for pair in parsed:
        if not isinstance(pair, list) or len(pair) != 2:
            raise _invalid(column)
        price, size = _decimal(pair[0], column), _decimal(pair[1], column)
        if price is None or size is None:
            raise _invalid(column)
        levels.append((price, size))
    return tuple(levels)


def _book_seq(update_id: int, cross_seq: int | None) -> int:
    return update_id if cross_seq is None else cross_seq


# A None key column reads as -1 (`_opt_id` refuses a stored negative id, which would tie with
# it) or "" (text): one type per tiebreak position.


def _trade(row: _Row) -> _Mapped:
    trade_id = _req_str(row, "trade_id")
    payload = RecordedTrade(
        side=_req_member(row, "side", _ORDER_SIDES),
        price=_req_decimal(row, "price"),
        size=_req_decimal(row, "size"),
        trade_id=trade_id,
        is_block=_opt_bool(row, "is_block"),
    )
    return _opt_int(row, "seq") or 0, (trade_id,), payload


def _book_delta(row: _Row) -> _Mapped:
    depth, side = _req_int(row, "depth"), _req_member(row, "side", _BOOK_SIDES)
    price, update_id = _req_decimal(row, "price"), _req_int(row, "update_id")
    cross_seq = _opt_int(row, "cross_seq")
    payload = RecordedBookDelta(depth, side, price, _req_decimal(row, "size"), update_id, cross_seq)
    return _book_seq(update_id, cross_seq), (update_id, depth, side, price), payload


def _book_snapshot(row: _Row) -> _Mapped:
    depth, update_id = _req_int(row, "depth"), _req_int(row, "update_id")
    cross_seq, epoch_id = _opt_int(row, "cross_seq"), _opt_id(row, "epoch_id")
    payload = RecordedBookSnapshot(
        depth, update_id, cross_seq, _levels(row, "bids"), _levels(row, "asks")
    )
    epoch = -1 if epoch_id is None else epoch_id
    return _book_seq(update_id, cross_seq), (update_id, depth, epoch), payload


def _ticker(row: _Row) -> _Mapped:
    payload = RecordedTicker(
        last_price=_opt_decimal(row, "last_price"),
        mark_price=_opt_decimal(row, "mark_price"),
        index_price=_opt_decimal(row, "index_price"),
        bid1_price=_opt_decimal(row, "bid1_price"),
        bid1_size=_opt_decimal(row, "bid1_size"),
        ask1_price=_opt_decimal(row, "ask1_price"),
        ask1_size=_opt_decimal(row, "ask1_size"),
        open_interest=_opt_decimal(row, "open_interest"),
        funding_rate=_opt_decimal(row, "funding_rate"),
        open_interest_value=_opt_decimal(row, "open_interest_value"),
        turnover_24h=_opt_decimal(row, "turnover_24h"),
        volume_24h=_opt_decimal(row, "volume_24h"),
        price_24h_pcnt=_opt_decimal(row, "price_24h_pcnt"),
        next_funding_ts=_opt_ts(row, "next_funding_ts"),
    )
    return 0, (), payload


def _kline(row: _Row) -> _Mapped:
    interval = _req_str(row, "interval")
    payload = RecordedKline(
        interval=interval,
        open=_req_decimal(row, "open"),
        high=_req_decimal(row, "high"),
        low=_req_decimal(row, "low"),
        close=_req_decimal(row, "close"),
        volume=_req_decimal(row, "volume"),
        turnover=_opt_decimal(row, "turnover"),
        confirmed=_opt_bool(row, "confirmed") is True,
    )
    return 0, (interval,), payload


def _liquidation(row: _Row) -> _Mapped:
    side = _req_member(row, "side", _ORDER_SIDES)
    price, size = _req_decimal(row, "price"), _req_decimal(row, "size")
    batch_index = _opt_id(row, "batch_index")
    payload = RecordedLiquidation(side, price, size, batch_index)
    return 0, (-1 if batch_index is None else batch_index, side, price, size), payload


def _open_interest(row: _Row) -> _Mapped:
    interval, source = _req_str(row, "interval"), _opt_str(row, "source")
    payload = RecordedOpenInterest(
        _req_decimal(row, "oi"), _opt_decimal(row, "oi_value"), interval, source
    )
    return 0, (interval, source or ""), payload


def _funding(row: _Row) -> _Mapped:
    payload = RecordedFunding(
        _req_decimal(row, "funding_rate"), _opt_int(row, "interval_min"), _opt_str(row, "source")
    )
    return 0, (), payload


_MAPPERS: Final[dict[StreamKind, Callable[[_Row], _Mapped]]] = {
    StreamKind.TRADES: _trade,
    StreamKind.ORDERBOOK_DELTA: _book_delta,
    StreamKind.ORDERBOOK_SNAPSHOT: _book_snapshot,
    StreamKind.TICKERS: _ticker,
    StreamKind.KLINES: _kline,
    StreamKind.LIQUIDATIONS: _liquidation,
    StreamKind.OPEN_INTEREST: _open_interest,
    StreamKind.FUNDING_RATES: _funding,
}


def event_from_row(stream: StreamKind, row: Mapping[str, object]) -> RecordedEvent:
    """Map one stored row of `stream` to its `RecordedEvent` (the tier-independent form).

    Fails closed with `StorageRecordInvalid` (naming the column, never a value) rather than
    skipping a row a replay would then silently lose."""
    mapper = _MAPPERS.get(stream)
    if mapper is None:
        raise StorageRecordInvalid(f"stream {stream.value!r} is not replayable")
    seq, tiebreak, payload = mapper(row)
    ts_us = _req_ts(row, "ts")
    return RecordedEvent(ts_us, seq, _req_str(row, "symbol"), stream, tiebreak, payload)
