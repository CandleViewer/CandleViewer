"""Contract (#2417, E27-X01 proposal P-2): the `exchange-accounts` paths say what C-2.8, SR-030a and
SR-005 require before E27-T03 and E27-S02 to E27-S04 mount their routes (C-6.1). One group per
scope item of #2417: the key gate (SR-E27-04), the key-id mask (SR-E27-03), the open-exposure
choice and local-only revocation (SR-E27-06, SR-E27-07), the fixed result vocabulary (SR-E27-08),
the single rotation overlap (SR-E27-10) and no reveal path (SR-E27-11), plus the cadence the key
gate re-runs on (C-12.2)."""

from __future__ import annotations

import inspect
import ipaddress
import json
import re
from collections.abc import Callable, Iterator, Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from candleviewer.accounts._permissions import reject_withdraw as m13_reject_withdraw
from candleviewer.accounts.errors import WithdrawPermissionError
from candleviewer.accounts.models import ApiKeyMetadata, ApiKeyRotation
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import OPENAPI_SPEC_PATH, load_openapi_spec
from candleviewer.exchange.bybit.mapping import map_ret_code
from candleviewer.ingestion.clock import ClockGuard
from candleviewer.secrets._permissions import reject_withdraw as m2_reject_withdraw
from candleviewer.secrets.errors import WithdrawPermissionRejected

_REPO_ROOT = Path(__file__).resolve().parents[4]
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
_CHOICES = ("leave_positions", "flatten_first")
_MIGRATION_0017 = (
    _REPO_ROOT / "services/api/candleviewer/migrations/versions/0017_exchange_accounts_api_keys.py"
)
_INTERNAL_SCHEMAS = _REPO_ROOT / "docs/plan/24-internal-schemas.md"
#: SR-E27-03: a key id is shown as `...` plus its last 4 characters, nothing more.
_MASK = r"^\.\.\.[A-Za-z0-9]{4}$"

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
#: The two codes of step 2: the withdrawal-or-transfer check runs first (M2 and M13 already raise
#: `key_withdraw_permission`), and the allow-list refuses every other right.
_RIGHT_RULES = ("key_withdraw_permission", "key_permission_not_allowed")
#: Every `createApiKey` rule code, with its step: E27-T03's list (#836) plus the two #2417 adds.
_RULE_STEPS = {
    "key_wrong_environment": 1,
    "key_withdraw_permission": 2,
    "key_permission_not_allowed": 2,
    "key_missing_scopes": 3,
    "key_not_read_only": 3,
    "key_not_unified": 4,
    "key_uid_mismatch": 4,
    "key_ip_whitelist_missing": 5,
    "key_ip_whitelist_mismatch": 5,
    "key_probe_failed": 7,
}
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


def _fold(text: str) -> str:
    """`text` with its line breaks folded, for phrase checks."""
    return " ".join(text.split())


def _text(path: str, method: str) -> str:
    """The operation description, folded."""
    return _fold(_op(path, method)["description"])


def _steps(description: str) -> dict[int, str]:
    """The numbered steps of a pipeline description, each folded onto one line."""
    blocks = re.split(r"\n(?=\d+\. )", description)
    return {
        int(match.group(1)): _fold(block[match.end() :].split("\n\n")[0])
        for block in blocks
        if (match := re.match(r"(\d+)\. ", block))
    }


def _sentence(text: str, code: str) -> str:
    """The one sentence of `text` that names `code`."""
    [sentence] = [part for part in re.split(r"(?<=\.) (?=[A-Z])", text) if f"`{code}`" in part]
    return sentence


def _gate_code(gate: Callable[[Mapping[str, object]], None], right: str) -> str | None:
    """The rule code a shipped gate raises for a key holding `right`, or None if it passes."""
    try:
        gate({"Wallet": [right]})
    except WithdrawPermissionRejected as refusal:  # M2, the credential broker
        return refusal.code
    except WithdrawPermissionError as refusal:  # M13, the account models
        return str(refusal)
    return None


