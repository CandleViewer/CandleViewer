"""#4834 (E35 authoring limits): each number the code holds is the one `22` states.

`test_rule_authoring_limits_contract.py` pins what `22` says; these tests tie its numbers to the
constants and settings that hold them, so neither moves alone: the condition-node bound, the
validate / compile limit, the `note` and `reason` bound, the stored-rule cap with the list's page
bound, and the refusal-record budget. The last test reads a save's real refusal of a rule document
against `RuleIrInvalid` (#4834's C-row): 22's `errors[{field, rule, message}]`, no `issues`.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from candleviewer.api.rules import CHECK_BURST_FACTOR
from candleviewer.api.rules_crud import MAX_PAGE
from candleviewer.rules.compiler.common import MAX_CONDITION_NODES, condition_node_error
from candleviewer.rules.limits import (
    MAX_NOTE_CHARS,
    MAX_STORED_RULES_PER_USER,
    stored_rules_message,
)
from candleviewer.rules.manager import (
    CONFLICT_TITLE,
    RULE_IR_INVALID_TITLE,
    RuleCapRefused,
    check_text_bound,
)
from candleviewer.settings import (
    RULES_CHECK_RATE_PER_USER_PER_SECOND,
    RULES_REFUSAL_BUDGET_PER_HOUR,
    Settings,
)
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode
from tests.contract._admin_support import SPEC, text, validate_example
from tests.rules.test_rule_condition_node_cap import _over, _Saves
from tests.rules.test_rules_routes import _Env, _ir

_SCHEMAS: dict[str, Any] = SPEC["components"]["schemas"]
_OPS: dict[str, dict[str, Any]] = {
    op["operationId"]: op
    for item in SPEC["paths"].values()
    for method, op in item.items()
    if method in {"get", "put", "post", "patch", "delete"}
}


def _prose(operation_id: str) -> str:
    return text(_OPS[operation_id]["description"])


_REGISTRY: dict[str, dict[str, Any]] = {e["code"]: e for e in SPEC["x-error-codes"]}
_INVALID = "/components/responses/RuleIrInvalid/content/application~1problem+json/schema"


def _body(operation_id: str) -> dict[str, Any]:
    """The properties of an operation's inline request body."""
    schema = _OPS[operation_id]["requestBody"]["content"]["application/json"]["schema"]
    properties: dict[str, Any] = schema["properties"]
    return properties


def _invalid_example(name: str) -> dict[str, Any]:
    """A named example of the shared `RuleIrInvalid` response."""
    examples = SPEC["components"]["responses"]["RuleIrInvalid"]["content"][
        "application/problem+json"
    ]["examples"]
    value: dict[str, Any] = examples[name]["value"]
    return value


def _node_example() -> dict[str, Any]:
    """The `conditionNodes` example: the answer to a rule over the condition-node bound."""
    return _invalid_example("conditionNodes")


def _number(pattern: str, prose: str) -> int:
    found = re.search(pattern, prose)
    assert found is not None, pattern
    return int(found.group(1).replace(",", ""))


def test_max_condition_nodes_is_the_bound_22_states() -> None:
    bound = text(_SCHEMAS["RuleIr"]["description"]).split("**Condition-node bound (E35, #4834).**")[
        1
    ]
    assert MAX_CONDITION_NODES == _number(r"`conditions` holds at most ([\d,]+) nodes", bound)
    for operation_id in ("validateRule", "compileRule"):
        assert f"{MAX_CONDITION_NODES:,} condition nodes" in _prose(operation_id)
    (error,) = _node_example()["errors"]
    (issue,) = condition_node_error().issues  # the place and the message the code answers with
    assert (error["field"], error["rule"], error["message"]) == (
        issue.path,
        issue.code,
        issue.message,
    )


def test_a_save_over_the_node_bound_answers_as_the_example_22_shows() -> None:
    """`createRule` and `updateRule` share the example: a save over the bound answers its status,
    code, `detail` and `errors[]`, and carries no `issues` (C-6.1)."""
    example = _node_example()
    members = ("status", "code", "detail", "errors")
    saves = _Saves()
    rid = saves.c.post("/rules", json={"ir": _ir()}).json()["id"]
    created = saves.c.post("/rules", json={"ir": _over()})
    updated = saves.c.put(f"/rules/{rid}", json={"ir": _over()}, headers={"If-Match": "1"})
    for answer in (created, updated):
        body = answer.json()
        assert answer.status_code == example["status"]
        assert {m: body[m] for m in members} == {m: example[m] for m in members}
        assert "issues" not in body


