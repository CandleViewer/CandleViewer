"""Contract (#2417, E27-X01 proposal P-2): the `exchange-accounts` paths say what C-2.8, SR-030a and
SR-005 require before E27-T03 and E27-S02 to E27-S04 mount their routes (C-6.1). One group per
scope item of #2417: the key gate (SR-E27-04), the key-id mask (SR-E27-03), the open-exposure
choice, unknown exposure, failed reads and local-only revocation (SR-E27-06, SR-E27-07), the fixed
result vocabulary (SR-E27-08), the single rotation overlap (SR-E27-10) and no reveal path
(SR-E27-11), plus the cadence the key gate re-runs on (C-12.2)."""

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
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from candleviewer.accounts._permissions import reject_withdraw as m13_reject_withdraw
from candleviewer.accounts.errors import WithdrawPermissionError
from candleviewer.accounts.models import ApiKeyMetadata, ApiKeyRotation
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import OPENAPI_SPEC_PATH, load_openapi_spec
from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.exchange.bybit.mapping import map_ret_code
from candleviewer.ingestion.clock import ClockGuard
from candleviewer.secrets._permissions import reject_withdraw as m2_reject_withdraw
from candleviewer.secrets.broker import _SIGNABLE
from candleviewer.secrets.errors import WithdrawPermissionRejected
from candleviewer.ws._generated.error_codes import ErrorCode

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SPEC: Any = load_openapi_spec()  # a parsed YAML document, walked untyped
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
_REMEDIES = ("leave_positions", "fix_key")
_BASE = "urn:cv:openapi"
_MIGRATION_0017 = (
    _REPO_ROOT / "services/api/candleviewer/migrations/versions/0017_exchange_accounts_api_keys.py"
)
_DB_SCHEMA = _REPO_ROOT / "docs/plan/21-database-schema.md"
_INTERNAL_SCHEMAS = _REPO_ROOT / "docs/plan/24-internal-schemas.md"
_SECURITY_PROGRAM = _REPO_ROOT / "docs/plan/04-security-program.md"
_ADR_0009 = _REPO_ROOT / "docs/plan/27-adrs/ADR-0009-secrets-and-key-management.md"
_USER_STORIES = _REPO_ROOT / "docs/plan/11-user-stories.md"
#: D4 of #2417: the Owner's confirmation of the `leave_positions` refusal is tracked here.
_STOP_LOSS_DECISION = "#2903"
#: The operations that accept `leave_positions`; delete takes `flatten_first` only.
_LEAVE_OPS = [(_KEY, "delete"), (_ACCOUNT, "patch")]
#: The `409` examples of `OpenExposureConflict`, with the operations that can return each.
_ANSWERED_BY = {
    "openExposure": ("deleteExchangeAccount", "updateExchangeAccount", "revokeApiKey"),
    "leavePositionsRefused": ("updateExchangeAccount", "revokeApiKey"),
    "exposureUnknownDead": ("deleteExchangeAccount", "updateExchangeAccount", "revokeApiKey"),
    "exposureUnknownFixable": ("deleteExchangeAccount", "updateExchangeAccount", "revokeApiKey"),
}
#: D3 of #2417: what each class of unknown exposure tells the client to do (`ExposureRemedy`): a
#: dead account is disabled (`leave_positions`), a fixable one waits for its key (`fix_key`).
_REMEDY = {"**Dead.**": "leave_positions", "**Fixable.**": "fix_key"}
_REMEDY_EXAMPLE = {"exposureUnknownDead": "leave_positions", "exposureUnknownFixable": "fix_key"}
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
#: D3 of #2417, round 2: only a credential the exchange no longer accepts makes a key dead.
_DEAD_KEY_ERRORS = ("auth_error",)
#: Refusals the Owner puts right at the Bybit dashboard (the egress IP, SR-033; the key's rights):
#: such a key is not dead.
_FIXABLE_KEY_ERRORS = ("ip_not_allowed", "permission_denied")
#: Every other probe error is a failed read: it says nothing about the key.
_FAILED_READ_ERRORS = tuple(
    error for error in _PROBE_ERRORS if error not in _DEAD_KEY_ERRORS + _FIXABLE_KEY_ERRORS
)
#: What a failed read is answered with: no answer at all is a 503, an error answer a 502.
_FAILED_READ_UNAVAILABLE = ("timeout", "transport_error")
_FAILED_READ_BAD_GATEWAY = (
    "clock_drift",
    "rate_limited",
    "service_unavailable",
    "exchange_unknown",
)
#: The only key statuses a signed call may use (21-database-schema.md §3.2.3a, secrets/broker.py).
_SIGNABLE_STATUSES = ("active", "rotating")
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


def _open_exposure() -> str:
    """The canonical `open_exposure` description, folded."""
    return _fold(_SPEC["components"]["parameters"]["OpenExposure"]["description"])


def _section(lead: str) -> str:
    """The folded paragraph or bullet of the canonical description that begins with `lead`."""
    raw = _SPEC["components"]["parameters"]["OpenExposure"]["description"]
    [block] = [
        part for part in re.split(r"\n\n|\n(?=- )", raw) if part.removeprefix("- ").startswith(lead)
    ]
    return _fold(block)


def _conflict() -> str:
    """The `OpenExposureConflict` response description, folded."""
    return _fold(_SPEC["components"]["responses"]["OpenExposureConflict"]["description"])


def _registered() -> dict[str, Any]:
    """The `x-error-codes` registry, by code."""
    return {entry["code"]: entry for entry in _SPEC["x-error-codes"]}


