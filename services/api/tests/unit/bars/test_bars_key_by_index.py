"""QuestDB migration 0004 (#2016, parent #2014): bars_* are keyed by (generation, index), not ts."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from candleviewer.bars.activity_builders import VolumeBarBuilder
from candleviewer.bars.models import Bar, BarSpec
from candleviewer.bars.reader import BarReader, row_key
from candleviewer.bars.rows import bar_row, row_checksum
from candleviewer.bars.writer import BarWriter
from candleviewer.domain.sql_names import ts_us_from_row
from candleviewer.storage.questdb.ddl import parse_ddl_dir
from tests.unit.bars._trades import SYM, trade

ROOT = Path(__file__).resolve().parents[5]
SPEC = BarSpec(kind="volume", volume_threshold=Decimal("1500"))
KEY = ("ts", "symbol", "bar_param", "generation", "index")


class _DedupStore:
    """In-memory QuestDB stand-in: UPSERT on the table's DEDUP key, last write wins."""

    def __init__(self) -> None:
        self.rows: dict[tuple[object, ...], dict[str, object]] = {}

    async def write_rows(self, table: str, rows: list[dict[str, object]], ts_key: str) -> None:
        for r in rows:
            self.rows[tuple(r[k] for k in KEY)] = r  # NULL index is a valid key part

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        # #2017: time keeps `ts, "index"`; non-time orders by the full key (ts first).
        assert 'ORDER BY ts, "index"' in sql or 'ORDER BY ts, generation, "index"' in sql
        # QuestDB sorts NULL first in ASC: `row_key` maps a NULL index to -1, same order.
        return sorted(self.rows.values(), key=row_key)


async def _sched(*_: object) -> None:
    return None


def _closed_bars() -> list[Bar]:
    builder = VolumeBarBuilder(SPEC, SYM)
    updates = builder.on_trade(trade(1_700_000_000_000_000, qty="5000"))
    return [u.bar for u in updates if u.bar.closed]


@pytest.mark.asyncio
async def test_three_volume_bars_from_one_print_survive_write_read_round_trip() -> None:
    bars = _closed_bars()
    assert len(bars) == 3 and len({b.open_time for b in bars}) == 1  # same ts, BI-1 setup
    store = _DedupStore()
    writer = BarWriter(store, batch_rows=1)
    await writer.start()
    await writer.submit(bars, SPEC, generation=0)
    assert await writer.stop() == 0
    assert len(store.rows) == 3  # (ts, symbol, bar_param) alone would have collapsed to 1
    page = await BarReader(store, _sched).read_bars(SYM, SPEC, 0, 2**55, 10)
    assert [r["index"] for r in page.rows] == [b.index for b in bars]
    assert all(r["generation"] == 0 for r in page.rows)
    assert sum(Decimal(repr(r["volume"])) for r in page.rows) == Decimal("4500")  # BI-1
    assert not page.integrity_degraded


def test_generation_and_index_are_in_the_row_and_the_checksum() -> None:
    b = _closed_bars()[0]
    base = bar_row(b, SPEC, generation=0)
    other = bar_row(b, SPEC, generation=1)
    assert base["index"] == b.index and base["generation"] == 0
    assert other["row_checksum"] != base["row_checksum"] == row_checksum(base)


def test_ddl_dir_recreates_all_six_bars_tables_keyed_by_generation_and_index() -> None:
    tables = {t.name: t for t in parse_ddl_dir(ROOT / "backend/db/questdb")}
    for kind in ("time", "tick", "volume", "range", "renko", "delta"):
        t = tables[f"bars_{kind}"]
        assert t.dedup_keys == KEY and t.source_file == "0004_bars_key_by_index.sql"
        assert t.partition_by == "MONTH" and t.ts_col == "ts"
        assert {"generation", "index", "source", "row_checksum"} <= set(t.columns)


def test_read_query_quotes_every_reserved_bare_identifier() -> None:
    """Docker-free guard for the #2016 class of bug: a reserved word used bare is rejected by a
    real QuestDB but accepted by every in-memory fake."""
    import re

    from candleviewer.bars.reader import build_range_query
    from candleviewer.storage.sql_identifiers import QUESTDB_RESERVED, column_identifier

    assert column_identifier("index") == '"index"' and column_identifier("ts") == "ts"
    sql, _ = build_range_query("volume", SYM, "vol:1500", 0, 10, None, 5)
    order = sql.split("ORDER BY", 1)[1].split("LIMIT", 1)[0]
    where = sql.split("WHERE", 1)[1].split("ORDER BY", 1)[0]
    bare = re.findall(r"(?<!\")\b([A-Za-z_]\w*)\b(?!\")", order)
    bare += re.findall(r"\b(\w+)\s*(?:=|>=|<)\s*\$", where)
    assert bare and not [w for w in bare if w.lower() in QUESTDB_RESERVED], bare
    assert '"index"' in order