def test_the_check_limit_default_and_burst_are_the_ones_22_states() -> None:
    prose = _prose("validateRule")
    assert RULES_CHECK_RATE_PER_USER_PER_SECOND == _number(r"\(default (\d+) a second\)", prose)
    assert Settings.model_fields["rules_check_rate_per_user_per_second"].default == (
        RULES_CHECK_RATE_PER_USER_PER_SECOND
    )
    assert "twice the rate" in prose and CHECK_BURST_FACTOR == 2
    burst = RULES_CHECK_RATE_PER_USER_PER_SECOND * CHECK_BURST_FACTOR
    assert burst == _number(r"a burst of twice the rate \((\d+) by default\)", prose)
    assert "`rules_check_rate_per_user_per_second`" in prose
    registered = next(e for e in SPEC["x-error-codes"] if e["code"] == "rate_limited")
    assert ERROR_META[ErrorCode.RATE_LIMITED].title == registered["title"]


@pytest.mark.parametrize(
    ("operation_id", "field"),
    [
        ("createRule", "note"),
        ("updateRule", "note"),
        ("setActiveRuleVersion", "note"),
        ("setRuleMode", "reason"),
    ],
)
def test_max_note_chars_is_the_bound_22_states_on_each_write(operation_id: str, field: str) -> None:
    schemas = {"createRule": "RuleInput", "updateRule": "RuleUpdateInput"}
    if operation_id in schemas:
        member = _SCHEMAS[schemas[operation_id]]["properties"][field]
    else:
        member = _body(operation_id)[field]
    assert member["maxLength"] == MAX_NOTE_CHARS
    if operation_id != "updateRule":  # it holds a save to `createRule`'s bounds by reference
        assert f"{MAX_NOTE_CHARS} characters, counted in Unicode code points" in (
            _prose(operation_id)
        )
    with pytest.raises(RuleCapRefused) as refused:
        check_text_bound("note" if field == "note" else "reason", "x" * (MAX_NOTE_CHARS + 1))
    example = _invalid_example("noteTooLong")
    answer = refused.value
    assert (answer.status, answer.code, answer.message) == (
        example["status"],
        example["code"],
        example["detail"],
    )
    named = [{**example["errors"][0], "field": field}]
    assert answer.extra == {"title": example["title"], "errors": named}
    assert example["title"] == _REGISTRY["rule_ir_invalid"]["title"] == RULE_IR_INVALID_TITLE


def test_the_stored_rule_cap_and_the_page_bound_are_the_ones_22_states() -> None:
    held = _number(r"A caller holds at most ([\d,]+) saved rules", _prose("createRule"))
    assert MAX_STORED_RULES_PER_USER == held
    page = _number(r"A page holds at most ([\d,]+) rules", _prose("listRules"))
    assert MAX_PAGE == page == MAX_STORED_RULES_PER_USER  # one page holds a user's whole set
    conflict = _OPS["createRule"]["responses"]["409"]["content"]["application/problem+json"]
    example = conflict["examples"]["storedRuleCap"]["value"]
    message = stored_rules_message(MAX_STORED_RULES_PER_USER)
    assert example["detail"] == message
    assert example["errors"] == [{"rule": "limit_reached", "message": message}]
    assert example["title"] == _REGISTRY["conflict"]["title"] == CONFLICT_TITLE


def test_the_refusal_record_budget_default_is_the_one_22_states() -> None:
    info = text(SPEC["info"]["description"])
    stated = _number(r"`rules_refusal_budget_per_hour` \(default (\d+)\)", info)
    assert RULES_REFUSAL_BUDGET_PER_HOUR == stated
    field = Settings.model_fields["rules_refusal_budget_per_hour"]
    assert field.default == RULES_REFUSAL_BUDGET_PER_HOUR


def test_a_saves_refusal_of_a_rule_document_is_22s_rule_ir_invalid_with_errors() -> None:
    """The C-row (#4834): one shape for a refused rule document. A save names each issue in
    `RuleIrInvalid`'s `errors[{field, rule, message}]`, `rule` the issue's code, with the registered
    title and a `detail` that counts them, as the node bound's `conditionNodes` example does; it
    carries no `issues` member."""
    widen = {"node_id": "a1", "type": "widen_stop", "params": {"mode": "pct", "value": 1}}
    for refused in (
        _Env().c.post("/rules", json={"ir": _ir(actions=[widen])}),
        _Env().c.post("/rules", json={"ir": _ir(limits={"max_fires_per_hour": 10**6})}),
    ):
        body = refused.json()
        assert (refused.status_code, body["code"]) == (422, "rule_ir_invalid"), refused.text
        validate_example(_INVALID, body)
        assert set(body) == {"type", "title", "status", "code", "detail", "errors"}
        assert body["title"] == _REGISTRY["rule_ir_invalid"]["title"]
        assert all(set(e) == {"field", "rule", "message"} for e in body["errors"])
        n = len(body["errors"])
        assert body["detail"] == f"{n} error{'s' if n != 1 else ''} in the rule IR."


def test_a_save_over_the_node_cap_answers_22s_condition_nodes_example() -> None:
    """The cap's refusal and every other refused rule document share the example's shape."""
    stated = _invalid_example("conditionNodes")
    refused = _Env().c.post("/rules", json={"ir": _over()})
    assert refused.json() == {k: v for k, v in stated.items() if k != "instance"}