def _steps(description: str) -> dict[int, str]:
    """The numbered steps of a pipeline description, each folded onto one line."""
    blocks = re.split(r"\n(?=\d+\. )", description)
    return {
        int(match.group(1)): _fold(block[match.end() :].split("\n\n")[0])
        for block in blocks
        if (match := re.match(r"(\d+)\. ", block))
    }


def _and(errors: tuple[str, ...]) -> str:
    """`errors` as the contract lists them: "`a`, `b` and `c`"."""
    return ", ".join(f"`{error}`" for error in errors[:-1]) + f" and `{errors[-1]}`"


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


def _described(*keys: str | int) -> str:
    """The folded `description` found by walking `keys` down from the spec root."""
    node: Any = _SPEC
    for key in keys:
        node = node[key]
    return _fold(node["description"])


_SCHEMA = ("components", "schemas")
_SUMMARY = (*_SCHEMA, "AccountConsequenceSummary")
#: Where each rule sentence is written, with a core phrase of every one that no other test quotes,
#: joined by "|": a deletion check, one sentence at a time over every prose string this change adds
#: or edits, found each of them unpinned (deleting it left every other test green).
_DESCRIBED = (
    (
        ("paths", _ACCOUNT, "patch"),
        "must carry an `open_exposure` choice (SR-E27-07)|never to a mode change",
    ),
    (
        ("paths", _ACCOUNT, "delete"),
        "never deleted while it holds open positions, working orders or running emulated algos"
        "|and deleted only once it is flat",
    ),
    (
        ("paths", _ACCOUNT, "delete", "parameters", 1),
        "deletion never leaves exposure behind, so `leave_positions` is not accepted here",
    ),
    (
        ("paths", _KEYS, "post"),
        "only persisted if every check passes"
        "|The same key gate (SR-E27-04) applies to `rotateApiKey`"
        "|never retried on another environment's host"
        "|**Permission allow-list** (C-2.8, SR-030a, #2270)"
        "|must report `readOnly: 0` and hold"
        "|mandatory in every environment (C-2.8, owner decision #5)"
        "|Expiry, if set, must be at least 14 days away",
    ),
    (
        ("paths", _KEY, "delete"),
        "When no other `active` key remains and the account holds open positions",
    ),
    (
        ("paths", f"{_KEY}/rotate", "post"),
        "The overlap is one fixed value, the `api_key_rotations.grace_seconds` of the rotation row"
        "|and no request can change it",
    ),
    (("paths", f"{_KEY}/test", "post"), "request fragment is ever echoed (SR-E27-08)"),
    (
        ("components", "parameters", "OpenExposure"),
        "The explicit choice SR-E27-07 requires before revoking an account's last active key"
        "|close its positions reduce-only), then act; if the account is still not flat, the "
        "action is not carried out"
        "|Without the parameter such a request is `409 open_exposure`"
        "|Ignored when the account holds no exposure"
        "|While a signable key can read it, the choices work as above"
        "|Whether the Owner can fix the refusal decides the answer, and the `409 exposure_unknown` "
        "says which in `remedy` (`ExposureRemedy`, a closed set, always present on it and on no "
        "other problem):",
    ),
    (
        ("components", "responses", "OpenExposureConflict"),
        "so the revoke, disable or delete was not carried out"
        "|it always carries `consequences`, the summary the caller shows",
    ),
    (
        (*_SCHEMA, "UpdateExchangeAccountRequest", "properties", "enabled"),
        "with open exposure it needs the `open_exposure` query choice",
    ),
    ((*_SCHEMA, "OpenExposureChoice"), "see `components.parameters.OpenExposure`"),
    (
        _SUMMARY,
        "so no partial picture is shown|Confidential: served only under the operation's own "
        "permission and scope",
    ),
    ((*_SUMMARY, "properties", "open_positions"), "with its native stop-loss state"),
    ((*_SUMMARY, "properties", "working_orders"), "Orders working on the exchange"),
    ((*_SUMMARY, "properties", "assigned_users"), "through `user_account_access`"),
    ((*_SUMMARY, "properties", "armed_rules"), "the action disarms them"),
    (
        (*_SCHEMA, "ExposureRemedy"),
        "What the client does after `409 exposure_unknown`"
        "|`components.parameters.OpenExposure` says which applies"
        "|send the disable or the revoke again with `open_exposure=leave_positions`"
        "|a delete is not sent again, the account is disabled instead"
        "|`fix_key`: put the key right at the exchange, then send the request again"
        "|It advises the SCR-129 dialog: the choice stays the Owner's (SR-E27-07)",
    ),
    (
        (*_SCHEMA, "ApiKey", "properties", "key_id_masked"),
        "At most the last 4 characters of the key id|`...` plus `key_id_last4` (SR-E27-03)"
        "|The rest is never stored in clear.",
    ),
    (
        (*_SCHEMA, "SecuritySummary", "properties", "keys", "items", "properties", "key_id_masked"),
        "as `ApiKey.key_id_masked`",
    ),
    (
        (*_SCHEMA, "KeyVerification", "properties", "uta"),
        "the deprecated `unified` field is never read",
    ),
    ((*_SCHEMA, "KeyVerification", "properties", "read_only"), "which alone decides write access"),
    (
        (*_SCHEMA, "KeyVerification", "properties", "permissions"),
        "Every right must be on the `createApiKey` allow-list (step 2)",
    ),
    (
        (*_SCHEMA, "KeyVerification", "properties", "ip_whitelist_matches_egress"),
        "every entry is the configured egress IP itself (no wildcard, no range)",
    ),
    (
        (*_SCHEMA, "KeyVerificationWarning"),
        "Closed vocabulary (SR-E27-08). `key_expiring_soon`: the key expires within 14 days",
    ),
    (
        (*_SCHEMA, "KeyProbeError"),
        "Closed vocabulary for a failed probe (SR-E27-08)"
        "|`ip_not_allowed`: `10010` or HTTP 403"
        "|`rate_limited`: `10006`, `10018`, `10429` or HTTP 429"
        "|`service_unavailable`: `10016`, `10019` or HTTP 5xx"
        "|`exchange_unknown`: any other non-zero `retCode` (the code itself is in `ret_code`)"
        "|No exchange error text, header, URL or request fragment is echoed.",
    ),
    (
        (*_SCHEMA, "RotateApiKeyRequest"),
        "No overlap field: the rotation overlap is one fixed value (`rotateApiKey`, SR-E27-10)",
    ),
)


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


