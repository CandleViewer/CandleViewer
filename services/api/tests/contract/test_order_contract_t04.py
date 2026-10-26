"""Contract (#913, E29-T04): the order contract says what the submission pipeline answers.

From E29-T04's contract-first bullet and the rulings on its plan (#913), read from
`22-api-openapi.yaml`, `21-database-schema.md` sections 3.3.4 and 3.3.10, `24-internal-schemas.md`
sections 8.1 to 8.6, `28-statechart-catalogue.md`, the E29 threat model and the regenerated
models, never from a copy: no text derives the `orderLinkId` from the `Idempotency-Key`;
`placeOrder`'s `202` and its permanent anchor (R3); the ruled order of the checks (R2); each
answer where the route gives it (R4, R5, R7, R8, R12), the two rate refusals (#2877 ruling 4) and
the profile's own refusal among them; `createTradeGroup`'s repeats; an order's provenance; the
pairing rule of the 2026-10-21 rulings on #3972 (28's text and the threat model's anchor); and B1's
entry of a recorded stop's row (CR-G6-R3-01 on #3972): 24 section 8.2's event kinds pinned to the
chart and the step writer, and the texts that say the row exists; and the size step, its outcome
mapping, the price band and `sizing_unavailable` (#913 S4-S), as text and registry only.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any, Literal, get_args, get_origin
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from candleviewer.accounts.sizer import FailReason, SkipReason
from candleviewer.api._generated import openapi_models as rest
from candleviewer.api.contract_conformance import OPENAPI_SPEC_PATH, load_openapi_spec
from candleviewer.domain.order_link import EXT_ID, OUR_ID
from candleviewer.domain.primitives import AccountId, GroupId
from candleviewer.exchange.base.errors import OmsErrorCode
from candleviewer.oms.order_link import OrderLinkIdParts
from candleviewer.oms.order_machine import Legality
from candleviewer.oms.order_steps import event_kind
from candleviewer.statechart.bindings.b01_order import Step, map_reject_code
from candleviewer.statechart.registry import Registry
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode
from tests.openapi_helpers import deref

_SPEC: Any = load_openapi_spec()  # a parsed YAML document, walked untyped
_SCHEMAS: dict[str, Any] = _SPEC["components"]["schemas"]
_RESPONSES: dict[str, Any] = _SPEC["components"]["responses"]
_OPS: dict[str, Any] = {
    op["operationId"]: op
    for item in _SPEC["paths"].values()
    for op in item.values()
    if isinstance(op, dict) and "operationId" in op
}
_PLACE: Any = _OPS["placeOrder"]
_EXAMPLES: Any = _PLACE["responses"]["202"]["content"]["application/json"]["examples"]
_CODES: dict[str, Any] = {entry["code"]: entry for entry in _SPEC["x-error-codes"]}
_PLAN = OPENAPI_SPEC_PATH.parent
_ARCH = (_PLAN / "20-architecture.md").read_text(encoding="utf-8")
_SCHEMA_DOC = (_PLAN / "21-database-schema.md").read_text(encoding="utf-8")
_INTERNAL_DOC = (_PLAN / "24-internal-schemas.md").read_text(encoding="utf-8")
_CATALOGUE = (_PLAN / "28-statechart-catalogue.md").read_text(encoding="utf-8")
_THREAT_MODEL = (_PLAN.parent / "security" / "threat-models" / "E29-oms.md").read_text("utf-8")
_WS_BUNDLE = _PLAN.parents[1] / "packages" / "protocol" / "ws-schemas.json"
_WS_SCHEMAS: Any = json.loads(_WS_BUNDLE.read_text(encoding="utf-8"))["schemas"]
_CANONICAL_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
#: The `createTradeGroup` example's ref, as G-6's contract PR (#3972) writes it.
_G6_GROUP_REF = "7d3e9b1a-5c2f-4a8e-9b6d-0e1f2a3b4c5d"
#: R2's order, as 22's paragraph and 24 section 8.4's numbered steps both name it.
_STEPS = "account scope|arm token|idempotency lookup|live trading enabled|kill switch|"
_STEPS += "order-entry gate|valid|siz|risk|persist|send"


def _words(text: str) -> str:
    """A description on one line: a YAML block keeps its line breaks, a phrase may span two."""
    return " ".join(text.split())


def _model_rows(ident: str) -> list[str]:
    """The E29 model's table rows for `ident`, whatever padding Prettier gives the first column
    (a longer id in the same table, such as OM-T05b, widens it for every row)."""
    head = re.compile(rf"^\|\s*{re.escape(ident)}\s*\|")
    return [row for row in _THREAT_MODEL.splitlines() if head.match(row)]


def _between(text: str, start: str, end: str) -> str:
    return _words(text.split(start, 1)[1].split(end, 1)[0])


def _in_order(text: str) -> bool:
    at = [text.index(step) for step in _STEPS.split("|")]
    return at == sorted(at)


def _missing(text: str, *statements: str) -> list[str]:
    return [statement for statement in statements if statement not in text]


def _values(node: object, key: str | None = None) -> Iterator[Any]:
    """Every value under `key` below `node`, or every string below it when `key` is None."""
    if isinstance(node, dict):
        for name, value in node.items():
            if key is not None and name == key:
                yield value
            yield from _values(value, key)
    elif isinstance(node, list):
        for value in node:
            yield from _values(value, key)
    elif key is None and isinstance(node, str):
        yield node


def _validate(schema_name: str, instance: object) -> None:
    schema = deref(_SPEC, {"$ref": f"#/components/schemas/{schema_name}"})
    checker = Draft202012Validator.FORMAT_CHECKER
    Draft202012Validator(schema, format_checker=checker).validate(instance)


def test_no_text_derives_the_order_link_id_from_the_idempotency_key() -> None:
    """Threat model section 12.3 note 2: the texts E29-T04's contract PR aligns."""
    assert "it is never part of an exchange id" in _words(_PLACE["description"])
    key = _words(_SPEC["components"]["parameters"]["IdempotencyKeyRequired"]["description"])
    assert "never part of an exchange id" in key and "seeds" not in key
    assert "(and, on an order submit or amend, the `trading_disabled` checks) all pass" in key
    link = _words(_SCHEMAS["Order"]["properties"]["order_link_id"]["description"])
    assert "never derived from the `Idempotency-Key` or any other client-supplied string" in link
    together = [  # wherever the id and the key share a sentence, it denies the derivation
        sentence
        for text in map(_words, _values(_SPEC))
        for sentence in re.split(r"(?<=\.) ", text)
        if re.search(r"orderLinkId|order_link_id", sentence) and "Idempotency-Key" in sentence
    ]
    assert together
    assert [s for s in together if not re.search(r"\bnever\b|no client-supplied", s)] == []


def test_every_example_id_is_the_one_its_order_generates() -> None:
    """24 section 8.3: `group22` is the order's group, or the order itself when it has none."""
    pattern = re.compile(_SCHEMAS["Order"]["properties"]["order_link_id"]["pattern"])
    ids = list(_values(_SPEC["paths"], "order_link_id"))
    assert len(ids) == 3  # listOrders' example and both of placeOrder's
    shaped = [i for i in ids if pattern.fullmatch(i) and (OUR_ID.match(i) or EXT_ID.match(i))]
    assert shaped == ids
    assert not pattern.fullmatch("cv-0c000000-1-entry")  # the key-derived form is refused
    page = _OPS["listOrders"]["responses"]["200"]["content"]["application/json"]["examples"]
    [listed] = page["openLimit"]["value"]["items"]
    [entry] = _EXAMPLES["entry"]["value"]["trade_group"]["legs"][0]["order_details"]
    for order in (listed, entry, _EXAMPLES["reduceOnly"]["value"]["order"]):  # `seq2` 0
        generated = OrderLinkIdParts.generate(
            mode="exchange",
            environment=order["environment"],
            group_id=GroupId(UUID(order["trade_group_id"] or order["id"])),
            account_id=AccountId(UUID(order["exchange_account_id"])),
            seq=0,
            purpose=order["intent"],
        )
        assert order["order_link_id"] == generated.value
    rule = _between(_INTERNAL_DOC, "### 8.3 ", "### 8.4 ")
    assert "(a reduce-only `placeOrder`, 22 `OrderAcceptance`) takes `group22` from its own" in rule


