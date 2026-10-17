"""Range reads and stale-`build_version` handling for `bars_*` (E12-T02, #345).

`read_bars` returns oldest->newest with a cursor (the last raw row's `ts`, and for non-time
kinds its `(ts, generation, index)` key, #2017), parameterised queries only
(`symbol`/`bar_param` come from the client). Rows whose `row_checksum` does not verify are
dropped and counted (SR-E12-11). Rows at an older `build_version` than the running code are
served as-is and a rebuild is scheduled **once** per `(symbol, spec_hash)` window, not per poll.
`read_tail` (E12-T06, #2195) is the WS snapshot store's one bounded newest-first read: closed,
tape-built bars only, oldest first, inside a `ts` window measured back from the wall clock.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Final, Protocol

import structlog

from candleviewer.bars.limits import MAX_NON_TIME_WINDOW_US, MAX_TIME_WINDOW_US
from candleviewer.bars.limits import MAX_TAIL as MAX_TAIL  # end of life: #2787 D2-M1
from candleviewer.bars.metrics import bars_tape_read_degraded_total
from candleviewer.bars.models import Bar, BarSpec
from candleviewer.bars.rows import (
    BUILD_VERSIONS,
    BarPersistError,
    bar_param_for,
    check_generation,
    row_checksum,
)
from candleviewer.domain.sql_names import column_identifier, ts_param, ts_us_from_row
from candleviewer.observability.metrics import Counter


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


MAX_LIMIT: Final = 50_000
_FAMILIES: Final = frozenset(BUILD_VERSIONS)

bars_stale_build_version_total = Counter(
    "bars_stale_build_version_total", "Reads that found rows below the current build_version."
)
bars_checksum_mismatch_total = Counter(
    "bars_checksum_mismatch_total",
    "Rows treated as an integrity event on read (reason: mismatch | missing).",
    ["table", "reason"],
)
bars_rebuild_scheduled_total = Counter(
    "bars_rebuild_scheduled_total", "Background rebuilds requested (post single-flight/dedup)."
)

#: Rebuild windows are quantised to this grid so a client cannot mint unbounded distinct keys.
WINDOW_GRID_US: Final = 86_400_000_000  # 1 day
MAX_BUCKETS_PER_SERIES: Final = 8  # beyond this, windows collapse into one catch-all bucket
MAX_REGISTRY: Final = 1_024  # SR-E12-05
TTL_S: Final = 300.0
MAX_ATTEMPTS: Final = 5
BACKOFF_BASE_S: Final = 2.0


class RowFetcher(Protocol):
    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]: ...


#: A stored bar's position: `(ts µs, generation, index)` (#2017). Unique per series (DEDUP key).
BarKey = tuple[int, int, int]
#: `BarTail.builds` key: a stored bar's `(generation, index, open_time µs)`, unique per series
#: even across a builder cold start that reused a `(generation, index)` (#2662).
BuildKey = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class BarPage:
    rows: list[dict[str, object]]
    next_cursor: int | None  # ts (µs) to pass as `after_ts_us`; None = no more rows
    stale: bool  # served from rows below the current build_version (meta.sources)
    #: SR-E12-11 (documented choice: marker, not exception): True when rows were withheld for an
    #: integrity failure, so the page is INCOMPLETE and the caller must not cache it as final.
    integrity_degraded: bool = False
    dropped: int = 0  # rows withheld (checksum mismatch or missing)
    #: Non-time kinds only (#2017): `(ts, generation, index)` of the last RAW row of a full
    #: fetch, i.e. the next page's first row (resume with `at_key=`); None = no more rows.
    next_key: BarKey | None = None


#: Ordering (#2017, 21 §9.5 choice (a)). `ts` stays primary everywhere: `index` restarts at 0 in
#: every new generation (each builder cold start begins one, #2662), so it is not chronological
#: across generations, and legacy generation-0 history repeats `(generation, index)` after an old
#: cold start (#2126 regression (b)). `bars_time` holds NULL-`index` kline rows, so it keeps
#: `ts, "index"` with a `ts` cursor (unique open time per interval). Non-time kinds order by
#: `ts, generation, "index"` and resume by keyset on that full key, so equal-`ts` siblings (renko
#: multi-brick, volume splits) are never skipped at a page boundary. Within one generation whose
#: `index` increases with `ts` this is exactly the contract's `(generation, index)` order.
#: `index` is a QuestDB reserved word: quoted via the shared helper (#2016), never hand-written.
_ORDER_BY_TIME = ", ".join(column_identifier(c) for c in ("ts", "index"))
_ORDER_BY_KEY = ", ".join(column_identifier(c) for c in ("ts", "generation", "index"))
#: QuestDB has no row-value comparison: `(ts, generation, index) >= ($5, $7, $9)` expanded.
#: A NULL `index` sorts first and is `row_key` index -1; resuming AT such a row must also admit
#: NULL (a comparison with NULL is never true), so that variant adds `OR "index" IS NULL`.
_GEN, _IDX = column_identifier("generation"), column_identifier("index")
_KEY_FROM = f"AND (ts > $5 OR (ts = $6 AND ({_GEN} > $7 OR ({_GEN} = $8 AND {_IDX} >= $9))))"
_KEY_FROM_NULL = (
    f"AND (ts > $5 OR (ts = $6 AND ({_GEN} > $7 OR ({_GEN} = $8 AND "
    f"({_IDX} >= $9 OR {_IDX} IS NULL)))))"
)


def build_range_query(
    kind: str,
    symbol: str,
    bar_param: str,
    from_us: int,
    to_us: int,
    after_us: int | None,
    limit: int,
    *,
    at_key: BarKey | None = None,
) -> tuple[str, tuple[object, ...]]:
    """`after_us` (time bars): resume after that ts. `at_key` (non-time bars): resume AT that
    `(ts, generation, index)` inclusive. The `from`/`to` window predicate always applies."""
    if kind not in _FAMILIES:
        raise ValueError(f"unknown bar kind {kind!r}")
    if not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
    if at_key is not None and (kind == "time" or after_us is not None):
        raise ValueError("at_key is only for non-time bars and excludes after_us")
    start = from_us if after_us is None else max(from_us, after_us + 1)
    order = _ORDER_BY_TIME if kind == "time" else _ORDER_BY_KEY
    key_sql = ""
    if at_key is not None:
        key_sql = f" {_KEY_FROM_NULL if at_key[2] < 0 else _KEY_FROM}"
    sql = (
        f"SELECT * FROM bars_{kind} WHERE symbol = $1 AND bar_param = $2 "  # noqa: S608  # nosec B608 reason=table-from-closed-allowlist owner=@CandleViewer/backend
        f"AND ts >= $3 AND ts < $4{key_sql} ORDER BY {order} LIMIT {int(limit)}"
    )
    # QuestDB 8.x does not count `LIMIT $n` as a bind slot (asyncpg: "server expects 4
    # arguments"), so the validated-int `limit` (1..MAX_LIMIT, checked above) is inlined.
    params: tuple[object, ...] = (symbol, bar_param, ts_param(start), ts_param(to_us))
    if at_key is not None:
        ts_us, gen, idx = (int(v) for v in at_key)
        params += (ts_param(ts_us), ts_param(ts_us), gen, gen, max(idx, 0))
    return sql, params


#: A time-bar tail looks back this many times the span of `limit` bars (room for recording gaps).
TAIL_SPAN_FACTOR: Final = 2
#: `read_tail` yields to the loop after every this many rows (~24 µs of CPU a row, C-2.17).
TAIL_YIELD_EVERY: Final = 128
_ORDER_BY_KEY_DESC = ", ".join(
    f"{column_identifier(c)} DESC" for c in ("ts", "generation", "index")
)


def tail_window_us(spec: BarSpec, limit: int) -> int:
    """How far back from now `read_tail` looks, within the SR-E12-02 window caps: time bars
    `TAIL_SPAN_FACTOR` times the span of `limit` bars; other kinds have no fixed span, so they
    get the whole non-time window."""
    if spec.kind != "time":
        return MAX_NON_TIME_WINDOW_US
    return min(limit * int(spec.param_value) * 1_000 * TAIL_SPAN_FACTOR, MAX_TIME_WINDOW_US)


def build_tail_query(
    kind: str, symbol: str, bar_param: str, limit: int, from_us: int, *, now_us: int
) -> tuple[str, tuple[object, ...]]:
    """The newest `limit` builder rows of one series at or after `from_us`, newest first by the
    full bar key (the caller reverses). Kline rows (NULL `index`) carry no bar key and are left
    out. A `from_us` further back from `now_us` than the kind's SR-E12-02 window cap is refused:
    a check against the caller's clock (`read_tail` passes the one it windows with), not a clamp."""
    if kind not in _FAMILIES:
        raise ValueError(f"unknown bar kind {kind!r}")
    if not 1 <= limit <= MAX_TAIL:
        raise ValueError(f"limit must be between 1 and {MAX_TAIL}")
    if from_us < now_us - (MAX_TIME_WINDOW_US if kind == "time" else MAX_NON_TIME_WINDOW_US):
        raise ValueError(f"from_us is older than the {kind} bars window cap (SR-E12-02)")
    # QuestDB 8.1.1 predates upstream #5148 (a multi-key DESC LIMIT sorts its whole scan): bound ts.
    sql = (
        f"SELECT * FROM bars_{kind} WHERE symbol = $1 AND bar_param = $2 AND ts >= $3 "  # noqa: S608  # nosec B608 reason=table-from-closed-allowlist owner=@CandleViewer/backend
        f"AND {_IDX} IS NOT NULL ORDER BY {_ORDER_BY_KEY_DESC} LIMIT {int(limit)}"
    )
    return sql, (symbol, bar_param, ts_param(from_us))


