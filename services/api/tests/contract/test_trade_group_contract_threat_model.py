"""Contract (#906, E28-T02 P-1a; E28 threat model section 10.2): a group definition has its own
paths, only the Owner writes one after a step-up (SR-E28-31, D8), and one with an ungranted member
reads as missing (SR-E28-21); a group has at most 20 legs, one per account (SR-E28-17); and the
preview takes the submit's permission (SR-E28-22). P-1b: a leg's values only narrow its bound
profile, and a request that would widen one is refused whole (SR-E28-03, SR-E28-04, D6); the
public request has no rule origin and refuses unknown members (SR-E28-05); and a group amend or
cancel keeps each open leg's stop (SR-E28-33). No route is mounted yet (C-6.1)."""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from candleviewer.api._generated import openapi_models as rest
from candleviewer.api.contract_conformance import load_openapi_spec
from tests.contract._admin_support import ROOT, capability_rows, grants
from tests.openapi_helpers import deref

_SPEC: Any = load_openapi_spec()  # a parsed YAML document, walked untyped
_SCHEMAS: dict[str, Any] = _SPEC["components"]["schemas"]
_ROUTES: dict[str, Any] = {
    f"{method.upper()} {path}": op
    for path, item in _SPEC["paths"].items()
    for method, op in item.items()
    if isinstance(op, dict) and "operationId" in op
}
_OPS: dict[str, Any] = {op["operationId"]: op for op in _ROUTES.values()}
_MATRIX = yaml.safe_load((Path(__file__).parent / "rbac/matrix.yaml").read_text(encoding="utf-8"))
_ADR = (ROOT / "docs/plan/27-adrs/ADR-0008-trade-group-fanout.md").read_text(encoding="utf-8")
_SCHEMA_DOC = (ROOT / "docs/plan/21-database-schema.md").read_text(encoding="utf-8")
_TABLES = _SCHEMA_DOC.split("#### 3.3.3a", 1)[1].split("#### 3.3.4", 1)[0]  # E28-T01's tables
_INTERNAL_DOC = (ROOT / "docs/plan/24-internal-schemas.md").read_text(encoding="utf-8")
_CODES: dict[str, Any] = {entry["code"]: entry for entry in _SPEC["x-error-codes"]}
_DEFINITIONS = {
    "GET /trade-group-definitions": "listTradeGroupDefinitions",
    "POST /trade-group-definitions": "createTradeGroupDefinition",
    "GET /trade-group-definitions/{definitionId}": "getTradeGroupDefinition",
    "PUT /trade-group-definitions/{definitionId}": "updateTradeGroupDefinition",
    "DELETE /trade-group-definitions/{definitionId}": "deleteTradeGroupDefinition",
}
_ACTORS = ("owner", "manager_with_grant", "manager_without_grant", "viewer")
_WRITES = {  # route -> (its responses, its x-idempotency)
    "POST /trade-group-definitions": ({"201", "400", "403", "409", "422", "503"}, "recommended"),
    "PUT /trade-group-definitions/{definitionId}": (
        {"200", "400", "403", "404", "409", "412", "422", "503"},
        "optional",
    ),
    "DELETE /trade-group-definitions/{definitionId}": ({"204", "403", "404", "503"}, "optional"),
}
_READS = ("GET /trade-group-definitions", "GET /trade-group-definitions/{definitionId}")


def _words(text: str) -> str:
    """A description on one line: a YAML block keeps its line breaks, a phrase may span two."""
    return " ".join(text.split())


def _ref(kind: str, name: str) -> dict[str, str]:
    return {"$ref": f"#/components/{kind}/{name}"}


def _walk(node: Any) -> Iterator[Any]:
    """`node` and every value below it (a YAML document, walked untyped)."""
    yield node
    if isinstance(node, dict):
        node = list(node.values())
    if isinstance(node, list):
        for child in node:
            yield from _walk(child)


