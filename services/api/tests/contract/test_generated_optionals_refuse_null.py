"""A generated REST model refuses an explicit `null` for an optional member the contract does not
let be `null` (#906 slice G2b for the models a request body reaches, #4237 for every other): left
out, the member is `None`; sent as `null`, it is a `value_error` whose constant message holds no
input. A member the contract lets be `null` takes it."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import BaseModel, RootModel, ValidationError

from candleviewer.api._generated import openapi_models as api
from tests.contract._generated_contract import (
    _SCHEMAS,
    MODELS,
    REQUEST_ROOTS,
    RESPONSE_ROOTS,
    UNPAIRED_ANY,
    _at,
    _deref,
    contract_accepts,
    model_accepts,
)

_REFUSED = "Value error, null is not allowed: leave the member out"
#: How a route reads a body: Python data, raw JSON, or FastAPI's `from_attributes` (spec 1.4).
_MODES = pytest.mark.parametrize("mode", ["python", "json", "attributes"])
_PROFILE = {"name": "p", "leverage": "5", "sizing": {"mode": "fixed_qty", "qty": "1"}}
_KEY = {"api_key": "k" * 8, "api_secret": "s" * 8}
_GRANT = {"exchange_account_id": "00000000-0000-4000-8000-000000000001", "level": "read"}
_USER = {"id": _GRANT["exchange_account_id"], "username": "u", "email": "u@x", "roles": []}
_USER |= {"status": "active"}


#: Schemas kept in 22 that no operation reaches, so no generated model pairs with them; named here
#: and read only by the pairing test below.
_KEPT_UNREFERENCED = {"RiskCaps": "kept for the E39-D02 records; retired with them"}


def _models() -> dict[str, type[BaseModel]]:
    """Every generated model but a `RootModel`, by name, as the module holds it now."""
    found = {n: c for n, c in vars(api).items() if isinstance(c, type) and issubclass(c, BaseModel)}
    return {n: c for n, c in found.items() if not issubclass(c, RootModel) and c is not BaseModel}


def _optionals(model: type[BaseModel]) -> dict[str, str]:
    """A model's members that default to `None`: name to the pointer of its schema."""
    return {n: p for n, p in MODELS[model].items() if model.model_fields[n].default is None}


def _validate(name: str, body: dict[str, Any], mode: str) -> Any:
    model: type[BaseModel] = getattr(api, name)
    if mode == "json":
        return model.model_validate_json(json.dumps(body))
    return model.model_validate(body, from_attributes=mode == "attributes")


def test_the_proof_pairs_every_generated_model_and_probes_each_optional_member() -> None:
    """Each generated model pairs with a contract schema, and the proof probes every optional
    member: 248 of the request models (G2b) and 1,109 more that a response reaches (#4237)."""
    assert sorted(m.__name__ for m in UNPAIRED_ANY) == []
    unpaired = set(_models()) - {m.__name__ for m in MODELS}
    assert sorted(unpaired - set(_KEPT_UNREFERENCED)) == []
    probed = {(m.__name__, n) for m in MODELS for n in _optionals(m)}
    assert len(probed) >= 1_350
    refused = {(m, n) for m, n in probed if not model_accepts(getattr(api, m), n, None)}
    assert len(refused) >= 1_100
    assert {("AccountAccessGrant", "granted_by"), ("Alert", "message_template")} <= refused


def test_each_class_refuses_under_a_name_of_its_own() -> None:
    """A model refuses `null` only for members of its own or of a class it extends, each under the
    mangled name of the class that declares them: no class takes `null` back (`_take_null`)."""
    for name, model in _models().items():
        own = [k for k in vars(model) if k.endswith("__null_refused")]
        assert own in ([], [f"_{name}__null_refused"]), name
    assert not hasattr(api, "_take_null")


def test_only_null_is_refused() -> None:
    """One function carries every refused member: it refuses `None` and hands any other value back
    as it came, a falsy or empty one included (R1C-04)."""
    values: tuple[object, ...] = (0, False, "", [], {})
    for value in values:
        assert api._refuse_null(value) is value
    with pytest.raises(ValueError, match="null is not allowed"):
        api._refuse_null(None)


def test_a_root_without_a_model_holds_no_object() -> None:
    """R1S-02: the walks start at the request and response roots codegen made a class of; one it
    collapsed is safe only while it holds no object, whose models every walk would then miss
    alike; read where its `$ref` ends, `additionalProperties` included (R2-02)."""
    keys = {"properties", "items", "additionalProperties", "allOf", "oneOf", "anyOf"}
    for name in sorted(REQUEST_ROOTS | RESPONSE_ROOTS):
        found = getattr(api, name, None)
        if not (isinstance(found, type) and issubclass(found, BaseModel)):
            assert not _at(_deref(_SCHEMAS + name)).keys() & keys, name


@pytest.mark.parametrize(
    "model", [m for m in MODELS if _optionals(m)], ids=lambda model: model.__name__
)
def test_a_generated_model_takes_null_for_an_optional_member_exactly_where_the_contract_does(
    model: type[BaseModel],
) -> None:
    differing = [
        name
        for name, pointer in _optionals(model).items()
        if model_accepts(model, name, None) != contract_accepts(pointer, None)
    ]
    assert differing == []


#: The members the G2 spec names, one of the recorded-symbol body mounted since (the order's is
#: pinned on its route), and four a response reaches (#4237), each with the smallest body its
#: model takes: `UserWithInvite` refuses `User`'s, which it extends.
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
    ("AccountAccessGrant", _GRANT, "granted_by"),
    ("User", _USER, "created_at"),
    ("UserWithInvite", _USER, "created_at"),
    ("ExchangeRecordFields", {}, "side"),
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
        ("WatchlistInput", {"name": "n", "symbols": []}, "columns", None),  # null: the defaults
    ],
)
def test_a_member_the_contract_lets_be_null_still_takes_it(
    mode: str, name: str, base: dict[str, Any], member: str, sent: object
) -> None:
    assert getattr(_validate(name, {**base, member: sent}, mode), member) == sent
