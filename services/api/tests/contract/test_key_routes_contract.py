"""Contract (#836, E27-T03 slice 2b1): `createApiKey` and `testApiKey` declare what they answer
before 2b4 and 2b6 mount them (C-6.1). The slice changes: `KeyVerification.egress_ip` and the
bounds on the names it shows; the `201`, which is always the stored key with the verification
that passed; the `verification` of a rejected import, with the not-read shape of a key the
exchange refused before its rights were read; `key_expired` as step 6's refusal; the import
without a verdict (`503` no answer, `502` error answer) and the exchange-text-free problem both
use; the statuses the routes answer that were undeclared; the `test` throttle and private-WS
budget (SR-E27-05); and what a test enforces and audits. It adds no operation, so the
composition guard's caps stand. Every new sentence of the prose is quoted in `_PINNED`, so
deleting one fails a test."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import pytest
from jsonschema import ValidationError as SchemaError
from pydantic import ValidationError

from candleviewer.accounts import selfcheck
from candleviewer.accounts.verification import Rule
from candleviewer.api._generated import openapi_models as api
from candleviewer.ws._generated.error_codes import ErrorCode
from tests.contract._admin_support import ROOT, SPEC, example_cases, text, validate_example

_KEYS = "/exchange-accounts/{accountId}/keys"
_TEST = f"{_KEYS}/{{keyId}}/test"
_SCHEMAS: dict[str, Any] = SPEC["components"]["schemas"]
_RESPONSES: dict[str, Any] = SPEC["components"]["responses"]
_REGISTRY: dict[str, dict[str, Any]] = {entry["code"]: entry for entry in SPEC["x-error-codes"]}
_PROBLEM = {"$ref": "#/components/schemas/Problem"}
_REJECTED = {"$ref": "#/components/schemas/KeyRejectedProblem"}
_EXCHANGE = {"$ref": "#/components/schemas/KeyExchangeProblem"}
_REJECTED_AT = "/components/schemas/KeyRejectedProblem"
_VERIFICATION = "/components/schemas/KeyVerification"
_NOT_READ = "/components/schemas/KeyVerificationNotRead"
_TEST_RESULT = "/components/schemas/KeyTestResult"

#: The statuses each operation declares, exactly (C-6.1; C-6.3: declaring one is additive), with
#: the shared response each reuses; `None` is written inline because no shared one fits: a test
#: refuses a key that is not signable with a 409, a body that fails its schema with a 422 and
#: nothing it could probe with a 503 that has no audit code, and its failures are `200`s. A test
#: has no `502`: an exchange failure is reported inside its `200`.
_DECLARED: dict[str, dict[int, str | None]] = {
    "createApiKey": {
        201: None,
        400: "BadRequest",
        403: "Forbidden",
        404: "NotFound",
        409: "Conflict",
        422: "KeyRejected",
        502: "KeyExchangeError",
        503: "KeyServiceUnavailable",
    },
    "testApiKey": {
        200: None,
        403: "Forbidden",
        404: "NotFound",
        409: None,
        422: None,
        429: "KeyTestThrottled",
        503: None,
    },
}
_FAILURES = [(op, s) for op, responses in _DECLARED.items() for s in responses if s >= 400]
#: Members no key response may carry (SR-E27-08, C-2.7); `exchange` may hold `ret_code` only.
_FORBIDDEN = {"ret_msg", "endpoint", "request_id", "api_key", "api_secret", "secret"}
#: Only an `active` or `rotating` key is signed with (`KeyStatus`).
_SIGNABLE = {"active", "rotating"}
_EGRESS = "203.0.113.10"

#: Where each new sentence is written, with a core phrase of every one: a deletion check.
_PINNED: dict[tuple[str, ...], tuple[str, ...]] = {
    ("paths", _KEYS, "post"): (
        "Expiry, if set, must be in the future (SR-030a)",
        "is rejected with `validation_failed` / `key_expired`",
        "accepted, with the `key_expiring_soon` warning",
        "gives no verdict, see **No verdict**",
        "**Verdict.** The exchange refusing the key itself ends a check with a verdict",
        "are the rules of steps 1, 3, 5 and 6 (`key_wrong_environment`, `key_missing_scopes`",
        "a refused signed probe is `key_probe_failed`",
        "Every rejection is a `422` that carries the `verification` the pipeline reached",
        "the fields of a check that did not run are left out",
        "(`KeyVerificationNotRead`): `passed` and `egress_ip` only, and never `withdraw_enabled`",
        "is not a pass and is not sent as `false` (C-2.8)",
        "A `422` is stored for replay like any other answer",
        "**No verdict.** A signed call can end without saying anything about the key",
        "(a refused signature, a clock outside the `recv_window`, a rate limit, an outage",
        "nothing is stored, no stored key or account changes, and the import may be sent again",
        "give `503 exchange_unavailable` with `Retry-After`",
        "an error answer gives `502 exchange_error`",
        "Neither answer echoes exchange text (`KeyExchangeProblem`)",
        "`Problem.exchange` holds `ret_code` only (omitted when the exchange sent none)",
        "A `502` or `503` of an import is never stored for replay",
        "`404` is an account that does not exist",
        "(`idempotency_key_reuse`) or still being processed (`idempotency_in_flight`)",
        "a request that conflicts with stored state (`conflict`)",
        "holds `api_key` only as a server-keyed HMAC",
        "is `idempotency_key_reuse` and never the first key's answer",
        "it never holds `api_secret`",
        "`audit_unavailable` when the write-ahead audit record of the import cannot be written",
        "`store_unavailable` when the relational store is unavailable",
        "A KEK that is unavailable is refused with `403 kek_unavailable` instead",
    ),
    ("paths", _TEST, "post"): (
        "Re-runs the verification pipeline against a stored key: diagnostics that change nothing",
        "The REST verdict is enforced as the hourly self-check enforces its own",
        "a pass refreshes the key's `last_verified_at`",
        "latches the process read-only and force-disables trading on the account",
        "a withdrawal right found on demand never waits for the next scheduled check (C-2.8)",
        "changes nothing and carries no `verification`: an outage never reads as a pass",
        "The WebSocket half is diagnostic only",
        "Without `include_ws` that half does not run: `websocket` is omitted, never `ok: true`",
        "**Audit.** A verdict writes `account.tested` ahead of the key-row writes it covers",
        "(`last_error_*`, the refreshed columns), with the acting Owner as actor",
        "the rule codes and the verified permission facts",
        "never the egress IP, the whitelist or an exchange UID",
        "a verdict that disarms the account also writes `account.disabled_by_policy`, once the",
        "disarm is made",
        "The audit sink is no gate on enforcement (C-2.8 before C-2.9)",
        "a failing verdict latches the process gate first and disables the account whatever",
        "the sink does, and the record of the disable is re-sent",
        "a pass whose record is refused refreshes nothing",
        "**Throttle.** One test per key per minute (E27-T03, #836)",
        "a second inside the minute is `429 rate_limited` with `Retry-After`",
        "at most 10 throwaway private WS connections per 5 minutes in all",
        "the scheduled self-check opens none (SR-E27-05)",
        "`websocket` `{ ok: false, error: rate_limited }`, and no connection is opened",
        "**Not signable.** Only an `active` or `rotating` key is signed with (`KeyStatus`)",
        "is refused with `409 conflict`, and nothing is probed",
        "An exchange failure never fails the request",
        "A KEK that is unavailable is refused with `403 kek_unavailable`",
    ),
    ("components", "responses", "Forbidden"): (
        "`createApiKey` and `testApiKey` answer `code: kek_unavailable` while the credential key",
        "(KEK) is unavailable (ADR-0009 Amendment 1)",
    ),
    ("components", "responses", "KeyRejected"): (
        "The verification pipeline refused the key, so nothing was stored",
        "the result as far as the pipeline got",
        "shows `egress_ip` to copy (`createApiKey`, SCR-126)",
        "A key the exchange refused before its rights were read carries `KeyVerificationNotRead`",
        "A request that fails its schema is the same `422` with the validation types in `errors`",
        "A call that ends without a verdict is a `502` or `503`, never this `422`",
    ),
    ("components", "responses", "KeyExchangeError"): (
        "An import whose signed call got an error answer that is not a refusal of the key",
        "`exchange` holds `ret_code` only (`KeyExchangeProblem`)",
    ),
    ("components", "responses", "KeyServiceUnavailable"): (
        "An import that could not be made or recorded, so nothing was stored (`createApiKey`)",
        "`exchange` holds `ret_code` only (`KeyExchangeProblem`)",
        "`audit_unavailable` is the import's alone: a test never fails on its audit record",
    ),
    ("paths", _TEST, "post", "responses", "503"): (
        "Nothing could be probed: signing is unavailable (`exchange_unavailable`)",
        "or the relational store is (`store_unavailable`)",
        "An exchange failure is never this status: it is reported inside the `200`",
        "a test never fails on its audit record",
    ),
    ("components", "responses", "KeyTestThrottled"): (
        "a second inside the minute is refused and nothing is probed",
        "An exchange rate limit is reported inside the `200`, never as this `429`",
    ),
    ("components", "schemas", "KeyRejectedProblem"): (
        "The `422` problem of a key operation (`createApiKey`; `rotateApiKey` can reuse it)",
        "when the verification pipeline refused the key, the `verification` it reached",
        "`verification.passed` is false, and otherwise it is not allowed",
        "A request that fails its schema is the same problem with the validation types",
        "no exchange text is echoed (SR-E27-08)",
    ),
    ("components", "schemas", "KeyExchangeProblem"): (
        "The `502` and `503` problems of a key operation",
        "holds the exchange's return code only, never `ret_msg`, `endpoint`, `request_id`",
        "This schema alone refuses the other members: the generated Python class re-declares",
        "`exchange` with the type of `Problem`, which also admits `ret_msg`, `endpoint` and",
        "so a body built from that class type-checks while it leaks exchange text",
        "A route builds `exchange` from the return code alone, and its provider test validates",
        "the real `502` and `503` against this schema",
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
    ("components", "schemas", "KeyVerificationNotRead"): (
        "The verification of a key whose rights were never read",
        "so no check of steps 2 to 7 ran",
        "never `withdraw_enabled`: a withdrawal check that did not run is not a pass",
        "a client shows each check as not checked, never as ok",
        "It is never the verification of a stored key (`KeyVerificationPassed`)",
    ),
    ("components", "schemas", "EgressIp"): (
        "The deployment's configured egress IP (`CV_EGRESS_IP`)",
        "`null` while none is configured",
        "It comes from configuration, never from a request header",
        "the address the Owner adds to the key's whitelist at the exchange when the exchange",
        "Confidential: served only to a caller holding `keys:manage` or `keys:read`",
        "never written to an audit record or used as a metric label",
    ),
    ("components", "schemas", "KeyVerification", "properties", "withdraw_enabled"): (
        "Sent only once the key's rights were read, never as a default (`KeyVerificationNotRead`)",
    ),
    ("components", "schemas", "KeyVerification", "properties", "permissions"): (
        "whose name is not a plain identifier is left out of the display",
    ),
    ("components", "schemas", "KeyVerification", "properties", "ip_whitelist"): (
        "At most 20 entries, each an address, a range or `*`",
    ),
    ("components", "schemas", "KeyProbeError"): (
        "in `KeyTestResult.websocket` it is also the deployment's own budget of private WS",
        "connections opened for tests being spent (SR-E27-05)",
    ),
    ("components", "schemas", "KeyTestResult", "properties", "passed"): (
        "True only when the verification passed, the REST probe succeeded and, with",
    ),
    ("components", "schemas", "KeyTestResult", "properties", "websocket"): (
        "Omitted when `include_ws` is false: that half did not run",
    ),
    ("components", "schemas", "KeyTestResult", "properties", "verification"): (
        "The verification as far as the pipeline got",
        "Omitted when the REST half reached no verdict",
        "an earlier check's standing result is never shown in its place",
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


def _response(operation_id: str, status: int) -> dict[str, Any]:
    """The response as declared (a `$ref` is not followed)."""
    response: dict[str, Any] | None = _operation(operation_id)["responses"].get(str(status))
    assert response is not None, f"{operation_id} does not declare {status}"
    return response


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


def _keys(node: object) -> Iterator[str]:
    """Every mapping key anywhere under `node`."""
    if isinstance(node, dict):
        for name, value in node.items():
            yield name
            yield from _keys(value)
    elif isinstance(node, list):
        for item in node:
            yield from _keys(item)


def _without(value: dict[str, Any], *names: str) -> dict[str, Any]:
    return {k: v for k, v in value.items() if k not in names}


def _schema_at(response: str) -> str:
    """The JSON pointer of the schema of a shared response's problem body."""
    return f"/components/responses/{response}/content/application~1problem+json/schema"


