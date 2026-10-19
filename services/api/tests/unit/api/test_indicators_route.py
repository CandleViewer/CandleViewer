"""`GET /api/v1/indicators` (`listIndicators`; E13-T02, scenario "The catalogue drives the form").

Every v1 indicator is returned with a valid JSON Schema `params_schema` in the closed subset a
client renders (SR-E13-09), bounded by `limits.py` (SR-E13-01); adding an indicator to the
registry changes the response with no frontend change. RBAC fails closed (501/401/403), each
item carries the contract's fields only (IR-25), and `compute` is never read from the request
(IR-41).
"""

from __future__ import annotations

from typing import Any

import jsonschema
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.indicators import make_indicators_router
from candleviewer.orderflow.indicators import limits
from candleviewer.orderflow.indicators.catalogue import (
    IndicatorCatalogue,
    IndicatorDef,
    OutputSpec,
    ParamSpec,
    default_catalogue,
)

#: The closed JSON Schema subset (SR-E13-09): object level, then each parameter.
SCHEMA_KEYS = {"type", "additionalProperties", "properties"}
PARAM_KEYS = {"type", "title", "default", "minimum", "maximum", "multipleOf", "enum"}
#: Each fractional parameter's family in `limits.py`.
FRACTIONAL = {
    "mult": "MULTIPLIER",
    "deviation_pct": "DEVIATION_PCT",
    "step": "PSAR_ACCELERATION",
    "max_step": "PSAR_ACCELERATION",
}


class _Principal:
    def __init__(self, *permissions: str) -> None:
        self.permissions = frozenset(permissions)

    def has(self, permission: str) -> bool:
        return permission in self.permissions


class _Resolver:
    def __init__(self, principal: _Principal | None) -> None:
        self.principal = principal

    def resolve(self, request: Request) -> _Principal | None:
        return self.principal


class _AsyncResolver:
    def __init__(self, principal: _Principal | None) -> None:
        self.principal = principal

    async def resolve(self, request: Request) -> _Principal | None:
        return self.principal


VIEWER = _Resolver(_Principal("marketdata:read"))


def _client(
    catalogue: IndicatorCatalogue | None = None,
    resolver: _Resolver | _AsyncResolver | None = VIEWER,
) -> TestClient:
    app = FastAPI()
    cat = default_catalogue() if catalogue is None else catalogue
    app.include_router(make_indicators_router(cat, principal_resolver=resolver))
    return TestClient(app)


def _items(client: TestClient, **params: str) -> list[dict[str, Any]]:
    response = client.get("/indicators", params=params)
    assert response.status_code == 200
    items: list[dict[str, Any]] = response.json()["items"]
    return items


def test_indicators_route_serves_every_v1_indicator_in_catalogue_order() -> None:
    items = _items(_client())
    assert [i["id"] for i in items] == [d.id for d in default_catalogue()]
    assert len(items) == 28 and sum(i["compute"] == "server" for i in items) == 9


def test_indicators_route_items_carry_exactly_the_contract_fields() -> None:
    spec: dict[str, Any] = load_openapi_spec()
    contract = set(spec["components"]["schemas"]["IndicatorDescriptor"]["properties"])
    for item in _items(_client()):
        assert set(item) == contract, item["id"]


def test_indicators_route_every_params_schema_is_legal_json_schema_in_the_closed_subset() -> None:
    for item in _items(_client()):
        schema = item["params_schema"]
        jsonschema.Draft202012Validator.check_schema(schema)
        assert set(schema) == SCHEMA_KEYS and schema["type"] == "object", item["id"]
        assert schema["additionalProperties"] is False, item["id"]
        for name, prop in schema["properties"].items():
            assert set(prop) <= PARAM_KEYS and prop["title"], (item["id"], name)
            assert prop["type"] in {"integer", "number", "string"}, (item["id"], name)


def _served_params(kind: str) -> list[tuple[str, str, dict[str, Any]]]:
    """(indicator, parameter, schema) of every served parameter of one JSON type."""
    return [
        (item["id"], name, prop)
        for item in _items(_client())
        for name, prop in item["params_schema"]["properties"].items()
        if prop["type"] == kind
    ]


