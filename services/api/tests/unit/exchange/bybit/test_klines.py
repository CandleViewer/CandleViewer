"""E12-S05 / SR-E12-09 (BR-02): strict `/v5/market/kline` page validation.

Inputs are the recorded corpus pages `rest/kline_BTCUSDT_1_page{0,1,2}.json` (C-13.5); the
tampered variants are derived from them in-test (one field mutated), never invented shapes.
"""

from __future__ import annotations

import copy
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.domain.klines import KlinePageRejected
from candleviewer.exchange.bybit.config import EndpointClass
from candleviewer.exchange.bybit.klines import (
    PATH,
    BybitKlineFetcher,
    fetch_kline_page,
    parse_kline_page,
)
from tests._corpus import rest

PAGE0 = rest("rest/kline_BTCUSDT_1_page0.json")
NOW_MS = 1_700_100_000_000  # after every corpus bar closed
TICK = Decimal("0.1")


def _page(**overrides: Any) -> dict[str, Any]:
    page: dict[str, Any] = copy.deepcopy(PAGE0)
    return page | overrides


def _mutate(row: int, col: int, value: str) -> dict[str, Any]:
    page = _page()
    page["result"]["list"][row][col] = value
    return page


def _env(rows: list[list[Any]]) -> dict[str, Any]:
    return {"retCode": 0, "result": {"symbol": "BTCUSDT", "list": rows}}


def _parse(payload: dict[str, Any], **kw: Any) -> list[Any]:
    return parse_kline_page(
        payload, symbol="BTCUSDT", interval="1", tick_size=TICK, now_ms=NOW_MS, **kw
    )


def test_parse_kline_page_corpus_page_is_ascending_and_confirmed() -> None:
    events = _parse(_page())
    starts = [e.start for e in events]
    assert len(events) == 200
    assert starts == sorted(starts)
    assert starts[0] == 1_700_014_980_000_000
    assert all(e.end == e.start + 60_000_000 - 1 for e in events)
    assert all(e.confirmed and e.source == "backfill" for e in events)


def test_parse_kline_page_forming_bar_is_unconfirmed() -> None:
    newest_ms = int(PAGE0["result"]["list"][0][0])
    events = parse_kline_page(_page(), symbol="BTCUSDT", interval="1", now_ms=newest_ms + 1)
    assert events[-1].confirmed is False
    assert all(e.confirmed for e in events[:-1])


@pytest.mark.parametrize(
    ("row", "col", "value", "reason"),
    [
        (3, 2, "62000.0", "high_below_body"),  # high < max(o, c)
        (3, 3, "62999.0", "low_above_body"),  # low > min(o, c)
        (3, 5, "-1", "negative_volume"),
        (3, 6, "-5", "negative_volume"),
        (3, 1, "62902.05", "off_tick"),
        (3, 4, "0", "non_positive_price"),
        (3, 0, "1700026740001", "misaligned_time"),
        (0, 0, "1700026950000", "misaligned_time"),  # 30 s off-grid (absolute check)
        (3, 0, "abc", "unparseable"),
        (3, 1, "NaN", "unparseable"),
        (3, 1, "x", "unparseable"),
    ],
)
def test_parse_kline_page_tampered_row_rejects_whole_page(
    row: int, col: int, value: str, reason: str
) -> None:
    with pytest.raises(KlinePageRejected) as info:
        _parse(_mutate(row, col, value))
    assert info.value.reason == reason


def test_parse_kline_page_non_monotonic_rejected() -> None:
    page = _page()
    rows = page["result"]["list"]
    rows[1], rows[2] = rows[2], rows[1]
    with pytest.raises(KlinePageRejected) as info:
        _parse(page)
    assert info.value.reason == "non_monotonic"


def test_parse_kline_page_duplicate_open_time_rejected() -> None:
    page = _page()
    page["result"]["list"][1] = list(page["result"]["list"][0])
    with pytest.raises(KlinePageRejected, match="newest-first"):
        _parse(page)


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ({"retCode": 0}, "envelope"),
        ({"retCode": 10001, "result": {"symbol": "BTCUSDT", "list": []}}, "envelope"),
        ({"result": {"symbol": "BTCUSDT", "list": []}}, "envelope"),
        ({"retCode": 0, "result": {"symbol": "BTCUSDT"}}, "envelope"),
        ({"retCode": 0, "result": {"list": []}}, "symbol_mismatch"),
        ({"retCode": 0, "result": {"symbol": "ETHUSDT", "list": []}}, "symbol_mismatch"),
        ({"retCode": 0, "result": {"symbol": "BTCUSDT", "list": [["1", "2"]]}}, "row_shape"),
        (_env([[1700026920000, "1", "1", "1", "1", "1", "1"]]), "unparseable"),
        (_env([["1700026920000", 1, "1", "1", "1", "1", "1"]]), "row_shape"),
    ],
)
def test_parse_kline_page_bad_envelope_rejected(payload: dict[str, Any], reason: str) -> None:
    with pytest.raises(KlinePageRejected) as info:
        _parse(payload)
    assert info.value.reason == reason