def _conflict_examples() -> dict[str, Any]:
    response = _SPEC["components"]["responses"]["OpenExposureConflict"]
    examples: dict[str, Any] = response["content"]["application/problem+json"]["examples"]
    return examples


def _operation_ids() -> dict[str, tuple[str, str]]:
    return {_op(path, method)["operationId"]: (path, method) for path, method in _EXPOSURE_OPS}


@pytest.mark.parametrize(("path", "method"), _LEAVE_OPS)
def test_leave_positions_refusal_is_defined_once_and_the_operation_points_at_it(
    path: str, method: str
) -> None:
    assert "leave_positions" in _accepted(path, method)
    text = _text(path, method)
    assert "the `leave_positions` stop-loss refusal" in text
    assert "are defined once, at `components.parameters.OpenExposure`" in text
    assert "is refused with `409 open_exposure` while" not in text


def test_delete_never_meets_the_stop_loss_refusal_because_it_cannot_leave_positions() -> None:
    assert "leave_positions" not in _accepted(_ACCOUNT, "delete")
    assert "is refused with `409 open_exposure` while" not in _text(_ACCOUNT, "delete")


def test_open_exposure_parameter_refuses_leave_positions_for_an_unprotected_position() -> None:
    choice = _open_exposure()
    assert (
        "It is refused with `409 open_exposure` while any open position has no native "
        "stop-loss (`native_stop_present: false`)"
    ) in choice
    assert "has none:" not in choice  # "none" could be read as "no position"
    assert "nothing can re-assert a missing stop" in choice
    assert "the caller resends with `flatten_first`" in choice
    assert f"confirmation of this refusal is tracked on {_STOP_LOSS_DECISION}" in choice
    assert "relaxing it later is non-breaking" in choice
    assert "recorded on #2417" not in choice
    assert "open Owner/Security decision" not in choice


def test_leave_positions_refusal_example_lists_the_position_without_a_stop() -> None:
    example = _conflict_examples()["leavePositionsRefused"]["value"]
    problem = api.OpenExposureProblem.model_validate(example)
    assert (problem.code, problem.status) == ("open_exposure", 409)
    assert example["type"].endswith("/errors/open_exposure")
    registered = {entry["code"]: entry for entry in _SPEC["x-error-codes"]}
    assert example["title"] == registered["open_exposure"]["title"]
    assert problem.consequences is not None
    unprotected = [p for p in problem.consequences.open_positions if p.native_stop_present is False]
    assert unprotected
    assert all(p.stop_loss is None for p in unprotected)
    assert "open_exposure=flatten_first" in example["detail"]


def test_each_open_exposure_example_names_the_operations_that_can_return_it() -> None:
    examples = _conflict_examples()
    assert set(examples) == set(_ANSWERED_BY)
    operations = _operation_ids()
    for name, answering in _ANSWERED_BY.items():
        summary = examples[name]["summary"]
        assert {operation for operation in operations if operation in summary} == set(answering)
        named = {choice for choice in _CHOICES if choice in examples[name]["value"]["detail"]}
        for operation in answering:
            assert named <= _accepted(*operations[operation]), (name, operation)


@pytest.mark.parametrize(
    ("keys", "phrases"),
    [pytest.param(keys, phrases, id="/".join(map(str, keys[-2:]))) for keys, phrases in _DESCRIBED],
)
def test_every_rule_sentence_of_the_contract_is_quoted_by_a_test(
    keys: tuple[str | int, ...], phrases: str
) -> None:
    text = _described(*keys)
    for phrase in phrases.split("|"):
        assert phrase in text, (keys, phrase)


def test_the_open_exposure_example_counts_what_its_summary_lists() -> None:
    example = _conflict_examples()["openExposure"]["value"]
    summary = example["consequences"]
    assert example["detail"] == (
        f"{len(summary['open_positions'])} open position, {summary['working_orders']} working "
        f"orders and {summary['running_algos']} running algo; resend with an open_exposure choice."
    )


# --- Unknown exposure and a failed read (D3 of #2417, round 2) ----------------------------------


def _restating_texts() -> dict[str, str]:
    """Every text outside the canonical definition that bears on unknown exposure."""
    texts = {f"{method} {path}": _text(path, method) for path, method in _EXPOSURE_OPS}
    texts["OpenExposureConflict"] = _conflict()
    texts["exposure_unknown title"] = _registered()["exposure_unknown"]["title"]
    for schema in ("OpenExposureProblem", "ExposureRemedy", "KeyStatus"):
        texts[schema] = _fold(_SCHEMAS[schema]["description"])
    for name, example in _conflict_examples().items():
        value = example["value"]
        texts[f"example {name}"] = _fold(f"{example['summary']} {value['title']} {value['detail']}")
    return texts


