"""E12-T06 slice B (#2195): the `bars_*` tail read that hydrates the WS snapshot store."""

from __future__ import annotations

import asyncio
import itertools
import time
from collections.abc import Mapping
from decimal import Decimal

import pytest
from structlog.testing import capture_logs

from candleviewer.bars.kline_rows import KLINE_SOURCE, ORDERFLOW_NULL_COLUMNS
from candleviewer.bars.limits import MAX_NON_TIME_WINDOW_US, MAX_TAIL, MAX_TIME_WINDOW_US
from candleviewer.bars.models import Bar, BarSpec
from candleviewer.bars.reader import BarReader, BarTail, build_tail_query, tail_window_us
from candleviewer.bars.rows import BUILD_VERSIONS, bar_row, row_checksum
from candleviewer.bars.series_store import SeriesStore
from candleviewer.domain.sql_names import ts_param
from candleviewer.ws.topics import FAMILIES

SPEC = BarSpec(kind="time", interval_ms=60_000)
SYM, T0, MIN = "BTCUSDT", 1_700_000_040_000_000, 60_000_000
NOW = T0 + 10_000 * MIN


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


def _kline_row(i: int) -> dict[str, object]:
    """A kline-sourced `bars_time` row (`kline_rows.kline_row` shape): no index, no order flow."""
    return _row(i, {"source": KLINE_SOURCE, "index": None, **dict.fromkeys(ORDERFLOW_NULL_COLUMNS)})


class _Conn:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        self.calls.append((sql, params))
        return self.rows


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
    """The wire range is 0..1000 (`23-ws-protocol.md` §6.1, §13; the caller skips a 0), and
    SR-E12-07 caps it at 1000: the one read never exceeds what a snapshot may ask for."""
    assert FAMILIES["bars"].options["history"].hi == MAX_TAIL == 1_000


@pytest.mark.parametrize(
    ("kind", "limit", "match"),
    [("tick", 0, "limit"), ("tick", MAX_TAIL + 1, "limit"), ("ohlc", 1, "kind")],
)
def test_tail_query_refuses_an_unbounded_limit_or_an_unknown_kind(
    kind: str, limit: int, match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        build_tail_query(kind, SYM, "tick:500", limit, T0, now_us=T0)


@pytest.mark.parametrize(
    ("kind", "cap"), [("time", MAX_TIME_WINDOW_US), ("tick", MAX_NON_TIME_WINDOW_US)]
)
def test_tail_query_refuses_a_window_beyond_the_sr_e12_02_cap(kind: str, cap: int) -> None:
    """The cap holds where the SQL is built, not only where `tail_window_us` sizes the window."""
    build_tail_query(kind, SYM, "x", 1, NOW - cap, now_us=NOW)  # exactly the cap: accepted
    with pytest.raises(ValueError, match="SR-E12-02"):
        build_tail_query(kind, SYM, "x", 1, NOW - cap - 1, now_us=NOW)


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
    (sql, params), *_ = conn.calls
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
    reader = BarReader(_Conn([]), _sched, now_us=lambda: next(clock))
    tail = await reader.read_tail(SYM, spec, MAX_TAIL)
    assert tail.since_us == NOW - tail_window_us(spec, MAX_TAIL)  # the first reading
    assert next(clock) == NOW + 1  # and the only one


async def test_read_tail_measures_back_from_the_wall_clock_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(time, "time_ns", lambda: NOW * 1_000 + 999)
    conn = _Conn([])
    await BarReader(conn, _sched).read_tail(SYM, SPEC, 4)
    assert conn.calls[0][1][2] == ts_param(NOW - 8 * MIN)


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
