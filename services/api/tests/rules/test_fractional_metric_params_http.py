"""A fractional metric param over HTTP (#4132): compile and save succeed with a stable hash, and a
value the IR cannot hold is a ``422 rule_ir_invalid`` problem on both paths, never a 500.

Bodies go as raw JSON text, so every number keeps its spelling (``0.50``, ``5E-1``) and the
non-standard literals Python's ``json`` accepts (``NaN``, ``Infinity``) reach the routes as floats.
"""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from httpx import Response

from candleviewer.api.rules import make_rules_router
from candleviewer.api.rules_crud import make_rules_crud_router
from candleviewer.rules.compiler import to_graph_model
from candleviewer.rules.ir import Rule, ir_hash
from candleviewer.rules.manager import Actor, InMemoryRuleStore, RulesManager
from candleviewer.rules.vocabulary import default_registry
from tests.rules._check_limiter import unthrottled

FIX = Path(__file__).parents[1] / "fixtures/rule_ir"
RULE_ID = "00000000-0000-4000-8000-000000000001"  # form_simple_0's own rule_id
REG = default_registry()
_BASE: dict[str, Any] = json.loads((FIX / "form_simple_0.json").read_text(encoding="utf-8"))
#: The hashes tests/unit/rules_ir/test_metric_param_values.py pins (computed on the base commit).
HALF = "ca1d7339f3a1554d6620a685d1872ea2a431f05aa2e4099b55fabb3697232e9e"
ONE = "503b645c9d48b1a32eb7e7a87abcfbd85471512cbf49a7f37532938244900847"
TRUE = "0520de66e155eb688ee163d99f72be44458e1854e5dafe1f4ab2b8d3bfe92468"
NULL = "3019dc201c2e965a58aefdf8ef3a87474ff8ad36bbc239f262fe25e3b1d67f46"
_SLOT = "__slot__"
_FINITE = "Input should be a finite number"
_PLAIN = "Input should be a plain value (true/false, a number, text or null)"
_REFUSED = [
    ('{"a": 1}', _PLAIN), ("[1]", _PLAIN), ("NaN", _FINITE), ("Infinity", _FINITE),
    ("-Infinity", _FINITE),
]  # fmt: skip
_NON_FINITE = ["NaN", "Infinity", "-Infinity"]
_JSON = {"content-type": "application/json"}
_PROBLEM = "https://candleviewer.local/errors/rule_ir_invalid"


def _ir(threshold: Any = _SLOT, **action: Any) -> dict[str, Any]:
    """``form_simple_0`` with ``threshold`` in its metric operand's params (``action``: extra
    params on its action); ``_SLOT`` marks the value ``_raw`` spells."""
    doc = copy.deepcopy(_BASE)
    doc["conditions"]["left"] = {"metric": "rsi", "params": {"period": 14, "threshold": threshold}}
    doc["actions"][0]["params"] = {"channel": "ui", "severity": "info", "template": "x", **action}
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


def _compile(spelling: str, body: dict[str, Any] | None = None) -> Response:
    app = FastAPI()
    app.include_router(
        make_rules_router(lambda: REG, principal_resolver=_Resolver(), check_limiter=unthrottled())
    )
    body = {"editor": "form", "model": _ir()} if body is None else body
    url = f"/rules/{RULE_ID}/compile"
    return TestClient(app).post(url, content=_raw(body, spelling), headers=_JSON)


def _crud() -> TestClient:
    mgr = RulesManager(InMemoryRuleStore(), REG)
    actor = Actor("u1", "s1", frozenset({"rules:read", "rules:write"}), is_owner=True)
    app = FastAPI()
    app.include_router(make_rules_crud_router(lambda: mgr, lambda _request: actor))
    return TestClient(app)


def test_compile_fractional_metric_param_is_200_with_a_deterministic_hash() -> None:
    """Scenario: a rule whose metric operand params hold 0.5 compiles (200, never a 500)."""
    first, again = _compile("0.5"), _compile("0.5")
    assert first.status_code == again.status_code == 200, first.text
    assert first.json()["ir_hash"] == again.json()["ir_hash"] == HALF
    assert first.json()["ir"]["conditions"]["left"]["params"] == {"period": 14, "threshold": "0.5"}


@pytest.mark.parametrize(
    ("spelling", "expected"),
    [("0.5", HALF), ("0.50", HALF), ("5E-1", HALF), ("1", ONE), ("1.0", ONE), ("true", TRUE),
     ("null", NULL)],
)  # fmt: skip
def test_compile_metric_param_spelling_hashes_to_its_pinned_value(
    spelling: str, expected: str
) -> None:
    r = _compile(spelling)
    assert (r.status_code, r.json()["ir_hash"]) == (200, expected)


