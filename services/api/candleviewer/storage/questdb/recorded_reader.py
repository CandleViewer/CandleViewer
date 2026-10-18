"""`RecordedStreamReader` over the QuestDB hot tier (E26-T02).

Reads the recorded raw tables (`21-database-schema.md` Sec.4) over PGWire for the replay source.
Every query is one of a fixed set of literal SQL templates keyed by `StreamKind`, the registered
dataset id, so no caller text ever reaches SQL: symbol, time bounds and book depth are bind
parameters (SR-047), and only the validated integer row limit is inlined, because QuestDB's
PGWire has no `LIMIT $n` slot (#2168). Each template filters `symbol` by equality, bounds `ts` on
both sides and orders by the designated timestamp only (the Sec.13.2 query lint). Every fetch is
time-bounded, and driver failures become one typed `HotReplayReadError` with no chained cause
(a driver's text may name the server's host and port, RP-I02).

Rows arrive as the driver's read-only records (`LazyPgWire.fetch_records`), never copied into
dicts on the event loop, and map through `event_from_row`, the mapping the cold tier shares, in
a worker thread: a read's whole row cap of mapping stays off the loop the OMS shares (C-2.17).
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping, Sequence
from typing import Final, Protocol

import asyncpg

from candleviewer.domain.sql_names import assert_bind_count, ts_param
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.questdb.reader import QueryBuilder
from candleviewer.storage.repositories.recorded import (
    BOOK_STREAMS,
    RecordedEvent,
    RecordedQueryRejected,
    event_from_row,
    order_key,
)

#: Replayable stream -> its range query: literal text, the table from this allowlist.
RANGE_SQL: Final[Mapping[StreamKind, str]] = {
    StreamKind.TRADES: (
        "SELECT * FROM trades WHERE symbol = $1 AND ts >= $2 AND ts < $3 ORDER BY ts"
    ),
    StreamKind.ORDERBOOK_DELTA: (
        "SELECT * FROM orderbook_deltas WHERE symbol = $1 AND ts >= $2 AND ts < $3 AND depth = $4 "
        "ORDER BY ts"
    ),
    StreamKind.ORDERBOOK_SNAPSHOT: (
        "SELECT * FROM orderbook_snapshots WHERE symbol = $1 AND ts >= $2 AND ts < $3 "
        "AND depth = $4 ORDER BY ts"
    ),
    StreamKind.TICKERS: (
        "SELECT * FROM tickers WHERE symbol = $1 AND ts >= $2 AND ts < $3 ORDER BY ts"
    ),
    StreamKind.KLINES: (
        "SELECT * FROM klines WHERE symbol = $1 AND ts >= $2 AND ts < $3 ORDER BY ts"
    ),
    StreamKind.LIQUIDATIONS: (
        "SELECT * FROM liquidations WHERE symbol = $1 AND ts >= $2 AND ts < $3 ORDER BY ts"
    ),
    StreamKind.OPEN_INTEREST: (
        "SELECT * FROM open_interest WHERE symbol = $1 AND ts >= $2 AND ts < $3 ORDER BY ts"
    ),
    StreamKind.FUNDING_RATES: (
        "SELECT * FROM funding_rates WHERE symbol = $1 AND ts >= $2 AND ts < $3 ORDER BY ts"
    ),
}
#: The anchor lookup reads the newest `ANCHOR_ROWS` snapshots: SQL orders by `ts` only (the
#: lint), so snapshots sharing the latest instant (one per book epoch) are then ordered by
#: `order_key`, the order every tier and the replay merge share (24 Sec.13.7).
ANCHOR_ROWS: Final = 16
ANCHOR_SQL: Final = (
    "SELECT * FROM orderbook_snapshots WHERE symbol = $1 AND depth = $2 "
    "AND ts >= $3 AND ts <= $4 ORDER BY ts DESC LIMIT 16"
)
#: Upper bound on one read's row limit (the replay merge asks for its row cap + 1).
MAX_READ_ROWS: Final = 4_194_304
#: Below the replay merge's 30 s storage deadline, so a slow query fails here, typed, first.
DEFAULT_TIMEOUT_S: Final = 20.0
_SYMBOL_RE: Final = re.compile(r"^[A-Z0-9]{1,32}$")


class HotReplayReadError(StorageTierUnavailable):
    """QuestDB could not serve the read (connection lost, backoff, server error): typed, so a
    replay surfaces a datastore outage as one error (chaos scenario 10)."""

    code = "HOT_REPLAY_READ_ERROR"


#: Driver and connection failures a PGWire fetch can raise (timeouts stay `TimeoutError`).
_DRIVER_ERRORS: Final = (
    OSError,
    asyncpg.PostgresError,
    asyncpg.InterfaceError,
    asyncpg.InternalClientError,
)


class RecordFetcher(Protocol):
    """The PGWire surface the reader needs: rows as the driver's read-only mappings."""

    async def fetch_records(self, sql: str, *params: object) -> Sequence[Mapping[str, object]]: ...


