"""#2523 lever 4: `KlineReadService.read_page` keeps the cold tier as an emitted-JSON page.

A pure-Python `KlinePageLike` stands in for `ColdKlinePage` (its DuckDB side is pinned in
`tests/unit/storage/cold/test_kline_page.py`): the page must precede every row, give up its
oldest bars to `limit`, be materialised when tape interleaves with it, and claim `parquet` /
`exchange_rest` exactly as `read` does. `read` itself never returns a page.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import pytest

from candleviewer.ingestion.kline_coverage import Range
from candleviewer.ingestion.kline_read import (
    ColdKlinePager,
    KlinePageLike,
    KlineRead,
    KlineReadService,
)

IV = "5"
W = 300_000_000
BOUNDARY = 100 * W


@dataclass(frozen=True)
class _Row:
    ts_us: int
    source: str = "parquet"
    confirmed: bool = True
    open: str = "1"
    high: str = "1"
    low: str = "1"
    close: str = "1"
    volume: str = "1"
    turnover: str = "1"


@dataclass(frozen=True)
class _Page:
    """`KlinePageLike` over a row list (ascending)."""

    bars: tuple[_Row, ...]

    def __len__(self) -> int:
        return len(self.bars)

    def last_ts_us(self) -> int:
        return self.bars[-1].ts_us

    def confirmed_only(self) -> _Page:
        return _Page(tuple(b for b in self.bars if b.confirmed))

    def head(self, n: int) -> _Page:
        return _Page(self.bars[: max(0, n)])

    def tail(self, n: int) -> _Page:
        return _Page(self.bars[len(self.bars) - n :] if n > 0 else ())

    def without_ts(self, ts: set[int]) -> _Page:
        return _Page(tuple(b for b in self.bars if b.ts_us not in ts))

    def has_source(self, sources: frozenset[str]) -> bool:
        return any(b.source in sources for b in self.bars)

    def bars_json(self, suffix: bytes) -> bytes:
        return b",".join(b"%d" % b.ts_us for b in self.bars)

    def rows(self) -> list[_Row]:
        return list(self.bars)


@dataclass
class _Cold:
    """A cold reader that can page (`ColdKlinePager`), or answer `page` with rows."""

    bars: list[_Row]
    as_rows: bool = False
    asked: list[Range] = field(default_factory=list)

    def _window(self, rng: Range) -> list[_Row]:
        return [b for b in self.bars if rng.start_us <= b.ts_us < rng.end_us]

    async def __call__(self, symbol: str, interval: str, rng: Range) -> list[_Row]:
        return self._window(rng)

    async def page(self, symbol: str, interval: str, rng: Range) -> _Page | list[_Row]:
        self.asked.append(rng)
        got = self._window(rng)
        return got if self.as_rows else _Page(tuple(got))


@dataclass
class _Hot:
    bars: list[_Row]

    async def read_klines(
        self, sym: str, interval: str, rng: Range, tier: str = "auto", limit: int | None = None
    ) -> Sequence[_Row]:
        out = [b for b in self.bars if rng.start_us <= b.ts_us < rng.end_us]
        return out if limit is None else out[-limit:]


def _cold(n: int = 10, **kw: object) -> _Cold:
    return _Cold([_Row(BOUNDARY - (n - i) * W) for i in range(n)], **kw)  # type: ignore[arg-type]


def _hot(n: int = 3) -> _Hot:
    return _Hot([_Row(BOUNDARY + i * W, source="ws") for i in range(n)])


def _svc(cold: _Cold, hot: _Hot | None = None, **kw: object) -> KlineReadService:
    return KlineReadService(
        hot or _Hot([]),
        cold=cold,
        hot_boundary_us=lambda: BOUNDARY,
        **kw,  # type: ignore[arg-type]
    )


def _ts(read: KlineRead) -> list[int]:
    page = read.cold_page
    cold = [b.ts_us for b in page.rows()] if page is not None else []
    return cold + [r.ts_us for r in read.rows]


def test_paging_reader_is_a_cold_kline_pager_and_a_plain_reader_is_not() -> None:
    assert isinstance(_cold(), ColdKlinePager)

    async def plain(symbol: str, interval: str, rng: Range) -> list[_Row]:
        return []

    assert not isinstance(plain, ColdKlinePager)


async def test_read_page_cold_only_window_is_one_page_and_no_rows() -> None:
    read = await _svc(_cold()).read_page("BTCUSDT", IV, Range(BOUNDARY - 10 * W, BOUNDARY))
    assert isinstance(read.cold_page, _Page)
    assert len(read.cold_page) == 10 and read.rows == []
    assert read.sources == ["parquet"]


async def test_read_page_matches_read_bar_for_bar_and_in_sources() -> None:
    svc = _svc(_cold(), _hot())
    rng = Range(BOUNDARY - 10 * W, BOUNDARY + 3 * W)
    paged, plain = await svc.read_page("BTCUSDT", IV, rng), await svc.read("BTCUSDT", IV, rng)
    assert plain.cold_page is None
    assert _ts(paged) == [r.ts_us for r in plain.rows]
    assert paged.sources == plain.sources == ["parquet", "questdb"]
    page = paged.cold_page
    assert page is not None and page.last_ts_us() < paged.rows[0].ts_us  # page precedes rows


@pytest.mark.parametrize(("limit", "cold_kept"), [(13, 10), (5, 2), (3, 0), (0, 0)])
async def test_read_page_limit_trims_the_page_from_its_oldest_end(
    limit: int, cold_kept: int
) -> None:
    svc = _svc(_cold(), _hot())
    rng = Range(BOUNDARY - 10 * W, BOUNDARY + 3 * W)
    paged = await svc.read_page("BTCUSDT", IV, rng, limit=limit)
    plain = await svc.read("BTCUSDT", IV, rng, limit=limit)
    assert _ts(paged) == [r.ts_us for r in plain.rows]
    assert len(paged.cold_page or ()) == cold_kept
    assert paged.sources == plain.sources  # a page trimmed to nothing is not claimed


async def test_read_page_empty_page_claims_no_cold_tier() -> None:
    read = await _svc(_cold(0)).read_page("BTCUSDT", IV, Range(0, BOUNDARY))
    assert read.cold_page is not None and len(read.cold_page) == 0
    assert read.sources == []


async def test_read_page_takes_rows_when_the_pager_falls_back() -> None:
    svc = _svc(_cold(as_rows=True), _hot())
    rng = Range(BOUNDARY - 10 * W, BOUNDARY + 3 * W)
    read = await svc.read_page("BTCUSDT", IV, rng)
    assert read.cold_page is None
    assert [r.ts_us for r in read.rows] == [
        r.ts_us for r in (await svc.read("BTCUSDT", IV, rng)).rows
    ]
    assert read.sources == ["parquet", "questdb"]


async def test_read_page_claims_exchange_rest_for_a_rest_sourced_cold_bar() -> None:
    cold = _cold(3)
    cold.bars[1] = _Row(cold.bars[1].ts_us, source="rest")
    read = await _svc(cold).read_page("BTCUSDT", IV, Range(0, BOUNDARY))
    assert read.sources == ["parquet", "exchange_rest"]


async def test_read_page_tape_newer_than_the_cold_range_keeps_the_page() -> None:
    async def tape(sym: str, iv: str, rng: Range, limit: int | None) -> list[_Row]:
        return [_Row(BOUNDARY + W, source="tape")]

    svc = _svc(_cold(), _hot(), tape=tape)
    read = await svc.read_page("BTCUSDT", IV, Range(BOUNDARY - 10 * W, BOUNDARY + 3 * W))
    assert read.cold_page is not None and len(read.cold_page) == 10
    assert [r.source for r in read.rows] == ["ws", "tape", "ws"]
    assert read.sources == ["parquet", "questdb", "tape"]


async def test_read_page_tape_inside_the_cold_range_materialises_the_page() -> None:
    """Tape interleaves with cold bars: the page becomes rows, tape wins the overlap."""

    async def tape(sym: str, iv: str, rng: Range, limit: int | None) -> list[_Row]:
        return [_Row(BOUNDARY - 5 * W, source="tape", open="9")]

    svc = _svc(_cold(), _hot(), tape=tape)
    rng = Range(BOUNDARY - 10 * W, BOUNDARY + 3 * W)
    paged, plain = await svc.read_page("BTCUSDT", IV, rng), await svc.read("BTCUSDT", IV, rng)
    assert paged.cold_page is None
    assert paged.rows == plain.rows and len(paged.rows) == 13
    assert next(r for r in paged.rows if r.ts_us == BOUNDARY - 5 * W).open == "9"
    assert paged.sources == plain.sources == ["parquet", "questdb", "tape"]


async def test_read_page_hot_only_window_never_asks_the_pager() -> None:
    cold = _cold()
    read = await _svc(cold, _hot()).read_page("BTCUSDT", IV, Range(BOUNDARY, BOUNDARY + 3 * W))
    assert cold.asked == [] and read.cold_page is None and len(read.rows) == 3


def test_fake_page_is_a_kline_page() -> None:
    page: KlinePageLike = _Page(())
    assert len(page) == 0