def test_open_exposure_is_the_one_definition_and_the_operations_point_at_it() -> None:
    assert (
        "This is the one definition of the choice, of the stop-loss refusal, of unknown exposure, "
        "of its remedy and of a failed read: `updateExchangeAccount`, `revokeApiKey` and "
        "`deleteExchangeAccount` point here and add only what is specific to them."
    ) in _open_exposure()
    for path, method in _EXPOSURE_OPS:
        assert "`components.parameters.OpenExposure`" in _text(path, method)
    # What makes a key or an account dead is stated there and nowhere else: no other text names
    # the probe errors that decide it, defines "dead" again or calls anything dead (the one use
    # is revoke's "the account is not dead", which applies the definition to a rotating key).
    defining = ("auth_error", "ip_not_allowed", "permission_denied", "makes a key dead")
    for where, text in _restating_texts().items():
        for term in defining:
            assert term not in text, (where, term)
        assert "dead" not in text.replace("the account is not dead", ""), where


def test_a_key_is_dead_only_when_the_exchange_no_longer_accepts_its_credential() -> None:
    assert set(_DEAD_KEY_ERRORS) <= set(_SCHEMAS["KeyProbeError"]["enum"])
    dead = _section("**Dead.**")
    assert (
        "Only a credential the exchange no longer accepts (`auth_error`) makes a key dead, and "
        "an account is dead when every one of its signable keys is dead, or when it has none"
    ) in dead
    assert not any(f"`{error}`" in dead for error in _FIXABLE_KEY_ERRORS + _FAILED_READ_ERRORS)
    assert "its exposure is unknown, not none" in _section("**Unknown exposure.**")


def test_the_exposure_is_read_only_with_signable_keys_and_the_other_statuses_are_named() -> None:
    # A pending, expired, invalid or revoked key is never signed with: the broker refuses it
    # (`secrets/broker.py`), so the contract may not probe with it either.
    assert set(_SIGNABLE_STATUSES) == set(_SIGNABLE)
    statuses = _SCHEMAS["KeyStatus"]["enum"]
    excluded = [status for status in statuses if status not in _SIGNABLE_STATUSES]
    assert sorted(excluded) == ["expired", "invalid", "pending", "revoked"]
    unknown = _section("**Unknown exposure.**")
    assert (
        "The exposure is read from the exchange for each request with the account's signable "
        "keys, `active` and `rotating` (`21-database-schema.md` §3.2.3a), whatever the exchange "
        "last said about them"
    ) in unknown
    assert "a `pending`, `expired`, `invalid` or `revoked` key is never used to read it" in unknown
    assert {status for status in statuses if f"`{status}`" in unknown} == set(statuses)
    assert "every key counted" not in unknown
    doc = _DB_SCHEMA.read_text(encoding="utf-8")
    keys = doc[doc.index("#### 3.2.3a") : doc.index("#### 3.2.4")]
    assert "Only `status IN ('active','rotating')` rows are signable" in _fold(keys)


def test_an_account_with_no_signable_key_has_unknown_exposure_and_counts_as_dead() -> None:
    unknown = _section("**Unknown exposure.**")
    assert (
        "An account with no signable key cannot read its exposure: it is unknown and counts as "
        "dead (disabled with `leave_positions`, never deleted)"
    ) in unknown
    assert (
        "An account that never had a key is disable-only on purpose: nothing can show that it "
        'holds no exposure, and "no key" is never taken for "no exposure"'
    ) in unknown
    assert "missing" in _SCHEMAS["ExchangeAccount"]["properties"]["key_status"]["enum"]
    assert "A dead account is disabled, never deleted" in _section("**Dead.**")


def test_a_fixable_refusal_answers_exposure_unknown_for_every_choice() -> None:
    fixable = _section("**Fixable.**")
    assert (
        "`ip_not_allowed` (the egress IP drifted from the key's whitelist, SR-033) and "
        "`permission_denied` are put right at the Bybit dashboard, so such a key is not dead"
    ) in fixable
    # "any", not "every": one fixable key keeps a mixed account (with a dead one) fixable.
    # "every signable key is refused", not "no key can read it": a failed read is not a refusal.
    assert "While every signable key is refused and any answers one of them" in fixable
    assert (
        "revoke, disable and delete answer `409 exposure_unknown` with `remedy: fix_key` for every "
        "`open_exposure` choice, `leave_positions` included"
    ) in fixable
    assert (
        "fix the key first, then the OMS re-asserts the stop and `flatten_first` can run"
    ) in fixable
    assert not any(f"`{error}`" in fixable for error in _DEAD_KEY_ERRORS + _FAILED_READ_ERRORS)


def test_the_stop_loss_refusal_is_lifted_only_for_a_dead_account() -> None:
    dead = _section("**Dead.**")
    assert (
        "`flatten_first`, or no choice, is then `409 exposure_unknown` with "
        "`remedy: leave_positions`, and nothing changes"
    ) in dead
    assert (
        "`leave_positions` is carried out: it is how a dead account is disabled or its last key "
        "revoked"
    ) in dead
    assert (
        "the stop-loss refusal is lifted only for a dead account, because no stop can be "
        "re-asserted there and `flatten_first` cannot run"
    ) in dead
    assert "stop-loss refusal" not in _section("**Fixable.**")


