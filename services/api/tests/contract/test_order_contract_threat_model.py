"""Contract (#3863, E29 G-1): the order contract says what the E29 threat model's controls do.

`docs/plan/22-api-openapi.yaml`, from `docs/security/threat-models/E29-oms.md` section 11.1 G-1:
the native stop keys on an order's effect, never on its `intent` or the profile flag (SR-E29-01);
events are served without payload, the stored exchange records have closed schemas and the
exchange's text reaches no route but the audited diagnostics read (SR-E29-08, SR-E29-09); foreign
and missing ids answer alike and a bulk route refuses an out-of-scope id whole (SR-E29-13); a live
account's risk-increasing order mutations need the arm token, which arming for live issues only
after a step-up, while the C-2.6 carve-out keeps every risk-reducing route free of it (SR-043,
24-internal-schemas.md section 8.10); and `setKillSwitch` claims no dead-man's switch (OM-D05).
Read from the spec and the regenerated models, never from a copy (AGENTS.md section 6 rule 12).
No route here is mounted yet: E29-T04 and E29-T07 implement them against this text (C-6.1).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import pytest

from candleviewer.api._generated import openapi_models as rest
from candleviewer.api.contract_conformance import load_openapi_spec

_SPEC: Any = load_openapi_spec()  # a parsed YAML document, walked untyped
_SCHEMAS: dict[str, Any] = _SPEC["components"]["schemas"]
_PARAMS: dict[str, Any] = _SPEC["components"]["parameters"]
#: (path, method, operation) for every operation of the contract.
_ROUTES: list[tuple[str, str, Any]] = [
    (path, method, op)
    for path, item in _SPEC["paths"].items()
    for method, op in item.items()
    if isinstance(op, dict) and "operationId" in op
]
_OPS: dict[str, Any] = {op["operationId"]: op for _, _, op in _ROUTES}
#: Every order mutation: the order, trade-group and position writes (`/settings/arm` issues the
#: token, so it is not one).
_MUTATIONS = sorted(
    name
    for name, op in _OPS.items()
    if {"orders:write", "positions:write"} & set(op.get("x-rbac", {}).get("permissions", []))
    and name != "armOneClickTrading"
)
#: The mutations that can open or increase exposure, as the order-entry gate classifies them.
_ARMED = (
    "placeOrder",
    "amendOrder",
    "createTradeGroup",
    "amendTradeGroup",
    "reversePosition",
    "setPositionLeverage",
    "setPositionTpSl",
)
#: The risk-reducing routes the C-2.6 carve-out keeps open (24-internal-schemas.md 8.10).
_CARVED_OUT = (
    "cancelOrder",
    "cancelAllOrders",
    "cancelTradeGroup",
    "closePosition",
    "closeAllPositions",
)
#: The order and position id routes (SR-E29-13).
_ID_ROUTES = [
    (f"{method.upper()} {path}", op)
    for path, method, op in _ROUTES
    if path.startswith(("/orders/{orderId}", "/positions/{positionId}"))
]
_BULK = ("cancelAllOrders", "closeAllPositions")
_ARM_TOKEN = {"$ref": "#/components/parameters/ArmToken"}


def _words(text: str) -> str:
    """A description on one line: a YAML block keeps its line breaks, a phrase may span two."""
    return " ".join(text.split())


def _strings(node: object) -> Iterator[str]:
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value)


def _ref(kind: str, name: str) -> dict[str, str]:
    return {"$ref": f"#/components/{kind}/{name}"}


def _refs(node: object) -> Iterator[str]:
    """Every `$ref` target under `node`."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                yield value
            else:
                yield from _refs(value)
    elif isinstance(node, list):
        for value in node:
            yield from _refs(value)


def _referrers(target: str) -> set[str]:
    """The component schemas and the operations whose subtree refers to `target`."""
    found = {f"schemas/{name}" for name, node in _SCHEMAS.items() if target in set(_refs(node))}
    found |= {f"op/{op['operationId']}" for _, _, op in _ROUTES if target in set(_refs(op))}
    return found


