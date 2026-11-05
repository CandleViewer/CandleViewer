"""#5913, #5914 (E35): `getRule` and `updateRule` answer the `RuleDetail` 22 declares.

A read answers the rule with its active IR, its `version` and its `graph_layout`; a save answers
the same detail of the rule it saved, at the version it wrote. Each answer is validated against the
route's own 200 schema in 22 through the shared helper (2020-12, format checker), never a copy.
"""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.rules.ir.models import Rule
from candleviewer.rules.manager import Actor, InMemoryRuleStore, RulesManager
from candleviewer.rules.vocabulary import default_registry
from tests.contract._admin_support import validate_example
from tests.contract._rule_save_support import owner_client, rule_ir, save_body

_SPEC: Any = load_openapi_spec()
#: The members of 22's `RuleIr`: what a detail's `ir` may hold.
RULE_IR = frozenset(_SPEC["components"]["schemas"]["RuleIr"]["properties"])
#: The rule IR corpus (`tests/fixtures/rule_ir`): every trigger, node and operand form, by name.
_CORPUS = {
    path.stem: json.loads(path.read_text(encoding="utf-8"), parse_float=str)
    for path in sorted((Path(__file__).parents[1] / "fixtures/rule_ir").glob("*.json"))
}
OWNER = Actor(str(uuid.UUID(int=1)), "s1", frozenset({"rules:read", "rules:write"}), is_owner=True)


def _answer(method: str) -> str:
    """The pointer of the 200 JSON schema 22 declares for `method /rules/{ruleId}`."""
    return f"/paths/~1rules~1{{ruleId}}/{method}/responses/200/content/application~1json/schema"


def _rebuilt(stored: dict[str, Any], ir: dict[str, Any]) -> dict[str, Any]:
    """What the server's model reads from an answered `ir` and the stored version's members
    outside `RuleIr`: what it reads from the stored version when the answer drops nothing."""
    envelope = {k: v for k, v in stored.items() if k not in RULE_IR}
    return Rule.model_validate({**envelope, **ir}).model_dump(mode="json")


def test_get_rule_answers_the_rule_detail_22_declares() -> None:
    """#5914: the read names the members the rule's detail declares, `ir`, `version` and
    `graph_layout` among them, each as 22's `getRule` 200 schema types it."""
    client = owner_client()
    made = client.post("/rules", json=save_body("RuleInput", "read", rule_ir(level="global")))
    assert made.status_code == 201, made.text
    got = client.get(f"/rules/{made.json()['id']}")
    assert got.status_code == 200, got.text
    assert {"ir", "version", "graph_layout"} <= set(got.json())
    validate_example(_answer("get"), got.json())


def test_update_rule_answers_the_rule_detail_of_the_version_it_wrote() -> None:
    """#5913: the save answers 22's `updateRule` 200 schema, the detail of the rule it saved, at
    the version it wrote: the next save's `If-Match`, never the version the client edited."""
    client = owner_client()
    made = client.post("/rules", json=save_body("RuleInput", "save", rule_ir(level="global")))
    assert made.status_code == 201, made.text
    rid = made.json()["id"]
    body = save_body("RuleUpdateInput", "save", rule_ir("2", level="global"))
    saved = client.put(f"/rules/{rid}", json=body, headers={"If-Match": '"1"'})
    assert saved.status_code == 200, saved.text
    validate_example(_answer("put"), saved.json())
    assert (saved.json()["id"], saved.json()["version"]) == (rid, 2)


@pytest.mark.parametrize("shape", list(_CORPUS))
async def test_every_stored_ir_shape_reads_as_22s_rule_ir_and_loses_nothing(shape: str) -> None:
    """A stored version of each shape the IR corpus holds (each trigger, node and operand form),
    as its writer wrote it, reads back as 22's `RuleDetail`, its `ir` as `RuleIr` holds it, from
    which the server's own model reads exactly what it reads from the stored version."""
    m = RulesManager(InMemoryRuleStore(), default_registry())
    rid = (await m.create({**rule_ir(level="global"), "name": "shape"}, OWNER))["id"]
    stored = copy.deepcopy(_CORPUS[shape])
    row = await m._s.get(rid)
    assert row is not None
    row.versions[0].ir = stored  # the store holds the shape as its writer wrote it
    detail = await m.get(rid, OWNER)
    validate_example(_answer("get"), detail)
    assert _rebuilt(stored, detail["ir"]) == Rule.model_validate(stored).model_dump(mode="json")
