"""E08-S05 `GET /market/orderbook` contract + RBAC (no network)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api._generated.openapi_models import OrderbookSnapshot
from candleviewer.api.orderbook import make_orderbook_router
from candleviewer.exchange.base.models import BookSnapshot
from candleviewer.orderbook_wiring import BookView
from tests.unit.book._builders import lvl, snap


class Reader:
    def __init__(self, live: bool = True) -> None:
        self.live = live
        self.acquired: list[tuple[str, str]] = []

    def acquire(self, consumer: str, symbol: str) -> None:
        self.acquired.append((consumer, symbol))

    def release(self, consumer: str, symbol: str) -> None:
        pass

    def is_listed(self, symbol: str) -> bool:
        return symbol == "BTCUSDT"

    def view(self, symbol: str, depth: int) -> BookView | None:
        s: BookSnapshot = snap(7, [lvl(631204, "12.5")], [lvl(631206, "9.87")], depth=depth)
        return BookView(s, stale=False) if self.live else None


class Principal:
    def __init__(self, ok: bool) -> None:
        self.ok = ok

    def has(self, permission: str) -> bool:
        return self.ok and permission == "marketdata:read"


class Resolver:
    def __init__(self, principal: Principal | None) -> None:
        self.principal = principal

    async def resolve(self, request: Request) -> Any:
        return self.principal


_OK = Principal(True)


def _client(principal: Principal | None = _OK, reader: Reader | None = None) -> TestClient:
    app = FastAPI()
    rd = reader if reader is not None else Reader()
    app.include_router(make_orderbook_router(lambda: rd, principal_resolver=Resolver(principal)))
    return TestClient(app)


def test_orderbook_matches_openapi_schema() -> None:
    r = _client().get("/market/orderbook", params={"symbol": "btcusdt", "depth": 50})
    assert r.status_code == 200
    body = r.json()
    OrderbookSnapshot.model_validate(body)
    assert body["bids"] == [["63120.4", "12.5"]] and body["u"] == 7 and body["stale"] is False


def test_orderbook_503_while_resyncing_never_a_patched_book() -> None:
    r = _client(reader=Reader(live=False)).get("/market/orderbook", params={"symbol": "BTCUSDT"})
    assert r.status_code == 503


def test_orderbook_rbac_and_validation() -> None:
    assert _client(None).get("/market/orderbook", params={"symbol": "BTCUSDT"}).status_code == 401
    assert (
        _client(Principal(False)).get("/market/orderbook", params={"symbol": "BTCUSDT"})
    ).status_code == 403
    assert _client().get("/market/orderbook", params={"symbol": "NOPEUSDT"}).status_code == 404
    assert (
        _client().get("/market/orderbook", params={"symbol": "BTCUSDT", "depth": 7}).status_code
        == 422
    )
