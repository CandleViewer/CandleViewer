"""Contract (#906, E28-T02): a profile body carries exactly the stored columns of `account_profiles`
(C-6.1, C-6.3). Every body schema is closed, the generated models hold exactly its members, and
the body takes the documented shapes and no other."""

from __future__ import annotations

import copy
from typing import Any, Literal, get_args, get_origin

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import load_openapi_spec

_SPEC: Any = load_openapi_spec()  # a parsed YAML document, walked untyped
_SCHEMAS: dict[str, Any] = _SPEC["components"]["schemas"]
_BASE = "urn:cv:openapi"
_REGISTRY = Registry().with_resource(
    _BASE, Resource.from_contents(_SPEC, default_specification=DRAFT202012)
)
#: The writable schemas of a profile: each maps to stored columns and refuses what it does not name.
_BODY = (
    "AccountProfileInput ProfileSizing ProfileStopLoss ProfileTakeProfit "
    "ProfileTakeProfitRung ProfileRiskCaps"
).split()
_GONE = object()  # an edit that removes the member
_STOP = {"unit": "ticks", "value": "20"}
#: (the edits to the create example, whether the body is still valid); an edit key is a dotted path.
_CASES: dict[str, tuple[dict[str, object], bool]] = {
    "the_create_example_an_atr_stop_and_an_r_multiple_target": ({}, True),
    "ticks_stop_with_its_value": ({"stop_loss": _STOP}, True),
    "take_profit_null": ({"take_profit": None}, True),
    "all_symbols_with_no_list": ({"all_symbols": True, "allowed_symbols": []}, True),
    "unknown_member": ({"trailing_stop": _STOP}, False),
    "removed_member_of_sizing": ({"sizing.round_to_lot": True}, False),
    "removed_member_of_risk_caps": ({"risk_caps.max_consecutive_losses": 3}, False),
    "read_only_version": ({"version": 2}, False),
    "read_only_is_active": ({"is_active": True}, False),
    "risk_based_without_a_stop": ({"stop_loss": _GONE}, False),
    "atr_stop_without_its_multiple": ({"stop_loss.atr_multiple": _GONE}, False),
    "ticks_stop_without_its_value": ({"stop_loss": {"unit": "ticks"}}, False),
    "stop_in_r_multiple": ({"stop_loss": {"unit": "r_multiple", "value": "2"}}, False),
    "take_profit_in_price": ({"take_profit": {"unit": "price", "value": "70000"}}, False),
    "fixed_qty_without_qty": ({"sizing": {"mode": "fixed_qty"}}, False),
    "risk_based_without_an_amount": ({"sizing.risk_per_trade_pct": _GONE}, False),
    "request_time_sizing_mode": ({"sizing": {"mode": "pct_position", "pct": "5"}}, False),
    "portfolio_margin": ({"margin_mode": "portfolio"}, False),
    "native_stop_off": ({"require_native_stop": False}, False),
    "all_symbols_with_a_list": ({"all_symbols": True}, False),
    "no_open_positions_allowed": ({"risk_caps.max_open_positions": 0}, False),
    "too_many_open_positions": ({"risk_caps.max_open_positions": 51}, False),
    "eleven_ladder_rungs": ({"take_profit_ladder": [{"qty_pct": "5", "r": "1"}] * 11}, False),
}


def _valid(name: str, value: object) -> bool:
    """Whether `value` is a valid `name` component, the whole spec being the `$ref` registry."""
    return Draft202012Validator(
        {"$ref": f"{_BASE}#/components/schemas/{name}"},
        registry=_REGISTRY,
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    ).is_valid(value)


def _changed(edits: dict[str, object]) -> dict[str, Any]:
    """The create operation's `riskBased` body, each dotted member set or removed (`_GONE`)."""
    post = _SPEC["paths"]["/exchange-accounts/{accountId}/profiles"]["post"]
    body: dict[str, Any] = copy.deepcopy(
        post["requestBody"]["content"]["application/json"]["examples"]["riskBased"]["value"]
    )
    for path, value in edits.items():
        *parents, leaf = path.split(".")
        node = body
        for key in parents:
            node = node[key]
        if value is _GONE:
            del node[leaf]
        else:
            node[leaf] = value
    return body


@pytest.mark.parametrize("name", _BODY)
def test_every_profile_body_schema_refuses_unknown_members(name: str) -> None:
    assert _SCHEMAS[name]["additionalProperties"] is False
    assert getattr(api, name).model_config["extra"] == "forbid"


def test_generated_profile_models_have_exactly_the_contract_members() -> None:
    for name in (*_BODY, "AccountProfile"):
        assert set(getattr(api, name).model_fields) == set(_SCHEMAS[name]["properties"]), name
    assert api.AccountProfile.model_fields["profile"].annotation is api.AccountProfileInput
    native_stop = api.AccountProfileInput.model_fields["require_native_stop"].annotation
    assert get_origin(native_stop) is Literal  # the stored invariant is a constant, `Literal[True]`
    assert get_args(native_stop) == (True,)


@pytest.mark.parametrize(("edits", "valid"), list(_CASES.values()), ids=list(_CASES))
def test_the_body_schema_takes_exactly_the_documented_shapes(
    edits: dict[str, object], valid: bool
) -> None:
    assert _valid("AccountProfileInput", _changed(edits)) is valid