def test_every_client_group_ref_example_has_the_schema_format() -> None:
    ref = _SCHEMAS["TradeGroup"]["properties"]["client_group_ref"]
    assert ref["format"] == "uuid"
    assert not _missing(
        _words(ref["description"]),
        "placing request's `Idempotency-Key`",
        "or the server-minted UUID of a rule-, alert- or replay-originated group",
    )
    refs = list(_values(_SPEC["paths"], "client_group_ref"))
    assert len(refs) == 2  # createTradeGroup's example and placeOrder's entry
    assert [value for value in refs if not _CANONICAL_UUID.fullmatch(value)] == []
    group = _OPS["createTradeGroup"]["responses"]["202"]["content"]["application/json"]
    # The ref G-6 (#3972) gives the same example, so the two contract PRs agree on it.
    assert group["examples"]["accepted"]["value"]["client_group_ref"] == _G6_GROUP_REF


def test_place_order_accepts_with_every_created_order_and_its_state() -> None:
    """Scenario: happy path is an acceptance, not a fill (R3: the `202` body, breaking)."""
    accepted = _PLACE["responses"]["202"]["content"]["application/json"]["schema"]
    assert accepted == {"$ref": "#/components/schemas/OrderAcceptance"}
    schema = _SCHEMAS["OrderAcceptance"]
    required = ["trade_group", "order", "reconciling"]  # slice 3's Q2 member has its own test
    assert (schema["additionalProperties"], schema["required"]) == (False, required)
    assert set(schema["properties"]) == set(required)
    assert {name: schema["properties"][name] for name in required[:2]} == {
        "trade_group": {"oneOf": [{"$ref": "#/components/schemas/TradeGroup"}, {"type": "null"}]},
        "order": {"oneOf": [{"$ref": "#/components/schemas/Order"}, {"type": "null"}]},
    }
    details = _SCHEMAS["TradeGroupLeg"]["properties"]["order_details"]["items"]
    assert details == {"$ref": "#/components/schemas/Order"}
    assert not _missing(
        _words(schema["description"]),
        "Exactly one member is non-null",
        "its leg carrying the order in `order_details`, and `order` is null",
        "joins no trade group: `order` holds it",
    )
    assert rest.OrderAcceptance.model_config.get("extra") == "forbid"
    assert "order_details" in rest.TradeGroupLeg.model_fields
    assert not _missing(  # scenario: transport failure lands in Unknown; a held duplicate id
        _words(_PLACE["description"]),
        "for an entry the server creates a one-leg trade group internally",
        "A reduce-only order that only reduces joins no trade group (`OrderAcceptance`)",
        "also answers `202`, with the order in `unknown`: it is never re-sent (C-2.10)",
        "So does an id the exchange already holds: the order is adopted after its full match",
    )


@pytest.mark.parametrize(
    ("name", "member", "lifecycle"),
    [("entry", "trade_group", "submitted"), ("reduceOnly", "order", "unknown")],
)
def test_each_acceptance_example_has_one_member_and_states_its_orders(
    name: str, member: str, lifecycle: str
) -> None:
    value = _EXAMPLES[name]["value"]
    _validate("OrderAcceptance", value)
    assert [key for key in ("trade_group", "order") if value[key] is not None] == [member]
    group = value["trade_group"]
    orders = [value["order"]] if group is None else group["legs"][0]["order_details"]
    if group is not None:  # the ids and the embedded orders name the same rows
        assert group["legs"][0]["orders"] == [order["id"] for order in orders]
    assert [order["lifecycle_state"] for order in orders] == [lifecycle]
    assert [order["trade_group_id"] for order in orders] == [group and group["id"]]


def test_the_order_routes_run_their_checks_in_the_ruled_order() -> None:
    """R2: scope, arm, replay, live, kill switch, gate, validate, size, risk, persist, send."""
    binding = _words(_SPEC["info"]["description"]).split("**Binding point (#2304).**", 1)[1]
    first_sentence = binding.split(". ", 1)[0]
    assert "and, on an order submit or amend, the `trading_disabled` refusals" in first_sentence
    order = binding.split("**Order of the checks on an order submit or amend (E29-T04).**")[1]
    assert _in_order(order)
    assert not _missing(
        order,
        "`amendOrder` takes the same order (its scope is the order id's `404`)",
        "while the same key with another body is still `409 idempotency_key_reuse` (C-2.10)",
    )
    steps = _INTERNAL_DOC.split("### 8.4 ", 1)[1].split("**8.4.1 ", 1)[0]
    items = _words(" ".join(re.findall(r"^\d\. (.*)$", steps, re.MULTILINE)))
    assert _in_order(items)  # 24 section 8.4 states the order 22 states
    assert "`amendOrder` checks in the same order (its scope is the order id's `404`)" in items
    assert not _missing(
        _words(_SPEC["components"]["parameters"]["ArmToken"]["description"]),
        "and before the idempotency lookup: a refused request binds no `Idempotency-Key`",
        "On `placeOrder` and `amendOrder` the live-enabled, kill-switch and order-entry-gate "
        "checks come after the lookup instead; the arm token stays before it",
    )
    assert not _missing(
        _words(_RESPONSES["Forbidden"]["description"]),
        "A `trading_disabled` body without `reason` is this response's plain `Problem`",
        "On `placeOrder` and `amendOrder` the three come after the idempotency lookup",
    )
    reasonless: dict[str, object] = {"title": "Order entry refused", "status": 403}
    reasonless |= {"type": "https://candleviewer.local/errors/trading_disabled"}
    reasonless |= {"code": "trading_disabled"}
    _validate("Problem", reasonless)
    with pytest.raises(ValidationError, match="'reason' is a required property"):
        _validate("TradingDisabledProblem", reasonless)


def test_a_repeat_of_place_order_reaches_its_rows_through_a_permanent_anchor() -> None:
    """Scenario: idempotent replay (R3, SR-E29-07), an undecided anchor included."""
    assert not _missing(
        _words(_PLACE["description"]),
        "in a permanent anchor scoped to the caller and this operation",
        "SR-E29-07), written in the one transaction that persists the request's rows",
        "Inside the 24 h record the replay is the original answer; later it carries the same",
        "`409 idempotency_key_reuse`, as is a key this principal already used for a trade group",
        "is `409 idempotency_in_flight` with `retry_after_seconds`",
        "and a key that another principal sent is answered as one never seen",
        "A repeat never sends: only the first request starts its order's send",
        "a repeat is `409 idempotency_in_flight` only within `CV_OMS_INFLIGHT_STUCK_S` (30 s)",
        "`202` with the rows in their reconciled state, never an assumed success: while",
        "reconciliation has not resolved the order (still `validated`, never sent, `submitting`, "
        "`unknown` or `quarantined`) the answer says `reconciling`",
    )
    general = _words(_SPEC["info"]["description"]).split("### Idempotency", 1)[1]
    assert "Exception (E29-T04): `placeOrder` also keeps the key in a permanent anchor" in general
    in_flight = _CODES["idempotency_in_flight"]
    assert (in_flight["status"], in_flight["retryable"]) == (409, True)
    assert "retry_after_seconds" in _SCHEMAS["Problem"]["properties"]
    assert not _missing(
        _between(_INTERNAL_DOC, "\n6. ", "**8.4.1 "),
        "recorded on the anchor by compare-and-set from NULL before the request answers",
        "only within `CV_OMS_INFLIGHT_STUCK_S` (30 s, E29-T08's in-flight threshold)",
        "A repeat never sends: only the first request starts its order's send",
        "A store failure after the send is never a `503`",
    )


