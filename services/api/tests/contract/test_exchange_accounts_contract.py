"""Contract (#2417, E27-X01 proposal P-2): the `exchange-accounts` paths say what C-2.8, SR-030a and
SR-005 require before E27-T03 and E27-S02 to E27-S04 mount their routes (C-6.1). One group per
scope item of #2417: the key gate (SR-E27-04), the key-id mask (SR-E27-03), the open-exposure
choice and local-only revocation (SR-E27-06, SR-E27-07), the fixed result vocabulary (SR-E27-08),
the single rotation overlap (SR-E27-10) and no reveal path (SR-E27-11)."""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from candleviewer.accounts.models import ApiKeyMetadata, ApiKeyRotation
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import (
    OPENAPI_SPEC_PATH,
    REPO_ROOT,
    load_openapi_spec,
)

_SPEC = load_openapi_spec()
_SCHEMAS: dict[str, Any] = _SPEC["components"]["schemas"]
_PATHS: dict[str, Any] = {
    path: item for path, item in _SPEC["paths"].items() if path.startswith("/exchange-accounts")
}
_ACCOUNT = "/exchange-accounts/{accountId}"
_KEYS = f"{_ACCOUNT}/keys"
_KEY = f"{_KEYS}/{{keyId}}"
#: Revoke, disable and delete: the three actions SR-E27-07 gates on open exposure.
_EXPOSURE_OPS = [(_KEY, "delete"), (_ACCOUNT, "patch"), (_ACCOUNT, "delete")]
_MIGRATION_0017 = (
    REPO_ROOT / "services/api/candleviewer/migrations/versions/0017_exchange_accounts_api_keys.py"
)

#: SR-E27-04 / #2270: the only rights a stored key may hold; every other group is empty or absent.
_ALLOWED = {"ContractTrade": {"Order", "Position"}, "Derivatives": {"DerivativesTrade"}}
#: Named by #2417: refused whether or not the name says "withdraw" or "transfer" (E27-X01 D6).
_REFUSED = (
    "Withdraw",
    "AccountTransfer",
    "SubMemberTransfer",
    "SubMemberTransferList",
    "FiatP2P",
    "FiatBitPay",
    "FiatConvertBroker",
    "BitCard",
)
#: The internal exchange-error taxonomy (24-internal-schemas.md §8.6) a key probe can end in.
_PROBE_ERRORS = [
    "auth_error",
    "permission_denied",
    "ip_not_allowed",
    "clock_drift",
    "rate_limited",
    "service_unavailable",
    "transport_error",
    "timeout",
    "exchange_unknown",
]
_WARNINGS = ["key_expiring_soon", "clock_skew"]
#: Plaintext or envelope fields (C-2.7, 21-database-schema.md §3.2.2) no response may carry.
_SECRET_FIELDS = frozenset(
    {
        "api_key",
        "api_secret",
        "secret",
        "key_id",
        "secret_enc",
        "key_id_enc",
        "enc_nonce",
        "dek_ref",
    }
)


def _op(path: str, method: str) -> dict[str, Any]:
    operation: dict[str, Any] = _PATHS[path][method]
    return operation


def _text(path: str, method: str) -> str:
    """The operation description with its line breaks folded, for phrase checks."""
    return " ".join(_op(path, method)["description"].split())


def _deref(ref: str) -> Any:
    section, name = ref.removeprefix("#/components/").split("/")
    return _SPEC["components"][section][name]


def _walk(node: object, seen: set[str] | None = None) -> Iterator[object]:
    """Every node under `node`, following each local `$ref` once."""
    seen = set() if seen is None else seen
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref not in seen:
            seen.add(ref)
            yield from _walk(_deref(ref), seen)
        yield node
        for value in node.values():
            yield from _walk(value, seen)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item, seen)


def _examples() -> list[object]:
    """Every example value reachable from the exchange-accounts operations."""
    found: list[object] = []
    for node in _walk(_PATHS):
        if not isinstance(node, dict):
            continue
        named = node.get("examples")
        if isinstance(named, dict):
            found += [v["value"] for v in named.values() if isinstance(v, dict) and "value" in v]
        if "example" in node:
            found.append(node["example"])
    return found


def _values(node: object, key: str) -> Iterator[Any]:
    if isinstance(node, dict):
        for name, value in node.items():
            if name == key:
                yield value
            yield from _values(value, key)
    elif isinstance(node, list):
        for item in node:
            yield from _values(item, key)


def _all(key: str) -> list[Any]:
    return [value for example in _examples() for value in _values(example, key)]


# --- Key gate (SR-E27-04) -----------------------------------------------------------------------


