"""E24-T04 PR B (#723): `GET /market/metrics` (derivatives codes) against the contract, RBAC
and the bounds. In-memory stores and a fake bar source; no network (C-13.5)."""

from __future__ import annotations

import functools
import json
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import jsonschema
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.market_metrics import MAX_METRICS, make_market_metrics_router
from candleviewer.domain.funding import settle
from candleviewer.domain.liquidations import LiqPrint
from candleviewer.domain.open_interest import OiPoint
from candleviewer.orderflow.derivatives import DerivBar, metric_value
from candleviewer.orderflow.derivatives_query import DERIVATIVE_CODES, DerivativesQuery, Window
from candleviewer.orderflow.funding_metrics import deriv_range_rejected_total
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.questdb.funding_store import InMemoryFundingStore
from candleviewer.storage.questdb.liquidation_store import InMemoryLiquidationStore
from candleviewer.storage.questdb.oi_store import InMemoryOiStore

S = 1_000_000
MIN_US = 60 * S
T0 = 1_757_844_900 * S  # 2025-09-14T10:15:00Z
BAR_MS = 15 * 60_000
SYM = "BTCUSDT"
URL = "/market/metrics"
PARAMS = {"symbol": SYM, "param": "15", "from": "2025-09-14T10:15:00Z",
          "to": "2025-09-14T11:00:00Z"}  # fmt: skip


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


@dataclass(frozen=True)
class _Inst:
    funding_interval_min: int = 480


@dataclass(frozen=True)
class _Ticker:
    ts_event: int = T0 + 40 * MIN_US
    last_price: Decimal | None = Decimal("100.5")
    mark_price: Decimal | None = Decimal("100.4")
    index_price: Decimal | None = Decimal("100.0")
    funding_rate: Decimal | None = Decimal("0.0002")
    next_funding_time: int | None = T0 + 60 * MIN_US


class _Tickers:
    def latest(self, symbol: str) -> _Ticker:
        return _Ticker()


class _Reads:
    """Every source read, so a refused request provably issued none."""

    count = 0


class _Bars:
    def __init__(self, down: bool = False) -> None:
        self.down = down

    async def __call__(
        self, symbol: str, interval_ms: int, start_us: int, end_us: int, limit: int
    ) -> Sequence[DerivBar]:
        _Reads.count += 1
        if self.down:
            raise StorageTierUnavailable("down")
        prices = ((100, 101), (101, 100), (100, 100))
        bars = [DerivBar(T0 // 1000 + i * BAR_MS, T0 // 1000 + (i + 1) * BAR_MS,
                         Decimal(o), Decimal(c)) for i, (o, c) in enumerate(prices)]  # fmt: skip
        return [b for b in bars if start_us <= b.start_ms * 1000 < end_us]


class _SpyOi(InMemoryOiStore):
    async def read_points(self, *a: Any, **kw: Any) -> list[OiPoint]:
        _Reads.count += 1
        return await super().read_points(*a, **kw)


_OK = _Principal(frozenset({"marketdata:read"}))


async def _query(*, listed: bool | None = True, down: bool = False) -> DerivativesQuery:
    _Reads.count = 0
    oi, funding, liqs = _SpyOi(), InMemoryFundingStore(), InMemoryLiquidationStore()
    await oi.write_points(
        [OiPoint(T0 + k * 5 * MIN_US, SYM, Decimal(1000 + 10 * k), None, "5min", "rest")
         for k in range(-1, 6)]
    )  # fmt: skip
    await funding.write_settled([settle(SYM, T0 + 60 * MIN_US, Decimal("0.0001"), 480)])
    await liqs.write_prints(
        [LiqPrint(T0 + MIN_US, SYM, "sell", Decimal(1), Decimal(1), Decimal(10), 0),
         LiqPrint(T0 + 16 * MIN_US, SYM, "buy", Decimal(1), Decimal(1), Decimal(5), 0)]
    )  # fmt: skip
    return DerivativesQuery(
        # The in-memory funding store takes the concrete `TimeRange`; `Window` is one.
        bars=_Bars(down), oi=oi, funding=funding, liquidations=liqs,  # type: ignore[arg-type]
        instrument=lambda s: _Inst(), listed=lambda s: listed, tickers=_Tickers,
    )  # fmt: skip