def test_parse_kline_page_month_interval_not_backfillable() -> None:
    with pytest.raises(KlinePageRejected):
        parse_kline_page(_page(), symbol="BTCUSDT", interval="M")


def test_parse_kline_page_without_tick_skips_only_tick_check() -> None:
    events = parse_kline_page(
        _mutate(3, 1, "62902.05"), symbol="BTCUSDT", interval="1", now_ms=NOW_MS
    )
    assert len(events) == 200


def test_kline_page_rejected_unknown_reason_is_bounded() -> None:
    assert KlinePageRejected("x", "free text").reason == "envelope"


class _Client:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict[str, Any], EndpointClass]] = []

    async def get_public(
        self, path: str, *, params: dict[str, Any], endpoint_class: EndpointClass
    ) -> dict[str, Any]:
        self.calls.append((path, params, endpoint_class))
        return self.payload


async def test_fetch_kline_page_uses_public_market_data_bucket() -> None:
    client = _Client(_page())
    events = await fetch_kline_page(
        client,  # type: ignore[arg-type]  # structural fake of the governed client
        "BTCUSDT",
        "1",
        start_us=1_700_014_980_000_000,
        end_us=1_700_026_920_000_000,
        tick_size=TICK,
    )
    assert len(events) == 200
    path, params, bucket = client.calls[0]
    assert path == PATH
    assert bucket is EndpointClass.MARKET_DATA
    assert params == {
        "category": "linear",
        "symbol": "BTCUSDT",
        "interval": "1",
        "start": 1_700_014_980_000,
        "end": 1_700_026_920_000,
        "limit": 1000,
    }


@pytest.mark.parametrize(
    ("symbol", "interval", "limit", "exc"),
    [
        ("btc/../x", "1", 10, KlinePageRejected),
        # #3555: `$` also matches before a final newline, so `match` let the first one through
        ("BTCUSDT\n", "1", 10, KlinePageRejected),
        ("BTCUSDT\r\n", "1", 10, KlinePageRejected),
        ("BTCUSDT", "M", 10, KlinePageRejected),
        ("BTCUSDT", "1", 1001, ValueError),
        ("BTCUSDT", "1", 0, ValueError),
    ],
)
async def test_fetch_kline_page_rejects_bad_inputs_before_any_call(
    symbol: str, interval: str, limit: int, exc: type[Exception]
) -> None:
    client = _Client(_page())
    with pytest.raises(exc):
        await fetch_kline_page(
            client,
            symbol,
            interval,
            start_us=0,
            end_us=1,
            limit=limit,  # type: ignore[arg-type]
        )
    assert client.calls == []


async def test_bybit_kline_fetcher_applies_catalogue_tick() -> None:
    client = _Client(_mutate(3, 1, "62902.05"))
    fetcher = BybitKlineFetcher(client, tick_size_for=lambda s: TICK)  # type: ignore[arg-type]
    with pytest.raises(KlinePageRejected):
        await fetcher("BTCUSDT", "1", 0, 1)
    plain = BybitKlineFetcher(_Client(_page()))  # type: ignore[arg-type]
    assert len(await plain("BTCUSDT", "1", 0, 1)) == 200


# ---- #2044 review fix round (F1-F3, F6) ---------------------------------------------------


def test_corpus_open_times_sit_on_the_absolute_minute_grid() -> None:
    for p in range(3):
        rows = rest(f"rest/kline_BTCUSDT_1_page{p}.json")["result"]["list"]
        assert all(int(r[0]) % 60_000 == 0 for r in rows)


def test_parse_kline_page_missing_bar_rejects_page_as_gap() -> None:
    """F1: Bybit klines are contiguous; a 2x spacing is a truncated/tampered page."""
    page = _page()
    del page["result"]["list"][5]
    with pytest.raises(KlinePageRejected) as info:
        _parse(page)
    assert info.value.reason == "gap"


def test_parse_kline_page_whole_page_shifted_off_grid_rejected() -> None:
    """F2: every row shifted by 30 s keeps relative spacing but fails the absolute grid."""
    page = _page()
    for row in page["result"]["list"]:
        row[0] = str(int(row[0]) + 30_000)
    with pytest.raises(KlinePageRejected) as info:
        _parse(page)
    assert info.value.reason == "misaligned_time"


def test_parse_kline_page_weekly_grid_is_monday() -> None:
    monday_ms = 1_699_833_600_000  # 2023-11-13 00:00 UTC
    row = [str(monday_ms), "1", "2", "0.5", "1.5", "3", "4"]
    events = parse_kline_page(_env([row]), symbol="BTCUSDT", interval="W", now_ms=NOW_MS * 2)
    assert events[0].start == monday_ms * 1000
    row[0] = str(monday_ms + 86_400_000)  # Tuesday
    with pytest.raises(KlinePageRejected):
        parse_kline_page(_env([row]), symbol="BTCUSDT", interval="W")


