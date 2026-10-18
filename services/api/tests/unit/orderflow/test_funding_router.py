from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.funding import make_funding_router
from candleviewer.domain.funding import PredictedFunding, settle
from candleviewer.orderflow.funding import (
    FundingInvalidRequest,
    FundingSeries,
    FundingSymbolUnknown,
)

T0 = 1_700_000_000_000_000


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


class _Reader:
    def __init__(self, result: FundingSeries | Exception) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    async def series(self, symbol: str, **kw: object) -> FundingSeries:
        self.calls.append({"symbol": symbol, **kw})
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _series(*, predicted: bool = True) -> FundingSeries:
    return FundingSeries(
        symbol="ETHUSDT",
        funding_interval_minutes=240,
        settled=(settle("ETHUSDT", T0, Decimal("0.00008"), 240),),
        predicted=PredictedFunding(T0 + 1, "ETHUSDT", Decimal("0.0001")) if predicted else None,
        next_funding_time_us=T0 + 1,
        next_cursor=None,
        has_more=False,
    )


def _client(
    reader: _Reader | None, principal: _Principal | None, *, resolver: bool = True
) -> TestClient:
    app = FastAPI()
    app.include_router(
        make_funding_router(
            lambda: reader, principal_resolver=_Resolver(principal) if resolver else None
        )
    )
    return TestClient(app)


_OK = _Principal(frozenset({"marketdata:read"}))


def test_contract_shape_flags_and_interval() -> None:
    body = (
        _client(_Reader(_series()), _OK).get("/market/funding", params={"symbol": "ETHUSDT"}).json()
    )
    assert body["symbol"] == "ETHUSDT" and body["funding_interval_minutes"] == 240
    settled, predicted = body["items"]
    assert settled == {
        "t": "2023-11-14T22:13:20Z",
        "funding_rate": "0.00008",
        "predicted": False,
        "estimated": False,
    }
    assert predicted["predicted"] is True and predicted["estimated"] is True
    assert body["meta"] == {"next_cursor": None, "has_more": False, "count": 2}


def test_response_validates_against_openapi_schema() -> None:
    import jsonschema

    spec = load_openapi_spec()
    op = spec["paths"]["/market/funding"]["get"]["responses"]["200"]["content"]["application/json"]
    comps = spec["components"]["schemas"]

    def deref(node: object) -> object:
        if isinstance(node, dict):
            if "$ref" in node:
                return deref(comps[node["$ref"].rsplit("/", 1)[1]])
            return {k: deref(v) for k, v in node.items() if k != "examples"}
        if isinstance(node, list):
            return [deref(v) for v in node]
        return node

    schema = deref(op["schema"])
    body = (
        _client(_Reader(_series()), _OK).get("/market/funding", params={"symbol": "ETHUSDT"}).json()
    )
    jsonschema.validate(body, schema)  # type: ignore[arg-type]
    assert "funding_interval_minutes" in body


def test_predicted_absent_means_no_predicted_item() -> None:
    body = (
        _client(_Reader(_series(predicted=False)), _OK)
        .get("/market/funding", params={"symbol": "ETHUSDT"})
        .json()
    )
    assert [i["predicted"] for i in body["items"]] == [False]


def test_forbidden_without_permission_never_reaches_reader() -> None:
    reader = _Reader(_series())
    r = _client(reader, _Principal(frozenset({"instruments:read"}))).get(
        "/market/funding", params={"symbol": "ETHUSDT"}
    )
    assert r.status_code == 403 and r.json()["code"] == "forbidden" and not reader.calls
    assert r.headers["content-type"].startswith("application/problem+json")


def test_unauthenticated_and_no_resolver_fail_closed() -> None:
    reader = _Reader(_series())
    assert (
        _client(reader, None).get("/market/funding", params={"symbol": "ETHUSDT"}).status_code
        == 401
    )
    assert (
        _client(reader, _OK, resolver=False)
        .get("/market/funding", params={"symbol": "ETHUSDT"})
        .status_code
        == 501
    )
    assert not reader.calls


@pytest.mark.parametrize(
    "symbol", ["eth", "ETH/USDT", "A", "X" * 30, "ETH;DROP", "ETHUSDT\n", "ETHUSDT\r\n"]
)
def test_invalid_symbol_is_rejected_before_reader(symbol: str) -> None:
    reader = _Reader(_series())
    r = _client(reader, _OK).get("/market/funding", params={"symbol": symbol})
    assert r.status_code == 400 and not reader.calls


def test_errors_map_to_problem_codes() -> None:
    cases = [
        (FundingInvalidRequest("invalid_time_range", "bad"), 400, "invalid_time_range"),
        (FundingInvalidRequest("invalid_cursor", "bad"), 400, "invalid_cursor"),
        (FundingSymbolUnknown("X"), 404, "not_found"),
    ]
    for exc, status, code in cases:
        r = _client(_Reader(exc), _OK).get("/market/funding", params={"symbol": "ETHUSDT"})
        assert (r.status_code, r.json()["code"]) == (status, code)


def test_malformed_timestamp_and_unwired_reader() -> None:
    r = _client(_Reader(_series()), _OK).get(
        "/market/funding", params={"symbol": "ETHUSDT", "from": "garbage"}
    )
    assert r.status_code == 400 and r.json()["code"] == "invalid_time_range"
    assert (
        _client(None, _OK).get("/market/funding", params={"symbol": "ETHUSDT"}).status_code == 503
    )


def test_time_params_are_parsed_and_naive_assumed_utc() -> None:
    reader = _Reader(_series())
    _client(reader, _OK).get(
        "/market/funding",
        params={"symbol": "ETHUSDT", "from": "2023-11-14T00:00:00", "to": "2023-11-15T00:00:00Z"},
    )
    call = reader.calls[0]
    assert call["end_us"] - call["start_us"] == 86_400 * 1_000_000  # type: ignore[operator]


def test_each_principal_only_sees_what_resolver_grants_no_cross_symbol_leak() -> None:
    reader = _Reader(_series())
    c = _client(reader, _OK)
    c.get("/market/funding", params={"symbol": "ETHUSDT"})
    assert reader.calls[0]["symbol"] == "ETHUSDT"  # symbol comes from the query only


def test_every_400_path_increments_range_rejected_counter() -> None:
    from candleviewer.orderflow.funding_metrics import deriv_range_rejected_total

    def count() -> float:
        return deriv_range_rejected_total.labels(endpoint="funding")._value.get()  # type: ignore[no-any-return]

    cases = [
        (_Reader(_series()), {"symbol": "eth"}),
        (_Reader(_series()), {"symbol": "ETHUSDT", "from": "garbage"}),
        (_Reader(FundingInvalidRequest("invalid_cursor", "bad")), {"symbol": "ETHUSDT"}),
        (_Reader(FundingInvalidRequest("validation_failed", "bad")), {"symbol": "ETHUSDT"}),
    ]
    for reader, params in cases:
        before = count()
        assert _client(reader, _OK).get("/market/funding", params=params).status_code == 400
        assert count() == before + 1


def test_overlong_cursor_is_400_invalid_cursor_not_422() -> None:
    from candleviewer.orderflow.funding import FundingService

    reader = _Reader(FundingInvalidRequest("invalid_cursor", "bad"))
    r = _client(reader, _OK).get(
        "/market/funding", params={"symbol": "ETHUSDT", "cursor": "a" * 600}
    )
    assert r.status_code == 400 and r.json()["code"] == "invalid_cursor"
    assert FundingService is not None
