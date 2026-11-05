"""#5879 (E35 hardening), contract first (C-6.1): the validation answers are bounded in 22.

`validateRule`'s `RuleValidationResult` and `compileRule`'s `200` list at most 50 issues
(`maxItems`), and each answer, `compileRule`'s `422 rule_ir_invalid` included (`Problem`), counts
every issue found in `issues_total`; a round trip lists at most 50 differences and counts them in
`diff_total`. Both operations state the bound ("Bounded answer") and 24 §19.140 logs it. Read
from the spec, never a copy (AGENTS.md section 6 rule 12).
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from candleviewer.rules.issues import MAX_RETURNED_ISSUES
from tests.contract._admin_support import ROOT, SPEC, text, validate_example
from tests.rules.test_rule_validation_answer_bound import (
    COMPILE,
    UNKNOWN,
    _any_of,
    _at_the_bounds,
    _differing,
    _form,
    _ir,
    _with_conditions,
)
from tests.rules.test_validator_endpoints import _client

_SCHEMAS: dict[str, Any] = SPEC["components"]["schemas"]
_VALIDATE: dict[str, Any] = SPEC["paths"]["/rules/validate"]["post"]
_COMPILE: dict[str, Any] = SPEC["paths"]["/rules/{ruleId}/compile"]["post"]
_JSON = "application/json"
_RESULT: dict[str, Any] = _SCHEMAS["RuleValidationResult"]
_COMPILED: dict[str, Any] = _COMPILE["responses"]["200"]["content"][_JSON]["schema"]
_ROUND_TRIP: dict[str, Any] = _COMPILED["properties"]["round_trip"]
_ISSUE = {"$ref": "#/components/schemas/RuleValidationIssue"}
_COMPILE_PATH = "~1rules~1{ruleId}~1compile"
_JSON_PART = "application~1json/schema"
_RAW_24 = (ROOT / "docs/plan/24-internal-schemas.md").read_text(encoding="utf-8")
#: The bound 22 states on `RuleValidationResult.errors`; every other statement of it must agree.
BOUND: int = _RESULT["properties"]["errors"]["maxItems"]


def _bounded_answer(operation: dict[str, Any]) -> str:
    """The operation's "Bounded answer" paragraph, whitespace-normalised."""
    return text(operation["description"]).split("**Bounded answer (E35, #5879).**", 1)[1]


def test_each_issue_list_of_the_two_answers_holds_at_most_the_bound() -> None:
    lists = [_RESULT["properties"][name] for name in ("errors", "warnings")]
    lists.append(_COMPILED["properties"]["issues"])
    assert BOUND == 50
    assert [(entry["type"], entry["maxItems"], entry["items"]) for entry in lists] == [
        ("array", BOUND, _ISSUE)
    ] * 3
    assert _ROUND_TRIP["properties"]["diff"]["maxItems"] == BOUND


def test_a_round_trip_counts_every_difference_in_an_optional_diff_total() -> None:
    total = _ROUND_TRIP["properties"]["diff_total"]
    assert (total["type"], total["minimum"]) == ("integer", 0)
    assert _ROUND_TRIP["required"] == ["match", "diff"]  # a new optional member (C-6.3)
    assert text(total["description"]).endswith(f"of which `diff` lists the first {BOUND}.")


@pytest.mark.parametrize(
    "schema", [_RESULT, _COMPILED, _SCHEMAS["Problem"]], ids=["validate", "compile", "problem"]
)
def test_each_answer_counts_every_issue_in_an_optional_issues_total(schema: dict[str, Any]) -> None:
    total = schema["properties"]["issues_total"]
    assert (total["type"], total["minimum"]) == ("integer", 0)
    assert "issues_total" not in schema.get("required", [])  # a new optional member (C-6.3)


def test_the_two_operations_state_the_bound_and_what_reads_every_issue() -> None:
    validate, compile_ = _bounded_answer(_VALIDATE), _bounded_answer(_COMPILE)
    assert f"The answer lists at most {BOUND} issues, the errors before the warnings" in validate
    assert "`issues_total` counts every error and warning found" in validate
    assert "`valid` and `blocks_arming` read them all, listed or not" in validate
    unexplained = "can be true while no listed issue explains it"
    assert f"so `blocks_arming` {unexplained} (a safety-class warning found after" in validate
    assert "and that holds more entries is one `schema_error` at the list" in validate
    assert "within its bound it answers its first refused entry and reads none after it" in validate
    first = "a metric's `params` and an object's unknown members each answer one issue, their first"
    assert f"`set_values`), {first} refused entry" in validate
    assert "past it a call is `429 rate_limited` with `Retry-After`, as past the bucket" in validate
    assert f"`issues` lists at most {BOUND} issues, the errors before the warnings" in compile_
    assert f"a `422 rule_ir_invalid` lists at most {BOUND} `errors`" in compile_
    assert "`issues_total` counts every issue found, as the `422`'s `detail` does" in compile_
    assert f"`blocks_arming` reads them all, so it {unexplained}" in compile_
    assert f"`round_trip.diff` lists at most {BOUND} of the leaves where the two" in compile_
    assert "and `diff_total` counts every one; `match` and the divergence count read" in compile_
    assert "a large check runs on the same check worker, with the same `429` past it" in compile_
    validated = text(_RESULT["properties"]["issues_total"]["description"])
    assert f"`errors` and `warnings` list at most {BOUND} of them together" in validated
    compiled = text(_COMPILED["properties"]["issues_total"]["description"])
    assert compiled == f"Every issue found, of which `issues` lists the first {BOUND}."
    problem = text(_SCHEMAS["Problem"]["properties"]["issues_total"]["description"])
    assert problem.startswith("`rule_ir_invalid` from `compileRule` only")
    assert f"of which `errors` lists the first {BOUND}" in problem