def test_definitions_have_their_own_paths_and_post_trade_groups_stays_the_execution() -> None:
    """SR-E28-31: a definition places nothing and grants nothing."""
    found = {
        route: op["operationId"] for route, op in _ROUTES.items() if "group-definitions" in route
    }
    assert found == _DEFINITIONS
    assert _ROUTES["POST /trade-groups"]["operationId"] == "createTradeGroup"
    text = _words(_OPS["createTradeGroupDefinition"]["description"])
    assert "It places nothing: `POST /trade-groups` is the execution." in text
    assert "each leg's account is checked against the caller's grants at that use" in text


@pytest.mark.parametrize("route", _WRITES)
def test_only_the_owner_writes_a_definition_after_a_risk_caps_step_up(route: str) -> None:
    """D8 (open, Owner), SR-E28-02, PF-E02: a write is Owner-only after a `risk_caps` step-up,
    which the step-up sweep reads from this text once the route is mounted."""
    op = _ROUTES[route]
    responses, idempotency = _WRITES[route]
    assert op["x-rbac"] == {"permissions": ["accounts:write"], "scope": "granted_accounts"}
    assert (set(op["responses"]), op["x-idempotency"]) == (responses, idempotency)
    assert op["responses"]["403"] == _ref("responses", "Forbidden")
    outcomes = {actor: "allow" if actor == "owner" else "403" for actor in _ACTORS}
    assert _MATRIX["operations"][route]["outcomes"] == {**outcomes, "unauthenticated": "401"}
    text = _words(op["description"])
    assert all(word in text for word in ("Owner-only", "step-up", "`risk_caps`", "D8"))
    if route.startswith("POST "):  # a grace class (auth/step_up.py), so an elevation, not a code
        assert "a live step-up elevation of class `risk_caps`" in text
    assert _ref("parameters", "CsrfToken") in op["parameters"]
    roles = _SPEC["x-permissions"]
    assert "accounts:write" not in roles["manager"] + roles["viewer"]


@pytest.mark.parametrize("route", _READS)
def test_a_reader_sees_only_definitions_whose_every_member_is_granted(route: str) -> None:
    """SR-E28-21: a read takes `accounts:read`; an ungranted member hides the definition, from
    the list, its count and a read by id alike."""
    op = _ROUTES[route]
    assert op["x-rbac"] == {"permissions": ["accounts:read"], "scope": "granted_accounts"}
    assert op["responses"]["403"] == _ref("responses", "Forbidden")
    outcomes = dict.fromkeys(_ACTORS, "allow")
    assert _MATRIX["operations"][route]["outcomes"] == {**outcomes, "unauthenticated": "401"}
    by_id = "{definitionId}" in route
    param = _SPEC["components"]["parameters"]["TradeGroupDefinitionId"]["description"]
    text = _words(param if by_id else op["description"]).lower()
    assert re.search(r"(?:does|did) not exist \(sr-e28-21\)", text) and "soft-deleted" in text
    assert op["responses"].get("404") == (_ref("responses", "NotFound") if by_id else None)
    if not by_id:
        assert "`meta.total`, when present, counts only the definitions the caller may read" in (
            _words(op["description"])
        )


def test_a_definition_is_replaced_only_over_the_version_its_writer_read() -> None:
    """A PUT replaces the whole member set: `If-Match` keeps a stale session from putting back a
    member the Owner removed, and every answer carrying a definition carries its `ETag`."""
    update = _OPS["updateTradeGroupDefinition"]
    assert _ref("parameters", "IfMatch") in update["parameters"]
    assert update["responses"]["412"] == _ref("responses", "PreconditionFailed")
    assert "a stale session cannot put back a member the Owner removed" in _words(
        update["description"]
    )
    # A member-only PUT must change the ETag: 21's touch trigger fires on the definition's own
    # row only, so an `updated_at`-derived tag would miss it (E28-T05 derives it accordingly).
    get_text = _words(_OPS["getTradeGroupDefinition"]["description"])
    assert "`ETag` versions the definition, members included" in get_text
    for op, status in (("getTradeGroupDefinition", "200"), ("updateTradeGroupDefinition", "200")):
        assert _OPS[op]["responses"][status]["headers"]["ETag"] == _ref("headers", "ETag")
    created = _OPS["createTradeGroupDefinition"]["responses"]["201"]
    assert created["headers"]["ETag"] == _ref("headers", "ETag")


