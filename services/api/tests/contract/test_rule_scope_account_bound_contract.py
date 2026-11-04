"""#5691 (E35, C-12.4): a rule's scope lists at most 100 accounts and 3 environments, each once.

22 states the bound and the uniqueness on `RuleIrScope.account_ids` and `environments` (contract
first, C-6.1), and how each operation that reads a scope answers a list past a bound or one naming
an entry twice: a save and `compileRule` with `422 rule_ir_invalid`, `validateRule` with `200` and
`valid: false`. 24 states the same in §11.2, §11.3 and its §19 entry. Read from the spec, never
a copy (AGENTS.md section 6 rule 12). The tests at the end tie the code to it: the model's
constants, the schema the model publishes and the contract model generated from 22.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from candleviewer.api._generated.openapi_models import RuleIrScope
from candleviewer.rules.ir import to_json_schema
from tests.contract._admin_support import ROOT, SPEC, text

#: The ruled bound (#5691, BQ-1), held here as a number of its own.
BOUND = 100
_SCHEMAS: dict[str, Any] = SPEC["components"]["schemas"]
_OPS: dict[str, dict[str, Any]] = {
    op["operationId"]: op
    for item in SPEC["paths"].values()
    for method, op in item.items()
    if method in {"get", "put", "post", "patch", "delete"}
}
_RAW_24 = (ROOT / "docs/plan/24-internal-schemas.md").read_text(encoding="utf-8")
_ITEM = {"type": "string", "format": "uuid"}
_RULE_IR_INVALID = {"$ref": "#/components/responses/RuleIrInvalid"}
#: The ruled bound on a scope's environments (the orchestrator's addition to #5691).
ENVIRONMENTS = 3
_ENVIRONMENT = {"$ref": "#/components/schemas/Environment"}


def _prose(operation_id: str) -> str:
    return text(_OPS[operation_id]["description"])


def _scope_prose() -> str:
    return text(_SCHEMAS["RuleIrScope"]["description"])


def _entry() -> tuple[str, str]:
    """24's §19 entry for #5691, found by the issue in its heading, never by its number: the
    heading and the entry's text."""
    heading = r"^### 19\.\d+ \d{4}-\d{2}-\d{2} — .*\(E35, #5691\)$"
    found = re.search(heading, _RAW_24, re.MULTILINE)
    assert found is not None, "24 section 19 holds no entry for #5691"
    return found.group(0), text(_RAW_24.split(found.group(0), 1)[1].split("\n### ", 1)[0])


def _section(start: str, end: str) -> str:
    return _RAW_24.split(start, 1)[1].split(end, 1)[0]


def _ir_json_scope_member(name: str) -> dict[str, Any]:
    """§11.3's abbreviated JSON Schema of the IR: the member `name` of its scope."""
    block = _section("### 11.3 JSON Schema", "\n### ").split("```json\n", 1)[1].split("\n```")[0]
    member: dict[str, Any] = json.loads(block)["properties"]["scope"]["properties"][name]
    return member


def test_rule_ir_scope_account_ids_states_its_bound_and_uniqueness() -> None:
    ids = _SCHEMAS["RuleIrScope"]["properties"]["account_ids"]
    shape = {"type": "array", "default": [], "items": _ITEM}
    assert ids == {**shape, "maxItems": BOUND, "uniqueItems": True}


def test_rule_ir_scope_environments_states_its_bound_and_uniqueness() -> None:
    environments = _SCHEMAS["RuleIrScope"]["properties"]["environments"]
    shape = {"type": "array", "default": ["demo"], "items": _ENVIRONMENT}
    assert environments == {**shape, "maxItems": ENVIRONMENTS, "uniqueItems": True}
    assert len(_SCHEMAS["Environment"]["enum"]) == ENVIRONMENTS  # each one once, at most