def test_ddl_quotes_every_reserved_column_name() -> None:
    from candleviewer.storage.sql_identifiers import QUESTDB_RESERVED

    files = sorted((ROOT / "backend/db/questdb").glob("*.sql"))
    assert len(files) >= 4
    for f in files:
        text = f.read_text("utf-8")
        code = "\n".join(line.split("--", 1)[0] for line in text.splitlines())
        for name in QUESTDB_RESERVED:
            pat = rf"^\s+{name}\s+(?:TIMESTAMP|SYMBOL|DOUBLE|LONG|INT|BOOLEAN)\b"
            assert not re.search(pat, code, re.M | re.I), (f.name, name)


def _row(b: Bar, **kw: object) -> dict[str, object]:
    row = {**bar_row(b, SPEC, generation=0), **kw}
    row["row_checksum"] = row_checksum(row)  # keep the row trustworthy for the reader
    return row


async def _page(store: _DedupStore, limit: int) -> list[dict[str, object]]:
    return (await BarReader(store, _sched).read_bars(SYM, SPEC, 0, 2**55, limit)).rows


@pytest.mark.asyncio
async def test_null_index_kline_rows_do_not_hide_older_tape_rows_from_page_one() -> None:
    """(a) NULL-index kline rows sort first under (generation, index, ts) and fill page 1."""
    b = _closed_bars()[0]
    store = _DedupStore()
    store.rows[("tape",)] = _row(b, ts=1_000, index=0)
    for i in range(3):
        store.rows[("kline", i)] = _row(b, ts=2_000 + i, index=None)
    page = await _page(store, 2)
    assert [r["ts"] for r in page][:2] == [1_000, 2_000]  # older tape row first (limit+1 rows)


@pytest.mark.asyncio
async def test_builder_cold_start_index_reset_keeps_ts_order_across_pages() -> None:
    """(b) Legacy generation-0 history repeats `(generation, index)` after an old cold start, and
    `index` is not chronological across generations: `ts` must still lead the order."""
    b = _closed_bars()[0]
    store = _DedupStore()
    store.rows[("old", 0)] = _row(b, ts=1_000, index=5)
    store.rows[("old", 1)] = _row(b, ts=1_100, index=6)
    store.rows[("new", 0)] = _row(b, ts=2_000, index=0)  # legacy cold start: same generation
    page = await _page(store, 3)
    assert [r["ts"] for r in page] == [1_000, 1_100, 2_000]


def test_range_query_bind_count_matches_placeholders() -> None:
    """Docker-free guard: QuestDB rejects a param/placeholder mismatch (asyncpg InterfaceError)."""
    from candleviewer.bars.reader import build_range_query

    for after in (None, 7):
        sql, params = build_range_query("volume", SYM, "vol:1500", 0, 10, after, 5)
        assert sorted(set(re.findall(r"\$(\d+)", sql))) == [str(i + 1) for i in range(len(params))]
        assert sql.endswith("LIMIT 5")
        assert all(isinstance(p, datetime) and p.tzinfo is None for p in params[2:])
    sql, params = build_range_query("volume", SYM, "vol:1500", 0, 10, None, 5, at_key=(3, 1, 2))
    from candleviewer.domain.sql_names import assert_bind_count

    assert_bind_count(sql, params)
    assert len(params) == 9 and params[7:] == (1, 2)
    assert all(isinstance(p, datetime) and p.tzinfo is None for p in params[2:6])
    assert all(type(p) is int for p in params[6:])  # generation, generation, index


def test_ts_param_is_microsecond_exact_and_round_trips() -> None:
    from candleviewer.domain.sql_names import ts_param, ts_us_from_row

    us = 1_700_000_000_123_457  # float division would round this
    dt = ts_param(us)
    assert dt.microsecond == 123_457 and dt.tzinfo is None  # naive, UTC by convention
    assert ts_us_from_row(dt) == us and ts_us_from_row(us) == us and ts_param(0).year == 1970
    assert ts_us_from_row(dt.replace(tzinfo=UTC)) == us  # aware UTC accepted too


@pytest.mark.asyncio
async def test_read_bars_cursor_and_rows_accept_datetime_ts_from_questdb() -> None:
    """QuestDB returns `ts` as datetime: cursor math and stored_bar must still get int µs."""
    from candleviewer.bars.reader import stored_bar
    from candleviewer.domain.sql_names import ts_param

    b = _closed_bars()[0]
    store = _DedupStore()
    for i in range(3):
        r = _row(b, ts=1_000 + i, index=i)
        r["ts"], r["close_ts"] = ts_param(1_000 + i), ts_param(2_000 + i)
        store.rows[("dt", i)] = r  # row_checksum was computed over int ts; ts is not in it
    page = await BarReader(store, _sched).read_bars(SYM, SPEC, 0, 2**55, 3)
    assert page.next_cursor == 1_002  # int µs, usable for `after_us + 1`
    sb = stored_bar(page.rows[0])
    assert sb.ts_us == 1_000 and sb.close_ts_us == 2_000