def test_the_dead_path_audits_why_the_stop_loss_refusal_was_lifted() -> None:
    # It is the only path that lifts a C-2.6 refusal, so its audit record says why (C-2.9).
    dead = _section("**Dead.**")
    assert (
        "The audit record of that disable or revoke (`account.disabled` or `api_key.revoke`, "
        "written ahead of the change, C-2.9) carries the code `exposure_unknown`, the "
        "`KeyProbeError` of each signable key (none for an account without one) and that the "
        "stop-loss refusal was lifted"
    ) in dead
    # Both names are registered: `api_key.revoke` in the code registry, `account.disabled` in the
    # closed vocabulary of 24-internal-schemas.md §15.5 (the threat model gives its registration
    # to E27-S04, the ticket that mounts the route). The spelling `accounts.disable` is neither.
    doc = _INTERNAL_SCHEMAS.read_text(encoding="utf-8")
    vocabulary = doc[doc.index("### 15.5 Audited action vocabulary") : doc.index("## 16.")]
    assert "`account.disabled`" in vocabulary
    assert "api_key.revoke" in AUDIT_ACTIONS
    assert "accounts.disable" not in OPENAPI_SPEC_PATH.read_text(encoding="utf-8")


def test_every_probe_error_is_named_in_exactly_one_of_dead_fixable_or_failed_read() -> None:
    probe = _SCHEMAS["KeyProbeError"]["enum"]

    def named(section: str) -> set[str]:
        return {error for error in probe if f"`{error}`" in section}

    assert named(_section("**Dead.**")) == set(_DEAD_KEY_ERRORS)
    assert named(_section("**Fixable.**")) == set(_FIXABLE_KEY_ERRORS)
    assert named(_section("**A failed read.**")) == set(_FAILED_READ_ERRORS)
    assert named(_section("**Unknown exposure.**")) == set(_DEAD_KEY_ERRORS + _FIXABLE_KEY_ERRORS)
    groups = (_DEAD_KEY_ERRORS, _FIXABLE_KEY_ERRORS, _FAILED_READ_ERRORS)
    assert sorted(error for group in groups for error in group) == sorted(probe)


def test_a_transient_read_failure_is_never_no_exposure_and_never_dead() -> None:
    failed = _section("**A failed read.**")
    assert (
        'A transient failure to read the exposure is never "no exposure" and never "dead"'
    ) in failed
    assert (
        "so an account is not dead while any of its signable keys answers one of them"
    ) in failed
    assert (
        "Such an answer is not a refusal, so while any signable key gives one neither the dead "
        "nor the fixable rule applies"
    ) in failed
    assert (
        "When no signable key reads the exposure, the request fails closed: nothing is revoked, "
        "disabled or deleted, and the answer is a retryable error of its own, decided by the "
        "error of the key"
    ) in failed


def test_the_rules_apply_in_one_stated_order_a_successful_read_first_dead_last() -> None:
    assert _open_exposure().count("**Order.**") == 1
    order = _section("**Order.**")
    clauses = (
        "(1) a signable key reads the exposure, and the choices work as above, whatever another "
        "key answers",
        "(2) else any signable key gives a failed read, and the request fails closed",
        "(3) else any signable key answers a fixable refusal",
        "(4) else the account is dead",
    )
    found = [order.find(clause) for clause in clauses]
    assert -1 not in found, [clause for clause, at in zip(clauses, found, strict=True) if at < 0]
    assert found == sorted(found)
    assert "the first of these decides" in order


def test_a_failed_read_names_the_answer_each_probe_error_gets_and_echoes_no_exchange_text() -> None:
    failed = _section("**A failed read.**")
    assert set(_FAILED_READ_UNAVAILABLE) | set(_FAILED_READ_BAD_GATEWAY) == set(_FAILED_READ_ERRORS)
    assert not set(_FAILED_READ_UNAVAILABLE) & set(_FAILED_READ_BAD_GATEWAY)
    assert (
        f"{_and(_FAILED_READ_UNAVAILABLE)}, where the exchange gave no answer, give "
        "`503 exchange_unavailable` with `Retry-After`"
    ) in failed
    assert (
        f"{_and(_FAILED_READ_BAD_GATEWAY)}, where it answered with an error, give "
        "`502 exchange_error`"
    ) in failed
    assert "Keys that fail both ways give the `503`" in failed
    # A `timeout` is a 503, not the registry's 504: these operations declare no 504.
    assert "a `timeout` is a `503` here, not the registry's `504 timeout`" in failed
    assert _registered()["timeout"]["status"] == 504
    assert all("504" not in _op(path, method)["responses"] for path, method in _EXPOSURE_OPS)
    assert "A failed read has no `remedy`: the caller retries." in failed
    # "No answer" is what the probe vocabulary says of exactly these two errors.
    probe = _fold(_SCHEMAS["KeyProbeError"]["description"])
    assert "`transport_error`: the connection failed or was reset" in probe
    assert "`timeout`, which refines §8.6's `TRANSPORT_ERROR`: no answer before the" in probe
    # Problem.exchange also holds ret_msg, Bybit's free text; a probe never echoes it (SR-E27-08).
    exchange = _SCHEMAS["Problem"]["properties"]["exchange"]["properties"]
    assert set(exchange) == {"ret_code", "ret_msg", "endpoint", "request_id"}
    assert (
        "Neither answer echoes exchange text: `Problem.exchange` holds `ret_code` only (omitted "
        "when the exchange sent none), never "
        "`ret_msg`, `endpoint`, `request_id` or any other exchange text, header, URL or request "
        "fragment (SR-E27-08)"
    ) in failed


