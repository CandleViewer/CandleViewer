"""E24-T02-F1: FundingService composed via funding_wiring; recorded fixtures, no network."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api.funding import make_funding_router
from candleviewer.app import AppContext, _compose_funding, build_app_context, create_app
from candleviewer.domain.funding import FundingRowRejected
from candleviewer.exchange.bybit.config import RestClientConfig
from candleviewer.exchange.bybit.funding import BybitFundingFetcher
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor
from candleviewer.exchange.bybit.rest import BybitRestClient
from candleviewer.funding_wiring import FundingRefreshTask, wire_funding
from candleviewer.settings import Settings
from candleviewer.storage.questdb.funding_store import InMemoryFundingStore

FIX = Path(__file__).resolve().parents[5] / "packages/fixtures/bybit/2026-10-05/rest"
NOW_US = 1_700_030_000_000_000


@dataclass(frozen=True)
class _Inst:
    symbol: str
    funding_interval_min: int
    status: str = "trading"


class _Snap:
    def __init__(self, items: list[_Inst]) -> None:
        self._m = {i.symbol: i for i in items}

    def get(self, s: str) -> _Inst | None:
        return self._m.get(s)

    def listing(self) -> list[_Inst]:
        return list(self._m.values())


class _Sched:
    def snapshot(self) -> _Snap:
        return _Snap([_Inst("ETHUSDT", 240)])


class _Principal:
    def has(self, permission: str) -> bool:
        return True


class _Resolver:
    def resolve(self, request: Request) -> _Principal:
        return _Principal()


def _client() -> BybitRestClient:
    body = json.loads((FIX / "funding_history_ETHUSDT_4h.json").read_text(encoding="utf-8"))
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json=body))
    return BybitRestClient(
        RestClientConfig(base_url="https://api.bybit.com"),
        governor=TokenBucketGovernor(),
        transport=transport,
    )


async def _started() -> AppContext:
    ctx = build_app_context(Settings())
    await ctx.storage.start(ctx)
    ctx.ingestion.instruments = _Sched()  # type: ignore[assignment]
    return ctx


def _http(ctx: AppContext) -> TestClient:
    app = FastAPI()
    router = make_funding_router(lambda: ctx.orderflow.funding, principal_resolver=_Resolver())
    app.include_router(router)
    return TestClient(app)


async def test_refresh_then_get_funding_returns_items_and_interval() -> None:
    ctx = await _started()
    client = _client()
    task = wire_funding(
        ctx,
        store=InMemoryFundingStore(),
        fetcher=BybitFundingFetcher(client),
        closer=client.aclose,
        now_us=lambda: NOW_US,
    )
    assert isinstance(task, FundingRefreshTask)
    assert await task.run_once() == 1
    resp = await asyncio.to_thread(
        _http(ctx).get,
        "/market/funding",
        params={"symbol": "ETHUSDT", "from": "2023-11-14T00:00:00Z", "to": "2023-11-16T00:00:00Z"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["funding_interval_minutes"] == 240
    assert len(body["items"]) == 4
    await task.stop()


async def test_hot_tier_outage_is_503_not_500() -> None:
    ctx = build_app_context(Settings())  # storage never started -> StorageTierUnavailable
    ctx.ingestion.instruments = _Sched()  # type: ignore[assignment]
    wire_funding(ctx, store=InMemoryFundingStore(), fetcher=None, now_us=lambda: NOW_US)
    resp = await asyncio.to_thread(_http(ctx).get, "/market/funding", params={"symbol": "ETHUSDT"})
    assert resp.status_code == 503


async def test_rejected_page_is_skipped_not_fatal() -> None:
    ctx = await _started()
    calls: list[str] = []

    async def fetcher(symbol: str, s: int, e: int, limit: int) -> Any:
        calls.append(symbol)
        raise FundingRowRejected("bad page", "envelope")

    task = wire_funding(ctx, store=InMemoryFundingStore(), fetcher=fetcher, now_us=lambda: NOW_US)
    assert task is not None
    assert await task.run_once() == 0
    assert calls == ["ETHUSDT"]


async def test_refresh_task_started_then_stopped_sleeps_jittered_interval_and_closes() -> None:
    ctx = await _started()
    sleeps: list[float] = []
    closed: list[bool] = []

    async def fetcher(symbol: str, s: int, e: int, limit: int) -> Any:
        return []

    slept = asyncio.Event()

    async def sleep(d: float) -> None:
        slept.set()
        sleeps.append(d)
        await asyncio.Event().wait()

    async def closer() -> None:
        closed.append(True)

    task = wire_funding(
        ctx, store=InMemoryFundingStore(), fetcher=fetcher, closer=closer, now_us=lambda: NOW_US
    )
    assert task is not None
    task._sleep = sleep  # type: ignore[method-assign]
    task._random = lambda: 0.5  # type: ignore[method-assign]
    task.start()
    await asyncio.wait_for(slept.wait(), 2)
    assert sleeps == [3600 * 1.05]
    await task.stop()
    assert not task.running
    assert closed == [True]


def test_create_app_fake_backend_wires_funding_without_network() -> None:
    app = create_app()
    assert app.state.app_context.orderflow.funding is not None
    assert app.state.funding_refresh_task is None


async def test_refresh_task_total_failure_backs_off_exponentially_to_interval_cap() -> None:
    ctx = await _started()
    sleeps: list[float] = []
    calls: list[int] = []

    async def fetcher(symbol: str, s: int, e: int, limit: int) -> Any:
        calls.append(s)
        raise FundingRowRejected("bad page", "envelope")

    task = wire_funding(ctx, store=InMemoryFundingStore(), fetcher=fetcher, now_us=lambda: NOW_US)
    assert task is not None
    task._random = lambda: 0.0  # type: ignore[method-assign]
    done = asyncio.Event()

    async def sleep(d: float) -> None:
        sleeps.append(d)
        if len(sleeps) >= 8:
            done.set()
            await asyncio.Event().wait()

    task._sleep = sleep  # type: ignore[method-assign]
    task.start()
    await asyncio.wait_for(done.wait(), 2)
    await task.stop()
    assert sleeps == [30.0, 60.0, 120.0, 240.0, 480.0, 960.0, 1920.0, 3600.0]
    # deep backfill retried every pass (first window is the full 30 days each time)
    assert set(calls) == {NOW_US - 30 * 86_400 * 1_000_000}


async def test_run_once_after_success_switches_to_recent_window() -> None:
    ctx = await _started()
    starts: list[int] = []

    async def fetcher(symbol: str, s: int, e: int, limit: int) -> Any:
        starts.append(s)
        return []

    task = wire_funding(ctx, store=InMemoryFundingStore(), fetcher=fetcher, now_us=lambda: NOW_US)
    assert task is not None
    await task.run_once()
    await task.run_once()
    assert starts == [NOW_US - 30 * 86_400 * 1_000_000, NOW_US - 2 * 86_400 * 1_000_000]


async def test_compose_funding_real_backend_without_store_spawns_no_task_and_serves_503() -> None:
    ctx = await _started()
    task = _compose_funding(ctx, Settings(storage_backend="real"))
    assert task is None
    resp = await asyncio.to_thread(_http(ctx).get, "/market/funding", params={"symbol": "ETHUSDT"})
    assert resp.status_code == 503