_REJECTIONS = _by_name("createApiKey", 422)
_PIPELINE = _REJECTIONS["ipWhitelistMismatch"]
#: The pipeline refusals that `KeyRejected` shows, with the rule each names.
_RULES = {
    "withdrawEnabled": "key_withdraw_permission",
    "ipWhitelistMismatch": "key_ip_whitelist_mismatch",
    "wrongEnvironment": "key_wrong_environment",
    "exchangeRefusedIp": "key_ip_whitelist_mismatch",
}


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
    assert len(accepted) >= 4  # the 201, the rotation 200 and both test 200s
    assert all(v["ip_whitelist"] == [v["egress_ip"]] for v in accepted)


# --- A rejected import carries its verification ----------------------------------------------


_BROKEN = {
    "a rule without its verification": _without(_PIPELINE, "verification"),
    "a rule with another code": {**_PIPELINE, "code": "conflict"},
    "a rule with a verification that passed": {
        **_PIPELINE,
        "verification": {**_PIPELINE["verification"], "passed": True},
    },
    "a schema failure with a verification": {
        **_REJECTIONS["requestInvalid"],
        "verification": _PIPELINE["verification"],
    },
}


@pytest.mark.parametrize("body", _BROKEN.values(), ids=_BROKEN)
def test_a_rejection_breaking_the_verification_rule_fails_the_schema(body: dict[str, Any]) -> None:
    with pytest.raises(SchemaError):
        validate_example(_REJECTED_AT, body)


