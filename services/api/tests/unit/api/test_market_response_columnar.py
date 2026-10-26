"""#2523 levers 3 and 4: the column-wise and DuckDB-emitted bars give the per-row bytes.

`serialize_bars` / `iso_us_many` against `serialize_bar` / `iso_us` (hypothesis); `BarSegments`
(emitted-JSON pages and row lists, truncated anywhere) and the `kline_response` envelope splice
against one `orjson.dumps` of the whole dict (hypothesis); and the `/market/klines` bodies over
the pack's fixture lake against the pre-#2523 read, per-row build and dict envelope (golden,
sha256-equal), with `include_delta` true and false. Merge-blocking for lever 4.
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


@dataclass(frozen=True)
class _Emitted:
    """`EmittedBars` over rows, its JSON built by per-row `serialize_bar` (the DuckDB page's
    own bytes are pinned in `tests/unit/storage/cold/test_kline_page.py`)."""

    rows: tuple[ColdKlineRow, ...]

    def __len__(self) -> int:
        return len(self.rows)

    def head(self, n: int) -> _Emitted:
        return _Emitted(self.rows[: max(0, n)])

    def last_ts_us(self) -> int:
        return self.rows[-1].ts_us

    def bars_json(self, suffix: bytes) -> bytes:
        bars = [mr.serialize_bar(r, include_delta=False) for r in self.rows]
        return b",".join(orjson.dumps(b)[:-1] + suffix + b"}" for b in bars)


_segment = st.one_of(
    st.lists(_kline, max_size=6).map(lambda rows: ("page", rows)),
    st.lists(_kline, max_size=6).map(lambda rows: ("rows", rows)),
    st.lists(_stored, max_size=4).map(lambda rows: ("rows", rows)),  # optional-field rows
)


@given(st.lists(_segment, max_size=5), st.booleans(), st.integers(0, 30))
@example([], True, 0)  # empty page
@example([("page", [ColdKlineRow(1, "1", "1", "1", "1", "1", "1", True, "x")])], True, 1)
def test_bar_segments_json_equals_one_dumps_of_every_bar(
    segments: list[tuple[str, list[Any]]], include_delta: bool, limit: int
) -> None:
    bars = mr.BarSegments()
    for kind, rows in segments:
        if kind == "page":
            bars.add_page(_Emitted(tuple(rows)))
        else:
            bars.add_rows(rows)
    flat = [r for _, rows in segments for r in rows]
    assert len(bars) == len(flat)
    bars.truncate(limit)
    kept = flat[:limit]
    assert len(bars) == len(kept)
    if kept:
        assert bars.last_ts_us() == kept[-1].ts_us
    got = b"[" + bars.json(include_delta=include_delta) + b"]"
    assert got == _body(kept, _old, include_delta)


@pytest.mark.parametrize("include_delta", [False, True])
def test_null_delta_suffix_is_what_serialize_bar_writes(include_delta: bool) -> None:
    row = ColdKlineRow(0, "1", "2", "3", "4", "5", "6", True, "parquet")
    page = _Emitted((row,))
    suffix = mr.NULL_DELTA_SUFFIX if include_delta else b""
    want = orjson.dumps(mr.serialize_bar(row, include_delta=include_delta))
    assert page.bars_json(suffix) == want


_meta_value = st.recursive(
    st.none() | st.booleans() | st.integers(-(2**53), 2**53) | st.text(max_size=8),
    lambda inner: st.lists(inner, max_size=3) | st.dictionaries(st.text(max_size=5), inner,
                                                                  max_size=3),
    max_leaves=8,
)  # fmt: skip


@given(st.text(max_size=12), st.text(max_size=4), st.text(max_size=6),
       st.dictionaries(st.text(max_size=8), _meta_value, max_size=5),
       st.lists(_kline, max_size=5), st.booleans())  # fmt: skip
@example("BTCUSDT", "1", "time", {}, [], False)  # no bars
@example('"\\\u2028\n', "\x00", "é", {"k": '"'}, [], True)  # escapes in every string
def test_kline_response_splice_equals_one_dumps_of_the_envelope(
    symbol: str, interval: str, bar_type: str, meta: dict[str, object],
    rows: list[ColdKlineRow], include_delta: bool,
) -> None:  # fmt: skip
    bars = [mr.serialize_bar(r, include_delta=include_delta) for r in rows]
    whole = mr.kline_response(
        symbol=symbol, interval=interval, bar_type=bar_type, meta=meta, bars=bars
    )
    spliced = mr.kline_response(
        symbol=symbol, interval=interval, bar_type=bar_type, meta=meta,
        bars_json=orjson.dumps(bars)[1:-1],
    )  # fmt: skip
    assert spliced.body == whole.body
    assert spliced.status_code == whole.status_code


def _old_kline_response(**kw: Any) -> Any:
    """The pre-lever-4 envelope: one `orjson.dumps` of a dict holding every bar dict."""
    bars_json = kw.pop("bars_json")
    return mr.kline_response(**kw, bars=orjson.loads(b"[" + bars_json + b"]"))


@pytest.mark.parametrize("include_delta", [False, True])
@pytest.mark.parametrize("route", ["klines_cold", "klines_page_boundary", "klines_warm"])
async def test_klines_bodies_over_the_fixture_lake_equal_the_pre_2523_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, route: str, include_delta: bool
) -> None:
    """Golden: the pack's three klines requests (5 000 cold bars; 500 cold + 500 hot; 1 000
    hot) give sha256-equal bodies through the DuckDB-emitted page, `BarSegments` and the
    envelope splice, and through the pre-#2523 reader, per-row `serialize_bar` and one
    `orjson.dumps` of the dict envelope."""
    write_cold_lake(tmp_path)
    app = await build_app(tmp_path)
    spec = requests_plan()[route]
    params = {**spec["params"], "include_delta": str(include_delta).lower()}
    pages: list[object] = []
    real_read_page = kr._read_page

    def spy(*a: Any) -> Any:
        pages.append(out := real_read_page(*a))
        return out

    monkeypatch.setattr(kr, "_read_page", spy)
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        new = await client.get(spec["path"], params=params)
        # The pager now returns rows, so the service merges as before lever 4.
        monkeypatch.setattr(kr, "_read_page", _old_read_rows)
        monkeypatch.setattr(kr, "_read_rows", _old_read_rows)
        monkeypatch.setattr(mr, "serialize_bars", _old)
        monkeypatch.setattr(market, "kline_response", _old_kline_response)
        old = await client.get(spec["path"], params=params)
    assert new.status_code == old.status_code == 200
    assert len(new.json()["bars"]) == spec["params"]["limit"]
    assert hashlib.sha256(new.content).hexdigest() == hashlib.sha256(old.content).hexdigest()
    # The new body really came from an emitted-JSON page wherever the window is cold.
    assert [type(p).__name__ for p in pages] == (
        [] if route == "klines_warm" else ["ColdKlinePage"]
    )
