"""#1864 (E40-T03 follow-up), contract first (C-6.1): the armed-alert cap in 22.

22 states the answer before the code that holds it: `createAlert`, `updateAlert` and
`setAlertEnabled` refuse a write that would arm a 201st alert with `409 conflict`,
`errors[].field` `enabled` and `errors[].rule` `limit_reached`, and a message that names the cap,
never a count (the stored-rule cap's pattern, 24 §19.62). Read from the spec, never a copy
(AGENTS.md section 6 rule 12).
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from tests.contract._admin_support import SPEC, example_cases, text, validate_example

_METHODS = frozenset({"get", "put", "post", "patch", "delete"})
_OPS: dict[str, dict[str, Any]] = {
    op["operationId"]: op
    for item in SPEC["paths"].values()
    for method, op in item.items()
    if method in _METHODS
}
_REGISTRY: dict[str, dict[str, Any]] = {e["code"]: e for e in SPEC["x-error-codes"]}
_PROBLEM = "application/problem+json"
#: Each arming operation -> its path and method in 22.
ARMING = {
    "createAlert": ("/alerts", "post"),
    "updateAlert": ("/alerts/{alertId}", "put"),
    "setAlertEnabled": ("/alerts/{alertId}/enabled", "put"),
}
EXAMPLE = "armedAlertCap"


def armed_cap() -> int:
    """The cap as `createAlert` states it."""
    prose = text(_OPS["createAlert"]["description"])
    found = re.search(r"A caller holds at most ([\d,]+) armed alerts", prose)
    assert found is not None
    return int(found.group(1).replace(",", ""))


def cap_example(operation_id: str) -> dict[str, Any]:
    response = _OPS[operation_id]["responses"]["409"]
    value: dict[str, Any] = response["content"][_PROBLEM]["examples"][EXAMPLE]["value"]
    return value


def test_create_alert_states_the_cap_of_200_armed_alerts_per_user() -> None:
    prose = text(_OPS["createAlert"]["description"])
    assert armed_cap() == 200
    assert "(live and `enabled`, snoozed or not), counted per user" in prose
    assert "refused `409 conflict` with `errors[].field` `enabled`, `errors[].rule`" in prose
    assert "a message that names the cap, never a count" in prose
    assert "and nothing is written" in prose
    never = "a create with `enabled` false, disabling, snoozing, deleting and a write to an alert"
    assert f"Only arming is refused: {never} that is already armed never are" in prose
    assert "interim until the Owner ratifies it as a `LIMIT_CAPS` row (#2701)" in prose


@pytest.mark.parametrize("operation_id", ["updateAlert", "setAlertEnabled"])
def test_the_arming_writes_name_the_cap_and_what_it_never_refuses(operation_id: str) -> None:
    prose = text(_OPS[operation_id]["description"])
    assert "armed-alert cap of `createAlert`" in prose
    assert "`limit_reached`" in prose and f"example `{EXAMPLE}`" in prose
    assert "already armed" in prose


@pytest.mark.parametrize("operation_id", sorted(ARMING))
def test_each_arming_write_declares_the_409_with_the_cap_example(operation_id: str) -> None:
    declared = _OPS[operation_id]["responses"]["409"]
    assert declared["content"][_PROBLEM]["schema"] == {"$ref": "#/components/schemas/Problem"}
    assert f"holds {armed_cap()} armed alerts" in text(declared["description"])
    example = cap_example(operation_id)
    registered = _REGISTRY["conflict"]
    assert (
        (example["status"], example["code"])
        == (registered["status"], "conflict")
        == (409, "conflict")
    )
    assert example["title"] == registered["title"]
    assert example["type"].endswith("/errors/conflict")
    assert [(e["field"], e["rule"]) for e in example["errors"]] == [("enabled", "limit_reached")]
    message = example["errors"][0]["message"]
    assert f"limit of {armed_cap()} armed alerts" in message and example["detail"] == message


def test_the_cap_examples_validate_against_the_problem_schema() -> None:
    seen: list[str] = []
    for case, pointer, value in example_cases(list(ARMING.values())):
        if case.endswith(f" {EXAMPLE}"):
            validate_example(pointer, value)
            seen.append(case)
    assert len(seen) == len(ARMING)


def test_the_cap_adds_no_error_code() -> None:
    """The pattern of the stored-rule cap: `conflict` + `limit_reached`, no new slug."""
    assert [
        c for c in _REGISTRY if re.search(r"alert.*(cap|limit)|armed_alert|alerts_armed", c)
    ] == []