def test_a_problem_whose_errors_name_no_pipeline_rule_demands_no_verification() -> None:
    validate_example(_REJECTED_AT, {**_without(_PIPELINE, "verification"), "errors": []})


@pytest.mark.parametrize("name", _REJECTIONS)
def test_every_rejection_example_is_the_problem_and_its_generated_model(name: str) -> None:
    validate_example(_REJECTED_AT, _REJECTIONS[name])
    api.KeyRejectedProblem.model_validate(_REJECTIONS[name])


@pytest.mark.parametrize(("name", "rule"), _RULES.items())
def test_a_pipeline_rejection_names_its_rule_and_a_failed_verification(
    name: str, rule: str
) -> None:
    value = _REJECTIONS[name]
    assert (value["code"], value["title"]) == (
        "validation_failed",
        _REGISTRY["validation_failed"]["title"],
    )
    assert [e["rule"] for e in value["errors"]] == [rule]
    assert value["verification"]["passed"] is False


def test_the_whitelist_rejection_holds_the_egress_ip_and_another_address() -> None:
    shown = _PIPELINE["verification"]  # the exchange only answers from a whitelisted address
    assert shown["ip_whitelist_matches_egress"] is False
    assert shown["egress_ip"] in shown["ip_whitelist"] and len(shown["ip_whitelist"]) > 1


