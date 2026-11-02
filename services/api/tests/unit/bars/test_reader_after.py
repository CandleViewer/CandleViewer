"""#2933: `read_after`, the restore check's read of the bars stored after a blob.

One bounded, parameterised statement anchored at the blob (`build_after_query`), failing closed:
a read that cannot say which bars are stored is `complete=False`, never a shorter run.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

import pytest

from candleviewer.bars.limits import MAX_NON_TIME_WINDOW_US, MAX_TIME_WINDOW_US
from candleviewer.bars.models import Bar, BarSpec
from candleviewer.bars.reader import MAX_AFTER_ROWS, BarReader, StoredRun, build_after_query
from candleviewer.bars.rows import bar_param_for, bar_row, row_checksum
from candleviewer.domain.sql_names import ts_param

SPEC = BarSpec(kind="tick", tick_count=100)
SYM, T0, GEN = "BTCUSDT", 1_700_000_040_000_000, 1_700_000_000_000
NOW = T0 + 3_600_000_000


def _bar(i: int) -> Bar:
    t = T0 + i * 1_000
    return Bar.model_validate(
        dict(
            spec_hash=SPEC.spec_hash, symbol=SYM, index=i, open_time=t, close_time=t + 999,
            open=Decimal("100.5"), high=Decimal("101"), low=Decimal("100"),
            close=Decimal("100.25"), volume=Decimal("2"), buy_volume=Decimal("1.5"),
            sell_volume=Decimal("0.5"), delta=Decimal("1"), min_delta=Decimal("-0.25"),
            max_delta=Decimal("1.25"), trade_count=100, turnover=Decimal("201"),
            vwap=Decimal("100.5"), closed=True, partial=False, gap_before=False,
        )
    )  # fmt: skip


def _row(i: int, change: Mapping[str, object] | None = None, gen: int = GEN) -> dict[str, object]:
    row = bar_row(_bar(i), SPEC, generation=gen)
    row.update(change or {})
    row["row_checksum"] = row_checksum(row)
    return row


class _Conn:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        self.calls.append((sql, params))
        return self.rows


async def _sched(*_: object) -> None:
    return None


async def _read(conn: _Conn, after: int = 4, from_us: int = T0) -> StoredRun:
    return await BarReader(conn, _sched, now_us=lambda: NOW).read_after(
        SYM, SPEC, GEN, after, from_us
    )


def test_after_query_binds_every_value_and_orders_by_the_designated_timestamp() -> None:
    sql, params = build_after_query("tick", SYM, "tick:100", GEN, 4, T0, now_us=NOW)
    head = "SELECT * FROM bars_tick WHERE symbol = $1 AND bar_param = $2 AND ts >= $3 AND "
    assert sql == head + 'generation = $4 AND "index" > $5 ORDER BY ts LIMIT ' + str(
        MAX_AFTER_ROWS + 1
    )
    assert params == (SYM, "tick:100", ts_param(T0), GEN, 4)


def test_after_query_refuses_an_unknown_kind_and_a_start_past_the_window_cap() -> None:
    with pytest.raises(ValueError, match="unknown bar kind"):
        build_after_query("bogus", SYM, "x", GEN, 0, T0, now_us=NOW)
    with pytest.raises(ValueError, match="window cap"):
        build_after_query("tick", SYM, "x", GEN, 0, NOW - MAX_NON_TIME_WINDOW_US - 1, now_us=NOW)
    build_after_query("time", SYM, "x", GEN, 0, NOW - MAX_TIME_WINDOW_US, now_us=NOW)


async def test_read_after_returns_the_bars_ordered_by_index() -> None:
    conn = _Conn([_row(6), _row(5), _row(7)])  # same `ts` order need not be index order
    run = await _read(conn)
    assert run.complete and [b.index for b in run.bars] == [5, 6, 7]
    assert run.bars[0].trade_count == 100 and run.bars[0].close_time == T0 + 5_999
    [(_, params)] = conn.calls
    assert params == (SYM, bar_param_for(SPEC), ts_param(T0), GEN, 4)


async def test_read_after_with_no_rows_is_a_complete_empty_run() -> None:
    assert await _read(_Conn([])) == StoredRun([])


async def test_read_after_past_its_row_limit_is_incomplete() -> None:
    run = await _read(_Conn([_row(5 + i) for i in range(MAX_AFTER_ROWS + 1)]))
    assert run == StoredRun([], complete=False)


async def test_read_after_at_its_row_limit_is_complete() -> None:
    run = await _read(_Conn([_row(5 + i) for i in range(MAX_AFTER_ROWS)]))
    assert run.complete and len(run.bars) == MAX_AFTER_ROWS


async def test_read_after_older_than_the_window_cap_is_incomplete_with_no_statement() -> None:
    conn = _Conn([_row(5)])
    run = await _read(conn, from_us=NOW - MAX_NON_TIME_WINDOW_US - 1)
    assert run == StoredRun([], complete=False) and conn.calls == []


@pytest.mark.parametrize(
    "bad",
    [
        {"row_checksum": 1},  # withheld by the integrity check (SR-E12-11)
        {"is_closed": False},
        {"source": "kline"},
        {"trade_count": None},
        {"generation": GEN + 1},
        {"index": 4},  # not above `after`
        {"close": "not-a-number"},
    ],
    ids=["untrusted", "open", "kline", "null", "other-gen", "not-after", "malformed"],
)
async def test_read_after_with_a_row_it_cannot_use_is_incomplete(bad: dict[str, object]) -> None:
    row = _row(6, None if "row_checksum" in bad else bad)
    if "row_checksum" in bad:
        row.update(bad)
    assert await _read(_Conn([_row(5), row])) == StoredRun([], complete=False)