def test_save_fractional_metric_param_creates_and_an_equal_spelling_is_no_new_version() -> None:
    """Scenario: saved with 0.5; the same rule spelled 0.50 is the same version (same hash)."""
    c = _crud()
    made = c.post("/rules", content=_raw({"ir": _ir()}, "0.5"), headers=_JSON)
    assert made.status_code == 201, made.text
    rid, h = made.json()["id"], made.json()["version"]["ir_hash"]
    stored = {**_ir(Decimal("0.5")), "rule_id": rid, "mode": "disabled", "enabled": False}
    assert h == ir_hash(stored)
    same = c.put(
        f"/rules/{rid}", content=_raw({"ir": _ir()}, "0.50"), headers={**_JSON, "If-Match": "1"}
    )
    assert same.status_code == 200, same.text
    assert same.json()["created"] is False and same.json()["version"]["ir_hash"] == h


@pytest.mark.parametrize("spelling", ["0.5", "3.0", "1e-7", "1E+21", "null"])
def test_metric_param_ir_returned_or_stored_rehashes_alike_and_resaves_as_no_version(
    spelling: str,
) -> None:
    """Compile's returned IR compiles to its hash again; the stored version re-validates to its
    hash; and an unchanged re-save of the stored IR is no new version."""
    compiled = _compile(spelling)
    assert compiled.status_code == 200, compiled.text
    again = _compile(spelling, {"editor": "form", "model": compiled.json()["ir"]})
    assert (again.status_code, again.json()["ir_hash"]) == (200, compiled.json()["ir_hash"])
    c = _crud()
    made = c.post("/rules", content=_raw({"ir": _ir()}, spelling), headers=_JSON)
    assert made.status_code == 201, made.text
    rid, version = made.json()["id"], made.json()["version"]
    stored = c.get(f"/rules/{rid}/versions/{version['id']}").json()["ir"]
    assert ir_hash(Rule.model_validate(stored)) == version["ir_hash"]
    same = c.put(f"/rules/{rid}", json={"ir": stored}, headers={"If-Match": "1"})
    assert same.status_code == 200, same.text
    assert same.json()["created"] is False
    assert same.json()["version"]["ir_hash"] == version["ir_hash"]


@pytest.mark.parametrize(("spelling", "message"), _REFUSED)
def test_compile_unsupported_metric_param_value_is_one_422_rule_ir_invalid_error(
    spelling: str, message: str
) -> None:
    r = _compile(spelling)
    body = r.json()
    assert (r.status_code, r.headers["content-type"]) == (422, "application/problem+json")
    assert (body["code"], body["type"], body["status"]) == ("rule_ir_invalid", _PROBLEM, 422)
    assert len(body["errors"]) == 1, body["errors"]
    assert (body["errors"][0]["rule"], body["errors"][0]["message"]) == ("schema_error", message)
    assert body["errors"][0]["field"].endswith("params.threshold")


@pytest.mark.parametrize(("spelling", "message"), _REFUSED)
def test_save_unsupported_metric_param_value_is_422_rule_ir_invalid_saying_why(
    spelling: str, message: str
) -> None:
    r = _crud().post("/rules", content=_raw({"ir": _ir()}, spelling), headers=_JSON)
    body = r.json()
    assert (r.status_code, r.headers["content-type"]) == (422, "application/problem+json")
    assert (body["code"], body["type"], body["status"]) == ("rule_ir_invalid", _PROBLEM, 422)
    assert body["detail"] == f"The rule document is not valid: {message}"
    assert body["path"].endswith("/params/threshold")


@pytest.mark.parametrize("spelling", _NON_FINITE)
def test_compile_non_finite_action_param_is_422_rule_ir_invalid(spelling: str) -> None:
    r = _compile(spelling, {"editor": "form", "model": _ir(14, weight=_SLOT)})
    assert (r.status_code, r.json()["code"]) == (422, "rule_ir_invalid")
    assert r.json()["errors"] == [
        {"field": "actions[0].params.weight", "rule": "schema_error",
         "message": "Input should be a finite number", "node_ids": []}
    ]  # fmt: skip


@pytest.mark.parametrize("spelling", _NON_FINITE)
def test_save_non_finite_action_param_is_422_rule_ir_invalid(spelling: str) -> None:
    body = _raw({"ir": _ir(14, weight=_SLOT)}, spelling)
    r = _crud().post("/rules", content=body, headers=_JSON)
    assert (r.status_code, r.json()["code"]) == (422, "rule_ir_invalid")
    assert r.json()["path"] == "/actions/0/params/weight"
    assert r.json()["detail"] == "The rule document is not valid: Input should be a finite number"


def test_compile_non_finite_counterpart_action_param_is_422_rule_ir_invalid() -> None:
    graph = to_graph_model(Rule.model_validate(_ir(14)))
    body = {"editor": "graph", "model": graph, "counterpart_model": _ir(14, weight=_SLOT)}
    r = _compile("NaN", body)
    assert (r.status_code, r.json()["code"]) == (422, "rule_ir_invalid")
    assert [e["field"] for e in r.json()["errors"]] == ["actions[0].params.weight"]
