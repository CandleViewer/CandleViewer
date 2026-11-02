"""Contract (#5479, E42-S05 AC7's server half), contract first (C-6.1): the armed-rule dependents of
a flag. `22` states `GET /admin/feature-flags/{flagKey}/dependents` (`listFeatureFlagDependents`)
and the write's `acknowledged_dependents` (pinned in `test_admin_feature_flags_contract.py`); `24`
section 16.4 states what a dependent is, the table, the check's place and the bounds, and section
19.92 logs the change. As built, no node of the rule IR reads a flag and the code the table's rows
describe is not on `main`, so every list is `[]` and no write needs an acknowledgement until a row
lands with its reading code. Each decision is pinned by whole sentences, so a mutated word fails."""

from __future__ import annotations

import re
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from candleviewer.api._generated import openapi_models as api
from tests.contract._admin_support import (
    OWNER_ONLY,
    ROOT,
    SPEC,
    example_cases,
    text,
    validate_example,
)
from tests.contract.rbac.rbac_harness import MATRIX_PATH

_PATH = "/admin/feature-flags/{flagKey}/dependents"
_OP: dict[str, Any] = SPEC["paths"][_PATH]["get"]
_SCHEMAS: dict[str, Any] = SPEC["components"]["schemas"]
_DEPENDENTS: dict[str, Any] = _SCHEMAS["FeatureFlagDependents"]
_DEPENDENT: dict[str, Any] = _SCHEMAS["FeatureFlagDependent"]
_PROSE = text(_OP["description"])
_INTERNAL = (ROOT / "docs/plan/24-internal-schemas.md").read_text(encoding="utf-8")
_DATABASE = (ROOT / "docs/plan/21-database-schema.md").read_text(encoding="utf-8")
_EXAMPLES: dict[str, Any] = _OP["responses"]["200"]["content"]["application/json"]["examples"]
_REF = "#/components/schemas/"


def test_the_read_holds_the_permission_of_the_write_it_precedes_and_changes_nothing() -> None:
    put = SPEC["paths"]["/admin/feature-flags/{flagKey}"]["put"]
    assert (_OP["operationId"], _OP["tags"]) == ("listFeatureFlagDependents", ["admin"])
    assert _OP["x-rbac"] == {"permissions": ["flags:write"], "scope": "none"}
    assert _OP["x-rbac"] == put["x-rbac"]
    assert not {"requestBody", "parameters", "x-idempotency"} & set(_OP)  # a read: no CSRF pair
    assert "step-up" not in _PROSE.lower()  # the write it precedes is gated, never the read


def test_the_flag_key_is_the_writes_path_parameter() -> None:
    put_item = SPEC["paths"]["/admin/feature-flags/{flagKey}"]
    assert SPEC["paths"][_PATH]["parameters"] == put_item["parameters"]


def test_the_read_answers_exactly_the_planned_statuses_through_the_shared_responses() -> None:
    assert set(_OP["responses"]) == {"200", "401", "403", "404", "503"}
    shared = {
        "401": "Unauthorized",
        "403": "Forbidden",
        "404": "NotFound",
        "503": "ServiceUnavailable",
    }
    for status, name in shared.items():
        assert _OP["responses"][status] == {"$ref": f"#/components/responses/{name}"}
    ok = _OP["responses"]["200"]["content"]["application/json"]
    assert ok["schema"] == {"$ref": _REF + "FeatureFlagDependents"}
    assert set(ok["examples"]) == {"twoDependents", "none"}


_CASES = example_cases([(_PATH, "get")])


@pytest.mark.parametrize(("case", "pointer", "value"), _CASES, ids=[case[0] for case in _CASES])
def test_every_example_validates_against_its_response_schema(
    case: str, pointer: str, value: Any
) -> None:
    validate_example(pointer, value)


@pytest.mark.parametrize("name", ["twoDependents", "none"])
def test_the_200_examples_round_trip_through_the_generated_model(name: str) -> None:
    value = _EXAMPLES[name]["value"]
    model = api.FeatureFlagDependents.model_validate(value)
    assert model.model_dump(mode="json", exclude_unset=True) == value
    assert (value["items"] == []) is (name == "none")  # an empty list needs no acknowledgement


