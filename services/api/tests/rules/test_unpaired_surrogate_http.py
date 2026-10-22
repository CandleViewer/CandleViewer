"""A lone surrogate in rule IR text over HTTP (#4172): compile, save and update answer
``422 rule_ir_invalid`` naming the field, never a 500, and nothing is stored.

Bodies go as raw JSON text holding the escape (``"\\ud800"``), as a client sends one: ``json``
decodes it into a ``str`` with no UTF-8 form, which the IR's unconstrained text accepts. Compile's
``errors[].field`` skips a step that is not an identifier, so a refused key is named by the object
that holds it; save's ``path`` names the key with the code point escaped.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from httpx import Response

from candleviewer.api.rules import make_rules_router
from candleviewer.api.rules_crud import make_rules_crud_router
from candleviewer.rules.compiler import to_graph_model
from candleviewer.rules.ir import Rule
from candleviewer.rules.manager import Actor, InMemoryRuleStore, RulesManager
from candleviewer.rules.vocabulary import default_registry

FIX = Path(__file__).parents[1] / "fixtures/rule_ir"
RULE_ID = "00000000-0000-4000-8000-000000000001"  # form_simple_0's own rule_id
REG = default_registry()
_BASE: dict[str, Any] = json.loads((FIX / "form_simple_0.json").read_text(encoding="utf-8"))
_SLOT = "__slot__"
_JSON = {"content-type": "application/json"}
_PROBLEM = "https://candleviewer.local/errors/rule_ir_invalid"
_REASON = "Text holds an unpaired surrogate code point"
#: Where the slot is -> (the escape sent there, compile's errors[].field, save's path).
_CASES = {
    "action param key": ("\\ud800", "actions[0].params", "/actions/0/params/\\ud800"),
    "action param value": ("\\udc00", "actions[0].params.note", "/actions/0/params/note"),
    "metric param": ("\\udbff", "conditions.left.params.source", "/conditions/left/params/source"),
    "node id": ("\\ud800", "conditions.comparison.node_id", "/conditions/comparison/node_id"),
    "layout": ("\\udc00", "graph_layout", "/graph_layout"),
    "trigger metric": ("\\udfff", "trigger.metric", "/trigger/metric"),
}


def _ir(where: str) -> dict[str, Any]:
    """``form_simple_0``, saveable, with the slot at ``where``."""
    doc = copy.deepcopy(_BASE)
    act: dict[str, Any] = {"channel": "ui", "severity": "info", "template": "x"}
    if where == "action param key":
        act[_SLOT] = "x"
    elif where == "action param value":
        act["note"] = _SLOT
    elif where == "node id":
        doc["conditions"]["node_id"] = _SLOT
    elif where == "layout":
        doc["graph_layout"] = {_SLOT: {"x": 0, "y": 0}}
    elif where == "trigger metric":
        doc["trigger"] = {"type": "on_metric_change", "metric": _SLOT}
    else:
        doc["conditions"]["left"]["params"]["source"] = _SLOT
    doc["actions"][0]["params"] = act
    return doc


def _raw(body: dict[str, Any], text: str) -> bytes:
    """``body`` as JSON text with the slot spelled ``"<text>"`` (an escape goes as written)."""
    return json.dumps(body, default=str).replace(f'"{_SLOT}"', f'"{text}"').encode()


class _Reader:
    def has(self, permission: str) -> bool:
        return permission == "rules:read"


class _Resolver:
    def resolve(self, request: Request) -> _Reader:
        return _Reader()


def _compile(body: dict[str, Any], where: str) -> Response:
    app = FastAPI()
    app.include_router(make_rules_router(lambda: REG, principal_resolver=_Resolver()))
    url = f"/rules/{RULE_ID}/compile"
    return TestClient(app).post(url, content=_raw(body, _CASES[where][0]), headers=_JSON)


def _crud() -> TestClient:
    mgr = RulesManager(InMemoryRuleStore(), REG)
    actor = Actor("u1", "s1", frozenset({"rules:read", "rules:write"}), is_owner=True)
    app = FastAPI()
    app.include_router(make_rules_crud_router(lambda: mgr, lambda _request: actor))
    return TestClient(app)


@pytest.mark.parametrize("where", sorted(_CASES))
def test_compile_lone_surrogate_in_ir_text_is_422_rule_ir_invalid_naming_the_field(
    where: str,
) -> None:
    r = _compile({"editor": "form", "model": _ir(where)}, where)
    assert (r.status_code, r.headers["content-type"]) == (422, "application/problem+json"), r.text
    assert (r.json()["code"], r.json()["type"]) == ("rule_ir_invalid", _PROBLEM)
    assert r.json()["errors"] == [
        {"field": _CASES[where][1], "rule": "schema_error", "message": _REASON, "node_ids": []}
    ]


@pytest.mark.parametrize("where", sorted(_CASES))
def test_compile_lone_surrogate_in_counterpart_model_is_422_rule_ir_invalid(where: str) -> None:
    graph = to_graph_model(Rule.model_validate(json.loads(_raw(_ir(where), "price"))))
    r = _compile({"editor": "graph", "model": graph, "counterpart_model": _ir(where)}, where)
    assert (r.status_code, r.json()["code"]) == (422, "rule_ir_invalid"), r.text
    assert [e["field"] for e in r.json()["errors"]] == [_CASES[where][1]]


@pytest.mark.parametrize("where", sorted(_CASES))
def test_save_lone_surrogate_in_ir_text_is_422_rule_ir_invalid_and_nothing_is_stored(
    where: str,
) -> None:
    c = _crud()
    r = c.post("/rules", content=_raw({"ir": _ir(where)}, _CASES[where][0]), headers=_JSON)
    assert (r.status_code, r.headers["content-type"]) == (422, "application/problem+json"), r.text
    assert (r.json()["code"], r.json()["type"]) == ("rule_ir_invalid", _PROBLEM)
    assert r.json()["detail"] == f"The rule document is not valid: {_REASON}"
    assert r.json()["path"] == _CASES[where][2]
    assert c.get("/rules").json()["items"] == []


@pytest.mark.parametrize("where", sorted(_CASES))
def test_update_lone_surrogate_in_ir_text_is_422_rule_ir_invalid_and_adds_no_version(
    where: str,
) -> None:
    c = _crud()
    made = c.post("/rules", content=_raw({"ir": _ir(where)}, "price"), headers=_JSON)
    assert made.status_code == 201, made.text
    rid, sent = made.json()["id"], _raw({"ir": _ir(where)}, _CASES[where][0])
    r = c.put(f"/rules/{rid}", content=sent, headers={**_JSON, "If-Match": "1"})
    assert (r.status_code, r.json()["code"]) == (422, "rule_ir_invalid"), r.text
    assert r.json()["path"] == _CASES[where][2]
    assert c.get(f"/rules/{rid}").json()["latest_version"] == 1


def test_compile_graph_refusal_naming_a_lone_surrogate_node_id_is_422_with_it_escaped() -> None:
    """The graph editor's own refusal names the node: its id goes back escaped, never a 500."""
    nodes = [{"id": _SLOT, "type": "comparison", "data": {"op": "gt"}},  # no operands: refused
             {"id": "a1", "type": "action", "data": _BASE["actions"][0]}]  # fmt: skip
    model = {**_BASE, "nodes": nodes, "edges": [{"from": _SLOT, "to": "a1", "port": "when"}]}
    r = _compile({"editor": "graph", "model": model}, "node id")
    assert (r.status_code, r.json()["code"]) == (422, "rule_ir_invalid"), r.text
    assert {n for e in r.json()["errors"] for n in e["node_ids"]} == {"\\ud800"}
    assert "nodes.\\ud800" in {e["field"] for e in r.json()["errors"]}
