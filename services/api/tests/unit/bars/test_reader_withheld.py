"""#452 F9 / #5581: `read_bars` and `read_tail` say where each checksum-withheld row stood
(`BarPage.withheld`, `BarTail.withheld`: `[open, next open)`, the #5581 ruling), so `/market/bars`
and the WS snapshot can name the range in `meta.coverage_holes`. Withholding itself is unchanged
(SR-E12-11, `test_bars_persistence.py`)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from candleviewer.bars.models import Bar, BarSpec
from candleviewer.bars.reader import BarPage, BarReader, Withheld
from candleviewer.bars.rows import bar_row

TIME = BarSpec(kind="time", interval_ms=300_000)
TICK = BarSpec(kind="tick", tick_count=100)
T = 1_700_000_000_000_000
WIDTH = 300_000_000


def _bar(spec: BarSpec, index: int, open_time: int, close_time: int) -> Bar:
    return Bar.model_validate(dict(
        spec_hash=spec.spec_hash, symbol="BTCUSDT", index=index, open_time=open_time,
        close_time=close_time, open=Decimal("100.1"), high=Decimal("101"), low=Decimal("99.5"),
        close=Decimal("100.5"), volume=Decimal("10"), buy_volume=Decimal("6"),
        sell_volume=Decimal("4"), delta=Decimal("2"), min_delta=Decimal("-1"),
        max_delta=Decimal("3"), trade_count=7, turnover=Decimal("1001"), vwap=Decimal("100.3"),
        closed=True, partial=False, gap_before=False,
    ))  # fmt: skip


def _row(spec: BarSpec, index: int, open_time: int, close_time: int) -> dict[str, object]:
    return bar_row(_bar(spec, index, open_time, close_time), spec, generation=2)


def _edited(row: dict[str, object], **values: object) -> dict[str, object]:
    return {**row, "close": 1.0, **values}  # changed after its checksum was written


class _Conn:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        return self.rows


async def _noop(*_: object) -> None: ...


async def _page(spec: BarSpec, rows: list[dict[str, object]], limit: int = 10) -> BarPage:
    return await BarReader(_Conn(rows), _noop).read_bars("BTCUSDT", spec, 0, 2**55, limit)


@pytest.mark.asyncio
async def test_read_bars_time_withheld_row_spans_open_to_next_open() -> None:
    rows = [_row(TIME, 0, T, T + WIDTH - 1), _edited(_row(TIME, 1, T + WIDTH, T + 2 * WIDTH - 1)),
            _row(TIME, 2, T + 2 * WIDTH, T + 3 * WIDTH - 1)]  # fmt: skip
    page = await _page(TIME, rows)
    assert page.rows == [rows[0], rows[2]] and page.dropped == 1  # withholding unchanged
    assert page.withheld == (Withheld((T + WIDTH, 2, 1), T + WIDTH, T + 2 * WIDTH),)


@pytest.mark.asyncio
async def test_read_bars_last_withheld_time_row_spans_the_spec_width() -> None:
    rows = [_row(TIME, 0, T, T + WIDTH - 1), _edited(_row(TIME, 1, T + WIDTH, T + 2 * WIDTH - 1))]
    assert (await _page(TIME, rows)).withheld == (
        Withheld((T + WIDTH, 2, 1), T + WIDTH, T + 2 * WIDTH),
    )


@pytest.mark.parametrize("close_ts", [T + 90, 2**60, None, "garbage"])
@pytest.mark.asyncio
async def test_read_bars_non_time_withheld_row_ends_at_the_next_open_never_its_close(
    close_ts: object,
) -> None:
    """L1: the row failed its checksum, so its `close_ts` (here also far-future, missing or
    unreadable) is never read: the range ends at the next raw row's open."""
    rows = [_row(TICK, 0, T, T + 40), _edited(_row(TICK, 1, T + 40, T + 90), close_ts=close_ts),
            _row(TICK, 2, T + 95, T + 120)]  # fmt: skip
    assert (await _page(TICK, rows)).withheld == (Withheld((T + 40, 2, 1), T + 40, T + 95),)


