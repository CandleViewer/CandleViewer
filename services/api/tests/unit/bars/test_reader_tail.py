"""E12-T06 slice B (#2195): the `bars_*` tail read that hydrates the WS snapshot store."""

from __future__ import annotations

from decimal import Decimal

import pytest

from candleviewer.bars.kline_rows import KLINE_SOURCE, ORDERFLOW_NULL_COLUMNS
from candleviewer.bars.models import Bar, BarSpec
from candleviewer.bars.reader import MAX_TAIL, BarReader, build_tail_query
from candleviewer.bars.rows import BUILD_VERSIONS, bar_row, row_checksum

SPEC = BarSpec(kind="time", interval_ms=60_000)
SYM, T0, MIN = "BTCUSDT", 1_700_000_040_000_000, 60_000_000


def _bar(i: int, *, closed: bool = True) -> Bar:
    return Bar.model_validate(
        dict(
            spec_hash=SPEC.spec_hash, symbol=SYM, index=i, open_time=T0 + i * MIN,
            close_time=T0 + (i + 1) * MIN - 1, open=Decimal("100.5"), high=Decimal("101"),
            low=Decimal("100"), close=Decimal("100.25"), volume=Decimal("2"),
            buy_volume=Decimal("1.5"), sell_volume=Decimal("0.5"), delta=Decimal("1"),
            min_delta=Decimal("-0.25"), max_delta=Decimal("1.25"), trade_count=500,
            turnover=Decimal("201"), vwap=Decimal("100.5"), closed=closed, partial=False,
            gap_before=False,
        )
    )  # fmt: skip


def _kline_row(i: int) -> dict[str, object]:
    """A kline-sourced `bars_time` row (`kline_rows.kline_row` shape): no index, no order flow."""
    row = bar_row(_bar(i), SPEC)
    row.update(dict.fromkeys(ORDERFLOW_NULL_COLUMNS), source=KLINE_SOURCE, index=None)
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


def test_tail_query_is_newest_first_by_the_full_bar_key_and_bounded() -> None:
    sql, params = build_tail_query("time", SYM, "1m", MAX_TAIL)
    assert sql.startswith("SELECT * FROM bars_time WHERE symbol = $1 AND bar_param = $2 ")
    assert 'AND "index" IS NOT NULL' in sql  # kline rows have no bar key
    assert sql.endswith('ORDER BY ts DESC, generation DESC, "index" DESC LIMIT 1000')
    assert params == (SYM, "1m")


@pytest.mark.parametrize(("kind", "limit"), [("tick", 0), ("tick", MAX_TAIL + 1), ("ohlc", 1)])
def test_tail_query_refuses_an_unbounded_limit_or_an_unknown_kind(kind: str, limit: int) -> None:
    with pytest.raises(ValueError, match=r"limit|kind"):
        build_tail_query(kind, SYM, "tick:500", limit)


async def test_read_tail_is_oldest_first_closed_only_and_drops_untrusted_rows() -> None:
    bars = [_bar(i) for i in range(3)] + [_bar(3, closed=False)]
    rows = [bar_row(b, SPEC, generation=2) for b in reversed(bars)]  # the query's DESC order
    rows[1]["close"] = 99.0  # bar 2 tampered after write: its checksum no longer matches
    conn = _Conn(rows)
    tail = await BarReader(conn, _sched).read_tail(SYM, SPEC, 4)
    assert [(gen, b.index) for gen, b in tail.bars] == [(2, 0), (2, 1)] and tail.skipped == 1
    assert conn.calls[0][1] == (SYM, "1m")
    fields = ("open_time", "close_time", "open", "high", "low", "close", "volume", "buy_volume",
              "sell_volume", "delta", "min_delta", "max_delta", "trade_count", "vwap", "turnover",
              "closed")  # fmt: skip
    for want, (_, have) in zip(bars, tail.bars, strict=False):
        assert [getattr(have, f) for f in fields] == [getattr(want, f) for f in fields]


async def test_a_mixed_tape_and_kline_page_hydrates_only_the_tape_rows() -> None:
    """Kline rows carry no `(generation, index)` key and no order flow (BR-07): REST serves them,
    the WS snapshot never fabricates an index or a zero delta for them."""
    conn = _Conn([bar_row(_bar(3), SPEC), _kline_row(2), bar_row(_bar(1), SPEC), _kline_row(0)])
    tail = await BarReader(conn, _sched).read_tail(SYM, SPEC, 4)
    assert ([b.index for _, b in tail.bars], tail.skipped) == ([1, 3], 2)


async def test_read_tail_names_only_the_rows_built_below_the_running_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§6.1 `meta.build_version` is the lowest among the bars sent: the read reports old rows."""
    rows = [bar_row(_bar(i), SPEC, generation=1) for i in reversed(range(2))]
    rows[0]["build_version"] = None  # a pre-0003 row: built by the v1 code, never "version 0"
    rows[0]["row_checksum"] = row_checksum(rows[0])
    conn = _Conn(rows)
    assert (await BarReader(conn, _sched).read_tail(SYM, SPEC, 2)).builds == {}
    monkeypatch.setitem(BUILD_VERSIONS, "time", BUILD_VERSIONS["time"] + 1)
    tail = await BarReader(conn, _sched).read_tail(SYM, SPEC, 2)
    assert tail.builds == {(1, 0): 1, (1, 1): 1}


@pytest.mark.parametrize(
    "change",
    [{"source": KLINE_SOURCE}, {"source": "unranked"}, {"index": None}, {"generation": None}],
    ids=["kline-source", "unknown-source", "no-index", "no-generation"],
)
async def test_read_tail_skips_a_row_missing_any_part_of_the_bar_key_or_tape_origin(
    change: dict[str, object],
) -> None:
    """Each condition holds on its own, not only via the SQL `index IS NOT NULL` filter."""
    odd = bar_row(_bar(1), SPEC, generation=1)
    odd.update(change)
    odd["row_checksum"] = row_checksum(odd)
    conn = _Conn([odd, bar_row(_bar(0), SPEC, generation=1)])
    tail = await BarReader(conn, _sched).read_tail(SYM, SPEC, 2)
    assert ([b.index for _, b in tail.bars], tail.skipped) == ([0], 1)
