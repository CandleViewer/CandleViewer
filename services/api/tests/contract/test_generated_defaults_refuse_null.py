"""A generated model refuses an explicit `null` for a member the contract defaults and does not
mark nullable (#906 slice G, the second gap slice 0b found): such a member is omittable, and
omitted it takes the contract's default, but `null` is not a value it holds. A member the
contract does mark nullable still takes `null`."""

from __future__ import annotations

from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import load_openapi_spec

_SPEC: Any = load_openapi_spec()  # a parsed YAML document, walked untyped
_SCHEMAS: dict[str, Any] = _SPEC["components"]["schemas"]
_BASE = "urn:cv:openapi"
#: The smallest `AccountProfileInput`: its three required members.
_BODY: dict[str, Any] = {"name": "p", "leverage": "5", "sizing": {"mode": "fixed_qty", "qty": "1"}}


def _contract_takes_null(prop: dict[str, Any]) -> bool:
    """Whether the contract's own schema for one member accepts `null`, `$ref`s resolved."""
    schemas = {**_SCHEMAS, "_probe": prop}
    spec = {**_SPEC, "components": {**_SPEC["components"], "schemas": schemas}}
    resource = Resource.from_contents(spec, default_specification=DRAFT202012)
    return Draft202012Validator(
        {"$ref": f"{_BASE}#/components/schemas/_probe"},
        registry=Registry().with_resource(_BASE, resource),
    ).is_valid(None)


def _generated_takes_null(model: type[BaseModel], member: str) -> bool:
    """Whether the generated `model` takes `null` for `member`, the rest of its body aside."""
    try:
        model.__pydantic_validator__.validate_assignment(model.model_construct(), member, None)
    except ValidationError:
        return False
    return True


def _defaulted_members() -> dict[str, dict[str, bool]]:
    """Per generated model: each member the contract gives a default, and whether it takes null."""
    found = {}
    for name, schema in _SCHEMAS.items():
        model = getattr(api, name, None)
        if isinstance(model, type) and issubclass(model, BaseModel):
            found[name] = {
                member: _contract_takes_null(prop)
                for member, prop in schema.get("properties", {}).items()
                if "default" in prop and member in model.model_fields
            }
    return {name: members for name, members in found.items() if members}


_DEFAULTED = _defaulted_members()


@pytest.mark.parametrize("name", list(_DEFAULTED))
def test_generated_model_takes_null_for_a_defaulted_member_only_where_the_contract_does(
    name: str,
) -> None:
    model: type[BaseModel] = getattr(api, name)
    assert {m: _generated_takes_null(model, m) for m in _DEFAULTED[name]} == _DEFAULTED[name]


def test_the_defaulted_members_cover_the_profile_body_and_the_nullable_ones() -> None:
    profile = _DEFAULTED["AccountProfileInput"]
    assert {"allowed_symbols", "enabled", "margin_mode"} <= set(profile)
    assert not any(profile.values())
    assert _DEFAULTED["AddRecordedSymbolRequest"]["retention_days"] is True


@pytest.mark.parametrize("member", ["allowed_symbols", "enabled", "margin_mode"])
def test_account_profile_input_refuses_null_for_a_member_the_contract_defaults(
    member: str,
) -> None:
    with pytest.raises(ValidationError) as refused:
        api.AccountProfileInput.model_validate({**_BODY, member: None})
    assert [error["loc"] for error in refused.value.errors()] == [(member,)]


def test_account_profile_input_omitting_a_defaulted_member_takes_the_contract_default() -> None:
    built = api.AccountProfileInput.model_validate(_BODY)
    props = _SCHEMAS["AccountProfileInput"]["properties"]
    defaults = {member: prop["default"] for member, prop in props.items() if "default" in prop}
    assert {m: getattr(built, m) for m in defaults} == defaults


def test_a_member_the_contract_marks_nullable_still_takes_null() -> None:
    assert api.ProfileRiskCaps.model_validate({"max_position_notional_usd": None})
    assert (
        api.AccountProfileInput.model_validate({**_BODY, "take_profit": None}).take_profit is None
    )