def test_the_capability_matrix_names_the_definition_rows() -> None:
    """04 section 7.2.2 (Security-owned): the reads scoped to granted members, the writes the
    Owner's alone and only after a step-up (D8)."""
    rows = capability_rows()
    _, cell, owner, manager, viewer = rows["20a"]
    assert grants(cell) == (
        {"accounts:read"},
        {"listTradeGroupDefinitions", "getTradeGroupDefinition"},
    )
    assert (owner, manager, viewer) == ("✔", "✔(every member granted)", "✔(every member granted)")
    for row, ops in (
        ("21a", {"createTradeGroupDefinition", "updateTradeGroupDefinition"}),
        ("21b", {"deleteTradeGroupDefinition"}),
    ):
        _, cell, owner, manager, viewer = rows[row]
        assert grants(cell) == ({"accounts:write"}, ops)
        assert (owner, manager, viewer) == ("✔(step-up)", "✖", "✖")


def test_a_definition_body_is_closed_stored_and_in_one_environment() -> None:
    """C-6.3 refuses unknown members; 21 section 3.3.3a's columns; SR-E28-16 refuses another
    environment in the API, and its triggers refuse it again in the database."""
    for name in ("TradeGroupDefinitionMember", "TradeGroupDefinitionInput", "TradeGroupDefinition"):
        assert _SCHEMAS[name]["additionalProperties"] is False
        assert getattr(rest, name).model_config.get("extra") == "forbid"
    body = _SCHEMAS["TradeGroupDefinitionInput"]["properties"]
    member = _SCHEMAS["TradeGroupDefinitionMember"]["properties"]
    stored = _SCHEMAS["TradeGroupDefinition"]["properties"]  # no `created_by` (SR-E28-21)
    assert set(body) == {"name", "environment", "members"}
    assert set(member) == {"exchange_account_id", "enabled"}
    assert set(stored) == {"id", "created_at", "updated_at", "definition"}
    assert _SCHEMAS["TradeGroupDefinitionInput"]["required"] == ["name", "environment", "members"]
    assert _SCHEMAS["TradeGroupDefinitionMember"]["required"] == ["exchange_account_id"]
    assert _SCHEMAS["TradeGroupDefinition"]["required"] == list(stored)
    assert body["environment"] == _ref("schemas", "Environment")  # explicit, never inferred
    assert (body["name"]["minLength"], body["name"]["maxLength"]) == (1, 80)
    assert "CONSTRAINT tgd_name CHECK (char_length(name) BETWEEN 1 AND 80)" in _TABLES
    assert member["enabled"]["default"] is True
    assert re.search(r"\benabled +boolean NOT NULL DEFAULT true,", _TABLES)
    assert (body["members"]["minItems"], body["members"]["maxItems"]) == (1, 20)
    create = _words(_OPS["createTradeGroupDefinition"]["description"])
    assert "`rule: environment_mismatch` per such member, and nothing is written" in create
    assert "refuse one, `403 account_scope_denied` (SR-E29-13)" in create
    assert "compared case-insensitively, is `409 conflict`" in create
    update = _words(_OPS["updateTradeGroupDefinition"]["description"])
    assert "`environment` is write-once (`trg_tgd_write_once`)" in update
    assert "`rule: write_once`" in update and "(`trg_tgdm_env` checks it again" in create
    for trigger in ("trg_tgdm_env BEFORE INSERT OR UPDATE", "trg_tgd_write_once BEFORE UPDATE"):
        assert f"CREATE TRIGGER {trigger}" in _TABLES


