"""#4834 (E35 authoring limits), contract first (C-6.1): the `/rules` limits in 22.

22 states the answer of each limit before the code that holds it: a `429` on both checks, a `409`
at the stored-rule cap, the refusal of a `note` or `reason` over its bound on the four writes, the
condition-node bound with its two answers, the list page bound and the refusal-record budget. Each
is read from the spec, never a copy (AGENTS.md section 6 rule 12). The numbers are the ruled ones,
and the slices that hold a bound pin it to its constant.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from tests.contract._admin_support import ROOT, SPEC, example_cases, text, validate_example

_COMPONENTS: dict[str, Any] = SPEC["components"]
_SCHEMAS: dict[str, Any] = _COMPONENTS["schemas"]
_METHODS = frozenset({"get", "put", "post", "patch", "delete"})
_OPS: dict[str, dict[str, Any]] = {
    op["operationId"]: op
    for item in SPEC["paths"].values()
    for method, op in item.items()
    if method in _METHODS
}
_REGISTRY: dict[str, dict[str, Any]] = {e["code"]: e for e in SPEC["x-error-codes"]}
_RAW_24 = (ROOT / "docs/plan/24-internal-schemas.md").read_text(encoding="utf-8")
_PROBLEM = "application/problem+json"
_RULE_IR_INVALID = {"$ref": "#/components/responses/RuleIrInvalid"}
_CHECKS = ("validateRule", "compileRule")


def _body(operation_id: str) -> dict[str, Any]:
    """The properties of an operation's inline request body."""
    schema = _OPS[operation_id]["requestBody"]["content"]["application/json"]["schema"]
    properties: dict[str, Any] = schema["properties"]
    return properties


#: Each write -> the member its bound holds, and that member's schema in 22.
_WRITES = {
    "createRule": ("note", _SCHEMAS["RuleInput"]["properties"]["note"]),
    "updateRule": ("note", _SCHEMAS["RuleUpdateInput"]["properties"]["note"]),
    "setActiveRuleVersion": ("note", _body("setActiveRuleVersion")["note"]),
    "setRuleMode": ("reason", _body("setRuleMode")["reason"]),
}
#: The examples this change adds -> the registered code and the `errors[].rule` each carries.
_NEW_EXAMPLES = {
    "storedRuleCap": ("conflict", "limit_reached"),
    "noteTooLong": ("rule_ir_invalid", "max_length"),
    "conditionNodes": ("rule_ir_invalid", "schema_error"),
}
#: `RuleValidationIssue.code` and the `rules` operations as 22 holds them: this change adds none.
_ISSUE_CODES = [
    *("schema_error", "unknown_variable", "unknown_function", "type_mismatch"),
    *("unreachable_branch", "guard_missing", "missing_action_param", "permission_required"),
    *("native_stop_missing", "unsupported_symbol", "unknown_metric", "operator_not_applicable"),
    *("cycle_detected", "dangling_port", "orphan_node", "multiple_sinks", "feedback_loop"),
    *("native_stop_violation", "high_frequency", "stop_loosening", "action_unavailable"),
]
_RULE_OPERATIONS = {
    *("listRules", "createRule", "getRule", "updateRule", "deleteRule", "listRuleVersions"),
    *("getRuleVersion", "setActiveRuleVersion", "validateRule", "simulateRule", "setRuleMode"),
    *("listRuleRuns", "listRuleRunEvents", "listRuleAccounts", "getRuleVocabulary"),
    *("getRuleIrSchema", "compileRule"),
}


def _prose(operation_id: str) -> str:
    return text(_OPS[operation_id]["description"])


def _answer(operation_id: str, status: str) -> dict[str, Any]:
    """The response an operation declares for `status`, a shared one followed by its `$ref`."""
    response: dict[str, Any] = _OPS[operation_id]["responses"][status]
    while "$ref" in response:
        response = _COMPONENTS["responses"][response["$ref"].rsplit("/", 1)[1]]
    return response


def _number(pattern: str, prose: str) -> int:
    """The one number `pattern` captures in `prose`, thousands separators dropped."""
    found = re.search(pattern, prose)
    assert found is not None, pattern
    return int(found.group(1).replace(",", ""))


def _example(operation_id: str, status: str, name: str) -> dict[str, Any]:
    examples = _answer(operation_id, status)["content"][_PROBLEM]["examples"]
    value: dict[str, Any] = examples[name]["value"]
    return value


@pytest.mark.parametrize("operation_id", _CHECKS)
def test_validate_and_compile_document_the_429_with_retry_after(operation_id: str) -> None:
    assert _OPS[operation_id]["responses"]["429"] == {"$ref": "#/components/responses/RateLimited"}
    limited = _answer(operation_id, "429")
    assert "Retry-After" in limited["headers"]
    example = limited["content"][_PROBLEM]["examples"]["local"]["value"]
    assert (example["status"], example["code"]) == (429, "rate_limited")
    prose = _prose(operation_id)
    assert "`429 rate_limited` with `Retry-After`" in prose
    assert "writes no audit record" in prose
    assert "one token bucket per user" in prose