def _client(
    query: DerivativesQuery | None, principal: _Principal | None = _OK, *, resolver: bool = True
) -> TestClient:
    app = FastAPI()
    app.include_router(
        make_market_metrics_router(
            lambda: query,
            principal_resolver=_Resolver(principal) if resolver else None,
            now_us=lambda: T0 + 60 * MIN_US,
        )
    )
    return TestClient(app)


@functools.cache
def _spec() -> Any:
    return load_openapi_spec()  # parsed once: the contract is large


def _schema(status: str, media: str = "application/json") -> object:
    spec: Any = _spec()
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


def _get(client: TestClient, **extra: Any) -> Any:
    return client.get(URL, params={**PARAMS, **extra})


async def test_every_derivatives_code_validates_against_openapi() -> None:
    resp = _get(_client(await _query()), metric=list(DERIVATIVE_CODES))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    jsonschema.validate(body, _schema("200"))  # type: ignore[arg-type]
    assert (body["symbol"], body["bar_type"], body["param"]) == (SYM, "time", "15")
    assert [s["metric"] for s in body["series"]] == list(DERIVATIVE_CODES)
    assert all(s["estimated"] is False for s in body["series"])
    assert all([p["t"] for p in s["points"]] == ["2025-09-14T10:15:00Z", "2025-09-14T10:30:00Z",
               "2025-09-14T10:45:00Z"] for s in body["series"])  # fmt: skip
    assert body["meta"]["count"] == 3 and body["meta"]["has_more"] is False


async def test_series_carry_the_registry_unit_and_resolved_params() -> None:
    body = _get(_client(await _query()), metric=["open_interest_delta", "basis",
                "liquidation_notional", "oi_price_quadrant"]).json()  # fmt: skip
    got = {s["metric"]: (s["unit"], s["params"]) for s in body["series"]}
    assert got == {
        "open_interest_delta": ("qty", {}), "basis": ("price", {"source": "last"}),
        "liquidation_notional": ("notional", {"side": "both"}), "oi_price_quadrant": ("enum", {}),
    }  # fmt: skip


async def test_values_are_the_engine_values_none_and_enum_included() -> None:
    body = _get(_client(await _query()), metric=["open_interest_delta", "oi_price_quadrant",
                "basis", "time_to_funding_ms"]).json()  # fmt: skip
    v = {s["metric"]: [p["v"] for p in s["points"]] for s in body["series"]}
    assert v["open_interest_delta"] == ["20", "20", None]  # bar 3 has no OI sample: never 0
    assert v["oi_price_quadrant"] == ["long_buildup", "short_buildup", None]
    assert v["basis"] == [None, None, "0.5"]
    assert v["time_to_funding_ms"] == [None, None, str(20 * 60_000)]


async def test_one_number_route_equals_the_engine_read_path() -> None:
    """A pane and a rule condition read `metric_value`; the route must say the same."""
    query = await _query()
    rows = await query.compute(
        SYM, query.check_symbol(SYM), interval_ms=BAR_MS, window=Window(T0, T0 + 45 * MIN_US)
    )
    params = json.dumps({"basis": {"source": "mark"}})
    body = _get(_client(query), metric=["open_interest_delta", "basis"], params=params).json()
    for series in body["series"]:
        p = series["params"]
        want = [metric_value(m, series["metric"], p) for m in rows]
        assert [p["v"] for p in series["points"]] == [None if w is None else str(w) for w in want]


async def test_alias_codes_read_their_descriptor() -> None:
    body = _get(_client(await _query()), metric=["funding_basis", "basis", "liquidation_intensity",
                "liquidation_notional"]).json()  # fmt: skip
    s = {x["metric"]: x for x in body["series"]}
    assert s["funding_basis"]["points"] == s["basis"]["points"]
    assert s["liquidation_intensity"]["points"] == s["liquidation_notional"]["points"]
    assert s["liquidation_intensity"]["unit"] == "notional"


