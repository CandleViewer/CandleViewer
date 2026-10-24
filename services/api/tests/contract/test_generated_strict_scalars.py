"""A generated REST model takes a boolean, an integer or a number only as that JSON type (#906 slice
G2a): `1`, `"yes"` and `"true"` are no boolean, `"5"` is no integer, `"1.5"` is no number, and `5.0`
is an integer, as the contract's `type`s say. The oracle is a JSON Schema validator over the
contract (`_generated_contract`); the models are the ones a request body reaches."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from candleviewer.api._generated import openapi_models as api
from tests.contract._generated_contract import (
    REQUEST_MODELS,
    UNPAIRED,
    contract_accepts,
    model_accepts,
    scalar_members,
)

#: What a lax parser takes for a boolean, an integer or a number (`1`, `"yes"`, `"5"`, `"1.5"`),
#: and what the contract takes: a whole float is an integer, a fraction is not, a bound is a bound.
_PROBES: list[object] = [1, 0, 1.0, 0.0, 5, 5.0, 5.5, -1, 1_000_000, 1e6, True, False]
_PROBES += ["1", "5", " 5", "5.0", "1.5", "true", "false", "yes", "on"]
_BOTH = pytest.mark.parametrize("json_mode", [False, True], ids=["python", "json"])
_PROFILE = {"name": "p", "leverage": "5", "sizing": {"mode": "fixed_qty", "qty": "1"}}


def _validate(model: type[BaseModel], body: dict[str, Any], *, json_mode: bool) -> Any:
    """`model` over `body`, as Python data (a FastAPI body) or as raw JSON (a route that parses)."""
    return model.model_validate_json(json.dumps(body)) if json_mode else model.model_validate(body)


def _refusal(model: type[BaseModel], body: dict[str, Any], *, json_mode: bool) -> list[Any]:
    with pytest.raises(ValidationError) as refused:
        _validate(model, body, json_mode=json_mode)
    return [(error["loc"], error["type"]) for error in refused.value.errors()]


def test_every_model_a_request_body_reaches_is_paired_with_its_contract_schema() -> None:
    assert sorted(model.__name__ for model in UNPAIRED) == []
    assert {"CreateApiKeyRequest", "ProfileRiskCaps", "ReplayControlRequest"} <= {
        model.__name__ for model in REQUEST_MODELS
    }


def test_the_request_scalars_the_proof_checks_hold_a_boolean_an_integer_and_a_number() -> None:
    members = {(m.__name__, name) for m in REQUEST_MODELS for name in scalar_members(m)}
    assert len(members) >= 115  # the walk's reach, re-measured: a lost model's scalars fail it
    assert {
        ("CreateApiKeyRequest", "read_only"),
        ("LayoutPaneInput", "slot_index"),  # only through a `list[...]` member (R2-02)
        ("ProfileRiskCaps", "max_open_positions"),
        ("ReplayControlRequest", "speed"),
        ("RetentionPolicyInput", "retain_days"),  # only from inside an inline body (R1C-02)
    } <= members


@pytest.mark.parametrize(
    "model", [m for m in REQUEST_MODELS if scalar_members(m)], ids=lambda model: model.__name__
)
def test_a_request_model_takes_a_scalar_exactly_where_the_contract_does(
    model: type[BaseModel],
) -> None:
    differing = [
        (name, value)
        for name, pointer in scalar_members(model).items()
        for value in _PROBES
        if model_accepts(model, name, value) != contract_accepts(pointer, value)
    ]
    assert differing == []


@_BOTH
@pytest.mark.parametrize(
    ("model", "base", "member", "sent", "rule"),
    [
        (api.AccountProfileInput, _PROFILE, "trading_enabled", 1, "bool_type"),
        (api.AccountProfileInput, _PROFILE, "trading_enabled", "yes", "bool_type"),
        (api.ProfileRiskCaps, {}, "max_open_positions", "5", "int_type"),
    ],
    ids=["one-for-true", "yes-for-true", "string-for-an-integer"],
)
def test_the_coercions_the_ruling_names_are_refused(
    json_mode: bool,
    model: type[BaseModel],
    base: dict[str, Any],
    member: str,
    sent: object,
    rule: str,
) -> None:
    assert _refusal(model, {**base, member: sent}, json_mode=json_mode) == [((member,), rule)]


@_BOTH
def test_an_integer_member_takes_a_json_integer_with_no_fraction(json_mode: bool) -> None:
    for sent in (5, 5.0):
        taken = _validate(api.ProfileRiskCaps, {"max_open_positions": sent}, json_mode=json_mode)
        assert taken.max_open_positions == 5 and type(taken.max_open_positions) is int
    for refused in (5.5, True, "5"):
        body = {"max_open_positions": refused}
        assert _refusal(api.ProfileRiskCaps, body, json_mode=json_mode) == [
            (("max_open_positions",), "int_type")
        ]


def test_the_kek_rewrap_body_takes_a_version_with_no_fraction_as_its_contract_does() -> None:
    """`admin_kek` parses with `model_validate_json(..., strict=True)`: `to_version: 2.0` was
    refused there, and the contract's `type: integer` takes it (#906 G2a ruling 3)."""

    def parse(version: object) -> Any:
        raw = json.dumps({"environment": "demo", "to_version": version}).encode()
        return api.KekRewrapRequest.model_validate_json(raw, strict=True)

    assert (parse(2.0).to_version, parse(3).to_version) == (2, 3)
    assert type(parse(2.0).to_version) is int  # the KEK handle selector, never a float (R1S-01)
    for refused in ("2", 2.5, True):
        with pytest.raises(ValidationError):
            parse(refused)


@_BOTH
def test_a_number_member_takes_an_integer_but_no_string_or_boolean(json_mode: bool) -> None:
    for sent in (0, 2, 2.5):
        body = {"action": "set_speed", "speed": sent}
        assert _validate(api.ReplayControlRequest, body, json_mode=json_mode).speed == sent
    for refused in ("2", "1.5", True):
        body = {"action": "set_speed", "speed": refused}
        assert _refusal(api.ReplayControlRequest, body, json_mode=json_mode) == [
            (("speed",), "float_type")
        ]
