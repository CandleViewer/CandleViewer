"""Contract (#906, E28-T02 P-1a; E28 threat model section 10.2): a group definition has its own
paths, only the Owner writes one after a step-up (SR-E28-31, D8), and one with an ungranted member
reads as missing (SR-E28-21); a group has at most 20 legs, one per account (SR-E28-17); and the
preview takes the submit's permission (SR-E28-22). No route is mounted yet (C-6.1)."""

from __future__ import annotations

import re
import uuid
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