def test_a_group_has_at_most_twenty_legs_one_per_account() -> None:
    """SR-E28-17, PF-T17, AC-15: ADR-0008's Business-KYC ceiling bounds N; one leg per account."""
    legs = _SCHEMAS["CreateTradeGroupRequest"]["properties"]["legs"]
    assert (legs["minItems"], legs["maxItems"]) == (1, 20)
    accounts = [{"exchange_account_id": str(uuid.UUID(int=i + 1))} for i in range(21)]
    group = {"symbol": "BTCUSDT", "side": "buy", "order_type": "market", "legs": accounts}
    validator = Draft202012Validator(deref(_SPEC, _ref("schemas", "CreateTradeGroupRequest")))
    assert not validator.is_valid(group) and validator.is_valid({**group, "legs": accounts[:20]})
    rest.CreateTradeGroupRequest.model_validate({**group, "legs": accounts[:20]})
    with pytest.raises(ValidationError):
        rest.CreateTradeGroupRequest.model_validate(group)
    assert (
        "Two legs on one `exchange_account_id` refuse the whole request, on `previewTradeGroup` "
        "too, with `422 validation_failed` and `rule: duplicate_account`"
        in _words(legs["description"])
    )
    body = _OPS["previewTradeGroup"]["requestBody"]["content"]["application/json"]["schema"]
    assert body == _ref("schemas", "CreateTradeGroupRequest")
    assert _SCHEMAS["CreateTradeGroupRequest"]["properties"]["max_concurrent_legs"]["maximum"] == 20
    assert "Sub-account cap of 5 (20 with Business KYC) bounds N" in _ADR


def test_the_preview_takes_the_submits_permission_and_nothing_else() -> None:
    """SR-E28-22, PF-I03, AC-30: the preview is the submit's dry run (24 section 9.4 rule 1)."""
    preview = _OPS["previewTradeGroup"]
    assert preview["x-rbac"] == _OPS["createTradeGroup"]["x-rbac"]
    assert preview["x-rbac"]["permissions"] == ["orders:write"]
    assert "orders:write" not in _SPEC["x-permissions"]["viewer"]
    row = _MATRIX["operations"]["POST /trade-groups/preview"]
    assert (row["permissions"], row["outcomes"]["viewer"]) == (["orders:write"], "403")
    assert _ref("parameters", "ArmToken") not in preview["parameters"]
    assert _ref("parameters", "CsrfToken") in preview["parameters"]
    assert preview["responses"]["403"] == _ref("responses", "Forbidden")
    assert preview.get("x-idempotency") != "required"
    text = _words(preview["description"])
    assert "so a caller who cannot submit, a Viewer included, gets `403 forbidden`" in text
    _, cell, _, _, viewer = capability_rows()["19a"]
    assert (grants(cell), viewer) == (({"orders:write"}, {"previewTradeGroup"}), "✖")


def test_adr_0008_records_p1a() -> None:
    amendment = _ADR.split("\n## Amendment 2 (", 1)[1]
    for decision in (
        "E28-T02 #906; P-1a of the E28 threat model §10.2",
        "1. **A definition is not a trade group.**",
        "2. **At most 20 legs, one per account.**",
        "3. **The preview takes the submit's permission**, `orders:write`",
        "This breaks the `/v1` contract (C-6.3) before any route serves it",
        "so no single group reaches all of them; a larger bound needs SR-E28-17 amended first",
    ):
        assert decision in amendment


def test_no_contract_text_resolves_later_wins() -> None:
    """F-01: "later wins" let a ticket widen every leg past its account's profile."""
    texts = [node for node in _walk(_SPEC) if isinstance(node, str)]
    assert [text for text in texts if "later wins" in _words(text).lower()] == []


