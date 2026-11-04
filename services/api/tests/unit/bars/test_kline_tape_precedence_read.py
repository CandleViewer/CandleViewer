"""BR-07 / SR-E12-10 read side: a kline-sourced `bars_time` row never shadows a tape row.

The DEDUP key includes `generation` and `index`, so a kline row (generation 0, NULL index) and
a tape row can share an open time. `read_bars` serves the tape row there, and a full page that
ends on a kline row resumes at that open time, so the tape row is never paged past.
"""

from __future__ import annotations

import re

from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.bars.models import BarSpec
from candleviewer.bars.reader import BarReader, stored_bar
from candleviewer.bars.rows import bar_param_for, row_checksum
from candleviewer.domain.sql_names import ts_us_from_row

SPEC = BarSpec(kind="time", interval_ms=60_000)
M = 60_000_000


def _row(ts: int, source: str | None = "tape", **kw: object) -> dict[str, object]:
    row: dict[str, object] = {
        "ts": ts, "close_ts": ts + M - 1, "symbol": "BTCUSDT", "bar_param": bar_param_for(SPEC),
        "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 4.0, "buy_volume": 3.0,
        "sell_volume": 1.0, "delta": 2.0, "min_delta": -1.0, "max_delta": 2.5, "delta_pct": 50.0,
        "trade_count": 9, "vwap": 1.25, "is_closed": True, "build_version": 1, "source": source,
        "generation": 1, "index": ts // M, **kw,
    }  # fmt: skip
    row["row_checksum"] = row_checksum(row) if source is not None else None
    return row


def _kline(ts: int) -> dict[str, object]:
    return _row(ts, "kline", generation=0, index=None, delta=None, buy_volume=None)


class _Fetch:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        return self.rows


async def _noop(*a: object) -> None: ...


def _reader(rows: list[dict[str, object]]) -> BarReader:
    return BarReader(_Fetch(rows), _noop)


async def test_read_bars_serves_the_tape_row_where_a_kline_row_shares_its_open_time() -> None:
    rows = [_kline(0), _row(0), _kline(M), _row(2 * M, source=None, generation=None, index=None)]
    rows.insert(3, _kline(2 * M))  # a legacy (NULL-source) row is tape-built too
    page = await _reader(rows).read_bars("BTCUSDT", SPEC, 0, 10 * M, 10)
    got = [(b.ts_us, b.source) for b in map(stored_bar, page.rows)]
    assert got == [(0, "tape"), (M, "kline"), (2 * M, "tape")]
    assert not page.integrity_degraded and page.dropped == 0


async def test_kline_row_is_withheld_when_the_tape_row_at_its_open_time_fails_integrity() -> None:
    tampered = _row(0)
    tampered["close"] = 9.0  # edited after its checksum
    page = await _reader([_kline(0), tampered]).read_bars("BTCUSDT", SPEC, 0, 10 * M, 10)
    assert page.rows == [] and page.integrity_degraded and page.dropped == 1


async def test_full_page_ending_on_a_kline_row_resumes_at_its_open_time() -> None:
    """NULL `index` sorts first, so a page can end on the kline row with the tape row next."""
    page = await _reader([_row(0), _row(M), _kline(2 * M)]).read_bars("BTCUSDT", SPEC, 0, 10 * M, 3)
    assert page.next_cursor == 2 * M - 1  # `after_us` callers start at 2 * M again
    assert [stored_bar(r).ts_us for r in page.rows] == [0, M]  # the kline row waits for its group


async def test_full_page_of_only_a_kline_row_still_progresses() -> None:
    page = await _reader([_kline(2 * M)]).read_bars("BTCUSDT", SPEC, 0, 10 * M, 1)
    assert page.next_cursor == 2 * M
    assert [stored_bar(r).source for r in page.rows] == ["kline"]


async def test_full_page_ending_on_a_tape_row_keeps_its_cursor() -> None:
    page = await _reader([_kline(0), _row(0), _row(M)]).read_bars("BTCUSDT", SPEC, 0, 10 * M, 3)
    assert page.next_cursor == M
    assert [(stored_bar(r).ts_us, stored_bar(r).source) for r in page.rows] == [
        (0, "tape"), (M, "tape"),
    ]  # fmt: skip


class _PagingFetch:
    """The `bars_time` range query over stored rows: window, `ORDER BY ts, index` (NULL first,
    so a kline row precedes the tape row of its open time) and the inlined `LIMIT`."""

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        lo, hi = ts_us_from_row(params[2]), ts_us_from_row(params[3])
        found = re.search(r"LIMIT (\d+)", sql)
        assert found is not None, "the reader inlines its LIMIT"
        limit = int(found.group(1))
        hit = [r for r in self.rows if lo <= ts_us_from_row(r["ts"]) < hi]
        hit.sort(key=lambda r: (ts_us_from_row(r["ts"]), r["index"] is not None))
        return hit[:limit]


@settings(max_examples=200, deadline=None, derandomize=True)
@given(
    tape=st.sets(st.integers(0, 14), max_size=10),
    kline=st.sets(st.integers(0, 14), max_size=10),
    limit=st.integers(1, 6),
)
async def test_paging_serves_the_tape_over_kline_projection_with_strict_progress(
    tape: set[int], kline: set[int], limit: int
) -> None:
    """Random tape and kline open times, random page size: the pages concatenate to exactly one
    row per open time (tape where stored, kline only elsewhere), each cursor moves forward, and
    nothing is skipped or repeated."""
    rows = [_row(i * M) for i in tape] + [_kline(i * M) for i in kline]
    reader = _reader([])
    reader._conn = _PagingFetch(rows)
    served: list[tuple[int, str]] = []
    after: int | None = None
    for _ in range(len(rows) + 2):
        page = await reader.read_bars("BTCUSDT", SPEC, 0, 100 * M, limit, after_us=after)
        served += [(b.ts_us, b.source) for b in map(stored_bar, page.rows)]
        if page.next_cursor is None:
            break
        assert after is None or page.next_cursor > after  # strict progress
        after = page.next_cursor
    else:
        raise AssertionError("paging did not terminate")
    want = [(i * M, "tape" if i in tape else "kline") for i in sorted(tape | kline)]
    assert served == want
