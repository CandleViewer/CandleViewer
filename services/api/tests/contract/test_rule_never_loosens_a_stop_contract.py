"""Contract (#2698): no rule loosens a stop, whatever permission its caller holds.

`24-internal-schemas.md` section 8.8 rule 5 refuses a rule action that would widen a stop,
`modify_stop_loss` with `only_tighten=false` or `widen_stop`, whatever permission the rule holds.
The rule engine refuses such a rule before it is stored, with the issue code that
`22-api-openapi.yaml` registers (`RuleValidationIssue.code`) and `createRule` explains. Read from
the spec and the plan, never from a copy (AGENTS.md section 6 rule 12).
"""

from __future__ import annotations

from typing import Any

import jsonschema
import pytest

from candleviewer.rules.ir import Rule
from candleviewer.rules.validator import validate_rule
from candleviewer.rules.vocabulary import default_registry
from tests.contract.test_stop_loosen_contract import _OPS, _SPEC, _rule_5, _words
from tests.rules.test_rules_routes import _ir

_SCHEMAS: Any = _SPEC["components"]["schemas"]
_CODE = "stop_loosening"


def _stop(kind: str, **params: Any) -> dict[str, Any]:
    return {"node_id": "a1", "type": kind, "params": {"mode": "atr", "value": 2, **params}}


def test_22_registers_the_refusal_and_create_rule_holds_it_for_every_role() -> None:
    assert _CODE in _SCHEMAS["RuleValidationIssue"]["properties"]["code"]["enum"]
    create = _words(_OPS["createRule"]["description"])
    for phrase in (
        "**No rule loosens a stop (24-internal-schemas.md section 8.8 rule 5).**",
        "is refused for every role, the Owner included, whatever permission the caller holds: "
        "`422 rule_ir_invalid`, issue code `stop_loosening`, class `safety`",
        '"Not available — rules never loosen a stop."',
        "`validateRule` and `compileRule` report the same issue, and an imported rule is refused "
        "with it",
    ):
        assert phrase in create, phrase
    update = _words(_OPS["updateRule"]["description"])
    assert "held to the action budget and the stop rule of `createRule`" in update


@pytest.mark.parametrize(
    "action", [_stop("modify_stop_loss", only_tighten=False), _stop("widen_stop")]
)
def test_each_form_rule_5_names_is_refused_with_the_registered_code(
    action: dict[str, Any],
) -> None:
    assert "`modify_stop_loss` with `only_tighten=false`, or `widen_stop`) is refused" in _rule_5()
    result = validate_rule(Rule.model_validate(_ir(actions=[action])), default_registry())
    body = result.to_dict()
    schema = {"components": _SPEC["components"], **_SCHEMAS["RuleValidationResult"]}
    jsonschema.Draft202012Validator(schema).validate(body)
    assert [(e["code"], e["class"]) for e in body["errors"]] == [(_CODE, "safety")]
