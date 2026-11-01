"""`QuestDbStoredPresence`: which minutes of the hot tier hold rows (E16-FR-03, #1739).

The recorder's coverage is session windows minus gap rows (`recorder.coverage`); a gap row
deleted or shrunk would make absent data read as present (threat model R-T1). This reader
answers from the data itself: for one `(symbol, stream)` and `[lo, hi)` it returns the merged
1-minute buckets that hold at least one stored row (`stored_spans`), and the order-book update-id
discontinuities (`seq_breaks`). It conforms to `recorder.coverage.StoredPresence` and to
`recorder.integrity.StoredData`; the recorder declares those ports, so it imports no storage.

Every statement is a literal template keyed by the recorder's stream name, the table from this
allowlist, so no caller text reaches SQL: symbol and time bounds are bind parameters (`ts_param`,
C-12.10), and only a validated integer row limit is inlined, because QuestDB's PGWire has no
`LIMIT $n` slot (#2168). Every fetch is time-bounded; a deadline is `StoredPresenceTimeout` and
a driver failure `StoredPresenceError`, each naming only the failure's type and holding no cause
or context (a driver's text may name the server's host and port, RP-I02).
"""

from __future__ import annotations

import asyncio
import math
import re
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Final, Protocol

import asyncpg

from candleviewer.domain.sql_names import assert_bind_count, ts_param, ts_us_from_row

BUCKET_US: Final = 60_000_000
#: Recorder stream -> its presence query: one row per 1-minute bucket that holds a row.
PRESENCE_SQL: Final[Mapping[str, str]] = MappingProxyType(
    {
        "trades": (
            "SELECT ts, count() AS n FROM trades WHERE symbol = $1 AND ts >= $2 AND ts < $3 "
            "SAMPLE BY 1m ALIGN TO CALENDAR"
        ),
        "orderbook_delta": (
            "SELECT ts, count() AS n FROM orderbook_deltas WHERE symbol = $1 AND ts >= $2 "
            "AND ts < $3 SAMPLE BY 1m ALIGN TO CALENDAR"
        ),
        "orderbook_snapshot": (
            "SELECT ts, count() AS n FROM orderbook_snapshots WHERE symbol = $1 AND ts >= $2 "
            "AND ts < $3 SAMPLE BY 1m ALIGN TO CALENDAR"
        ),
        "tickers": (
            "SELECT ts, count() AS n FROM tickers WHERE symbol = $1 AND ts >= $2 AND ts < $3 "
            "SAMPLE BY 1m ALIGN TO CALENDAR"
        ),
        "klines": (
            "SELECT ts, count() AS n FROM klines WHERE symbol = $1 AND ts >= $2 AND ts < $3 "
            "SAMPLE BY 1m ALIGN TO CALENDAR"
        ),
        "liquidations": (
            "SELECT ts, count() AS n FROM liquidations WHERE symbol = $1 AND ts >= $2 "
            "AND ts < $3 SAMPLE BY 1m ALIGN TO CALENDAR"
        ),
        "open_interest": (
            "SELECT ts, count() AS n FROM open_interest WHERE symbol = $1 AND ts >= $2 "
            "AND ts < $3 SAMPLE BY 1m ALIGN TO CALENDAR"
        ),
        "funding": (
            "SELECT ts, count() AS n FROM funding_rates WHERE symbol = $1 AND ts >= $2 "
            "AND ts < $3 SAMPLE BY 1m ALIGN TO CALENDAR"
        ),
    }
)
#: One row per distinct book update (per depth: the venue's update id runs per topic), oldest first.
SEQ_SQL: Final = (
    "SELECT depth, update_id, prev_update_id, min(ts) AS first_ts FROM orderbook_deltas "
    "WHERE symbol = $1 AND ts >= $2 AND ts < $3 AND prev_update_id IS NOT NULL "
    "GROUP BY depth, update_id, prev_update_id ORDER BY first_ts"
)
#: 140 days of minutes: past the 90-day coverage horizon, so a presence read is never cut short.
MAX_BUCKETS: Final = 201_600
#: Distinct book updates one `seq_breaks` read may return (a day at 10 Hz on two depths, plus
#: margin); a read that reaches it fails loud instead of reporting a truncated sequence.
MAX_SEQ_ROWS: Final = 2_000_000
DEFAULT_TIMEOUT_S: Final = 10.0
_SYMBOL_RE: Final = re.compile(r"^[A-Z0-9]{1,32}$")
_DRIVER_ERRORS: Final = (
    OSError,
    asyncpg.PostgresError,
    asyncpg.InterfaceError,
    asyncpg.InternalClientError,
)


class StoredPresenceError(Exception):
    """A presence read failed or was refused; the message names no host, path or value."""