def test_rule_ir_scope_and_the_save_operations_state_the_refusal() -> None:
    scope = _scope_prose()
    for kept in (
        "A save sends the rule's accounts in `account_ids` and in no member outside `ir`"
        " (`RuleInput`), and the version it stores echoes exactly them",
        "An empty list means every account the rule's owner holds a grant on when the rule fires.",
    ):
        assert kept in scope, kept
    for stated in (
        f"A scope lists at most {BOUND} accounts, each once: a longer list, or one that names an"
        " account twice, is refused.",
        "Two entries are one account when they read as the same UUID, whatever their spelling"
        " (`uniqueItems` compares text, so the server's check is the stricter one).",
        "A save (`createRule`, `updateRule`) answers `422 rule_ir_invalid` with `path`"
        " `/scope/account_ids`, `compileRule` answers `422 rule_ir_invalid` with `errors[].field`"
        " `scope.account_ids`, and `validateRule` answers `200` with `valid: false` and a"
        " `schema_error` at `scope.account_ids`.",
        "The refusal is decided on the list alone, before the scope check and for every role, so"
        " it names no account and writes no audit record.",
        f"A scope names at most {ENVIRONMENTS} environments, each once, and a longer list or a"
        " repeat there is refused in the same way, before the scope check, at"
        " `/scope/environments` (`scope.environments` on `validateRule` and `compileRule`).",
    ):
        assert stated in scope, stated
    create = _prose("createRule")
    paragraph = (
        f"**A rule's account list (E35, #5691).** `ir.scope.account_ids` holds at most {BOUND}"
        " accounts, each once (`RuleIrScope`): a list past the bound, or one that names an"
        " account twice, is refused `422 rule_ir_invalid` (`path` `/scope/account_ids`) before"
        " the scope check, for every role, with no audit record, and nothing is stored. A list"
        " within the bound then meets the scope check, each listed account against the saver's"
        " grants."
    )
    assert paragraph in create
    before, after = "(E35, #4835).**", "**Limits on what a save holds (E35, #4834).**"
    assert create.index(before) < create.index(paragraph) < create.index(after)
    assert "The body is held to `createRule`'s rule for accounts and members" in _prose(
        "updateRule"
    )
    assert (
        "A scope past the account-list bound of `RuleIrScope`, or naming an account twice, is"
        " `200` with `valid: false` and one error, code `schema_error`, class `syntax`, path"
        " `scope.account_ids`." in _prose("validateRule")
    )
    assert (
        "A model whose scope is past the account-list bound of `RuleIrScope`, or names an account"
        " twice, is refused `422 rule_ir_invalid` (`errors[].field` `scope.account_ids`)."
        in _prose("compileRule")
    )
    for operation_id in ("createRule", "updateRule", "compileRule"):
        assert _OPS[operation_id]["responses"]["422"] == _RULE_IR_INVALID, operation_id


def test_the_24_entry_states_the_bound_and_the_c63_call() -> None:
    heading, entry = _entry()
    assert heading.endswith(
        "22 `RuleIrScope.account_ids` and `environments`, §11.2: a scope lists at most"
        f" {BOUND} accounts and {ENVIRONMENTS} environments, each once (E35, #5691)"
    )
    for stated in (
        f"22 `RuleIrScope.account_ids` gains `maxItems: {BOUND}` and `uniqueItems: true`",
        "Two entries are one account when they parse to the same UUID, whatever their spelling.",
        "The refusal is decided on the list alone, before the scope check and for every role, so"
        " it names no account and writes no audit record, and nothing is stored.",
        "takes the path every unreadable version takes (G-15): read-only, disarmed when armed,"
        " skipped by the evaluator, never clamped or edited",
        "There is no migration.",
        f"22 `RuleIrScope.environments` gains `maxItems: {ENVIRONMENTS}` and `uniqueItems: true`",
        "a repeat or a longer list is refused `422 rule_ir_invalid` at `/scope/environments`",
        "decided before the scope check, so the refusal writes no record. A stored scope that"
        " breaks it takes the same quarantine path.",
        "**Breaking by the letter (C-6.3):** a list past the bound, or with a repeat, was accepted"
        " before and is now refused, so the request schema narrows.",
        "the squash title carries `!` and the body a `BREAKING CHANGE:` footer. No ADR is needed"
        " pre-GA, because no client sends a scope's account or environment list past these"
        " bounds",
    ):
        assert stated in entry, stated
    listing = _section("### 11.2 ", "### 11.3 ")
    line = "account_ids: tuple[AccountId, ...] = ()      # empty = all permitted accounts;"
    assert f"{line} at most {BOUND}, each once\n" in listing
    held = "# SAFE DEFAULT: demo only;"
    assert f'= ("demo",)   {held} at most {ENVIRONMENTS}, each once\n' in listing
    note = text(listing.split("> **Scope account list (E35, #5691).**", 1)[1].split("\n\n")[0])
    assert f"at most `MAX_SCOPE_ACCOUNTS` ({BOUND}) accounts, each once" in note
    assert "A longer list, or a repeat, is refused at save, validate and compile." in note
    assert f"at most `MAX_SCOPE_ENVIRONMENTS` ({ENVIRONMENTS}) environments, each once" in note
    env = _ir_json_scope_member("environments")
    assert (env["default"], env["maxItems"], env["uniqueItems"]) == (["demo"], ENVIRONMENTS, True)
    ids = _ir_json_scope_member("account_ids")
    assert ids == {"type": "array", "items": _ITEM, "maxItems": BOUND, "uniqueItems": True}


