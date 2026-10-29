"""E22-T02 (#654) Gherkin "REST and WS agree": one recorded tape (packages/fixtures, 2026-10-05
`clean_publicTrade_BTCUSDT`) replayed live into `trades.BTCUSDT` and read back over
`GET /market/trades` with identical options gives the same flagged prints and the same cluster
membership. No network: the replay offers the recorded batches to the topic by hand."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api._generated.openapi_models import PublicTrade, TradesPageMeta
from candleviewer.api.trades import make_trades_router
from candleviewer.orderflow.bigtrade_models import BigTradeConfig
from tests._bigtrades import Tape, World, recorded_batches

#: Small enough that the recorded BTCUSDT tape has big prints (its sizes run 0.001 to ~1 BTC).
_CONFIG = BigTradeConfig("absolute_size", Decimal("0.05"))
_OPTIONS: list[dict[str, Any]] = [
    {},
    {"min_size": "0.002"},
    {"cluster_window_ms": 250, "cluster_tolerance_ticks": 1},
    {"min_size": "0.002", "cluster_window_ms": 2000, "cluster_tolerance_ticks": 20},
]


class _Owner:
    def has(self, permission: str) -> bool:
        return permission == "marketdata:read"


class _Resolver:
    async def resolve(self, request: Request) -> Any:
        return _Owner()


def _rest(tape: Tape, opts: dict[str, Any]) -> list[dict[str, Any]]:
    app = FastAPI()
    app.include_router(
        make_trades_router(
            lambda: tape,
            principal_resolver=_Resolver(),
            min_size_floor=lambda _s: Decimal("0.001"),
            config=lambda _s: _CONFIG,
        )
    )
    client = TestClient(app)
    items: list[dict[str, Any]] = []
    params: dict[str, Any] = {"symbol": "BTCUSDT", "limit": 500, **opts}
    while True:
        page = client.get("/market/trades", params=params).json()
        TradesPageMeta.model_validate(page["meta"])
        items += [PublicTrade.model_validate(i).model_dump(mode="json") for i in page["items"]]
        if not page["meta"]["has_more"]:
            return items
        params["cursor"] = page["meta"]["next_cursor"]


def _ws(opts: dict[str, Any]) -> list[dict[str, Any]]:
    batches = recorded_batches()
    world = World(config=_CONFIG)
    conn = world.conn()
    _, sub = world.sub(conn, {**opts, "encoding": "structured"})
    assert sub is not None
    conn.take()
    for batch in batches:
        world.now_us = batch[-1].ts_event  # the reader's clock follows the tape
        world.window(batch)
    world.now_us = batches[-1][-1].ts_event + 10_000_000  # every cluster closes
    world.window()
    return [t for f in conn.take() if f["t"] == "d" for t in f["p"]["trades"]]


def _membership(items: list[dict[str, Any]]) -> list[tuple[str, int, Decimal, bool]]:
    return sorted(
        (i["id"], i["cluster_size"], Decimal(i["size"]), i["is_big_trade"]) for i in items
    )


@pytest.mark.parametrize("opts", _OPTIONS, ids=["plain", "min_size", "clustered", "both"])
def test_rest_and_ws_agree_on_flagged_prints_and_cluster_membership(opts: dict[str, Any]) -> None:
    tape = Tape([e for batch in recorded_batches() for e in batch])
    assert 0 < len(tape.recent("BTCUSDT")) <= 1000  # the hot tape REST reads holds it all
    ws, rest = _ws(opts), _rest(tape, opts)
    assert _membership(ws) == _membership(rest)
    flagged = {i["id"] for i in ws if i["is_big_trade"]}
    assert flagged and flagged == {i["id"] for i in rest if i["is_big_trade"]}
    if "cluster_window_ms" in opts:
        assert any(i["cluster_size"] > 1 for i in ws)