def test_a_leg_only_narrows_its_bound_profile_and_a_widening_request_is_refused_whole() -> None:
    """SR-E28-03, SR-E28-04, D6, D7, AC-04, AC-11; the Q4 ruling on P-1b: a widening is never
    clamped and never leaves a partial group, so the preview answers as the submit does."""
    create = _words(_OPS["createTradeGroup"]["description"])
    for phrase in (
        "**Resolution per leg: later narrows** (SR-E28-03, SR-E28-04; E28 threat model F-01)",
        "The leg's account's bound profile, its default profile (`is_default`), is the ceiling "
        "(E28 threat model D7)",
        "only narrow it, field by field, judged on the resulting leg after the sizer and its "
        "clamps run again",
        "may not exceed the bound profile's caps and risk budget",
        "the stop may not lie further from entry than the bound profile's own resolved stop for "
        "that leg",
        "never clamped and never a partial group (C-12.5, D6)",
        "It is audited, before any leg is sent, whatever `atomicity` says",
        "whatever `atomicity` says; it is never a per-leg failure",
        "A leg whose values the profile alone produced and that an account-state cap then "
        "rejects",
        "fails alone when it is sent",
        "a request value that breaks the comparator is refused whole",
        "an alternate profile never relaxes one",
        "The sizer's own policy clamp is no refusal; `sizing_explanation` names it",
        "decided at validation, after the account-scope check and before any leg is sized, with "
        "one title and `detail` shape",
    ):
        assert phrase in create, phrase
    preview = _words(_OPS["previewTradeGroup"]["description"])
    assert "never a leg returned with `would_submit: false`" in preview
    assert "cap the request does not move still marks that leg alone" in preview
    assert "(`intent_mismatch`, with any `native_stop_required` it lists)" in preview
    assert (
        "is `404 not_found`, decided at validation, after the account-scope check and before any "
        "leg is sized, as on the submit" in preview
    )
    for text in (create, preview):
        assert "refused whole" in text and "`403 risk_limit_breached`" in text
        assert "one `errors[]` entry per offending leg" in text
    assert _CODES["risk_limit_breached"]["status"] == 403
    for operation in ("createTradeGroup", "previewTradeGroup"):
        assert _OPS[operation]["responses"]["403"] == _ref("responses", "Forbidden")
    # "Answers as that submit would": the submit's whole-request 400s are declared on the dry run.
    assert _OPS["previewTradeGroup"]["responses"]["400"] == _ref("responses", "BadRequest")


@pytest.mark.parametrize("operation", ["createTradeGroup", "previewTradeGroup", "placeOrder"])
def test_a_profile_id_of_another_account_is_answered_as_a_missing_one(operation: str) -> None:
    """SR-E28-03, AC-11; the Q3 and Q5 rulings on P-1b: an alternate profile only narrows, and any
    other id is answered alike after the account-scope check, so the answer is no oracle."""
    assert _OPS[operation]["responses"]["404"] == _ref("responses", "NotFound")
    fields = _SCHEMAS["PlaceOrderRequest"]["properties"]
    if operation != "placeOrder":
        fields = _SCHEMAS["TradeGroupLegInput"]["properties"]["overrides"]["properties"]
    text = _words(fields["profile_id"]["description"])
    assert "only narrows" in text and "the same answer for each" in text
    assert "`404 not_found`, decided at validation, after the account-scope check" in text
    if operation == "placeOrder":  # SEC-4107-02: an alternate never relaxes a cap
        assert "every cap the guard reads and the allowed symbols stay the bound profile's" in text
        assert "the account's bound profile, its default profile (`is_default`, D7;" in text
        assert "active profile" not in text  # D-4107-01: `active_profile_id` is not the ceiling
    order = _words(_SPEC["info"]["description"])  # the owner of the order of the checks
    assert (
        "then validation (where a `profile_id` that is not one of the account's own profiles is "
        "`404 not_found`), sizing, risk" in order
    )


def test_a_widening_refusal_is_declared_on_the_submit_and_the_preview_with_its_leg_entries() -> (
    None
):
    """#2635 (F-01, ADR-0040 (proposed, #4461) Decision 1): the refused widening is the registered
    `403 risk_limit_breached`, declared on both operations through `Forbidden`, with one
    `errors[]` entry per offending leg naming the field, the requested value and the limit."""
    create = _words(_OPS["createTradeGroup"]["description"])
    assert "may not rise" not in create  # the ceiling is the bound profile's caps and budget
    assert "the requested value in `message`" in create
    registered = _CODES["risk_limit_breached"]
    assert registered["title"].endswith(
        "would be exceeded, by the account's state or by a submitted value"
    )
    forbidden = _SPEC["components"]["responses"]["Forbidden"]
    assert (
        "On `createTradeGroup`, `previewTradeGroup` and `amendTradeGroup` it may be "
        "`code: risk_limit_breached`" in _words(forbidden["description"])
    )
    example = forbidden["content"]["application/problem+json"]["examples"]["tradeGroupWidening"]
    value = example["value"]
    assert (value["code"], value["status"], value["title"]) == (
        "risk_limit_breached",
        403,
        registered["title"],
    )
    assert value["type"] == "https://candleviewer.local/errors/risk_limit_breached"
    (item,) = value["errors"]
    assert re.fullmatch(r"legs\[\d+\]\.overrides\.[a-z_]+", item["field"])
    assert set(item) == {"field", "rule", "limit", "message"}
    assert item["limit"] in item["message"] and "25" in item["message"]  # requested 25x
    problem = Draft202012Validator(deref(_SPEC, _SCHEMAS["Problem"]))
    assert list(problem.iter_errors(value)) == []
    for operation in ("createTradeGroup", "previewTradeGroup", "amendTradeGroup"):
        assert _OPS[operation]["responses"]["403"] == _ref("responses", "Forbidden")