def test_the_anchor_table_is_principal_scoped_permanent_and_written_with_its_order() -> None:
    """21 section 3.3.10 with its ERD, retention, class and revision rows (R3), and the TRUNCATE
    guard of the Q8 ruling, as slice 2a's revision ships it (SR-E29-05's pattern)."""
    table = _SCHEMA_DOC.split("#### 3.3.10 `idempotency_anchors`", 1)[1].split("### 3.4 ")[0]
    assert "CONSTRAINT ux_ia_principal_ref UNIQUE (created_by, operation, client_ref)" in table
    [listed] = re.findall(r"ia_operation CHECK \(operation IN \(([^)]*)\)\)", table)
    operations = [name.strip("'") for name in listed.split(",")]
    assert operations == ["placeOrder", "closePosition", "reversePosition", "closeAllPositions"]
    assert set(operations) <= set(_OPS)
    assert "(operation <> 'placeOrder' OR num_nonnulls(trade_group_id, order_id) = 1)" in table
    assert not _missing(
        _words(table),
        "in the one transaction that persists the request's rows, B1's `VALIDATE` step",
        "So an anchor never exists without its order",
        "its `client_body_sha256` holding the anchor's `request_sha256`",
        "`409 idempotency_in_flight` only within `CV_OMS_INFLIGHT_STUCK_S` (30 s) of `created_at`",
        "and a repeat never sends (24 §8.4)",
    )
    trigger = table.split("CREATE FUNCTION ia_write_once()", 1)[1]
    write_once = "id created_by operation client_ref request_sha256 trade_group_id order_id "
    write_once += "created_at outcome_status outcome_code outcome_ret_code decided_at"
    assert [c for c in write_once.split() if not re.search(rf"NEW\.{c}\b", trigger)] == []
    assert "ERRCODE = 'check_violation', CONSTRAINT = 'trg_ia_write_once'" in trigger
    assert "ALTER TABLE idempotency_anchors ENABLE ALWAYS TRIGGER trg_ia_write_once;" in trigger
    second = table.split("```sql")[2].split("```", 1)[0]
    assert second.endswith(
        "ALTER TABLE idempotency_anchors ENABLE ALWAYS TRIGGER trg_ia_write_once;\n"
        "CREATE TRIGGER trg_ia_no_truncate BEFORE TRUNCATE ON idempotency_anchors\n"
        "  FOR EACH STATEMENT EXECUTE FUNCTION audit_refuse_truncate();\n"
        "ALTER TABLE idempotency_anchors ENABLE ALWAYS TRIGGER trg_ia_no_truncate;\n"
        "-- REVOKE DELETE, TRUNCATE ON idempotency_anchors FROM cv_app, cv_ro;\n"
    )
    assert "CREATE FUNCTION audit_refuse_truncate() RETURNS trigger" in _SCHEMA_DOC  # 0003's
    assert (
        "`cv_app` and `cv_ro` hold no DELETE or TRUNCATE on the table where the roles exist, and "
        "`trg_ia_no_truncate` (BEFORE TRUNCATE, `ENABLE ALWAYS`, 0003's `audit_refuse_truncate()`) "
        "refuses a TRUNCATE by any role, SR-E29-05's pattern: the anchor is permanent (§7)"
    ) in _words(table)
    assert "idempotency_anchors |o--o| orders : names" in _between(
        _SCHEMA_DOC, "### 2.2", "### 2.3"
    )
    assert "| `idempotency_anchors` (PG) " in _between(_SCHEMA_DOC, "\n## 7. ", "\n## 8. ")
    assert "| `idempotency_anchors` | `client_ref`" in _words(_SCHEMA_DOC.split("\n## 12. ")[1])
    revisions = _between(_SCHEMA_DOC, "### 9.4 ", "### 9.5 ")
    revision = revisions.split("| `0043_order_submission` ")[1]
    assert revision.startswith(
        "| `idempotency_anchors` (§3.3.10), `recorded_stops` (§3.3.11) and `orders.provenance` "
        "(§3.3.4), their guard and TRUNCATE triggers; no `DELETE` or `TRUNCATE` for `cv_app`"
    )
    assert "NULL for adopted orders and groupless ones (§3.3.10)" in _SCHEMA_DOC


def test_place_order_declares_each_answer_the_pipeline_gives() -> None:
    """R12 and S4-S: clock drift, a lost store, the spent id bound, the size step (the rate
    budget's two refusals have a test of their own, below)."""
    responses = _PLACE["responses"]
    for status, name in (
        ("502", "OrderExchangeError"),
        ("503", "ServiceUnavailable"),
    ):
        assert responses[status] == {"$ref": f"#/components/responses/{name}"}
    assert "Retry-After" in _RESPONSES["ServiceUnavailable"]["headers"]
    assert "the condition pages the operator" in _words(responses["500"]["description"])
    assert not _missing(
        _words(_PLACE["description"]),
        "or the exchange clock guard past 2000 ms, section 2.8), the request is refused with "
        "`503 clock_drift` and `Retry-After` until time sync recovers",
        "A request whose own create meets `10002` was sent and refused: its order is `rejected`",
        "A store failure after the send is never a `503`",
        "sends nothing and answers `500 internal_error`, which pages",
        "refuse with `403 trading_disabled` before anything reaches the exchange",
        "an order that is not reduce-only is sized by the profile's sizer (24-internal-schemas.md "
        "section 9.3, `size_leg`), never by a client figure",
        "an `r_multiple` stop, which defines R, is `validation_failed` / `stop_unit_unsupported`",
        "`400` for `validation_failed` (each failing rule in `errors[]`)",
        "and `403` for `risk_limit_breached`",
    )
    assert {"atr", "r_multiple"} <= set(_SCHEMAS["OffsetUnit"]["enum"])
    expected = {"exchange_rate_limited": 429, "clock_drift": 503, "internal_error": 500}
    assert {code: _CODES[code]["status"] for code in expected} == expected
    assert _CODES["clock_drift"]["retryable"] is True
    title = _CODES["clock_drift"]["title"]
    assert ERROR_META[ErrorCode("clock_drift")].title == title
    assert re.search(r"(?i)\bbybit\b|\d{4,}", title) is None  # C-6.5: no vendor, no raw code
    drift = _RESPONSES["ServiceUnavailable"]["content"]["application/problem+json"]["examples"]
    assert (drift["clockDrift"]["value"]["code"], drift["clockDrift"]["value"]["title"]) == (
        "clock_drift",
        title,
    )
    guard = _between(_INTERNAL_DOC, "### 2.8 ", "### 2.9 ")
    assert '`ClockSyncEvent.action == "block_trading"` when `abs(offset_ms) > 2000`' in guard


def test_order_entry_is_refused_with_503_store_unavailable_when_it_cannot_be_recorded() -> None:
    """Scenario: order entry blocked when we cannot record it. `store_unavailable` is the
    registry's code; the ticket's `service_unavailable` is no `x-error-codes` slug."""
    assert (_CODES["store_unavailable"]["status"], "service_unavailable" in _CODES) == (503, False)
    unavailable = _RESPONSES["ServiceUnavailable"]["content"]["application/problem+json"]
    assert unavailable["examples"]["storeUnavailable"]["value"]["code"] == "store_unavailable"
    text = _words(_PLACE["description"])
    assert "refused with `503 store_unavailable` before any exchange call" in text


def test_the_422_examples_are_marked_with_the_registry_statuses() -> None:
    """`native_stop_required` is a `400 validation_failed` and a risk refusal a `403` (#2088)."""
    statuses = (_CODES["validation_failed"]["status"], _CODES["risk_limit_breached"]["status"])
    assert statuses == (400, 403)
    text = _words(_RESPONSES["UnprocessableEntity"]["description"])
    assert "answer `validation_failed` with `400` and `risk_limit_breached` with `403`" in text


