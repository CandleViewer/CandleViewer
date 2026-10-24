"""A generated model a request body reaches refuses an explicit `null` for an optional member the
contract does not let be `null` (#906 slice G2b): left out, the member is `None`; sent as `null`, it
is a `value_error` whose constant message holds no input. A member the contract lets be `null`
takes it, and so does every model no request body reaches (ruling 1 of 2026-10-23 00:29Z)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, RootModel, ValidationError

from candleviewer.api._generated import openapi_models as api
from tests.contract._generated_contract import (
    REQUEST_MODELS,
    SPEC,
    _request_roots,
    contract_accepts,
    model_accepts,
)
from tests.contract.test_generate_protocol_models import _generator

_REFUSED = "Value error, null is not allowed: leave the member out"
#: How a route reads a body: Python data, raw JSON, or FastAPI's `from_attributes` (spec 1.4).
_MODES = pytest.mark.parametrize("mode", ["python", "json", "attributes"])
_PROFILE = {"name": "p", "leverage": "5", "sizing": {"mode": "fixed_qty", "qty": "1"}}
_KEY = {"api_key": "k" * 8, "api_secret": "s" * 8}


def _models() -> dict[str, type[BaseModel]]:
    """Every generated model but a `RootModel`, by name, as the module holds it now."""
    found = {n: c for n, c in vars(api).items() if isinstance(c, type) and issubclass(c, BaseModel)}
    return {n: c for n, c in found.items() if not issubclass(c, RootModel)}


def _optionals(model: type[BaseModel]) -> dict[str, str]:
    """A request model's members that default to `None`: name to the pointer of its schema."""
    return {n: p for n, p in REQUEST_MODELS[model].items() if model.model_fields[n].default is None}


def _validate(name: str, body: dict[str, Any], mode: str) -> Any:
    model: type[BaseModel] = getattr(api, name)
    if mode == "json":
        return model.model_validate_json(json.dumps(body))
    return model.model_validate(body, from_attributes=mode == "attributes")


def test_the_generator_marks_the_models_a_request_body_reaches_and_the_proof_checks_them() -> None:
    """The generator's own walk (`_request_models`) reaches the models the proof pairs, only they
    refuse `null` under a name of their own, and the proof reaches through a list (R2-02)."""
    source = Path(api.__file__).read_text(encoding="utf-8")
    requested = {model.__name__ for model in REQUEST_MODELS}
    assert _generator()._request_models(SPEC, source) & _models().keys() == requested
    assert {n for n, c in _models().items() if f"_{n}__null_refused" in vars(c)} <= requested
    probed = {(m.__name__, n) for m in REQUEST_MODELS for n in _optionals(m)}
    assert len(probed) >= 248  # every optional member of a request model, re-measured
    assert {("CreateApiKeyRequest", "label"), ("TakeProfitLevel", "offset")} <= probed


def test_only_null_is_refused() -> None:
    """One function carries every refused member: it refuses `None` and hands any other value back
    as it came, a falsy or empty one included (R1C-04)."""
    values: tuple[object, ...] = (0, False, "", [], {})
    for value in values:
        assert api._refuse_null(value) is value
    with pytest.raises(ValueError, match="null is not allowed"):
        api._refuse_null(None)


def test_a_request_root_without_a_model_holds_no_object() -> None:
    """R1S-02: both walks start at the request roots codegen made a class of; one it collapsed is
    safe only while it holds no object, whose models both walks would then miss alike."""
    for name in sorted(_request_roots()):
        found = getattr(api, name, None)
        if not (isinstance(found, type) and issubclass(found, BaseModel)):
            held = SPEC["components"]["schemas"][name].keys()
            assert not held & {"properties", "items", "allOf", "oneOf", "anyOf"}, name


@pytest.mark.parametrize(
    "model", [m for m in REQUEST_MODELS if _optionals(m)], ids=lambda model: model.__name__
)
def test_a_request_model_takes_null_for_an_optional_member_exactly_where_the_contract_does(
    model: type[BaseModel],
) -> None:
    differing = [
        name
        for name, pointer in _optionals(model).items()
        if model_accepts(model, name, None) != contract_accepts(pointer, None)
    ]
    assert differing == []


#: The members the G2 spec names, and one of the recorded-symbol body mounted since (the order's
#: is pinned on its route), each with the smallest body its model takes.
_NULL_REFUSED = [
    ("AccountProfileInput", _PROFILE, "stop_loss"),
    ("AccountProfileInput", _PROFILE, "risk_caps"),  # `attributes`: never an empty caps model
    ("CreateApiKeyRequest", _KEY, "label"),
    ("CreateApiKeyRequest", _KEY, "expected_uid"),
    ("UpdateUserRequest", {}, "status"),
    ("UpdateUserRequest", {}, "roles"),
    ("UpdateUserRequest", {}, "mfa_required"),
    ("SetFeatureFlagRequest", {"value": True}, "overrides"),
    ("SetFeatureFlagRequest", {"value": True}, "reason"),
    ("SetFeatureFlagRequest", {"value": True}, "evidence_url"),
    ("SetFeatureFlagRequest", {"value": True}, "expected_updated_at"),
    ("SimulateRuleRequest", {}, "from"),  # the wire name of `from_`
    ("UpdateRecordedSymbolRequest", {}, "pinned"),
]


@_MODES
@pytest.mark.parametrize(
    ("name", "base", "member"), _NULL_REFUSED, ids=[f"{n}.{m}" for n, _, m in _NULL_REFUSED]
)
def test_null_is_a_value_error_at_the_member(
    mode: str, name: str, base: dict[str, Any], member: str
) -> None:
    with pytest.raises(ValidationError) as refused:
        _validate(name, {**base, member: None}, mode)
    errors = [(e["loc"], e["type"], e["msg"]) for e in refused.value.errors()]
    assert errors == [((member,), "value_error", _REFUSED)]


@_MODES
def test_a_left_out_optional_member_stays_absent(mode: str) -> None:
    taken = _validate("CreateApiKeyRequest", _KEY, mode)
    assert (taken.label, taken.expected_uid, taken.model_fields_set) == (None, None, set(_KEY))
    assert taken.model_dump(exclude_unset=True).keys() == _KEY.keys()


@_MODES
@pytest.mark.parametrize(
    ("name", "base", "member", "sent"),
    [
        ("AccountProfileInput", _PROFILE, "take_profit", None),
        ("UpdateUserRequest", {}, "display_name", None),
        ("SetFeatureFlagRequest", {}, "value", None),  # `{}` in the contract: any value
        ("PaneConfig", {}, "settings", {"depth": None}),  # a value that is null, not the member
        ("UpdateRecordedSymbolRequest", {}, "retention_days", None),
    ],
)
def test_a_member_the_contract_lets_be_null_still_takes_it(
    mode: str, name: str, base: dict[str, Any], member: str, sent: object
) -> None:
    assert getattr(_validate(name, {**base, member: sent}, mode), member) == sent


def test_a_model_no_request_body_reaches_still_takes_null() -> None:
    """Ruling 1: a response model keeps taking `null`, also where it extends a request model that
    refuses it (`Alert` extends `AlertInput`, `Watchlist` extends `WatchlistInput`)."""
    requested = {model.__name__ for model in REQUEST_MODELS}
    models = [c for n, c in _models().items() if n not in requested]
    probed = [(c, m) for c in models for m, f in c.model_fields.items() if f.default is None]
    assert {(api.Alert, "message_template"), (api.Watchlist, "columns")} <= set(probed)
    assert [(c.__name__, m) for c, m in probed if not model_accepts(c, m, None)] == []