def test_a_leg_s_first_native_stop_covers_its_full_quantity_at_admission() -> None:
    """#2635, ADR-0040 (proposed, #4461) rule 8 (C-2.6; PF-T20): the leg has no stop-size
    member, so under `Partial` the server sizes the first stop to the whole leg."""
    create = _words(_OPS["createTradeGroup"]["description"])
    for phrase in (
        "first native stop covers the leg's full quantity under either `tpsl_mode`",
        "under `Partial` the server sets that stop's size to the leg's full quantity",
        "only the owner's `sl_loosen` step-up on `setPositionTpSl` (`sl_size`) may make its cover "
        "smaller than the position it protects (24-internal-schemas.md section 8.8 rule 5)",
        "is a post-entry failure that starts the leg's unwind (E34-S03), never a refusal",
    ):
        assert phrase in create, phrase
    assert "makes it smaller" not in create  # reduce-only fills and closes shrink it too
    overrides = _SCHEMAS["TradeGroupLegInput"]["properties"]["overrides"]["properties"]
    assert not [name for name in overrides if "size" in name and name != "sizing"]


@pytest.mark.parametrize("operation", ["createTradeGroup", "previewTradeGroup", "placeOrder"])
def test_a_foreign_profile_id_is_never_a_forbidden_answer(operation: str) -> None:
    """#2635 (SR-E28-03): a missing, deleted or another account's profile is `404`, never `403`,
    so the status never tells which it is."""
    fields = _SCHEMAS["PlaceOrderRequest"]["properties"]
    if operation != "placeOrder":
        fields = _SCHEMAS["TradeGroupLegInput"]["properties"]["overrides"]["properties"]
    assert "never a `403`" in _words(fields["profile_id"]["description"])
    assert _OPS[operation]["responses"]["404"] == _ref("responses", "NotFound")


def test_the_preview_refuses_an_out_of_scope_leg_account_whole_as_the_submit_does() -> None:
    """SEC-4093-01 (SR-E28-21, SR-E29-13): an ungranted and a missing account answer alike on the
    dry run too, so it is no existence oracle; the two shared scope lists name it."""
    text = _words(_OPS["previewTradeGroup"]["description"])
    assert (
        "A `legs[].exchange_account_id` outside the caller's grants, or one that does not exist, "
        "refuses the whole request alike with `403 account_scope_denied` (SR-E28-21, SR-E29-13), "
        "so the answer never tells whether the account exists" in text
    )
    for name in ("Forbidden", "AccountScopeDenied"):
        assert "`previewTradeGroup`" in _SPEC["components"]["responses"][name]["description"]


def test_the_public_request_carries_no_rule_origin() -> None:
    """SR-E28-05, PF-S01, AC-14: a group's rule origin is set only on M15's internal path."""
    assert "rule_id" not in _SCHEMAS["CreateTradeGroupRequest"]["properties"]
    assert "rule_id" not in rest.CreateTradeGroupRequest.model_fields
    leg = {"exchange_account_id": str(uuid.UUID(int=1))}
    group = {"symbol": "BTCUSDT", "side": "buy", "order_type": "market", "legs": [leg]}
    rest.CreateTradeGroupRequest.model_validate(group)
    with pytest.raises(ValidationError, match="extra_forbidden"):  # answered 422
        rest.CreateTradeGroupRequest.model_validate({**group, "rule_id": str(uuid.UUID(int=2))})
    assert "rule_id" in _SCHEMAS["TradeGroup"]["properties"]  # the read side keeps it
    assert "rule_id" in rest.TradeGroup.model_fields
    text = _words(_OPS["createTradeGroup"]["description"])
    assert "(`TradeGroup.rule_id`) is set only on the rule engine's internal path (M15)" in text


