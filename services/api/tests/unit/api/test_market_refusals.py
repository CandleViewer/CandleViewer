"""#452 F4a: the bars and klines routes count and log every refusal.

No storage is reachable: a fake reader/cache fails the test if a refused request reaches it."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.api.market import MarketDataPrincipal, make_market_router
from candleviewer.api.market_bars import make_market_bars_router
from candleviewer.api.market_refusal import MAX_VALUE_CHARS, escape_value
from candleviewer.bars.metrics import PARAM_REJECT_REASONS

_NOW = 1_800_000_000_000_000
_OK = MarketDataPrincipal(user_id="u1", permissions=frozenset({"marketdata:read"}))
_NO_PERM = MarketDataPrincipal(user_id="u2", permissions=frozenset())
#: A real cursor-shaped but unsigned string: decode_cursor refuses it.
_BAD_CURSOR = "AAAA"


class _Resolver:
    def __init__(self, principal: MarketDataPrincipal | None) -> None:
        self._principal = principal

    def resolve(self, request: Request) -> MarketDataPrincipal | None:
        return self._principal


class _Reader:
    async def read_bars(self, *a: object, **k: object) -> Any:
        raise AssertionError("a refused request must not reach the reader")


class _Cache:
    async def read_klines(self, *a: object, **k: object) -> Any:
        raise AssertionError("a refused request must not reach the cache")


def _bars(
    principal: MarketDataPrincipal | None = _OK,
    *,
    resolver: bool = True,
    reader: bool = True,
    listed: bool = True,
    started: int | None = None,
) -> TestClient:
    async def recording_started(symbol: str) -> int | None:
        return started

    app = FastAPI()
    app.include_router(
        make_market_bars_router(
            lambda: _Reader() if reader else None,
            recording_started_at_us=recording_started,
            principal_resolver=_Resolver(principal) if resolver else None,
            symbol_listed=lambda s: listed,
            now_us=lambda: _NOW,
        )
    )
    return TestClient(app, client=("127.0.0.1", 50000))


def _klines(
    principal: MarketDataPrincipal | None = _OK, *, resolver: bool = True, listed: bool = True
) -> TestClient:
    app = FastAPI()
    app.include_router(
        make_market_router(
            lambda: _Cache(),
            principal_resolver=_Resolver(principal) if resolver else None,
            symbol_listed=lambda s: listed,
            now_us=lambda: _NOW,
        )
    )
    return TestClient(app, client=("127.0.0.1", 50000))


def _count(reason: str) -> float:
    return (
        REGISTRY.get_sample_value("bars_endpoint_param_rejected_total", {"reason": reason}) or 0.0
    )


def _refusals(logs: list[MutableMapping[str, Any]]) -> list[MutableMapping[str, Any]]:
    return [entry for entry in logs if entry["event"] == "market_request_refused"]


_W = {"from": "2026-01-01T00:00:00Z", "to": "2026-01-02T00:00:00Z"}
_BARS_Q = {"symbol": "BTCUSDT", "bar_type": "time", "param": "1", **_W}
_KLINES_Q = {"symbol": "BTCUSDT", "interval": "1", **_W}

# (id, route, client kwargs, query overrides, status, reason)
_CASES: list[tuple[str, str, dict[str, Any], dict[str, str], int, str]] = [
    ("bars-501", "bars", {"resolver": False}, {}, 501, "unavailable"),
    ("bars-401", "bars", {"principal": None}, {}, 401, "unauthenticated"),
    ("bars-403", "bars", {"principal": _NO_PERM}, {}, 403, "forbidden"),
    ("bars-bar-type", "bars", {}, {"bar_type": "nope"}, 400, "invalid"),
    ("bars-pnf", "bars", {}, {"bar_type": "pnf"}, 422, "unsupported"),
    ("bars-param-oob", "bars", {}, {"bar_type": "tick", "param": "1"}, 400, "out_of_range"),
    ("bars-from-garbage", "bars", {}, {"from": "not-a-date"}, 400, "bad_window"),
    ("bars-from-missing", "bars", {}, {"from": ""}, 400, "bad_window"),
    ("bars-inverted", "bars", {}, {"from": _W["to"], "to": _W["from"]}, 400, "bad_window"),
    ("bars-cursor", "bars", {}, {"cursor": _BAD_CURSOR}, 400, "invalid_cursor"),
    ("bars-no-reader", "bars", {"reader": False}, {}, 503, "unavailable"),
    ("bars-unlisted", "bars", {"listed": False}, {}, 422, "unknown_symbol"),
    (
        "bars-no-data",
        "bars",
        {"started": _NOW},
        {"bar_type": "tick", "param": "100"},
        422,
        "no_data_recorded",
    ),
    ("bars-window", "bars", {}, {"from": "2024-01-01T00:00:00Z"}, 422, "window_too_large"),
    (
        "bars-bar-count",
        "bars",
        {},
        {"from": "2025-04-01T00:00:00Z", "to": "2026-04-01T00:00:00Z"},
        422,
        "window_too_large",
    ),
    ("klines-501", "klines", {"resolver": False}, {}, 501, "unavailable"),
    ("klines-401", "klines", {"principal": None}, {}, 401, "unauthenticated"),
    ("klines-403", "klines", {"principal": _NO_PERM}, {}, 403, "forbidden"),
    ("klines-interval", "klines", {}, {"interval": "7"}, 400, "invalid"),
    ("klines-price-type", "klines", {}, {"price_type": "x"}, 400, "invalid"),
    ("klines-mark", "klines", {}, {"price_type": "mark"}, 422, "unsupported"),
    ("klines-from-garbage", "klines", {}, {"from": "nope"}, 400, "bad_window"),
    ("klines-inverted", "klines", {}, {"from": _W["to"], "to": _W["from"]}, 400, "bad_window"),
    ("klines-cursor", "klines", {}, {"cursor": _BAD_CURSOR}, 400, "invalid_cursor"),
    ("klines-window", "klines", {}, {"from": "2024-01-01T00:00:00Z"}, 422, "window_too_large"),
    ("klines-unlisted", "klines", {"listed": False}, {}, 422, "unknown_symbol"),
]


@pytest.mark.parametrize(
    ("route", "kwargs", "override", "status", "reason"),
    [c[1:] for c in _CASES],
    ids=[c[0] for c in _CASES],
)
def test_refusal_increments_the_counter_and_logs_once(
    route: str, kwargs: dict[str, Any], override: dict[str, str], status: int, reason: str
) -> None:
    assert reason in PARAM_REJECT_REASONS
    client = _bars(**kwargs) if route == "bars" else _klines(**kwargs)
    query = {**(_BARS_Q if route == "bars" else _KLINES_Q), **override}
    query = {k: v for k, v in query.items() if v != ""}
    before = _count(reason)

    with capture_logs() as logs:
        resp = client.get(f"/market/{route}", params=query)

    assert resp.status_code == status
    assert _count(reason) == before + 1
    [entry] = _refusals(logs)
    assert (entry["route"], entry["reason"], entry["status"]) == (route, reason, status)
    assert entry["log_level"] == "warning"


def test_a_served_request_is_not_counted_as_refused() -> None:
    # No refusal reason moves on the happy path's first gate (auth passes; the reader is then
    # reached), so a request that fails inside the reader is not a refusal either.
    before = {r: _count(r) for r in PARAM_REJECT_REASONS}
    with capture_logs() as logs, pytest.raises(AssertionError):
        _bars().get("/market/bars", params=_BARS_Q)
    assert {r: _count(r) for r in PARAM_REJECT_REASONS} == before
    assert _refusals(logs) == []


_HOSTILE = "x\r\nERROR forged line\x00‮" + "A" * 5_000


def test_hostile_param_is_escaped_and_truncated_in_the_log() -> None:
    with capture_logs() as logs:
        resp = _bars().get("/market/bars", params={**_BARS_Q, "param": _HOSTILE})

    assert resp.status_code == 400
    [entry] = _refusals(logs)
    logged = entry["param"]
    assert "\n" not in logged and "\r" not in logged and "\x00" not in logged
    assert "‮" not in logged
    assert logged.isascii()
    assert len(logged) <= MAX_VALUE_CHARS * 4 + 2 + 3  # worst case: every char escapes to \xNN
    assert logged.startswith("'x\\r\\nERROR")  # one line: the break is a visible escape
    assert "A" * 40 not in logged


def test_hostile_symbol_and_window_values_are_escaped_in_the_log() -> None:
    with capture_logs() as logs:
        _bars(listed=False).get("/market/bars", params={**_BARS_Q, "symbol": _HOSTILE})
        _klines().get("/market/klines", params={**_KLINES_Q, "from": _HOSTILE})

    first, second = _refusals(logs)
    assert first["reason"] == "unknown_symbol" and second["reason"] == "bad_window"
    for value in (first["symbol"], second["from_"]):
        assert value.isascii() and "\n" not in value and "\r" not in value
        assert len(value) < 140


def test_refusal_log_carries_neither_the_session_nor_the_cursor_payload() -> None:
    client = _bars()
    with capture_logs() as logs:
        client.get(
            "/market/bars",
            params={**_BARS_Q, "cursor": _BAD_CURSOR},
            headers={"authorization": "Bearer s3cret-token", "cookie": "cv_session=s3cret"},
        )
    assert "s3cret" not in repr(logs)


def test_escape_value_short_values_are_repr_escaped_and_not_marked() -> None:
    assert escape_value("a\nb") == "'a\\nb'"
    assert escape_value("é") == "'\\xe9'"


def test_escape_value_long_values_are_cut_and_marked() -> None:
    out = escape_value("A" * 100)
    assert out == "'" + "A" * MAX_VALUE_CHARS + "'..."