def test_the_list_is_closed_unpaged_and_bounded_at_the_armed_rule_cap() -> None:
    props = _DEPENDENTS["properties"]
    assert (_DEPENDENTS["additionalProperties"], _DEPENDENTS["required"]) == (
        False,
        ["flag_key", "items", "truncated"],
    )
    assert set(props) == {"flag_key", "items", "truncated"}  # no cursor and no meta: not paged
    assert props["items"] == {
        "type": "array",
        "maxItems": 200,
        "items": {"$ref": _REF + "FeatureFlagDependent"},
    }
    assert props["truncated"]["type"] == "boolean"
    path_key = SPEC["paths"][_PATH]["parameters"][0]["schema"]["maxLength"]
    assert props["flag_key"] == {"type": "string", "maxLength": path_key}
    assert "max_armed_rules: int = 200" in _INTERNAL  # `24` 16.1: the cap that the bound follows
    assert set(api.FeatureFlagDependents.model_fields) == set(props)


def test_a_dependent_names_its_rule_version_scope_and_the_action_nodes_that_read_the_flag() -> None:
    props = _DEPENDENT["properties"]
    required = ["rule_id", "name", "version", "owner_user_id", "scope", "reads"]
    assert (_DEPENDENT["additionalProperties"], _DEPENDENT["required"]) == (False, required)
    assert set(props) == {*required, "unreadable"}
    assert props["unreadable"]["type"] == "boolean"
    rule_input = _SCHEMAS["RuleInput"]["properties"]
    assert props["name"]["maxLength"] == rule_input["name"]["maxLength"] == 120
    assert (props["version"]["type"], props["version"]["minimum"]) == ("integer", 1)
    scope = props["scope"]
    assert (scope["additionalProperties"], scope["required"]) == (
        False,
        ["level", "account_ids", "environments"],
    )
    assert scope["properties"]["level"] == {"$ref": _REF + "RuleScope"}
    assert scope["properties"]["environments"]["items"] == {"$ref": _REF + "Environment"}
    reads = props["reads"]
    assert reads["maxItems"] == _SCHEMAS["RuleIr"]["properties"]["actions"]["maxItems"] == 10
    read = reads["items"]
    assert (read["additionalProperties"], read["required"]) == (
        False,
        ["node_id", "node_kind", "action_type"],
    )
    assert read["properties"]["node_kind"]["enum"] == ["action"]  # no other node reads a flag
    assert set(api.FeatureFlagDependent.model_fields) == set(props)


def test_the_generated_models_refuse_what_the_schemas_close_and_bound() -> None:
    item = _EXAMPLES["twoDependents"]["value"]["items"][0]
    with pytest.raises(ValidationError):
        api.FeatureFlagDependent.model_validate({**item, "bindings": []})
    with pytest.raises(ValidationError):
        api.FeatureFlagDependent.model_validate({**item, "reads": [item["reads"][0]] * 11})
    with pytest.raises(ValidationError):
        api.FeatureFlagDependent.model_validate(
            {**item, "reads": [{**item["reads"][0], "node_kind": "condition"}]}
        )
    over = {"flag_key": "maintenance.mode", "truncated": True, "items": [item] * 201}
    with pytest.raises(ValidationError):
        api.FeatureFlagDependents.model_validate(over)


def test_an_unreadable_dependent_is_listed_with_no_reads_and_the_marker() -> None:
    item = {**_EXAMPLES["twoDependents"]["value"]["items"][0], "reads": [], "unreadable": True}
    assert api.FeatureFlagDependent.model_validate(item).unreadable is True
    assert "`unreadable: true`" in _PROSE


