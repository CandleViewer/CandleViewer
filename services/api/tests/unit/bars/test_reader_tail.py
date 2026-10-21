"""E12-T06 slice B (#2195): the `bars_*` tail read that hydrates the WS snapshot store."""

from __future__ import annotations

import asyncio
import itertools
import time
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal

import pytest
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.bars.kline_rows import KLINE_SOURCE, ORDERFLOW_NULL_COLUMNS
from candleviewer.bars.limits import (
    MAX_NON_TIME_WINDOW_US,
    MAX_TAIL,
    MAX_TAIL_SCAN_ROWS,
    MAX_TIME_WINDOW_US,
)
from candleviewer.bars.models import Bar, BarSpec
from candleviewer.bars.reader import (
    BarReader,
    BarTail,
    build_tail_bound_query,
    build_tail_query,
    build_tail_scan_bound_query,
    row_key,
    tail_window_us,
)
from candleviewer.bars.rows import (
    BUILD_VERSIONS,
    MAX_GENERATION,
    bar_param_for,
    bar_row,
    row_checksum,
)
from candleviewer.bars.series_store import SeriesStore
from candleviewer.domain.sql_names import ts_param, ts_us_from_row
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.ws.topics import FAMILIES

SPEC = BarSpec(kind="time", interval_ms=60_000)
SYM, T0, MIN = "BTCUSDT", 1_700_000_040_000_000, 60_000_000
NOW = T0 + 10_000 * MIN
#: A non-time spec, whose read is bounded first (D2-M2, #3688), and its window start.
RSPEC, RSINCE = BarSpec(kind="renko", range_ticks=2), NOW - MAX_NON_TIME_WINDOW_US
#: A valid spec of each non-time kind (tick, range and renko at their SR-E12-03 floors). A kind
#: added to `BUILD_VERSIONS` without one fails the tests over `NON_TIME`, never skips.
FLOORS = {
    "tick": BarSpec(kind="tick", tick_count=100),
    "volume": BarSpec(kind="volume", volume_threshold=Decimal(10)),
    "range": BarSpec(kind="range", range_ticks=2),
    "renko": RSPEC,
    "delta": BarSpec(kind="delta", delta_threshold=Decimal(10)),
}
NON_TIME = pytest.mark.parametrize("kind", [k for k in BUILD_VERSIONS if k != "time"])
#: Both tail statements' builders: the refusals are one set.
BUILDERS = pytest.mark.parametrize("build", [build_tail_query, build_tail_bound_query])
Build = Callable[..., tuple[str, tuple[object, ...]]]


def _bar(i: int, *, closed: bool = True, shift: int = 0) -> Bar:
    """Bar `i`, opening `shift` minutes later than bar `i` of the first run (a restarted run)."""
    t = T0 + (i + shift) * MIN
    return Bar.model_validate(
        dict(
            spec_hash=SPEC.spec_hash, symbol=SYM, index=i, open_time=t, close_time=t + MIN - 1,
            open=Decimal("100.5"), high=Decimal("101"), low=Decimal("100"),
            close=Decimal("100.25"), volume=Decimal("2"), buy_volume=Decimal("1.5"),
            sell_volume=Decimal("0.5"), delta=Decimal("1"), min_delta=Decimal("-0.25"),
            max_delta=Decimal("1.25"), trade_count=500, turnover=Decimal("201"),
            vwap=Decimal("100.5"), closed=closed, partial=False, gap_before=False,
        )
    )  # fmt: skip


def _row(
    i: int,
    change: Mapping[str, object] | None = None,
    *,
    gen: int = 0,
    closed: bool = True,
    shift: int = 0,
) -> dict[str, object]:
    """The stored row of bar `i` with `change` applied and a checksum that verifies."""
    row = bar_row(_bar(i, closed=closed, shift=shift), SPEC, generation=gen)
    row.update(change or {})
    row["row_checksum"] = row_checksum(row)
    return row


def _brick(i: int, at: int, spec: BarSpec = RSPEC, *, closed: bool = True) -> dict[str, object]:
    """The stored row of non-time bar `i` of `spec` (generation 1), opening `at` minutes after
    `T0`."""
    bar = _bar(i, closed=closed, shift=at - i).model_copy(update={"spec_hash": spec.spec_hash})
    return bar_row(bar, spec, generation=1)


def _kline_row(i: int) -> dict[str, object]:
    """A kline-sourced `bars_time` row (`kline_rows.kline_row` shape): no index, no order flow."""
    return _row(i, {"source": KLINE_SOURCE, "index": None, **dict.fromkeys(ORDERFLOW_NULL_COLUMNS)})


def _stamps(*ts: int) -> list[dict[str, object]]:
    """The rows a `SELECT ts` statement returns, newest first as given."""
    return [{"ts": ts_param(t)} for t in ts]


def _is_scan_bound(sql: str) -> bool:
    """The table-row bound's statement (D2-M4): `ts` of the table, no series named."""
    return sql.startswith("SELECT ts FROM bars_") and " symbol = " not in sql


class _Conn:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        self.calls.append((sql, params))
        return [] if _is_scan_bound(sql) else self.rows  # a table of fewer than K rows


class _Steps(_Conn):
    """Answers its k-th statement with `answers[k]`, and records each."""

    def __init__(self, *answers: list[dict[str, object]]) -> None:
        super().__init__([])
        self.answers = answers

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        self.calls.append((sql, params))
        return self.answers[len(self.calls) - 1]