def test_the_validate_examples_count_their_issues() -> None:
    examples = _VALIDATE["responses"]["200"]["content"][_JSON]["examples"]
    for name, example in examples.items():
        value = example["value"]
        validate_example("/components/schemas/RuleValidationResult", value)
        assert value["issues_total"] == len(value["errors"]) + len(value["warnings"]), name


def test_24_logs_the_bound_under_its_assigned_number() -> None:
    title = (
        r"^### 19\.140 2026-11-04 — 22 `validateRule`, `compileRule`: the validation answers are "
        r"bounded, contract first \(E35, #5879\)$"
    )
    assert re.search(title, _RAW_24, re.MULTILINE)
    entry = text(_RAW_24.split("### 19.140 ", 1)[1].split("\n### ", 1)[0])
    assigned = "This is the number the orchestrator assigned on 2026-11-05 (03:08Z); it keeps it"
    assert f"{assigned} through its rebases." in entry
    assert f"`maxItems: {BOUND}` on `errors` and on `warnings`" in entry
    assert f"`round_trip.diff` lists at most {BOUND} of the leaves" in entry
    assert "its first error names the list (`too_long`, at the list) where it named" in entry
    assert "the first entry; its status, shape and codes are unchanged" in entry
    assert "Which documents are valid does not change" in entry
    assert "Every list of `RuleIr` stops at its first refused entry, answered at the place" in entry
    bounded = "the three it bounds (`actions`, a boolean node's `children`, an arithmetic node's"
    assert f"{bounded} `operands`), within their bound, and the four it leaves unbounded" in entry
    assert "These are refusals of the schema, entries no editor produces; the validator's" in entry
    assert "one per action or condition at fault, are unchanged" in entry
    assert "The condition-node bound is unchanged: it counts objects, and the first" in entry
    threshold = "more values than a fixed threshold, counted as `check_bounds` counts a document's"
    assert f"{threshold} and never by its bytes, runs on the server's one check worker" in entry


def test_the_server_lists_no_more_issues_than_22_states() -> None:
    assert MAX_RETURNED_ISSUES == BOUND


def test_validate_answers_past_the_bound_as_22_states() -> None:
    unknown = _with_conditions(_any_of("u", UNKNOWN, 30), _any_of("v", UNKNOWN, 30))
    for doc in (_at_the_bounds(_ir()), unknown):
        body = _client().post("/rules/validate", json={"ir": doc}).json()
        validate_example("/components/schemas/RuleValidationResult", body)
        assert body["issues_total"] > len(body["errors"]) + len(body["warnings"]) == BOUND


def test_compile_answers_past_the_bound_as_22_states() -> None:
    unknown = _form(_with_conditions(_any_of("u", UNKNOWN, 30), _any_of("v", UNKNOWN, 30)))
    compiled = _client().post(COMPILE, json={"editor": "form", "model": unknown}).json()
    issues = {name: value for name, value in compiled.items() if name != "ir"}
    validate_example(f"/paths/{_COMPILE_PATH}/post/responses/200/content/{_JSON_PART}", issues)
    assert compiled["issues_total"] > len(compiled["issues"]) == BOUND
    at_bounds = {"editor": "form", "model": _at_the_bounds(_form(_ir()))}
    refused = _client().post(COMPILE, json=at_bounds).json()
    validate_example("/components/schemas/Problem", refused)
    assert refused["issues_total"] > len(refused["errors"]) == BOUND


def test_a_round_trip_answers_past_the_bound_as_22_states() -> None:
    trip = _client().post(COMPILE, json=_differing(60)).json()["round_trip"]
    pointer = f"/paths/{_COMPILE_PATH}/post/responses/200/content/{_JSON_PART}"
    validate_example(pointer, {"round_trip": trip})
    assert trip["diff_total"] > len(trip["diff"]) == BOUND