def test_an_amend_with_a_stale_if_match_is_refused_with_412() -> None:
    """R5: T04 honours `If-Match` on `PATCH /orders/{orderId}`."""
    amend = _OPS["amendOrder"]
    assert {"$ref": "#/components/parameters/IfMatch"} in amend["parameters"]
    assert amend["responses"]["412"] == {"$ref": "#/components/responses/PreconditionFailed"}
    stale = _RESPONSES["PreconditionFailed"]["content"]["application/problem+json"]["examples"]
    assert stale["stale"]["value"]["code"] == "version_conflict"
    assert "ETag" in amend["responses"]["202"]["headers"]
    assert not _missing(
        _words(amend["description"]),
        "The `ETag` is opaque and changes with every step the order takes, each `order_events`",
        "the amend is refused with `412 version_conflict` and nothing is sent",
    )


def test_a_trade_group_refuses_a_mismatched_intent_before_any_leg_is_sent() -> None:
    """R7: a reduce-only leg may need a position read before it can be classified."""
    text = _words(_OPS["createTradeGroup"]["description"])
    assert "That refusal is the whole request's, before any leg is sent, whatever" in text
    assert "or any exchange call is made" not in text


def test_the_exchange_text_reaches_no_order_answer() -> None:
    """R8: 24 section 8.6's verbatim rule is the code-only rule (SR-E29-09)."""
    assert "Verbatim rule" not in _INTERNAL_DOC
    rule = _between(_INTERNAL_DOC, "**Code-only rule (SR-E29-09; #913 ruling R8):**", "\n")
    assert "(`OrderExchangeProblem`, whose `exchange` holds `ret_code` only)" in rule
    shape = _SCHEMAS["OrderExchangeProblem"]["allOf"][1]["properties"]["exchange"]
    assert (shape["additionalProperties"], list(shape["properties"])) == (False, ["ret_code"])


def _request_schemas() -> set[str]:
    """Every component schema a request body can reach, by name (a cycle-safe `$ref` walk)."""
    todo = [ref for op in _OPS.values() for ref in _values(op.get("requestBody", {}), "$ref")]
    seen: set[str] = set()
    while todo:
        name = todo.pop().rsplit("/", 1)[-1]
        if name not in seen:
            seen.add(name)
            todo.extend(_values(_SCHEMAS[name], "$ref"))
    return seen


def test_the_rate_budget_refuses_before_the_persist_or_at_the_send() -> None:
    """#2877 ruling 4 (R12): a headroom read binds no key; a send with no token ends `rejected`,
    recorded under the key, so its repeat says it is a replay and gives no `Retry-After` to
    honour under that key (the fold round's Low on the retry loop)."""
    limited_429 = _PLACE["responses"]["429"]
    replayed = {"$ref": "#/components/headers/IdempotencyReplayed"}
    assert limited_429["headers"]["Idempotency-Replayed"] == replayed
    assert limited_429["headers"]["Retry-After"] == {"$ref": "#/components/headers/RetryAfter"}
    assert set(_RESPONSES["RateLimited"]["headers"]) < set(limited_429["headers"])
    problem = limited_429["content"]["application/problem+json"]["schema"]
    assert problem == {"$ref": "#/components/schemas/Problem"}
    assert not _missing(
        _words(limited_429["description"]),
        "The headroom refusal before the persist binds no key, so the same key and body may be "
        "sent again after `Retry-After`",
        "The refusal at the send is recorded under the key and is not retryable under it: a "
        "repeat gets that `429` again with `Idempotency-Replayed: true` and no `Retry-After`, and "
        "placing the order again takes a new `Idempotency-Key`",
    )
    limited = _CODES["exchange_rate_limited"]
    assert (limited["status"], limited["retryable"]) == (429, True)
    assert not _missing(
        _words(_PLACE["description"]),
        "The account's per-UID exchange budget refuses at two points, each with "
        "`429 exchange_rate_limited` and `Retry-After`",
        "with none, nothing is recorded or sent and the key is not bound, so the same key and "
        "body sent again after `Retry-After` are a first submission",
        "(for an entry `CV_FANOUT_ADMIT_WAIT_MS`, 750 ms, `20-architecture.md` section 4.3) and "
        "never queueing past it",
        "the recorded order ends `rejected` with `RATE_BUDGET_EXCEEDED`, a refused send, never "
        "`unknown`, answered as `429 exchange_rate_limited` and stored as the anchor's "
        "`outcome_code` (`21-database-schema.md` section 3.3.10)",
        "so a repeat at any age gets the same `429` and sends nothing: placing the order again "
        "takes a new `Idempotency-Key`. It is not retryable under its key: the repeat carries "
        "`Idempotency-Replayed: true` and no `Retry-After`",
    )
    general = _words(_SPEC["info"]["description"]).split("### Idempotency", 1)[1]
    assert (
        "A `placeOrder` refused at the exchange budget's headroom, before its persist "
        "(`429 exchange_rate_limited`), stores nothing under the key either" in general
    )
    diagram = _INTERNAL_DOC.split("### 8.4 ", 1)[1].split("```", 2)[1]
    steps = ["OMS->>AD: headroom(", "VALIDATE, one transaction", "OMS->>AD: place_order("]
    steps += ["AD->>RL: acquire(", "AD->>BY: POST /v5/order/create"]
    at = [diagram.index(step) for step in steps]
    assert at == sorted(at)  # the headroom before the persist, the token after it, then the send
    assert ("OMS->>RL" in diagram, "RL-->>OMS" in diagram) == (False, False)  # only the port's
    no_token = diagram.split("else no rate token within the bound", 1)[1].split("else ", 1)[0]
    assert not _missing(
        no_token,
        "RateBudgetExceededError, nothing sent: a refused send (not-ok ack), never ambiguous",
        "OMS->>PG: state=rejected, reject_code=RATE_BUDGET_EXCEEDED, event",
    )
    assert not _missing(
        _between(_INTERNAL_DOC, "\n4. B1's `rate` verdict", "\n5. "),
        "reads the account's headroom through the trading port, a figure that takes no token",
        "and the key is not bound (`22-api-openapi.yaml` Idempotency), so the same key and body "
        "after `Retry-After` are a first submission",
        "taken once, by the trading port as the create leaves (step 6), never by a governor call "
        "from `oms` (C-2.2)",
    )
    assert not _missing(
        _between(_INTERNAL_DOC, "\n6. The send's outcome", "\nA request that ends"),
        "and a create that gets no rate token `429 exchange_rate_limited` with `Retry-After`",
        "(for an entry `CV_FANOUT_ADMIT_WAIT_MS`, 750 ms, `20-architecture.md` §4.3)",
        "B1's command port answers it as a refused send (a not-ok ack), never as an ambiguous "
        "outcome, so the order ends `rejected` with `RATE_BUDGET_EXCEEDED` (§8.6) and never "
        "reaches `unknown`; the request answers `429 exchange_rate_limited`, the slug the anchor "
        "stores as its `outcome_code` (`21-database-schema.md` §3.3.10)",
        "It is not retryable under its key: the repeat carries `Idempotency-Replayed: true` and "
        "no `Retry-After` (`22-api-openapi.yaml` `placeOrder`)",
    )
    anchor = _SCHEMA_DOC.split("#### 3.3.10 `idempotency_anchors`", 1)[1].split("### 3.4 ")[0]
    [status] = re.findall(r"^\| `outcome_status` .*$", anchor, re.MULTILINE)
    assert re.findall(r"`(\d{3})`", status) == ["202", "429", "502"]
    assert "the `429 exchange_rate_limited` of a create the trading port sent nothing for" in (
        _words(anchor)
    )
    # The order's `reject_code` is a 24 section 8.6 taxonomy code; the slug is the answer's and
    # the anchor's `outcome_code` only (the delta review's Medium).
    assert OmsErrorCode("RATE_BUDGET_EXCEEDED") is OmsErrorCode.RATE_BUDGET_EXCEEDED
    assert "exchange_rate_limited" not in {code.value for code in OmsErrorCode}


