"""``POST /rules/validate`` refuses what compile refuses (#4185): a value the rule hash cannot hold
is ``valid: false`` naming the field, not ``valid: true`` with a 422 waiting at compile and save.

Validate used to stop at the models and the semantic checks, which accept these values: a lone
surrogate in free text (an action param key or value, a metric param, a timeframe), a NaN in an
action param, and a decimal past the context's range or wider than 64 characters. Each case goes to
both routes, and each must name the same field. Bodies go as raw JSON text, so the spelling is kept.
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
from candleviewer.rules.vocabulary import default_registry

FIX = Path(__file__).parents[1] / "fixtures/rule_ir"
RULE_ID = "00000000-0000-4000-8000-000000000001"  # form_simple_0's own rule_id
REG = default_registry()
_BASE: dict[str, Any] = json.loads((FIX / "form_simple_0.json").read_text(encoding="utf-8"))
_SLOT = "__slot__"
_JSON = {"content-type": "application/json"}
_UNPAIRED = "Text holds an unpaired surrogate code point"
_FINITE = "Input should be a finite number"
_RANGE = "Number is outside the range a rule can hold"
_ABOVE = f'"1E+{decimal.getcontext().Emax + 1}"'  # a numeric string one past the largest exponent
_WIDE = '"1E+64"'  # a numeric string whose plain form is 65 characters, one past the bound
#: Where the slot is -> (the spelling sent there, the field both routes name, the refusal).
_CASES = {
    "action param key": ('"\\ud800"', "actions[0].params", _UNPAIRED),
    "action param value": ('"\\udc00"', "actions[0].params.note", _UNPAIRED),
    "metric param": ('"\\udbff"', "conditions.left.params.source", _UNPAIRED),
    "metric timeframe": ('"\\udfff"', "conditions.left.timeframe", _UNPAIRED),
    "trigger timeframe": ('"\\ud800"', "trigger.timeframe", _UNPAIRED),
    "action param nan": ("NaN", "actions[0].params.w", _FINITE),
    "decimal out of range": (_ABOVE, "conditions.tolerance", _RANGE),
    "decimal too wide": (_WIDE, "conditions.tolerance", _RANGE),
}


def _ir(where: str) -> dict[str, Any]:
    """``form_simple_0``, saveable, with the slot at ``where``."""
    doc = copy.deepcopy(_BASE)
    act: dict[str, Any] = {"channel": "ui", "severity": "info", "template": "x"}
    if where == "action param key":
        act[_SLOT] = "x"
    elif where == "action param value":
        act["note"] = _SLOT
    elif where == "action param nan":
        act["w"] = _SLOT
    elif where == "metric param":
        doc["conditions"]["left"]["params"]["source"] = _SLOT
    elif where == "metric timeframe":
        doc["conditions"]["left"]["timeframe"] = _SLOT
    elif where == "trigger timeframe":
        doc["trigger"] = {"type": "on_bar_close", "timeframe": _SLOT}
    else:
        doc["conditions"]["tolerance"] = _SLOT
    doc["actions"][0]["params"] = act
    return doc


class _Reader:
    def has(self, permission: str) -> bool:
        return permission == "rules:read"


class _Resolver:
    def resolve(self, request: Request) -> _Reader:
        return _Reader()


def _post(url: str, body: dict[str, Any], spelling: str) -> Response:
    app = FastAPI()
    app.include_router(make_rules_router(lambda: REG, principal_resolver=_Resolver()))
    raw = json.dumps(body, default=str).replace(f'"{_SLOT}"', spelling).encode()
    return TestClient(app).post(url, content=raw, headers=_JSON)


@pytest.mark.parametrize("where", _CASES)
def test_validate_value_the_hash_refuses_is_invalid_naming_the_field_compile_names(
    where: str,
) -> None:
    spelling, field, reason = _CASES[where]
    c = _post(f"/rules/{RULE_ID}/compile", {"editor": "form", "model": _ir(where)}, spelling)
    assert (c.status_code, [e["field"] for e in c.json()["errors"]]) == (422, [field]), c.text
    v = _post("/rules/validate", {"ir": _ir(where)}, spelling)
    assert (v.status_code, v.json()["valid"]) == (200, False), v.text
    errors = [(e["path"], e["code"], e["message"]) for e in v.json()["errors"]]
    assert errors == [(field, "schema_error", reason)]