@pytest.mark.parametrize("operation", ["createTradeGroup", "amendTradeGroup", "cancelTradeGroup"])
def test_every_object_in_a_group_request_refuses_unknown_members(operation: str) -> None:
    """SR-E28-05, PF-T06, AC-10, C-6.3 (fail closed): no snapshot, ATR or "already checked" flag
    gets in at any depth. The bracket's take-profit levels were the one open object."""
    body = _OPS[operation]["requestBody"]["content"]["application/json"]["schema"]
    objects = [
        node
        for node in _walk(deref(_SPEC, body))
        if isinstance(node, dict)
        and ("properties" in node or node.get("type") in ("object", ["object", "null"]))
    ]
    unclosed = [node for node in objects if node.get("additionalProperties") is not False]
    assert objects and unclosed == []


def test_the_bracket_take_profit_level_model_refuses_unknown_members() -> None:
    """The one open object the walk found on main: its generated model now refuses extras."""
    assert rest.TakeProfitLevel.model_config.get("extra") == "forbid"


def test_a_group_amend_never_clears_or_loosens_a_stop() -> None:
    """SR-E28-33, PF-T20, F-29, AC-32: an amend goes through admission again, and a refusal is
    the whole request's (Q4); `amendOrder`'s refusal of a cleared stop is the parity anchor."""
    text = _words(_OPS["amendTradeGroup"]["description"])
    for phrase in (
        "**An amend keeps the admission rules** (SR-E28-33; E28 threat model PF-T20, F-29)",
        "A refusal is the whole request's, as on `createTradeGroup`: nothing is amended, "
        "`errors[]` names every offending leg",
        "each targeted leg goes through the resolver, the sizer and the guard again",
        "`errors[]` names every offending leg, and the refusal is audited with a result per leg",
        "on a leg whose order is an entry (classified by its effect, never by its `intent`: "
        "SR-E29-01)",
        "no request clears the stop of an open position",
        "is refused as `amendOrder` refuses a cleared stop: `400 validation_failed` / "
        "`native_stop_required` (C-2.6)",
        "An entry leg's stop-loss, attached or under `tpsl_mode: Partial` a separate order, can "
        "move but is never removed",
        "A stop moved to loosen is refused with `403 risk_limit_breached`: compared with the stop "
        "it replaces, a long leg's stop may only rise and a short leg's only fall",
        "above the bound profile's caps and risk budget is refused with "
        "`403 risk_limit_breached`, never clamped (C-12.5, D6)",
        "A reduction or a tightening is never refused by these checks",
        "a stop moved the ratchet's way (a long leg's up, a short leg's down), passes",
        "When one request holds both a `400` and a `403` offender, the `400` answers",
        "On an amend an account-state cap refuses the whole request too",
    ):
        assert phrase in text, phrase
    assert "toward the market" not in text  # a pending conditional entry's stop (RC-4107-02)


def test_a_group_amend_declares_its_refusals_and_keeps_its_bounds() -> None:
    """The statuses the text names, and the body's shape: `stop_loss: null` stays in the shape,
    and the request's own text refuses it on an entry leg and on any leg whose position is open."""
    amend = _OPS["amendTradeGroup"]
    assert amend["responses"]["400"] == _ref("responses", "BadRequest")
    group_id = _words(_SPEC["components"]["parameters"]["TradeGroupId"]["description"])
    assert "or is a risk refusal (`risk_limit_breached`); it is never a scope answer" in group_id
    assert amend["responses"]["403"] == _ref("responses", "Forbidden")
    anchor = _words(_OPS["amendOrder"]["description"])
    assert "which returns `validation_failed` / `native_stop_required`" in anchor
    body = _SCHEMAS["AmendTradeGroupRequest"]["properties"]
    # `null` stays in the shape; the request's text refuses it (RC-4107-03).
    cleared = {"oneOf": [_ref("schemas", "Offset"), {"type": "null"}]}
    request = _words(_SCHEMAS["AmendTradeGroupRequest"]["description"])
    assert "refused on an entry leg, or on any leg whose position is open" in request
    assert body["stop_loss"] == body["legs"]["items"]["properties"]["stop_loss"] == cleared
    assert body["legs"]["maxItems"] == 20