@pytest.mark.parametrize(
    ("code", "recorded"),
    [
        ("RATE_BUDGET_EXCEEDED", "RATE_BUDGET_EXCEEDED"),
        ("exchange_rate_limited", "EXCHANGE_UNKNOWN"),
    ],
    ids=["taxonomy_code", "rest_slug"],
)
async def test_b1_records_a_send_with_no_rate_token_under_the_code_24_names(
    code: str, recorded: str
) -> None:
    """24 section 8.4 step 6: the command port answers a create that got no rate token with a
    not-ok ack naming `RATE_BUDGET_EXCEEDED`, which B1's `map_reject_code` keeps as the order's
    `reject_code`. The REST slug is no taxonomy code: B1 would record it as `EXCHANGE_UNKNOWN`."""
    context: dict[str, Any] = {}
    await map_reject_code(None, context, {"ok": False, "error_code": code}, None)
    assert context["reject_code"] == recorded


def test_a_profile_that_is_off_or_does_not_allow_the_symbol_is_a_risk_refusal() -> None:
    """24 section 9.3 step 1: the profile is enabled, trading-enabled and allows the symbol."""
    breached = _CODES["risk_limit_breached"]
    assert (breached["status"], breached["retryable"]) == (403, False)
    title = "The account's profile is disabled, is not trading-enabled, does not allow the symbol, "
    assert breached["title"] == title + (
        "or a risk cap (daily loss, max position) would be exceeded, by the account's state or "
        "by a submitted value"
    )
    assert ERROR_META[ErrorCode("risk_limit_breached")].title == breached["title"]
    assert (
        "The account's bound profile, its default (`is_default`), must be enabled and "
        "trading-enabled and allow the symbol, otherwise `risk_limit_breached` "
        "(24-internal-schemas.md section 9.3 step 1; the profile an account is created with is "
        "not trading-enabled" in _words(_PLACE["description"])
    )
    assert (
        "The size step's skips `profile_disabled`, `symbol_not_allowed` and `symbol_denied` are "
        "this refusal, as are its failures `cap_breached` and `insufficient_margin`, a cap the "
        "sized order would break" in _words(_PLACE["description"])
    )
    gate = _INTERNAL_DOC.split("### 9.3 Sizing algorithm", 1)[1].split("# 2. Reference price")[0]
    assert not _missing(
        gate,
        "if not profile.enabled or not profile.trading_enabled:",
        "matches(intent.symbol, profile.allowed_symbols)",
        "matches(intent.symbol, profile.denied_symbols)",
    )
    assert "The bootstrap profile is `enabled` and not `trading_enabled`" in _SCHEMA_DOC


def test_create_trade_group_answers_a_repeat_as_place_order_does() -> None:
    """Its `202` replay header and its `409`s are `placeOrder`'s; 24 section 8.3 rule 1 (#3972)."""
    group = _OPS["createTradeGroup"]["responses"]
    replayed = {"$ref": "#/components/headers/IdempotencyReplayed"}
    assert group["202"]["headers"] == {"Idempotency-Replayed": replayed}
    assert _PLACE["responses"]["202"]["headers"]["Idempotency-Replayed"] == replayed
    assert group["409"] == {"$ref": "#/components/responses/Conflict"}
    shared = _RESPONSES["Conflict"]["content"]["application/problem+json"]["examples"]
    place = _PLACE["responses"]["409"]["content"]["application/problem+json"]["examples"]
    assert shared.items() <= place.items()  # and the entry's stop answer, below
    assert not _missing(
        _words(_OPS["createTradeGroup"]["description"]).split("**Idempotency.**", 1)[1],
        "with the request's fingerprint, unique per creator (24-internal-schemas.md section 8.3 "
        "rule 1), so the same key and body, at any age, reach the same group and send nothing",
        "A repeat is admitted as a first submission is, so a grant withdrawn since refuses it",
        "While the 24 h record holds the key the replay is the original answer, and otherwise "
        "(expired, evicted or lost at a restart) the group in its current state as "
        "`getTradeGroup` returns it (`Idempotency-Replayed: true` either way)",
        "`409 idempotency_key_reuse` at any age, as is a key this principal already used for a "
        "`placeOrder` entry",
        "`409 idempotency_in_flight` with `retry_after_seconds`",
        "a key that another principal sent is answered as one never seen",
    )


def test_an_entry_whose_stop_request_collides_with_one_in_flight_is_refused_with_409() -> None:
    """The orchestrator's 2a ruling Q4 on #913: one stop request in flight per position (21
    section 3.3.11, the recorded stop, with slice 2a), so after a bounded retry a colliding entry
    is `409 stop_request_in_flight` with `Retry-After`, recording, sending and binding nothing.
    `conflict` is no fit: it is not retryable, and this request is, unchanged."""
    entry = _CODES["stop_request_in_flight"]
    assert (entry["status"], entry["retryable"]) == (409, True)
    assert _CODES["conflict"]["retryable"] is False
    assert ERROR_META[ErrorCode("stop_request_in_flight")].title == entry["title"]
    conflict = _PLACE["responses"]["409"]
    assert conflict["headers"] == {"Retry-After": {"$ref": "#/components/headers/RetryAfter"}}
    stop = conflict["content"]["application/problem+json"]["examples"]["stopRequestInFlight"]
    _validate("Problem", stop["value"])
    assert stop["value"]["code"] == "stop_request_in_flight"
    assert stop["value"]["title"] == entry["title"]
    assert stop["value"]["retry_after_seconds"] > 0
    carries = "`idempotency_in_flight` and `stop_request_in_flight` carry `Retry-After`"
    assert carries in _words(conflict["description"])
    assert not _missing(
        _words(_PLACE["description"]),
        "one stop request in flight per position (`21-database-schema.md` section 3.3.11, the "
        "recorded stop, which lands with E29-T04's slice 2a)",
        "An entry whose stop request collides with one still in flight on the same position is "
        "retried for a bounded time, then refused with `409 stop_request_in_flight` and "
        "`Retry-After`: nothing is recorded or sent and the key is not bound",
    )
    persist = _between(_INTERNAL_DOC, "\n5. The write-ahead persist", "\n6. ")
    assert (
        "An entry whose stop request collides with one still in flight on the same position (the "
        "recorded stop, `21-database-schema.md` §3.3.11, which lands with E29-T04's slice 2a) "
        "commits nothing: after a bounded retry it is refused with `409 stop_request_in_flight` "
        "and `Retry-After`, and the key is not bound"
    ) in persist


def test_every_order_says_how_its_row_came_to_exist_and_every_execution_has_one() -> None:
    """`OrderProvenance` (22), `orders.provenance` (21 section 3.3.4), 24 section 8.1: one set."""
    provenance = ["placed", "reconciliation", "recorded_stop"]
    assert _SCHEMAS["OrderProvenance"]["enum"] == provenance
    field = {"$ref": "#/components/schemas/OrderProvenance", "readOnly": True}
    assert _SCHEMAS["Order"]["properties"]["provenance"] == field
    generated = get_args(rest.Order.model_fields["provenance"].annotation)  # Literal | None
    assert [list(get_args(arg)) for arg in generated if get_origin(arg) is Literal] == [provenance]
    requests = _request_schemas()
    assert {"PlaceOrderRequest", "CreateTradeGroupRequest", "AmendOrderRequest"} <= requests
    assert [name for name in requests if "provenance" in _SCHEMAS[name].get("properties", {})] == []
    orders = _SCHEMA_DOC.split("#### 3.3.4 `orders`", 1)[1].split("#### 3.3.5 ", 1)[0]
    [listed] = re.findall(r"ord_provenance CHECK \(provenance IN \(([^)]*)\)\)", orders)
    assert [value.strip("'") for value in listed.split(",")] == provenance
    assert "ALTER TABLE orders ADD COLUMN provenance text NOT NULL DEFAULT 'placed';" in orders
    assert re.search(r"^\| `provenance` +\| text +\| no +\| `'placed'` +\|", orders, re.MULTILINE)
    assert not _missing(
        _words(orders),
        "`reconciliation`, an exchange order that reconciliation records as `untracked`",
        "which E29-T05 materialises bound to its exchange `orderId` when it first appears, on its "
        "push or in reconciliation, so that every execution has an order",
        "It decides nothing: an order or fill is OMS intent only through a row or a recorded stop",
    )
    model = _INTERNAL_DOC.split("class Order(BaseModel):", 1)[1].split("```", 1)[0]
    [declared] = re.findall(r'^    provenance: Literal\[([^\]]*)\] = "placed"', model, re.MULTILINE)
    assert [value.strip('"') for value in declared.split(",")] == provenance
    assert _SCHEMAS["Execution"]["properties"]["order_id"] == {"type": "string", "format": "uuid"}
    frame = _WS_SCHEMAS["cv://ws/v1/executions.schema.json"]["properties"]["executions"]["items"]
    assert "order_id" in frame["required"]
    assert frame["properties"]["order_id"] == {"$ref": "cv://ws/v1/common.schema.json#/$defs/uuid"}