def _shipped_rule(right: str) -> str:
    """The rule the shipped code gives `right`: M2 and M13 agree on withdrawal and transfer
    rights (SR-030a); any other right outside the allow-list is the allow-list's to refuse."""
    codes = {_gate_code(m2_reject_withdraw, right), _gate_code(m13_reject_withdraw, right)}
    assert len(codes) == 1, (right, codes)
    return codes.pop() or _RIGHT_RULES[1]


def _choice(path: str, method: str) -> dict[str, Any]:
    """The operation's `open_exposure` query parameter, `$ref` resolved."""
    parameters = [_deref(p["$ref"]) if "$ref" in p else p for p in _op(path, method)["parameters"]]
    [choice] = [p for p in parameters if p.get("name") == "open_exposure"]
    resolved: dict[str, Any] = choice
    return resolved


def _accepted(path: str, method: str) -> set[str]:
    schema = _choice(path, method)["schema"]
    return set((_deref(schema["$ref"]) if "$ref" in schema else schema)["enum"])


def _properties(node: object) -> Iterator[tuple[str, Any]]:
    """Every `(name, schema)` property pair anywhere under `node`, `$ref`s not followed."""
    if isinstance(node, dict):
        properties = node.get("properties")
        if isinstance(properties, dict):
            yield from properties.items()
        for value in node.values():
            yield from _properties(value)
    elif isinstance(node, list):
        for item in node:
            yield from _properties(item)


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
    gate = _steps(_op(_KEYS, "post")["description"])[2]
    assert "`ContractTrade` with `Order` and `Position`" in gate
    assert "`Derivatives` with `DerivativesTrade`" in gate
    named = {
        rule: {right for right in _REFUSED if f"`{right}`" in _sentence(gate, rule)}
        for rule in _RIGHT_RULES
    }
    shipped = {
        rule: {right for right in _REFUSED if _shipped_rule(right) == rule} for rule in _RIGHT_RULES
    }
    assert named == shipped
    assert all(shipped.values())
    assert "same verification pipeline as `createApiKey`" in _text(f"{_KEY}/rotate", "post")


def test_key_gate_names_each_rule_code_in_its_step() -> None:
    steps = _steps(_op(_KEYS, "post")["description"])
    assert sorted(steps) == [1, 2, 3, 4, 5, 6, 7]
    found = {rule: step for rule, step in _RULE_STEPS.items() if f"`{rule}`" in steps[step]}
    assert found == _RULE_STEPS


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
    # Every schema property whose name contains `key_id`, anywhere in the contract: a display
    # form (`key_id_*`) is the last-4 mask, a row reference (`*_key_id`) is a uuid.
    fields = [(name, schema) for name, schema in _properties(_SPEC) if "key_id" in name]
    displays = [(name, schema) for name, schema in fields if name.startswith("key_id_")]
    assert {name for name, _ in displays} == {"key_id_masked"}
    assert len(displays) >= 2  # ApiKey and SecuritySummary.keys[] (SCR-137)
    assert all(schema.get("pattern") == _MASK for _, schema in displays), displays
    references = [schema for name, schema in fields if name.endswith("_key_id")]
    assert references  # ApiKeyRotation.old_key_id
    assert all(schema.get("format") == "uuid" for schema in references), references
    masks = _all("key_id_masked")
    assert len(masks) >= 2
    assert all(re.fullmatch(_MASK, mask) for mask in masks), masks
    built = ApiKeyMetadata.model_construct(key_id_last4="AbC1").key_id_masked
    assert re.fullmatch(_MASK, built)
    listing = _text(_KEYS, "get")
    assert "last 4" in listing
    assert "first 4" not in listing


def test_generated_security_summary_refuses_a_key_id_longer_than_the_last_four() -> None:
    summary = api.SecuritySummary.model_validate({"keys": [{"key_id_masked": "...WxYz"}]})
    assert summary.keys is not None
    with pytest.raises(ValidationError):
        api.SecuritySummary.model_validate({"keys": [{"key_id_masked": "AbCd...WxYz"}]})


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


@pytest.mark.parametrize(("path", "method"), _EXPOSURE_OPS)
def test_open_exposure_example_names_no_choice_the_operation_refuses(
    path: str, method: str
) -> None:
    response = _SPEC["components"]["responses"]["OpenExposureConflict"]
    example = response["content"]["application/problem+json"]["examples"]["openExposure"]["value"]
    named = {choice for choice in _CHOICES if choice in example["detail"]}
    assert named <= _accepted(path, method)


