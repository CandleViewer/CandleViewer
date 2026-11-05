"""#5879 (E35 hardening): the validation answers are bounded.

`validateRule` and `compileRule` list at most `MAX_RETURNED_ISSUES` issues, the first ones found in
order, the errors before the warnings, beside `issues_total`, which counts every one (22 "Bounded
answer"); `valid` and `blocks_arming` read them all, and a round trip lists its first differences
beside `diff_total`. A list the IR bounds is refused on its length before its entries are read:
one issue for the list, in the words and at the place of the model's own bound. Within it, every
list stops at its first refused entry, as does a metric's `params`, and a model's unknown members
answer the first of them. A check whose body holds more than `OFF_LOOP_VALUES` values runs on the
one check worker, which admits at most `MAX_CHECKS_IN_FLIGHT` checks and answers `429` past them.
"""

from __future__ import annotations

import asyncio
import gc
import hashlib
import json
import statistics
import threading
import time
from asyncio import events
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import candleviewer.api.rules as rules_api
import candleviewer.rules.compiler.common as common
from candleviewer.api.rules import (
    MAX_CHECKS_IN_FLIGHT,
    OFF_LOOP_VALUES,
    CheckWorker,
    make_rules_router,
)
from candleviewer.rules.compiler import to_form_model, to_graph_model
from candleviewer.rules.compiler.common import (
    MAX_CONDITION_NODES,
    MAX_DEPTH,
    MAX_ITEMS,
    build_rule,
    count_condition_nodes,
    count_values,
)
from candleviewer.rules.ir import ir_hash, parse_ir_json
from candleviewer.rules.ir.models import (
    MAX_ACTIONS,
    MAX_ARITHMETIC_OPERANDS,
    MAX_BOOLEAN_CHILDREN,
    Rule,
)
from candleviewer.rules.ir.schema import render_schema
from candleviewer.rules.issues import MAX_RETURNED_ISSUES, Issue, RuleCompileError
from tests.rules._check_limiter import unthrottled
from tests.rules.test_validator_endpoints import (
    _P,
    FIX,
    REG,
    RULE_ID,
    _client,
    _jsonable,
    _notify,
)
from tests.unit.rules_ir.test_ir_hash_base_pins import IR_HASHES

COMPILE = f"/rules/{RULE_ID}/compile"
JSON = {"content-type": "application/json"}
#: A metric no vocabulary holds: each comparison of it is one `unknown_metric` error.
UNKNOWN = {"metric": "not_a_metric"}
#: The warnings of the fixture rule compiled from its form model, which carries every limit, the
#: cooldown included: `high_frequency` alone (the document as sent also has `guard_missing`).
FORM_WARNINGS = 1
#: The deepest condition node whose children `check_bounds` takes: node k of a chain from
#: `conditions` sits at depth 1 + 2k, its children at 3 + 2k.
DEEPEST = (MAX_DEPTH - 3) // 2


def _ir() -> dict[str, Any]:
    """The simple fixture rule as a document, its notification complete: a valid rule with two
    warnings (no cooldown on a price trigger, so `guard_missing`, and `high_frequency`)."""
    doc: dict[str, Any] = json.loads((FIX / "form_simple_0.json").read_text(encoding="utf-8"))
    doc["actions"] = [_notify()]
    return doc


def _node(children: list[Any]) -> dict[str, Any]:
    return {"node_id": "n", "op": "any_of", "children": children}


def _chain(levels: int) -> Any:
    """`levels` temporal nodes, each the next one's parent through `child`, each with three values
    the model refuses (`node_id`, `window_ms`, `min_count`); the deepest child does not parse."""
    node: Any = 0
    for _ in range(levels):
        node = {"node_id": 0, "op": "sustained_for", "child": node, "window_ms": 0, "min_count": 0}
    return node