def test_validate_and_compile_share_one_bucket_of_10_a_second_and_a_burst_of_20() -> None:
    prose = _prose("validateRule")
    assert "`validateRule` and `compileRule` share one token bucket per user, across" in prose
    assert "`rules_check_rate_per_user_per_second`" in prose
    rate = _number(r"\(default (\d+) a second\)", prose)
    burst = _number(r"a burst of twice the rate \((\d+) by default\)", prose)
    assert (rate, burst) == (10, 20)
    assert "(whole seconds, at least 1, which the body's `retry_after_seconds` repeats)" in prose
    assert "taken after authentication and the permission check and before the body" in prose
    assert "a refused caller takes no token" in prose
    assert "shared by both" in _prose("compileRule")


def test_create_rule_documents_the_stored_rule_cap_as_409_conflict_limit_reached() -> None:
    prose = _prose("createRule")
    cap = _number(r"A caller holds at most ([\d,]+) saved rules", prose)
    assert cap == 200
    counted = "the Owner included, counting the caller's own rules that are not deleted"
    assert f"A caller holds at most {cap} saved rules, {counted}" in prose
    assert "after the permission and scope checks, and nothing is stored" in prose
    assert "refused `409 conflict` with `errors[].rule` `limit_reached`" in prose
    interim = "interim until the Owner ratifies it as a `LIMIT_CAPS` row (#2701)"
    assert f"The cap of {cap} is {interim}" in prose
    declared = _OPS["createRule"]["responses"]["409"]
    assert declared["content"][_PROBLEM]["schema"] == {"$ref": "#/components/schemas/Problem"}
    assert f"holds {cap} saved rules" in declared["description"]
    example = _example("createRule", "409", "storedRuleCap")
    assert (example["status"], example["code"]) == (409, "conflict")
    assert [e["rule"] for e in example["errors"]] == ["limit_reached"]
    message = example["errors"][0]["message"]
    assert f"limit of {cap} saved rules" in message and example["detail"] == message


@pytest.mark.parametrize("operation_id", list(_WRITES))
def test_each_write_documents_the_note_or_reason_refusal(operation_id: str) -> None:
    field, member = _WRITES[operation_id]
    bound = member["maxLength"]
    assert bound == 280
    prose = _prose(operation_id)
    assert "422" in _OPS[operation_id]["responses"]
    assert "`422 rule_ir_invalid`" in prose and "`noteTooLong`" in prose
    if operation_id == "updateRule":  # a save is held to the bounds of `createRule`
        assert "held to the `note` and condition-node bounds of `createRule`" in prose
        assert "a refused save writes no version" in prose
        return
    if operation_id == "createRule":
        assert "refused whole, never shortened" in prose and "bind every role" in prose
    assert f"{bound} characters, counted in Unicode code points" in prose
    assert f"`errors[].field` `{field}`" in prose and "`errors[].rule` `max_length`" in prose
    assert "stays `400 validation_failed`" in prose
    assert "refused whole" in prose and "before the scope check" in prose
    assert "no audit record" in prose
    refusal = _example("createRule", "422", "noteTooLong")
    assert (refusal["status"], refusal["code"]) == (422, "rule_ir_invalid")
    assert [(e["field"], e["rule"]) for e in refusal["errors"]] == [("note", "max_length")]
    assert f"At most {bound} characters" in refusal["errors"][0]["message"]


def test_the_condition_node_bound_is_named_with_its_two_answers() -> None:
    held = text(_SCHEMAS["RuleIr"]["description"]).split("**Condition-node bound (E35, #4834).**")
    assert len(held) == 2
    bound = held[1]
    nodes = _number(r"`conditions` holds at most ([\d,]+) nodes", bound)
    assert nodes == 1000
    assert "comparison, boolean and temporal node counts once at each place it occurs" in bound
    assert "operands and actions are not nodes" in bound and "binds every role" in bound
    assert "`validateRule` answers a rule over it `200` with `valid: false` and one error" in bound
    assert "code `schema_error`, class `syntax`, path `conditions`" in bound
    assert "an import and `compileRule` answer `422 rule_ir_invalid`" in bound
    issue = _SCHEMAS["RuleValidationIssue"]["properties"]
    assert "schema_error" in issue["code"]["enum"] and "syntax" in issue["class"]["enum"]
    answer = "`200` with `valid: false` and one error, code `schema_error`, class `syntax`, path"
    assert f"{answer} `conditions`" in _prose("validateRule")
    assert "is refused `422 rule_ir_invalid` (example `conditionNodes`)" in _prose("compileRule")
    for operation_id in _CHECKS:
        assert f"{nodes:,} condition nodes" in _prose(operation_id)
    for operation_id in ("createRule", "updateRule", "compileRule"):
        assert "`conditionNodes`" in _prose(operation_id)
        assert _OPS[operation_id]["responses"]["422"] == _RULE_IR_INVALID
    example = _example("createRule", "422", "conditionNodes")
    assert (example["status"], example["code"]) == (422, "rule_ir_invalid")
    assert [(e["field"], e["rule"]) for e in example["errors"]] == [("conditions", "schema_error")]
    assert f"at most {nodes} condition nodes" in example["errors"][0]["message"]