def test_reconciliation_pairs_a_row_by_the_bound_id_or_after_the_full_match() -> None:
    """28's INV-B1-m, B1.8 (h) and INV-B19-c say what 24 sections 8.3 rule 7 and 8.5 say (#3972)."""
    invariant = _words(_CATALOGUE.split("| **INV-B1-m** |", 1)[1].split("\n", 1)[0])
    note = _words(_CATALOGUE.split("(h) Reconciliation sends", 1)[1].split("(OM-R02)", 1)[0])
    rule = "`RECON_FOUND_*` to a row by the bound id, or after the full match: to a row bound to "
    rule += "an exchange `orderId` (24 §8.3 rule 7) by that id, comparing no terms again; to an "
    rule += "`unknown` or `quarantined` row with none bound only after its SR-E29-03 full match"
    assert [text for text in (invariant, note) if rule not in text] == []
    diffs = _words(_CATALOGUE.split("| **INV-B19-c** |", 1)[1].split("\n", 1)[0])
    assert not _missing(
        diffs,
        "Diffs are by the bound id, or after the full match: a row bound to an exchange "
        "`orderId` pairs by that id, and one with none bound only after the SR-E29-03 full match "
        "of the order found under its `orderLinkId`",
        "`Unknown` orders are resolved by lookup, never by blind resubmission.",
    )
    assert "Diffs are by `orderLinkId` (C-2.10);" not in _CATALOGUE
    assert "`RECON_FOUND_*` to `unknown` or `quarantined` only after" not in _CATALOGUE


def test_the_threat_model_routes_every_placement_through_its_permanent_anchor() -> None:
    """E29 model section 5.1 and SR-E29-07: R3's anchor for every `placeOrder`, reduce-only
    included, the one-leg group's ref its entry-only twin; `createTradeGroup` keeps its group's."""
    section = _words(_THREAT_MODEL.split("### 5.1 ", 1)[1].split("### 5.2 ", 1)[0])
    [requirement] = _model_rows("SR-E29-07")
    assert "(through its one-leg group)" not in section
    assert not _missing(
        section,
        "The permanent anchor of `createTradeGroup` is `client_group_ref`",
        "`POST /orders` (`placeOrder`) keeps the key in #913 ruling R3's request-level anchor "
        "(`21-database-schema.md` §3.3.10) for every placement, reduce-only included, of which an "
        "entry's one-leg group's `client_group_ref` is the entry-only twin",
        "Three duties move to the anchors (SR-E29-07):",
    )
    assert not _missing(
        _words(requirement),
        "for placement a permanent anchor: on `POST /orders` (`placeOrder`) #913 ruling R3's "
        "request-level anchor (`21-database-schema.md` §3.3.10) for every placement, reduce-only "
        "included, with an entry's one-leg group's `client_group_ref` as its entry-only twin",
        "and on `createTradeGroup` the group's `client_group_ref`, in which §8.3 rule 1 (#2841) "
        "stores the key",
    )
    assert "#### 3.3.10 `idempotency_anchors`" in _SCHEMA_DOC  # the section both cite
    log = _THREAT_MODEL.split("### Review log", 1)[1].splitlines()
    [revision] = [_words(row) for row in log if "| Revision 14, the #913 contract PR" in row]
    assert not _missing(
        revision,
        "§5.1 and SR-E29-07 route every `POST /orders` (`placeOrder`) through #913 ruling R3's "
        "request-level anchor",
        "OM-T05 and SR-E29-06 give a recorded stop's TP/SL order the `orders` row E29-T05 "
        "materialises",
        "no E29-X03 re-pin (ruling C(f))",
    )


def _kind_table() -> dict[str, tuple[str, str]]:
    """24 section 8.2's "Event kinds" table: trigger -> (kind, source)."""
    block = _INTERNAL_DOC.split("**Event kinds (E29-T03", 1)[1].split("**Recovery (E29-T03", 1)[0]
    rows = re.findall(r"^\| `([\w.]+)` +\| `(\w+)` +\| `(\w+)` +\|$", block, re.MULTILINE)
    return {trigger: (kind, source) for trigger, kind, source in rows}


def test_24_names_the_kind_of_every_step_b1_writes_as_the_step_writer_records_it() -> None:
    """CR-G6-R3-01 on #3972 (24 section 8.3 rule 7): section 8.2's "Event kinds" table names a
    kind and source for every trigger of a `lifecycle` step the chart declares, but the fills and
    the `place` results its text keeps apart, and the step writer records each one so.
    `MATERIALISED`, a recorded stop's first row, is the exchange fact of its TP/SL order, from the
    path that met it, and the diagram draws its one edge."""
    table, legality = _kind_table(), Legality.of(Registry().get("order"))
    triggers: set[str] = set().union(*legality.triggers.values())
    apart = {
        "EXEC",
        "done.invoke.place",
        *(f"error.platform.{i}" for i in ("place", "cancel", "amend")),
    }
    assert apart <= triggers and set(table) == triggers - apart
    for trigger, want in table.items():
        step = Step(None, None, None, "submitted", "submitted", trigger, {}, {})
        assert event_kind(step) == want, trigger
    assert table["MATERIALISED"] == ("exchange_push", "ws_private")
    found = Step(None, None, None, None, "submitted", "MATERIALISED", {"source": "reconcile"}, {})
    assert event_kind(found) == ("exchange_push", "reconcile")
    edges = {edge for edge, names in legality.triggers.items() if "MATERIALISED" in names}
    assert edges == {("draft", "submitted")}
    machine = _INTERNAL_DOC.split("### 8.2 Order state machine", 1)[1].split(
        "**Binding transition"
    )[0]
    assert not _missing(
        machine,
        "  Draft --> Submitted: a recorded stop's TP/SL order first seen, bound to its orderId, "
        "nothing sent (§8.3 rule 7)\n",
        "  note left of Submitted : a recorded stop's row is never killed: each live state audits "
        "its KILL and sends nothing\n",
    )
    assert (
        "`MATERIALISED`, a recorded stop's first row (§8.3 rule 7), is the exchange fact that its "
        "TP/SL order exists: `exchange_push` from `ws_private`, or from `reconcile` when "
        "reconciliation materialises it and its payload names that source; it is the one first "
        "row into `submitted`, so recovery tells it apart"
    ) in _between(_INTERNAL_DOC, "**Event kinds (E29-T03", "| Trigger")