def _contiguous(n: int, newest_ms: int = 1_700_026_920_000) -> list[list[str]]:
    return [
        [str(newest_ms - i * 60_000), "100.0", "100.5", "99.5", "100.0", "1", "100"]
        for i in range(n)
    ]


def test_parse_kline_page_oversized_response_rejected_before_rows_are_parsed() -> None:
    """F3: 1 200 contiguous rows exceed the 1 000-row cap; a non-list row past the cap
    proves the size check runs before any row is parsed."""
    rows: list[Any] = _contiguous(1_200)
    rows[-1] = "not-a-row"
    with pytest.raises(KlinePageRejected) as info:
        _parse(_env(rows))
    assert info.value.reason == "oversized"


def test_parse_kline_page_more_rows_than_requested_limit_rejected() -> None:
    with pytest.raises(KlinePageRejected) as info:
        _parse(_env(_contiguous(11)), limit=10)
    assert info.value.reason == "oversized"
    assert len(_parse(_env(_contiguous(10)), limit=10)) == 10


# ---- F6: property tests over the SR-E12-09 validation rules --------------------------------

_PX = st.integers(min_value=1, max_value=10_000_000)  # in ticks of 0.1


@st.composite
def _valid_page(draw: st.DrawFn) -> list[list[str]]:
    n = draw(st.integers(min_value=1, max_value=40))
    newest = draw(st.integers(min_value=16_666_800, max_value=166_666_000)) * 60_000  # 13 digits
    rows = []
    for i in range(n):
        o, c = draw(_PX), draw(_PX)
        h = max(o, c) + draw(st.integers(0, 50))
        lo = max(1, min(o, c) - draw(st.integers(0, 50)))
        v = draw(st.integers(0, 10**6))
        tick = Decimal("0.1")
        rows.append(
            [str(newest - i * 60_000)]
            + [str(Decimal(x) * tick) for x in (o, h, lo, c)]
            + [str(v), str(v * 3)]
        )
    return rows


_MUTATIONS = {
    "high_below_body": lambda r: r.__setitem__(2, str(min(Decimal(r[1]), Decimal(r[4])) - 1)),
    "low_above_body": lambda r: r.__setitem__(3, str(max(Decimal(r[1]), Decimal(r[4])) + 1)),
    "negative_volume": lambda r: r.__setitem__(5, "-1"),
    "off_tick": lambda r: r.__setitem__(1, str(Decimal(r[1]) + Decimal("0.05"))),
    "misaligned_time": lambda r: r.__setitem__(0, str(int(r[0]) + 1)),
}


@given(rows=_valid_page())
@settings(max_examples=80, deadline=None)
def test_property_random_valid_page_passes(rows: list[list[str]]) -> None:
    events = _parse(_env(rows), limit=1000)
    assert len(events) == len(rows)
    assert [e.start for e in events] == sorted(e.start for e in events)


@given(rows=_valid_page(), data=st.data())
@settings(max_examples=120, deadline=None)
def test_property_single_field_mutation_rejects_page(
    rows: list[list[str]], data: st.DataObject
) -> None:
    reason = data.draw(st.sampled_from(sorted(_MUTATIONS)))
    victim = rows[data.draw(st.integers(0, len(rows) - 1))]
    _MUTATIONS[reason](victim)
    with pytest.raises(KlinePageRejected) as info:
        _parse(_env(rows))
    # A low/high mutation can also break the other bound or positivity; any rejection is a
    # rejection, but the time mutation must be classified exactly.
    if reason == "misaligned_time":
        assert info.value.reason == "misaligned_time"


# ---- #2044 security review S1: hostile numerics never escape as non-rejection errors -------


@pytest.mark.parametrize(
    "value", ["1e999999", "-1e999999", "1E-999999", "sNaN", "Infinity", "-inf"]
)
@pytest.mark.parametrize("tick", [None, TICK])
def test_parse_kline_page_hostile_numeric_rejected_with_or_without_tick(
    value: str, tick: Decimal | None
) -> None:
    with pytest.raises(KlinePageRejected) as info:
        parse_kline_page(
            _mutate(3, 2, value), symbol="BTCUSDT", interval="1", tick_size=tick, now_ms=NOW_MS
        )
    assert info.value.reason in {"unparseable", "high_below_body", "non_positive_price"}


@pytest.mark.parametrize(
    "ts", ["١٧٠٠٠٢٦٩٢٠٠٠٠", "+1700026920000", "1700026920000 ", "17000269200000"]
)
def test_parse_kline_page_start_time_must_be_13_ascii_digits(ts: str) -> None:
    with pytest.raises(KlinePageRejected) as info:
        _parse(_mutate(0, 0, ts))
    assert info.value.reason == "unparseable"