#: The read's decisions, each a whole sentence or run of sentences of its description.
_READ_ROWS = (
    "A rule depends on a flag through the code that runs its actions: no node of the rule IR "
    "names a flag, so `reads` holds action nodes only (`node_kind: action`).",
    "a flag it does not name has no dependents: its list is empty. That table holds no row until "
    "the code that reads a flag for a rule's action is built (E35's executor checks and order "
    "handlers are not built yet), so until then every list is `[]` and no write needs an "
    "acknowledgement.",
    "A rule is listed while its stored `mode` is `armed` and it is not deleted "
    "(`21-database-schema.md` 3.4.1), whatever B9 state it is in. The stored row decides, never "
    "the IR's own `mode` member and never an interpreter (C-2.21), so a `simulate` or `disabled` "
    "rule is never listed. Only the rule's active version counts: a newer saved version of an "
    "armed rule is read once it becomes the active one.",
    "A rule whose active version's actions cannot be read counts as reading every flag the table "
    "names: it is listed with `unreadable: true` and no `reads`.",
    "The items are ordered by `rule_id` and are not paged, since the write needs the whole set at "
    "once. There are at most 200, the cap of armed rules (`24-internal-schemas.md` 16.1); while "
    "E35 does not hold that cap at arming, a set above it answers its first 200 with "
    "`truncated: true`, and `setFeatureFlag` refuses the write (`dependents_over_bound`).",
    "The read changes nothing and spends nothing: no rule is disarmed and nothing is queued.",
    "It holds `flags:write`, the permission of the write it precedes, which the Owner alone "
    "holds: a Manager, a Viewer and a caller holding `flags:read` only get `403` and learn no "
    "rule id, and a view-as session reads as its target, so it gets `403` too.",
    "The audited admin guard records `admin.area_entered` for the call, with outcome `denied` for "
    "a refused caller, and nothing else is recorded (`503 audit_unavailable` when the guard "
    "cannot write it).",
    "A rule's `name` is user text: it goes to this caller alone and to no audit record or log "
    "(C-12.6).",
    "An unknown `flagKey`, or one the caller's role cannot see, is `404 not_found`, as the write "
    "answers it, and a read of the rules store that fails or exceeds its bound is "
    "`503 store_unavailable`.",
)


@pytest.mark.parametrize("sentence", _READ_ROWS)
def test_every_decision_of_the_read_is_pinned(sentence: str) -> None:
    assert sentence in _PROSE


def test_the_matrix_row_is_the_owners_alone() -> None:
    matrix = yaml.safe_load(MATRIX_PATH.read_text(encoding="utf-8"))
    row = matrix["operations"][f"GET {_PATH}"]
    assert (row["permissions"], row["scope"], row["public"]) == (["flags:write"], "none", False)
    assert row["outcomes"] == OWNER_ONLY  # a Manager, a Viewer and a `flags:read` holder: 403


def _section_16_4() -> str:
    heading = "### 16.4 Armed-rule dependents of a flag\n"
    assert _INTERNAL.count(heading) == 1
    tail = _INTERNAL.split(heading, 1)[1]
    assert _INTERNAL.index("### 16.3 ") < _INTERNAL.index(heading) < _INTERNAL.index("\n## 17. ")
    return " ".join(tail.split("\n---\n", 1)[0].split())


_SECTION = _section_16_4()
#: Section 16.4's decisions, one run of sentences each.
_SECTION_ROWS = (
    "`listFeatureFlagDependents` (`GET /admin/feature-flags/{flagKey}/dependents`) lists the "
    "dependents, and `setFeatureFlag` refuses a write whose `acknowledged_dependents` is not "
    "exactly their ids.",
    "No node of the rule IR reads a flag (§11.2): a condition reads metrics (`MetricRef`), a "
    "trigger names an event and an action names an operation. A rule depends on a flag only "
    "through the code that runs its actions, so the dependents are action nodes.",
    "A newer saved version of an armed rule counts once it is the active one.",
    "It is derived from the executor's own tables and never copied by hand, and each row is "
    "pinned by a test that drives the code reading that flag, so a new flag read on the action "
    "path fails a test until its row exists. The rows below are proposed until the code that "
    "reads each flag has merged, and a row lands with that code.",
    "No row names `trading.live_enabled` (rule actions run on demo and testnet only, and check "
    "4's `live_gate` refuses a live account first) or an `algo.*` flag (no handler reads one "
    "before E33's handlers land), and none names a condition or a trigger. A flag without a row "
    "has no dependents.",
    "An armed rule whose active version's actions cannot be read counts as reading every flag "
    "the table names (fail closed, as `PostgresArmedRules` counts an unreadable scope as "
    "covering every account), and is listed with `unreadable: true`.",
    "is E35's open stack (#5367, #5406, #5423 and #5472) and is not on `main`. The table "
    "therefore holds no row: every list is `[]` and no write needs an acknowledgement until a "
    "row lands with its reading code.",
    "and nothing else does: there is no table of dependents and no migration, nothing on the "
    "arm path, the evaluator, the runner or the executor, no call from a tick or a fire, and no "
    "interpreter is queried (C-2.21).",
    "`setFeatureFlag` reads the live set under the flag's row lock, as the first step there, "
    "after every other validation (`unknown_user` included) and before the step-up gate, so "
    "that a stale list never spends a step-up. It is awaited inside the write, before the "
    "commit, and is never an interpreter.",
    "`acknowledged_dependents` must hold exactly the live set's rule ids, compared as sets: a "
    "missing or an unexpected id refuses the write (`422 validation_failed`, rule "
    "`dependents_unacknowledged`, with the live list and the difference in the body), and an "
    "empty live set needs none.",
    "The check judges every write, of every flag and in either direction (a rollout flag turned "
    "on lets an armed rule reach the OMS, a risk-increasing capability, §16.2), a "
    "kill-switch-class flag's engaged value included, for every role: no role, flag or setting "
    "turns it off (C-4.14), and it reads no flag or setting.",
    "ids only, never a rule's name (user text, C-12.6).",
    "What refuses a rule's action is the executor's synchronous check at the moment of the "
    "action (§11.5 checks 2 and 3, C-2.21), which reads the flag whatever any list said, so a "
    "stale acknowledgement weakens no safety.",
    "an arm or a disarm that commits between the check's read and the flag's commit, inside the "
    "store write's bound (`write_bound_s`, 5 s at most), is a named residual, and each event "
    "keeps its own record (`rules.arm` or `rules.disarm`, and `flags.change`).",
    "a console engage can be answered `422` (a stale list) or `503` (the rules store does not "
    "answer), while the code-free emergency engage, `POST /trading/kill-switch`, with its "
    "`disarm_rules` option (§11.7), never waits on a list or on the rules store (C-4.14).",
    "While E35 does not hold that cap at arming, a live set above it answers the read's first "
    "200 by `rule_id` with `truncated: true` and refuses the write (`422`, rule "
    "`dependents_over_bound`): no list is cut without saying so.",
    "the write route's body cap rises from 16 KiB to 32 KiB, for 200 ids beside 200 overrides. "
    "The 200 ids and the 32 KiB are proposed, interim until the Owner ratifies them (#2701). A "
    "read of the rules store that fails or exceeds its bound is `503 store_unavailable`, with "
    "nothing written.",
)