def test_key_gate_allows_only_the_listed_rights_and_names_every_refused_one() -> None:
    gate = _text(_KEYS, "post")
    for name in _REFUSED:
        assert f"`{name}`" in gate, name
    assert "`ContractTrade` with `Order` and `Position`" in gate
    assert "`Derivatives` with `DerivativesTrade`" in gate
    assert "same verification pipeline as `createApiKey`" in _text(f"{_KEY}/rotate", "post")


def test_no_exchange_accounts_example_holds_a_right_outside_the_allow_list() -> None:
    permissions = _all("permissions")
    assert len(permissions) >= 3  # the createApiKey 201, rotateApiKey 200 and testApiKey 200
    for granted in permissions:
        for group, rights in granted.items():
            assert set(rights) <= _ALLOWED.get(group, set()), (group, rights)


def test_key_gate_reads_write_access_from_read_only_and_uta_never_unified() -> None:
    verification = _SCHEMAS["KeyVerification"]["properties"]
    assert {"uta", "read_only"} <= set(verification)
    assert "unified" not in verification
    assert {"uta", "read_only"} <= set(api.KeyVerification.model_fields)
    gate = _text(_KEYS, "post")
    assert "`readOnly`" in gate
    assert "`uta`" in gate
    assert "deprecated `unified`" in gate
    assert _all("unified") == []


def test_ip_whitelist_is_mandatory_and_no_setting_can_turn_it_off() -> None:
    assert "require_ip_whitelist" not in OPENAPI_SPEC_PATH.read_text(encoding="utf-8")
    gate = _text(_KEYS, "post")
    for phrase in ("non-empty", "wildcard", "egress IP", "C-4.14"):
        assert phrase in gate, phrase


def test_every_whitelist_example_is_one_host_address() -> None:
    verifications = _all("verification")
    assert len(verifications) >= 3
    for verification in verifications:
        assert verification["ip_whitelist_matches_egress"] is True
        hosts = {ipaddress.ip_network(entry, strict=True) for entry in verification["ip_whitelist"]}
        assert len(hosts) == 1
        assert next(iter(hosts)).num_addresses == 1


# --- Key-id mask (SR-E27-03) --------------------------------------------------------------------


def test_key_id_masked_exposes_at_most_the_last_four_characters() -> None:
    pattern = _SCHEMAS["ApiKey"]["properties"]["key_id_masked"]["pattern"]
    assert pattern == r"^\.\.\.[A-Za-z0-9]{4}$"
    masks = _all("key_id_masked")
    assert len(masks) >= 2
    assert all(re.fullmatch(pattern, mask) for mask in masks), masks
    built = ApiKeyMetadata.model_construct(key_id_last4="AbC1").key_id_masked
    assert re.fullmatch(pattern, built)
    listing = _text(_KEYS, "get")
    assert "last 4" in listing
    assert "first 4" not in listing


# --- Revoke, disable and delete (SR-E27-06, SR-E27-07) -------------------------------------------


@pytest.mark.parametrize(("path", "method"), [(_KEY, "delete"), (_ACCOUNT, "patch")])
def test_revoke_and_disable_take_either_open_exposure_choice(path: str, method: str) -> None:
    assert {"$ref": "#/components/parameters/OpenExposure"} in _op(path, method)["parameters"]
    choice = _SPEC["components"]["parameters"]["OpenExposure"]
    assert (choice["name"], choice["in"], choice["required"]) == ("open_exposure", "query", False)
    assert _deref(choice["schema"]["$ref"])["enum"] == ["leave_positions", "flatten_first"]


def test_delete_takes_only_flatten_first() -> None:
    choices = [p for p in _op(_ACCOUNT, "delete")["parameters"] if p.get("name") == "open_exposure"]
    assert len(choices) == 1
    choice = choices[0]
    assert (choice["in"], choice["required"]) == ("query", False)
    assert choice["schema"]["enum"] == ["flatten_first"]


@pytest.mark.parametrize(("path", "method"), _EXPOSURE_OPS)
def test_open_exposure_answers_409_with_the_consequence_summary(path: str, method: str) -> None:
    operation = _op(path, method)
    assert operation["responses"]["409"] == {"$ref": "#/components/responses/OpenExposureConflict"}
    assert "`409 open_exposure`" in _text(path, method)


def test_open_exposure_problem_is_registered_and_its_example_carries_the_summary() -> None:
    response = _SPEC["components"]["responses"]["OpenExposureConflict"]
    content = response["content"]["application/problem+json"]
    assert content["schema"] == {"$ref": "#/components/schemas/OpenExposureProblem"}
    example = content["examples"]["openExposure"]["value"]
    problem = api.OpenExposureProblem.model_validate(example)
    assert (problem.code, problem.status) == ("open_exposure", 409)
    assert example["type"].endswith("/errors/open_exposure")
    assert problem.consequences is not None
    assert problem.consequences.open_positions
    registered = {entry["code"]: entry for entry in _SPEC["x-error-codes"]}
    assert (registered["open_exposure"]["status"], registered["open_exposure"]["retryable"]) == (
        409,
        False,
    )


