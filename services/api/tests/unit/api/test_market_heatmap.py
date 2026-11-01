"""E21-T03 (#606) `GET /market/heatmap` (22 `getHeatmap`): RBAC, validation, cursor, the per-user
read limit, disconnects, failures and metrics. The route's scope is `none` (market data), so
there is no cross-account (IDOR) case; the forbidden-role case is the 403. No network: the
reader is a fake over generated cells."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from candleviewer.api._generated.openapi_models import HeatmapResponse
from candleviewer.api.market_heatmap import MAX_PER_USER, make_market_heatmap_router
from candleviewer.orderflow.heatmap_history import (
    BookAnchor,
    BookChange,
    CellRow,
    CellSpan,
    HeatmapReadLimit,
)
from candleviewer.storage.errors import StorageTierUnavailable

T0 = 1_790_812_800_000_000  # 2026-10-01 00:00 UTC
S = 1_000_000
HOUR = 3_600 * S


def _iso(us: int) -> str:
    return datetime.fromtimestamp(us / 1e6, UTC).isoformat().replace("+00:00", "Z")


class Reader:
    """`HeatmapHistoryReader` over generated hot cells; `gate` holds every read open."""

    def __init__(
        self,
        rows: Sequence[CellRow] = (),
        *,
        first: int | None = T0,
        anchor: BookAnchor | None = None,
        fail: Exception | None = None,
    ) -> None:
        self.rows, self.first, self.anchor, self.fail = list(rows), first, anchor, fail
        self.calls = 0
        self.gate: asyncio.Event | None = None
        self.entered = 0
        self.all_in = asyncio.Event()  # set once `MAX_PER_USER` reads are inside

    async def first_available(self, symbol: str) -> int | None:
        self.calls += 1
        self.entered += 1
        if self.entered >= MAX_PER_USER:
            self.all_in.set()
        if self.gate is not None:
            await self.gate.wait()
        if self.fail is not None:
            raise self.fail
        return self.first

    async def cells(self, symbol: str, lo_us: int, hi_us: int) -> AsyncIterator[CellSpan]:
        yield CellSpan(lo_us, hi_us, "hot", [r for r in self.rows if lo_us <= r.ts_us < hi_us])

    async def book_anchor(
        self, symbol: str, depth: int, at_us: int, *, not_before_us: int
    ) -> BookAnchor | None:
        return self.anchor

    async def book_changes(
        self, symbol: str, depth: int, lo_us: int, hi_us: int
    ) -> Sequence[BookChange]:
        return []


class Principal:
    def __init__(self, ok: bool = True, user: uuid.UUID | None = None) -> None:
        self.ok, self.user_id = ok, user or uuid.uuid4()

    def has(self, permission: str) -> bool:
        return self.ok and permission == "marketdata:read"


class Resolver:
    def __init__(self, principal: Principal | None) -> None:
        self.principal = principal

    async def resolve(self, request: Request) -> Any:
        return self.principal


_OK = Principal()


def _app(
    reader: Reader | None, principal: Principal | None = _OK, *, resolver: bool = True
) -> FastAPI:
    app = FastAPI()
    app.include_router(
        make_market_heatmap_router(
            lambda: reader,
            principal_resolver=Resolver(principal) if resolver else None,
            symbol_listed=lambda sym: sym == "BTCUSDT",
            tick_size=lambda sym: Decimal("0.1"),
            now_us=lambda: T0 + 2 * HOUR,
        )
    )
    return app


def _get(app: FastAPI, **params: Any) -> httpx.Response:
    base = {"symbol": "BTCUSDT", "from": _iso(T0), "to": _iso(T0 + 10 * S)}
    response: httpx.Response = TestClient(app).get("/market/heatmap", params=base | params)
    return response


def _rows(lo: int, hi: int) -> list[CellRow]:
    return [CellRow(t, Decimal(100 + k % 3), 1.0 + k, 0.5, 1, False)
            for k, t in enumerate(range(lo, hi, S))]  # fmt: skip


def test_recorded_history_is_served_as_the_contract_shape() -> None:
    r = _get(_app(Reader(_rows(T0, T0 + 10 * S))), time_bucket_ms=1000)
    assert r.status_code == 200
    body = r.json()
    HeatmapResponse.model_validate(body)
    assert len(body["times"]) == 10 and len(body["bid_matrix"][0]) == 10
    assert body["history"] == "full" and body["next_cursor"] is None
    assert [s["source"] for s in body["segments"]] == ["hot"]


def test_unauthorised_without_marketdata_read_is_403() -> None:
    """Scenario: Unauthorised caller (the forbidden role; scope none, so no IDOR case)."""
    reader = Reader()
    r = _get(_app(reader, Principal(ok=False)))
    assert r.status_code == 403 and r.json()["code"] == "forbidden"
    assert _get(_app(reader, None)).status_code == 401
    assert _get(_app(reader, resolver=False)).status_code == 501
    assert reader.calls == 0


def test_unauthenticated_is_401_before_any_storage_read() -> None:
    reader = Reader()
    r = _get(_app(reader, None))
    assert r.status_code == 401 and r.json()["code"] == "unauthenticated"
    assert reader.calls == 0


@pytest.mark.parametrize("name", ["time_bucket_ms", "price_grouping", "depth"])
def test_non_integer_parameter_is_the_problem_shaped_422(name: str) -> None:
    r = _get(_app(Reader()), **{name: "abc"})
    assert r.status_code == 422 and r.json()["code"] == "validation_failed"
    assert r.headers["content-type"].startswith("application/problem+json")


def test_ts_us_is_exact_where_the_float_path_rounds_wrong() -> None:
    from candleviewer.api.market_heatmap import _ts_us

    value = "9999-10-01T00:00:00.000001Z"
    exact = (datetime(9999, 10, 1, tzinfo=UTC) - datetime(1970, 1, 1, tzinfo=UTC)) // timedelta(
        microseconds=1
    ) + 1
    assert _ts_us(value) == exact
    float_path = int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1_000_000)
    assert float_path != exact


@pytest.mark.parametrize("symbol", ["NOPEUSDT", "btcusdt", "BTCUSD", "../etc"])
def test_unknown_symbol_422_before_storage_read(symbol: str) -> None:
    reader = Reader()
    r = _get(_app(reader), symbol=symbol)
    assert r.status_code == 422 and r.json()["code"] == "validation_failed"
    assert reader.calls == 0


@pytest.mark.parametrize(
    "bad",
    [
        {"time_bucket_ms": 300},
        {"depth": 100},
        {"normalize": "log"},
        {"price_grouping": 0},
        {"price_grouping": 1001},
        {"from": "yesterday"},
        {"time_bucket_ms": "abc"},
        {"price_grouping": "1.5"},
        {"depth": ""},
        {"from": _iso(T0 + 20 * S)},
    ],
)
def test_invalid_parameter_422(bad: dict[str, Any]) -> None:
    reader = Reader()
    r = _get(_app(reader), **bad)
    assert r.status_code == 422 and reader.calls == 0


def test_from_is_required() -> None:
    r = TestClient(_app(Reader())).get("/market/heatmap", params={"symbol": "BTCUSDT"})
    assert r.status_code == 422


def test_cursor_continues_the_older_remainder_and_is_bound_to_params() -> None:
    app = _app(Reader(first=T0))
    first = _get(app, to=_iso(T0 + 48 * HOUR), time_bucket_ms=60000)
    assert first.status_code == 200
    cursor = first.json()["next_cursor"]
    assert cursor is not None
    nxt = _get(app, to=_iso(T0 + 48 * HOUR), time_bucket_ms=60000, cursor=cursor)
    assert nxt.status_code == 200
    assert nxt.json()["to"] == first.json()["from"] and nxt.json()["next_cursor"] is None
    for other in ({"price_grouping": 2}, {"depth": 50}, {"from": _iso(T0 + S)}):
        moved = _get(app, to=_iso(T0 + 48 * HOUR), time_bucket_ms=60000, cursor=cursor, **other)
        assert moved.status_code == 422 and moved.json()["code"] == "invalid_cursor"
    assert _get(app, cursor="not-a-cursor").json()["code"] == "invalid_cursor"


def test_client_disconnect_stops_the_read_and_releases_its_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = Reader(_rows(T0, T0 + 10 * S))
    app = _app(reader)

    async def gone(self: Request) -> bool:
        return True

    with monkeypatch.context() as patched:
        patched.setattr(Request, "is_disconnected", gone)
        for _ in range(MAX_PER_USER + 1):
            assert _get(app).status_code == 499
    assert _get(app).status_code == 200  # no slot was kept by the abandoned reads


async def test_concurrent_backfill_limit_429() -> None:
    reader = Reader(_rows(T0, T0 + 10 * S))
    reader.gate = asyncio.Event()
    app = _app(reader)
    params = {"symbol": "BTCUSDT", "from": _iso(T0), "to": _iso(T0 + 10 * S)}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        held = [asyncio.create_task(client.get("/market/heatmap", params=params))
                for _ in range(MAX_PER_USER)]  # fmt: skip
        await reader.all_in.wait()
        refused = await client.get("/market/heatmap", params=params)
        assert refused.status_code == 429 and refused.json()["code"] == "rate_limited"
        assert refused.headers["Retry-After"] == "1"
        reader.gate.set()
        assert [r.status_code for r in await asyncio.gather(*held)] == [200] * MAX_PER_USER
        assert (await client.get("/market/heatmap", params=params)).status_code == 200


@pytest.mark.parametrize(
    "fail", [StorageTierUnavailable("down"), HeatmapReadLimit("dense"), TimeoutError()]
)
def test_storage_failure_is_503(fail: Exception) -> None:
    r = _get(_app(Reader(fail=fail)))
    assert r.status_code == 503 and r.json()["code"] == "store_unavailable"


def test_no_reader_composed_is_503() -> None:
    assert _get(_app(None)).status_code == 503


def _sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def test_metrics_count_sources_clamps_and_unverified_rebuilds() -> None:
    hot = _sample("heatmap_backfill_requests_total", tier="hot")
    _get(_app(Reader(_rows(T0, T0 + 10 * S))))
    assert _sample("heatmap_backfill_requests_total", tier="hot") == hot + 1
    level = ((Decimal("100.0"), Decimal("1")),)
    anchor = BookAnchor(T0 - S, 1, level, level, None)
    unverified = _sample("heatmap_reconstruct_unverified_total")
    clamped = _sample("heatmap_backfill_clamped_total")
    r = _get(_app(Reader(anchor=anchor)), to=_iso(T0 + HOUR), time_bucket_ms=100)
    assert r.json()["clamped"] is True and r.json()["estimated"] is True
    assert _sample("heatmap_reconstruct_unverified_total") > unverified
    assert _sample("heatmap_backfill_clamped_total") == clamped + 1