class _KeysetStore(_DedupStore):
    """`_DedupStore` that also evaluates the #2017 keyset binds `(ts, gen, idx) >= key`."""

    async def fetch(self, sql: str, *params: object) -> list[dict[str, object]]:
        rows = await super().fetch(sql, *params)
        if len(params) == 9:
            key = (
                ts_us_from_row(params[4]),
                int(str(params[6])),
                -1 if "IS NULL" in sql else int(str(params[8])),
            )
            rows = [r for r in rows if row_key(r) >= key]
        return rows[: int(sql.rsplit("LIMIT ", 1)[1])]


async def _walk(store: _DedupStore, limit: int) -> list[list[object]]:
    reader, key, pages = BarReader(store, _sched), None, []
    for _ in range(10):
        page = await reader.read_bars(SYM, SPEC, 0, 2**55, limit + 1, at_key=key)
        nxt = page.next_key
        pages.append([r["index"] for r in page.rows if nxt is None or row_key(r) < nxt])
        if (key := nxt) is None:
            return pages
    raise AssertionError("paging did not terminate")


@pytest.mark.asyncio
@pytest.mark.parametrize(("limit", "want"), [(1, [[0], [1], [2]]), (2, [[0, 1], [2]])])
async def test_same_ts_rows_page_by_key_without_skip(limit: int, want: list[list[int]]) -> None:
    b = _closed_bars()[0]
    store = _KeysetStore()
    for i in range(3):
        store.rows[("same", i)] = _row(b, ts=1_000, index=i)
    assert await _walk(store, limit) == want


@pytest.mark.asyncio
async def test_checksum_dropped_last_row_still_advances_the_key() -> None:
    b = _closed_bars()[0]
    store = _KeysetStore()
    for i in range(3):
        store.rows[("same", i)] = _row(b, ts=1_000, index=i)
    store.rows[("same", 1)] = {**store.rows[("same", 1)], "close": 9.9}  # checksum now fails
    assert await _walk(store, 1) == [[0], [], [2]]  # dropped row skipped, series continues


@pytest.mark.asyncio
async def test_null_index_kline_rows_are_still_served_on_bars_time() -> None:
    spec = BarSpec(kind="time", interval_ms=60_000)
    b = _closed_bars()[0]
    store = _KeysetStore()
    for i in range(2):
        row = {
            **bar_row(b, spec, source="kline", generation=0),
            "ts": 60_000_000 * (i + 1),
            "index": None,
        }
        row["row_checksum"] = row_checksum(row)
        store.rows[("k", i)] = row
    page = await BarReader(store, _sched).read_bars(SYM, spec, 0, 2**55, 10)
    assert [r["index"] for r in page.rows] == [None, None] and page.next_key is None


def test_at_key_is_refused_for_time_bars_and_with_after_us() -> None:
    from candleviewer.bars.reader import build_range_query

    with pytest.raises(ValueError, match="at_key"):
        build_range_query("time", SYM, "60000", 0, 10, None, 5, at_key=(1, 0, 0))
    with pytest.raises(ValueError, match="at_key"):
        build_range_query("volume", SYM, "vol:1500", 0, 10, 3, 5, at_key=(1, 0, 0))


_T = 1_700_000_000_000_000


@pytest.mark.asyncio
async def test_null_index_boundary_row_on_a_non_time_table_pages_to_completion() -> None:
    """#2181 security LOW: a legacy NULL-index row at a page boundary yields a cursor the
    server accepts (encoded, decoded, resumed) and paging reaches the end, nothing skipped."""
    from candleviewer.api.market_response import decode_key_cursor, encode_key_cursor
    from candleviewer.bars.reader import build_range_query

    b = _closed_bars()[0]
    store = _KeysetStore()
    store.rows[("a", 0)] = _row(b, ts=_T, index=0)
    store.rows[("n", 0)] = _row(b, ts=_T + 1, index=None)  # NULL sorts first at ts 2_000
    store.rows[("b", 1)] = _row(b, ts=_T + 1, index=1)
    reader, key, pages = BarReader(store, _sched), None, []
    for _ in range(10):
        page = await reader.read_bars(SYM, SPEC, 0, 2**55, 2, at_key=key)
        nxt = page.next_key
        pages.append([r["index"] for r in page.rows if nxt is None or row_key(r) < nxt])
        if nxt is None:
            break
        cursor = encode_key_cursor("bars|S|volume:1500", nxt)
        key = decode_key_cursor(cursor, scope="bars|S|volume:1500", end_us=2**55)
        assert key == nxt
    assert pages == [[0], [None], [1]]
    sql, params = build_range_query("volume", SYM, "vol:1500", 0, 10, None, 5, at_key=(_T, 0, -1))
    assert '"index" IS NULL' in sql and params[8] == 0