def test_consequence_summary_lists_positions_orders_algos_users_and_rules() -> None:
    summary = _SCHEMAS["AccountConsequenceSummary"]
    assert summary["additionalProperties"] is False
    assert set(summary["required"]) == {
        "exchange_account_id",
        "open_positions",
        "working_orders",
        "running_algos",
        "assigned_users",
        "armed_rules",
    }
    assert summary["properties"]["open_positions"]["items"] == {
        "$ref": "#/components/schemas/Position"
    }


def test_revocation_stays_local_and_deletion_at_the_exchange_is_manual() -> None:
    revoke = _text(_KEY, "delete")
    assert "never deletes keys on Bybit" in revoke
    assert "dashboard" in revoke


# --- Verification results (SR-E27-08) -----------------------------------------------------------


def test_probe_errors_and_warnings_use_a_closed_vocabulary() -> None:
    assert _SCHEMAS["KeyProbeError"]["enum"] == _PROBE_ERRORS
    assert _SCHEMAS["KeyVerificationWarning"]["enum"] == _WARNINGS
    probe = {"oneOf": [{"$ref": "#/components/schemas/KeyProbeError"}, {"type": "null"}]}
    result = _SCHEMAS["KeyTestResult"]["properties"]
    assert result["rest"]["properties"]["error"] == probe
    assert result["websocket"]["properties"]["error"] == probe
    warnings = _SCHEMAS["KeyVerification"]["properties"]["warnings"]
    assert warnings["items"] == {"$ref": "#/components/schemas/KeyVerificationWarning"}


def test_every_result_example_uses_only_the_fixed_codes() -> None:
    errors = [
        side["error"]
        for name in ("rest", "websocket")
        for side in _all(name)
        if side.get("error") is not None
    ]
    warnings = [code for listed in _all("warnings") for code in listed]
    assert errors
    assert warnings
    assert set(errors) <= set(_PROBE_ERRORS)
    assert set(warnings) <= set(_WARNINGS)


def test_generated_test_result_model_refuses_free_text_errors() -> None:
    test = _op(f"{_KEY}/test", "post")["responses"]["200"]["content"]["application/json"]
    example = test["examples"]["degraded"]["value"]
    api.KeyTestResult.model_validate(example)
    free_text = {**example, "websocket": {"ok": False, "error": "auth timeout after 5000ms"}}
    with pytest.raises(ValidationError):
        api.KeyTestResult.model_validate(free_text)


# --- Rotation overlap (SR-E27-10) ---------------------------------------------------------------


def _grace_seconds_default() -> int:
    migration = _MIGRATION_0017.read_text(encoding="utf-8")
    match = re.search(r"grace_seconds\s+integer NOT NULL DEFAULT (\d+)", migration)
    assert match is not None
    return int(match.group(1))


def test_rotation_has_one_overlap_value_equal_to_grace_seconds() -> None:
    grace = _grace_seconds_default()
    assert grace == ApiKeyRotation.model_fields["grace_seconds"].default
    request = _SCHEMAS["RotateApiKeyRequest"]
    assert "overlap_seconds" not in request["properties"]
    assert request["additionalProperties"] is False
    rotate = _op(f"{_KEY}/rotate", "post")
    assert f"**{grace} s**" in _text(f"{_KEY}/rotate", "post")
    ok = rotate["responses"]["200"]["content"]["application/json"]["examples"]["ok"]["value"]
    verified = datetime.fromisoformat(ok["new_key"]["last_verified_at"])
    assert datetime.fromisoformat(ok["overlap_until"]) - verified == timedelta(seconds=grace)


def test_suspected_compromise_takes_the_revoke_path_never_an_overlap() -> None:
    rotate = _text(f"{_KEY}/rotate", "post")
    assert "compromise" in rotate
    assert "`revokeApiKey`" in rotate


# --- No reveal path (SR-E27-11) -----------------------------------------------------------------


def test_no_reveal_path_and_no_response_carries_a_secret_bearing_field() -> None:
    assert [path for path in _PATHS if "reveal" in path] == []
    fields: set[str] = set()
    for item in _PATHS.values():
        for method, operation in item.items():
            if method == "parameters":
                continue
            for node in _walk(operation["responses"]):
                if isinstance(node, dict):
                    fields |= set(node.get("properties") or {})
                    assert node.get("format") != "password"
    assert "key_id_masked" in fields
    assert fields & _SECRET_FIELDS == set()
