"""Contract (E08-T08, PR 1 of #4707): `GET /market/tickers`, the bulk ticker snapshot, and the 24 h
high and low. Contract first (C-6.1): nothing serves the route yet, so the composition guard and
the RBAC matrix carry it as pending until the implementation PR mounts it. Additive only (C-6.3):
`Ticker` and the WS `ticker` item keep every field, type and `required` list they had, and nothing
new is required of either; a bulk item is a `TickersItem`, a `Ticker` that must carry its `symbol`,
`ts` and `stale`; `TickerEvent` (24 §2.3) gains the two prices, typed like its others.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from referencing import Registry, Resource

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import load_contract_subset, load_openapi_spec
from tests.openapi_helpers import deref

_REPO = Path(__file__).resolve().parents[4]
_SPEC: dict[str, Any] = load_openapi_spec()
_SCHEMAS: dict[str, Any] = _SPEC["components"]["schemas"]
_PATH = "/market/tickers"
_WS_SCHEMAS: dict[str, Any] = json.loads(
    (_REPO / "docs" / "plan" / "ws-schema.json").read_text(encoding="utf-8")
)["schemas"]
_WS_TICKER: dict[str, Any] = _WS_SCHEMAS["cv://ws/v1/ticker.schema.json"]
_WS_REGISTRY: Registry[Any] = Registry().with_resources(
    (sid, Resource.from_contents(body)) for sid, body in _WS_SCHEMAS.items()
)
#: The 23 §14.8 `ticker` payload, its `cv://ws/v1/common.schema.json` refs read from the bundle.
_WS_FRAME = Draft202012Validator(_WS_TICKER, registry=_WS_REGISTRY)
#: A §14.8 item as a symbol's merged state may give it: no 24 h range and no `stale`.
_WS_ITEM: dict[str, Any] = {
    "symbol": "BTCUSDT",
    "last_price": "63120.50",
    "mark_price": "63118.90",
    "funding_rate": "0.0001",
    "ts_ms": 1_789_468_262_100,
}
_DOC24 = _REPO / "docs" / "plan" / "24-internal-schemas.md"
_DECIMAL = {"$ref": "#/components/schemas/Decimal"}
_INSTANT = {"type": "string", "format": "date-time"}
#: `Ticker` as it stood before this change: each field keeps its schema (C-6.3).
_TICKER_BEFORE: dict[str, dict[str, Any]] = {
    "symbol": {"$ref": "#/components/schemas/Symbol"},
    **dict.fromkeys(
        (
            *("last_price", "mark_price", "index_price", "bid1_price", "bid1_size"),
            *("ask1_price", "ask1_size", "price_change_pct_24h", "high_24h", "low_24h"),
            *("volume_24h", "turnover_24h", "open_interest", "open_interest_value"),
            "funding_rate",
        ),
        _DECIMAL,
    ),
    "next_funding_time": _INSTANT,
    "ts": _INSTANT,
    "stale": {"type": "boolean"},
}


def _op() -> dict[str, Any]:
    op: dict[str, Any] = _SPEC["paths"][_PATH]["get"]
    return op


def _example() -> dict[str, Any]:
    examples = _op()["responses"]["200"]["content"]["application/json"]["examples"]
    (only,) = examples.values()
    value: dict[str, Any] = only["value"]
    return value


def _rest(name: str) -> Draft202012Validator:
    """The contract's `name` schema as a validator, every `$ref` inlined."""
    return Draft202012Validator(deref(_SPEC, _SCHEMAS[name]))


def _ws_frame(**fields: Any) -> dict[str, Any]:
    """A §14.8 `ticker` payload of one item, `_WS_ITEM` with `fields` set on it."""
    return {"tickers": [{**_WS_ITEM, **fields}]}


def _failing(validator: Draft202012Validator, instance: Any) -> list[str]:
    """The JSON path of each error `instance` raises; empty when it validates."""
    return sorted(error.json_path for error in validator.iter_errors(instance))


def test_get_tickers_is_a_market_data_read_scoped_like_the_per_symbol_ticker() -> None:
    op = _op()
    assert (op["operationId"], op["tags"]) == ("getTickers", ["market-data"])
    assert op["x-rbac"] == {"permissions": ["marketdata:read"], "scope": "none"}
    assert op["x-rbac"] == _SPEC["paths"]["/instruments/{symbol}/ticker"]["get"]["x-rbac"]


def test_symbols_is_one_required_repeatable_list_capped_at_a_watchlists_200() -> None:
    (param,) = _op()["parameters"]
    cap = _SCHEMAS["WatchlistInput"]["properties"]["symbols"]["maxItems"]
    assert cap == 200
    assert (param["name"], param["in"], param["required"], param["explode"]) == (
        "symbols",
        "query",
        True,
        True,
    )
    assert param["schema"] == {
        "type": "array",
        "minItems": 1,
        "maxItems": cap,
        "items": {"$ref": "#/components/schemas/Symbol"},
    }


def test_the_answer_holds_one_ticker_per_found_symbol_and_reports_the_unknown_ones() -> None:
    content = _op()["responses"]["200"]["content"]["application/json"]
    assert content["schema"] == {"$ref": "#/components/schemas/TickersResponse"}
    answer = _SCHEMAS["TickersResponse"]
    assert sorted(answer["required"]) == ["items", "meta", "unknown_symbols"]
    props = answer["properties"]
    assert props["items"]["items"] == {"$ref": "#/components/schemas/TickersItem"}
    assert props["unknown_symbols"]["items"] == {"$ref": "#/components/schemas/Symbol"}
    assert props["items"]["maxItems"] == props["unknown_symbols"]["maxItems"] == 200
    assert props["meta"] == {"$ref": "#/components/schemas/PageMeta"}


