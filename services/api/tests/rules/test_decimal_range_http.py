"""A number the rule hash refuses over HTTP (#4185), outside the decimal range or with a canonical
form wider than 64 characters: compile (and its counterpart model), save and update answer
``422 rule_ir_invalid`` naming the field, never a 500, and nothing is stored.

``tolerance`` and the notional limits are ``Decimal`` fields that read a numeric string, so a body
can carry such a number there (a JSON number past the float range reads as ``inf``: refused
already). Bodies go as raw JSON text, so the spelling is kept; each number is built from the
decimal context's own limits.
"""

from __future__ import annotations

import copy
import decimal
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
_REASON = "Number is outside the range a rule can hold"
_CTX = decimal.getcontext()
_WIDTH = 64  # the most characters a canonical number may take
#: The spelling sent: a number past the top of the range (either sign), one below its bottom, and
#: one whose plain form is a character wider than the bound.
_SPELLED = {
    "above": f'"1E+{_CTX.Emax + 1}"', "negative above": f'"-1E+{_CTX.Emax + 1}"',
    "below": f'"1E{_CTX.Etiny() - 1}"', "too wide": f'"1E+{_WIDTH}"',
}  # fmt: skip
_ABOVE = _SPELLED["above"]
#: Where the slot is -> (compile's errors[].field, save's path).
_WHERE = {
    "tolerance": ("conditions.tolerance", "/conditions/tolerance"),
    "per-fire notional": ("limits.max_notional_per_fire", "/limits/max_notional_per_fire"),
    "daily notional": ("limits.max_daily_notional", "/limits/max_daily_notional"),
}


def _ir(where: str) -> dict[str, Any]:
    """``form_simple_0``, saveable, with the slot at ``where``."""
    doc = copy.deepcopy(_BASE)
    doc["actions"][0]["params"] = {"channel": "ui", "severity": "info", "template": "x"}
    section, key = _WHERE[where][0].split(".")  # conditions.tolerance, limits.<key>
    doc[section][key] = _SLOT
    return doc


def _raw(body: dict[str, Any], spelling: str) -> bytes:
    """``body`` as JSON text with the slot spelled exactly ``spelling``."""
    return json.dumps(body, default=str).replace(f'"{_SLOT}"', spelling).encode()


class _Reader:
    def has(self, permission: str) -> bool:
        return permission == "rules:read"


class _Resolver:
    def resolve(self, request: Request) -> _Reader:
        return _Reader()


def _compile(body: dict[str, Any], spelling: str) -> Response:
    app = FastAPI()
    app.include_router(make_rules_router(lambda: REG, principal_resolver=_Resolver()))
    url = f"/rules/{RULE_ID}/compile"
    return TestClient(app).post(url, content=_raw(body, spelling), headers=_JSON)


def _crud() -> TestClient:
    mgr = RulesManager(InMemoryRuleStore(), REG)
    actor = Actor("u1", "s1", frozenset({"rules:read", "rules:write"}), is_owner=True)
    app = FastAPI()
    app.include_router(make_rules_crud_router(lambda: mgr, lambda _request: actor))
    return TestClient(app)


@pytest.mark.parametrize("spelling", _SPELLED)
@pytest.mark.parametrize("where", _WHERE)
def test_compile_number_outside_the_decimal_range_is_422_rule_ir_invalid_naming_the_field(
    where: str, spelling: str
) -> None:
    r = _compile({"editor": "form", "model": _ir(where)}, _SPELLED[spelling])
    assert (r.status_code, r.headers["content-type"]) == (422, "application/problem+json"), r.text
    assert (r.json()["code"], r.json()["type"]) == ("rule_ir_invalid", _PROBLEM)
    assert r.json()["errors"] == [
        {"field": _WHERE[where][0], "rule": "schema_error", "message": _REASON, "node_ids": []}
    ]


@pytest.mark.parametrize("where", _WHERE)
def test_compile_number_outside_the_decimal_range_in_counterpart_model_is_422_rule_ir_invalid(
    where: str,
) -> None:
    graph = to_graph_model(Rule.model_validate(json.loads(_raw(_ir(where), '"1"'))))
    r = _compile({"editor": "graph", "model": graph, "counterpart_model": _ir(where)}, _ABOVE)
    assert (r.status_code, r.json()["code"]) == (422, "rule_ir_invalid"), r.text
    assert [e["field"] for e in r.json()["errors"]] == [_WHERE[where][0]]


@pytest.mark.parametrize("spelling", _SPELLED)
@pytest.mark.parametrize("where", _WHERE)
def test_save_number_outside_the_decimal_range_is_422_rule_ir_invalid_and_nothing_is_stored(
    where: str, spelling: str
) -> None:
    c = _crud()
    r = c.post("/rules", content=_raw({"ir": _ir(where)}, _SPELLED[spelling]), headers=_JSON)
    assert (r.status_code, r.headers["content-type"]) == (422, "application/problem+json"), r.text
    assert (r.json()["code"], r.json()["type"]) == ("rule_ir_invalid", _PROBLEM)
    assert r.json()["detail"] == f"The rule document is not valid: {_REASON}"
    assert r.json()["path"] == _WHERE[where][1]
    assert c.get("/rules").json()["items"] == []


@pytest.mark.parametrize("where", _WHERE)
def test_update_number_outside_the_decimal_range_is_422_rule_ir_invalid_and_adds_no_version(
    where: str,
) -> None:
    c = _crud()
    made = c.post("/rules", content=_raw({"ir": _ir(where)}, '"1"'), headers=_JSON)
    assert made.status_code == 201, made.text
    rid, sent = made.json()["id"], _raw({"ir": _ir(where)}, _ABOVE)
    r = c.put(f"/rules/{rid}", content=sent, headers={**_JSON, "If-Match": "1"})
    assert (r.status_code, r.json()["code"]) == (422, "rule_ir_invalid"), r.text
    assert r.json()["path"] == _WHERE[where][1]
    assert c.get(f"/rules/{rid}").json()["latest_version"] == 1