@pytest.mark.parametrize("sentence", _SECTION_ROWS)
def test_every_decision_of_section_16_4_is_pinned(sentence: str) -> None:
    assert sentence in _SECTION


def test_the_table_holds_the_proposed_rows_and_names_only_flags_the_catalogue_lists() -> None:
    rows = {
        cells[0]: cells[1]
        for line in _INTERNAL.split("### 16.4 ", 1)[1].split("\n---\n", 1)[0].splitlines()
        if line.startswith("| `")
        for cells in [[cell.strip() for cell in line.strip("|").split("|")]]
    }
    assert rows == {
        "`rules.enabled`": "every type",
        "`killswitch.order_entry`": "every type",
        "`rules.oms_actions`": "every type whose handler reaches past the engine",
        "`trading.oms_enabled` and `maintenance.mode`": (
            "the entries: the types that open or add to a position"
        ),
    }
    catalogue = _DATABASE.split("### 10.7 Feature flags", 1)[1].split("###", 1)[0]
    listed = set(re.findall(r"^\| `([a-z_.]+)`", catalogue, re.MULTILINE))
    named = set(re.findall(r"`([a-z]+\.[a-z_]+)`", " ".join(rows)))
    assert named and named <= listed, sorted(named - listed)
    for absent in ("trading.live_enabled", "algo.twap"):  # no row: see `_SECTION_ROWS`
        assert absent not in " ".join(rows)


def test_section_19_92_logs_the_contract_first_change_without_a_new_code_or_table() -> None:
    title = (
        r"^### 19\.92 2026-11-02 — §16\.4 and 22 `setFeatureFlag`, `listFeatureFlagDependents`: "
    )
    title += r"the armed-rule dependents of a flag, contract first \(#5479\)$"
    heads = re.findall(title, _INTERNAL, re.MULTILINE)
    assert len(heads) == 1
    entry = text(_INTERNAL.split("\n### 19.92 ", 1)[1])
    assert (
        "This is the number the orchestrator assigned on 2026-11-02 (13:45Z); it keeps it" in entry
    )
    assert "contract first (C-6.1), in the first of the ticket's three PRs" in entry
    assert (
        "No new `x-error-codes` entry, audit action, WS frame, table, migration, chart or" in entry
    )
    assert "the server half follows in #5479's second and third PRs." in entry
    numbers = [int(n) for n in re.findall(r"^### 19\.(\d+) ", _INTERNAL, re.MULTILINE)]
    assert numbers == sorted(set(numbers)) and numbers.count(92) == 1  # unique and increasing