def test_a_bulk_item_is_a_ticker_that_must_carry_its_symbol_ts_and_stale() -> None:
    item = _SCHEMAS["TickersItem"]
    assert set(item) == {"description", "allOf", "required"}  # it narrows `Ticker`, adds nothing
    assert item["allOf"] == [{"$ref": "#/components/schemas/Ticker"}]
    assert sorted(item["required"]) == ["stale", "symbol", "ts"]
    assert issubclass(api.TickersItem, api.Ticker)
    fields = api.TickersItem.model_fields
    assert sorted(name for name, field in fields.items() if field.is_required()) == [
        "stale",
        "symbol",
        "ts",
    ]


def test_its_refusals_are_the_shared_problems_and_an_unknown_symbol_is_never_a_404() -> None:
    responses = _op()["responses"]
    refusals = {
        "400": "BadRequest",
        "401": "Unauthorized",
        "403": "Forbidden",
        "503": "ServiceUnavailable",
    }
    assert set(responses) == {"200", *refusals}
    for status, name in refusals.items():
        assert responses[status] == {"$ref": f"#/components/responses/{name}"}
    codes = {e["code"]: e["status"] for e in _SPEC["x-error-codes"]}
    for status, code in (("400", "validation_failed"), ("503", "exchange_unavailable")):
        assert codes[code] == int(status)
        assert f"`{status} {code}`" in _op()["description"]


def test_the_example_validates_and_every_item_carries_its_ts_and_the_24h_range() -> None:
    example = _example()
    jsonschema.validate(example, deref(_SPEC, _SCHEMAS["TickersResponse"]))
    answer = api.TickersResponse.model_validate(example)
    assert answer.meta.count == len(answer.items) and answer.meta.has_more is False
    assert len({item["ts"] for item in example["items"]}) == 1  # one snapshot, one time
    for item in example["items"]:
        assert {"symbol", "ts", "stale", "high_24h", "low_24h"} <= item.keys()
    assert set(example["unknown_symbols"]).isdisjoint(i["symbol"] for i in example["items"])


def test_the_packaged_subset_declares_get_tickers_as_the_contract_does() -> None:
    subset: dict[str, Any] = load_contract_subset()
    assert subset["paths"][_PATH] == {"get": {"x-rbac": _op()["x-rbac"]}}


def test_ticker_keeps_every_field_and_type_and_requires_nothing() -> None:
    ticker = _SCHEMAS["Ticker"]
    assert "required" not in ticker
    for name, schema in _TICKER_BEFORE.items():
        kept = {k: v for k, v in ticker["properties"][name].items() if k != "description"}
        assert kept == schema, name


def test_the_ws_ticker_item_keeps_its_fields_with_the_24h_range_optional() -> None:
    item = _WS_TICKER["properties"]["tickers"]["items"]
    assert item["required"] == ["symbol", "last_price", "ts_ms"]
    decimal = {"$ref": "cv://ws/v1/common.schema.json#/$defs/decimal"}
    assert item["properties"]["high_24h"] == item["properties"]["low_24h"] == decimal
    assert item["properties"]["stale"] == {"type": "boolean", "default": False}


def test_a_ws_ticker_frame_without_the_24h_range_validates() -> None:
    assert not {"high_24h", "low_24h"} & _WS_ITEM.keys()
    assert _failing(_WS_FRAME, _ws_frame()) == []


@pytest.mark.parametrize("name", ["high_24h", "low_24h"])
def test_a_ws_ticker_frame_with_a_null_24h_high_or_low_is_refused(name: str) -> None:
    assert _failing(_WS_FRAME, _ws_frame(**{name: None})) == [f"$.tickers[0].{name}"]


def test_a_ws_ticker_frame_with_a_stale_item_validates() -> None:
    assert _failing(_WS_FRAME, _ws_frame(stale=True)) == []


def test_a_rest_ticker_with_a_null_24h_high_is_refused() -> None:
    ticker = _example()["items"][0]
    assert _failing(_rest("Ticker"), ticker) == []
    assert _failing(_rest("Ticker"), {**ticker, "high_24h": None}) == ["$.high_24h"]


def test_a_bulk_item_without_its_ts_is_refused_by_the_contract_and_the_generated_model() -> None:
    example = _example()
    item = {k: v for k, v in example["items"][0].items() if k != "ts"}
    body = {**example, "items": [item], "meta": {**example["meta"], "count": 1}}
    errors = [(e.json_path, e.message) for e in _rest("TickersResponse").iter_errors(body)]
    assert errors == [("$.items[0]", "'ts' is a required property")]
    with pytest.raises(ValidationError) as caught:
        api.TickersResponse.model_validate(body)
    missing = [(e["loc"], e["type"]) for e in caught.value.errors()]
    assert missing == [(("items", 0, "ts"), "missing")]


def test_ticker_event_gains_the_24h_high_and_low_typed_like_its_other_prices() -> None:
    section = _DOC24.read_text(encoding="utf-8").split("### 2.3 TickerEvent", 1)[1]
    section = section.split("\n### ", 1)[0]
    block = section.split("```python", 1)[1].split("```", 1)[0]
    fields = dict(re.findall(r"^    (\w+): ([^#\n]*?)\s*(?:#.*)?$", block, re.MULTILINE))
    assert fields["high_24h"] == fields["low_24h"] == fields["last_price"] == "Px | None"
    assert "`highPrice24h→high_24h`" in section and "`lowPrice24h→low_24h`" in section