def test_the_withdrawal_rejection_shows_the_right_and_leaves_later_checks_out() -> None:
    withdraw = _REJECTIONS["withdrawEnabled"]["verification"]
    assert withdraw["withdraw_enabled"] is True and "Withdraw" in withdraw["permissions"]["Wallet"]
    # The gate runs before every other check and before the probe (step 2): they left no fields.
    assert not {"ip_whitelist_matches_egress", "probe_ret_code", "clock_offset_ms"} & set(withdraw)


# --- A key the exchange refused before its rights were read: nothing was checked --------------


_UNREAD = {
    "wrongEnvironment": ({"passed": False}, "key does not belong to this environment"),
    "exchangeRefusedIp": ({"passed": False, "egress_ip": _EGRESS}, _EGRESS),
}


@pytest.mark.parametrize("name", _UNREAD)
def test_a_key_refused_unread_carries_no_check_fact(name: str) -> None:
    shown = _UNREAD[name][0]
    assert _REJECTIONS[name]["verification"] == shown
    validate_example(_NOT_READ, shown)
    api.KeyVerificationNotRead.model_validate(shown)


@pytest.mark.parametrize("name", _UNREAD)
def test_a_key_refused_unread_says_what_to_do(name: str) -> None:
    assert _UNREAD[name][1] in _REJECTIONS[name]["errors"][0]["message"]


