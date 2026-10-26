"""#2523 lever 3: the column-wise bar builder gives exactly the per-row builder's output.

`serialize_bars` / `iso_us_many` against `serialize_bar` / `iso_us` (hypothesis), and the
`/market/klines` bodies over the pack's fixture lake against the pre-#2523 read and build
(golden, sha256-equal), with `include_delta` true and false.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import orjson
import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from bench.ingestion.fixture_app import build_app, requests_plan, write_cold_lake
from candleviewer.api import market
from candleviewer.api import market_response as mr
from candleviewer.storage.cold import kline_reader as kr
from candleviewer.storage.cold.kline_reader import ColdKlineRow
from tests.unit.storage.cold.test_kline_reader import _old_read_rows

#: Inside the range `iso_us` itself accepts (years 1..9999 UTC, a day in from each end: its
#: float division can round the last microsecond of 9999 over).
_MIN_US, _MAX_US = -62_135_510_400_000_000, 253_402_214_400_000_000
_EDGE = 2**32 * 1_000_000  # `iso_us_many`'s vector bound


@dataclass(frozen=True, slots=True)
class _Stored:
    """A `/market/bars`-shaped row: optional fields the fast path must hand to `serialize_bar`."""

    ts_us: int
    open: str = "1"
    high: str = "1"
    low: str = "1"
    close: str = "1"
    volume: str = "1"
    turnover: str = "1"
    confirmed: bool = True
    index: int | None = None
    generation: int | None = None
    close_ts_us: int | None = None
    trades: int | None = None
    delta: str | None = None
    min_delta: str | None = None
    max_delta: str | None = None


_ts = st.integers(min_value=_MIN_US, max_value=_MAX_US) | st.integers(
    min_value=_EDGE - 10**7, max_value=_EDGE + 10**7
)


@given(st.lists(_ts, max_size=30))
@example([])
@example([0, 1, 999_999, 1_000_000])
@example([_EDGE - 1, _EDGE])  # the last vectorised value, then the fallback
@example([-1, 1_780_000_000_000_000])
@example([1_780_000_000_000_000 + i * 60_000_000 for i in range(5)])
@example([1_780_000_000_123_456, 1_780_000_000_000_000])  # mixed: whole and fractional
@example([_MIN_US, _MAX_US])
def test_iso_us_many_is_iso_us_per_value(ts: list[int]) -> None:
    assert mr.iso_us_many(ts) == [mr.iso_us(t) for t in ts]


def test_iso_us_many_defers_non_int64_input_to_iso_us() -> None:
    assert mr.iso_us_many([True, 2]) == [mr.iso_us(True), mr.iso_us(2)]
    with pytest.raises((OverflowError, ValueError, OSError)):
        mr.iso_us_many([2**70])  # what `iso_us` itself raises, never a silent wrap
    with pytest.raises((OverflowError, ValueError, OSError)):
        mr.iso_us(2**70)


_text = st.text(min_size=0, max_size=8)
_kline = st.builds(
    ColdKlineRow,
    ts_us=st.integers(min_value=0, max_value=_EDGE + 10**9),
    open=_text,
    high=_text,
    low=_text,
    close=_text,
    volume=_text,
    turnover=_text,
    confirmed=st.booleans(),
    source=st.sampled_from(("parquet", "ws", "tape", "rest")),
)


def _body(rows: list[Any], build: Callable[..., list[dict[str, object]]], delta: bool) -> bytes:
    return orjson.dumps(build(rows, include_delta=delta))


def _old(rows: list[Any], *, include_delta: bool) -> list[dict[str, object]]:
    return [mr.serialize_bar(r, include_delta=include_delta) for r in rows]


@given(st.lists(_kline, max_size=40), st.booleans())
@example([], True)
@example([], False)
def test_serialize_bars_equals_serialize_bar_for_kline_pages(
    rows: list[ColdKlineRow], include_delta: bool
) -> None:
    new = mr.serialize_bars(rows, include_delta=include_delta)
    assert new == _old(rows, include_delta=include_delta)
    assert [list(b) for b in new] == [list(b) for b in _old(rows, include_delta=include_delta)]
    assert _body(rows, mr.serialize_bars, include_delta) == _body(rows, _old, include_delta)


_optional = st.fixed_dictionaries(
    {},
    optional={
        "index": st.integers(0, 10) | st.none(),
        "generation": st.integers(0, 10) | st.none(),
        "close_ts_us": st.integers(0, 2**40) | st.none(),
        "trades": st.integers(0, 10) | st.none(),
        "delta": st.sampled_from(("1.5", "-2", None)),
        "min_delta": st.sampled_from(("0", None)),
        "max_delta": st.sampled_from(("3", None)),
    },
)
_stored = st.builds(lambda ts, kw: _Stored(ts, **kw), st.integers(0, 2**52), _optional)


@given(st.lists(_stored, max_size=20), st.booleans())
def test_serialize_bars_equals_serialize_bar_for_rows_with_optional_fields(
    rows: list[_Stored], include_delta: bool
) -> None:
    """Any optional field set on any row: the page takes `serialize_bar` row by row."""
    assert _body(rows, mr.serialize_bars, include_delta) == _body(rows, _old, include_delta)


@pytest.mark.parametrize("include_delta", [False, True])
def test_one_extreme_bar(include_delta: bool) -> None:
    row = ColdKlineRow(_EDGE - 1, "1e-05", "-0.0", "0.000005", "1e+16", "", '"\\\n', False, "x")
    assert _body([row], mr.serialize_bars, include_delta) == _body([row], _old, include_delta)


@pytest.mark.parametrize("include_delta", [False, True])
@pytest.mark.parametrize("route", ["klines_cold", "klines_page_boundary", "klines_warm"])
async def test_klines_bodies_over_the_fixture_lake_equal_the_pre_2523_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, route: str, include_delta: bool
) -> None:
    """Golden: the pack's three klines requests (5 000 cold bars; 500 cold + 500 hot; 1 000
    hot) give sha256-equal bodies through the column-wise reader and builder and through the
    pre-#2523 reader and per-row `serialize_bar`."""
    write_cold_lake(tmp_path)
    app = await build_app(tmp_path)
    spec = requests_plan()[route]
    params = {**spec["params"], "include_delta": str(include_delta).lower()}
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        new = await client.get(spec["path"], params=params)
        monkeypatch.setattr(kr, "_read_rows", _old_read_rows)
        monkeypatch.setattr(market, "serialize_bars", _old)
        old = await client.get(spec["path"], params=params)
    assert new.status_code == old.status_code == 200
    assert len(new.json()["bars"]) == spec["params"]["limit"]
    assert hashlib.sha256(new.content).hexdigest() == hashlib.sha256(old.content).hexdigest()
