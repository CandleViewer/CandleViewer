"""E08-S04 end-to-end through the real `create_app` wiring: frame pump -> TradeStream ->
bus -> `GET /market/trades`, demand via the REST read, write-behind into the storage
repository, and the reconnect gap via the real bus health topic. No network."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.api.trades import make_trades_router
from candleviewer.app import create_app
from candleviewer.bus.models import Topic
from candleviewer.ingestion.watchdog import feed_health
from candleviewer.settings import Settings
from candleviewer.storage.repositories.rows import TradeRow
from candleviewer.storage.testing.fakes import FakeMarketDataRepository
from tests._corpus import corpus_path

FRAMES = corpus_path("ws/publicTrade_BTCUSDT.jsonl").read_text(encoding="utf-8").splitlines()


class _Principal:
    def has(self, permission: str) -> bool:
        return permission == "marketdata:read"


class _Resolver:
    async def resolve(self, request: Any) -> Any:
        return _Principal()


def _app_with_catalogue() -> Any:
    app = create_app(Settings(ingestion_ws_enabled=True))
    ctx = app.state.app_context
    assert (
        TestClient(app, client=("127.0.0.1", 50000))
        .get("/market/trades?symbol=BTCUSDT")
        .status_code
        == 501
    )  # mounted by create_app, fail-closed without identity
    inst = SimpleNamespace(status="trading", tick_size=Decimal("0.1"), launch_time=0)
    ctx.ingestion.instruments = SimpleNamespace(
        snapshot=lambda: SimpleNamespace(get=lambda s: inst if s == "BTCUSDT" else None)
    )
    ctx.storage._market_data = FakeMarketDataRepository()
    # create_app mounts the route fail-closed (501, no identity on the fake backend);
    # serve the same router over the app's real ingestion context with a stub principal.
    served = FastAPI()
    served.include_router(
        make_trades_router(lambda: ctx.ingestion.trades, principal_resolver=_Resolver())
    )
    app = served
    return app, ctx


async def test_rest_read_acquires_topic_and_frames_fill_the_tape() -> None:
    app, ctx = _app_with_catalogue()
    ing = ctx.ingestion
    desired: list[set[str]] = []
    ing.ws.set_desired = lambda t: desired.append(set(t))  # type: ignore[method-assign]
    await ing.trades.start()
    pump = asyncio.create_task(ing._pump_frames())
    try:
        client = TestClient(app, client=("127.0.0.1", 50000))
        r = await asyncio.to_thread(client.get, "/market/trades?symbol=BTCUSDT")
        assert r.status_code == 200, r.text
        assert r.json()["items"] == []
        assert desired and desired[-1] == {"publicTrade.BTCUSDT"}  # demand reached the socket
        for f in FRAMES:
            ing.offer_frame(f)
        for _ in range(100):
            if len(ing.trades.recent("BTCUSDT")) >= 4:
                break
            await asyncio.sleep(0.01)
        body = (await asyncio.to_thread(client.get, "/market/trades?symbol=BTCUSDT")).json()
        ids = [i["id"] for i in body["items"]]
        assert len(ids) == len(set(ids)) >= 4, ids
        # write-behind reaches the storage repository through the app's real writer
        repo: FakeMarketDataRepository = ctx.storage._market_data
        for _ in range(100):  # the started write-behind loop drains the queue
            if len(repo._trades) >= len(ids):
                break
            await asyncio.sleep(0.01)
        assert len(repo._trades) == len(ids) and all(
            isinstance(v, TradeRow) for v in repo._trades.values()
        )
    finally:
        pump.cancel()
        await ing.trades.stop()


async def test_real_bus_health_event_marks_gap() -> None:
    _app, ctx = _app_with_catalogue()
    ing = ctx.ingestion
    await ing.trades.start()
    try:
        ing.trades.acquire("t", "BTCUSDT")
        ing.offer_frame(FRAMES[0])
        await ing.trades.handle_frame(await ing.ws_frames.get())
        topic = Topic(env=ctx.settings.environment.value, domain="health", detail="feed")
        await ctx.bus.bus.publish(
            topic, feed_health("publicTrade.BTCUSDT", "resubscribing", 0.0, now_us=0)
        )
        for _ in range(100):
            if ing.trades.open_gaps():
                break
            await asyncio.sleep(0.01)
        assert "BTCUSDT" in ing.trades.open_gaps()
    finally:
        await ing.trades.stop()
