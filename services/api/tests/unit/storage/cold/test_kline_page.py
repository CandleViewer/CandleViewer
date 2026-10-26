"""#2523 lever 4: the cold page's DuckDB-emitted bar JSON equals the pre-#2523 bytes.

`ColdKlinePage.bars_json` against `orjson.dumps` of per-row `serialize_bar` over the pre-#2523
rows (`_old_read_rows`): seeded lakes with exponent forms, -0.0, subnormals, inf/nan, nulls,
blank sources, union_by_name gaps and duplicate parts; hypothesis over any float and any
microsecond; empty and one-bar pages. Odd values are rebuilt per row in Python; files that
cannot be emitted as text (a column no file carries, a non-DOUBLE price, a non-BOOLEAN
`confirmed`, a non-VARCHAR `source`) fall back to the lever-3 rows for the whole page. The
route-level golden lives in `tests/unit/api/test_market_response_columnar.py`.
"""

from __future__ import annotations

import random
import tempfile
import threading
from pathlib import Path
from typing import Any

import duckdb
import orjson
import pyarrow as pa
import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from candleviewer.api import market_response as mr
from candleviewer.ingestion.kline_coverage import Range
from candleviewer.ingestion.kline_read import ColdKlinePager
from candleviewer.storage.cold import kline_reader as kr
from candleviewer.storage.cold.kline_reader import ColdKlinePage, ParquetKlineReader
from candleviewer.storage.cold.layout import DatasetRegistry
from tests.unit.storage.cold.test_kline_reader import (
    _ALL,
    MIN,
    _old_read_rows,
    _part_files,
    _seeded_columns,
    _us,
    _write_table,
)

_PRICES = ("open", "high", "low", "close", "volume", "turnover")


def _old_body(rows: list[Any], include_delta: bool) -> bytes:
    return orjson.dumps([mr.serialize_bar(r, include_delta=include_delta) for r in rows])


def _con() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(":memory:")


def _page_and_old(files: list[str], lo: int, hi: int, max_rows: int = 5_100) -> tuple[Any, Any]:
    return (
        kr._read_page(_con(), files, lo, hi, max_rows),
        _old_read_rows(_con(), files, lo, hi, max_rows),
    )


def _assert_bytes_equal(page: Any, want: list[Any]) -> None:
    assert isinstance(page, ColdKlinePage)
    for include_delta in (False, True):
        suffix = mr.NULL_DELTA_SUFFIX if include_delta else b""
        assert b"[" + page.bars_json(suffix) + b"]" == _old_body(want, include_delta)
    assert page.rows() == want


def _table(values: list[float | None], t0: int, **extra: Any) -> pa.Table:
    n = len(values)
    cols: dict[str, Any] = {
        "ts": pa.array([t0 + i * MIN for i in range(n)], type=pa.timestamp("us", tz="UTC"))
    }
    for k, name in enumerate(_PRICES):  # each column a rotation, so rows mix their odd values
        cols[name] = pa.array(values[k % n :] + values[: k % n], pa.float64())
    cols["confirmed"] = [i % 3 != 0 for i in range(n)]
    cols["source"] = ["tape"] * n
    cols.update(extra)
    return pa.table(cols)