_UNREAD_BROKEN = {
    "withdraw_enabled false": {"passed": False, "withdraw_enabled": False},
    "withdraw_enabled true": {"passed": False, "withdraw_enabled": True},
    "a verification that passed": {"passed": True},
    "another check fact": {"passed": False, "uid": "10234567"},
}


@pytest.mark.parametrize("verification", _UNREAD_BROKEN.values(), ids=_UNREAD_BROKEN)
def test_the_not_read_verification_refuses_a_pass_and_every_check_fact(
    verification: dict[str, Any],
) -> None:
    with pytest.raises(SchemaError):
        validate_example(_NOT_READ, verification)
    with pytest.raises(ValidationError):
        api.KeyVerificationNotRead.model_validate(verification)


@pytest.mark.parametrize(
    ("schema", "body"),
    [
        (_REJECTED_AT, {**_PIPELINE, "verification": {"passed": False, "uid": "10234567"}}),
        (_TEST_RESULT, {"passed": False, "verification": {"passed": False, "uid": "10234567"}}),
    ],
    ids=["rejected import", "test result"],
)
def test_check_facts_without_withdraw_enabled_are_refused_where_a_verification_is_served(
    schema: str, body: dict[str, Any]
) -> None:
    with pytest.raises(SchemaError):  # a check that did not run is never sent as a half-result
        validate_example(schema, body)


def test_a_test_result_may_carry_the_verification_of_a_key_refused_unread() -> None:
    refused = {"passed": False, "rest": {"ok": False, "error": "ip_not_allowed", "ret_code": 10010}}
    body = {**refused, "verification": {"passed": False, "egress_ip": _EGRESS}}
    validate_example(_TEST_RESULT, body)
    assert isinstance(
        api.KeyTestResult.model_validate(body).verification, api.KeyVerificationNotRead
    )


# --- key_expired is step 6's refusal ----------------------------------------------------------


def test_every_rule_the_shipped_pipeline_emits_is_a_rule_of_step_one_to_seven() -> None:
    steps = SPEC["paths"][_KEYS]["post"]["description"]
    named = set(re.findall(r"`(key_[a-z_]+)`", steps)) - {"key_expiring_soon"}
    assert {rule.value for rule in Rule} <= named
    [step6] = [s for s in re.split(r"\n(?=\d+\. )", steps) if s.startswith("6. ")]
    assert "`key_expired`" in step6 and "`key_expiring_soon`" in step6


