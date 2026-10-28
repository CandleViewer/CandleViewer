"""#4835 (E36-X01 G-12): one place for a rule's accounts, and closed `/rules` save bodies.

22 names `ir.scope.account_ids` (`RuleIrScope`) as the only place a save carries a rule's
accounts: `createRule` takes `RuleInput` and `updateRule` takes `RuleUpdateInput`, both closed, and
no member outside `ir` names an account. The IR's scope mirrors the server's own model
(`rules.ir.models.RuleScope`), and a saved version echoes the accounts its save sent. Read from
the spec, never from a copy (AGENTS.md section 6 rule 12).
"""

from __future__ import annotations

from typing import Any, get_args

import pytest

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.domain.primitives import Environment
from candleviewer.rules.ir.accounts import collect_account_ids, is_account_key
from candleviewer.rules.ir.models import RuleScope
from tests.contract._admin_support import validate_example
from tests.rules.test_rules_routes import _Env, _ir
from tests.rules.test_scope import A, B

_SPEC: Any = load_openapi_spec()
_SCHEMAS: Any = _SPEC["components"]["schemas"]
_BODIES = {("/rules", "post"): "RuleInput", ("/rules/{ruleId}", "put"): "RuleUpdateInput"}


def _schema(node: Any) -> Any:
    """`node` with its `$ref` followed (the contract's refs are all local)."""
    while "$ref" in node:
        node = _SCHEMAS[node["$ref"].rsplit("/", 1)[1]]
    return node


def _account_members(node: Any, at: str) -> list[str]:
    """Every member path under `node` whose name is an account reference, at any depth."""
    node, found = _schema(node), []
    for name, member in node.get("properties", {}).items():
        if is_account_key(name):
            found.append(f"{at}{name}")
        found += _account_members(member, f"{at}{name}.")
    return found + (_account_members(node["items"], at) if "items" in node else [])


@pytest.mark.parametrize(("path", "method"), list(_BODIES))
def test_each_save_body_is_closed_and_names_no_account_outside_ir(path: str, method: str) -> None:
    ref = _SPEC["paths"][path][method]["requestBody"]["content"]["application/json"]["schema"]
    body = _schema(ref)
    assert ref == {"$ref": f"#/components/schemas/{_BODIES[(path, method)]}"}
    assert body["additionalProperties"] is False and "bindings" not in body["properties"]
    outside = {k: v for k, v in body["properties"].items() if k != "ir"}
    assert _account_members({"properties": outside}, "") == []
    assert body["properties"]["ir"] == {"$ref": "#/components/schemas/RuleIr"}


def test_the_update_body_is_the_create_body_and_expected_version() -> None:
    create, update = _SCHEMAS["RuleInput"], _SCHEMAS["RuleUpdateInput"]
    shared = {k: v for k, v in update["properties"].items() if k != "expected_version"}
    assert shared == create["properties"] and update["required"] == create["required"]
    assert update["additionalProperties"] is False
    expected = update["properties"]["expected_version"]
    assert expected["type"] == "integer" and expected["minimum"] == 1


def test_the_ir_scope_is_the_one_place_for_accounts_and_mirrors_the_server_model() -> None:
    scope = _SCHEMAS["RuleIrScope"]
    props = scope["properties"]
    assert _SCHEMAS["RuleIr"]["properties"]["scope"] == {"$ref": "#/components/schemas/RuleIrScope"}
    assert scope["additionalProperties"] is False and scope["required"] == ["level"]
    assert set(props) == set(RuleScope.model_fields)
    fields = RuleScope.model_fields
    assert _schema(props["level"])["enum"] == list(get_args(fields["level"].annotation))
    assert props["applies_to"]["enum"] == list(get_args(fields["applies_to"].annotation))
    assert _schema(props["environments"]["items"])["enum"] == list(get_args(Environment))
    assert props["environments"]["default"] == list(fields["environments"].default)
    assert props["account_ids"]["items"] == {"type": "string", "format": "uuid"}


@pytest.mark.parametrize("name", ["breakEvenForm", "tapeSpikeGraph"])
def test_the_create_examples_are_valid_and_carry_accounts_only_in_ir_scope(name: str) -> None:
    body = _SPEC["paths"]["/rules"]["post"]["requestBody"]["content"]["application/json"]
    example = body["examples"][name]["value"]
    validate_example("/components/schemas/RuleInput", example)
    scope = example["ir"]["scope"]
    rest = {**example, "ir": {k: v for k, v in example["ir"].items() if k != "scope"}}
    assert collect_account_ids(rest) == ()
    assert collect_account_ids(scope) == tuple(scope.get("account_ids", ()))


def test_a_saved_version_echoes_exactly_the_accounts_its_save_sent() -> None:
    e = _Env()

    def stored(rid: str) -> list[str]:
        latest = e.c.get(f"/rules/{rid}/versions").json()["items"][0]["id"]
        version = e.c.get(f"/rules/{rid}/versions/{latest}").json()
        return list(version["ir"]["scope"]["account_ids"])

    sent = [str(B), str(A)]
    rid = e.create(scope={"level": "account", "account_ids": sent})
    assert stored(rid) == sent
    edited = _ir("2", scope={"level": "account", "account_ids": [str(A)]})
    saved = e.c.put(f"/rules/{rid}", json={"ir": edited}, headers={"If-Match": "1"})
    assert saved.status_code == 200
    assert stored(rid) == [str(A)]
