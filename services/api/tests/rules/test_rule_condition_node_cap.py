"""#4834 (E35 authoring limits, G-2): a rule holds at most `MAX_CONDITION_NODES` condition nodes.

The count is each comparison, boolean and temporal node under `conditions`, once at each place it
occurs (operands and actions are not nodes). `check_bounds` decides it after its value and depth
pass and before any model is built, so validate, every save and import and `compile_form` answer
it, and `compile_graph` charges each expanded copy before it is built. Validate answers `200` with
one `schema_error` at `conditions`; a save, an import and compile answer `422 rule_ir_invalid`;
each refusal is counted under `cap="condition_nodes"` through `on_cap_refused` and never audited.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.api.rules import make_rules_router
from candleviewer.api.rules_crud import make_rules_crud_router
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.rules import manager as rules_manager
from candleviewer.rules.compiler import compile_form, compile_graph, to_form_model, to_graph_model
from candleviewer.rules.compiler.common import (
    MAX_CONDITION_NODES,
    MAX_GRAPH_NODES,
    MAX_ITEMS,
    ConditionNodeBoundError,
    check_bounds,
    count_condition_nodes,
)
from candleviewer.rules.ir import Rule
from candleviewer.rules.issues import Issue, RuleCompileError
from candleviewer.rules.manager import (
    REFUSED_CAPS,
    Actor,
    InMemoryRuleStore,
    RuleCapRefused,
    RuleError,
    RulesManager,
)
from candleviewer.rules.vocabulary import default_registry
from tests.rules.test_rule_save_bounds import (
    BOUNDS,
    LIMITS,
    SHARED_DEEP,
    SHARED_WITHIN,
    _expansion,
    _issues,
    _shared,
    _sized,
    _values,
)
from tests.rules.test_rules_manager import OWNER, _mgr
from tests.rules.test_rules_routes import BASE, _ir
from tests.rules.test_scope_crud import C, _setup
from tests.rules.test_validator_endpoints import (
    _P,
    _R,
    RULE_ID,
    _assert_median_within,
    _jsonable,
    _rule,
)

CAP = MAX_CONDITION_NODES
LIMIT_TEXT = f"A rule holds at most {CAP} condition nodes."
#: The one issue the bound raises, as `check_bounds` and validate show it.
ISSUE = Issue("conditions", "schema_error", LIMIT_TEXT, klass="syntax").to_dict()
#: A save answers as `22`'s `conditionNodes` example does: the count of errors as its `detail`, the
#: one `errors[]` item and no `issues`; the cap is an attribute of the error, never a member.
SAVE_DETAIL = "1 error in the rule IR."
SAVE_ERROR = {"field": "conditions", "rule": "schema_error", "message": LIMIT_TEXT}
SAVE_MEMBERS = {"type", "title", "status", "code", "detail", "errors"}
REG = default_registry()


def _comparison(ident: str) -> dict[str, Any]:
    return {"node_id": ident, "op": "gt", "left": {"metric": "price"}, "right": {"const": 5}}


def _form_conditions(n: int) -> dict[str, Any]:
    """`all_of` of `any_of` groups of comparisons holding exactly `n` nodes (at least three)."""
    groups = -(-(n - 1) // 33)  # a group is a boolean and at most 32 comparisons
    below, ids = n - 1 - groups, iter(range(n))
    sizes = [below // groups + (g < below % groups) for g in range(groups)]
    kids = [
        {"node_id": f"g{g}", "op": "any_of", "children": [_comparison(f"n{next(ids)}") for _ in s]}
        for g, s in enumerate(map(range, sizes))
    ]
    return {"node_id": "root", "op": "all_of", "children": kids}


def _temporal_conditions() -> dict[str, Any]:
    """`all_of` of `sustained_for` nodes, each wrapping an `any_of` of 32 comparisons."""
    groups = _form_conditions(1 + 32 * 33)["children"]
    wrapped = [
        {"node_id": f"t{k}", "op": "sustained_for", "window_ms": 30_000, "child": group}
        for k, group in enumerate(groups)
    ]
    return {"node_id": "root", "op": "all_of", "children": wrapped}


def _one_id(node: dict[str, Any]) -> dict[str, Any]:
    """`node` with every `node_id` the same: ids are the client's and need not be unique."""
    one: dict[str, Any] = json.loads(
        re.sub(r'"node_id": "[^"]*"', '"node_id": "x"', json.dumps(node))
    )
    return one