def _mapped(stream: StreamKind, rows: Sequence[Mapping[str, object]]) -> list[RecordedEvent]:
    """Worker thread: stored rows to events."""
    return [event_from_row(stream, row) for row in rows]


def build_read_recorded(
    symbol: str, stream: StreamKind, rng: TimeRange, *, depth: int, limit: int
) -> QueryBuilder:
    """The range read of one `(symbol, stream)`: `[rng.start_us, rng.end_us)`, earliest
    `limit` rows, book streams filtered to `depth`."""
    template = RANGE_SQL.get(stream)
    if template is None:
        raise RecordedQueryRejected(f"stream {stream.value!r} is not a recorded table")
    if not _SYMBOL_RE.fullmatch(symbol):
        raise RecordedQueryRejected("symbol is not a plain instrument code")
    if isinstance(limit, bool) or not 1 <= limit <= MAX_READ_ROWS:
        raise RecordedQueryRejected(f"limit must be an int in 1..{MAX_READ_ROWS}")
    params: tuple[object, ...] = (symbol, ts_param(rng.start_us), ts_param(rng.end_us))
    if stream in BOOK_STREAMS:
        params = (*params, depth)
    sql = " ".join((template, "LIMIT", str(int(limit))))
    assert_bind_count(sql, params)
    return QueryBuilder(sql, params)


def build_snapshot_anchor(symbol: str, depth: int, at_us: int, not_before_us: int) -> QueryBuilder:
    """The latest `depth` snapshot with `not_before_us <= ts <= at_us` (two-sided bound)."""
    if not _SYMBOL_RE.fullmatch(symbol):
        raise RecordedQueryRejected("symbol is not a plain instrument code")
    params: tuple[object, ...] = (symbol, depth, ts_param(not_before_us), ts_param(at_us))
    assert_bind_count(ANCHOR_SQL, params)
    return QueryBuilder(ANCHOR_SQL, params)


class QuestDbRecordedReader:
    """Hot-tier `RecordedStreamReader`: QuestDB over PGWire (`RecordFetcher`)."""

    def __init__(self, connection: RecordFetcher, *, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        self._conn = connection
        self._timeout_s = timeout_s

    async def read(
        self, symbol: str, stream: StreamKind, rng: TimeRange, *, depth: int, limit: int
    ) -> list[RecordedEvent]:
        rows = await self._fetch(build_read_recorded(symbol, stream, rng, depth=depth, limit=limit))
        return await asyncio.to_thread(_mapped, stream, rows)

    async def snapshot_at(
        self, symbol: str, depth: int, at_us: int, *, not_before_us: int
    ) -> RecordedEvent | None:
        rows = await self._fetch(build_snapshot_anchor(symbol, depth, at_us, not_before_us))
        found = await asyncio.to_thread(_mapped, StreamKind.ORDERBOOK_SNAPSHOT, rows)
        if len(found) == ANCHOR_ROWS and found[0].ts_us == found[-1].ts_us:
            raise HotReplayReadError("more snapshots share one instant than an anchor lookup reads")
        return max(found, key=order_key, default=None)

    async def _fetch(self, query: QueryBuilder) -> Sequence[Mapping[str, object]]:
        try:
            async with asyncio.timeout(self._timeout_s):
                return await self._conn.fetch_records(query.sql, *query.params)
        except TimeoutError:
            raise
        except _DRIVER_ERRORS as exc:
            raise HotReplayReadError(f"hot replay read failed: {type(exc).__name__}") from None
