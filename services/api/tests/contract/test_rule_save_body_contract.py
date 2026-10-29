"""#4835 (E36-X01 G-12): no account outside `ir`, and closed `/rules` save bodies.

22 sends a rule's accounts in `ir.scope.account_ids` (`RuleIrScope`, required), none outside `ir`;
both save bodies are closed, a refused member is named with one of two reasons, and the IR's scope
mirrors the server's `RuleScope`. Read from the spec, never a copy (AGENTS.md section 6 rule 12).
"""

from __future__ import annotations

from typing import Any, get_args

import pytest
from pydantic_core import PydanticUndefined

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.domain.primitives import Environment
from candleviewer.rules.ir.accounts import collect_account_ids, is_account_key
from candleviewer.rules.ir.models import Rule, RuleScope
from tests.contract._admin_support import validate_example
from tests.contract._rule_save_support import A, B, owner_client, rule_ir, save_body

_SPEC: Any = load_openapi_spec()
_SCHEMAS: Any = _SPEC["components"]["schemas"]
_BODIES = {("/rules", "post"): "RuleInput", ("/rules/{ruleId}", "put"): "RuleUpdateInput"}
_CREATE: Any = _SPEC["paths"]["/rules"]["post"]
_EXAMPLES: Any = _CREATE["requestBody"]["content"]["application/json"]["examples"]
_REFUSED: Any = _SPEC["components"]["responses"]["RuleIrInvalid"]["content"]
#: The two `errors[].rule` reasons 22 names for a refused save-body member (`RuleInput`).
REASONS = ("accounts_outside_scope", "unknown_field")


def _schema(node: Any) -> Any:
    """`node` with its `$ref` followed (the contract's refs are all local)."""
    while "$ref" in node:
        node = _SCHEMAS[node["$ref"].rsplit("/", 1)[1]]
    return node


def _account_members(node: Any, at: str, seen: frozenset[str] = frozenset()) -> list[str]:
    """Every member path under `node` that names an account, through `$ref` and each composition."""
    ref = node.get("$ref") if isinstance(node, dict) else None
    if not isinstance(node, dict) or ref in seen:
        return []  # `additionalProperties: true`, or a schema this path already walks
    seen, node = (seen | {ref} if ref else seen), _schema(node)
    found: list[str] = []
    for name, member in node.get("properties", {}).items():
        found += [f"{at}{name}"] if is_account_key(name) else []
        found += _account_members(member, f"{at}{name}.", seen)
    subs = [node.get("items"), node.get("additionalProperties")]
    subs += [sub for key in ("allOf", "oneOf", "anyOf") for sub in node.get(key, [])]
    return found + [path for sub in subs for path in _account_members(sub, at, seen)]


@pytest.mark.parametrize("via", ["items", "additionalProperties", "allOf", "oneOf", "anyOf"])
def test_the_account_walk_reaches_a_member_through_each_composition(via: str) -> None:
    held = {"type": "object", "properties": {"accountId": {"type": "string"}}}
    node = {via: held if via in ("items", "additionalProperties") else [held]}
    assert _account_members({"properties": {"m": node}}, "") == ["m.accountId"]


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


def test_the_ir_scope_is_required_and_mirrors_the_server_model() -> None:
    """`RuleIr` requires `scope`, as the server's IR does, and `RuleIrScope` is the server's
    `RuleScope`: the same members, the same required ones, and every default, enum and item."""
    ir, scope = _SCHEMAS["RuleIr"], _SCHEMAS["RuleIrScope"]
    props, fields = scope["properties"], RuleScope.model_fields
    assert ir["properties"]["scope"] == {"$ref": "#/components/schemas/RuleIrScope"}
    assert "scope" in ir["required"] and Rule.model_fields["scope"].is_required()
    assert scope["additionalProperties"] is False and set(props) == set(fields)
    assert scope["required"] == [name for name, f in fields.items() if f.is_required()]
    for name, f in fields.items():
        default = list(f.default) if isinstance(f.default, tuple) else f.default
        assert props[name].get("default", PydanticUndefined) == default, name
    assert _schema(props["level"])["enum"] == list(get_args(fields["level"].annotation))
    assert props["applies_to"]["enum"] == list(get_args(fields["applies_to"].annotation))
    assert _schema(props["environments"]["items"])["enum"] == list(get_args(Environment))
    assert props["account_ids"]["items"] == {"type": "string", "format": "uuid"}
    assert props["symbols"]["items"] == {"$ref": "#/components/schemas/Symbol"}


@pytest.mark.parametrize("name", list(_EXAMPLES))
def test_the_create_examples_are_valid_and_carry_accounts_only_in_ir_scope(name: str) -> None:
    example = _EXAMPLES[name]["value"]
    validate_example("/components/schemas/RuleInput", example)
    scope = example["ir"]["scope"]
    rest = {**example, "ir": {k: v for k, v in example["ir"].items() if k != "scope"}}
    assert collect_account_ids(rest) == ()
    assert collect_account_ids(scope) == tuple(scope.get("account_ids", ()))


def test_a_refused_member_is_named_with_one_of_the_two_reasons_22_names() -> None:
    """`RuleInput` and `createRule` name both reasons, and the example names the member and its
    reason only: a fixed `message`, and a `detail` that counts (C-12.6)."""
    for described in (_SCHEMAS["RuleInput"]["description"], _CREATE["description"]):
        assert all(f"`{reason}`" in described for reason in REASONS)
    example = _REFUSED["application/problem+json"]["examples"]["memberOutsideIr"]["value"]
    validate_example("/components/schemas/Problem", example)
    assert [(e["field"], e["rule"]) for e in example["errors"]] == [("bindings", REASONS[0])]
    assert example["detail"].split()[0] == str(len(example["errors"]))
    assert "bindings" not in example["detail"] + example["errors"][0]["message"]


def test_a_saved_version_echoes_exactly_the_accounts_its_save_sent() -> None:
    """Each body holds every member its schema requires and is validated before it is sent."""
    client = owner_client()

    def stored(rid: str) -> list[str]:
        items = client.get(f"/rules/{rid}/versions").json()["items"]
        newest = max(items, key=lambda v: v["version"])["id"]
        version = client.get(f"/rules/{rid}/versions/{newest}").json()
        return list(version["ir"]["scope"]["account_ids"])

    sent = [str(B), str(A)]
    body = save_body("RuleInput", "echo", rule_ir(level="account", account_ids=sent))
    created = client.post("/rules", json=body)
    assert created.status_code == 201, created.text
    rid = created.json()["id"]
    assert stored(rid) == sent
    edited = save_body(
        "RuleUpdateInput", "echo", rule_ir("2", level="account", account_ids=[str(A)])
    )
    saved = client.put(f"/rules/{rid}", json=edited, headers={"If-Match": "1"})
    assert saved.status_code == 200, saved.text
    assert stored(rid) == [str(A)]
