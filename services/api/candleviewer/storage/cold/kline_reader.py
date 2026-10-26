"""Bounded Parquet read path for `/market/klines` (E12 cold tier, issue #2048).

Layout `klines/symbol=<S>/interval=<I>/ym=<YYYY-MM>/part-*.parquet` (`21-database-schema.md`
Sec.5.1). Every path is built by `DatasetRegistry.resolve_partition`, which validates the
symbol/interval/month against a closed charset *before* any join (SR-097), so `../x` never
reaches the filesystem. The scan is bounded: only the months the (already capped) window
touches are opened, only manifest-listed + verified files are read, the DuckDB statement is
fully parameterised, `LIMIT` is pushed down, and the blocking call runs off the event loop
under a timeout (C-2.18) that interrupts the read's DuckDB cursor. Reads share one in-memory
DuckDB instance per reader, each on its own `cursor()` (#2523): no per-read connect/close.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from operator import attrgetter
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb
import pyarrow as pa
import pyarrow.compute as pc
import structlog

from candleviewer.observability.context import thread_future
from candleviewer.storage.cold.layout import ColdPaths, DatasetRegistry
from candleviewer.storage.cold.manifest import ManifestStore
from candleviewer.storage.cold.observability import LoggingSystemEventSink, SystemEventSink
from candleviewer.storage.cold.scrub import verify_partition
from candleviewer.storage.errors import StorageExportVerifyFailed, StorageTierUnavailable
from candleviewer.storage.models import StreamKind

if TYPE_CHECKING:  # storage never imports ingestion at runtime (C-3.1)
    from candleviewer.ingestion.kline_coverage import Range

_MAX_MONTHS = 120
_DEFAULT_MAX_ROWS = 5_100
_DEFAULT_CONCURRENCY = 2
_MEMORY_LIMIT = "256MiB"
_THREADS = 2


class ColdKlineReadTimeout(StorageTierUnavailable):
    """The DuckDB kline read exceeded its deadline (route maps this to 503)."""

    code = "COLD_KLINE_READ_TIMEOUT"


class ColdKlineReadError(StorageTierUnavailable):
    """Integrity failure (checksum/row-count mismatch, quarantined partition: the whole cold
    read fails, never a partial window), schema drift or a corrupt file.

    DuckDB/Parquet could not serve the read (schema drift, corrupt file): route -> 503."""

    code = "COLD_KLINE_READ_ERROR"


@dataclass(frozen=True, slots=True)
class ColdKlineRow:
    """One Parquet kline, shaped like `ingestion.kline_read.KlineRowLike`."""

    ts_us: int
    open: str
    high: str
    low: str
    close: str
    volume: str
    turnover: str
    confirmed: bool
    source: str


def _num(value: object) -> str:
    """Decimal text of a Parquet value, equal to `format(Decimal(repr(v)), "f")` for floats.

    #2523: a float `repr` with no exponent (`e`) and not `inf`/`nan` (`n`) is already that
    text, so the Decimal round-trip runs only for the forms that need it."""
    if isinstance(value, float):
        text = repr(value)
        # exponent forms hold "e"; the only reprs holding "n" are inf, -inf and nan
        if "e" in text or "n" in text:
            return format(Decimal(text), "f")
        return text
    return str(value)


def months_between(start_us: int, end_us: int) -> list[str]:
    """`YYYY-MM` keys of every month overlapping `[start_us, end_us)`, oldest first."""
    if end_us <= start_us:
        return []
    first = datetime.fromtimestamp(start_us / 1_000_000, tz=UTC)
    last = datetime.fromtimestamp((end_us - 1) / 1_000_000, tz=UTC)
    out: list[str] = []
    y, m = first.year, first.month
    while (y, m) <= (last.year, last.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out[-_MAX_MONTHS:]


class ParquetKlineReader:
    """`ColdKlineReader` (see `ingestion.kline_read`) over the cold lake."""

    def __init__(
        self,
        registry: DatasetRegistry,
        *,
        events: SystemEventSink | None = None,
        timeout_s: float = 5.0,
        max_rows: int = _DEFAULT_MAX_ROWS,
        max_concurrency: int = _DEFAULT_CONCURRENCY,
    ) -> None:
        self._registry = registry
        self._events: SystemEventSink = events or LoggingSystemEventSink()
        self._timeout_s = timeout_s
        self._max_rows = max_rows
        # C-2.18: bound concurrent DuckDB scans (each is a thread + a cursor on the one shared
        # in-memory instance, so `memory_limit` / `threads` cap all of them together).
        self._sem = asyncio.Semaphore(max(1, max_concurrency))
        self._verified: dict[Path, tuple[int, int]] = {}
        self._db: _SharedDuckDB | None = None

    def close(self) -> None:
        """Release the shared DuckDB instance; it closes once no read still holds a cursor.
        A later read opens a fresh one."""
        if self._db is not None:
            self._retire(self._db)

    def _retire(self, db: _SharedDuckDB) -> None:
        # Closing the instance closes its cursors, so an in-flight read keeps it open until
        # its worker returns (`_release`). Only the event loop thread runs this.
        if self._db is db:
            self._db = None
        db.retired = True
        if db.users == 0:
            db.con.close()

    def _shared(self) -> _SharedDuckDB:
        """The shared instance, opened on first use. Limits go through connect-config."""
        if self._db is None:
            con = duckdb.connect(
                ":memory:", config={"memory_limit": _MEMORY_LIMIT, "threads": str(_THREADS)}
            )
            self._db = _SharedDuckDB(con)
        return self._db

    def _cursor(self) -> tuple[_SharedDuckDB, duckdb.DuckDBPyConnection]:
        """A cursor for one read. A broken instance (`cursor()` fails) is retired and replaced
        once; if the fresh one fails too, the read fails typed (503)."""
        db = self._shared()
        try:
            cur = db.con.cursor()
        except duckdb.Error:
            self._retire(db)
            db = self._shared()
            try:
                cur = db.con.cursor()
            except duckdb.Error as exc:
                self._retire(db)
                raise ColdKlineReadError(f"cold kline read failed: {type(exc).__name__}") from exc
        db.users += 1
        return db, cur

    def _release(self, db: _SharedDuckDB, fut: asyncio.Future[Any]) -> None:
        """Done-callback of a read's worker future (event loop thread). It runs only once the
        worker thread has returned: `thread_future` is a plain executor future that nothing but
        this reader could cancel, and it never does. So a caller cancelled mid-read, or the
        loop tearing down (which cancels Tasks, never this future), leaves the read counted
        until its worker is out of DuckDB, and a retired instance is never closed under it.
        Any failure other than our own timeout's interrupt retires the instance, so a poisoned
        one is never reused."""
        db.users -= 1
        exc = fut.exception()
        if exc is not None and not isinstance(exc.__cause__, duckdb.InterruptException):
            self._retire(db)
        elif db.retired and db.users == 0:
            db.con.close()

    def _partition(self, symbol: str, interval: str, ym: str) -> ColdPaths:
        return self._registry.resolve_partition(
            StreamKind.KLINES, partition_values={"symbol": symbol, "interval": interval, "ym": ym}
        )

    async def _files(self, paths: ColdPaths) -> list[str]:
        store = ManifestStore(paths.manifests_dir)
        read = store.read_with_quarantine
        try:
            entries, quarantined = await asyncio.to_thread(read, paths.partition_dir, paths.root)
        except OSError:  # its text names the path: typed, with no chain (503)
            raise ColdKlineReadError("cold kline partition could not be listed") from None
        if quarantined:
            # #3477: the manifest no longer names the quarantined part, so the month's other
            # parts would pass for all of it. Fail the cold read (503) until it is cleared.
            raise ColdKlineReadError("cold kline partition holds a quarantined part")
        files = [paths.partition_dir / e.file for e in entries]
        if not files:
            return []
        stamps = await asyncio.to_thread(_stamps, files)
        if any(self._verified.get(f) != stamps[f] for f in files):
            try:
                await verify_partition(paths, self._events)
            except StorageExportVerifyFailed as exc:
                # B1: a quarantined partition is an integrity event. Fail the cold read (503)
                # rather than silently serving a partial window.
                raise ColdKlineReadError("cold kline partition failed verification") from exc
            self._verified.update(stamps)
        return [f.as_posix() for f in files]

    async def __call__(self, symbol: str, interval: str, rng: Any) -> list[ColdKlineRow]:
        lo, hi = int(rng.start_us), int(rng.end_us)
        files: list[str] = []
        # Validation happens inside `_partition` for every component, before any I/O.
        for ym in months_between(lo, hi):
            files.extend(await self._files(self._partition(symbol, interval, ym)))
        if not files:
            return []
        return await self._query(files, lo, hi)

    async def page(
        self, symbol: str, interval: str, rng: Range
    ) -> ColdKlinePage | list[ColdKlineRow]:
        """`ingestion.kline_read.ColdKlinePager`: the window as a `ColdKlinePage` (bar JSON
        emitted by DuckDB, #2523 lever 4), or the lever-3 rows when the files cannot be emitted
        as JSON text. Same files, verification, bounds and timeout as `__call__`."""
        lo, hi = int(rng.start_us), int(rng.end_us)
        files: list[str] = []
        for ym in months_between(lo, hi):
            files.extend(await self._files(self._partition(symbol, interval, ym)))
        if not files:
            return []
        async with self._sem:
            return await self._query_unbounded(_read_page, files, lo, hi)

    async def _query(self, files: list[str], lo: int, hi: int) -> list[ColdKlineRow]:
        async with self._sem:
            return await self._query_unbounded(_read_rows, files, lo, hi)

    async def _query_unbounded[T](
        self, worker: Callable[[duckdb.DuckDBPyConnection, list[str], int, int, int], T],
        files: list[str], lo: int, hi: int,
    ) -> T:  # fmt: skip
        # N4: take this read's cursor BEFORE the worker thread starts so `interrupt()` can never
        # be a no-op; it interrupts this cursor only (#2523). The worker closes the cursor.
        db, cur = self._cursor()
        # Not `spawn(to_thread(...))`: cancelling that Task would cancel the executor future
        # while the thread still runs, and `_release` would drop the count early (see there).
        fut = thread_future(worker, cur, files, lo, hi, self._max_rows)
        fut.add_done_callback(lambda f: self._release(db, f))
        try:
            async with asyncio.timeout(self._timeout_s):
                return await asyncio.shield(fut)
        except TimeoutError as exc:
            # The worker may close its cursor just as the deadline fires; `interrupt()` on a
            # closed cursor raises ConnectionException, and the caller still gets the typed
            # timeout (503), never that raw error.
            with contextlib.suppress(duckdb.ConnectionException):
                cur.interrupt()
            raise ColdKlineReadTimeout(f"cold kline read exceeded {self._timeout_s}s") from exc
        finally:
            if not fut.done():  # timed out or cancelled: nobody awaits the worker's outcome
                fut.add_done_callback(_log_late_failure)


@dataclass(slots=True, eq=False)
class _SharedDuckDB:
    """The reader's one in-memory DuckDB instance; each read runs on its own `cursor()` (a
    connection to the same database, one per worker thread, as DuckDB documents)."""

    con: duckdb.DuckDBPyConnection
    users: int = 0  # reads holding a cursor (event loop thread only)
    retired: bool = False


def _log_late_failure(fut: asyncio.Future[Any]) -> None:
    """Debug trace of a worker that failed after its caller stopped waiting (timeout or
    cancel); `_release` consumes the exception. Type names only: no paths, no values."""
    exc = fut.exception()
    if exc is not None:
        # Resolved per call: a module-level logger pins a stale processor chain (#2008).
        structlog.get_logger(__name__).debug(
            "cold_kline_read_late_failure",
            error=type(exc).__name__,
            cause=type(exc.__cause__).__name__,  # "NoneType" when it has no cause
        )


def _stamps(files: list[Path]) -> dict[Path, tuple[int, int]]:
    out: dict[Path, tuple[int, int]] = {}
    for f in files:
        st = f.stat() if f.is_file() else None
        out[f] = (st.st_size, st.st_mtime_ns) if st else (-1, -1)
    return out


#: Price/size columns, in `ColdKlineRow` order; `_READ_SQL` lists the same names.
_NUM_COLS = ("open", "high", "low", "close", "volume", "turnover")
_TXT = "__cv_txt_"  # prefix of their text columns in the result
# union_by_name tolerates schema drift; optional columns default in Python. Dedup on ts happens
# before LIMIT so duplicate part-file rows never eat the cap. #2523: `ts` leaves DuckDB as int64
# epoch us (the WHERE still binds the stored TIMESTAMPTZ, so the predicate is pushed into the
# scan), never as tz-aware datetimes built in Python; each `_NUM_COLS` column also leaves it as
# text (`__cv_txt_<name>`, cast in the scan, off the GIL). `ts` is in that list so the set is
# never empty (a binder error); its text is unused.
_READ_SQL = (
    "SELECT * REPLACE (epoch_us(ts) AS ts), "
    "CAST(COLUMNS(c -> c IN ('ts', 'open', 'high', 'low', 'close', 'volume', 'turnover')) "
    "AS VARCHAR) AS '__cv_txt_\\0' "
    "FROM read_parquet($files, hive_partitioning = false, union_by_name = true) "
    "WHERE ts >= make_timestamptz($lo::BIGINT) AND ts < make_timestamptz($hi::BIGINT) "
    "QUALIFY row_number() OVER (PARTITION BY ts ORDER BY ts) = 1 "
    "ORDER BY ts DESC LIMIT $n"
)


def _column(table: pa.Table, name: str, default: object) -> list[Any]:
    """`name`'s values, or `default` per row when no file carries it (union_by_name)."""
    if name in table.column_names:
        values: list[Any] = table.column(name).to_pylist()
        return values
    return [default] * table.num_rows