def test_list_rules_names_its_page_bound() -> None:
    prose = _prose("listRules")
    page = _number(r"A page holds at most ([\d,]+) rules whatever `limit` asks for", prose)
    wider = _COMPONENTS["parameters"]["Limit"]["schema"]["maximum"]
    assert {"$ref": "#/components/parameters/Limit"} in _OPS["listRules"]["parameters"]
    assert (page, wider) == (200, 500)
    assert f"(`Limit` takes up to {wider})" in prose and "`meta.next_cursor`" in prose
    # One page holds the whole set of a user's stored rules.
    assert page == _number(r"A caller holds at most ([\d,]+) saved rules", _prose("createRule"))


def test_the_new_examples_validate_against_the_problem_schema() -> None:
    operations = [
        ("/rules", "post"),
        ("/rules/{ruleId}", "put"),
        ("/rules/{ruleId}/active-version", "put"),
        ("/rules/{ruleId}/compile", "post"),
    ]
    seen: set[str] = set()
    for case, pointer, value in example_cases(operations):
        name = case.rsplit(" ", 1)[1]
        if name not in _NEW_EXAMPLES:
            continue
        seen.add(name)
        validate_example(pointer, value)
        code, rule = _NEW_EXAMPLES[name]
        registered = _REGISTRY[code]
        assert (value["status"], value["title"]) == (registered["status"], registered["title"])
        assert value["code"] == code and value["type"].endswith(f"/errors/{code}")
        assert value["instance"].startswith("urn:cv:req:") and value["detail"]
        assert [e["rule"] for e in value["errors"]] == [rule]
        assert all(e["message"] for e in value["errors"])
        assert all("field" in e for e in value["errors"]) is (name != "storedRuleCap")
    assert seen == set(_NEW_EXAMPLES)


def test_the_contract_adds_no_error_code_no_issue_code_and_no_operation() -> None:
    """The limits answer with codes and issues 22 already registers, on the operations it already
    has. The snapshot is the rules slice of 22: a change that adds a rule operation or an issue
    code updates it in its own contract change (C-6.1)."""
    assert _SCHEMAS["RuleValidationIssue"]["properties"]["code"]["enum"] == _ISSUE_CODES
    assert {i for i, op in _OPS.items() if "rules" in op.get("tags", [])} == _RULE_OPERATIONS
    carried = {code: (e["status"], e["retryable"]) for code, e in _REGISTRY.items()}
    assert carried["conflict"] == (409, False) and carried["rate_limited"] == (429, True)
    assert carried["rule_ir_invalid"] == (422, False)
    assert {code for code in _REGISTRY if code.startswith("rule")} == {"rule_ir_invalid"}
    assert not {"limit_reached", "max_length"} & set(_REGISTRY)  # `errors[].rule` values, no codes


def test_the_refusal_record_budget_is_named_with_its_default_and_its_exclusions() -> None:
    info = text(SPEC["info"]["description"])
    head = info.index("### Rule authoring refusal records (E35, #4834)")
    assert info.index("### View-as session") < head < info.index("### RBAC")
    section = info[head : info.index(" ### ", head + 1)]
    budget = _number(r"`rules_refusal_budget_per_hour` \(default (\d+)\)", section)
    assert budget == 120
    for phrase in (
        "(`rules.scope_denied`, and `rules.arm` for a refused mode change)",
        "a budget per acting user, across all of the user's sessions",
        "records in a rolling hour, the same for every role, the Owner included",
        "(`suppressed_summary`, outside the cap), so a refusal is never dropped",
        "turns the refusal into `503 audit_unavailable`, and nothing changes",
        "A refusal of a limit writes no record and is counted",
        "A rule action's own denial while the rule runs and the boot-time check of the system "
        "rules are never held to the cap",
    ):
        assert phrase in section, phrase
    records = text(_RAW_24.split("\n### 15.5 ", 1)[1].split("\n### 15.6 ", 1)[0])
    sentence = records.split("The `rules.scope_denied` and `rules.arm` records of a refused", 1)[1]
    sentence = sentence.split(" never held to it.", 1)[0]
    assert f"`rules_refusal_budget_per_hour` per acting user (default {budget} in a rolling" in (
        sentence
    )
    assert "one `suppressed_summary` record per user and window, outside the cap" in sentence
    assert "`rule.system_rule_tampered` record" in sentence
    title = r"^### 19\.(\d+) 2026-10-30 — 22 `/rules`, §15\.5: the authoring limits"
    heading = re.search(title, _RAW_24, re.MULTILINE)
    assert heading is not None
    entry = text(_RAW_24[heading.start() :].split("\n### ", 1)[0])
    assert f"This number follows `main`'s last entry, §19.{int(heading.group(1)) - 1};" in entry
    assert f"`rules_refusal_budget_per_hour` (default {budget})" in entry