def _walk(node: dict[str, Any]) -> int:
    """The nodes under `node` by plain recursion: the check's own count is iterative."""
    below = sum(_walk(kid) for kid in node.get("children", ()))
    return 1 + below + (_walk(node["child"]) if "child" in node else 0)


#: Documents over the cap, by the edges the count follows: the form's two levels, a temporal node's
#: `child`, and one id throughout.
OVER = {
    "form": lambda: _form_conditions(CAP + 1),
    "temporal": _temporal_conditions,
    "one_id": lambda: _one_id(_form_conditions(CAP + 1)),
}
SHAPES = pytest.mark.parametrize("shape", sorted(OVER))


def _over(shape: str = "form", **over: Any) -> dict[str, Any]:
    return _ir(conditions=OVER[shape](), **over)


def _at(**over: Any) -> dict[str, Any]:
    """A valid rule of exactly `CAP` condition nodes."""
    return _ir(conditions=_form_conditions(CAP), **over)


def _model(conditions: dict[str, Any]) -> dict[str, Any]:
    return _jsonable(_ir(conditions=conditions))


def _no_schema_walk(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any pydantic walk of a rule fails the test: the bound is decided before one."""

    def walked(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("the schema walk ran before the node bound was decided")

    monkeypatch.setattr(Rule, "model_validate", classmethod(walked))


class _Saves:
    """The save routes over an in-memory manager: audit records and `on_cap_refused`'s calls."""

    def __init__(self, perms: frozenset[str] = frozenset(BASE)) -> None:
        self.audits: list[tuple[str, dict[str, Any]]] = []
        self.capped: list[str] = []

        async def audit(action: str, payload: dict[str, Any]) -> None:
            self.audits.append((action, payload))

        self.mgr = RulesManager(InMemoryRuleStore(), REG, audit=audit)
        actor = Actor("u1", "s1", perms, is_owner=True, step_up_fresh=True)
        router = make_rules_crud_router(
            lambda: self.mgr, lambda _request: actor, on_cap_refused=self.capped.append
        )
        app = FastAPI()
        app.include_router(router)
        self.c = TestClient(app)


class _Checks:
    """`/rules/validate` and `/rules/{id}/compile`, with `on_cap_refused`'s calls."""

    def __init__(self, *perms: str) -> None:
        self.capped: list[str] = []
        who = _R(_P(*(perms or ("rules:read",))))
        router = make_rules_router(
            lambda: REG, principal_resolver=who, on_cap_refused=self.capped.append
        )
        app = FastAPI()
        app.include_router(router)
        self.c = TestClient(app)

    def compile(self, model: dict[str, Any], editor: str = "form", **extra: Any) -> Any:
        body = {"editor": editor, "model": model, **extra}
        return self.c.post(f"/rules/{RULE_ID}/compile", json=body)


# ----- the bound, and what is counted ---------------------------------------------------------


def test_the_cap_equals_max_graph_nodes() -> None:
    """Either editor can store what it can draw (E36 threat model section 5.1): one number."""
    assert (CAP, MAX_GRAPH_NODES) == (1000, 1000)


def test_the_closed_set_of_counted_caps_is_the_four_the_metric_bounds() -> None:
    assert REFUSED_CAPS == ("condition_nodes", "note", "reason", "stored_rules")
    spec = next(s for s in CATALOGUE if s.name == "rule_authoring_cap_refused_total")
    assert (spec.kind, spec.labels, spec.max_series) == ("counter", ("cap",), len(REFUSED_CAPS))
    assert (spec.status, spec.owner_epic) == ("live", "E35")
    assert ConditionNodeBoundError.cap in REFUSED_CAPS


@pytest.mark.parametrize(
    ("conditions", "count"),
    [
        ({"op": "gt", "left": {"metric": "price"}, "right": {"const": 1}}, 1),
        ({"op": "all_of", "children": [{"op": "gt"}, {"op": "lt"}]}, 3),
        ({"op": "sustained_for", "child": {"op": "any_of", "children": [{"op": "gt"}]}}, 3),
        ({"op": "gt", "left": {"op": "add", "operands": [{"metric": "price"}]}}, 1),
        ({"op": "all_of", "children": [{"op": "gt"}] * 3}, 4),
        (None, 0),
        ("not a node", 0),
    ],
    ids=["comparison", "boolean", "temporal", "operands", "repeated", "absent", "scalar"],
)
def test_the_count_is_each_node_of_conditions_once_at_each_place_it_occurs(
    conditions: Any, count: int
) -> None:
    doc = {"conditions": conditions, "actions": [{"type": "send_notification"}] * 4}
    assert count_condition_nodes(doc, limit=10**9) == count
    assert count_condition_nodes([doc], limit=10**9) == 0  # a document is an object
    assert count_condition_nodes({"nodes": [{}] * 5}, limit=10**9) == 0  # a graph model has none


@SHAPES
def test_a_document_over_the_cap_is_refused_by_check_bounds_with_one_issue(shape: str) -> None:
    with pytest.raises(ConditionNodeBoundError) as refused:
        check_bounds(_over(shape), "rule")
    assert isinstance(refused.value, RuleCompileError)
    assert [i.to_dict() for i in refused.value.issues] == [ISSUE]
    assert LIMIT_TEXT in str(refused.value)


@pytest.mark.parametrize(
    "held",
    [{}, {"conditions": _form_conditions(CAP + 1)}],
    ids=["within_the_cap", "over_the_cap_too"],
)
def test_a_document_over_the_value_bound_is_not_a_node_bound_refusal(held: dict[str, Any]) -> None:
    """The values and the depth keep their own issue, at `$`, and are not counted as a node cap: the
    value and depth pass is first, so a document over both bounds is answered by it."""
    doc = _sized(MAX_ITEMS + 1, **held)
    with pytest.raises(RuleCompileError) as refused:
        check_bounds(doc, "rule")
    assert not isinstance(refused.value, ConditionNodeBoundError)
    assert _issues([i.to_dict() for i in refused.value.issues]) == BOUNDS
    assert LIMITS in refused.value.issues[0].message
    with pytest.raises(RuleError) as plain:
        RulesManager.check_document(doc)
    assert not isinstance(plain.value, RuleCapRefused)  # never counted as a cap
    assert _issues(plain.value.extra["issues"]) == BOUNDS and LIMITS in plain.value.message
    checks = _Checks()
    r = checks.c.post("/rules/validate", json={"ir": doc})
    assert (r.json()["valid"], _issues(r.json()["errors"]), checks.capped) == (False, BOUNDS, [])


@SHAPES
def test_a_rule_one_node_past_the_cap_is_refused_before_the_schema_walk(
    shape: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_schema_walk(monkeypatch)
    doc = _over(shape)
    with pytest.raises(RuleCapRefused):
        RulesManager.check_document(doc)
    body = _Checks().c.post("/rules/validate", json={"ir": doc}).json()
    assert body["valid"] is False and body["errors"] == [ISSUE]
    assert _Saves().c.post("/rules", json={"ir": doc}).status_code == 422
    assert _Checks().compile(_model(doc["conditions"])).status_code == 422
    with pytest.raises(ConditionNodeBoundError):
        compile_form(_model(doc["conditions"]), RULE_ID)


# ----- validate -------------------------------------------------------------------------------


@SHAPES
def test_validate_over_the_node_cap_is_200_invalid_schema_error_at_conditions(shape: str) -> None:
    checks = _Checks()
    r = checks.c.post("/rules/validate", json={"ir": _over(shape)})
    assert r.status_code == 200, r.text[:300]
    assert r.json() == {
        "valid": False,
        "errors": [ISSUE],
        "warnings": [],
        "referenced_variables": [],
        "referenced_actions": [],
        "estimated_evaluations_per_minute": 0,
    }
    assert checks.capped == ["condition_nodes"]


def test_a_rule_at_exactly_the_cap_is_validated_stored_and_compiled_and_never_counted() -> None:
    checks, saves = _Checks(), _Saves()
    r = checks.c.post("/rules/validate", json={"ir": _at()})
    assert (r.status_code, r.json()["valid"], r.json()["errors"]) == (200, True, [])
    created = saves.c.post("/rules", json={"ir": _at()})
    assert created.status_code == 201, created.text[:300]
    renamed = {"ir": _at(name="renamed")}
    put = saves.c.put(f"/rules/{created.json()['id']}", json=renamed, headers={"If-Match": "1"})
    assert put.status_code == 200
    assert checks.compile(_model(_form_conditions(CAP))).status_code == 200
    assert checks.capped == saves.capped == []


# ----- save and import ------------------------------------------------------------------------


@SHAPES
def test_post_rules_over_the_node_cap_is_422_and_stores_nothing(shape: str) -> None:
    saves = _Saves()
    r = saves.c.post("/rules", json={"ir": _over(shape)})
    assert r.status_code == 422, r.text[:300]
    body = r.json()
    assert (body["code"], body["detail"], body["errors"]) == (
        "rule_ir_invalid",
        SAVE_DETAIL,
        [SAVE_ERROR],
    )
    assert set(body) == SAVE_MEMBERS  # `22`'s example members: no `issues`, and no `cap`
    assert saves.c.get("/rules").json()["items"] == [] and saves.audits == []
    assert saves.capped == ["condition_nodes"]


def test_put_rule_over_the_node_cap_writes_no_version() -> None:
    saves = _Saves()
    rid = saves.c.post("/rules", json={"ir": _ir()}).json()["id"]
    r = saves.c.put(f"/rules/{rid}", json={"ir": _over()}, headers={"If-Match": "1"})
    assert r.status_code == 422 and r.json()["errors"] == [SAVE_ERROR]
    assert (r.json()["detail"], set(r.json())) == (SAVE_DETAIL, SAVE_MEMBERS)
    assert saves.c.get(f"/rules/{rid}/versions").json()["meta"]["count"] == 1
    assert [a for a, _ in saves.audits] == ["rule.created"]
    assert saves.capped == ["condition_nodes"]


def test_a_save_refused_for_another_reason_is_answered_unchanged_and_never_counted() -> None:
    saves = _Saves()
    rid = saves.c.post("/rules", json={"ir": _ir()}).json()["id"]
    stale = saves.c.put(f"/rules/{rid}", json={"ir": _ir()}, headers={"If-Match": "7"})
    assert (stale.status_code, stale.json()["code"]) == (412, "version_conflict")
    member = saves.c.post("/rules", json={"ir": _ir(), "unknown": 1})
    assert (member.status_code, member.json()["code"]) == (422, "rule_ir_invalid")
    assert [e["rule"] for e in member.json()["errors"]] == ["unknown_field"]
    values = saves.c.post("/rules", json={"ir": _sized(MAX_ITEMS + 1)})
    assert (values.status_code, _issues(values.json()["issues"])) == (422, BOUNDS)
    assert saves.capped == []  # each is answered as it is for any refusal, none counted as a cap


def test_a_save_over_the_node_cap_is_decided_before_the_scope_check() -> None:
    """After the permission gate, the bound comes before the scope check reads the document's
    scope: an ungranted account in it is never looked up, so no scope record is written."""
    c, audits, _src, _manager = _setup()
    scope = {"level": "account", "account_ids": [str(C)]}
    r = c.post("/rules", json={"ir": _over(scope=scope)})
    assert (r.status_code, r.json()["code"]) == (422, "rule_ir_invalid")
    assert audits == [] and c.get("/rules").json()["items"] == []


def test_check_document_over_the_node_cap_raises_the_counted_refusal() -> None:
    with pytest.raises(RuleCapRefused) as refused:
        RulesManager.check_document(_over())
    capped = refused.value
    assert capped.cap == "condition_nodes"
    assert (capped.status, capped.code, capped.message) == (422, "rule_ir_invalid", SAVE_DETAIL)
    assert capped.extra == {"errors": [SAVE_ERROR]} and isinstance(capped, RuleError)
    assert isinstance(capped.__cause__, ConditionNodeBoundError)


async def test_create_and_update_over_the_node_cap_store_nothing_and_write_no_record() -> None:
    m, audits, _ = _mgr()
    with pytest.raises(RuleCapRefused):
        await m.create(_over(), OWNER)
    assert (await m.list_rules(OWNER))["items"] == [] and audits == []
    rid = (await m.create(_ir(), OWNER))["id"]
    with pytest.raises(RuleCapRefused):
        await m.update(rid, _over(), 1, OWNER)
    assert [v["version"] for v in await m.versions(rid)] == [1]
    assert [a for a, _p in audits] == ["rule.created"]  # no refusal wrote a record


async def test_import_rule_over_the_node_cap_is_refused_before_the_bundle_is_copied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    m, audits, _ = _mgr()

    def walked(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("the bundle was walked before the node bound was decided")

    for name in ("collect_account_ids", "_bundled_ir"):  # an import is refused before either
        monkeypatch.setattr(rules_manager, name, walked)
    with pytest.raises(RuleCapRefused) as refused:
        await m.import_rule({"format": "cv-rule-bundle/1", "ir": _over()}, OWNER)
    assert refused.value.cap == "condition_nodes"
    assert (await m.list_rules(OWNER))["items"] == [] and audits == []  # nothing stored or recorded


# ----- compile --------------------------------------------------------------------------------


@SHAPES
def test_compile_form_over_the_node_cap_is_422(shape: str) -> None:
    checks = _Checks()
    r = checks.compile(_model(OVER[shape]()))
    assert r.status_code == 422, r.text[:300]
    body = r.json()
    assert (body["code"], body["detail"]) == ("rule_ir_invalid", "1 error in the rule IR.")
    assert body["errors"] == [
        {"field": "conditions", "rule": "schema_error", "message": LIMIT_TEXT, "node_ids": []}
    ]
    assert checks.capped == ["condition_nodes"]


def _over_depth() -> int:
    """The shallowest `_shared` fan-out whose expansion holds more nodes than the cap."""
    return next(k for k in range(1, 40) if _expansion(_shared(k)) > CAP)


#: What a graph's shared node is, as `_rule` overrides: the base comparison; a temporal node over
#: one; and a comparison over arithmetic operands, whose copy holds one condition node and an
#: arithmetic node and two operands that are not condition nodes.
COPIES = {
    "comparison": {},
    "temporal": {
        "conditions": {
            "node_id": "t1",
            "op": "sustained_for",
            "window_ms": 30_000,
            "child": _comparison("c1"),
        }
    },
    "arithmetic": {
        "conditions": {
            **_comparison("c1"),
            "left": {"const": 1},
            "right": {"node_id": "x1", "op": "add", "operands": [{"const": 2}, {"const": 3}]},
        }
    },
}


def _graph_of(n: int, kind: str = "comparison") -> dict[str, Any]:
    """A graph model that expands to exactly `n` condition nodes: a root over groups over copies of
    one shared node, by `kind` (`COPIES`); a comparison makes up the odd node of a temporal one."""
    g = _jsonable(to_graph_model(_rule(**COPIES[kind])))
    top = next(e["from"] for e in g["edges"] if e["port"] == "when")
    groups = -(-(n - 1) // 33)
    copies, odd = divmod(n - 1 - groups, _expansion(g))
    g["nodes"] += [{"id": "root", "type": "boolean", "data": {"op": "any_of"}}]
    g["nodes"] += [
        {"id": f"g{i}", "type": "boolean", "data": {"op": "all_of"}} for i in range(groups)
    ]
    g["edges"] = [e for e in g["edges"] if e["port"] != "when"]
    g["edges"] += [{"from": "root", "to": "a1", "port": "when"}]
    g["edges"] += [{"from": f"g{i}", "to": "root", "port": "in"} for i in range(groups)]
    for i in range(groups):
        size = copies // groups + (i < copies % groups)
        g["edges"] += [{"from": top, "to": f"g{i}", "port": "in"}] * size
    g["edges"] += [{"from": "c1", "to": "g0", "port": "in"}] * odd
    return g


def test_compile_graph_charges_each_expanded_copy_at_the_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _expansion(_shared(SHARED_WITHIN)) <= CAP < _expansion(_shared(SHARED_WITHIN + 1))
    for kind in COPIES:  # exactly at the cap: compiled, holding the nodes the expansion counts
        graph = _graph_of(CAP, kind)
        stored = {"conditions": compile_graph(graph).model_dump(mode="json")["conditions"]}
        assert _expansion(graph) == count_condition_nodes(stored, limit=10**9) == CAP, kind
        assert _expansion(_graph_of(CAP + 1, kind)) == CAP + 1, kind
    shared = _shared(_over_depth())
    over, sent = [_graph_of(CAP + 1, kind) for kind in COPIES], _jsonable(shared)
    over += [shared, _shared(SHARED_DEEP)]
    _no_schema_walk(monkeypatch)  # past it: refused before any copy is built into a rule
    for model in over:
        with pytest.raises(ConditionNodeBoundError) as refused:
            compile_graph(model)
        assert [i.to_dict() for i in refused.value.issues] == [ISSUE]
    checks = _Checks()
    r = checks.compile(sent, "graph")
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "conditions"
    assert checks.capped == ["condition_nodes"]


def test_a_counterpart_model_over_the_node_cap_is_refused_and_counted() -> None:
    base, checks = _rule(), _Checks()
    over_form = _model(_form_conditions(CAP + 1))
    r = checks.compile(_jsonable(to_graph_model(base)), "graph", counterpart_model=over_form)
    assert (r.status_code, r.json()["code"]) == (422, "rule_ir_invalid")
    over_graph = _jsonable(_shared(_over_depth()))
    r = checks.compile(_jsonable(to_form_model(base)), "form", counterpart_model=over_graph)
    assert (r.status_code, r.json()["code"]) == (422, "rule_ir_invalid")
    assert checks.capped == ["condition_nodes"] * 2


# ----- the count against an independent walk --------------------------------------------------

_COMPARISONS = st.builds(
    dict, op=st.just("gt"), left=st.just({"metric": "price"}), right=st.just({"const": 5})
)
TREES = st.recursive(
    _COMPARISONS,
    lambda inner: st.one_of(
        st.builds(
            lambda kids: {"op": "all_of", "children": kids},
            st.lists(inner, min_size=1, max_size=32),
        ),
        st.builds(lambda kid: {"op": "sustained_for", "window_ms": 1, "child": kid}, inner),
    ),
    max_leaves=80,
)


@settings(deadline=None)
@given(tree=TREES, limit=st.integers(1, 120))
def test_the_count_equals_an_independent_tree_walk(tree: dict[str, Any], limit: int) -> None:
    doc = {"conditions": tree}
    expected = _walk(tree)
    assert count_condition_nodes(doc, limit=10**9) == expected
    assert count_condition_nodes(doc, limit=limit) == min(expected, limit)


@settings(deadline=None, max_examples=60)
@given(n=st.integers(CAP - 40, CAP + 40))
def test_the_check_refuses_exactly_when_the_count_is_over_the_cap(n: int) -> None:
    doc = {"conditions": _form_conditions(n)}
    assert _walk(doc["conditions"]) == n
    if n > CAP:
        with pytest.raises(ConditionNodeBoundError):
            check_bounds(doc, "rule")
    else:
        check_bounds(doc, "rule")


@pytest.mark.perf
def test_check_bounds_decides_the_cap_within_the_perf_budget() -> None:
    """The cost of the check: one refusal and one full count, each within the budget."""
    over, at = _sized(MAX_ITEMS, conditions=_form_conditions(CAP + 1)), _at()
    assert _values(over) == MAX_ITEMS

    def refuse() -> None:
        with pytest.raises(ConditionNodeBoundError):
            check_bounds(over, "rule")

    _assert_median_within(refuse, budget_ms=50)
    _assert_median_within(lambda: check_bounds(at, "rule"), budget_ms=50)


# ----- C-12.4: the gates answer first ---------------------------------------------------------


def test_a_viewer_gets_403_before_any_node_count(monkeypatch: pytest.MonkeyPatch) -> None:
    counted: list[object] = []
    real = count_condition_nodes

    def counting(doc: Any, *args: Any, **kwargs: Any) -> int:
        counted.append(doc)
        return real(doc, *args, **kwargs)

    monkeypatch.setattr("candleviewer.rules.compiler.common.count_condition_nodes", counting)
    checks, saves = _Checks("orders:read"), _Saves(frozenset({"rules:read"}))
    r = checks.c.post("/rules/validate", json={"ir": _over()})
    assert (r.status_code, r.json()["detail"]) == (403, "requires rules:read")
    r = saves.c.post("/rules", json={"ir": _over()})
    assert (r.status_code, r.json()["detail"]) == (403, "requires rules:write")
    assert checks.compile(_model(_over()["conditions"])).status_code == 403
    assert counted == [] and checks.capped == [] and saves.capped == []