# --- The statuses the key operations answer ---------------------------------------------------


@pytest.mark.parametrize("operation_id", _DECLARED)
def test_key_operation_declares_exactly_the_statuses_it_answers(operation_id: str) -> None:
    declared = {int(code) for code in _operation(operation_id)["responses"]}
    assert declared == set(_DECLARED[operation_id])


@pytest.mark.parametrize(("operation_id", "status"), _FAILURES)
def test_key_failure_reuses_its_shared_response_or_is_an_inline_problem(
    operation_id: str, status: int
) -> None:
    response, shared = _response(operation_id, status), _DECLARED[operation_id][status]
    assert (response == {"$ref": f"#/components/responses/{shared}"}) is (shared is not None)
    ((media, body),) = _resolved(response)["content"].items()
    schema = body["schema"]
    members = [schema, *schema.get("anyOf", []), *schema.get("allOf", [])]
    assert media == "application/problem+json"
    assert any(m in (_PROBLEM, _REJECTED, _EXCHANGE) for m in members)


_CASES = example_cases([(_KEYS, "post"), (_TEST, "post")])


def _at(pointer: str) -> Any:
    """The node of the spec at a JSON pointer (`~1` is `/`, `~0` is `~`)."""
    node: Any = SPEC
    for part in pointer.removeprefix("/").split("/"):
        node = node[part.replace("~1", "/").replace("~0", "~")]
    return node


#: Every example whose answer is the exchange-text-free problem: `(case id, schema pointer, body)`.
_EXCHANGE_ANSWERS = [case for case in _CASES if _at(case[1]) == _EXCHANGE]


@pytest.mark.parametrize(
    ("pointer", "value"), [(p, v) for _, p, v in _CASES], ids=[case for case, _, _ in _CASES]
)
def test_every_example_validates_against_the_schema_it_is_declared_for(
    pointer: str, value: Any
) -> None:
    validate_example(pointer, value)


@pytest.mark.parametrize(("operation_id", "status"), _FAILURES)
def test_every_declared_failure_has_examples_of_registered_codes(
    operation_id: str, status: int
) -> None:
    examples = list(_by_name(operation_id, status).values())
    assert examples
    for value in examples:
        assert value["status"] == status
        assert value["code"] in _REGISTRY
        assert value["type"] == f"https://candleviewer.local/errors/{value['code']}"


@pytest.mark.parametrize(
    ("code", "status", "retryable"),
    [
        ("exchange_error", 502, True),
        ("exchange_unavailable", 503, True),
        ("audit_unavailable", 503, True),
        ("store_unavailable", 503, True),
        ("rate_limited", 429, True),
        ("idempotency_key_reuse", 409, False),
        ("idempotency_in_flight", 409, True),
        ("conflict", 409, False),
        ("not_found", 404, False),
        ("kek_unavailable", 403, False),
    ],
)
def test_every_code_the_key_routes_name_is_registered_with_its_status(
    code: str, status: int, retryable: bool
) -> None:
    assert (_REGISTRY[code]["status"], _REGISTRY[code]["retryable"]) == (status, retryable)


@pytest.mark.parametrize(
    ("operation_id", "status"), [failure for failure in _FAILURES if failure[1] in (429, 503)]
)
def test_a_retryable_refusal_tells_the_client_when_to_come_back(
    operation_id: str, status: int
) -> None:
    headers = _resolved(_response(operation_id, status))["headers"]
    assert headers["Retry-After"] == {"$ref": "#/components/headers/RetryAfter"}


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


# --- No exchange text and no key material in a failure (SR-E27-08, C-2.7) ---------------------


def _leaks(value: dict[str, Any]) -> set[str]:
    exchange = value.get("exchange", {})
    return (set(_keys(_without(value, "exchange"))) & _FORBIDDEN) | (set(exchange) - {"ret_code"})