def row_key(row: dict[str, object]) -> BarKey:
    """`(ts µs, generation, index)` of a stored row (NULL generation/index read as 0/-1)."""
    gen, idx = row.get("generation"), row.get("index")
    return (
        ts_us_from_row(row["ts"]),
        0 if gen is None else int(str(gen)),
        -1 if idx is None else int(str(idx)),
    )


@dataclass(slots=True)
class _Rebuild:
    expires: float
    attempts: int = 0
    next_try: float = 0.0
    in_flight: bool = False
    done: bool = False


class RebuildRegistry:
    """Single-flight, bounded, TTL-pruned rebuild scheduling (BR-31, SR-E12-05)."""

    def __init__(
        self,
        schedule: Callable[[str, str, int, int], Awaitable[None]],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._schedule = schedule
        self._clock = clock
        self._entries: OrderedDict[tuple[str, str, int, int], _Rebuild] = OrderedDict()
        self._per_series: dict[tuple[str, str], int] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def _prune(self, now: float) -> None:
        for key in [k for k, e in self._entries.items() if e.expires <= now and not e.in_flight]:
            self._drop(key)

    def _drop(self, key: tuple[str, str, int, int]) -> None:
        del self._entries[key]
        series = key[:2]
        self._per_series[series] -= 1
        if self._per_series[series] <= 0:
            del self._per_series[series]

    def _key(
        self, symbol: str, spec_hash: str, from_us: int, to_us: int
    ) -> tuple[str, str, int, int]:
        lo, hi = from_us // WINDOW_GRID_US, to_us // WINDOW_GRID_US
        key = (symbol, spec_hash, lo, hi)
        if (
            key not in self._entries
            and self._per_series.get((symbol, spec_hash), 0) >= MAX_BUCKETS_PER_SERIES
        ):
            return (symbol, spec_hash, -1, -1)  # catch-all bucket
        return key

    async def request(self, symbol: str, spec_hash: str, from_us: int, to_us: int) -> bool:
        """True if this call started a rebuild; False if deduplicated/backing off/refused."""
        now = self._clock()
        self._prune(now)
        key = self._key(symbol, spec_hash, from_us, to_us)
        entry = self._entries.get(key)
        if entry is None:
            if len(self._entries) >= MAX_REGISTRY:
                return False  # full of live entries: refuse rather than grow
            entry = _Rebuild(expires=now + TTL_S)
            self._entries[key] = entry
            self._per_series[key[:2]] = self._per_series.get(key[:2], 0) + 1
        if entry.in_flight or entry.done or now < entry.next_try or entry.attempts >= MAX_ATTEMPTS:
            return False
        entry.in_flight = True
        try:
            await self._schedule(
                symbol, spec_hash, key[2] * WINDOW_GRID_US, (key[3] + 1) * WINDOW_GRID_US
            )
        except Exception:
            entry.attempts += 1
            entry.next_try = now + BACKOFF_BASE_S * 2 ** (entry.attempts - 1)
            _log().warning(
                "bars_rebuild_schedule_failed", spec_hash=spec_hash, attempts=entry.attempts
            )
            return False
        else:
            entry.done = True
            bars_rebuild_scheduled_total.inc()
            return True
        finally:
            entry.in_flight = False


def _wall_us() -> int:
    """Epoch µs now: `read_tail` measures its window back from the wall clock."""
    return time.time_ns() // 1_000


class BarReader:
    def __init__(
        self,
        conn: RowFetcher,
        schedule_rebuild: Callable[[str, str, int, int], Awaitable[None]],
        clock: Callable[[], float] = time.monotonic,
        *,
        now_us: Callable[[], int] = _wall_us,
    ) -> None:
        self._conn = conn
        self._rebuilds = RebuildRegistry(schedule_rebuild, clock)
        self._now_us = now_us

    async def read_bars(
        self,
        symbol: str,
        spec: BarSpec,
        from_us: int,
        to_us: int,
        limit: int,
        *,
        after_us: int | None = None,
        at_key: BarKey | None = None,
    ) -> BarPage:
        sql, params = build_range_query(
            spec.kind, symbol, bar_param_for(spec), from_us, to_us, after_us, limit, at_key=at_key
        )
        raw = await self._conn.fetch(sql, *params)
        rows = [r for r in raw if not _untrusted(r, spec)]
        dropped = len(raw) - len(rows)
        current = BUILD_VERSIONS[spec.kind]
        stale = any(int(str(r.get("build_version") or 0)) < current for r in rows)
        if stale:
            bars_stale_build_version_total.inc()
            await self._rebuilds.request(symbol, spec.spec_hash, from_us, to_us)
        more = len(raw) == limit
        cursor = ts_us_from_row(raw[-1]["ts"]) if more and raw else None
        key = row_key(raw[-1]) if more and raw and spec.kind != "time" else None
        return BarPage(
            rows, cursor, stale, integrity_degraded=dropped > 0, dropped=dropped, next_key=key
        )

    async def read_tail(self, symbol: str, spec: BarSpec, limit: int) -> BarTail:
        """The newest `limit` closed, tape-built bars of a series inside `tail_window_us`, oldest
        first (WS `bars` snapshot hydration, #2195): one `build_tail_query` read, reversed.
        Untrusted rows are dropped and counted as in `read_bars`; stale `build_version` rows are
        served as-is. A malformed row is skipped, never fatal to the whole tail: one whose
        generation is outside the writer's bound (`check_generation`) too.

        Callers skip a `history` of 0 (a `limit` below 1 raises) and bound every read with a
        timeout, degrading when it expires (SR-E12-01). `BarTail` says what `since_us` and
        `fetched` tell of a tail shorter than `limit`, and what they do not."""
        now = self._now_us()
        since = now - tail_window_us(spec, limit)
        bar_param = bar_param_for(spec)
        sql, params = build_tail_query(spec.kind, symbol, bar_param, limit, since, now_us=now)
        raw = await self._conn.fetch(sql, *params)
        current = BUILD_VERSIONS[spec.kind]
        bars: list[tuple[int, Bar]] = []
        builds: dict[BuildKey, int] = {}
        dropped = skipped = malformed = 0
        error = ""
        for n, row in enumerate(reversed(raw)):
            if n and n % TAIL_YIELD_EVERY == 0:
                await asyncio.sleep(0)  # C-2.17: never hold the loop for a whole 1 000-row tail
            if _untrusted(row, spec):
                dropped += 1
                continue
            try:
                got = _tail_bar(row, spec)
                built = max(1, int(str(row.get("build_version") or 0)))  # NULL: a pre-0003 v1 row
            except (ArithmeticError, ValueError, TypeError, BarPersistError) as exc:
                malformed, error = malformed + 1, error or type(exc).__name__
                continue
            if got is None:
                skipped += 1
                continue
            bars.append(got)
            gen, bar = got
            if built < current:
                builds[gen, bar.index, bar.open_time] = built
        if malformed:
            _log().warning(
                "bars_tail_rows_malformed", table=f"bars_{spec.kind}", spec_hash=spec.spec_hash,
                rows=malformed, error_type=error,
            )  # fmt: skip
        return BarTail(
            bars, skipped=skipped + malformed, builds=builds, dropped=dropped, since_us=since,
            fetched=len(raw),
        )  # fmt: skip


@dataclass(frozen=True, slots=True)
class BarTail:
    """`read_tail` result: `(generation, bar)` pairs, oldest first.

    `skipped` counts the rows left out for not being closed or tape-built, for lacking a §8.2
    `(generation, index)` key or a value the bar needs (NULL is never turned into zero, BR-07),
    or for holding a malformed value. `dropped` counts the rows withheld by the integrity check
    (SR-E12-11): a tail that is `integrity_degraded` is INCOMPLETE and must not be kept as final.

    `since_us` and `fetched` say where the read stopped, and no more. `fetched` below the `limit`
    asked for means the read took every builder row (one with a bar index) from `since_us` on;
    `bars` can hold fewer, since rows are dropped, skipped or malformed. They do not say whether
    older bars exist below `since_us`, nor why a short tail is short: the series' first bar, or
    the window ending the read (`tail_window_us`: for a time kind `TAIL_SPAN_FACTOR` times the
    span of `limit` bars, within the SR-E12-02 cap; for any other kind the cap itself). Telling
    an exhausted series apart needs its recording start (REST `meta.recording_started_at`)
    compared with `since_us`.
    """

    bars: list[tuple[int, Bar]]
    skipped: int = 0
    #: `BuildKey -> build_version` of the rows built below the running code (§6.1
    #: `meta.build_version` is the lowest among the bars a snapshot sends).
    builds: dict[BuildKey, int] = field(default_factory=dict)
    dropped: int = 0
    #: Where the read stopped: its window start (µs) and the rows the query returned, before
    #: drops and skips. `fetched` below the limit: every builder row from `since_us` on was
    #: taken. Not whether older bars exist, nor why the tail is short (see the class docstring).
    #: `read_tail` always sets both. A `BarTail` built by hand leaves both at 0, which is not a
    #: measurement: its `since_us` is no window start of 1970 (a real read's is now minus its
    #: window), and its `fetched` is no empty read (a real read of a tapeless series reports 0).
    since_us: int = 0
    fetched: int = 0

    @property
    def integrity_degraded(self) -> bool:
        return self.dropped > 0


#: The stored columns a tail bar takes as data: a NULL in any of them skips the row.
_TAIL_VALUES: Final = (
    "close_ts", "volume", "buy_volume", "sell_volume", "delta", "min_delta", "max_delta",
    "trade_count", "vwap",
)  # fmt: skip


def _tail_bar(row: dict[str, object], spec: BarSpec) -> tuple[int, Bar] | None:
    """A tape-built closed row as `(generation, Bar)`, in the REST row semantics of `stored_bar`
    (turnover is `vwap * volume`); `partial`/`gap_before` are not stored and read as False.
    None for any other row, or one with a NULL in `_TAIL_VALUES`: nothing is invented."""
    if any(row.get(c) is None for c in _TAIL_VALUES):
        return None
    s = stored_bar(row)
    if not (s.tape_built and s.confirmed) or s.index is None or s.generation is None:
        return None
    check_generation(s.generation, source=s.source)  # 0..MAX_GENERATION, as written
    bar = Bar.model_construct(
        spec_hash=spec.spec_hash, symbol=str(row["symbol"]), index=s.index, open_time=s.ts_us,
        close_time=ts_us_from_row(row["close_ts"]), open=Decimal(s.open), high=Decimal(s.high),
        low=Decimal(s.low), close=Decimal(s.close), volume=Decimal(s.volume),
        buy_volume=_dec(row["buy_volume"]), sell_volume=_dec(row["sell_volume"]),
        delta=_dec(row["delta"]), min_delta=_dec(row["min_delta"]),
        max_delta=_dec(row["max_delta"]), trade_count=s.trades, turnover=Decimal(s.turnover),
        vwap=_dec(row["vwap"]), closed=True, partial=False, gap_before=False,
    )  # fmt: skip
    return s.generation, bar


def _dec(value: object) -> Decimal:
    return Decimal(_num(value))


@dataclass(frozen=True, slots=True)
class StoredBar:
    """A `bars_*` row in the kline-like shape `api.market_response` serialises.

    Prices stay the stored DOUBLE rendered with `repr` (round-trips exactly, `bars.rows`).
    `turnover` is not a stored column: it is `vwap * volume` computed in `Decimal`, rendered
    the same way.
    """

    ts_us: int
    close_ts_us: int | None
    open: str
    high: str
    low: str
    close: str
    volume: str
    turnover: str
    confirmed: bool
    trades: int
    delta: str | None  # None on kline-sourced rows: no order flow (null, never zero, BR-07)
    min_delta: str | None
    max_delta: str | None
    source: str
    index: int | None = None  # NULL on kline-sourced `bars_time` rows (no builder index)
    generation: int | None = None

    @property
    def tape_built(self) -> bool:
        """Built from recorded trades (`tape`, or `parquet` = restored tape, `SOURCE_RANK`)."""
        return self.source in ("tape", "parquet")


def _num(v: object) -> str:
    return repr(float(str(v)))


def stored_bar(row: dict[str, object]) -> StoredBar:
    close_ts = row.get("close_ts")
    vwap, volume = Decimal(str(row.get("vwap") or 0)), Decimal(str(row.get("volume") or 0))
    source = str(row.get("source") or "tape")  # NULL = pre-0003 legacy row, tape-built
    flow = source != "kline"
    idx, gen = row.get("index"), row.get("generation")
    return StoredBar(
        ts_us=ts_us_from_row(row["ts"]),
        close_ts_us=ts_us_from_row(close_ts) if close_ts is not None else None,
        open=_num(row["open"]), high=_num(row["high"]), low=_num(row["low"]),
        close=_num(row["close"]), volume=_num(volume), turnover=repr(float(vwap * volume)),
        confirmed=bool(row.get("is_closed")), trades=int(str(row.get("trade_count") or 0)),
        delta=_num(row.get("delta") or 0) if flow else None,
        min_delta=_num(row.get("min_delta") or 0) if flow else None,
        max_delta=_num(row.get("max_delta") or 0) if flow else None, source=source,
        index=None if idx is None else int(str(idx)),
        generation=None if gen is None else int(str(gen)),
    )  # fmt: skip


class _Window(Protocol):
    @property
    def start_us(self) -> int: ...
    @property
    def end_us(self) -> int: ...


TapeTimeBars = Callable[[str, str, _Window, "int | None"], Awaitable[list[StoredBar]]]


def tape_time_bar_reader(reader: BarReader, *, timeout_s: float) -> TapeTimeBars:
    """`/market/klines` tier (1): tape-built `bars_time` rows for a kline interval code.

    Only tape-built rows are returned (kline-sourced `bars_time` rows are not tape and must not
    claim it). A failing or slow tape tier degrades the response to klines-only (never a 500,
    never a false `tape` claim): `meta.sources` then honestly omits `tape`.

    S2/A2 (#2087 reviews): the catch is deliberately `Exception`, not a driver class list.
    `LazyPgWire.fetch` re-raises raw asyncpg errors (e.g. `UndefinedTableError` when `bars_time`
    does not exist yet), and `bars` may not import `asyncpg` (ADR-0003 import contract), so it
    cannot name `asyncpg.PostgresError`. Cancellation is a `BaseException` and still propagates.
    Every degrade is counted (`bars_tape_read_degraded_total{reason}`) and logged WARN.
    """
    from candleviewer.bars.spec import TIME_INTERVALS  # cycle break: spec imports models

    async def read(symbol: str, interval: str, rng: _Window, limit: int | None) -> list[StoredBar]:
        interval_ms = TIME_INTERVALS.get(interval)
        if interval_ms is None or rng.end_us <= rng.start_us:
            return []
        spec = BarSpec(kind="time", interval_ms=interval_ms)
        try:
            async with asyncio.timeout(timeout_s):
                page = await reader.read_bars(
                    symbol, spec, rng.start_us, rng.end_us, min(limit or MAX_LIMIT, MAX_LIMIT)
                )
        except Exception as exc:  # broad on purpose: see the S2/A2 note in the docstring
            bars_tape_read_degraded_total.labels(reason=degrade_reason(exc)).inc()
            _log().warning("bars_tape_read_degraded", error=type(exc).__name__)
            return []
        return [b for b in map(stored_bar, page.rows) if b.tape_built]

    return read


def degrade_reason(exc: Exception) -> str:
    """A failed tape read's bounded `reason` label (also the WS series store's)."""
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, (OSError, ConnectionError)):
        return "connection"
    return "query_error"


def _integrity_failure(row: dict[str, object]) -> str | None:
    """None if trustworthy. NULL checksum is untrusted unless the row is pre-0003 legacy
    (both `source` and `row_checksum` NULL: 0003 is their first writer)."""
    checksum = row.get("row_checksum")
    if checksum is None:
        return None if row.get("source") is None else "missing"
    return None if checksum == row_checksum(row) else "mismatch"


def _untrusted(row: dict[str, object], spec: BarSpec) -> bool:
    """SR-E12-11: True, counted and logged, when `row` fails its integrity check."""
    reason = _integrity_failure(row)
    if reason is None:
        return False
    table = f"bars_{spec.kind}"
    bars_checksum_mismatch_total.labels(table, reason).inc()
    _log().warning(
        "bars_row_integrity_event", table=table, reason=reason,
        spec_hash=spec.spec_hash, ts=row.get("ts"),
    )  # fmt: skip
    return True
