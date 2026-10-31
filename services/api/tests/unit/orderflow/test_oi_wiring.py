"""E24-T01 (#665): the open-interest composition: ticker tap, backfill over recorded pages, app."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from candleviewer.app import AppContext, _compose_open_interest, build_app_context, create_app
from candleviewer.bus.models import Topic
from candleviewer.exchange.bybit.config import RestClientConfig
from candleviewer.exchange.bybit.open_interest import BybitOpenInterestFetcher
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor
from candleviewer.exchange.bybit.rest import BybitRestClient
from candleviewer.ingestion.ticker_stream import ticker_event
from candleviewer.oi_wiring import OiRuntime, wire_open_interest
from candleviewer.orderflow.open_interest import TimeWindow
from candleviewer.settings import Settings
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.questdb.oi_store import InMemoryOiStore
from candleviewer.storage.questdb.repository import QuestDbMarketDataRepository

FIX = Path(__file__).resolve().parents[5] / "packages/fixtures/bybit/2026-10-05/rest"
PAGES = [
    json.loads((FIX / f"open_interest_BTCUSDT_5min_page{i}.json").read_text(encoding="utf-8"))
    for i in (0, 1)
]
S = 1_000_000
NOW_US = 1_700_100_000 * S


@dataclass(frozen=True)
class _Inst:
    symbol: str
    status: str = "trading"


class _Sched:
    def snapshot(self) -> _Sched:
        return self

    def get(self, symbol: str) -> _Inst | None:
        return _Inst(symbol) if symbol == "BTCUSDT" else None


async def _started() -> AppContext:
    ctx = build_app_context(Settings())
    await ctx.storage.start(ctx)
    ctx.ingestion.instruments = _Sched()  # type: ignore[assignment]  # a minimal catalogue
    return ctx


def _tick(ts_us: int, oi: str | None = "61180.2", value: str | None = "3861100000") -> object:
    state = {k: Decimal(v) for k, v in (("open_interest", oi), ("open_interest_value", value))
             if v is not None}  # fmt: skip
    return ticker_event("BTCUSDT", state, ts_event_us=ts_us, ts_ingest_us=ts_us)


def _fetcher(seen: list[httpx.Request]) -> BybitOpenInterestFetcher:
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=PAGES[1 if "cursor" in req.url.params else 0])

    client = BybitRestClient(
        RestClientConfig(base_url="https://api.bybit.com"),
        governor=TokenBucketGovernor(),
        transport=httpx.MockTransport(handler),
    )
    return BybitOpenInterestFetcher(client)


async def test_oi_tap_writes_one_row_per_second_and_skips_tickers_without_oi() -> None:
    ctx, store = await _started(), InMemoryOiStore()
    runtime = wire_open_interest(ctx, store=store, fetcher=None, now_us=lambda: NOW_US)
    results = [
        await runtime.on_ticker(ev)
        for ev in (_tick(NOW_US), _tick(NOW_US + 500_000), _tick(NOW_US + S, oi=None),
                   _tick(NOW_US + 2 * S), "not a ticker")
    ]  # fmt: skip
    assert results == [True, False, False, True, False]
    rows = await store.read_points("BTCUSDT", "1s", "ws_ticker", TimeWindow(0, 2**62), 10)
    assert [r.ts_us for r in rows] == [NOW_US, NOW_US + 2 * S]
    assert rows[0].open_interest_value == Decimal("3861100000")


async def test_oi_tap_write_failure_is_logged_not_raised() -> None:
    ctx = build_app_context(Settings())  # storage never started -> StorageTierUnavailable
    runtime = wire_open_interest(ctx, store=InMemoryOiStore(), fetcher=None, now_us=lambda: 0)
    assert await runtime.on_ticker(_tick(NOW_US)) is False


async def test_oi_runtime_taps_the_bus_and_backfills_on_first_request() -> None:
    ctx, store = await _started(), InMemoryOiStore()
    seen: list[httpx.Request] = []
    runtime = wire_open_interest(ctx, store=store, fetcher=_fetcher(seen), now_us=lambda: NOW_US)
    runtime.start()
    runtime.start()  # idempotent
    env = ctx.settings.environment.value
    await ctx.bus.bus.publish(Topic(env=env, domain="md", symbol="BTCUSDT", detail="ticker"),
                              _tick(NOW_US))  # fmt: skip
    service = ctx.orderflow.open_interest
    assert service is not None
    first = await service.series(
        "BTCUSDT", interval="5min", start_us=None, end_us=NOW_US, limit=10, cursor=None
    )
    assert first.points == () and first.coverage is None  # answered at once, never blocked
    for _ in range(5000):  # yield to the worker; no wall-clock wait
        if len(store) == 261:
            break
        await asyncio.sleep(0)
    await runtime.stop()
    await runtime.stop()
    assert len(store) == 261 and len(seen) == 2  # 260 rest rows, 1 ticker row
    assert runtime.backfill is not None and runtime.backfill.keys() == [("BTCUSDT", "5min")]
    assert runtime.refresh_once() == 1


async def test_compose_fake_backend_has_no_fetcher_and_real_builds_questdb_store_on_use() -> None:
    ctx = await _started()
    fake = _compose_open_interest(ctx, Settings(), None)
    assert isinstance(fake, OiRuntime) and fake.backfill is None and fake.refresh_once() == 0

    class _Writer:
        def __init__(self) -> None:
            self.rows: list[dict[str, object]] = []

        async def write_rows(self, table: str, rows: list[dict[str, object]], key: str) -> None:
            self.rows.extend(rows)

    writer = _Writer()
    real = _compose_open_interest(ctx, Settings(storage_backend="real"), None)
    with pytest.raises(StorageTierUnavailable):  # the fake repository is no QuestDB one
        await real._store.coverage("BTCUSDT", "1s", "ws_ticker")
    ctx.storage._market_data = QuestDbMarketDataRepository(writer, None)  # type: ignore[arg-type]
    assert await real.on_ticker(_tick(NOW_US)) and writer.rows[0]["source"] == "ws_ticker"


def test_create_app_mounts_open_interest_and_sets_the_runtime() -> None:
    app = create_app(Settings())
    assert isinstance(app.state.oi_runtime, OiRuntime)
    paths, todo = set(), list(app.routes)
    while todo:  # routers are included lazily: walk each one's own routes
        route = todo.pop()
        paths.add(getattr(route, "path", ""))
        todo.extend(getattr(getattr(route, "original_router", None), "routes", []))
    assert any(p.endswith("/market/open-interest") for p in paths)