def test_a_group_cancel_keeps_each_open_legs_stop() -> None:
    """SR-E28-33, PF-T20, AC-32: a plain cancel keeps an open leg's exits; a flatten, and
    E34-S03's unwind, removes the stop only once the leg is flat (24 section 9.5.1)."""
    cancel = _OPS["cancelTradeGroup"]
    text = _words(cancel["description"])
    for phrase in (
        "its stop-loss, attached or under `tpsl_mode: Partial` a separate order, is never "
        "cancelled (C-2.6; SR-E28-33, E28 threat model PF-T20)",
        "and its take-profits stay as well, as `cancelAllOrders` keeps reduce-only exits by "
        "default",
        "in the order of 24-internal-schemas.md section 9.5.1",
        "its stop-loss goes only once the leg is verified flat",
        "E34-S03's unwind never cancels the stop before the leg is flat (section 9.5.1)",
        "names each stop kept, or gone with its flat position",
    ):
        assert phrase in text, phrase


def test_a_group_cancel_bounds_its_legs_and_unwinds_in_section_9_5_1s_order() -> None:
    """The body's shape and the 24 unwind order the text cites: no step cancels the stop."""
    cancel = _OPS["cancelTradeGroup"]
    assert cancel["responses"]["422"] == _ref("responses", "UnprocessableEntity")
    body = cancel["requestBody"]["content"]["application/json"]["schema"]["properties"]
    assert (body["legs"]["maxItems"], body["flatten_filled"]["default"]) == (20, False)
    assert _SCHEMAS["CancelAllRequest"]["properties"]["exclude_reduce_only"]["default"] is True
    unwind = _words(_INTERNAL_DOC.split("#### 9.5.1 ", 1)[1].split("**Idempotency and restart.")[0])
    assert "strictly ordered `cancel_children → close_position → verify_flat → verify_sl`" in unwind
    children = "cancel_children: cancel-all for (uid, symbol) filtered to this leg's children (TP "
    assert children + "ladder, algo children, working entries remnant)." in unwind  # no stop


def test_a_leg_names_the_profile_it_was_sized_from() -> None:
    """24 section 9.1: `account_profile_id` is null only once its profile row is gone; no ticket
    overrides the profile entirely (`trg_tgl_profile` refuses such a leg at insert)."""
    field = _SCHEMAS["TradeGroupLeg"]["properties"]["account_profile_id"]["description"]
    text = _words(field)
    assert "overrode the profile entirely" not in text
    assert "Null only once that profile row is gone; the leg's snapshot keeps the id." in text
    comment = r"account_profile_id: UUID \| None +# None only once its profile row is gone"
    assert re.search(comment, _INTERNAL_DOC)
    assert "CREATE TRIGGER trg_tgl_profile BEFORE INSERT ON trade_group_legs" in _SCHEMA_DOC
    accepted = _OPS["createTradeGroup"]["responses"]["202"]["content"]["application/json"]
    legs = accepted["examples"]["accepted"]["value"]["legs"]
    assert all("account_profile_id" in leg and "profile_id" not in leg for leg in legs)


def test_adr_0008_records_p1b() -> None:
    amendment = _words(_ADR.split("\n## Amendment 3 (", 1)[1])
    for decision in (
        "E28-T02 #906; P-1b of the E28 threat model §10.2",
        "1. **Each account's bound profile is the ceiling: later narrows.**",
        "is refused whole with `risk_limit_breached`, never clamped and never a partial group",
        "2. **A rule origin is internal.**",
        "3. **Rule 2 holds after admission.**",
        "nor the stop of any leg whose position is open",
        "unless it flattens the leg first; that unwind removes the stop only once the leg is flat",
        "and keeps its take-profits too, as `cancelAllOrders` keeps reduce-only exits by default",
        "Amend and cancel name at most 20 legs, as a group holds",
        "a reduction or a tightening is never refused",
        "still rejects only its leg",
        "on a submit, an account-state cap the request does not move",
        "issuecomment-6335477829",
        "This breaks the `/v1` contract (C-6.3) before any route serves it",
    ):
        assert decision in amendment, decision