async def test_params_select_the_side() -> None:
    params = json.dumps({"liquidation_notional": {"side": "short"}})
    body = _get(_client(await _query()), metric="liquidation_notional", params=params).json()
    assert [p["v"] for p in body["series"][0]["points"]] == ["0", "5", "0"]


async def test_no_resolver_is_501() -> None:
    resp = _get(_client(await _query(), resolver=False), metric="basis")
    assert resp.status_code == 501 and _Reads.count == 0


async def test_unauthenticated_is_401_without_a_read() -> None:
    resp = _get(_client(await _query(), None), metric="basis")
    assert resp.status_code == 401 and resp.json()["code"] == "unauthenticated"
    assert _Reads.count == 0


@pytest.mark.parametrize("perms", [frozenset(), frozenset({"orders:write", "rules:read"})])
async def test_a_principal_without_marketdata_read_is_403(perms: frozenset[str]) -> None:
    resp = _get(_client(await _query(), _Principal(perms)), metric="basis")
    assert resp.status_code == 403 and resp.json()["code"] == "forbidden"
    jsonschema.validate(resp.json(), _schema("403", "application/problem+json"))  # type: ignore[arg-type]
    assert _Reads.count == 0


_TOO_MANY = ["basis"] * (MAX_METRICS + 1)


@pytest.mark.parametrize(
    ("extra", "code"),
    [
        ({"symbol": "btc-usdt", "metric": "basis"}, "validation_failed"),
        ({}, "validation_failed"),  # no metric
        ({"metric": _TOO_MANY}, "validation_failed"),
        ({"metric": "not_a_code"}, "validation_failed"),
        ({"metric": "basis", "bar_type": "tick"}, "validation_failed"),
        ({"metric": "basis", "param": "7"}, "validation_failed"),
        ({"metric": "basis", "params": "{"}, "validation_failed"),
        ({"metric": "basis", "params": "[]"}, "validation_failed"),
        ({"metric": "basis", "params": json.dumps({"cvd": {}})}, "validation_failed"),
        ({"metric": "basis", "params": json.dumps({"basis": {"source": "index"}})},
         "validation_failed"),
        ({"metric": "basis", "params": json.dumps({"basis": {"n": "1"}})}, "validation_failed"),
        ({"metric": "basis", "params": json.dumps({"basis": "mark"})}, "validation_failed"),
        ({"metric": "basis", "params": "x" * 2049}, "validation_failed"),
        ({"metric": "basis", "from": "yesterday"}, "invalid_time_range"),
        ({"metric": "basis", "from": "2025-09-14T11:00:00Z"}, "invalid_time_range"),
        ({"metric": "basis", "param": "1", "from": "2025-09-10T00:00:00Z"}, "invalid_time_range"),
        ({"metric": "basis", "param": "D", "from": "2024-01-01T00:00:00Z"}, "invalid_time_range"),
    ],
)  # fmt: skip
async def test_bad_requests_are_400_before_any_store_read(extra: dict[str, Any], code: str) -> None:
    before = deriv_range_rejected_total.labels(endpoint="metrics")._value.get()
    resp = _get(_client(await _query()), **extra)
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == code
    jsonschema.validate(resp.json(), _schema("400", "application/problem+json"))  # type: ignore[arg-type]
    assert _Reads.count == 0
    assert deriv_range_rejected_total.labels(endpoint="metrics")._value.get() == before + 1


async def test_a_code_no_engine_computes_yet_is_422_without_a_read() -> None:
    resp = _get(_client(await _query()), metric=["basis", "cvd"])
    assert resp.status_code == 422 and "cvd" in resp.json()["detail"]
    assert _Reads.count == 0


async def test_an_unlisted_symbol_is_422_without_a_read() -> None:
    resp = _get(_client(await _query(listed=False)), metric="basis")
    assert resp.status_code == 422 and resp.json()["code"] == "validation_failed"
    assert _Reads.count == 0


async def test_unwired_and_down_sources_are_503() -> None:
    assert _get(_client(None), metric="basis").status_code == 503
    resp = _get(_client(await _query(down=True)), metric="basis")
    assert resp.status_code == 503 and resp.json()["code"] == "store_unavailable"
