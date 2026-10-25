"""S-RL (#913): the recorded `GET /v5/market/risk-limit` replies -> the adapter's real parser ->
the real `InstrumentsRefreshScheduler` cache -> the real `/instruments/{symbol}` route, validated
against the generated `InstrumentDetail` model (22). Recorded fixtures only, no network (C-13.5).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api._generated.openapi_models import InstrumentDetail
from candleviewer.api.instruments import InstrumentsPrincipal, make_instruments_router
from candleviewer.exchange.base.instruments import InstrumentsFetchResult
from candleviewer.exchange.base.models import RiskLimitTier
from candleviewer.exchange.bybit.config import EndpointClass
from candleviewer.exchange.bybit.instruments import parse_instruments
from candleviewer.exchange.bybit.risk_limits import PATH, fetch_risk_limits
from candleviewer.ingestion.instruments_refresh import InstrumentsRefreshScheduler
from tests._corpus import rest

T0 = 1_700_000_000_000_000
#: The recorded replies, one per symbol (named in full for the feed-rot meta-check).
FIXTURES = {"BTCUSDT": "rest/risk_limit_BTCUSDT.json", "ETHUSDT": "rest/risk_limit_ETHUSDT.json"}
SYMBOLS = tuple(FIXTURES)


def _reply(symbol: str) -> dict[str, Any]:
    return dict(rest(FIXTURES[symbol]))


class _Recorded:
    """`get_public` answering from the recorded replies; it records each call it gets."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], EndpointClass]] = []

    async def get_public(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        endpoint_class: EndpointClass = EndpointClass.MARKET_DATA,
    ) -> dict[str, Any]:
        args = dict(params or {})
        self.calls.append((path, args, endpoint_class))
        return _reply(str(args["symbol"]))


async def test_recorded_replies_map_to_ascending_decimal_tiers() -> None:
    client = _Recorded()
    for symbol in SYMBOLS:
        tiers = await fetch_risk_limits(client, symbol)
        rows = _reply(symbol)["result"]["list"]
        assert len(tiers) == len(rows) == 35
        by_id = {row["id"]: row for row in rows}
        for tier in tiers:
            row = by_id[tier.tier_id]
            assert tier.risk_limit_value == Decimal(row["riskLimitValue"])
            assert tier.maintenance_margin_rate == Decimal(row["maintenanceMargin"])
            assert tier.initial_margin_rate == Decimal(row["initialMargin"])
            assert tier.max_leverage == Decimal(row["maxLeverage"])
        values = [t.risk_limit_value for t in tiers]
        assert values == sorted(values) and len(set(values)) == len(values)
    assert client.calls == [
        (PATH, {"category": "linear", "symbol": s}, EndpointClass.MARKET_DATA) for s in SYMBOLS
    ]


class _Repo:
    async def upsert_snapshot(self, rows: Sequence[Mapping[str, Any]]) -> None:
        return None

    async def record_version(
        self, row: Mapping[str, Any], *, changed_fields: Sequence[str]
    ) -> None:
        return None

    async def mark_stale(self, *, stale_since_us: int) -> None:
        return None

    async def load_all(self) -> Sequence[Mapping[str, Any]]:
        return []


class _Resolver:
    def resolve(self, request: Request) -> InstrumentsPrincipal:
        return InstrumentsPrincipal(user_id="u", permissions=frozenset({"instruments:read"}))


async def _catalogue(now_us: Callable[[], int]) -> InstrumentsFetchResult:
    items = rest("rest/instruments_before.json")["result"]["list"]
    return parse_instruments(items, fetched_at_us=now_us())


async def test_detail_route_serves_the_recorded_tiers_in_the_contract_shape() -> None:
    client = _Recorded()

    async def fetch(symbol: str) -> Sequence[RiskLimitTier]:
        return await fetch_risk_limits(client, symbol)

    sched = InstrumentsRefreshScheduler(
        fetch_instruments_info=_catalogue, repository=_Repo(), now_us=lambda: T0,
        fetch_risk_limits=fetch,
    )  # fmt: skip
    await sched.refresh_now()
    app = FastAPI()
    app.include_router(make_instruments_router(lambda: sched, principal_resolver=_Resolver()))
    http = TestClient(app, client=("127.0.0.1", 50000))
    body = http.get("/instruments/BTCUSDT").json()
    detail = InstrumentDetail.model_validate(body)
    assert detail.risk_limit_tiers is not None and len(detail.risk_limit_tiers) == 35
    first = _reply("BTCUSDT")["result"]["list"][0]
    assert body["risk_limit_tiers"][0] == {
        "tier": first["id"],
        "risk_limit_value": first["riskLimitValue"],
        "initial_margin": first["initialMargin"],
        "maintenance_margin": first["maintenanceMargin"],
        "max_leverage": first["maxLeverage"],
    }
    http.get("/instruments/BTCUSDT")  # served from the cache: no second upstream call
    assert [c[1]["symbol"] for c in client.calls] == ["BTCUSDT"]
