"""22's `/watchlists` contract read as JSON Schema 2020-12 (E08-T07, #4706): a full `Watchlist`
validates, as its own schema, closed on purpose (an `allOf` over the closed `WatchlistInput`
accepted none), and its `name`, `symbols` and `columns` carry exactly the input's constraints;
`columns` is bounded as E08-D07 has it (the ids of §4.1, an open set by D8, none twice, `null` on
input only, meaning the defaults); the writes declare `413 payload_too_large` and
`WatchlistSaveUnavailable`, the 503 that carries `instrument_cache_unavailable` with `Retry-After`,
and the create and the replace state where that 503 sits in their refusal order and when a write
needs no catalogue."""

from __future__ import annotations

from typing import Any

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry
from referencing.jsonschema import DRAFT202012

from candleviewer.api.contract_conformance import load_openapi_spec

SPEC: dict[str, Any] = load_openapi_spec()
_BASE = "urn:cv:22-api-openapi"
_REGISTRY: Registry[Any] = Registry().with_resource(_BASE, DRAFT202012.create_resource(SPEC))
_SCHEMAS: dict[str, Any] = SPEC["components"]["schemas"]
_STAMP = "2026-10-28T12:00:00.000000Z"
_LIST: dict[str, Any] = {
    "id": "0193f2bb-0000-7000-8000-000000000001", "name": "Majors",
    "symbols": ["BTCUSDT", "ETHUSDT"], "columns": ["last", "chg_24h_pct"], "version": 2,
    "created_at": _STAMP, "updated_at": _STAMP,
}  # fmt: skip
#: E08-D07 §4.1: the nine defaults with an id (Status has none) and the eight optional columns.
_D07_IDS = (
    "symbol last chg_24h_pct turnover_24h funding_rate next_funding oi_chg_24h_pct spread_bps rec "
    "volume_24h open_interest_value mark_price index_price bid1_price ask1_price high_24h low_24h"
).split()
_WRITES = [("/watchlists", "post"), ("/watchlists/{watchlistId}", "put")]
_ORDER = (
    "then `422` for the rules that need no catalogue (`name`, `columns`, `too_many_symbols`, "
    "`duplicate_symbol`), then `503 instrument_cache_unavailable`, then `422` for "
    "`unknown_symbol`, then `409`."
)


def _errors(schema: str, doc: Any) -> list[str]:
    checker = Draft202012Validator.FORMAT_CHECKER
    ref = {"$ref": f"{_BASE}#/components/schemas/{schema}"}
    validator = Draft202012Validator(ref, registry=_REGISTRY, format_checker=checker)
    return sorted(e.message for e in validator.iter_errors(doc))


def _words(text: str) -> str:
    return " ".join(text.split())


def test_a_full_watchlist_validates_and_the_schema_is_closed_on_purpose() -> None:
    assert _errors("Watchlist", _LIST) == []
    assert _errors("Watchlist", _LIST | {"columns": []}) == []
    assert _errors("Watchlist", _LIST | {"owner_user_id": _LIST["id"]})  # closed
    assert _errors("Watchlist", _LIST | {"version": 0})
    assert _errors("Watchlist", _LIST | {"columns": None})  # always answered as a list
    for member in _LIST:  # every member is always answered
        assert _errors("Watchlist", {k: v for k, v in _LIST.items() if k != member}), member
    assert "Closed on purpose" in _words(_SCHEMAS["Watchlist"]["description"])


def test_watchlist_carries_the_inputs_constraints_on_name_symbols_and_columns() -> None:
    """Descriptions aside, the members match; the one difference is the input's `null` for
    `columns` (left out or `null`: the defaults), which a stored list never answers."""

    def bare(schema: str, member: str) -> dict[str, Any]:
        found = dict(_SCHEMAS[schema]["properties"][member])
        found.pop("description", None)
        return found

    for member in ("name", "symbols"):
        assert bare("Watchlist", member) == bare("WatchlistInput", member), member
    assert bare("WatchlistInput", "columns") == bare("Watchlist", "columns") | {
        "type": ["array", "null"]
    }


