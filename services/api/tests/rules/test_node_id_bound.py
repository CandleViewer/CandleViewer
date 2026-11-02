"""E35-T11 (the orchestrator's carry 1): the IR bounds every node's `node_id` to a short identifier,
`^[A-Za-z0-9_-]{1,64}$`, the form the OMS's rule origin carries (`oms.ports.RuleOrigin`), so no
saved rule names a node an order cannot carry (24 §11.2). A save that names another is refused
through the manager's schema refusal, `422 rule_ir_invalid` at the node's path, nothing stored;
the published JSON schema and the contract's node schemas (22 `RuleIr`, mirrored by the generated
models) carry the same pattern."""

from __future__ import annotations

import copy
import json
from typing import Any

import jsonschema
import pytest

from candleviewer.api._generated import openapi_models as contract
from candleviewer.rules.ir import Rule, to_json_schema
from candleviewer.rules.ir.models import NODE_ID_PATTERN
from candleviewer.rules.manager import InMemoryRuleStore, RuleError, RulesManager
from candleviewer.rules.vocabulary import default_registry
from tests.rules.executor.engine_rig import ACTOR, FIXTURE

#: Outside the bound: a dot, a space, 65 characters, none, a character outside ASCII.
OUTSIDE = ("a.1", "a 1", "n" * 65, "", "nœud")
OUTSIDE_IDS = ("dot", "space", "too-long", "empty", "non-ascii")
#: Inside it: one character, 64, and each kind it admits.
INSIDE = ("a", "n" * 64, "A-z_0-9")


def _doc(where: str, node: str) -> dict[str, Any]:
    """The rig's rule, saveable (a journal tag as its action), naming `node` at `where`."""
    raw: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    doc = copy.deepcopy(raw)
    doc["actions"] = [{"node_id": "a1", "type": "log_journal_tag", "params": {"tag": "t"}}]
    (doc["actions"][0] if where == "action" else doc["conditions"])["node_id"] = node
    return doc


@pytest.mark.parametrize("where", ["action", "condition"])
@pytest.mark.parametrize("node", OUTSIDE, ids=OUTSIDE_IDS)
async def test_saving_a_rule_whose_node_id_is_not_a_short_identifier_is_422_at_its_path(
    where: str, node: str
) -> None:
    store = InMemoryRuleStore()
    manager = RulesManager(store, default_registry())
    with pytest.raises(RuleError) as refused:
        await manager.create(_doc(where, node), ACTOR)
    path = "/actions/0/node_id" if where == "action" else "/conditions/comparison/node_id"
    assert (refused.value.status, refused.value.code) == (422, "rule_ir_invalid")
    assert refused.value.extra["path"] == path
    assert node == "" or node not in refused.value.message
    assert await store.all() == []


@pytest.mark.parametrize("node", INSIDE)
async def test_a_short_identifier_is_saved(node: str) -> None:
    manager = RulesManager(InMemoryRuleStore(), default_registry())
    created = await manager.create(_doc("action", node), ACTOR)
    assert created["id"]


@pytest.mark.parametrize("node", OUTSIDE, ids=OUTSIDE_IDS)
def test_the_published_schema_refuses_what_the_model_refuses(node: str) -> None:
    doc = _doc("action", node)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, to_json_schema())
    with pytest.raises(ValueError):
        Rule.model_validate(doc)


@pytest.mark.parametrize(
    "schema",
    [
        contract.RuleArithmeticNode, contract.RuleComparisonNode, contract.RuleBooleanNode,
        contract.RuleTemporalNode, contract.RuleAction,
    ],
    ids=lambda model: model.__name__,
)  # fmt: skip
def test_the_contracts_rule_nodes_carry_the_ir_node_id_pattern(schema: Any) -> None:
    """22's five node schemas, as their generated models mirror them, bound `node_id` as the IR
    does, so the contract and the model refuse the same ids."""
    published = schema.model_json_schema()
    node = published["$defs"][schema.__name__] if "$ref" in published else published  # recursive
    assert node["properties"]["node_id"]["pattern"] == NODE_ID_PATTERN