def _request_properties(op: Any) -> dict[str, Any]:
    """The top-level properties of an operation's JSON request body, through one `$ref`."""
    content = op.get("requestBody", {}).get("content", {}).get("application/json", {})
    schema = content.get("schema", {})
    if "$ref" in schema:
        schema = _SCHEMAS[schema["$ref"].rsplit("/", 1)[1]]
    properties: dict[str, Any] = schema.get("properties", {})
    return properties


def test_no_contract_text_keys_the_native_stop_on_intent_or_the_profile_flag() -> None:
    """Scenario: a client-supplied intent cannot waive the native stop (SR-E29-01, note 7)."""
    texts = list(map(_words, _strings(_SPEC)))
    keyed = re.compile(r"\bentry[- ](?:intents?|type)\b")
    assert [text for text in texts if keyed.search(text)] == []
    # The profile flag is named only where the contract says it is a constant nobody reads.
    flag = [text for text in texts if "require_native_stop" in text]
    assert flag  # the profile still documents its constant
    allowed = ("cannot be set to `false`", "The order path never reads it")
    assert [text for text in flag if not any(phrase in text for phrase in allowed)] == []


def test_place_order_takes_an_opening_order_as_an_entry_whatever_its_intent() -> None:
    text = _words(_OPS["placeOrder"]["description"])
    assert (
        "an order that is not reduce-only, or whose quantity exceeds the position it reduces, "
        "is an entry whatever its `intent`" in text
    )
    assert "No field, flag or profile setting waives it (C-4.14)." in text
    assert (
        "The stop requirement is checked first. Then an `intent` that disagrees with the effect "
        "is refused too (`validation_failed` / `intent_mismatch`): a reducing one (`stop_loss`, "
        "`take_profit`, `scale_out`, `flatten`) on an entry, or an opening one (`entry`, "
        "`scale_in`) on an order that is not an entry" in text
    )
    # AC-08: a mislabelled opening order with no stop is refused for both rules.
    assert "carries both `native_stop_required` and `intent_mismatch`" in text


def test_an_open_position_stop_is_never_cleared_whatever_the_profile_says() -> None:
    text = _words(_OPS["setPositionTpSl"]["description"])
    assert "The stop-loss of an open position can never be cleared (C-2.6)" in text


@pytest.mark.parametrize("name", ["OrderEvent", "OrderDiagnostics"])
def test_order_events_and_diagnostics_are_closed_and_events_carry_no_payload(name: str) -> None:
    """Scenario: events carry no raw payload (SR-E29-09)."""
    assert set(_SCHEMAS["OrderEvent"]["properties"]) == {"id", "kind", "event_ts"}
    assert _SCHEMAS[name]["additionalProperties"] is False
    assert getattr(rest, name).model_config.get("extra") == "forbid"


def test_the_stored_exchange_records_have_closed_schemas_and_bounded_strings() -> None:
    """SR-E29-08: a field outside the allow-list is never stored, so it is never served."""
    calls = _SCHEMAS["OrderDiagnostics"]["properties"]["exchange_calls"]
    assert calls["items"] == _ref("schemas", "ExchangeCallRecord")
    record = _SCHEMAS["ExchangeCallRecord"]["properties"]
    for member in ("request_redacted", "response_redacted"):
        assert record[member]["oneOf"] == [
            _ref("schemas", "ExchangeRecordFields"),
            {"type": "null"},
        ]
    for name in ("ExchangeCallRecord", "ExchangeRecordFields"):
        schema = _SCHEMAS[name]
        assert schema["additionalProperties"] is False
        assert getattr(rest, name).model_config.get("extra") == "forbid"
        unbounded = [
            field
            for field, node in schema["properties"].items()
            if "string" in node.get("type", ())
            and not ({"maxLength", "enum", "format"} & set(node))
        ]
        assert unbounded == []