def _num_column(table: pa.Table, name: str) -> list[str]:
    """`[_num(v) for v in column]` without the per-row Python call (#2523).

    For a DOUBLE column DuckDB's own text is Python's `repr` of every finite float (checked
    by a property test); exponent forms, inf and nan (`-nan` in DuckDB) hold "e" or "n" and,
    with nulls, are the only rows that still go through `_num`. Other types keep `_num`."""
    if name not in table.column_names:
        return ["0"] * table.num_rows
    raw = table.column(name)
    if not pa.types.is_float64(raw.type):
        return [_num(v) for v in raw.to_pylist()]
    txt = table.column(_TXT + name)
    out: list[str] = txt.to_pylist()
    odd = pc.or_kleene(
        pc.is_null(txt), pc.or_(pc.match_substring(txt, "e"), pc.match_substring(txt, "n"))
    )
    if pc.any(odd).as_py():
        for i in pc.indices_nonzero(odd).to_pylist():
            out[i] = _num(raw[i].as_py())
    return out


def _source_column(table: pa.Table) -> list[str]:
    """`str(source or "parquet")` per row, column-wise for a string column."""
    if "source" not in table.column_names:
        return ["parquet"] * table.num_rows
    src = table.column("source")
    if not pa.types.is_string(src.type):
        return [str(v or "parquet") for v in src.to_pylist()]
    blank = pc.or_kleene(pc.is_null(src), pc.equal(src, ""))
    filled: list[str] = pc.if_else(blank, "parquet", src).to_pylist()
    return filled