# ----- the code holds what 22 states ----------------------------------------------------------


def test_max_scope_accounts_is_the_bound_22_states() -> None:
    from candleviewer.rules.ir.models import MAX_SCOPE_ACCOUNTS

    stated = _SCHEMAS["RuleIrScope"]["properties"]["account_ids"]["maxItems"]
    assert MAX_SCOPE_ACCOUNTS == stated == BOUND
    assert f"A scope lists at most {MAX_SCOPE_ACCOUNTS} accounts, each once" in _scope_prose()
    held = f"holds at most {MAX_SCOPE_ACCOUNTS} accounts, each once (`RuleIrScope`)"
    assert held in _prose("createRule")


def test_max_scope_environments_is_the_bound_22_states() -> None:
    from candleviewer.rules.ir.models import MAX_SCOPE_ENVIRONMENTS

    stated = _SCHEMAS["RuleIrScope"]["properties"]["environments"]["maxItems"]
    assert MAX_SCOPE_ENVIRONMENTS == stated == ENVIRONMENTS
    assert f"A scope names at most {MAX_SCOPE_ENVIRONMENTS} environments" in _scope_prose()


def test_the_published_ir_schema_carries_the_same_bound() -> None:
    """The schema the model publishes (`rule-ir.json`, served at `GET /schemas/rule-ir.json`)
    holds 22's bounds, uniqueness, items and defaults on `RuleScope.account_ids` and
    `environments` (22 names its environments by `$ref`, the published schema inline)."""
    published = to_json_schema()["$defs"]["RuleScope"]["properties"]
    stated = _SCHEMAS["RuleIrScope"]["properties"]
    ids = published["account_ids"]
    assert {key: value for key, value in ids.items() if key != "title"} == stated["account_ids"]
    envs = {key: value for key, value in published["environments"].items() if key != "title"}
    assert envs.pop("items")["enum"] == _SCHEMAS["Environment"]["enum"]
    assert envs == {k: v for k, v in stated["environments"].items() if k != "items"}


def test_the_generated_python_model_carries_the_bound() -> None:
    """The contract model generated from 22 holds `maxItems`; uniqueness is the server model's own
    check (`RuleScope`), which compares UUIDs, not text."""
    ids = [str(uuid.UUID(int=0x1000 + i)) for i in range(BOUND + 1)]
    RuleIrScope.model_validate({"level": "account", "account_ids": ids[:BOUND]})
    for member, sent in (("account_ids", ids), ("environments", ["demo"] * (ENVIRONMENTS + 1))):
        with pytest.raises(ValidationError) as refused:
            RuleIrScope.model_validate({"level": "account", member: sent})
        assert [(e["type"], e["loc"]) for e in refused.value.errors()] == [("too_long", (member,))]
