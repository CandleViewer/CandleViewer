"""E24-T03 (#667): `GET /market/liquidations` against the contract, RBAC and the bounds."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import jsonschema
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.liquidations import make_liquidations_router
from candleviewer.domain.liquidations import LiqPrint
from candleviewer.orderflow.funding_metrics import deriv_range_rejected_total
from candleviewer.orderflow.liquidations import LiquidationService
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.questdb.liquidation_store import InMemoryLiquidationStore

S = 1_000_000
T0 = 1_757_844_000 * S  # 2025-09-14T10:00:00Z
NOW_S = T0 / S + 3600
URL = "/market/liquidations"


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


class _SpyStore(InMemoryLiquidationStore):
    """Counts every query, so a refused request provably issued none."""

    def __init__(self) -> None:
        super().__init__()
        self.queries = 0

    async def first_ts(self, symbol: str) -> int | None:
        self.queries += 1
        return await super().first_ts(symbol)

    async def read_prints(self, *a: Any, **kw: Any) -> list[LiqPrint]:
        self.queries += 1
        return await super().read_prints(*a, **kw)


class _Down:
    async def page(self, symbol: str, **kw: object) -> object:
        raise StorageTierUnavailable("down")


_OK = _Principal(frozenset({"marketdata:read"}))


async def _seeded() -> _SpyStore:
    store = _SpyStore()
    px, size = Decimal("62880.00"), Decimal("3.220")
    await store.write_prints(
        [LiqPrint(T0 + 764_120_000 + k * 200_000, "BTCUSDT", "sell", px, size, px * size, k)
         for k in range(3)]
        + [LiqPrint(T0 + 900 * S, "BTCUSDT", "buy", px, size, px * size, 0)]
    )  # fmt: skip
    store.queries = 0
    return store


def _client(
    reader: object | None, principal: _Principal | None = _OK, *, resolver: bool = True
) -> TestClient:
    app = FastAPI()
    app.include_router(
        make_liquidations_router(
            lambda: reader,  # type: ignore[arg-type,return-value]  # structural fakes
            principal_resolver=_Resolver(principal) if resolver else None,
        )
    )
    return TestClient(app)


def _service(store: InMemoryLiquidationStore, listed: bool | None = True) -> LiquidationService:
    return LiquidationService(store=store, listed=lambda s: listed, clock_s=lambda: NOW_S)


def _schema(status: str) -> object:
    spec: Any = load_openapi_spec()
    op = spec["paths"][URL]["get"]["responses"][status]
    comps = spec["components"]["schemas"]

    def deref(node: object) -> object:
        if isinstance(node, dict):
            if "$ref" in node:
                return deref(comps[node["$ref"].rsplit("/", 1)[1]])
            return {k: deref(v) for k, v in node.items() if k != "examples"}
        if isinstance(node, list):
            return [deref(v) for v in node]
        return node

    return deref(op["content"]["application/json"]["schema"])


_PARAMS = {"symbol": "BTCUSDT", "from": "2025-09-14T10:00:00Z", "to": "2025-09-14T11:00:00Z"}


async def test_liquidations_response_validates_against_openapi_with_coverage() -> None:
    body = _client(_service(await _seeded())).get(URL, params=_PARAMS).json()
    jsonschema.validate(body, _schema("200"))  # type: ignore[arg-type]
    assert body["items"][0] == {
        "ts": "2025-09-14T10:12:44.120000Z", "symbol": "BTCUSDT", "side": "sell",
        "price": "62880.00", "size": "3.220", "notional_usd": "202473.60000", "cluster_size": 1,
    }  # fmt: skip
    meta = body["meta"]
    assert (meta["next_cursor"], meta["has_more"], meta["count"]) == (None, False, 4)
    assert meta["coverage"] == {
        "first_available_ts": "2025-09-14T10:12:44.120000Z",
        "covered_from": "2025-09-14T10:12:44.120000Z",
        "covered_to": "2025-09-14T11:00:00Z",
        "no_coverage": False,
    }


async def test_liquidations_cluster_side_and_paging_over_http() -> None:
    client = _client(_service(await _seeded()))
    one = client.get(URL, params={**_PARAMS, "cluster_window_ms": 1000, "side": "sell"}).json()
    assert [(i["cluster_size"], i["size"]) for i in one["items"]] == [(3, "9.660")]
    assert "estimated" not in str(one)
    first = client.get(URL, params={**_PARAMS, "limit": 3}).json()
    assert first["meta"]["has_more"] and first["meta"]["count"] == 3
    rest = client.get(URL, params={**_PARAMS, "cursor": first["meta"]["next_cursor"]}).json()
    assert [i["side"] for i in rest["items"]] == ["buy"] and not rest["meta"]["has_more"]


async def test_liquidations_window_before_first_record_reports_no_coverage() -> None:
    params = {**_PARAMS, "from": "2025-09-14T09:00:00Z", "to": "2025-09-14T10:00:00Z"}
    body = _client(_service(await _seeded())).get(URL, params=params).json()
    jsonschema.validate(body, _schema("200"))  # type: ignore[arg-type]
    assert body["items"] == [] and body["meta"]["coverage"]["no_coverage"] is True
    assert body["meta"]["coverage"]["first_available_ts"] == "2025-09-14T10:12:44.120000Z"


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({"from": "2025-08-01T00:00:00Z"}, "invalid_time_range"),
        ({"from": "2025-09-14T12:00:00Z"}, "invalid_time_range"),
        ({"from": "garbage"}, "invalid_time_range"),
        ({"limit": 501}, "validation_failed"),
        ({"limit": "x"}, "validation_failed"),
        ({"cluster_window_ms": 60_001}, "validation_failed"),
        ({"cluster_window_ms": -1}, "validation_failed"),
        ({"min_notional_usd": "lots"}, "validation_failed"),
        ({"min_notional_usd": "1" * 40}, "validation_failed"),
        ({"side": "long"}, "validation_failed"),
        ({"symbol": "btc/usdt"}, "validation_failed"),
        ({"cursor": "a" * 600}, "invalid_cursor"),
    ],
)
async def test_liquidations_bad_request_returns_400_and_issues_no_query(
    params: dict[str, object], code: str
) -> None:
    store = await _seeded()
    before = deriv_range_rejected_total.labels(endpoint="liquidations")._value.get()
    r = _client(_service(store)).get(URL, params={**_PARAMS, **params})
    assert (r.status_code, r.json()["code"]) == (400, code)
    assert r.headers["content-type"].startswith("application/problem+json")
    assert store.queries == 0
    assert deriv_range_rejected_total.labels(endpoint="liquidations")._value.get() == before + 1


async def test_liquidations_unlisted_symbol_is_422_and_unwired_or_down_is_503() -> None:
    store = await _seeded()
    r = _client(_service(store, listed=False)).get(URL, params=_PARAMS)
    assert (r.status_code, r.json()["code"], store.queries) == (422, "validation_failed", 0)
    assert _client(None).get(URL, params=_PARAMS).status_code == 503
    assert _client(_Down()).get(URL, params=_PARAMS).status_code == 503


def test_liquidations_401_without_token() -> None:
    store = _SpyStore()
    r = _client(_service(store), None).get(URL, params=_PARAMS)
    assert (r.status_code, r.json()["code"], store.queries) == (401, "unauthenticated", 0)
    assert _client(_service(store), resolver=False).get(URL, params=_PARAMS).status_code == 501


def test_liquidations_403_without_marketdata_read() -> None:
    store = _SpyStore()
    r = _client(_service(store), _Principal(frozenset({"instruments:read"}))).get(
        URL, params=_PARAMS
    )
    assert (r.status_code, r.json()["code"], store.queries) == (403, "forbidden", 0)


def _nan_after(cursor: str) -> str:
    raw = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    raw["a"][2] = "NaN"
    return base64.urlsafe_b64encode(json.dumps(raw).encode()).decode().rstrip("=")


async def test_liquidations_nan_cursor_is_400_invalid_cursor_not_500() -> None:
    """r1 HIGH: a client-edited cursor carrying NaN reached a Decimal compare and 500'd."""
    store = await _seeded()
    client = _client(_service(store))
    first = client.get(URL, params={**_PARAMS, "limit": 1}).json()
    store.queries = 0
    r = client.get(
        URL, params={**_PARAMS, "limit": 1, "cursor": _nan_after(first["meta"]["next_cursor"])}
    )
    assert (r.status_code, r.json()["code"], store.queries) == (400, "invalid_cursor", 0)


def test_liquidations_decimal_fault_below_the_service_is_400_invalid_cursor() -> None:
    class _Faulty:
        async def page(self, symbol: str, **kw: object) -> object:
            raise InvalidOperation("crafted cursor")

    r = _client(_Faulty()).get(URL, params=_PARAMS)
    assert (r.status_code, r.json()["code"]) == (400, "invalid_cursor")