@pytest.mark.parametrize("schema", ["Watchlist", "WatchlistInput"])
def test_columns_are_at_most_32_unique_snake_case_ids_of_at_most_32_characters(schema: str) -> None:
    base = _LIST if schema == "Watchlist" else {"name": "Majors", "symbols": []}
    assert len(_D07_IDS) == 17 and _errors(schema, base | {"columns": list(_D07_IDS)}) == []
    assert _errors(schema, base | {"columns": ["a_column_d07_does_not_name_yet"]}) == []  # D8
    assert _errors(schema, base | {"columns": [f"c{i}" for i in range(32)]}) == []
    assert _errors(schema, base | {"columns": ["c" * 32]}) == []
    for bad in ([f"c{i}" for i in range(33)], ["c" * 33], ["last", "last"], ["Last"], ["24h"],
                ["last-price"]):  # fmt: skip
        assert _errors(schema, base | {"columns": bad}), bad


def test_an_input_may_leave_columns_out_or_send_null_for_the_default_set() -> None:
    assert _errors("WatchlistInput", {"name": "Majors", "symbols": []}) == []
    assert _errors("WatchlistInput", {"name": "Majors", "symbols": [], "columns": None}) == []
    words = _words(_SCHEMAS["WatchlistInput"]["properties"]["columns"]["description"])
    assert "Left out or `null`, on a create and on a replace alike" in words
    assert all(f"`{c}`" in words for c in _D07_IDS[:9])  # E08-D07 §4.1's nine defaults


def test_the_name_is_trimmed_before_it_is_checked_and_stored() -> None:
    words = _words(_SCHEMAS["WatchlistInput"]["properties"]["name"]["description"])
    assert words.startswith("Trimmed of leading and trailing white space before it is checked")
    assert "so a name blank once trimmed is `422 validation_failed`" in words


@pytest.mark.parametrize(("path", "method"), _WRITES)
def test_both_writes_declare_413_and_place_the_catalogues_503_in_their_order(
    path: str, method: str
) -> None:
    op = SPEC["paths"][path][method]
    assert op["responses"]["413"] == {"$ref": "#/components/responses/PayloadTooLarge"}
    assert op["responses"]["503"] == {"$ref": "#/components/responses/WatchlistSaveUnavailable"}
    words = _words(op["description"])
    assert "body over 64 KiB is `413 payload_too_large`" in words
    assert _ORDER in words
    exempt = {"post": "A list with no symbols needs no catalogue, so it is never",
              "put": "A replace whose symbols are all already on the stored list"}  # fmt: skip
    assert exempt[method] in words


def test_the_watchlist_503_covers_the_three_writes_with_retry_after() -> None:
    codes = {e["code"]: e["status"] for e in SPEC["x-error-codes"]}
    assert codes["payload_too_large"] == 413
    delete = SPEC["paths"]["/watchlists/{watchlistId}"]["delete"]["responses"]["503"]
    assert delete == {"$ref": "#/components/responses/WatchlistSaveUnavailable"}
    response = SPEC["components"]["responses"]["WatchlistSaveUnavailable"]
    words = _words(response["description"])
    assert all(
        f"`{op}`" in words for op in ("createWatchlist", "updateWatchlist", "deleteWatchlist")
    )
    assert response["headers"] == {"Retry-After": {"$ref": "#/components/headers/RetryAfter"}}
    named = ("instrument_cache_unavailable", "audit_unavailable", "store_unavailable")
    assert all(f"`{c}`" in words and codes[c] == 503 for c in named)
    (example,) = response["content"]["application/problem+json"]["examples"].values()
    assert _errors("Problem", example["value"]) == []
    assert (example["value"]["code"], example["value"]["retry_after_seconds"]) == (
        "instrument_cache_unavailable", 2)  # fmt: skip