def _one_part(table: pa.Table) -> tuple[Any, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        _write_table(Path(tmp), "2026-03", table)
        t0 = _us(2026, 3)
        return _page_and_old(_part_files(Path(tmp)), t0, t0 + 31 * 24 * 60 * MIN)


@pytest.mark.parametrize("seed", [2523, 7, 11])
@pytest.mark.parametrize("max_rows", [5_100, 150])
def test_page_json_equals_the_pre_2523_bytes_over_seeded_parts(
    tmp_path: Path, seed: int, max_rows: int
) -> None:
    """Three parts: full schema with odd values and blank sources; one missing `turnover` and
    `source` (union_by_name nulls); a duplicate of part 0's first rows (dedup before LIMIT)."""
    rng = random.Random(seed)  # noqa: S311 - seeded, reproducible test data
    t0 = _us(2026, 3)
    full = _seeded_columns(rng, [t0 + i * MIN for i in range(400)], _ALL)
    _write_table(tmp_path, "2026-03", full)
    partial = _seeded_columns(rng, [t0 + (400 + i) * MIN for i in range(200)], _ALL[:5])
    _write_table(tmp_path, "2026-03", partial, name="part-0001.parquet")
    _write_table(tmp_path, "2026-03", full.slice(0, 50), name="part-0002.parquet")
    page, want = _page_and_old(_part_files(tmp_path), t0 + 10 * MIN, t0 + 590 * MIN, max_rows)
    _assert_bytes_equal(page, want)
    assert len(page) == min(580, max_rows)


@settings(max_examples=80, deadline=None)
@given(
    st.lists(st.floats(allow_nan=True, allow_infinity=True) | st.none(), min_size=1, max_size=40),
    st.integers(0, 999_999),
)
@example([1.0], 0)  # one bar, whole second
@example([1e-05, 1e16, -0.0, 5e-324], 1)  # exponent forms, signed zero, subnormal
@example([float("inf"), float("-inf"), float("nan")], 999_999)
@example([None, 60000.1], 500_000)  # NULL price
@example([1.5, 2.5], 123_000)  # whole milliseconds: `.123000`, never `.123` or dropped
def test_page_json_equals_the_pre_2523_bytes_for_any_float(
    values: list[float | None], micros: int
) -> None:
    page, want = _one_part(_table(values, _us(2026, 3) + micros))
    _assert_bytes_equal(page, want)


def test_page_rebuilds_only_the_odd_rows_in_python(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    real = kr._odd_body

    def spy(table: pa.Table, i: int) -> str:
        calls.append(i)
        return real(table, i)

    monkeypatch.setattr(kr, "_odd_body", spy)
    page, want = _one_part(_table([1.5, 2.5, 1e-07, 3.5, 4.5, 5.5, 6.5], _us(2026, 3)))
    _assert_bytes_equal(page, want)
    assert sorted(calls) == [0, 1, 2, 4, 5, 6]  # column k holds 1e-07 on row (2 - k) % 7
    page, _ = _one_part(_table([1.5, 2.5, 3.5, 4.5, 5.5, 6.5], _us(2026, 3)))
    assert len(calls) == 6  # a clean page never calls it


def test_empty_page_is_empty_json(tmp_path: Path) -> None:
    t0 = _us(2026, 3)
    _write_table(tmp_path, "2026-03", _table([1.0, 2.0], t0))
    page, want = _page_and_old(_part_files(tmp_path), t0 + 10 * MIN, t0 + 20 * MIN)
    assert isinstance(page, ColdKlinePage) and len(page) == 0 and want == []
    assert page.bars_json(b"") == b"" and page.rows() == []
    assert len(page.confirmed_only()) == len(page.tail(5)) == 0


def test_page_operations_follow_its_rows(tmp_path: Path) -> None:
    t0 = _us(2026, 3)
    sources = ["tape", "", "rest", None, "ws"]
    _write_table(tmp_path, "2026-03", _table([1.0, 2.0, 3.0, 4.0, 5.0], t0, source=sources))
    page, want = _page_and_old(_part_files(tmp_path), t0, t0 + 10 * MIN)
    assert isinstance(page, ColdKlinePage)
    assert [r.source for r in page.rows()] == ["tape", "parquet", "rest", "parquet", "ws"]
    assert page.last_ts_us() == want[-1].ts_us
    assert page.head(2).rows() == want[:2] and page.head(-1).rows() == []
    assert page.tail(2).rows() == want[-2:] and page.tail(99).rows() == want
    assert page.confirmed_only().rows() == [r for r in want if r.confirmed]
    assert page.without_ts({want[1].ts_us, 7}).rows() == [want[0], *want[2:]]
    assert page.has_source(frozenset({"rest", "kline"}))
    assert not page.without_ts({want[2].ts_us}).has_source(frozenset({"rest", "kline"}))
    assert b"[" + page.tail(2).bars_json(b"") + b"]" == _old_body(want[-2:], False)


@pytest.mark.parametrize(
    "extra",
    [
        {"open": pa.array(["1.5", "2"])},  # string price: `_num(str)`
        {"open": pa.array([1.5, 2.25], pa.float32())},  # FLOAT: repr of the widened double
        {"confirmed": pa.array([1, 0], pa.int8())},  # `bool(int)`
        {"source": pa.array([0, 7], pa.int32())},  # `str(v or "parquet")`
    ],
    ids=["varchar-price", "float32-price", "int-confirmed", "int-source"],
)
def test_page_falls_back_to_rows_for_a_column_of_another_type(extra: dict[str, Any]) -> None:
    page, want = _one_part(_table([1.0, 2.0], _us(2026, 3), **extra))
    assert isinstance(page, list) and page == want


def test_page_falls_back_to_rows_when_no_file_carries_a_column(tmp_path: Path) -> None:
    t0 = _us(2026, 3)
    rng = random.Random(1)  # noqa: S311 - seeded, reproducible test data
    table = _seeded_columns(rng, [t0 + i * MIN for i in range(30)], ("open",))
    _write_table(tmp_path, "2026-03", table)
    page, want = _page_and_old(_part_files(tmp_path), t0, t0 + 60 * MIN)
    assert isinstance(page, list) and page == want


def test_page_read_error_is_typed_and_closes_the_cursor(tmp_path: Path) -> None:
    bad = tmp_path / "part-0000.parquet"
    bad.write_bytes(b"not parquet")
    cur = _con()
    with pytest.raises(kr.ColdKlineReadError) as info:
        kr._read_page(cur, [bad.as_posix()], 0, 2**60, 10)
    assert isinstance(info.value.__cause__, duckdb.Error)
    assert str(bad) not in str(info.value)  # no path in the message
    with pytest.raises(duckdb.ConnectionException):
        cur.execute("SELECT 1")


def test_a_null_body_is_refused_not_emitted() -> None:
    table = pa.table({"ts": pa.array([1], pa.int64()), "body": pa.array([None], pa.string())})
    with pytest.raises(kr.ColdKlineReadError):
        ColdKlinePage(table).bars_json(b"")


async def test_reader_page_serves_the_window_through_the_shared_instance(tmp_path: Path) -> None:
    t0 = _us(2026, 3)
    _write_table(tmp_path, "2026-03", _table([1.0, 1e-9, 3.0], t0))
    reader = ParquetKlineReader(DatasetRegistry(tmp_path))
    assert isinstance(reader, ColdKlinePager)
    rng = Range(t0, t0 + 10 * MIN)
    page = await reader.page("BTCUSDT", "60", rng)
    assert isinstance(page, ColdKlinePage)
    assert page.rows() == await reader("BTCUSDT", "60", rng)
    assert await reader.page("BTCUSDT", "60", Range(_us(2026, 5), _us(2026, 5, 2))) == []
    reader.close()


async def test_reader_page_timeout_is_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    t0 = _us(2026, 3)
    _write_table(tmp_path, "2026-03", _table([1.0], t0))
    release = threading.Event()

    def slow(*a: object, **k: object) -> list[object]:
        release.wait(2)
        return []

    monkeypatch.setattr(kr, "_read_page", slow)
    reader = ParquetKlineReader(DatasetRegistry(tmp_path), timeout_s=0.05)
    try:
        with pytest.raises(kr.ColdKlineReadTimeout):
            await reader.page("BTCUSDT", "60", Range(t0, t0 + MIN))
    finally:
        release.set()


def _route_bodies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, params: dict[str, str]
) -> tuple[list[bytes], list[bytes]]:
    """Every page of `params` (following `next_cursor`) through the lever-4 route, then
    through the pre-#2523 reader, per-row `serialize_bar` and one dict `orjson.dumps`."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from candleviewer.api import market
    from candleviewer.api.market import MarketDataPrincipal, make_market_router
    from candleviewer.ingestion.kline_read import KlineReadService

    t0 = _us(2026, 3)
    values = [100.5, 1e-07, 101.25, float("inf"), 99.0, None, 98.5, 1e17]
    table = _table(values * 5, t0)  # 40 hourly bars; every third one unconfirmed
    _write_table(tmp_path, "2026-03", table.set_column(
        0, "ts", pa.array([t0 + i * 60 * MIN for i in range(40)], pa.timestamp("us", tz="UTC"))
    ))  # fmt: skip
    boundary = t0 + 30 * 60 * MIN

    class _Hot:
        async def read_klines(self, sym: str, iv: str, rng: Range, tier: str = "auto",
                              limit: int | None = None) -> list[kr.ColdKlineRow]:  # fmt: skip
            hot = [kr.ColdKlineRow(t, "7", "8", "6", "7", "1", "7", t // (60 * MIN) % 2 == 0, "ws")
                   for t in range(boundary, boundary + 10 * 60 * MIN, 60 * MIN)]  # fmt: skip
            return [r for r in hot if rng.start_us <= r.ts_us < rng.end_us][-(limit or 99) :]

    class _Resolver:
        def resolve(self, request: object) -> MarketDataPrincipal:
            return MarketDataPrincipal(user_id="u", permissions=frozenset({"marketdata:read"}))

    svc = KlineReadService(
        _Hot(), cold=ParquetKlineReader(DatasetRegistry(tmp_path)),
        hot_boundary_us=lambda: boundary,
    )  # fmt: skip
    app = FastAPI()
    app.include_router(make_market_router(
        lambda: _Hot(), principal_resolver=_Resolver(),  # type: ignore[arg-type,return-value]
        read_service_provider=lambda: svc, symbol_listed=lambda s: s == "BTCUSDT",
        now_us=lambda: t0 + 90 * 24 * 60 * 60 * MIN,
    ))  # fmt: skip
    client = TestClient(app, client=("127.0.0.1", 50000))

    def pages() -> list[bytes]:
        out: list[bytes] = []
        cursor: str | None = None
        while True:
            q = {**params, **({"cursor": cursor} if cursor else {})}
            r = client.get("/market/klines", params=q)
            assert r.status_code == 200
            out.append(r.content)
            cursor = r.json()["meta"]["next_cursor"]
            if cursor is None:
                return out

    new = pages()

    def old_response(**kw: Any) -> Any:
        return mr.kline_response(**kw | {"bars_json": None},
                                 bars=orjson.loads(b"[" + kw["bars_json"] + b"]"))  # fmt: skip

    monkeypatch.setattr(kr, "_read_page", _old_read_rows)
    monkeypatch.setattr(kr, "_read_rows", _old_read_rows)
    monkeypatch.setattr(
        mr, "serialize_bars",
        lambda rows, *, include_delta: [mr.serialize_bar(r, include_delta=include_delta)
                                        for r in rows],
    )  # fmt: skip
    monkeypatch.setattr(market, "kline_response", old_response)
    return new, pages()


@pytest.mark.parametrize("include_open", ["true", "false"])
@pytest.mark.parametrize("include_delta", ["true", "false"])
@pytest.mark.parametrize("limit", ["7", "40"])
def test_route_pages_equal_the_pre_2523_bytes_across_tiers_and_cursors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    include_open: str,
    include_delta: str,
    limit: str,
) -> None:
    """Odd and unconfirmed cold bars, hot bars after the boundary, pages split by the cursor
    inside the cold range, across the boundary and inside the hot range."""
    params = {
        "symbol": "BTCUSDT", "interval": "60", "from": "2026-03-01T00:00:00Z",
        "to": "2026-03-02T16:00:00Z", "limit": limit,
        "include_open": include_open, "include_delta": include_delta,
    }  # fmt: skip
    new, old = _route_bodies(tmp_path, monkeypatch, params)
    assert new == old
    bars = [b for body in new for b in orjson.loads(body)["bars"]]
    assert len(bars) == (40 if include_open == "true" else 40 - 10 - 5)


class _ArrowFailingCursor:
    """A cursor whose result fails in pyarrow, not DuckDB; it records `close()`."""

    def __init__(self) -> None:
        self.closed = 0

    def execute(self, sql: str, params: object = None) -> _ArrowFailingCursor:
        return self

    def to_arrow_table(self) -> pa.Table:
        raise pa.ArrowInvalid("injected")

    def close(self) -> None:
        self.closed += 1


def test_page_closes_its_cursor_when_a_non_duckdb_error_escapes() -> None:
    cur = _ArrowFailingCursor()
    with pytest.raises(pa.ArrowInvalid):
        kr._read_page(cur, ["x.parquet"], 0, 1, 10)  # type: ignore[arg-type]
    assert cur.closed == 1
