"""Contract (#836, E27-T03 slice 2b1a): the pieces `createApiKey` and `testApiKey` share, and the
`201`, ahead of the routes (C-6.1). The slice changes: `KeyVerification.egress_ip`, the address
the Owner adds to a key's whitelist; the names and addresses a verification may show, bounded
(SR-E27-08); the `403 kek_unavailable` of ADR-0009 Amendment 1; and the `201`, which is always
the stored key with the verification that passed. It adds no operation, so the composition
guard's caps stand. Every new sentence of the prose is quoted in `_PINNED`, so deleting one
fails a test."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from jsonschema import ValidationError as SchemaError
from pydantic import ValidationError

from candleviewer.api._generated import openapi_models as api
from candleviewer.ws._generated.error_codes import ErrorCode
from tests.contract._admin_support import ROOT, SPEC, text, validate_example

_SCHEMAS: dict[str, Any] = SPEC["components"]["schemas"]
_RESPONSES: dict[str, Any] = SPEC["components"]["responses"]
_REGISTRY: dict[str, dict[str, Any]] = {entry["code"]: entry for entry in SPEC["x-error-codes"]}
_VERIFICATION = "/components/schemas/KeyVerification"

_EGRESS = "203.0.113.10"

#: Where each new sentence is written, with a core phrase of every one: a deletion check.
_PINNED: dict[tuple[str, ...], tuple[str, ...]] = {
    ("components", "responses", "Forbidden"): (
        "`createApiKey` and `testApiKey` answer `code: kek_unavailable` while the credential key",
        "(KEK) is unavailable (ADR-0009 Amendment 1)",
    ),
    ("components", "schemas", "ApiKeyWithVerification"): (
        "The `201` of `createApiKey`: the key is stored only if every check passes",
        "both members are always present and `verification` is the full `KeyVerification`",
        "A key that fails a check is a `422`, never this body",
    ),
    ("components", "schemas", "KeyVerificationPassed"): (
        "A `KeyVerification` of a key that passed every check",
        "the one verification a stored key has, and the only one a `201` carries",
    ),
    ("components", "schemas", "EgressIp"): (
        "The deployment's configured egress IP (`CV_EGRESS_IP`)",
        "`null` while none is configured",
        "It comes from configuration, never from a request header",
        "the address the Owner adds to the key's whitelist at the exchange when the exchange",
        "Confidential: served only to a caller holding `keys:manage` or `keys:read`",
        "never written to an audit record or used as a metric label",
    ),
    ("components", "schemas", "KeyVerification", "properties", "permissions"): (
        "whose name is not a plain identifier is left out of the display",
    ),
    ("components", "schemas", "KeyVerification", "properties", "ip_whitelist"): (
        "At most 20 entries, each an address, a range or `*`",
    ),
}


def _operation(operation_id: str) -> dict[str, Any]:
    (operation,) = [
        operation
        for item in SPEC["paths"].values()
        for operation in item.values()
        if isinstance(operation, dict) and operation.get("operationId") == operation_id
    ]
    return operation


def _resolved(response: dict[str, Any]) -> dict[str, Any]:
    ref = response.get("$ref")
    return response if ref is None else _RESPONSES[ref.rsplit("/", 1)[1]]


def _description(*keys: str) -> str:
    node: Any = SPEC
    for key in keys:
        node = node[key]
    return text(node["description"])


def _examples(operation_id: str, only: int | None = None) -> Iterator[tuple[int, str, Any]]:
    """`(status, name, value)` of every example of every response, shared ones included."""
    for status, response in _operation(operation_id)["responses"].items():
        for body in _resolved(response).get("content", {}).values():
            for name, example in body.get("examples", {}).items():
                if only in (None, int(status)):
                    yield int(status), name, example["value"]


def _by_name(operation_id: str, status: int) -> dict[str, Any]:
    return {name: value for _, name, value in _examples(operation_id, status)}


def _without(value: dict[str, Any], *names: str) -> dict[str, Any]:
    return {k: v for k, v in value.items() if k not in names}


# --- Egress IP: the address to copy into the whitelist (US-ACCT-003) -------------------------


@pytest.mark.parametrize("egress_ip", [_EGRESS, "2001:db8::10", None])
def test_egress_ip_is_one_ip_address_or_null_while_none_is_set(egress_ip: str | None) -> None:
    verification = {"passed": False, "withdraw_enabled": False, "egress_ip": egress_ip}
    validate_example(_VERIFICATION, verification)
    decoded = api.KeyVerification.model_validate(verification).egress_ip
    assert (None if decoded is None else str(decoded)) == egress_ip


@pytest.mark.parametrize(
    "egress_ip",
    ["203.0.113.0/24", "*", "1.1.1.1, 2.2.2.2", "x.com", "", "dead.beef", "....", "::::", "1.2"],
)
def test_egress_ip_refuses_a_range_a_wildcard_a_list_and_text(egress_ip: str) -> None:
    # `ipv4` and `ipv6` parse the address; a character class would let "dead.beef" through.
    verification = {"passed": False, "withdraw_enabled": False, "egress_ip": egress_ip}
    with pytest.raises(SchemaError):
        validate_example(_VERIFICATION, verification)
    with pytest.raises(ValidationError):
        api.KeyVerification.model_validate(verification)


def test_egress_ip_is_additive_to_the_verification() -> None:
    assert "egress_ip" not in _SCHEMAS["KeyVerification"]["required"]  # C-6.3


def test_an_accepted_verification_names_its_whitelist_host() -> None:
    accepted = [
        v["verification"]
        for op in ("createApiKey", "testApiKey", "rotateApiKey")
        for _, _, v in _examples(op)
        if isinstance(v, dict) and v.get("verification", {}).get("passed") is True
    ]
    assert len(accepted) >= 3  # the 201, the rotation 200 and the test 200
    assert all(v["ip_whitelist"] == [v["egress_ip"]] for v in accepted)


# --- The 403 while the credential key is unavailable ------------------------------------------


def test_the_adr_refuses_the_key_routes_with_403_while_the_kek_is_unavailable() -> None:
    adr = (ROOT / "docs/plan/27-adrs/ADR-0009-secrets-and-key-management.md").read_text("utf-8")
    amendment = text(adr.split("## Amendment 1", 1)[1].split("## Amendment 2", 1)[0])
    assert "KEK unavailable ⇒ `Degraded`: signing, key add/verify/rotate refused (403)" in amendment


def test_that_403_is_the_registered_kek_unavailable_problem_with_an_example() -> None:
    forbidden = _by_name("createApiKey", 403)["kekUnavailable"]
    assert (forbidden["code"], forbidden["status"]) == ("kek_unavailable", 403)
    assert forbidden["title"] == _REGISTRY["kek_unavailable"]["title"]


def test_the_generated_error_codes_hold_the_kek_code() -> None:
    assert ErrorCode("kek_unavailable").name == "KEK_UNAVAILABLE"  # the enums were regenerated


# --- A 201 is the stored key and its verification that passed (AC 1) ---------------------------

_CREATED_AT = "/components/schemas/ApiKeyWithVerification"
_CREATED = _by_name("createApiKey", 201)["verified"]
_UNVERIFIED = {
    "a 201 without its verification": _without(_CREATED, "verification"),
    "a 201 without its key": _without(_CREATED, "key"),
    "a 201 whose verification failed": {
        **_CREATED,
        "verification": {**_CREATED["verification"], "passed": False},
    },
    "a 201 holding the verification of a key not read": {
        **_CREATED,
        "verification": {"passed": False, "egress_ip": _EGRESS},
    },
}


def test_the_created_example_is_the_key_with_its_passed_verification() -> None:
    validate_example(_CREATED_AT, _CREATED)
    decoded = api.ApiKeyWithVerification.model_validate(_CREATED)
    assert decoded.verification.passed is True


@pytest.mark.parametrize("body", _UNVERIFIED.values(), ids=_UNVERIFIED)
def test_a_201_that_is_not_the_key_with_its_passed_verification_fails_the_schema(
    body: dict[str, Any],
) -> None:
    with pytest.raises(SchemaError):
        validate_example(_CREATED_AT, body)
    with pytest.raises(ValidationError):  # the generated model refuses it too
        api.ApiKeyWithVerification.model_validate(body)


def test_the_passed_verification_is_the_full_verification_with_passed_true() -> None:
    verification = _SCHEMAS["KeyVerificationPassed"]
    assert verification["allOf"][0] == {"$ref": "#/components/schemas/KeyVerification"}
    assert verification["allOf"][1]["properties"] == {"passed": {"const": True}}
    assert _SCHEMAS["ApiKeyWithVerification"]["required"] == ["key", "verification"]


# --- What a verification may show of the exchange's own names (SR-E27-08) ---------------------

_BOUNDED = {
    "a group name that is not an identifier": {"permissions": {"Wallet; DROP": ["Order"]}},
    "a right name that is not an identifier": {
        "permissions": {"ContractTrade": ["Order Position"]}
    },
    "a right name past 64 characters": {"permissions": {"ContractTrade": ["A" * 65]}},
    "more than 32 groups": {"permissions": {f"G{i}": [] for i in range(33)}},
    "more than 32 rights": {"permissions": {"ContractTrade": [f"R{i}" for i in range(33)]}},
    "a whitelist entry that is text": {"ip_whitelist": ["not an address, just text"]},
    "an overlong whitelist entry": {"ip_whitelist": ["1" * 50]},
    "more than 20 whitelist entries": {"ip_whitelist": [f"198.51.100.{i}" for i in range(21)]},
}


@pytest.mark.parametrize("shown", _BOUNDED.values(), ids=_BOUNDED)
def test_a_verification_bounds_the_names_and_addresses_it_may_show(shown: dict[str, Any]) -> None:
    with pytest.raises(SchemaError):
        validate_example(_VERIFICATION, {"passed": False, "withdraw_enabled": False, **shown})


def test_a_verification_may_show_a_wildcard_and_a_range_the_whitelist_check_refused() -> None:
    whitelist = ["*", "203.0.113.0/24", "2001:db8::/32", _EGRESS]
    shown = {"passed": False, "withdraw_enabled": False, "ip_whitelist": whitelist}
    validate_example(_VERIFICATION, shown)


# --- Every new sentence is quoted -------------------------------------------------------------


@pytest.mark.parametrize(
    ("keys", "phrases"), [pytest.param(k, p, id="/".join(k[-2:])) for k, p in _PINNED.items()]
)
def test_every_new_sentence_of_the_key_routes_is_quoted_by_a_test(
    keys: tuple[str, ...], phrases: tuple[str, ...]
) -> None:
    description = _description(*keys)
    assert [phrase for phrase in phrases if phrase not in description] == []