@pytest.mark.asyncio
async def test_read_bars_non_time_withheld_row_skips_equal_open_siblings() -> None:
    """The next open is the next LATER one: an equal-`ts` sibling opens no range of its own."""
    rows = [_edited(_row(TICK, 1, T + 40, T + 40)), _row(TICK, 2, T + 40, T + 60),
            _row(TICK, 3, T + 70, T + 80)]  # fmt: skip
    assert (await _page(TICK, rows)).withheld == (Withheld((T + 40, 2, 1), T + 40, T + 70),)


@pytest.mark.asyncio
async def test_read_bars_last_withheld_non_time_row_spans_its_open() -> None:
    rows = [_row(TICK, 0, T, T + 40), _edited(_row(TICK, 1, T + 40, 2**60))]
    assert (await _page(TICK, rows)).withheld == (Withheld((T + 40, 2, 1), T + 40, T + 41),)


@pytest.mark.asyncio
async def test_read_bars_withheld_row_with_an_unreadable_key_keeps_its_open_time() -> None:
    rows = [_edited(_row(TICK, 1, T + 10, T + 90), generation="x", index="y")]
    assert (await _page(TICK, rows)).withheld == (Withheld((T + 10, 0, -1), T + 10, T + 11),)


@pytest.mark.asyncio
async def test_read_bars_missing_checksum_is_withheld_and_named() -> None:
    rows = [{**_row(TIME, 4, T, T + WIDTH - 1), "row_checksum": None}]
    page = await _page(TIME, rows)
    assert page.rows == [] and page.withheld == (Withheld((T, 2, 4), T, T + WIDTH),)


@pytest.mark.asyncio
async def test_read_bars_trusted_rows_name_nothing_withheld() -> None:
    rows = [_row(TIME, 0, T, T + WIDTH - 1), {**_row(TIME, 1, T + WIDTH, T + 2 * WIDTH - 1),
                                              "row_checksum": None, "source": None}]  # fmt: skip
    page = await _page(TIME, rows)
    assert page.rows == rows and page.withheld == () and not page.integrity_degraded


@pytest.mark.asyncio
async def test_read_bars_withheld_last_raw_row_still_sets_the_cursor() -> None:
    """The (limit)-th raw row is the next page's first, withheld or not: it is named with its key,
    and the caller keeps it off this page by that key (`next_key`)."""
    rows = [_row(TICK, 0, T, T + 40), _edited(_row(TICK, 1, T + 40, T + 90))]
    page = await _page(TICK, rows, limit=2)
    assert page.next_key == (T + 40, 2, 1) and page.withheld[0].key == page.next_key


class _TailConn:
    """`read_tail`'s statements: no table-row bound, then the rows newest first."""

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        return [] if sql.startswith("SELECT ts ") else self.rows[::-1]


@pytest.mark.asyncio
async def test_read_tail_withheld_row_spans_open_to_next_open_oldest_first() -> None:
    rows = [_row(TIME, i, T + i * WIDTH, T + (i + 1) * WIDTH - 1) for i in range(4)]
    rows[1], rows[3] = _edited(rows[1]), _edited(rows[3])
    reader = BarReader(_TailConn(rows), _noop, now_us=lambda: T + 10 * WIDTH)
    tail = await reader.read_tail("BTCUSDT", TIME, 10)
    assert [b.index for _, b in tail.bars] == [0, 2] and tail.dropped == 2
    first = Withheld((T + WIDTH, 2, 1), T + WIDTH, T + 2 * WIDTH)  # ends at row 2's open
    last = Withheld((T + 3 * WIDTH, 2, 3), T + 3 * WIDTH, T + 4 * WIDTH)  # no next: the width
    assert tail.withheld == (first, last)