class _Fails(_Steps):
    """`_Steps` whose `at`-th statement (1-based) raises `error` instead of answering."""

    def __init__(self, error: Exception, at: int, *answers: list[dict[str, object]]) -> None:
        super().__init__(*answers)
        self.error, self.at = error, at

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        if len(self.calls) + 1 == self.at:
            self.calls.append((sql, params))
            raise self.error
        return await super().fetch(sql, *params)


def _select(
    rows: list[dict[str, object]], sql: str, binds: tuple[object, ...]
) -> list[dict[str, object]]:
    """A tail statement over `rows` as QuestDB answers it: the series' keyed rows from its `ts`
    bind on, newest first by the key it orders by (`ts`, or `ts, generation, index`), at most its
    `LIMIT`; a bound's statement returns the `ts` column only (the table-row bound's, of every
    row)."""
    if _is_scan_bound(sql):  # the k-th newest `ts` of the whole table from its bind on
        lo, hi = (int(n) for n in sql.rsplit(" LIMIT ", 1)[1].split(", "))
        stamps = (ts_us_from_row(r["ts"]) for r in rows)
        ts = sorted((t for t in stamps if t >= ts_us_from_row(binds[0])), reverse=True)
        return [{"ts": ts_param(t)} for t in ts[lo:hi]]
    symbol, param, since = binds
    start = ts_us_from_row(since)
    hits = [r for r in rows if (r["symbol"], r["bar_param"]) == (symbol, param)]
    hits = [r for r in hits if r["index"] is not None and ts_us_from_row(r["ts"]) >= start]
    hits.sort(
        key=lambda r: row_key(r) if " generation DESC" in sql else row_key(r)[:1], reverse=True
    )
    out = hits[: int(sql.rsplit(" LIMIT ", 1)[1])]
    return [{"ts": r["ts"]} for r in out] if sql.startswith("SELECT ts ") else out


class _Table(_Conn):
    """A table of stored `rows`: each statement is answered by `_select`, and `landing` is written
    right after the `after`-th one, as a bar's row lands between two statements of a read. `scans`
    is the rows each statement visits: its bound's `k` rows, else those from its `ts` bind on."""

    def __init__(
        self,
        rows: list[dict[str, object]],
        landing: dict[str, object] | None = None,
        after: int = 2,
    ) -> None:
        super().__init__(rows)
        self.landing, self.after = landing, after
        self.answers, self.scans = list[list[dict[str, object]]](), list[int]()

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        self.calls.append((sql, params))
        start = ts_us_from_row(params[-1])  # every statement's `ts` bind is its last
        seen = sum(ts_us_from_row(r["ts"]) >= start for r in self.rows)
        hi = int(sql.rsplit(" LIMIT ", 1)[1].split(", ")[-1]) if _is_scan_bound(sql) else seen
        self.scans.append(min(seen, hi))
        self.answers.append(_select(self.rows, sql, params))
        if self.landing is not None and len(self.calls) == self.after:
            self.rows.append(self.landing)
        return self.answers[-1]


async def _sched(*_: object) -> None:
    return None


async def _read(rows: list[dict[str, object]], limit: int = MAX_TAIL) -> BarTail:
    """`read_tail` over `rows`, given newest first as the query returns them."""
    return await BarReader(_Conn(rows), _sched, now_us=lambda: NOW).read_tail(SYM, SPEC, limit)


def _indexes(tail: BarTail) -> list[int]:
    return [b.index for _, b in tail.bars]


def test_tail_query_is_newest_first_by_the_full_bar_key_inside_a_ts_window() -> None:
    sql, params = build_tail_query("time", SYM, "1m", MAX_TAIL, T0, now_us=T0)
    assert sql.startswith("SELECT * FROM bars_time WHERE symbol = $1 AND bar_param = $2 ")
    assert 'AND ts >= $3 AND "index" IS NOT NULL ' in sql  # the window; kline rows have no key
    assert sql.endswith('ORDER BY ts DESC, generation DESC, "index" DESC LIMIT 1000')
    assert params == (SYM, "1m", ts_param(T0))


@pytest.mark.parametrize("limit", [1, MAX_TAIL])
def test_tail_query_takes_a_limit_from_one_to_max_tail(limit: int) -> None:
    sql, _ = build_tail_query("tick", SYM, "tick:500", limit, T0, now_us=T0)
    assert sql.endswith(f" LIMIT {limit}")


def test_the_tail_cap_is_the_ws_history_maximum() -> None:
    """The wire range is 0..1000 (`23-ws-protocol.md` §6.1, §13), and
    SR-E12-07 caps it at 1000: the one read never exceeds what a snapshot may ask for."""
    assert FAMILIES["bars"].options["history"].hi == MAX_TAIL == 1_000