@pytest.mark.parametrize(("path", "method"), _EXPOSURE_OPS)
def test_the_operations_declare_the_retryable_answers_of_a_failed_read(
    path: str, method: str
) -> None:
    responses = _op(path, method)["responses"]
    assert responses["502"] == {"$ref": "#/components/responses/ExchangeError"}
    assert responses["503"] == {"$ref": "#/components/responses/ServiceUnavailable"}


@pytest.mark.parametrize(("path", "method"), _EXPOSURE_OPS)
def test_a_failed_read_is_never_stored_for_replay_so_the_same_key_retries_the_read(
    path: str, method: str
) -> None:
    # The global rule stores "the original response" for 24 h with no status restriction, so a
    # stored 503 would make the account un-disableable under that key.
    choice = _fold(_choice(path, method)["description"])
    assert "A `502` or `503` of a failed read is never stored for replay" in choice
    assert (
        "A `502` or `503` of a failed read is never stored for replay: the identical request "
        "re-sent with the same `Idempotency-Key` is a first submission, which reads the exposure "
        "again and is not answered from the idempotency store (no `Idempotency-Replayed`)"
    ) in _open_exposure()


def test_the_failed_read_answers_are_the_existing_retryable_problem_shapes() -> None:
    registered = _registered()
    for code, status in (("exchange_error", 502), ("exchange_unavailable", 503)):
        assert (registered[code]["status"], registered[code]["retryable"]) == (status, True)
    components = _SPEC["components"]["responses"]
    bad_gateway = components["ExchangeError"]["content"]["application/problem+json"]
    assert bad_gateway["examples"]["bybitReject"]["value"]["code"] == "exchange_error"
    unavailable = components["ServiceUnavailable"]
    assert "Retry-After" in unavailable["headers"]
    shapes = unavailable["content"]["application/problem+json"]["examples"]
    assert shapes["wsDown"]["value"]["code"] == "exchange_unavailable"


def test_delete_answers_exposure_unknown_whatever_open_exposure_is_sent() -> None:
    delete = _text(_ACCOUNT, "delete")
    assert (
        "Whatever `open_exposure` the request carries, the answer is `409 exposure_unknown` and "
        "nothing changes"
    ) in delete
    assert _accepted(_ACCOUNT, "delete") == {"flatten_first"}  # no choice gets past it
    assert _section("`deleteExchangeAccount` takes only `flatten_first`") == (
        "`deleteExchangeAccount` takes only `flatten_first`, so in both cases it answers "
        "`409 exposure_unknown`, whatever it carries; there `remedy: leave_positions` means "
        "disabling the account instead (`updateExchangeAccount` with `enabled: false`)."
    )


def test_an_account_with_unknown_exposure_is_never_deleted() -> None:
    delete = _text(_ACCOUNT, "delete")
    assert (
        "An account whose exposure is unknown is never deleted: it is not known to be flat"
        in delete
    )
    assert (
        "its `remedy` says whether the account can be disabled instead (`updateExchangeAccount` "
        "with `enabled: false`) or a key is to be fixed first, and "
        "`components.parameters.OpenExposure` defines both, and what a failed read is answered with"
    ) in delete
    assert "A dead account is disabled, never deleted" in _section("**Dead.**")


def test_conflict_answers_exposure_unknown_for_flatten_first_or_no_choice() -> None:
    conflict = _conflict()
    assert "`deleteExchangeAccount` answers it whatever the request carries" in conflict
    assert (
        "`updateExchangeAccount` (disable) and `revokeApiKey` answer it when the request carries "
        "`flatten_first` or no choice, and for `leave_positions` too while a key can still be fixed"
    ) in conflict
    assert "it always carries `remedy` and no `consequences`" in conflict


def test_revoke_counts_a_rotating_key_and_a_usable_one_means_the_account_is_not_dead() -> None:
    assert "rotating" in _SCHEMAS["KeyStatus"]["enum"]
    revoke = _text(_KEY, "delete")
    assert (
        "Every signable key of the account counts in that definition, a `rotating` key too: "
        "while a `rotating` key is usable the account is not dead, whatever the key being "
        "revoked answers"
    ) in revoke


def test_exposure_unknown_is_not_positions_unknown_and_the_contract_says_why() -> None:
    registered = _registered()
    assert registered["positions_unknown"]["status"] == 409
    assert "acknowledge_unknown_positions" in registered["positions_unknown"]["title"]
    reset = _SPEC["paths"]["/users/{userId}/mfa/reset"]["post"]
    flag = reset["requestBody"]["content"]["application/json"]["schema"]["properties"]
    assert "acknowledge_unknown_positions" in flag  # the E42 user lifecycle takes the flag
    # The operations here take none: not as a query parameter, not in the one request body.
    for path, method in _EXPOSURE_OPS:
        parameters = [
            _deref(p["$ref"]) if "$ref" in p else p for p in _op(path, method)["parameters"]
        ]
        assert "acknowledge_unknown_positions" not in {p["name"] for p in parameters}
    assert (
        "acknowledge_unknown_positions"
        not in _SCHEMAS["UpdateExchangeAccountRequest"]["properties"]
    )
    why = _section("`exposure_unknown` is not")
    assert ". " not in why  # one sentence
    assert why == (
        "`exposure_unknown` is not the `409 positions_unknown` of the user lifecycle (E42), whose "
        "remedy is to resend with `acknowledge_unknown_positions=true`: these operations have no "
        "acknowledge parameter and delete never proceeds, so that remedy does not exist here."
    )