def _read_rows(
    cur: duckdb.DuckDBPyConnection,
    files: list[str],
    lo: int,
    hi: int,
    max_rows: int,
) -> list[ColdKlineRow]:
    try:
        cur.execute("SET TimeZone = 'UTC'")
        table = cur.execute(
            _READ_SQL, {"files": files, "lo": lo, "hi": hi, "n": max_rows}
        ).to_arrow_table()
    except duckdb.Error as exc:
        raise ColdKlineReadError(f"cold kline read failed: {type(exc).__name__}") from exc
    finally:
        cur.close()  # N4: the worker closes its own cursor; the shared instance stays open
    # Column-wise (#2523): one pass per column, rows built by `map`, no per-row Python body.
    out = list(
        map(
            ColdKlineRow,
            table.column("ts").to_pylist(),
            *(_num_column(table, name) for name in _NUM_COLS),
            map(bool, _column(table, "confirmed", True)),
            _source_column(table),
        )
    )
    out.sort(key=attrgetter("ts_us"))  # one descending run: linear
    return out


# #2523 lever 4: DuckDB emits each bar's JSON text, so a cold page never becomes Python objects.
#
# `body` is one bar's `serialize_bar` JSON without its closing brace (`ColdKlinePage.bars_json`
# appends the `include_delta` nulls and `}` while joining). `t` is `datetime.isoformat()`'s
# form: `.ffffff` only when the microseconds are non-zero, then `+00:00`. Each number is
# DuckDB's DOUBLE text, Python's `repr` of the float (lever 3's property test); a row whose
# text holds an exponent, inf or nan ("e" / "n"), or a NULL, is `odd`, and only its body is
# rebuilt through `_num` in Python. `typed` is false when any emitted column is not the type
# the text form assumes; the whole page then takes the lever-3 row path. The window, dedup,
# LIMIT and pushdown are `_READ_SQL`'s.
# One literal, assembled by the interpreter and never at run time: every runtime value is a
# bound `$` parameter. `bool(None)` is False and a blank source reads "parquet", as `_read_rows`
# builds them; `confirm` is `coalesce(TRY_CAST(confirmed AS BOOLEAN), false)` in both places.
_PAGE_SQL = (
    "WITH r AS (SELECT epoch_us(ts) AS t_us, confirmed, source, open, high, low, close, "
    "volume, turnover, CAST(open AS VARCHAR) AS o_t, CAST(high AS VARCHAR) AS h_t, "
    "CAST(low AS VARCHAR) AS l_t, CAST(close AS VARCHAR) AS c_t, CAST(volume AS VARCHAR) "
    "AS v_t, CAST(turnover AS VARCHAR) AS tv_t, typeof(open) = 'DOUBLE' AND typeof(high) = "
    "'DOUBLE' AND typeof(low) = 'DOUBLE' AND typeof(close) = 'DOUBLE' AND typeof(volume) = "
    "'DOUBLE' AND typeof(turnover) = 'DOUBLE' AND typeof(confirmed) = 'BOOLEAN' AND "
    "typeof(source) = 'VARCHAR' AS typed FROM read_parquet($files, hive_partitioning = "
    "false, union_by_name = true) WHERE ts >= make_timestamptz($lo::BIGINT) AND ts < "
    "make_timestamptz($hi::BIGINT) QUALIFY row_number() OVER (PARTITION BY ts ORDER BY ts) "
    "= 1 ORDER BY ts DESC LIMIT $n) SELECT t_us AS ts, coalesce(TRY_CAST(confirmed AS "
    "BOOLEAN), false) AS confirmed, CASE WHEN source IS NULL OR CAST(source AS VARCHAR) = "
    "'' THEN 'parquet' ELSE CAST(source AS VARCHAR) END AS source, open, high, low, close, "
    "volume, turnover, typed, o_t AS __cv_txt_open, h_t AS __cv_txt_high, l_t AS "
    "__cv_txt_low, c_t AS __cv_txt_close, v_t AS __cv_txt_volume, tv_t AS "
    "__cv_txt_turnover, '{\"t\":\"' || strftime(make_timestamp(t_us), '%Y-%m-%dT%H:%M:%S') || "
    "CASE WHEN t_us % 1000000 = 0 THEN '' ELSE '.' || lpad(CAST(((t_us % 1000000) + "
    '1000000) % 1000000 AS VARCHAR), 6, \'0\') END || \'+00:00","o":"\' || o_t || \'","h":"\' || '
    'h_t || \'","l":"\' || l_t || \'","c":"\' || c_t || \'","v":"\' || v_t || \'","turnover":"\' '
    '|| tv_t || \'","confirm":\' || CASE WHEN coalesce(TRY_CAST(confirmed AS BOOLEAN), '
    "false) THEN 'true' ELSE 'false' END AS body, (o_t || h_t || l_t || c_t || v_t || "
    "tv_t) IS NULL OR regexp_matches(o_t || h_t || l_t || c_t || v_t || tv_t, '[en]') AS "
    "odd FROM r ORDER BY t_us"
)
_BAR_KEYS = ("o", "h", "l", "c", "v", "turnover")  # `serialize_bar`'s keys for `_NUM_COLS`