def _failing(doc: dict[str, Any], values: int) -> dict[str, Any]:
    """`doc` at exactly `values` values, its conditions the densest and deepest failing content a
    document of that size holds within the bounds: every list stops at its first refused entry, so
    it is a chain of nodes as deep as the bounds take it, each refused field by field. What the
    chain leaves over pads `graph_layout`."""
    out: dict[str, Any] = json.loads(json.dumps(doc))
    out["graph_layout"] = {"pad": []}
    out["conditions"] = 0
    levels = min(MAX_DEPTH - 1, (values - count_values(out)) // 5)  # five values a node
    out["conditions"] = _chain(levels)
    out["graph_layout"]["pad"] = [0] * (values - count_values(out))
    common.check_bounds(out, "rule")  # within the bounds: the schema refuses it, not the bound
    return out


def _wide(doc: dict[str, Any], values: int) -> dict[str, Any]:
    """`doc` at `values` values, its conditions as many valid comparisons as fit, 32 to a group,
    within the node bound: the costliest valid content, each comparison checked as a rule's."""

    def tree(n: int) -> dict[str, Any]:
        row = {
            "op": "gt",
            "left": {"metric": "price", "params": {"n": 14}},
            "right": {"const": "1"},
        }
        rows = [{"node_id": f"c{i}", **row} for i in range(n)]
        width = MAX_BOOLEAN_CHILDREN
        groups = [_node(rows[i : i + width]) for i in range(0, n, width)]
        return {"node_id": "r", "op": "all_of", "children": groups}

    out: dict[str, Any] = json.loads(json.dumps(doc))
    out["graph_layout"] = {"pad": []}
    low, high = 1, MAX_CONDITION_NODES
    while low < high:  # the most comparisons that fit
        mid = (low + high + 1) // 2
        out["conditions"] = tree(mid)
        fits = count_values(out) <= values and count_condition_nodes(out) <= MAX_CONDITION_NODES
        low, high = (mid, high) if fits else (low, mid - 1)
    out["conditions"] = tree(low)
    out["graph_layout"]["pad"] = [0] * (values - count_values(out))
    return out


def _at_the_bounds(doc: dict[str, Any]) -> dict[str, Any]:
    """`doc` at exactly `MAX_ITEMS` values, the document bound `check_bounds` holds."""
    return _failing(doc, MAX_ITEMS)


def _refused(node: Any, path: str = "conditions") -> Iterator[str]:
    """Where the model refuses `_chain`'s content, in its order: a node's `node_id`, then its
    child's refusals, then its `window_ms` and `min_count`; the deepest child where it sits."""
    if not isinstance(node, dict):
        yield path
        return
    here = f"{path}.temporal"
    yield f"{here}.node_id"
    yield from _refused(node["child"], f"{here}.child")
    yield f"{here}.window_ms"
    yield f"{here}.min_count"


def _any_of(prefix: str, left: dict[str, Any], n: int) -> dict[str, Any]:
    """An `any_of` of `n` comparisons of `left` with a constant (a constant `left` is a warning,
    `unreachable_branch`; an unknown metric an error, `unknown_metric`)."""
    children = [
        {"node_id": f"{prefix}{i}", "op": "gt", "left": left, "right": {"const": i}}
        for i in range(n)
    ]
    return {"node_id": prefix, "op": "any_of", "children": children}


def _with_conditions(*groups: dict[str, Any]) -> dict[str, Any]:
    doc = _ir()
    doc["conditions"] = {"node_id": "root", "op": "all_of", "children": list(groups)}
    return doc


def _validate(doc: dict[str, Any]) -> dict[str, Any]:
    answer: dict[str, Any] = _client().post("/rules/validate", json={"ir": doc}).json()
    return answer


def test_build_rule_keeps_the_first_issues_in_order_and_counts_them_all() -> None:
    doc = _at_the_bounds(_ir())
    with pytest.raises(RuleCompileError) as refused:
        build_rule(doc)
    paths = list(_refused(doc["conditions"]))
    assert refused.value.total == len(paths)
    assert [i.path for i in refused.value.issues] == paths[:MAX_RETURNED_ISSUES]


def test_a_compile_error_without_a_total_counts_its_issues() -> None:
    issues = [Issue("$", "schema_error", "no", klass="syntax")] * 3
    assert RuleCompileError(issues).total == 3


def test_validate_answers_a_document_at_the_bounds_with_its_first_issues_and_their_total() -> None:
    doc = _at_the_bounds(_ir())
    body, paths = _validate(doc), list(_refused(doc["conditions"]))
    assert body["valid"] is False
    assert body["issues_total"] == len(paths)
    assert [e["path"] for e in body["errors"]] == paths[:MAX_RETURNED_ISSUES]
    assert body["warnings"] == []


def test_validate_lists_the_first_errors_and_counts_the_warnings_it_leaves_out() -> None:
    body = _validate(_with_conditions(_any_of("u", UNKNOWN, 30), _any_of("v", UNKNOWN, 30)))
    assert body["valid"] is False
    assert len(body["errors"]) == MAX_RETURNED_ISSUES
    assert {e["code"] for e in body["errors"]} == {"unknown_metric"}
    assert body["errors"][-1]["path"] == "conditions.children[1].children[19].left"
    assert body["warnings"] == []
    assert body["issues_total"] == 60 + 2  # the two warnings of the fixture's trigger


def test_validate_lists_the_errors_first_and_fills_the_rest_with_warnings() -> None:
    const = {"const": 1}
    groups = (_any_of("u", UNKNOWN, 3), _any_of("k", const, 30), _any_of("m", const, 30))
    doc = _with_conditions(*groups)
    body = _validate(doc)
    assert [e["code"] for e in body["errors"]] == ["unknown_metric"] * 3
    assert len(body["warnings"]) == MAX_RETURNED_ISSUES - 3
    assert {w["code"] for w in body["warnings"]} == {"unreachable_branch"}
    assert body["issues_total"] == 3 + 60 + 2


def test_a_valid_rule_past_the_bound_still_blocks_arming_on_a_warning_it_does_not_list() -> None:
    const = {"const": 1}
    body = _validate(_with_conditions(_any_of("k", const, 30), _any_of("m", const, 30)))
    assert (body["valid"], body["errors"]) == (True, [])
    assert len(body["warnings"]) == MAX_RETURNED_ISSUES
    assert "guard_missing" not in {w["code"] for w in body["warnings"]}  # found after the cap
    assert body["blocks_arming"] is True  # a safety-class warning, listed or not
    assert body["issues_total"] == 60 + 2


def test_validate_lists_at_most_the_bound_whatever_its_parse_refuses_with(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    many = [Issue(f"nodes[{i}]", "schema_error", "No.", klass="syntax") for i in range(60)]

    def refuse(ir: dict[str, Any]) -> Rule:
        raise RuleCompileError(many)

    monkeypatch.setattr(rules_api, "_parsed", refuse)
    body = _validate(_ir())
    assert [e["path"] for e in body["errors"]] == [i.path for i in many[:MAX_RETURNED_ISSUES]]
    assert body["issues_total"] == 60


def _form(doc: dict[str, Any]) -> dict[str, Any]:
    return _jsonable(to_form_model(Rule.model_validate(doc)))


def _graph(doc: dict[str, Any]) -> dict[str, Any]:
    return _jsonable(to_graph_model(Rule.model_validate(doc)))


def test_compile_refuses_a_model_at_the_bounds_with_its_first_errors_and_their_total() -> None:
    model = _at_the_bounds(_form(_ir()))
    answer = _client().post(COMPILE, json={"editor": "form", "model": model})
    body, paths = answer.json(), list(_refused(model["conditions"]))
    total = len(paths)
    assert (answer.status_code, body["code"]) == (422, "rule_ir_invalid")
    assert [e["field"] for e in body["errors"]] == paths[:MAX_RETURNED_ISSUES]
    assert (body["issues_total"], body["detail"]) == (total, f"{total} errors in the rule IR.")


def test_compile_lists_the_first_faults_of_a_graph_and_counts_them_all() -> None:
    model: dict[str, Any] = {"nodes": [{} for _ in range(60)], "edges": []}
    body = _client().post(COMPILE, json={"editor": "graph", "model": model}).json()
    assert [e["field"] for e in body["errors"]] == [
        f"nodes[{i}]" for i in range(MAX_RETURNED_ISSUES)
    ]
    assert (body["issues_total"], body["detail"]) == (60, "60 errors in the rule IR.")


def test_compile_lists_the_first_issues_of_a_rule_it_compiles_and_counts_them_all() -> None:
    model = _form(_with_conditions(_any_of("u", UNKNOWN, 30), _any_of("v", UNKNOWN, 30)))
    body = _client().post(COMPILE, json={"editor": "form", "model": model}).json()
    assert [i["code"] for i in body["issues"]] == ["unknown_metric"] * MAX_RETURNED_ISSUES
    assert (body["issues_total"], body["blocks_arming"]) == (60 + FORM_WARNINGS, True)


def test_compile_blocks_arming_on_a_safety_warning_it_does_not_list() -> None:
    const = {"const": 1}
    model = _form(_with_conditions(_any_of("k", const, 30), _any_of("m", const, 30)))
    del model["limits"]["cooldown_ms"]  # no cooldown: `guard_missing`, found after the cap
    body = _client().post(COMPILE, json={"editor": "form", "model": model}).json()
    assert {(i["code"], i["severity"]) for i in body["issues"]} == {
        ("unreachable_branch", "warning")
    }
    assert (len(body["issues"]), body["issues_total"]) == (MAX_RETURNED_ISSUES, 60 + 2)
    assert body["blocks_arming"] is True  # the safety-class warning, listed or not


class _Resolver:
    """Every request's principal holds `rules:read`; it notes the thread it was resolved on (the
    event loop's)."""

    def __init__(self) -> None:
        self.threads: list[int] = []

    def resolve(self, request: Request) -> _P:
        self.threads.append(threading.get_ident())
        return _P("rules:read")


def _app(worker: CheckWorker | None = None, **hooks: Any) -> tuple[FastAPI, _Resolver]:
    resolver = _Resolver()
    app = FastAPI()
    app.include_router(
        make_rules_router(
            lambda: REG,
            principal_resolver=resolver,
            check_limiter=unthrottled(),
            check_worker=worker,
            **hooks,
        )
    )
    return app, resolver


def test_a_counterpart_that_does_not_compile_counts_every_issue_as_its_divergence() -> None:
    seen: list[tuple[str, int]] = []
    app, _ = _app(on_divergence=lambda editor, n: seen.append((editor, n)))
    other = _graph(_ir())
    other["nodes"] += [{} for _ in range(60)]  # past the first issues the compile keeps
    body = {"editor": "form", "model": _form(_ir()), "counterpart_model": other}
    answer = TestClient(app).post(COMPILE, json=body)
    assert (answer.status_code, answer.json()["issues_total"]) == (422, 60)
    assert len(answer.json()["errors"]) == MAX_RETURNED_ISSUES
    assert seen == [("form", 60)]


def _differing(n: int) -> dict[str, Any]:
    """A compile body whose model and counterpart differ in `n` leaves, a set's values."""
    model, other = _ir(), _ir()
    for doc, prefix in ((model, "a"), (other, "b")):
        doc["conditions"] = {"node_id": "c", "op": "in_set", "left": {"metric": "price"}}
        doc["conditions"]["set_values"] = [f"{prefix}{i}" for i in range(n)]
    return {"editor": "form", "model": _form(model), "counterpart_model": _graph(other)}


def test_a_round_trip_lists_the_first_differences_and_counts_them_all() -> None:
    seen: list[tuple[str, int]] = []
    app, _ = _app(on_divergence=lambda editor, n: seen.append((editor, n)))
    trip = TestClient(app).post(COMPILE, json=_differing(60)).json()["round_trip"]
    paths = [f"/conditions/set_values/{i}" for i in range(MAX_RETURNED_ISSUES)]
    assert (trip["match"], [d["path"] for d in trip["diff"]]) == (False, paths)
    assert trip["diff_total"] == 60
    assert seen == [("form", 60)]  # the divergence counts every difference


#: Each list the IR bounds: its bound, an entry that parses, and where the model names the list.
BOUNDED: dict[str, tuple[int, Any, str]] = {
    "actions": (MAX_ACTIONS, _ir()["actions"][0], "actions"),
    "children": (MAX_BOOLEAN_CHILDREN, _ir()["conditions"], "conditions.boolean.children"),
    "operands": (
        MAX_ARITHMETIC_OPERANDS,
        {"const": 1},
        "conditions.comparison.left.arith.operands",
    ),
}


def _holding(where: str, entries: list[Any]) -> dict[str, Any]:
    """The fixture rule with the bounded list `where` holding `entries`."""
    doc = _ir()
    if where == "actions":
        doc["actions"] = entries
    elif where == "children":
        doc["conditions"] = {"node_id": "b", "op": "all_of", "children": entries}
    else:
        arith = {"node_id": "a", "op": "add", "operands": entries}
        doc["conditions"] = {"node_id": "c", "op": "gt", "left": arith, "right": {"const": 1}}
    return doc


def _issues(doc: dict[str, Any]) -> list[tuple[str, str]]:
    return [(e["path"], e["message"]) for e in _validate(doc)["errors"]]


def _too_long(limit: int, n: int) -> str:
    """The model's own words for a list past its bound (`max_length`)."""
    return f"Tuple should have at most {limit} items after validation, not {n}"


@pytest.mark.parametrize("where", sorted(BOUNDED))
def test_a_bounded_list_past_its_bound_is_refused_in_the_models_words(where: str) -> None:
    limit, parses, path = BOUNDED[where]
    assert _issues(_holding(where, [parses] * (limit + 1))) == [(path, _too_long(limit, limit + 1))]


@pytest.mark.parametrize("where", sorted(BOUNDED))
def test_a_bounded_list_of_unparsed_entries_past_its_bound_is_one_issue(where: str) -> None:
    limit, _, path = BOUNDED[where]
    many = MAX_RETURNED_ISSUES + limit
    assert _issues(_holding(where, [0] * many)) == [(path, _too_long(limit, many))]


@pytest.mark.parametrize("where", sorted(BOUNDED))
def test_a_bounded_list_within_its_bound_names_only_its_first_unparsable_entry(where: str) -> None:
    """A mixed list within its bound, entries that parse, then one the schema refuses, then more of
    both: the list is named at its first bad index, one issue for the list. An entry the schema
    refuses is one no editor produces; what the validator finds in entries that parse is
    unchanged (`test_the_validator_still_names_each_action_at_fault`)."""
    _, parses, path = BOUNDED[where]
    mixed = _holding(where, [parses, parses, 0, parses, 0])
    assert [issue_path for issue_path, _ in _issues(mixed)] == [f"{path}[2]"]


def test_the_validator_still_names_each_action_at_fault() -> None:
    """Actions that parse are each checked as before: one issue per missing parameter of each."""
    action = {"type": "send_notification", "params": {"channel": "ui"}}
    doc = _ir()
    doc["actions"] = [{"node_id": f"a{i}", **action} for i in range(3)]
    missing = [f"actions[{i}].params.{name}" for i in range(3) for name in ("severity", "template")]
    assert [path for path, _ in _issues(doc)] == missing


def test_unparsable_children_the_node_cap_does_not_count_stop_at_the_first() -> None:
    """The condition-node bound counts objects, so entries that are not one escape it. Each list
    now stops at its first: a root of full boolean nodes, each holding entries that do not parse,
    answers that first entry and the two lists it leaves empty, not one issue per entry."""
    width = MAX_BOOLEAN_CHILDREN
    doc = _ir()
    doc["conditions"] = _node([_node([0] * width) for _ in range(width)])
    assert count_condition_nodes(doc) == width + 1  # the cap sees none of the entries
    inner = "conditions.boolean.children[0].boolean.children"
    paths = [inner + "[0]", inner, "conditions.boolean.children"]
    assert [path for path, _ in _issues(doc)] == paths


#: Each list the IR leaves unbounded (`FailFast`): two entries that parse, and where the model names
#: the list.
UNBOUNDED: dict[str, tuple[tuple[Any, Any], str]] = {
    "symbols": (("BTCUSDT", "ETHUSDT"), "scope.symbols"),
    "account_ids": (
        ("00000000-0000-4000-8000-000000000002", "00000000-0000-4000-8000-000000000003"),
        "scope.account_ids",
    ),
    "environments": (("demo", "testnet"), "scope.environments"),
    "set_values": (("a", "b"), "conditions.comparison.set_values"),
}


@pytest.mark.parametrize("where", sorted(UNBOUNDED))
def test_an_unbounded_list_answers_its_first_unparsed_entry_alone(where: str) -> None:
    """A mixed list, entries that parse, then one that does not, then more of both: the list is
    named at its first bad index, one issue for the list."""
    (one, other), path = UNBOUNDED[where]
    entries = [one, other, 0, one, *[0] * MAX_RETURNED_ISSUES]
    doc = _ir()
    if where == "set_values":
        doc["conditions"] = {"node_id": "c", "op": "in_set", "left": {"metric": "price"}}
        doc["conditions"]["set_values"] = entries
    else:
        doc["scope"][where] = entries
    body = _validate(doc)
    assert ([e["path"] for e in body["errors"]], body["issues_total"]) == ([f"{path}[2]"], 1)


def test_a_metrics_params_answer_their_first_refused_value_alone() -> None:
    doc, alone = _ir(), _ir()
    doc["conditions"]["left"]["params"] = {"n": 14, **{f"k{i}": [i] for i in range(60)}}
    alone["conditions"]["left"]["params"] = {"k0": [0]}
    assert _issues(doc) == _issues(alone)
    assert [path for path, _ in _issues(alone)] == ["conditions.comparison.left.metric.params.k0"]


def test_a_models_unknown_members_answer_their_first_alone() -> None:
    doc, alone = _ir(), _ir()
    doc["conditions"] |= {f"u{i}": i for i in range(60)}
    alone["conditions"]["u0"] = 0
    assert _issues(doc) == _issues(alone)
    assert [path for path, _ in _issues(alone)] == ["conditions.comparison.u0"]


#: `rule-ir.json` as this change found it: the one-issue rules change no JSON schema. A later
#: change to the schema moves this pin with the file.
RULE_IR_SHA256 = "e07dcd16a3bb14ac9970d0786a0a888e9f42e0650932b1544cab672855f87fb6"


def test_the_one_issue_rules_leave_the_ir_schema_byte_for_byte() -> None:
    committed = (FIX.parents[2] / "candleviewer/rules/ir/rule-ir.json").read_bytes()
    assert render_schema().encode() == committed  # the models generate the committed schema
    assert hashlib.sha256(committed).hexdigest() == RULE_IR_SHA256


def _golden_rules() -> Iterator[tuple[str, Rule, Any, str]]:
    """Each valid rule a golden pins, parsed as its golden parses it, with its document and its
    `ir_hash`: the IR fixtures' base hashes, the thirty-rule corpus, the client hash vectors."""
    for name, golden in IR_HASHES.items():
        text = (FIX / f"{name}.json").read_text(encoding="utf-8")
        yield name, parse_ir_json(text), json.loads(text), golden
    corpus = FIX.parent / "rule_corpus"
    for name, golden in json.loads((corpus / "golden_hashes.json").read_text())["hashes"].items():
        text = (corpus / name).read_text(encoding="utf-8")
        yield name, parse_ir_json(text), json.loads(text), golden
    vectors = FIX.parents[4] / "packages/fixtures/golden/rule-ir/hash_vectors.json"
    for vector in json.loads(vectors.read_text(encoding="utf-8"))["vectors"]:
        if "refused" not in vector:  # the HTTP path: floats, then the model
            doc = json.loads(vector["ir"])
            yield vector["name"], Rule.model_validate(doc), doc, vector["ir_hash"]


def _filled(node: Any, found: set[str]) -> None:
    """Adds to `found` each list this change reads that `node` fills."""
    if isinstance(node, dict):
        found.update(name for name in (*UNBOUNDED, "params") if node.get(name))
        for value in node.values():
            _filled(value, found)
    elif isinstance(node, list):
        for value in node:
            _filled(value, found)


def test_every_golden_rule_still_validates_and_keeps_its_hash() -> None:
    filled: set[str] = set()
    for name, rule, doc, golden in _golden_rules():
        assert ir_hash(rule) == golden, name
        _filled(doc, filled)
    assert filled == {*UNBOUNDED, "params"}  # the goldens fill every list the change reads


def _valued(route: str, values: int, text: int = 0) -> bytes:
    """A valid check body of exactly `values` values, counted as `check_bounds` counts them, padded
    with empty lists (each one value) in the rule's `graph_layout`, which also holds one string of
    `text` characters. A compile body carries the other editor's model as its counterpart."""
    doc = _ir()
    payload: dict[str, Any] = {"ir": doc}
    if route == "compile":
        doc = _form(_ir())
        payload = {"editor": "form", "model": doc, "counterpart_model": _graph(_ir())}
    doc["graph_layout"] = {"pad": [], "text": "x" * text}
    doc["graph_layout"]["pad"] = [[] for _ in range(values - count_values(payload))]
    assert count_values(payload) == values
    return json.dumps(payload).encode()


def _noting(fn: Callable[..., Any], threads: list[threading.Thread]) -> Callable[..., Any]:
    def noted(*args: Any) -> Any:
        threads.append(threading.current_thread())
        return fn(*args)

    return noted


#: What decides is the count of values, containers counted as `check_bounds` counts them, never
#: the bytes: at the threshold a check runs in place, one value past it on the worker, and a body
#: of few values in many bytes in place. Every body is sent with no declared length.
SIZES = [
    (OFF_LOOP_VALUES, 0, False),
    (OFF_LOOP_VALUES + 1, 0, True),
    (OFF_LOOP_VALUES, 20_000, False),
]
STEPS = {
    "validate": ("_parsed", "_validated"),
    "compile": ("_compiled", "_validated", "_round_trip"),
}


@pytest.mark.parametrize("route", sorted(STEPS))
@pytest.mark.parametrize(("values", "text", "on_worker"), SIZES)
def test_a_check_runs_on_the_worker_only_past_the_value_threshold(
    monkeypatch: pytest.MonkeyPatch, route: str, values: int, text: int, on_worker: bool
) -> None:
    worked: list[threading.Thread] = []
    for step in STEPS[route]:
        monkeypatch.setattr(rules_api, step, _noting(getattr(rules_api, step), worked))
    app, resolver = _app()
    path = "/rules/validate" if route == "validate" else COMPILE
    body = _valued(route, values, text)
    answer = TestClient(app).post(path, content=iter([body]), headers=JSON)
    assert answer.status_code == 200
    assert answer.json()["issues_total"] == (2 if route == "validate" else FORM_WARNINGS)
    (loop,) = resolver.threads
    assert len(worked) == len(STEPS[route])  # compile's round trip included
    assert all((t.ident != loop) is on_worker for t in worked)
    assert all(t.name.startswith("cv-rule-check") is on_worker for t in worked)


class _Shared(ThreadPoolExecutor):
    """The loop's default executor, counting what it is given."""

    given = 0

    def submit(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Future[Any]:
        self.given += 1
        return super().submit(fn, *args, **kwargs)


async def _settle(done: Callable[[], bool]) -> None:
    """Steps of the loop until `done()`, a bounded number of them."""
    for _ in range(10_000):
        if done():
            return
        await asyncio.sleep(0)
    raise AssertionError("never settled")


async def test_a_burst_past_the_workers_checks_is_refused_off_the_default_executor() -> None:
    shared = _Shared(max_workers=1)
    asyncio.get_running_loop().set_default_executor(shared)
    worker, gate = CheckWorker(), threading.Event()
    holding = asyncio.ensure_future(worker.run(gate.wait, 10))  # the one thread is busy
    app, _ = _app(worker)
    body = _valued("validate", OFF_LOOP_VALUES + 1)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://r") as c:
        burst = [
            asyncio.ensure_future(c.post("/rules/validate", content=body, headers=JSON))
            for _ in range(MAX_CHECKS_IN_FLIGHT + 2)
        ]
        await _settle(lambda: sum(post.done() for post in burst) == 2)
        assert worker.admitted == MAX_CHECKS_IN_FLIGHT  # the rest wait for the thread
        gate.set()
        answers = await asyncio.gather(*burst)
    assert await holding
    assert sorted(a.status_code for a in answers) == [200] * MAX_CHECKS_IN_FLIGHT + [429] * 2
    assert {a.headers["retry-after"] for a in answers if a.status_code == 429} == {"1"}
    assert (worker.admitted, shared.given) == (0, 0)  # no check queued on the default executor


async def test_a_cancelled_check_holds_the_worker_until_its_thread_returns() -> None:
    worker, gate = CheckWorker(), threading.Event()
    job = asyncio.ensure_future(worker.run(gate.wait, 10))
    await asyncio.sleep(0)  # the call is on the thread
    job.cancel()
    for _ in range(100):  # the cancellation is delivered; the thread still waits
        await asyncio.sleep(0)
    assert not job.done()
    gate.set()
    with pytest.raises(asyncio.CancelledError):
        await job


#: C-2.17: no work blocks the event loop beyond 50 ms.
LOOP_STEP_BUDGET_MS = 50
#: Each reading is the median of this many rounds, so one runner pause cannot fail it.
STEP_SAMPLES = 7


@pytest.fixture
def loop_steps(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[float]]:
    """The loop thread's own time (`time.thread_time`, seconds) of every loop callback run while
    the test body awaits: neither the worker's work nor the host's other load counts, and neither
    does a wait for the interpreter lock (the worker's passes are read for that). The cyclic GC is
    off for the span."""
    steps: list[float] = []
    monkeypatch.setattr(events.Handle, "_run", _timed(events.Handle._run, steps))
    was_enabled = gc.isenabled()
    gc.collect()
    gc.disable()
    try:
        yield steps
    finally:
        if was_enabled:
            gc.enable()


def _timed(
    fn: Callable[..., Any], passes: list[float], clock: Callable[[], float] = time.thread_time
) -> Callable[..., Any]:
    """`fn`, each call's time on `clock` (seconds) added to `passes`."""

    def timed(*args: Any) -> Any:
        started = clock()
        try:
            return fn(*args)
        finally:
            passes.append(clock() - started)

    return timed


async def _rounds(
    body: bytes, burst: int, steps: list[float], passes: list[float]
) -> tuple[dict[str, Any], list[float], list[float]]:
    """An untimed check of `body` (its answer), then `STEP_SAMPLES` rounds of `burst` checks sent
    at once: each round's longest loop step and longest worker pass, in ms."""
    app, _ = _app()
    longest_step, longest_pass = [], []
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://rules") as client:
        first = await client.post("/rules/validate", content=body, headers=JSON)
        await asyncio.sleep(0)  # ends the step that took the untimed answer
        for _ in range(STEP_SAMPLES):
            steps.clear()
            passes.clear()
            posts = (
                client.post("/rules/validate", content=body, headers=JSON) for _ in range(burst)
            )
            answers = await asyncio.gather(*posts)
            await asyncio.sleep(0)  # ends the step that took the answers, so it is counted
            assert {a.status_code for a in answers} <= {200, 429}
            longest_step.append(max(steps) * 1000)
            longest_pass.append(max(passes, default=0.0) * 1000)
    return first.json(), longest_step, longest_pass


def _within_budget(name: str, readings: list[float]) -> None:
    median = statistics.median(readings)
    message = f"{name}: median {median:.1f} ms of {len(readings)}, budget {LOOP_STEP_BUDGET_MS} ms"
    assert median < LOOP_STEP_BUDGET_MS, f"{message}: {readings}"


class _Ticks:
    """A fake thread clock: the two reads around each timed call are `durations[i]` apart."""

    def __init__(self, durations: list[float]) -> None:
        self._durations = iter(durations)
        self._now, self._closing = 0.0, False

    def __call__(self) -> float:
        if self._closing:
            self._now += next(self._durations)
        self._closing = not self._closing
        return self._now


def test_a_reading_times_each_call_on_the_clock_it_is_given() -> None:
    passes: list[float] = []
    timed = _timed(lambda n: n + 1, passes, clock=_Ticks([0.004, 0.834]))
    assert (timed(1), timed(2)) == (2, 3)
    assert passes == pytest.approx([0.004, 0.834])


@pytest.mark.parametrize("stalled", [0, STEP_SAMPLES // 2])
def test_a_budget_holds_while_a_minority_of_readings_stall(stalled: int) -> None:
    _within_budget("in place", [834.0] * stalled + [4.0] * (STEP_SAMPLES - stalled))


def test_a_budget_fails_once_most_readings_exceed_it() -> None:
    readings = [834.0] * (STEP_SAMPLES // 2 + 1) + [4.0] * (STEP_SAMPLES // 2)
    with pytest.raises(AssertionError, match=rf"in place: median 834\.0 ms of {STEP_SAMPLES},"):
        _within_budget("in place", readings)


@pytest.mark.perf  # a time budget (C-13.9): run by `py-perf`, not the default unit run
@pytest.mark.parametrize(
    ("make", "valid"), [(_failing, False), (_wide, True)], ids=["failing", "valid"]
)
async def test_a_check_in_place_at_the_threshold_keeps_each_loop_step_within_budget(
    loop_steps: list[float], make: Callable[[dict[str, Any], int], dict[str, Any]], valid: bool
) -> None:
    """The costliest bodies that run in place, at `OFF_LOOP_VALUES` values with the body's own
    object: the densest and deepest failing content, and the widest valid content. The loop
    thread's own time per step, which holds the whole check here, stays within C-2.17's budget."""
    body = json.dumps({"ir": make(_ir(), OFF_LOOP_VALUES - 1)}).encode()
    assert count_values(json.loads(body)) == OFF_LOOP_VALUES
    answer, steps, _ = await _rounds(body, 1, loop_steps, [])
    assert (answer["valid"], answer["issues_total"] > MAX_RETURNED_ISSUES) == (valid, not valid)
    _within_budget("in place, the longest loop step", steps)


def _unbounded_failing() -> dict[str, Any]:
    """A request at the bounds whose entries fail one by one in a list the IR leaves unbounded,
    a comparison's `set_values` at the deepest node, where each issue's path is longest."""
    doc = _ir()
    leaf: dict[str, Any] = {"node_id": "c", "op": "in_set", "left": {"metric": "price"}}
    leaf["set_values"] = []
    doc["conditions"] = leaf
    for _ in range(DEEPEST):
        doc["conditions"] = _node([doc["conditions"]])
    leaf["set_values"] = [0] * (MAX_ITEMS - count_values(doc))
    common.check_bounds(doc, "rule")
    return doc


@pytest.mark.perf
async def test_a_burst_on_the_worker_keeps_each_pass_and_loop_step_within_budget(
    loop_steps: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A burst of checks at the bounds, past what the worker holds, whose list fails entry by
    entry. The worker's longest pass, `model_validate` or `errors()` read as the thread's own time
    (the loop waits for a native pass as long as it runs), and the loop's longest step stay within
    C-2.17's budget; the checks past what the worker holds are refused."""
    passes: list[float] = []
    model = type(
        "TimedRule", (), {"model_validate": staticmethod(_timed(Rule.model_validate, passes))}
    )
    monkeypatch.setattr(common, "Rule", model)
    monkeypatch.setattr(common, "schema_issues", _timed(common.schema_issues, passes))
    body = json.dumps({"ir": _unbounded_failing()}).encode()
    answer, steps, worker = await _rounds(body, MAX_CHECKS_IN_FLIGHT + 2, loop_steps, passes)
    # Its list's first entry, and each node above it, left with no child (`too_short`).
    assert (answer["valid"], answer["issues_total"]) == (False, 1 + DEEPEST)
    _within_budget("on the worker, the longest pass", worker)
    _within_budget("on the worker, the longest loop step", steps)
