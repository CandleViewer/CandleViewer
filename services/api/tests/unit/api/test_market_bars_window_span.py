"""#452 F1: the `/market/bars` window caps count from `from` when there is no cursor, so a `from`
before 1970 is not clamped up to the epoch and measured as a shorter window.

No storage is reachable: the fake reader fails the test if a refused request reaches it."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.api.market import MarketDataPrincipal
from candleviewer.api.market_bars import make_market_bars_router, window_span_us
from candleviewer.bars.limits import MAX_TIME_WINDOW_US

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


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(
        make_market_bars_router(
            lambda: _Reader(),
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