def _odd_body(table: pa.Table, i: int) -> str:
    """Row `i`'s body with each number through `_num` (exponent, inf, nan or NULL text)."""
    ts_us: int = table.column("ts")[i].as_py()
    stamp = datetime.fromtimestamp(ts_us / 1_000_000, tz=UTC).isoformat()  # `iso_us`
    nums = (_num(table.column(name)[i].as_py()) for name in _NUM_COLS)
    fields = "".join(f',"{k}":"{v}"' for k, v in zip(_BAR_KEYS, nums, strict=True))
    confirm = "true" if table.column("confirmed")[i].as_py() else "false"
    return f'{{"t":"{stamp}"{fields},"confirm":{confirm}'


@dataclass(frozen=True, slots=True)
class ColdKlinePage:
    """A cold window held as Arrow columns, ascending by `ts` (#2523 lever 4): `ts` (int64
    µs), `confirmed`, `source` (blank -> "parquet"), `body` (each bar's JSON, no closing
    brace), plus the raw and text price columns `rows()` needs. `ingestion.kline_read`'s
    `KlinePageLike`; every operation is an Arrow kernel, never a per-row Python body."""

    table: pa.Table

    def __len__(self) -> int:
        return int(self.table.num_rows)

    def last_ts_us(self) -> int:
        """`ts` of the newest bar; the page must not be empty."""
        value: int = self.table.column("ts")[-1].as_py()
        return value

    def confirmed_only(self) -> ColdKlinePage:
        return ColdKlinePage(self.table.filter(self.table.column("confirmed")))

    def head(self, n: int) -> ColdKlinePage:
        return ColdKlinePage(self.table.slice(0, max(0, n)))

    def tail(self, n: int) -> ColdKlinePage:
        n = max(0, min(n, len(self)))
        return ColdKlinePage(self.table.slice(len(self) - n, n))

    def without_ts(self, ts: set[int]) -> ColdKlinePage:
        hit = pc.is_in(self.table.column("ts"), value_set=pa.array(sorted(ts), pa.int64()))
        return ColdKlinePage(self.table.filter(pc.invert(hit)))

    def has_source(self, sources: frozenset[str]) -> bool:
        hit = pc.is_in(self.table.column("source"), value_set=pa.array(sorted(sources)))
        return bool(pc.any(hit).as_py())

    def bars_json(self, suffix: bytes) -> bytes:
        """The bars as `{...}` objects joined by `,`, no brackets; `suffix` and `}` close each
        one. One Arrow join over the `body` buffer: no per-bar Python string or dict."""
        if not len(self):
            return b""
        body = self.table.column("body").combine_chunks()
        one_list = pa.ListArray.from_arrays(pa.array([0, len(body)], pa.int32()), body)
        joined = pc.binary_join(one_list, suffix.decode() + "},")[0].as_buffer()
        if joined is None:  # a body is never NULL (`_read_page` rebuilt every odd one)
            raise ColdKlineReadError("cold kline page holds a NULL bar")
        out: bytes = joined.to_pybytes()
        return out + suffix + b"}"

    def rows(self) -> list[ColdKlineRow]:
        """The lever-3 rows, equal field by field (the interleaving-tape fallback)."""
        t = self.table
        return list(
            map(
                ColdKlineRow,
                t.column("ts").to_pylist(),
                *(_num_column(t, name) for name in _NUM_COLS),
                t.column("confirmed").to_pylist(),
                t.column("source").to_pylist(),
            )
        )