@pytest.mark.parametrize(("operation_id", "status"), _FAILURES)
def test_no_failure_example_echoes_exchange_text_or_key_material(
    operation_id: str, status: int
) -> None:
    assert {n: _leaks(v) for n, v in _by_name(operation_id, status).items() if _leaks(v)} == {}


@pytest.mark.parametrize(
    ("operation_id", "status"), [failure for failure in _FAILURES if failure[1] in (502, 503)]
)
def test_the_exchange_facing_failures_are_the_exchange_text_free_problem(
    operation_id: str, status: int
) -> None:
    ((_, body),) = _resolved(_response(operation_id, status))["content"].items()
    assert body["schema"] == _EXCHANGE


def test_the_exchange_text_free_problem_answers_the_import_and_the_test() -> None:
    assert {case.split(" ")[1] for case, _, _ in _EXCHANGE_ANSWERS} == {_KEYS, _TEST}


def test_a_502_example_holds_the_return_code_alone() -> None:
    answer = _by_name("createApiKey", 502)["signatureRefused"]
    assert answer["exchange"] == {"ret_code": 10004}


_LEAKS = ["ret_msg", "endpoint", "request_id"]
_LEAKING = "error sign! origin_string[…]"


@pytest.mark.parametrize("leak", _LEAKS)
@pytest.mark.parametrize(
    ("pointer", "answer"),
    [(pointer, answer) for _, pointer, answer in _EXCHANGE_ANSWERS],
    ids=[case for case, _, _ in _EXCHANGE_ANSWERS],
)
def test_a_key_failure_that_carries_exchange_text_fails_its_schema(
    pointer: str, answer: dict[str, Any], leak: str
) -> None:
    leaking = {**answer, "exchange": {**answer.get("exchange", {}), leak: _LEAKING}}
    with pytest.raises(SchemaError):
        validate_example(pointer, leaking)


@pytest.mark.parametrize("leak", _LEAKS)
def test_the_generated_class_admits_the_exchange_text_its_schema_refuses(leak: str) -> None:
    # The limit `KeyExchangeProblem` states: the generator cannot narrow `Problem.exchange`, so the
    # schema is the guarantee. Once the class refuses this, delete that sentence and this test.
    answer = _by_name("createApiKey", 502)["signatureRefused"]
    leaking = {**answer, "exchange": {**answer["exchange"], leak: _LEAKING}}
    try:
        decoded = api.KeyExchangeProblem.model_validate(leaking)
    except ValidationError:
        pytest.fail("the generated class refuses exchange text: drop the limit from the schema")
    assert decoded.exchange is not None and getattr(decoded.exchange, leak) == _LEAKING


# --- The test throttle and the private-WS budget (SR-E27-05) ----------------------------------


def test_the_throttle_and_the_ws_budget_are_the_threat_models_numbers() -> None:
    model = text((ROOT / "docs/security/threat-models/E27-accounts.md").read_text("utf-8"))
    assert "`test` throttled to 1 per minute per key" in model
    assert (
        "at most 10 private-WS opens per 5 minutes from `test`, none from scheduled checks" in model
    )


def test_a_throttled_test_is_rate_limited_with_its_wait_and_names_no_exchange_uid() -> None:
    (value,) = _by_name("testApiKey", 429).values()
    assert (value["code"], value["status"]) == ("rate_limited", 429)
    assert value["retry_after_seconds"] > 0
    assert not re.search(r"\d{6,}", value["detail"])  # an exchange UID is 8 digits


@pytest.mark.parametrize(
    "broken",
    [{"code": "exchange_rate_limited"}, {"retry_after_seconds": None}],
    ids=["code", "wait"],
)
def test_a_throttle_that_is_not_rate_limited_with_its_wait_fails_the_schema(
    broken: dict[str, Any],
) -> None:
    value = next(iter(_by_name("testApiKey", 429).values()))
    body = {k: v for k, v in {**value, **broken}.items() if v is not None}
    with pytest.raises(SchemaError):
        validate_example(_schema_at("KeyTestThrottled"), body)