class StoredPresenceTimeout(StoredPresenceError, TimeoutError):
    """A presence read exceeded its deadline."""


class RecordFetcher(Protocol):
    async def fetch_records(self, sql: str, *params: object) -> Sequence[Mapping[str, object]]: ...


def _window(symbol: str, lo: int, hi: int) -> None:
    if not _SYMBOL_RE.fullmatch(symbol):
        raise StoredPresenceError("symbol is not a plain instrument code")
    if isinstance(lo, bool) or isinstance(hi, bool) or not lo < hi:
        raise StoredPresenceError("the window must have lo < hi")
    if (hi - lo) // BUCKET_US + 2 > MAX_BUCKETS:
        raise StoredPresenceError(f"the window spans more than {MAX_BUCKETS} minutes")


def build_presence(symbol: str, stream: str, lo: int, hi: int) -> tuple[str, tuple[object, ...]]:
    """The presence query of `(symbol, stream)` over `[lo, hi)`, with its binds."""
    template = PRESENCE_SQL.get(stream)
    if template is None:
        raise StoredPresenceError("the stream is not a recorded table")
    _window(symbol, lo, hi)
    limit = (hi - lo) // BUCKET_US + 2  # the buckets the window can touch
    params: tuple[object, ...] = (symbol, ts_param(lo), ts_param(hi))
    sql = " ".join((template, "LIMIT", str(int(limit))))
    assert_bind_count(sql, params)
    return sql, params


def build_seq(symbol: str, lo: int, hi: int) -> tuple[str, tuple[object, ...]]:
    _window(symbol, lo, hi)
    params: tuple[object, ...] = (symbol, ts_param(lo), ts_param(hi))
    sql = " ".join((SEQ_SQL, "LIMIT", str(MAX_SEQ_ROWS)))
    assert_bind_count(sql, params)
    return sql, params


def merge_buckets(starts: Sequence[int], lo: int, hi: int) -> list[tuple[int, int]]:
    """Bucket starts -> merged `[a, b)` spans clipped to `[lo, hi)`; adjacent buckets join."""
    out: list[tuple[int, int]] = []
    for start in sorted(starts):
        a, b = max(lo, start), min(hi, start + BUCKET_US)
        if b <= a:
            continue
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def find_breaks(rows: Sequence[Mapping[str, object]]) -> list[tuple[int, int]]:
    """Per depth, an update whose `prev_update_id` is not the previous update's id: the span
    from the previous update to it. The first update of each depth has nothing to follow."""
    last: dict[int, tuple[int, int]] = {}  # depth -> (update_id, ts)
    out: list[tuple[int, int]] = []
    for row in rows:
        depth, uid = int(str(row["depth"])), int(str(row["update_id"]))
        prev, ts = int(str(row["prev_update_id"])), ts_us_from_row(row["first_ts"])
        held = last.get(depth)
        if held is not None and prev != held[0] and ts > held[1]:
            out.append((held[1], ts))
        last[depth] = (uid, ts)
    return sorted(out)


class QuestDbStoredPresence:
    """Hot-tier `StoredPresence` / `StoredData`: QuestDB over PGWire (`RecordFetcher`)."""

    def __init__(self, connection: RecordFetcher, *, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        if not (math.isfinite(timeout_s) and timeout_s > 0):
            raise ValueError("timeout_s must be a positive, finite number of seconds")
        self._conn = connection
        self._timeout_s = timeout_s

    async def stored_spans(
        self, symbol: str, stream: str, lo: int, hi: int
    ) -> list[tuple[int, int]]:
        rows = await self._fetch(*build_presence(symbol, stream, lo, hi))
        return merge_buckets([ts_us_from_row(r["ts"]) for r in rows], lo, hi)

    async def seq_breaks(self, symbol: str, lo: int, hi: int) -> list[tuple[int, int]]:
        rows = await self._fetch(*build_seq(symbol, lo, hi))
        if len(rows) >= MAX_SEQ_ROWS:
            raise StoredPresenceError("too many book updates in the window to check")
        return await asyncio.to_thread(find_breaks, rows)

    async def _fetch(self, sql: str, params: tuple[object, ...]) -> Sequence[Mapping[str, object]]:
        """Raised after the handler, so neither cause nor context holds the driver's text."""
        failure: StoredPresenceError
        try:
            async with asyncio.timeout(self._timeout_s):
                return await self._conn.fetch_records(sql, *params)
        except TimeoutError:
            failure = StoredPresenceTimeout(f"presence read exceeded {self._timeout_s}s")
        except _DRIVER_ERRORS as exc:
            failure = StoredPresenceError(f"presence read failed: {type(exc).__name__}")
        raise failure