def test_the_exchange_text_reaches_no_order_route_but_diagnostics() -> None:
    """SR-E29-09: raw `ret_msg` only through the audited diagnostics read (OM-I06, M1)."""
    holders = sorted(
        name
        for name, schema in _SCHEMAS.items()
        if "request_redacted" in schema.get("properties", {})
    )
    assert holders == ["ExchangeCallRecord"]
    assert _referrers("#/components/schemas/ExchangeRecordFields") == {"schemas/ExchangeCallRecord"}
    assert _referrers("#/components/schemas/ExchangeCallRecord") == {"schemas/OrderDiagnostics"}
    assert _referrers("#/components/schemas/OrderDiagnostics") == {"op/getOrderDiagnostics"}
    order_paths = ("/orders", "/positions", "/trade-groups")
    exchange_errors = sorted(
        op["operationId"]
        for path, _, op in _ROUTES
        if path.startswith(order_paths) and "502" in op["responses"]
    )
    assert exchange_errors  # the order path has exchange refusals to check
    for operation in exchange_errors:
        assert _OPS[operation]["responses"]["502"] == _ref("responses", "OrderExchangeError")
    problem = _SCHEMAS["OrderExchangeProblem"]["allOf"][1]["properties"]["exchange"]
    assert problem == {
        "type": "object",
        "additionalProperties": False,
        "properties": {"ret_code": {"type": "integer"}},
    }


def test_the_diagnostics_read_is_audited_and_its_roles_wait_for_d7() -> None:
    text = _words(_OPS["getOrderDiagnostics"]["description"])
    assert "every read is audited (`order.diagnostics_viewed`)" in text
    # D7 is the Owner's open decision (#2701): the contract names it and invents no roles.
    assert "the Owner's decision D7 (E29 threat model section 4.3, queued on #2701)" in text
    assert "its `x-rbac` is provisional until then" in text


@pytest.mark.parametrize(("route", "op"), _ID_ROUTES, ids=[route for route, _ in _ID_ROUTES])
def test_an_id_route_answers_404_and_keeps_403_for_capability(route: str, op: Any) -> None:
    """Scenario: foreign and missing ids look the same (SR-E29-13, AC-02, AC-04)."""
    assert op["responses"]["404"] == _ref("responses", "NotFound")
    assert op["responses"]["403"] == _ref("responses", "Forbidden")


@pytest.mark.parametrize("name", ["OrderId", "PositionId"])
def test_an_id_parameter_answers_a_foreign_id_as_a_missing_one(name: str) -> None:
    text = _words(_PARAMS[name]["description"])
    assert "is answered exactly as an id that does not exist: `404` `not_found`" in text
    assert "it is never a scope answer" in text


def test_a_trade_group_with_an_ungranted_leg_is_answered_as_missing() -> None:
    text = _words(_PARAMS["TradeGroupId"]["description"])
    assert "is answered as a group that does not exist (SR-E28-21)" in text


def test_forbidden_names_the_scope_and_arm_refusals() -> None:
    forbidden = _SPEC["components"]["responses"]["Forbidden"]
    text = _words(forbidden["description"])
    assert "alike with `code: account_scope_denied` (see `AccountScopeDenied`)" in text
    assert "it may be `code: session_not_armed` (SR-043" in text
    example = forbidden["content"]["application/problem+json"]["examples"]["sessionNotArmed"]
    assert (example["value"]["status"], example["value"]["code"]) == (403, "session_not_armed")


def test_an_arm_refusal_binds_no_idempotency_key() -> None:
    binding = _words(_SPEC["info"]["description"]).split("**Binding point (#2304).**", 1)[1]
    assert "the arm state's `session_not_armed` of SR-043" in binding.split(". ", 1)[0]


@pytest.mark.parametrize("operation", _BULK)
def test_a_bulk_route_refuses_an_out_of_scope_id_whole(operation: str) -> None:
    """Scenario: one out-of-scope id refuses a bulk request whole (SR-E29-13, AC-03)."""
    op = _OPS[operation]
    text = _words(op["description"])
    assert "refuses the whole request alike with `403 account_scope_denied`" in text
    verb = "cancelled" if operation == "cancelAllOrders" else "closed"
    assert f"nothing is {verb}, no exchange call is made, and the refusal is audited" in text
    assert "reports exchange outcomes only" in text
    assert "Partial success is normal" not in text
    assert "404" not in op["responses"]  # an unknown account is not an existence oracle


def test_bulk_account_results_hold_exchange_outcomes_only() -> None:
    assert "A scope refusal never appears here" in _words(
        _SCHEMAS["BulkAccountResult"]["description"]
    )