@pytest.mark.parametrize(("path", "method"), _EXPOSURE_OPS)
def test_replay_fingerprint_covers_the_open_exposure_choice(path: str, method: str) -> None:
    assert _op(path, method)["x-idempotency"] == "optional"
    choice = _fold(_choice(path, method)["description"])
    assert "replay fingerprint covers this value as well as the method, path and body" in choice


def test_leave_positions_promises_no_stop_loss_a_position_lacks() -> None:
    choice = _fold(_SPEC["components"]["parameters"]["OpenExposure"]["description"])
    assert "still protected" not in choice
    assert "keeps the native stop-loss it carries (C-2.6)" in choice
    assert "`consequences.open_positions[].native_stop_present` shows any that has none" in choice
    assert "native_stop_present" in _SCHEMAS["Position"]["properties"]
    assert "open Owner/Security decision recorded on #2417" in choice


def test_consequence_summary_names_the_ticket_that_adds_its_up_front_read() -> None:
    # SCR-129 renders the summary before the dialog's confirm control; only the 409 carries it.
    ref = "#/components/schemas/AccountConsequenceSummary"
    holders = {name for name, schema in _SCHEMAS.items() if ref in json.dumps(schema, default=str)}
    assert holders == {"OpenExposureProblem"}
    assert ref not in json.dumps(_SPEC["paths"], default=str)
    summary = _fold(_SCHEMAS["AccountConsequenceSummary"]["description"])
    assert "only in the `409 open_exposure` answer" in summary
    assert "E27-S04 (#898) adds that operation in its own interface-first PR (C-6.1)" in summary


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
    # SR-E27-06 marks the vendor's "delete needs a fund right" reference as still to confirm.
    assert "(vendor reference, to be confirmed on demo by E27-S04)" in revoke


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


def test_clock_skew_warning_names_the_clock_guard_warning_threshold() -> None:
    warn_ms = inspect.signature(ClockGuard).parameters["warn_threshold_ms"].default
    warning = _fold(_SCHEMAS["KeyVerificationWarning"]["description"])
    assert f"absolute value is above {warn_ms} ms" in warning
    assert "`24-internal-schemas.md` §14.2 item 9" in warning


def test_probe_errors_have_their_own_table_and_timeout_refines_transport_error() -> None:
    probe = _fold(_SCHEMAS["KeyProbeError"]["description"])
    assert "`timeout`, which refines §8.6's `TRANSPORT_ERROR`" in probe
    assert "own translation table, owned and tested by E27-T03 (#836)" in probe
    # The stated reason holds: the adapter's mapping folds codes this vocabulary keeps apart.
    assert type(map_ret_code(10005, "")) is type(map_ret_code(10003, ""))
    assert type(map_ret_code(10010, "")) is type(map_ret_code(10003, ""))
    assert type(map_ret_code(10016, "")) is type(map_ret_code(10006, ""))
    assert type(map_ret_code(10019, "")) is type(map_ret_code(10006, ""))


# --- Re-check cadence and expiry window (C-12.2, SR-E27-05) --------------------------------------


def test_keys_are_rechecked_at_start_up_and_hourly_never_nightly() -> None:
    operations = [
        _text(path, method)
        for path, item in _PATHS.items()
        for method, operation in item.items()
        if method != "parameters" and "description" in operation
    ]
    assert [text for text in operations if "nightly" in text] == []
    assert "re-checked at start-up and hourly (C-12.2)" in _text(_KEYS, "post")
    assert "by the start-up and hourly self-check (C-12.2)" in _text(f"{_KEY}/test", "post")


def test_internal_key_rules_match_the_cadence_and_the_expiry_warning() -> None:
    doc = _INTERNAL_SCHEMAS.read_text(encoding="utf-8")
    rules = _fold(doc[doc.index("### 15.3 API key handling") : doc.index("### 15.4")])
    assert "every 24 h" not in rules
    assert "7 days" not in rules
    assert "re-verified at start-up, hourly (C-12.2) and on every auth failure" in rules
    assert "within 14 days raises the `key_expiring_soon` warning" in rules


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