def _read_page(
    cur: duckdb.DuckDBPyConnection, files: list[str], lo: int, hi: int, max_rows: int
) -> ColdKlinePage | list[ColdKlineRow]:
    """`_read_rows`' window as a `ColdKlinePage`, or `_read_rows` itself when the files cannot
    be emitted as JSON text: a column no file carries (a binder error) or a non-DOUBLE price,
    non-BOOLEAN `confirmed` or non-VARCHAR `source` column. The cursor is closed on every
    path, whatever raises (N4); `_read_rows` closes it too, and a second close is a no-op."""
    try:
        try:
            cur.execute("SET TimeZone = 'UTC'")
            table = cur.execute(
                _PAGE_SQL, {"files": files, "lo": lo, "hi": hi, "n": max_rows}
            ).to_arrow_table()
        except duckdb.BinderException:
            return _read_rows(cur, files, lo, hi, max_rows)
        except duckdb.Error as exc:
            raise ColdKlineReadError(f"cold kline read failed: {type(exc).__name__}") from exc
        if table.num_rows and not pc.all(table.column("typed")).as_py():
            return _read_rows(cur, files, lo, hi, max_rows)
    finally:
        cur.close()
    odd = pc.fill_null(table.column("odd"), False).combine_chunks()
    if pc.any(odd).as_py():
        idx = pc.indices_nonzero(odd).to_pylist()
        fixed = pa.array([_odd_body(table, i) for i in idx], pa.string())
        body = pc.replace_with_mask(table.column("body").combine_chunks(), odd, fixed)
        table = table.set_column(table.schema.get_field_index("body"), "body", body)
    return ColdKlinePage(table)


__all__ = [
    "ColdKlinePage",
    "ColdKlineReadError",
    "ColdKlineReadTimeout",
    "ColdKlineRow",
    "ParquetKlineReader",
    "months_between",
]