def test_every_order_mutation_is_either_armed_or_carved_out() -> None:
    assert sorted(_ARMED + _CARVED_OUT) == _MUTATIONS


@pytest.mark.parametrize("operation", _ARMED)
def test_a_risk_increasing_order_mutation_declares_the_arm_token(operation: str) -> None:
    """Scenario: a live order mutation needs an arm token (SR-043, OM-S01, N2)."""
    op = _OPS[operation]
    assert _ARM_TOKEN in op["parameters"]
    assert "arm_token" not in _request_properties(op)


@pytest.mark.parametrize("operation", _CARVED_OUT)
def test_a_risk_reducing_route_never_needs_the_arm_token(operation: str) -> None:
    """C-2.6: cancels and closes keep working unarmed (24-internal-schemas.md 8.10)."""
    op = _OPS[operation]
    assert _ARM_TOKEN not in op["parameters"]
    assert "arm_token" not in _request_properties(op)


def test_the_arm_token_is_refused_with_a_registered_code_and_spares_the_carve_out() -> None:
    param = _PARAMS["ArmToken"]
    assert (param["name"], param["in"], param["required"]) == ("X-Arm-Token", "header", False)
    text = _words(param["description"])
    assert "On a live account every order mutation that opens or increases exposure" in text
    assert "`403 session_not_armed`, audited, before any exchange call" in text
    assert "before the idempotency lookup" in text
    assert "cancels, `closePosition`, `closeAllPositions`, quantity-reducing amends" in text
    assert "The token is never logged (C-12.6)." in text
    assert "reduce-only ones included" in text and "a leverage change in either direction" in text
    assert "so is a token issued without the live step-up" in text
    entry = next(e for e in _SPEC["x-error-codes"] if e["code"] == "session_not_armed")
    assert (entry["status"], entry["retryable"]) == (403, False)


def test_the_cors_header_list_names_every_declared_header_parameter() -> None:
    """The desktop preflight allows every declared header (#3712), `X-Arm-Token` included."""
    declared = {p["name"] for p in _PARAMS.values() if p.get("in") == "header"}
    declared |= {
        p["name"]
        for _, _, op in _ROUTES
        for p in op.get("parameters", [])
        if "name" in p and p.get("in") == "header"
    }
    cors = _words(_SPEC["info"]["description"]).split("### Cross-origin (CORS)", 1)[1]
    today = re.search(r"every header parameter this document declares \(today ([^)]*)\)", cors)
    assert today is not None
    assert set(re.findall(r"`([A-Za-z-]+)`", today.group(1))) == declared


def test_arming_for_live_needs_a_fresh_step_up() -> None:
    """N2: a client holding only the session and the CSRF token cannot arm itself (SR-025)."""
    text = _words(_OPS["armOneClickTrading"]["description"])
    assert "Arming needs a fresh step-up while a live account is within the caller's reach" in text
    assert "Without one it answers `403 step_up_required` with the class `live_enablement`" in text
    assert "`one_click`" not in text  # no request field of that name exists
    # The Owner holds no grants, so "within reach" names both principals (R2-M1).
    assert "for the Owner whenever one exists, for a Manager through a trade grant" in text
    assert "one issued without it never satisfies a live mutation" in text


def test_the_kill_switch_reports_failures_as_closed_rows_without_exchange_text() -> None:
    """SR-E29-09: the kill switch's cancel and flatten failures are closed rows (R2-m1)."""
    actions = _SCHEMAS["KillSwitchResult"]["properties"]["actions"]["properties"]
    row = actions["failures"]["items"]
    assert row["additionalProperties"] is False
    assert set(row["properties"]) == {"exchange_account_id", "ok", "affected", "error"}


def test_the_kill_switch_claims_no_dead_mans_switch() -> None:
    """OM-D05: `inverse` is out of scope (C-1.2); SR-059 names the compensating control."""
    text = _words(_OPS["setKillSwitch"]["description"])
    assert "inverse" not in text
    assert "disconnected-cancel-all" not in text
    assert (
        "the compensating control for a lost connection is the native stop (C-2.6) plus "
        "reconciliation on reconnect (SR-058, SR-059)" in text
    )
