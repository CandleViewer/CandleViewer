"""#452 F1: the `/market/bars` window caps count from `from` when there is no cursor, so a `from`
before 1970 is not clamped up to the epoch and measured as a shorter window.

No storage is reachable: the fake reader fails the test if a refused request reaches it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st
from prometheus_client import REGISTRY

from candleviewer.api.market import MarketDataPrincipal, make_market_router
from candleviewer.api.market_bars import _ts_us, make_market_bars_router, window_span_us
from candleviewer.bars.limits import MAX_TIME_WINDOW_US
from candleviewer.bars.reader import BarPage
from candleviewer.domain.sql_names import ts_param
from candleviewer.storage.models import TimeRange
from candleviewer.storage.repositories.rows import TradeTotals

_NOW = 1_800_000_000_000_000
_US_PER_DAY = 86_400_000_000
_OK = MarketDataPrincipal(user_id="u1", permissions=frozenset({"marketdata:read"}))
_Q = {"symbol": "BTCUSDT", "bar_type": "time", "param": "1"}


class _Resolver:
    def resolve(self, request: Request) -> MarketDataPrincipal:
        return _OK


class _Reader:
    async def read_bars(self, *a: object, **k: object) -> Any:
        raise AssertionError("a refused request must not reach the reader")


class _EmptyReader:
    """Binds its window the way `bars.reader` does, so an unrepresentable instant raises here."""

    async def read_bars(
        self, symbol: str, spec: object, from_us: int, to_us: int, *a: object, **k: object
    ) -> BarPage:
        ts_param(from_us)
        ts_param(to_us)
        return BarPage(rows=[], next_cursor=None, stale=False)


async def _recording_started(symbol: str) -> int | None:
    return 0


async def _no_prints(symbol: str, rng: TimeRange) -> TradeTotals:
    return TradeTotals(prints=0, qty=Decimal(0))


def _client(reader: _Reader | _EmptyReader | None = None) -> TestClient:
    app = FastAPI()
    served = reader or _Reader()
    app.include_router(
        make_market_bars_router(
            lambda: served,
            recording_started_at_us=_recording_started,
            trade_totals=_no_prints,
            qty_step=lambda s: Decimal("0.001"),
            principal_resolver=_Resolver(),
            symbol_listed=lambda s: True,
            now_us=lambda: _NOW,
        )
    )
    return TestClient(app, client=("127.0.0.1", 50000))


def test_pre_1970_from_without_a_cursor_is_refused_for_its_real_window() -> None:
    # Before the fix the span ran from 1970-01-01, so 70 years read as 151 days and passed.
    resp = _client().get(
        "/market/bars",
        params={**_Q, "from": "1900-01-01T00:00:00Z", "to": "1970-06-01T00:00:00Z"},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "bar_window_too_large"


def test_pre_1970_from_for_a_few_days_is_not_refused_as_too_large() -> None:
    # It passes the window gate and reaches the (failing) reader.
    with pytest.raises(AssertionError, match="reach the reader"):
        _client().get(
            "/market/bars",
            params={**_Q, "from": "1969-12-30T00:00:00Z", "to": "1970-01-02T00:00:00Z"},
        )


_TS = st.integers(min_value=-(10**16), max_value=10**16)


@given(start=_TS, length=st.integers(min_value=0, max_value=10**16))
def test_property_uncursored_span_is_exactly_the_requested_window(start: int, length: int) -> None:
    assert window_span_us(start, start + length, None) == length


@given(
    start=_TS,
    length=st.integers(min_value=0, max_value=10**16),
    after_offset=st.integers(min_value=-(10**16), max_value=10**16),
)
def test_property_span_never_less_than_the_unread_part_of_the_window(
    start: int, length: int, after_offset: int
) -> None:
    end = start + length
    span = window_span_us(start, end, start + after_offset)
    assert span <= length  # a cursor can only shrink the window
    assert span >= min(length, end - (start + after_offset + 1))  # and never below what is left


def test_cap_boundary_is_unchanged_for_post_epoch_windows() -> None:
    assert window_span_us(0, MAX_TIME_WINDOW_US, None) == MAX_TIME_WINDOW_US
    assert window_span_us(_US_PER_DAY, _US_PER_DAY + 5, 7) == 5  # cursor before `from`
    assert window_span_us(0, 100, 49) == 50  # cursor inside the window


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
#: Whole seconds from year 2 to year 2100, so pre-1970 values are well covered.
_SECONDS = st.integers(min_value=-62_000_000_000, max_value=4_100_000_000)
_ROUTE_CLIENT = _client(_EmptyReader())


def _iso(seconds: int) -> str:
    return (_EPOCH + timedelta(seconds=seconds)).isoformat()


@settings(max_examples=60, derandomize=True, deadline=None)
@given(start=_SECONDS, end=_SECONDS)
def test_property_every_served_window_is_within_the_cap(start: int, end: int) -> None:
    """A 200 never covers more than the time-bar cap, whatever `from`/`to` (pre-1970 included)."""
    resp = _ROUTE_CLIENT.get("/market/bars", params={**_Q, "from": _iso(start), "to": _iso(end)})
    assert resp.status_code in {200, 400, 422}
    if resp.status_code == 200:
        assert 0 <= end - start <= MAX_TIME_WINDOW_US // 1_000_000


# --- F7: exact integer time conversion, so the last representable instant is not a 500 ------------

_MAX_ISO = "9999-12-31T23:59:59.999999Z"
_US = st.integers(min_value=-62_135_596_800_000_000, max_value=253_402_300_799_999_999)


@given(micros=_US)
def test_property_ts_us_round_trips_whole_microseconds(micros: int) -> None:
    moment = _EPOCH + timedelta(microseconds=micros)
    assert _ts_us(moment.isoformat()) == micros
    assert _ts_us(moment.isoformat().replace("+00:00", "Z")) == micros


def test_ts_us_is_exact_at_the_last_representable_microsecond() -> None:
    assert _ts_us(_MAX_ISO) == 253_402_300_799_999_999  # float math gave 253402300800000000
    assert _ts_us("0001-01-01T00:00:00Z") == -62_135_596_800_000_000


@pytest.mark.parametrize("bound", ["9999-12-31T23:59:59.999999-01:00", "0001-01-01T00:00:00+01:00"])
def test_ts_us_refuses_an_instant_outside_the_bind_range(bound: str) -> None:
    with pytest.raises(ValueError, match="range"):
        _ts_us(bound)


@pytest.mark.parametrize(
    ("bar_type", "param"),
    [("time", "1"), ("tick", "100"), ("volume", "5"), ("range", "20"), ("delta", "1"),
     ("renko", "20")],
)  # fmt: skip
def test_to_at_the_last_microsecond_is_not_a_500_for_any_bar_type(
    bar_type: str, param: str
) -> None:
    resp = _client(_EmptyReader()).get(
        "/market/bars",
        params={
            "symbol": "BTCUSDT", "bar_type": bar_type, "param": param,
            "from": "9999-12-30T00:00:00Z", "to": _MAX_ISO,
        },
    )  # fmt: skip
    assert resp.status_code == 200


def test_an_instant_past_the_range_is_a_counted_400_not_a_500() -> None:
    before = REGISTRY.get_sample_value("api_request_rejected_total", _LABELS) or 0.0
    resp = _client(_EmptyReader()).get(
        "/market/bars",
        params={**_Q, "from": "9999-12-30T00:00:00Z", "to": "9999-12-31T23:59:59.999999-01:00"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "validation_failed"
    assert (REGISTRY.get_sample_value("api_request_rejected_total", _LABELS) or 0.0) == before + 1


def test_klines_is_unaffected_at_the_last_microsecond() -> None:
    # Klines floors its window at `now` before any read, so a far-future window reads nothing.
    app = FastAPI()
    app.include_router(
        make_market_router(
            lambda: _Cache(), principal_resolver=_Resolver(), symbol_listed=lambda s: True,
            now_us=lambda: _NOW,
        )
    )  # fmt: skip
    resp = TestClient(app, client=("127.0.0.1", 50000)).get(
        "/market/klines",
        params={
            "symbol": "BTCUSDT",
            "interval": "1",
            "from": "9999-12-30T00:00:00Z",
            "to": _MAX_ISO,
        },
    )
    assert resp.status_code < 500


class _Cache:
    async def read_klines(self, *a: object, **k: object) -> Any:
        raise AssertionError("a window after now must not be read")


_LABELS = {"route": "bars", "reason": "bad_window"}
