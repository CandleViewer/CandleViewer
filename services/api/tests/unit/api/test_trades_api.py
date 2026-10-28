"""E08-S04 `GET /market/trades` contract + RBAC (no network)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api._generated.openapi_models import Page, PublicTrade, TradesPageMeta
from candleviewer.api.trades import make_trades_router
from candleviewer.exchange.base.models import TradeEvent
from candleviewer.ingestion.ticker_stream import uuid7
from candleviewer.orderflow.bigtrade_metrics import bigtrade_range_rejected_total
from candleviewer.orderflow.bigtrade_models import BigTradeConfig


def _ev(i: int, side: str, qty: str) -> TradeEvent:
    ts = 1_700_000_000_000_000 + i * 1000
    return TradeEvent.model_validate(
        {
            "event_id": uuid7(ts // 1000),
            "ts_event": ts,
            "ts_ingest": ts,
            "source": "live",
            "symbol": "BTCUSDT",
            "trade_id": f"t{i}",
            "price": Decimal("63120.5"),
            "qty": Decimal(qty),
            "side": side,
            "is_block_trade": False,
            "price_ticks": 0,
            "notional": Decimal("1"),
            "seq": i,
        }
    )


class Reader:
    def __init__(self) -> None:
        self.acquired: list[tuple[str, str]] = []

    def acquire(self, consumer: str, symbol: str) -> None:
        self.acquired.append((consumer, symbol))

    def release(self, consumer: str, symbol: str) -> None:
        pass

    def tick_size(self, symbol: str) -> Decimal | None:
        return Decimal("0.1")

    def recent(self, symbol: str) -> list[TradeEvent]:
        return [_ev(1, "buy", "0.1"), _ev(2, "sell", "2"), _ev(3, "buy", "5")]

    def is_listed(self, symbol: str) -> bool:
        return symbol == "BTCUSDT"


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
_READER = Reader()


def _client(
    principal: Principal | None = _OK,
    reader: Any = _READER,
    config: BigTradeConfig | None = None,
) -> TestClient:
    app = FastAPI()
    router = make_trades_router(
        lambda: reader,
        principal_resolver=Resolver(principal),
        min_size_floor=lambda s: Decimal("0.001") if s == "BTCUSDT" else None,
        config=lambda _s: config or BigTradeConfig(),
    )
    app.include_router(router)
    return TestClient(app)


def test_get_trades_newest_first_matches_openapi_schema() -> None:
    r = _client().get("/market/trades", params={"symbol": "BTCUSDT", "limit": 2})
    assert r.status_code == 200
    body = r.json()
    Page.model_validate(body)
    items = [PublicTrade.model_validate(i) for i in body["items"]]
    assert [i.id for i in items] == ["t3", "t2"]
    assert body["meta"]["has_more"] is True and body["meta"]["count"] == 2
    assert body["meta"]["next_cursor"]


def test_get_trades_filters_side_min_size_and_window() -> None:
    c = _client()
    r = c.get("/market/trades", params={"symbol": "btcusdt", "side": "buy", "min_size": "1"})
    assert [i["id"] for i in r.json()["items"]] == ["t3"]
    r = c.get(
        "/market/trades",
        params={
            "symbol": "BTCUSDT",
            "from": "2023-11-14T22:13:20.002Z",
            "to": "2023-11-14T22:13:20.003Z",
        },
    )
    assert [i["id"] for i in r.json()["items"]] == ["t2"]


@pytest.mark.parametrize(
    ("principal", "params", "status"),
    [
        (None, {"symbol": "BTCUSDT"}, 401),
        (Principal(False), {"symbol": "BTCUSDT"}, 403),
        (Principal(True), {"symbol": "BAD*"}, 400),
        (Principal(True), {"symbol": "BTCUSDT", "from": "nope"}, 400),
        (Principal(True), {"symbol": "BTCUSDT", "from": "2023-11-14T22:13:20"}, 400),
        (Principal(True), {"symbol": "ETHUSDT"}, 404),
    ],
)
def test_get_trades_error_paths(principal: Principal | None, params: Any, status: int) -> None:
    assert _client(principal).get("/market/trades", params=params).status_code == status


def test_get_trades_unwired_is_501_or_503() -> None:
    app = FastAPI()
    app.include_router(make_trades_router(lambda: None))
    assert TestClient(app).get("/market/trades?symbol=BTCUSDT").status_code == 501
    assert _client(reader=None).get("/market/trades?symbol=BTCUSDT").status_code == 503


def test_get_trades_acquires_demand_so_tape_fills() -> None:
    reader = Reader()
    _client(reader=reader).get("/market/trades?symbol=BTCUSDT")
    assert reader.acquired == [("rest-tape", "BTCUSDT")]


def test_get_trades_cursor_pages_without_overlap() -> None:
    c = _client()
    p1 = c.get("/market/trades", params={"symbol": "BTCUSDT", "limit": 2}).json()
    assert p1["meta"]["has_more"] is True
    p2 = c.get(
        "/market/trades",
        params={"symbol": "BTCUSDT", "limit": 2, "cursor": p1["meta"]["next_cursor"]},
    ).json()
    assert [i["id"] for i in p2["items"]] == ["t1"]
    assert p2["meta"] == {
        "next_cursor": None,
        "has_more": False,
        "count": 1,
        "big_trade_threshold": "250000",
        "big_trade_mode": "notional",
    }
    TradesPageMeta.model_validate(p2["meta"])
    assert c.get("/market/trades", params={"symbol": "BTCUSDT", "cursor": "!!"}).status_code == 400


def test_get_trades_clusters_same_side_same_price_in_window() -> None:
    # t1 buy@t0, t3 buy@t+2ms (same price): merged; t2 sell stays alone.
    r = _client().get("/market/trades", params={"symbol": "BTCUSDT", "cluster_window_ms": 10})
    body = r.json()
    Page.model_validate(body)
    by_id = {i["id"]: i for i in body["items"]}
    assert by_id["t1"]["cluster_size"] == 2 and by_id["t1"]["size"] == "5.1"
    assert by_id["t2"]["cluster_size"] == 1
    assert "t3" not in by_id


def test_get_trades_derives_tick_direction() -> None:
    items = _client().get("/market/trades?symbol=BTCUSDT").json()["items"]
    assert all(PublicTrade.model_validate(i) for i in items)
    assert items[0]["tick_direction"] == "ZeroPlusTick"


# -- E22-T02 (#654): the bounds, the flag and the threshold -------------------------------------


def _rejected() -> float:
    return float(bigtrade_range_rejected_total.labels("trades")._value.get())


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({"from": "2023-11-14T00:00:00Z", "to": "2023-11-14T06:00:00.001Z"}, "invalid_time_range"),
        (
            {"from": "2023-11-14T00:00:00Z", "to": "2023-11-14T00:15:00.001Z",
             "cluster_window_ms": 2001},
            "invalid_time_range",
        ),
        ({"from": "2023-11-14T01:00:00Z", "to": "2023-11-14T00:00:00Z"}, "invalid_time_range"),
        ({"min_size": "0.0001"}, "invalid_min_size"),
        ({"min_size": "0"}, "invalid_min_size"),
        ({"min_size": "-1"}, "invalid_min_size"),
        ({"min_size": "NaN"}, "invalid_min_size"),
    ],
)  # fmt: skip
def test_get_trades_refuses_out_of_bound_reads_before_reading(
    params: dict[str, Any], code: str
) -> None:
    """SR-E22-01 (6 h, or 15 min past a 2 000 ms cluster window) and SR-E22-03 (the floor): 400
    with the 22 code, counted in `bigtrade_range_rejected_total`."""
    reader = Reader()
    before = _rejected()
    r = _client(reader=reader).get("/market/trades", params={"symbol": "BTCUSDT", **params})
    assert r.status_code == 400 and r.json()["code"] == code
    assert _rejected() - before == 1
    assert reader.acquired == []  # nothing was read, no demand taken


def test_get_trades_keeps_its_bounds_at_their_edges() -> None:
    c = _client()
    edge = {"symbol": "BTCUSDT", "from": "2023-11-14T00:00:00Z", "to": "2023-11-14T06:00:00Z"}
    assert c.get("/market/trades", params=edge).status_code == 200
    wide = {**edge, "to": "2023-11-14T00:15:00Z", "cluster_window_ms": 5000}
    assert c.get("/market/trades", params=wide).status_code == 200
    assert c.get("/market/trades", params={**edge, "min_size": "0.001"}).status_code == 200
    for params in ({"limit": 501}, {"cluster_window_ms": 5001}, {"cluster_tolerance_ticks": 21}):
        assert c.get("/market/trades", params={"symbol": "BTCUSDT", **params}).status_code == 422


def test_get_trades_floor_unknown_refuses_a_min_size() -> None:
    class Unlisted(Reader):
        def is_listed(self, symbol: str) -> bool:
            return True

    r = _client(reader=Unlisted()).get("/market/trades?symbol=XRPUSDT&min_size=1")
    assert r.status_code == 400 and r.json()["code"] == "invalid_min_size"


def test_get_trades_flags_big_trades_and_returns_the_threshold_in_meta() -> None:
    """`is_big_trade` is the engine's flag; on a cluster, any member's (22 `PublicTrade`)."""
    c = _client(config=BigTradeConfig("absolute_size", Decimal("3")))
    body = c.get("/market/trades", params={"symbol": "BTCUSDT"}).json()
    assert {i["id"]: i["is_big_trade"] for i in body["items"]} == {
        "t3": True, "t2": False, "t1": False
    }  # fmt: skip
    assert all(i["is_liquidation"] is False for i in body["items"])
    meta = TradesPageMeta.model_validate(body["meta"])
    assert (meta.big_trade_threshold, meta.big_trade_mode) == ("3", "absolute_size")
    clustered = c.get("/market/trades", params={"symbol": "BTCUSDT", "cluster_window_ms": 10})
    by_id = {i["id"]: i for i in clustered.json()["items"]}
    assert (by_id["t1"]["cluster_size"], by_id["t1"]["is_big_trade"]) == (2, True)


def test_get_trades_min_size_drops_prints_before_clustering() -> None:
    """t1 (0.1) is dropped before clustering, so t3 (5) clusters alone (22 `min_size`)."""
    c = _client()
    params = {"symbol": "BTCUSDT", "cluster_window_ms": 10, "min_size": "1"}
    items = c.get("/market/trades", params=params).json()["items"]
    assert [(i["id"], i["cluster_size"], i["size"]) for i in items] == [
        ("t3", 1, "5"), ("t2", 1, "2")
    ]  # fmt: skip


def test_get_trades_unknown_tick_size_is_503() -> None:
    class NoTick(Reader):
        def tick_size(self, symbol: str) -> Decimal | None:
            return None

    assert _client(reader=NoTick()).get("/market/trades?symbol=BTCUSDT").status_code == 503