def test_exposure_unknown_is_a_registered_409_with_an_example_per_class_and_no_summary() -> None:
    entry = _registered()["exposure_unknown"]
    assert (entry["status"], entry["retryable"]) == (409, False)
    assert ErrorCode.EXPOSURE_UNKNOWN.value == "exposure_unknown"
    # The title holds for every way the exposure cannot be read: the exchange refuses each
    # signable key, or the account has none (a key that is not signable is never probed).
    assert "none of its keys can be used to read it" in entry["title"]
    assert "the exchange refuses" not in entry["title"]
    for name, remedy in _REMEDY_EXAMPLE.items():
        example = _conflict_examples()[name]["value"]
        problem = api.OpenExposureProblem.model_validate(example)
        assert (problem.code, problem.status, problem.remedy) == ("exposure_unknown", 409, remedy)
        assert example["type"].endswith("/errors/exposure_unknown")
        assert example["title"] == entry["title"]
        assert problem.consequences is None
        assert "consequences" not in example
    # Each detail says why the exposure cannot be read: no signable key, or a key to put right.
    details = {name: _conflict_examples()[name]["value"]["detail"] for name in _REMEDY_EXAMPLE}
    assert "has no signable key" in details["exposureUnknownDead"]
    assert "until the key is put right" in details["exposureUnknownFixable"]
    schema = _fold(_SCHEMAS["OpenExposureProblem"]["description"])
    assert (
        "The `409` problem of the revoke, disable and delete operations. `consequences` is "
        "present exactly when `code` is `open_exposure`, and `remedy` exactly when `code` is "
        "`exposure_unknown`, which carries no `consequences` because the exposure cannot be read"
    ) in schema


def _problem_validator() -> Draft202012Validator:
    """A validator for `OpenExposureProblem` with the whole spec as its `$ref` registry."""
    resource = Resource.from_contents(_SPEC, default_specification=DRAFT202012)
    return Draft202012Validator(
        {"$ref": f"{_BASE}#/components/schemas/OpenExposureProblem"},
        registry=Registry().with_resource(_BASE, resource),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )


def test_exposure_unknown_carries_a_required_closed_remedy_and_no_other_problem_does() -> None:
    remedy = _SCHEMAS["ExposureRemedy"]
    assert (remedy["type"], remedy["enum"]) == ("string", list(_REMEDIES))
    assert set(_REMEDIES) & set(_CHOICES) == {"leave_positions"}  # the contract's own vocabulary
    assert "Closed: a new value is a breaking change (C-6.3)" in _fold(remedy["description"])
    examples = {name: example["value"] for name, example in _conflict_examples().items()}
    validator = _problem_validator()
    assert all(validator.is_valid(value) for value in examples.values())
    summary = examples["openExposure"]["consequences"]
    for name in _REMEDY_EXAMPLE:
        value = examples[name]
        assert not validator.is_valid({k: v for k, v in value.items() if k != "remedy"})
        assert not validator.is_valid({**value, "consequences": summary})
        for outside in ("wait", "flatten_first"):  # closed: not even a choice is a remedy
            assert not validator.is_valid({**value, "remedy": outside}), outside
    for name in ("openExposure", "leavePositionsRefused"):
        value = examples[name]
        assert not validator.is_valid({k: v for k, v in value.items() if k != "consequences"})
        assert not validator.is_valid({**value, "remedy": "fix_key"})
    other = {"type": "https://candleviewer.local/errors/conflict", "title": "t", "status": 409}
    assert validator.is_valid({**other, "code": "conflict"})
    assert not validator.is_valid({**other, "code": "conflict", "remedy": "fix_key"})
    assert not validator.is_valid({**other, "code": "conflict", "consequences": summary})


def test_the_remedy_follows_the_class_of_the_account_in_the_text_and_in_the_examples() -> None:
    for lead, remedy in _REMEDY.items():
        assert re.findall(r"`remedy: (\w+)`", _section(lead)) == [remedy], lead
    assert set(_REMEDY.values()) == set(_REMEDIES)  # every remedy is some class's, and no more
    for name, remedy in _REMEDY_EXAMPLE.items():
        assert _conflict_examples()[name]["value"]["remedy"] == remedy
    # A failed read has none: it is the 502 or 503 problem, whose shape has no such member.
    assert "remedy" not in _SCHEMAS["Problem"]["properties"]
    assert "A failed read has no `remedy`" in _section("**A failed read.**")


def test_key_status_invalid_is_a_rejected_credential_and_not_signable() -> None:
    status = _fold(_SCHEMAS["KeyStatus"]["description"])
    assert "Only `active` and `rotating` keys are signable" in status
    assert (
        "`invalid`: the exchange rejected the key's credential (retCode `10003` or `10004`), "
        "which `24-internal-schemas.md` §8.6 answers by marking the key `invalid`; it is not "
        "signable"
    ) in status
    assert "invalid" in _SCHEMAS["KeyStatus"]["enum"]
    assert "invalid" not in _SIGNABLE_STATUSES
    # §8.6 marks a key `invalid` on the two credential refusals that the probe calls `auth_error`.
    doc = _INTERNAL_SCHEMAS.read_text(encoding="utf-8")
    table = doc[doc.index("| Bybit retCode") :]
    rows = {code: _fold(row) for code, row in re.findall(r"^\| `(\d+)` *\|(.*)$", table, re.M)}
    assert "`AUTH_ERROR`" in rows["10003"]
    assert "Mark key `invalid`" in rows["10003"]
    assert "`AUTH_ERROR`" in rows["10004"]
    assert rows["10004"].endswith("| Same |")
    probe = _fold(_SCHEMAS["KeyProbeError"]["description"])
    assert "`auth_error`: key or signature refused (`10003`, `10004`)" in probe


