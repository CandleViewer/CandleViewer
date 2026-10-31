"""E24-T01 (#665): `GET /market/open-interest` against the contract, RBAC and the bounds."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import jsonschema
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.open_interest import make_open_interest_router
from candleviewer.domain.open_interest import OiPoint
from candleviewer.orderflow.funding_metrics import deriv_range_rejected_total
from candleviewer.orderflow.open_interest import OpenInterestService
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.questdb.oi_store import InMemoryOiStore

S = 1_000_000
T0 = 1_757_845_500 * S  # 2025-09-14T10:25:00Z
NOW_S = T0 / S + 600
URL = "/market/open-interest"


@dataclass
class _Principal:
    perms: frozenset[str]

    def has(self, permission: str) -> bool:
        return permission in self.perms


class _Resolver:
    def __init__(self, principal: _Principal | None) -> None:
        self.principal = principal

    def resolve(self, request: Request) -> _Principal | None:
        return self.principal


class _SpyStore(InMemoryOiStore):
    """Counts every query, so a refused request provably issued none."""

    def __init__(self) -> None:
        super().__init__()
        self.queries = 0

    async def coverage(self, symbol: str, interval: str, source: str) -> tuple[int, int] | None:
        self.queries += 1
        return await super().coverage(symbol, interval, source)

    async def read_points(self, *a: Any, **kw: Any) -> list[OiPoint]:
        self.queries += 1
        return await super().read_points(*a, **kw)


class _Down:
    async def series(self, symbol: str, **kw: object) -> object:
        raise StorageTierUnavailable("down")


_OK = _Principal(frozenset({"marketdata:read"}))


async def _seeded() -> _SpyStore:
    store = _SpyStore()
    await store.write_points(
        [OiPoint(T0 + i * 300 * S, "BTCUSDT", Decimal("61180.22") + i, None, "5min", "rest")
         for i in (2, 0, 1)]
        + [OiPoint(T0, "BTCUSDT", Decimal("61180"), Decimal("3861100000"), "1s", "ws_ticker")]
    )  # fmt: skip
    return store


def _client(
    reader: object | None, principal: _Principal | None = _OK, *, resolver: bool = True
) -> TestClient:
    app = FastAPI()
    app.include_router(
        make_open_interest_router(
            lambda: reader,  # type: ignore[arg-type,return-value]  # structural fakes
            principal_resolver=_Resolver(principal) if resolver else None,
        )
    )
    return TestClient(app)


def _service(store: InMemoryOiStore, listed: bool | None = True) -> OpenInterestService:
    return OpenInterestService(
        store=store, listed=lambda s: listed, backfill=None, clock_s=lambda: NOW_S
    )


def _schema(status: str, media: str = "application/json") -> object:
    spec: Any = load_openapi_spec()
    op = spec["paths"][URL]["get"]["responses"][status]
    if "$ref" in op:
        op = spec["components"]["responses"][op["$ref"].rsplit("/", 1)[1]]
    comps = spec["components"]["schemas"]

    def deref(node: object) -> object:
        if isinstance(node, dict):
            if "$ref" in node:
                return deref(comps[node["$ref"].rsplit("/", 1)[1]])
            return {k: deref(v) for k, v in node.items() if k != "examples"}
        if isinstance(node, list):
            return [deref(v) for v in node]
        return node

    return deref(op["content"][media]["schema"])


_PARAMS = {"symbol": "BTCUSDT", "interval": "5min", "from": "2025-09-14T10:00:00Z",
           "to": "2025-09-14T10:40:00Z"}  # fmt: skip


async def test_oi_response_validates_against_openapi_ascending_with_meta() -> None:
    body = _client(_service(await _seeded())).get(URL, params=_PARAMS).json()
    jsonschema.validate(body, _schema("200"))  # type: ignore[arg-type]
    ts = [i["t"] for i in body["items"]]
    assert ts == sorted(ts) and len(ts) == 3
    assert body["items"][0] == {
        "t": "2025-09-14T10:25:00Z", "open_interest": "61180.22", "open_interest_value": None,
        "interval": "5min", "source": "rest",
    }  # fmt: skip
    meta = body["meta"]
    assert (meta["next_cursor"], meta["has_more"], meta["count"]) == (None, False, 3)
    assert meta["coverage"]["native_interval"] == "5min" and meta["coverage"]["source"] == "rest"
    assert meta["coverage"]["gaps"] == [{"from": "2025-09-14T10:00:00Z",
                                         "to": "2025-09-14T10:25:00Z"}]  # fmt: skip


async def test_oi_ticker_series_is_its_own_page_with_the_usd_value() -> None:
    body = _client(_service(await _seeded())).get(URL, params={**_PARAMS, "interval": "1s"}).json()
    jsonschema.validate(body, _schema("200"))  # type: ignore[arg-type]
    assert [(i["source"], i["open_interest_value"]) for i in body["items"]] == [
        ("ws_ticker", "3861100000")
    ]


async def test_oi_paging_reports_next_cursor_and_has_more() -> None:
    client = _client(_service(await _seeded()))
    first = client.get(URL, params={**_PARAMS, "limit": 2}).json()
    assert first["meta"]["has_more"] and first["meta"]["count"] == 2
    rest = client.get(URL, params={**_PARAMS, "cursor": first["meta"]["next_cursor"]}).json()
    assert [i["t"] for i in rest["items"]] == ["2025-09-14T10:35:00Z"]


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({"from": "2024-01-01T00:00:00Z"}, "invalid_time_range"),
        ({"from": "2025-09-14T11:00:00Z"}, "invalid_time_range"),
        ({"from": "garbage"}, "invalid_time_range"),
        ({"limit": 501}, "validation_failed"),
        ({"limit": 0}, "validation_failed"),
        ({"interval": "2h"}, "validation_failed"),
        ({"symbol": "btc/usdt"}, "validation_failed"),
        ({"cursor": "a" * 600}, "invalid_cursor"),
    ],
)
async def test_oi_oversized_range_returns_400_and_issues_no_query(
    params: dict[str, object], code: str
) -> None:
    store = await _seeded()
    before = deriv_range_rejected_total.labels(endpoint="open_interest")._value.get()
    r = _client(_service(store)).get(URL, params={**_PARAMS, **params})
    assert (r.status_code, r.json()["code"]) == (400, code)
    assert r.headers["content-type"].startswith("application/problem+json")
    assert store.queries == 0
    assert deriv_range_rejected_total.labels(endpoint="open_interest")._value.get() == before + 1


async def test_oi_unlisted_symbol_is_422_and_unwired_or_down_is_503() -> None:
    store = await _seeded()
    r = _client(_service(store, listed=False)).get(URL, params=_PARAMS)
    assert (r.status_code, r.json()["code"], store.queries) == (422, "validation_failed", 0)
    assert _client(None).get(URL, params=_PARAMS).status_code == 503
    assert _client(_Down()).get(URL, params=_PARAMS).status_code == 503


def test_oi_401_without_token() -> None:
    store = _SpyStore()
    r = _client(_service(store), None).get(URL, params=_PARAMS)
    assert (r.status_code, r.json()["code"], store.queries) == (401, "unauthenticated", 0)
    assert _client(_service(store), resolver=False).get(URL, params=_PARAMS).status_code == 501


def test_oi_403_without_marketdata_read() -> None:
    store = _SpyStore()
    r = _client(_service(store), _Principal(frozenset({"instruments:read"}))).get(
        URL, params=_PARAMS
    )
    assert (r.status_code, r.json()["code"], store.queries) == (403, "forbidden", 0)