def test_a_spent_ws_budget_is_a_200_that_fails_with_rate_limited_in_websocket_error() -> None:
    spent = _by_name("testApiKey", 200)["wsBudgetSpent"]
    assert spent["websocket"] == {"ok": False, "latency_ms": None, "error": "rate_limited"}
    assert (spent["passed"], spent["rest"]["ok"], spent["verification"]["passed"]) == (
        False,
        True,
        True,
    )


def test_the_generated_test_result_decodes_a_spent_ws_budget() -> None:
    decoded = api.KeyTestResult.model_validate(_by_name("testApiKey", 200)["wsBudgetSpent"])
    assert decoded.websocket is not None and decoded.websocket.error == "rate_limited"


# --- What a test enforces and audits, in the order of the hourly job (C-2.8 before C-2.9) -----


def test_the_hourly_job_latches_first_and_audits_ahead_of_the_key_row_writes() -> None:
    job = text(selfcheck.__doc__ or "")
    assert "failure: the process read-only gate latches first" in job
    assert "A write-ahead `account.tested` covers `last_error_*`" in job
    assert "The account is force-disabled whatever the audit sink does" in job
    assert "then the verified `api_keys` columns are refreshed" in job


def test_a_test_audits_ahead_of_the_key_row_writes_it_covers_not_ahead_of_its_effects() -> None:
    audit = _description("paths", _TEST, "post").split("**Audit.**", 1)[1].split("**Throttle.**")[0]
    assert "ahead of the key-row writes it covers (`last_error_*`, the refreshed columns)" in audit
    assert "ahead of its effects" not in audit  # the latch and the disable do not wait for it


def test_a_test_latches_before_it_asks_the_audit_sink_and_never_waits_for_it() -> None:
    audit = _description("paths", _TEST, "post").split("**Audit.**", 1)[1].split("**Throttle.**")[0]
    assert "a failing verdict latches the process gate first and disables the account" in audit
    assert audit.index("latches the process gate first") < audit.index("whatever the sink does")


# --- What a test answers when the key cannot be probed ----------------------------------------


def test_every_key_status_that_is_not_signable_is_named_and_refused_with_a_409() -> None:
    unsignable = [s for s in _SCHEMAS["KeyStatus"]["enum"] if s not in _SIGNABLE]
    description = _description("paths", _TEST, "post")
    assert [s for s in unsignable if f"`{s}`" not in description] == []
    (conflict,) = _by_name("testApiKey", 409).values()
    assert (conflict["code"], conflict["status"]) == ("conflict", 409)


def _failure_codes(operation_id: str) -> set[str]:
    return {value["code"] for status, _, value in _examples(operation_id) if status >= 400}


def test_the_audit_unavailable_answer_is_the_imports_alone() -> None:
    assert "audit_unavailable" in _failure_codes("createApiKey")
    assert "audit_unavailable" not in _failure_codes("testApiKey")  # a test never fails on it


def test_the_503_of_a_test_is_a_signing_outage_that_names_no_exchange_silence() -> None:
    (outage,) = _by_name("testApiKey", 503).values()
    assert (outage["code"], outage["status"]) == ("exchange_unavailable", 503)
    assert "exchange" not in outage  # nothing was probed, so no exchange answered or kept quiet
    assert "gave no answer" not in outage["detail"]  # that is a `200` with `rest.error: timeout`


def test_a_test_with_no_verdict_and_no_ws_carries_neither_verification_nor_websocket() -> None:
    timeout = _by_name("testApiKey", 200)["restTimeout"]
    assert {"verification", "websocket"}.isdisjoint(timeout)
    assert (timeout["passed"], timeout["rest"]["ok"], timeout["rest"]["error"]) == (
        False,
        False,
        "timeout",
    )


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


def test_the_test_route_is_no_longer_described_as_read_only_diagnostics() -> None:
    assert "Read-only diagnostics" not in _description("paths", _TEST, "post")