def test_indicators_route_every_integer_parameter_is_a_period_of_1_to_5000() -> None:
    periods = _served_params("integer")
    assert len(periods) == 31  # every period-like parameter of the 28 indicators
    for indicator, name, prop in periods:
        bounds = (prop["minimum"], prop["maximum"], "multipleOf" in prop)
        assert bounds == (limits.PERIOD_MIN, limits.PERIOD_MAX, False), (indicator, name)


def test_indicators_route_every_fractional_parameter_has_its_limits_py_bounds_and_step() -> None:
    fractional = _served_params("number")
    assert {name for _, name, _ in fractional} == set(FRACTIONAL)
    for indicator, name, prop in fractional:
        pinned = [getattr(limits, f"{FRACTIONAL[name]}_{p}") for p in ("MIN", "MAX", "STEP")]
        served = [prop["minimum"], prop["maximum"], prop["multipleOf"]]
        assert served == [float(v) for v in pinned], (indicator, name)


def test_indicators_route_every_string_parameter_is_a_closed_enum() -> None:
    for indicator, name, prop in _served_params("string"):
        assert prop["enum"] and prop["default"] in prop["enum"], (indicator, name)


def test_indicators_route_defaults_are_legal_values_of_their_own_schema() -> None:
    for item in _items(_client()):
        jsonschema.Draft202012Validator(item["params_schema"]).validate(item["defaults"])
        props = item["params_schema"]["properties"]
        assert item["defaults"] == {k: p["default"] for k, p in props.items()}, item["id"]


def test_indicators_route_describes_outputs_warmup_unit_and_nullability() -> None:
    by_id = {i["id"]: i for i in _items(_client())}
    vwap = by_id["vwap"]
    assert [o["id"] for o in vwap["outputs"]] == [
        "vwap", "sigma", "upper_1", "lower_1", "upper_2", "lower_2", "upper_3", "lower_3",
        "band_sigma",
    ]  # fmt: skip
    assert (by_id["atr"]["warmup_bars"], by_id["atr"]["unit"]) == (14, "price")
    assert "None until n bars exist" in by_id["atr"]["nullable_when"]
    assert by_id["zigzag"]["defaults"] == {"depth": 5, "deviation_pct": 0}
    assert all(i["name"] and i["outputs"] and i["nullable_when"] for i in by_id.values())


def test_indicators_route_compute_is_derived_never_requested() -> None:
    client = _client()
    assert _items(client, compute="server", ema="client_worker") == _items(client)


def test_indicators_route_a_newly_registered_indicator_appears_with_no_frontend_change() -> None:
    catalogue = default_catalogue()
    client = _client(catalogue)
    assert len(_items(client)) == 28
    catalogue.register(
        IndicatorDef(
            "hull_ma",
            "Hull moving average",
            "trend",
            "price",
            "price",
            (OutputSpec("hull_ma", "Hull MA"),),
            (ParamSpec("n", "Period", "integer", 9, limits.PERIOD_MIN, limits.PERIOD_MAX),),
            "None until n bars exist.",
            lambda params: 9,
        )
    )
    items = _items(client)
    assert [i["id"] for i in items][-1] == "hull_ma" and len(items) == 29
    hull = items[-1]
    assert (hull["compute"], hull["defaults"], hull["warmup_bars"]) == (
        "client_worker",
        {"n": 9},
        9,
    )
    assert hull["params_schema"]["properties"]["n"]["maximum"] == limits.PERIOD_MAX


def test_indicators_route_without_a_session_is_401() -> None:
    response = _client(resolver=_Resolver(None)).get("/indicators")
    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "unauthenticated"


@pytest.mark.parametrize("permissions", [(), ("workspaces:read", "orders:read")])
def test_indicators_route_without_marketdata_read_is_403(permissions: tuple[str, ...]) -> None:
    response = _client(resolver=_Resolver(_Principal(*permissions))).get("/indicators")
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"
    assert "items" not in response.json()


def test_indicators_route_without_a_resolver_fails_closed_with_501() -> None:
    response = _client(resolver=None).get("/indicators")
    assert response.status_code == 501
    assert response.json()["code"] == "not_implemented"


def test_indicators_route_accepts_an_async_resolver() -> None:
    allowed = _client(resolver=_AsyncResolver(_Principal("marketdata:read")))
    assert len(_items(allowed)) == 28
    assert _client(resolver=_AsyncResolver(None)).get("/indicators").status_code == 401