@BUILDERS
@pytest.mark.parametrize(
    ("kind", "limit", "match"),
    [("tick", 0, "limit"), ("tick", MAX_TAIL + 1, "limit"), ("ohlc", 1, "kind")],
)
def test_tail_query_refuses_an_unbounded_limit_or_an_unknown_kind(
    build: Build, kind: str, limit: int, match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        build(kind, SYM, "tick:500", limit, T0, now_us=T0)


@BUILDERS
@pytest.mark.parametrize(
    ("kind", "cap"), [("time", MAX_TIME_WINDOW_US), ("tick", MAX_NON_TIME_WINDOW_US)]
)
def test_tail_query_refuses_a_window_beyond_the_sr_e12_02_cap(
    build: Build, kind: str, cap: int
) -> None:
    """The cap holds where the SQL is built, not only where `tail_window_us` sizes the window."""
    build(kind, SYM, "x", 1, NOW - cap, now_us=NOW)  # exactly the cap: accepted
    with pytest.raises(ValueError, match="SR-E12-02"):
        build(kind, SYM, "x", 1, NOW - cap - 1, now_us=NOW)


def test_the_table_row_bound_takes_the_kth_newest_ts_of_the_whole_table_from_the_window() -> None:
    """D2-M4 (#2787): `ts` only and no series named, so it counts the kind's table rows, the rows
    every later statement filters; QuestDB's `LIMIT m, n` is rows m+1..n, so `k-1, k` is the k-th
    newest, which 8.1.1 plans as `Limit lo hi` over a backward scan that stops there. The default is
    `MAX_TAIL_SCAN_ROWS`, 500 000 (`bars/limits.py`: a change is a reviewed diff)."""
    sql, params = build_tail_scan_bound_query("renko", T0, now_us=T0, rows=500_000)
    assert sql == "SELECT ts FROM bars_renko WHERE ts >= $1 ORDER BY ts DESC LIMIT 499999, 500000"
    assert params == (ts_param(T0),)
    assert build_tail_scan_bound_query("tick", T0, now_us=T0, rows=1)[0].endswith("LIMIT 0, 1")
    default, _ = build_tail_scan_bound_query("tick", T0, now_us=T0)
    assert default.endswith("LIMIT 499999, 500000")


@pytest.mark.parametrize(("kind", "rows", "match"), [("ohlc", 5, "kind"), ("tick", 0, "rows")])
def test_the_table_row_bound_refuses_an_unknown_kind_and_no_rows(
    kind: str, rows: int, match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        build_tail_scan_bound_query(kind, T0, now_us=T0, rows=rows)


def test_the_table_row_bound_reads_the_time_table_too() -> None:
    """#399 R1: a time read's window reaches 400 d for its longer intervals, and `symbol` has no
    index, so it takes the same bound over `bars_time`, within the time cap."""
    sql, params = build_tail_scan_bound_query("time", T0, now_us=T0)
    assert sql == "SELECT ts FROM bars_time WHERE ts >= $1 ORDER BY ts DESC LIMIT 499999, 500000"
    assert params == (ts_param(T0),)
    build_tail_scan_bound_query("time", NOW - MAX_TIME_WINDOW_US, now_us=NOW)  # at the cap
    with pytest.raises(ValueError, match="window cap"):
        build_tail_scan_bound_query("time", NOW - MAX_TIME_WINDOW_US - 1, now_us=NOW)


def test_the_table_row_bound_refuses_a_window_beyond_the_sr_e12_02_cap() -> None:
    build_tail_scan_bound_query("tick", NOW - MAX_NON_TIME_WINDOW_US, now_us=NOW)  # at the cap
    with pytest.raises(ValueError, match="SR-E12-02"):
        build_tail_scan_bound_query("tick", NOW - MAX_NON_TIME_WINDOW_US - 1, now_us=NOW)


async def test_the_table_row_bound_cannot_be_raised_past_its_pin() -> None:
    """D2-M4: a larger `rows`, the reader's `tail_scan_rows` included, is read as
    `MAX_TAIL_SCAN_ROWS`, so no caller turns the bound into a no-op."""
    pinned = build_tail_scan_bound_query("tick", T0, now_us=T0)
    for rows in (MAX_TAIL_SCAN_ROWS + 1, 10**12):
        assert build_tail_scan_bound_query("tick", T0, now_us=T0, rows=rows) == pinned
    conn = _Conn([])
    reader = BarReader(conn, _sched, now_us=lambda: NOW, tail_scan_rows=10**12)
    await reader.read_tail(SYM, RSPEC, 3)
    assert conn.calls[0] == build_tail_scan_bound_query("renko", RSINCE, now_us=NOW)


def test_the_bound_query_takes_the_newest_ts_on_one_key_with_the_tail_query_s_where() -> None:
    """D2-M2 (#3688): `ts` alone, ordered by the designated timestamp only (QuestDB 8.1.1 scans
    backward and stops at the limit), with the WHERE and binds of the read it bounds."""
    where = ' WHERE symbol = $1 AND bar_param = $2 AND ts >= $3 AND "index" IS NOT NULL ORDER BY '
    sql, params = build_tail_bound_query("renko", SYM, "renko:2", MAX_TAIL, T0, now_us=T0)
    tail_sql, tail_params = build_tail_query("renko", SYM, "renko:2", MAX_TAIL, T0, now_us=T0)
    assert sql.split(where) == ["SELECT ts FROM bars_renko", "ts DESC LIMIT 1000"]
    assert tail_sql.split(where)[0] == "SELECT * FROM bars_renko"  # the same WHERE
    assert params == tail_params == (SYM, "renko:2", ts_param(T0))


@pytest.mark.parametrize(
    ("spec", "window"),
    [
        (SPEC, 2_000 * MIN),  # twice the span of the 1 000 bars asked for
        (BarSpec(kind="time", interval_ms=86_400_000), MAX_TIME_WINDOW_US),  # 2 000 d: capped
        (BarSpec(kind="tick", tick_count=500), MAX_NON_TIME_WINDOW_US),  # no fixed span
    ],
    ids=["1m", "1d-capped", "tick"],
)
def test_tail_window_is_twice_the_bars_span_within_the_sr_e12_02_caps(
    spec: BarSpec, window: int
) -> None:
    assert tail_window_us(spec, MAX_TAIL) == window


@pytest.mark.parametrize(
    ("interval_ms", "bars"),
    [(43_200_000, 800), (86_400_000, 400), (604_800_000, 57)],
    ids=["12h", "1d", "1w"],
)
def test_the_capped_time_window_holds_the_bar_counts_the_docs_quote(
    interval_ms: int, bars: int
) -> None:
    """`limits.py` and `21-database-schema.md` §9.5 quote these as the most a WS `bars` snapshot
    holds; amending the cap fails here, so the quoted numbers cannot go stale unnoticed."""
    spec = BarSpec(kind="time", interval_ms=interval_ms)
    assert tail_window_us(spec, MAX_TAIL) // (interval_ms * 1_000) == bars


async def test_read_tail_binds_its_window_back_from_the_injected_clock() -> None:
    conn = _Conn([])
    tail = await BarReader(conn, _sched, now_us=lambda: NOW).read_tail(SYM, SPEC, 4)
    bound, (sql, params) = conn.calls
    assert bound == build_tail_scan_bound_query("time", NOW - 8 * MIN, now_us=NOW)
    assert sql.endswith(" LIMIT 4") and params == (SYM, "1m", ts_param(NOW - 8 * MIN))
    assert tail == BarTail([], since_us=NOW - 8 * MIN)  # a series with no tape yet: fetched 0


@pytest.mark.parametrize(
    "spec",
    [BarSpec(kind="tick", tick_count=500), BarSpec(kind="time", interval_ms=86_400_000)],
    ids=["tick", "1d"],
)
async def test_read_tail_reads_the_clock_once_so_a_window_at_its_cap_is_never_refused(
    spec: BarSpec,
) -> None:
    """These windows equal the SR-E12-02 cap, which `build_tail_query` checks against the
    caller's `now_us`: that holds only while the window and the check share one reading. A clock
    that moves 1 us a read would otherwise turn every such read into a refusal."""
    clock = itertools.count(NOW)
    conn = _Conn([_row(0)])  # a row, so the read runs its second statement too
    tail = await BarReader(conn, _sched, now_us=lambda: next(clock)).read_tail(SYM, spec, MAX_TAIL)
    assert tail.since_us == NOW - tail_window_us(spec, MAX_TAIL)  # the first reading
    assert next(clock) == NOW + 1  # and the only one


async def test_read_tail_measures_back_from_the_wall_clock_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(time, "time_ns", lambda: NOW * 1_000 + 999)
    conn = _Conn([])
    await BarReader(conn, _sched).read_tail(SYM, SPEC, 4)
    assert conn.calls[-1][1][2] == ts_param(NOW - 8 * MIN)


K5 = T0 + 5 * MIN  # a table-row bound inside the window


@NON_TIME
@pytest.mark.parametrize(
    ("kth", "newest", "scan", "start"),
    [
        ([], [], RSINCE, None),
        ([], [T0 + 9 * MIN, T0 + 8 * MIN], RSINCE, RSINCE),
        ([], [T0 + 9 * MIN, T0 + 8 * MIN, T0 + 7 * MIN], RSINCE, T0 + 7 * MIN),
        ([], [T0 + 9 * MIN, T0 + 7 * MIN, T0 + 7 * MIN], RSINCE, T0 + 7 * MIN),
        ([], [T0 + 9 * MIN, T0 + 8 * MIN, RSINCE - MIN], RSINCE, RSINCE),
        ([K5], [], K5, None),
        ([K5], [T0 + 9 * MIN, T0 + 8 * MIN], K5, K5),
        ([K5], [T0 + 9 * MIN, T0 + 8 * MIN, T0 + 7 * MIN], K5, T0 + 7 * MIN),
        ([RSINCE], [T0 + 9 * MIN], RSINCE, RSINCE),
        ([RSINCE - MIN], [T0 + 9 * MIN], RSINCE, RSINCE),
    ],
    ids=["table-below-k-empty", "table-below-k-fewer", "table-below-k-the-limit",
         "table-below-k-tied-at-the-bound", "table-below-k-below-the-window", "bounded-empty",
         "bounded-fewer-than-the-limit", "bounded-the-limit", "bound-at-the-window-start",
         "bound-below-the-window"],
)  # fmt: skip
async def test_a_non_time_read_starts_at_the_later_of_its_window_start_and_its_table_bound(
    kind: str, kth: list[int], newest: list[int], scan: int, start: int | None
) -> None:
    """D2-M4, then D2-M2 from there: the table's k-th newest `ts` first; the series' nth-newest
    `ts` from the later of it and the window start (a bound at or below the window start moves
    nothing); the tail from the oldest `ts` it returned when it returned the limit, else from
    where it started. Nothing from there on ends the read: the empty tail, no second scan.
    `since_us` is where the read started, and `bounded` says the table bound moved it."""
    spec, param = FLOORS[kind], bar_param_for(FLOORS[kind])
    conn = _Steps(_stamps(*kth), _stamps(*newest), [])
    tail = await BarReader(conn, _sched, now_us=lambda: NOW).read_tail(SYM, spec, 3)
    second = [] if start is None else [build_tail_query(kind, SYM, param, 3, start, now_us=NOW)]
    assert conn.calls == [
        build_tail_scan_bound_query(kind, RSINCE, now_us=NOW),
        build_tail_bound_query(kind, SYM, param, 3, scan, now_us=NOW),
        *second,
    ]
    assert tail == BarTail([], since_us=scan, bounded=scan > RSINCE)


@NON_TIME
async def test_a_non_time_read_folds_its_second_statement_s_rows_as_the_one_statement_did(
    kind: str,
) -> None:
    """The bound only moves where the tail starts: those rows are dropped, skipped and counted
    as before, and the bound's own `ts` rows are never folded."""
    spec = FLOORS[kind]
    tampered = _brick(2, 7, spec)
    tampered["close"] = 99.0  # edited after its checksum: dropped
    rows = [_brick(3, 7, spec), tampered, _brick(1, 6, spec, closed=False), _brick(0, 5, spec)]
    conn = _Steps([], [{"ts": ts_param(T0 + m * MIN)} for m in (7, 7, 6, 5)], rows)
    tail = await BarReader(conn, _sched, now_us=lambda: NOW).read_tail(SYM, spec, 4)
    assert conn.calls[2][1][2] == ts_param(T0 + 5 * MIN)
    assert [(gen, b.index, b.open_time) for gen, b in tail.bars] == [
        (1, 0, T0 + 5 * MIN), (1, 3, T0 + 7 * MIN)
    ]  # fmt: skip
    assert (tail.dropped, tail.skipped, tail.fetched, tail.since_us) == (1, 1, 4, RSINCE)


@pytest.mark.parametrize(
    ("held", "landed", "indexes"),
    [(range(1, 11), 11, [9, 10, 11]), ([5, 6], 4, [4, 5, 6])],
    ids=["above-the-bound", "below-the-oldest-of-fewer-than-the-limit"],
)
async def test_a_row_written_between_the_two_statements_is_read_as_the_one_statement_would(
    held: Sequence[int], landed: int, indexes: list[int]
) -> None:
    """The tail statement runs after a row lands: it reads that row when it lies at or above the
    bound and, with fewer than the limit returned (no bound), wherever it lies in the window. Its
    rows are those of the one statement over the table as it then is."""
    conn = _Table([_brick(m, m) for m in held], _brick(landed, landed))
    tail = await BarReader(conn, _sched, now_us=lambda: NOW).read_tail(SYM, RSPEC, 3)
    one = _select(conn.rows, *build_tail_query("renko", SYM, "renko:2", 3, RSINCE, now_us=NOW))
    assert conn.answers[2] == one
    assert [b.index for _, b in tail.bars] == indexes


def _busy_table() -> list[dict[str, object]]:
    """`renko:2` rows at minutes 10..19, and a sparse `renko:3` at 4 and 13 (tied with one)."""
    sparse = BarSpec(kind="renko", range_ticks=3)
    busy = [_brick(m - 10, m) for m in range(10, 20)]
    return [*busy, _brick(0, 4, sparse), _brick(1, 13, sparse)]


async def _read_k(
    rows: list[dict[str, object]], spec: BarSpec, k: int, limit: int = 3
) -> tuple[BarTail, _Table]:
    table = _Table(rows)
    reader = BarReader(table, _sched, now_us=lambda: NOW, tail_scan_rows=k)
    return await reader.read_tail(SYM, spec, limit), table


async def test_a_sparse_series_gets_only_its_rows_among_the_newest_k_and_a_dense_one_all() -> None:
    """D2-M4: k = 7 of the 12 rows: the 7th newest is minute 13, which the sparse series' second
    row shares with a busy one, so the bound `>=` keeps both (a tie is read). Its first row
    (minute 4) is below the bound and is not returned; the busy series' newest 3 all lie above
    it, as without a bound. No statement visits more than k rows and the rows tied with the last."""
    sparse = BarSpec(kind="renko", range_ticks=3)
    tail, table = await _read_k(_busy_table(), sparse, k=7)
    assert ([b.index for _, b in tail.bars], tail.fetched) == ([1], 1)
    assert (tail.since_us, tail.bounded) == (T0 + 13 * MIN, True)
    assert table.scans == [7, 8, 8]  # the bound's k rows, then the 8 at or after minute 13, twice
    dense, _ = await _read_k(_busy_table(), RSPEC, k=7)
    whole, _ = await _read_k(_busy_table(), RSPEC, k=MAX_TAIL_SCAN_ROWS)
    assert [b.index for _, b in dense.bars] == [b.index for _, b in whole.bars] == [7, 8, 9]
    assert (whole.since_us, whole.bounded) == (RSINCE, False)  # 12 rows: fewer than k


async def test_a_series_with_no_row_from_the_bound_on_reads_empty_after_two_statements() -> None:
    """Its rows are all below the bound: nothing is returned, `bounded` says rows may lie below
    `since_us`, and there is no tail statement (two statements, not three)."""
    sparse = BarSpec(kind="renko", range_ticks=3)
    rows = [row for row in _busy_table() if row["bar_param"] != "renko:3" or row["index"] == 0]
    tail, table = await _read_k(rows, sparse, k=5)
    assert (tail.bars, tail.fetched, tail.since_us, tail.bounded) == ([], 0, T0 + 15 * MIN, True)
    assert len(table.calls) == 2


@pytest.mark.parametrize(
    ("landed", "at", "indexes"), [(10, 20, [8, 9, 10]), (2, 12, [8, 9])],
    ids=["above-the-bound", "below-the-bound"],
)  # fmt: skip
async def test_a_row_written_after_the_table_bound_is_read_only_at_or_above_it(
    landed: int, at: int, indexes: list[int]
) -> None:
    """D2-M4: the bound is taken once, at the first statement (k = 2 of 3 rows: minute 18). A row
    that lands after it and lies at or above it is read; one below it is not, though it lies in the
    window (it reaches the store live, as for the one-statement read)."""
    rows = [_brick(m - 10, m) for m in (10, 18, 19)]
    table = _Table(rows, _brick(landed, at), after=1)
    reader = BarReader(table, _sched, now_us=lambda: NOW, tail_scan_rows=2)
    tail = await reader.read_tail(SYM, RSPEC, 3)
    assert ([b.index for _, b in tail.bars], tail.since_us) == (indexes, T0 + 18 * MIN)


def _bounded_reads(kind: str | None = None) -> float:
    """`bars_tail_scan_bounded_total`, for one kind or summed over them all (#399 OD2)."""
    kinds = [kind] if kind is not None else list(BUILD_VERSIONS)
    return sum(
        float(REGISTRY.get_sample_value("bars_tail_scan_bounded_total", {"kind": k}) or 0.0)
        for k in kinds
    )


async def test_the_bound_counts_the_reads_it_started_later_than_their_window_only() -> None:
    before, renko, time_reads = _bounded_reads(), _bounded_reads("renko"), _bounded_reads("time")
    await _read_k(_busy_table(), RSPEC, k=7)  # moved, a tail read: counted
    sparse = BarSpec(kind="renko", range_ticks=3)
    await _read_k(_busy_table(), sparse, k=5)  # moved past all its rows, an empty read: counted
    await _read_k(_busy_table(), RSPEC, k=MAX_TAIL_SCAN_ROWS)  # 12 rows, fewer than k: not
    at_start = BarReader(_Steps(_stamps(RSINCE), []), _sched, now_us=lambda: NOW)
    await at_start.read_tail(SYM, RSPEC, 3)  # the bound is the window start: moved nothing, not
    time_reader = BarReader(_Conn([_row(0)]), _sched, now_us=lambda: NOW)
    await time_reader.read_tail(SYM, SPEC, 2)  # a time read on a table below k: not
    assert _bounded_reads() == before + 2
    assert (_bounded_reads("renko"), _bounded_reads("time")) == (renko + 2, time_reads)


@pytest.mark.parametrize(("k", "logged"), [(7, 7), (10**12, MAX_TAIL_SCAN_ROWS)])
async def test_a_truncated_read_logs_its_kind_and_the_clamped_rows_its_bound_scanned(
    k: int, logged: int
) -> None:
    """#399 OD2: the log line names the read's own kind and the K its bound used, a K past
    `MAX_TAIL_SCAN_ROWS` logged as that pin."""
    conn = _Steps(_stamps(RSINCE + MIN), [])  # bounded, then no row from the bound on
    reader = BarReader(conn, _sched, now_us=lambda: NOW, tail_scan_rows=k)
    with capture_logs() as logs:
        tail = await reader.read_tail(SYM, RSPEC, 3)
    (line,) = [e for e in logs if e["event"] == "bars_tail_scan_truncated"]
    assert (line["kind"], line["scanned_rows"]) == ("renko", logged)
    assert (
        (line["window_start_us"], line["since_us"])
        == (RSINCE, RSINCE + MIN)
        == (
            RSINCE,
            tail.since_us,
        )
    )


@pytest.mark.parametrize("error_type", [OSError, TimeoutError], ids=["os-error", "timeout"])
@pytest.mark.parametrize("at", [1, 2, 3], ids=["the-table-bound", "the-series-bound", "the-tail"])
async def test_a_failed_statement_fails_the_read_with_no_fallback_and_no_count(
    at: int, error_type: type[Exception]
) -> None:
    """D2-M4: the table-row bound is the read's first statement, and when it fails or times out so
    does the read (the store counts it and reads again): the statements that scan from the window
    start never run in its place. A read that fails after the bound moved it is not counted:
    the counter says how many reads the bound shaped, and the retry counts once."""
    newest = _stamps(T0 + 9 * MIN, T0 + 8 * MIN, T0 + 7 * MIN)  # the limit: a tail follows
    conn = _Fails(error_type("questdb down"), at, _stamps(K5), newest, [])
    before = _bounded_reads()
    with pytest.raises(error_type):
        await BarReader(conn, _sched, now_us=lambda: NOW).read_tail(SYM, RSPEC, 3)
    assert len(conn.calls) == at and _is_scan_bound(conn.calls[0][0])
    assert _bounded_reads() == before


@pytest.mark.parametrize("error_type", [OSError, TimeoutError], ids=["os-error", "timeout"])
async def test_a_failed_time_bound_fails_the_read_with_no_fallback_and_no_count(
    error_type: type[Exception],
) -> None:
    """#399 R1: a time read's bound fails as a non-time one's does: one statement, no count."""
    conn = _Fails(error_type("questdb down"), 1, _stamps(NOW - 3 * MIN), [_row(1)])
    before = _bounded_reads("time")
    with pytest.raises(error_type):
        await BarReader(conn, _sched, now_us=lambda: NOW).read_tail(SYM, SPEC, 2)
    assert len(conn.calls) == 1 and _is_scan_bound(conn.calls[0][0])
    assert _bounded_reads("time") == before


def test_the_counter_declares_one_series_per_bar_kind() -> None:
    """#399 OD2: `kind` is a closed set; the catalogue's cardinality follows `BUILD_VERSIONS`."""
    (entry,) = [s for s in CATALOGUE if s.name == "bars_tail_scan_bounded_total"]
    assert entry.labels == ("kind",) and entry.max_series == len(BUILD_VERSIONS)
    assert all(
        REGISTRY.get_sample_value("bars_tail_scan_bounded_total", {"kind": k}) is not None
        for k in BUILD_VERSIONS
    )  # each series exists from import, at 0 until a read is truncated


async def test_a_time_read_takes_its_table_bound_then_one_tail_statement() -> None:
    """A time window spans twice `limit` bars, which bounds its sort, so it needs no series
    bound; its table-row bound comes first (#399 R1), as a non-time read's does."""
    conn = _Conn([_row(1), _row(0)])
    await BarReader(conn, _sched, now_us=lambda: NOW).read_tail(SYM, SPEC, 2)
    assert conn.calls == [
        build_tail_scan_bound_query("time", NOW - 4 * MIN, now_us=NOW),
        build_tail_query("time", SYM, "1m", 2, NOW - 4 * MIN, now_us=NOW),
    ]


@pytest.mark.parametrize(
    ("kth", "start", "bounded"),
    [([], NOW - 4 * MIN, False), ([NOW - 3 * MIN], NOW - 3 * MIN, True),
     ([NOW - 4 * MIN], NOW - 4 * MIN, False), ([NOW - 9 * MIN], NOW - 4 * MIN, False)],
    ids=["table-below-k", "bounded", "bound-at-the-window-start", "bound-below-the-window"],
)  # fmt: skip
async def test_a_time_read_starts_at_the_later_of_its_window_start_and_its_table_bound(
    kth: list[int], start: int, bounded: bool
) -> None:
    """#399 R1: a sparse time series gets only its bars among the table's newest rows; the read
    that the bound started later is counted, as a non-time one is."""
    conn = _Steps(_stamps(*kth), [_row(1)])
    before = _bounded_reads("time")
    with capture_logs() as logs:
        tail = await BarReader(conn, _sched, now_us=lambda: NOW).read_tail(SYM, SPEC, 2)
    assert conn.calls[1] == build_tail_query("time", SYM, "1m", 2, start, now_us=NOW)
    assert (tail.since_us, tail.bounded) == (start, bounded)
    assert _bounded_reads("time") - before == (1 if bounded else 0)
    truncated = [e for e in logs if e["event"] == "bars_tail_scan_truncated"]
    assert truncated == (
        [{"event": "bars_tail_scan_truncated", "log_level": "info", "kind": "time",
          "spec_hash": SPEC.spec_hash, "scanned_rows": MAX_TAIL_SCAN_ROWS,
          "window_start_us": NOW - 4 * MIN, "since_us": start}]
        if bounded else []
    )  # fmt: skip


async def test_read_tail_is_oldest_first_and_closed_only() -> None:
    tail = await _read([_row(3, gen=2, closed=False), *(_row(i, gen=2) for i in (2, 1, 0))])
    assert [(gen, b.index) for gen, b in tail.bars] == [(2, 0), (2, 1), (2, 2)]
    assert (tail.skipped, tail.dropped, tail.integrity_degraded) == (1, 0, False)


async def test_read_tail_maps_each_stored_row_back_to_its_bar() -> None:
    bars = [_bar(i) for i in range(3)]
    tail = await _read([bar_row(b, SPEC, generation=0) for b in reversed(bars)])
    assert [b for _, b in tail.bars] == bars  # every field, symbol and spec_hash included


async def test_read_tail_drops_untrusted_rows_and_marks_the_tail_degraded() -> None:
    """SR-E12-11: a degraded tail is incomplete; `skipped` still counts only the open bar."""
    rows = [_row(3, closed=False), _row(2), _row(1), _row(0)]
    rows[1]["close"] = 99.0  # bar 2 tampered after write: its checksum no longer matches
    tail = await _read(rows)
    assert _indexes(tail) == [0, 1]
    assert (tail.dropped, tail.skipped, tail.integrity_degraded, tail.fetched) == (1, 1, True, 4)


async def test_a_mixed_tape_and_kline_page_hydrates_only_the_tape_rows() -> None:
    """Kline rows carry no `(generation, index)` key and no order flow (BR-07): REST serves them,
    the WS snapshot never fabricates an index or a zero delta for them."""
    tail = await _read([_row(3), _kline_row(2), _row(1), _kline_row(0)])
    assert (_indexes(tail), tail.skipped) == ([1, 3], 2)


async def test_read_tail_names_only_the_rows_built_below_the_running_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§6.1 `meta.build_version` is the lowest among the bars sent: the read reports old rows."""
    rows = [_row(1, gen=1), _row(0, {"build_version": None}, gen=1)]  # NULL: a pre-0003 v1 row
    assert (await _read(rows)).builds == {}
    monkeypatch.setitem(BUILD_VERSIONS, "time", BUILD_VERSIONS["time"] + 1)
    assert (await _read(rows)).builds == {(1, 0, T0): 1, (1, 1, T0 + MIN): 1}


async def test_read_tail_keeps_the_builds_of_two_runs_that_reused_a_bar_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A builder cold start reuses `(generation, index)` (#2662): the open time keeps the old
    run's bar 0 and the new run's bar 0 apart, each with its own build."""
    v = BUILD_VERSIONS["time"]
    monkeypatch.setitem(BUILD_VERSIONS, "time", v + 2)
    new0 = _row(0, {"build_version": v + 1}, shift=5)
    tail = await _read([new0, _row(1, {"build_version": v}), _row(0, {"build_version": v})])
    assert tail.builds == {(0, 0, T0): v, (0, 1, T0 + MIN): v, (0, 0, T0 + 5 * MIN): v + 1}


async def test_read_tail_keeps_restored_tape_rows() -> None:
    """`parquet` rows are tape restored from the cold tier (`SOURCE_RANK`): kept like `tape`."""
    tail = await _read([_row(1, {"source": "parquet"}), _row(0)])
    assert (_indexes(tail), tail.skipped) == ([0, 1], 0)


@pytest.mark.parametrize(
    "change",
    [{"source": KLINE_SOURCE}, {"source": "unranked"}, {"index": None}, {"generation": None}],
    ids=["kline-source", "unknown-source", "no-index", "no-generation"],
)
async def test_read_tail_skips_a_row_missing_any_part_of_the_bar_key_or_tape_origin(
    change: dict[str, object],
) -> None:
    """Each condition holds on its own, not only via the SQL `index IS NOT NULL` filter."""
    tail = await _read([_row(1, change, gen=1), _row(0, gen=1)])
    assert (_indexes(tail), tail.skipped) == ([0], 1)


@pytest.mark.parametrize(
    "column",
    ["close_ts", "volume", "buy_volume", "sell_volume", "delta", "min_delta", "max_delta",
     "trade_count", "vwap"],
)  # fmt: skip
async def test_read_tail_skips_a_row_with_a_null_value_instead_of_inventing_one(
    column: str,
) -> None:
    """BR-07: a NULL is never read as zero (or a close time as the open time). It is a plain
    skip, not a malformed row."""
    with capture_logs() as logs:
        tail = await _read([_row(1, {column: None}), _row(0)])
    assert (_indexes(tail), tail.skipped) == ([0], 1)
    assert not [e for e in logs if e["event"] == "bars_tail_rows_malformed"]


class _Unprintable:
    def __str__(self) -> str:
        raise TypeError("no text form")


@pytest.mark.parametrize(
    "change",
    [{"open": "not a number"}, {"vwap": "sNaN"}, {"trade_count": _Unprintable()}],
    ids=["ValueError", "ArithmeticError", "TypeError"],
)
async def test_read_tail_skips_a_malformed_row_instead_of_failing_the_tail(
    change: dict[str, object],
) -> None:
    tail = await _read([_row(1, change), _row(0)])
    assert (_indexes(tail), tail.skipped, tail.dropped) == ([0], 1, 0)


@pytest.mark.parametrize(
    ("generation", "kept"), [(-1, False), (MAX_GENERATION, True), (MAX_GENERATION + 1, False)]
)
async def test_read_tail_skips_a_row_whose_generation_the_writer_would_refuse(
    generation: int, kept: bool
) -> None:
    """`check_generation`'s bound on read too: a row outside it is malformed, never folded."""
    with capture_logs() as logs:
        tail = await _read([_row(1, {"generation": generation}), _row(0)])
    assert (_indexes(tail), tail.skipped) == (([0, 1], 0) if kept else ([0], 1))
    assert [e["error_type"] for e in logs] == ([] if kept else ["BarPersistError"])


async def test_read_tail_warns_once_per_read_however_many_rows_are_malformed() -> None:
    rows = [_row(2), _row(1, {"trade_count": _Unprintable()}), _row(0, {"open": "not a number"})]
    with capture_logs() as logs:
        tail = await _read(rows)
    assert (_indexes(tail), tail.skipped) == ([2], 2)
    assert [e for e in logs if e["event"] == "bars_tail_rows_malformed"] == [
        {
            "event": "bars_tail_rows_malformed", "log_level": "warning", "table": "bars_time",
            "spec_hash": SPEC.spec_hash, "rows": 2, "error_type": "ValueError",
        }
    ]  # fmt: skip


@pytest.mark.parametrize(("rows", "yields"), [(128, 0), (129, 1)])
async def test_read_tail_yields_the_loop_after_every_128_rows(rows: int, yields: int) -> None:
    """C-2.17: a ticker task counts the scheduling points the read gives the loop (the fake
    fetch never suspends, so every tick is one of the read's own yields)."""
    ticks, stop = 0, False

    async def ticker() -> None:
        nonlocal ticks
        while not stop:
            ticks += 1
            await asyncio.sleep(0)

    task = asyncio.create_task(ticker())
    await asyncio.sleep(0)  # the ticker runs once before the read
    before = ticks
    tail = await _read([_row(i) for i in reversed(range(rows))])
    gave = ticks - before
    stop = True
    await task
    assert (len(tail.bars), gave) == (rows, yields)


async def test_the_series_store_hydrates_only_the_tape_rows_of_a_mixed_page() -> None:
    conn = _Conn([_row(3), _kline_row(2), _row(1), _kline_row(0)])
    store = SeriesStore(BarReader(conn, _sched, now_us=lambda: NOW).read_tail)
    with capture_logs() as logs:
        await store.ensure(SYM, SPEC)
    got = store.latest(SYM, SPEC.spec_hash, 10)
    assert got is not None and [b.index for b in got.closed] == [1, 3] and got.forming is None
    assert [e["skipped"] for e in logs if e["event"] == "bars_series_rows_skipped"] == [2]