def test_the_catalogue_records_the_recorded_stop_entry_and_the_unkeepable_ack() -> None:
    """28 B1, chart version 4: the entry's note with its snapshot migration, and B1.6's sentence
    of ruling 3 on #3972: an ok `place` answer whose id B1 cannot keep lands in `unknown`."""
    actions = _words(_CATALOGUE.split("### B1.6 Actions", 1)[1].split("| Action |", 1)[0])
    assert (
        "An ok `place` answer whose exchange order id B1 cannot keep (`text_id`) raises, so the "
        "order lands in `unknown`, never `submitted` (ruling 3 on #3972; E29-T04's first slice "
        "pins it in the binding)."
    ) in actions
    notes = _words(_CATALOGUE.split("### B1.8 Implementation notes", 1)[1].split("## B2 ", 1)[0])
    note = notes.split("chart `version: 4`.**", 1)[1]
    assert not _missing(
        note,
        "`MATERIALISED`, accepted only in `draft` as `VALIDATE` and `DISCOVERED` are, moves to "
        "`submitted` with `record_materialised`",
        "No service is invoked, so nothing is sent",
        "(d) `CANCEL` and `AMEND` carry no guard: synchronous code enforces 24 §8.8 rule 6 "
        "(C-2.21)",
        "The facade's `command` refuses an `AMEND` of the row too, before any send "
        "(`IllegalTransition`), as rule 6 refuses every one whatever the position; a `CANCEL` it "
        "leaves to the cancel service, which reads the position",
        "a snapshot sealed at version 3 (`6cdf8750e255…`) is refused on restore",
        "nothing outside the tests builds an `order` machine and no `Persister` or `Restorer` is "
        "wired for it yet (E50-T63), so no snapshot of it is written and no upcaster is "
        "registered; B1 recovers from `order_events`",
    )
    assert "no snapshot store exists yet" not in note  # the stores landed (E50-T61, E50-T62)


def test_place_order_names_the_bounds_the_validator_applies() -> None:
    """Slice 1's validator (#913; its round-4 Low): each figure outside the instrument's bounds is
    listed in `errors[]` with its field and, as its rule, the bound it breaks; slice 2b's
    take-profit (S2-Q6) among them."""
    assert not _missing(
        _words(_PLACE["description"]),
        "Price, trigger price, stop and take-profit are held to the instrument's `min_price` to "
        "`max_price`, and the quantity above zero and within its ceiling (`max_order_qty`, or "
        "`max_mkt_order_qty` for a market order)",
        "each figure outside is listed in `errors[]` with its `field` (`price`, `trigger.price`, "
        "`stop_loss`, `take_profit`, `qty`) and the bound it breaks as its `rule` (`min_price`, "
        "`max_price`, `min_order_qty`, `max_order_qty`, `max_mkt_order_qty`)",
        "answered `lot_size_violation` when the quantity is listed and `validation_failed` "
        "otherwise",
    )
    item = _SCHEMAS["Problem"]["properties"]["errors"]["items"]["properties"]
    assert {"field", "rule"} <= set(item)


def test_the_pipelines_own_rules_are_in_22_and_24() -> None:
    """Slice 2b (#913): #4006's follow-ups and the pipeline's rulings (Q-B, Q-D, S2-Q5, S2-Q6), as
    22 `placeOrder`, 22 Idempotency and 24 section 8.4 state them (C-6.1 inside the PR)."""
    assert not _missing(
        _words(_PLACE["description"]),
        "this request sends nothing and leaves its anchor undecided, and a `submitting` row whose "
        "commit was lost is resumed by a restart's hydration, under its persisted `orderLinkId`: "
        "looked up first, and sent again only within its re-send bound (24-internal-schemas.md "
        "section 8.3 rule 6)",
        "one in `atr` or `r_multiple` is `stop_unit_unsupported` on `take_profit`",
        "A reduce-only order carries no take-profit and no stop-loss: the exchange sets neither on "
        "one (`ExchangeCapabilities.supports_reduce_only_tpsl`",
        "is refused with `validation_failed` / `reduce_only_tpsl`, one `errors[]` item per side, "
        "before anything is recorded or sent",
        "`sizing.mode` `profile` sizes by the profile; another mode, except `pct_position`, "
        "overlays the request's values onto a copy of the profile, judged by `judge_leg` "
        "(24-internal-schemas.md section 9.3.2a) as a resulting leg and refused whole, never "
        "clamped, when it goes past the profile's caps (ADR-0040; #913 S4-S ruling Q2)",
        "`pct_position` on an order that is not reduce-only, is `validation_failed` / "
        "`sizing_mode_unsupported`; `pct_position` on a reduce-only one is refused the same way "
        "until the position read reaches the size step (an interim)",
        "an `atr` stop uses `fallback_sl_offset_pct`, recorded as `stop_fallback`",
        "until the E13 kernel port reaches `oms`",
        "a profile with no fallback fails closed",
        "A reduce-only order is not sized by the profile: its `fixed_qty` `qty` is floored to the "
        "lot step",
    )
    general = _words(_SPEC["info"]["description"]).split("### Idempotency", 1)[1]
    assert (
        "The 24 h record holds only a `2xx`: the `429` and `502` a `placeOrder` request answers "
        "once its order is recorded are replayed from the anchor"
    ) in general
    rules = _between(_INTERNAL_DOC, "**The pipeline's own rules", "**8.4.1 ")
    assert not _missing(
        rules,
        "is `503 exchange_unavailable` with `Retry-After`, nothing written or sent",
        "tried again twice, after 0.1 s and 0.25 s, then answered `409` with `Retry-After: 1`",
        "the startup kills every `validated` row before order entry opens",
        "total 17 s, under `CV_OMS_INFLIGHT_STUCK_S`",
        "carries its correlation id (`X-Correlation-Id`)",
        "A reduce-only order carries no take-profit and no stop-loss where the venue sets neither "
        "on one (`ExchangeCapabilities.supports_reduce_only_tpsl`, §14.1)",
        "this request sends nothing and leaves its anchor undecided",
        "A later repeat answers `202` with the order's reconciled state, `reconciling` while "
        "reconciliation has not resolved it",
    )
    steps = _between(_INTERNAL_DOC, "### 8.4 ", "\n3. Risk checks")
    sub_steps = (
        "**3a** the market read, mid and last kept apart, then the price band",
        "**3b** the reference price, `size_leg`'s anchor",
        "**3c** the size: `size_leg` for an order that is not reduce-only",
        "**3d** the effect (SR-E29-01), then `NativeStopGuard` over the sizer's own `ResolvedStop`",
    )
    at = [steps.index(sub_step) for sub_step in sub_steps]  # each present, 3a to 3d in order
    assert at == sorted(at)
    assert "The stop the order carries is the stop its `risk_usdt` was computed from" in steps


def test_the_rules_the_provenance_texts_cite_are_in_24() -> None:
    """The fold round's Low on pointers: 22's `OrderProvenance` and 21 section 3.3.4 cite 24
    section 8.3 rule 7 and section 8.8 rule 6, which G-6 (#3972) writes; a renumbering fails here
    rather than leaving them dangling."""
    pairing = _INTERNAL_DOC.split("### 8.3 Idempotency", 1)[1].split("### 8.4 ", 1)[0]
    assert re.search(r"^7\. \*\*Pairing through the bound id \(SR-E29-03\)\.\*\*", pairing, re.M)
    recorded = _INTERNAL_DOC.split("### 8.8 Safety invariant", 1)[1].split("### 8.9 ", 1)[0]
    assert re.search(r"^6\. \*\*The recorded stop \(SR-E29-06, `\[O-4\]`\)\.\*\*", recorded, re.M)
    provenance = _words(_SCHEMAS["OrderProvenance"]["description"])
    assert "(section 8.8 rule 6)" in provenance and "(section 8.3)" in provenance
    orders = _SCHEMA_DOC.split("#### 3.3.4 `orders`", 1)[1].split("#### 3.3.5 ", 1)[0]
    assert "(24 §8.8 rule 6)" in orders and "(24 §8.3 rule 7)" in orders


def test_the_threat_model_gives_a_recorded_stops_order_its_row() -> None:
    """Ruling C(d) on #3972 in the E29 model: a recorded stop's TP/SL order has no local row only
    until E29-T05 materialises its `recorded_stop` row, so each of its executions has an
    `order_id` (24 section 8.3 rule 7)."""
    [threat] = [_words(row) for row in _model_rows("OM-T05")]
    [requirement] = [_words(row) for row in _model_rows("SR-E29-06")]
    assert (
        "is a conditional order with its own `orderId` and no local row until one is materialised "
        "for it (24 §8.3 rule 7) `[O-4]`, so, unmatched, 24 §8.5 step 3c adopts it `untracked`"
    ) in threat
    assert (
        "An OMS-recorded stop is never `untracked`: its TP/SL order gets the `orders` row E29-T05 "
        "materialises, provenance `recorded_stop`, bound to its `orderId`, so each of its "
        "executions has an `order_id` (24 §8.3 rule 7)"
    ) in requirement
    assert "and no local row `[O-4]`" not in _THREAT_MODEL