def test_exposure_unknown_is_answered_only_by_revoke_disable_and_delete() -> None:
    conflict = _conflict()
    for operation in _operation_ids():
        assert f"`{operation}`" in conflict
    assert (
        "`exposure_unknown`: the exposure cannot be read because the exchange refuses every "
        "signable key of the account, or the account has none (`components.parameters."
        "OpenExposure`); it always carries `remedy` and no `consequences`"
    ) in conflict
    others = [
        operation.get("description", "")
        for path, item in _PATHS.items()
        for method, operation in item.items()
        if method != "parameters" and (path, method) not in _EXPOSURE_OPS
    ]
    assert len(others) >= 8
    assert [text for text in others if "exposure_unknown" in text] == []


def test_consequence_summary_names_the_ticket_that_adds_its_up_front_read() -> None:
    # SCR-129 renders the summary before the dialog's confirm control; only the 409 carries it.
    ref = "#/components/schemas/AccountConsequenceSummary"
    holders = {name for name, schema in _SCHEMAS.items() if ref in json.dumps(schema, default=str)}
    assert holders == {"OpenExposureProblem"}
    assert ref not in json.dumps(_SPEC["paths"], default=str)
    summary = _fold(_SCHEMAS["AccountConsequenceSummary"]["description"])
    assert "only in the `409 open_exposure` answer" in summary
    assert (
        "SCR-129 fetches it before the dialog renders, which needs a side-effect-free read: "
        "E27-S04 (#898) adds that operation in its own interface-first PR (C-6.1)"
    ) in summary


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


def test_internal_key_rules_match_the_mask_the_key_gate_the_cadence_and_the_expiry_warning() -> (
    None
):
    doc = _INTERNAL_SCHEMAS.read_text(encoding="utf-8")
    rules = _fold(doc[doc.index("### 15.3 API key handling") : doc.index("### 15.4")])
    assert '# "...WxYz" — "..." + the last 4 only (SR-E27-03)' in rules
    assert (
        "On registration the adapter calls `GET /v5/user/query-api` and **refuses** any key that "
        "holds a right outside the permission allow-list (withdrawal, transfer and the fiat, pay "
        "and card groups included) or whose IP whitelist is empty, a wildcard or anything other "
        "than the deployment egress IP (`createApiKey` steps 2 and 5 in `22-api-openapi.yaml`, "
        "C-2.8)."
    ) in rules
    assert (
        "Bybit made allowlist configuration browser-only in Feb 2026, so the operator sets it in "
        "the dashboard and CandleViewer only reads and compares it."
    ) in rules
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


def test_security_program_rotation_overlap_is_the_contract_value() -> None:
    grace = _grace_seconds_default()
    lines = _SECURITY_PROGRAM.read_text(encoding="utf-8").splitlines()
    [row] = [_fold(line) for line in lines if line.startswith("| SR-035 ")]
    assert "24 h" not in row
    assert f"the one fixed overlap of {grace} s" in row
    assert "US-ACCT-004" in row
    assert "`rotateApiKey`" in row
    assert "`rotating`" in row  # the key_status of the old key, not `retiring`
    assert "`retiring`" not in row
    stories = _USER_STORIES.read_text(encoding="utf-8")
    story = stories[stories.index("#### US-ACCT-004") :].split("\n#### ")[0]
    assert "15-minute drain window" in story
    assert timedelta(minutes=15) == timedelta(seconds=grace)


def test_security_program_key_id_mask_is_the_last_four_characters_the_contract_uses() -> None:
    lines = _SECURITY_PROGRAM.read_text(encoding="utf-8").splitlines()
    [row] = [_fold(line) for line in lines if line.startswith("| SR-005 ")]
    assert "first 4" not in row
    assert "prefix" not in row
    assert (
        "may return a secret or any part of the key id beyond its last 4 characters "
        "(`...` plus those 4, `key_id_masked` in `22-api-openapi.yaml`)"
    ) in row
    assert "A contract test MUST assert that no response schema contains a secret field" in row
    # The contract's mask is exactly that: `...` plus the last 4, nothing before it.
    assert _SCHEMAS["ApiKey"]["properties"]["key_id_masked"]["pattern"] == _MASK


def test_adr_0009_amendment_supersedes_the_24_h_soak_with_the_contract_overlap() -> None:
    grace = _grace_seconds_default()
    adr = _ADR_0009.read_text(encoding="utf-8")
    [amendment] = re.findall(
        r"^## Amendment \d+ \(2026-10-16, #2417;[^\n]*\n(.*?)(?=^## |\Z)", adr, flags=re.M | re.S
    )
    assert _fold(amendment) == (
        'Supersedes Design §5\'s "soak for 24 h". The rotation overlap is one fixed '
        f"{grace} s: the `api_key_rotations.grace_seconds` default and US-ACCT-004's 15-minute "
        "drain window (`rotateApiKey` in `docs/plan/22-api-openapi.yaml`). The rest of §5 (keys "
        'are created in the Bybit dashboard, not "via the Bybit API"; the old key is revoked '
        "locally only) stays with E27-T05."
    )


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