def test_place_order_states_the_price_band_its_setting_and_rule() -> None:
    """#913 S4-S rulings Q3 and Q4: a limit entry's price, or a conditional entry's trigger, within
    `CV_OMS_PRICE_BAND_PCT` of mid, judged before sizing; no mid is the 503 a market order meets."""
    band = _between(_PLACE["description"], "* The price band", "* A reduce-only order carries")
    assert not _missing(
        band,
        "the `price` of a limit order that is not reduce-only must lie within "
        "`[ref \N{MULTIPLICATION SIGN} (1 \N{MINUS SIGN} b), "
        "ref \N{MULTIPLICATION SIGN} (1 + b)]`, `ref` the market's mid price, else its last "
        "price, and `b` the `CV_OMS_PRICE_BAND_PCT` setting (default `0.05`, from `0.005` to "
        "`0.20`, with no off value; `20-architecture.md` section 7.2)",
        "A per-profile value, when the profile carries one (the setting being the default), is "
        "allowed only inside `0.005` to `0.20`; a value outside is refused at save, never clamped",
        "A conditional entry, market or limit, has its `trigger.price` judged against `ref`, and "
        "the limit `price` behind a trigger is judged too, against its trigger price, with the "
        "same `b`",
        "is refused with `400 validation_failed`, `errors[]` `{field: price, rule: price_band}` "
        "(or `trigger.price`), "
        "before the order is sized",
        "A reduce-only order is never judged",
        "With neither a mid nor a last price to judge against the request is "
        "`503 exchange_unavailable` with `Retry-After`",
    )
    sizer = _INTERNAL_DOC.split("**9.3.5 ", 1)[1].split("**9.3.6 ", 1)[0]
    assert "the band's scope, rule and setting are defined in `22-api-openapi.yaml`" in sizer


def test_the_price_band_setting_has_a_row_in_20() -> None:
    """The band's setting sits in 20's configuration table, process-level, with its range."""
    section = _ARCH.split("### 7.2 Configuration model", 1)[1].split("### 7.3 ", 1)[0]
    cells = [[cell.strip() for cell in line.strip("|").split("|")] for line in section.split("\n")]
    rows = {row[0].strip("`"): row[1:] for row in cells if len(row) == 5 and row[0][:4] == "`CV_"}
    assert rows["CV_OMS_PRICE_BAND_PCT"][:3] == ["float", "`0.05`", "process"]
    assert "0.005-0.20, no off value (C-4.14)" in rows["CV_OMS_PRICE_BAND_PCT"][3]


def test_place_order_maps_each_sizer_outcome_to_one_answer() -> None:
    """24 section 9.3.4's closed skip and fail reasons, each one row of `placeOrder`'s mapping."""
    table = _PLACE["description"].split("| Sizer outcome | Answer |", 1)[1].split("\n\n", 1)[0]
    answers: dict[str, str] = {}
    for line in table.strip().splitlines()[1:]:
        outcomes, answer = (cell.strip() for cell in line.strip().strip("|").split("|"))
        for outcome in re.findall(r"`([a-z_]+)`", outcomes):
            answers[outcome] = answer.split(",", 1)[0].split(" with ", 1)[0].split(" on ", 1)[0]
    reasons = set(re.findall(r"`([a-z_]+)`", _between(_INTERNAL_DOC, "| `skip` |", "\n\n")))
    assert set(answers) == reasons - {"fail"}  # the kind's own cell is no reason
    assert set(answers) == {str(r) for r in SkipReason} | {str(r) for r in FailReason}
    assert answers == {
        "profile_disabled": "`403 risk_limit_breached`",
        "symbol_not_allowed": "`403 risk_limit_breached`",
        "symbol_denied": "`403 risk_limit_breached`",
        "cap_breached": "`403 risk_limit_breached`",
        "insufficient_margin": "`403 risk_limit_breached`",
        "below_min_notional": "`400 lot_size_violation`",
        "leverage_unavailable": "`400 validation_failed`",
        "invalid_stop_distance": "`400 validation_failed`",
        "stop_beyond_liquidation": "`400 validation_failed`",
        "no_reference_price": "`503 exchange_unavailable`",
        "figure_unknown": "`503 sizing_unavailable`",
    }
    for answer in set(answers.values()):
        status, code = answer.strip("`").split(" ")
        assert _CODES[code]["status"] == int(status)


def test_sizing_unavailable_is_a_retryable_503() -> None:
    """#913 S4-S ruling Q5: a figure with no source is its own 503, never a venue outage."""
    entry = _CODES["sizing_unavailable"]
    assert (entry["status"], entry["retryable"]) == (503, True)
    assert set(entry) == {"code", "status", "title", "retryable"}  # REST only, as its neighbours
    assert ERROR_META[ErrorCode("sizing_unavailable")].title == entry["title"]
    assert re.search(r"(?i)\bbybit\b|\d{4,}", entry["title"]) is None  # C-6.5
    assert "Retry-After" in _RESPONSES["ServiceUnavailable"]["headers"]
    assert _PLACE["responses"]["503"] == {"$ref": "#/components/responses/ServiceUnavailable"}
    assert "`figure_unknown` | `503 sizing_unavailable` with `Retry-After`" in _PLACE["description"]
    figures = _INTERNAL_DOC.split("**9.3.6 ", 1)[1].split("### 9.4 ", 1)[0]
    assert not _missing(
        _words(figures),
        'an announced interim, `DayRiskFigures` (`oms_interim_ports{port="risk_figures"}`',
        "It serves demo and testnet accounts only and refuses `live` at construction",
        "the cached committed-risk figure is dropped on every accepted send or amend on the "
        "account, so no two entries inside the cache window are sized against the same room, and "
        "two entries on one account whose size steps overlap are judged one after the other or "
        "with the first one's `risk_usdt` counted",
        "On a live process nothing serves `risk_figures`, so every figure is unknown and every "
        "live entry is `figure_unknown`, answered `503 sizing_unavailable`, until E39-T01",
        "Until E39-T01 (#881) serves real day figures",
        "the recorded stop or, without one, the profile's fallback distance (which errs high)",
        "`taker_fee_rate` is the venue's fee rate per (account, symbol), cached for seconds",
        "E39-T01 (#881) replaces the counters; the fee source stays",
        "answered `503 sizing_unavailable`",
    )
    row = _ARCH.split("| OMS | `oms_interim_ports{port}` |", 1)[1].split("\n", 1)[0]
    assert not _missing(
        _words(row),
        "`risk_figures`, the demo and testnet `DayRiskFigures`, which refuses `live` at "
        "construction",
        "`atr`, an `atr` stop's `fallback_sl_offset_pct` until the E13 kernel port reaches `oms`",
        "`stop_resolver`, `risk_gate`, `arm_records` and `sizer`, until S4-S-b2 retires it",
        "`risk_figures` at 1 on a live process means every live entry is refused "
        "`503 sizing_unavailable` (dashboard)",
    )
    assert "E39-S01 serves real day figures" not in _INTERNAL_DOC
    assert "Planned (wired by `oms.submit`'s size step) for a single order" in _ARCH
    assert "0.005-0.20, no off value (C-4.14)     |" in _ARCH
    pct = _SCHEMAS["SizingMode"]["description"]
    assert "`placeOrder` refuses it (`sizing_mode_unsupported`) until the position read" in pct
    assert 'oms_interim_ports{port="atr"}' in _words(_INTERNAL_DOC.split("**9.3.5 ", 1)[0])
