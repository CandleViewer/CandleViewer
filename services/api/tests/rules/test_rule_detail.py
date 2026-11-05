"""#5913, #5914 (E35): what a rule's detail holds, read (`getRule`) and after a save (`updateRule`).

`ir`, `ir_hash` and `graph_layout` are the active version's (22 `getRule`: the rule with its active
IR; the layout its document holds, else null); `version` is the newest version, the one a save's
`If-Match` names. A quarantined version's IR and layout are never answered (G-15).
"""

from __future__ import annotations

import copy
from typing import Any, cast

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.rules.manager import RULE_IR_MEMBERS, Actor, InMemoryRuleStore, RuleRow
from tests.contract._admin_support import validate_example
from tests.rules.test_rules_routes import _Env, _ir

DETAIL = "/components/schemas/RuleDetail"
#: The `RuleIr` members a stored version holds (22 `RuleIr`; it stores no `variables`).
CORE = {"ir_version", "trigger", "conditions", "actions", "scope", "limits"}
#: The layout `_ir()`'s document holds, and one a later save moves its node to.
LOADED = {"c1": {"x": 0, "y": 0}}
MOVED = {"c1": {"x": 240, "y": 120}}


def _row(e: _Env, rid: str) -> RuleRow:
    """The stored row of `rid`, as the in-memory store holds it."""
    return cast(InMemoryRuleStore, e.mgr._s)._rows[rid]


def _put(e: _Env, rid: str, threshold: str, if_match: str, **over: Any) -> Any:
    sent = {"ir": _ir(threshold, **over)}
    return e.c.put(f"/rules/{rid}", json=sent, headers={"If-Match": if_match})


def _versions_named(body: dict[str, Any]) -> tuple[Any, ...]:
    """What a detail names of the rule's versions: the newest, the active one and its hash."""
    return body["version"], body["active_version_id"], body["ir_hash"]


def test_the_ir_a_detail_answers_names_exactly_22s_rule_ir_members() -> None:
    spec: Any = load_openapi_spec()
    assert set(RULE_IR_MEMBERS) == set(spec["components"]["schemas"]["RuleIr"]["properties"])
    assert set(RULE_IR_MEMBERS) > CORE


def test_a_read_answers_the_active_ir_its_hash_and_the_version_a_save_names() -> None:
    e = _Env()
    rid = e.create()
    body = e.c.get(f"/rules/{rid}").json()
    (v1,) = _row(e, rid).versions
    assert _versions_named(body) == (1, v1.id, v1.ir_hash) and body["latest_version"] == 1
    assert body["graph_layout"] == v1.ir["graph_layout"] == LOADED
    assert set(body["ir"]) == CORE and "right2" not in body["ir"]["conditions"]
    assert body["ir"]["conditions"]["right"] == {"const": "65000.50"}
    assert (body["ir"]["scope"], body["ir"]["actions"]) == (v1.ir["scope"], v1.ir["actions"])


def test_a_rule_saved_without_a_layout_reads_and_saves_with_a_null_one() -> None:
    e = _Env()
    rid = e.create(graph_layout=None)
    got = e.c.get(f"/rules/{rid}").json()
    assert "graph_layout" in got and got["graph_layout"] is None
    saved = _put(e, rid, "2", "1", graph_layout=None).json()
    assert (saved["version"], saved["graph_layout"]) == (2, None)
    validate_example(DETAIL, saved)


async def test_a_detail_is_a_copy_that_never_changes_the_stored_version() -> None:
    e = _Env()
    rid = e.create()
    (v1,) = _row(e, rid).versions
    held = copy.deepcopy(v1.ir)
    detail = await e.mgr.get(rid, Actor("u1", "s1", frozenset({"rules:read"}), is_owner=True))
    detail["ir"]["actions"][0]["params"]["template"] = "changed"
    detail["ir"]["scope"]["symbols"].append("ETHUSDT")
    detail["graph_layout"]["c1"]["x"] = 9
    assert v1.ir == held


def test_a_version_stored_with_only_what_its_model_requires_reads_as_the_engine_reads_it() -> None:
    """Every default the engine applies is answered, `ir_version` among them; a metric
    parameter's null is the parameter's own value, kept."""
    e = _Env()
    rid = e.create()
    (v1,) = _row(e, rid).versions
    for key in ("ir_version", "limits"):
        del v1.ir[key]
    v1.ir["conditions"]["left"]["params"] = {"n": 14, "src": None}
    body = e.c.get(f"/rules/{rid}").json()
    assert (body["ir"]["ir_version"], body["ir"]["limits"]["cooldown_ms"]) == (1, 1000)
    assert body["ir"]["conditions"]["left"]["params"] == {"n": 14, "src": None}
    validate_example(DETAIL, body)


def test_a_save_answers_the_version_it_wrote_and_the_next_save_continues_from_it() -> None:
    """The bug's flow: the editor sends the version the save answered as the next `If-Match`; the
    answer holds the layout the save stored."""
    e = _Env()
    rid = e.create()
    saved = _put(e, rid, "2", '"1"', graph_layout=MOVED).json()
    v2 = _row(e, rid).versions[-1]
    assert _versions_named(saved) == (2, v2.id, v2.ir_hash)
    assert saved["ir"]["conditions"]["right"] == {"const": "2"}
    assert saved["graph_layout"] == v2.ir["graph_layout"] == MOVED
    assert saved == e.c.get(f"/rules/{rid}").json()
    again = _put(e, rid, "3", str(saved["version"]))
    assert (again.status_code, again.json()["version"]) == (200, 3)
    same = _put(e, rid, "3", "3").json()  # a document version 3 holds: nothing is written
    assert _versions_named(same) == _versions_named(again.json())
    assert len(_row(e, rid).versions) == 3


def test_a_save_of_a_running_rule_moves_the_version_and_keeps_the_active_ir() -> None:
    """A simulating rule keeps running its active version (US-RULE-006): the save's answer names
    the version it wrote, and the IR and layout of the version the rule still runs."""
    e = _Env()
    rid = e.create()
    assert e.mode(rid, "simulate", "k-sim").status_code == 200
    saved = _put(e, rid, "2", "1", graph_layout=MOVED).json()
    v1, v2 = _row(e, rid).versions
    assert _versions_named(saved) == (2, v1.id, v1.ir_hash)
    assert (saved["ir"]["conditions"]["right"], saved["graph_layout"]) == (
        {"const": "65000.50"},
        LOADED,
    )
    assert (v2.ir["conditions"]["right"], v2.ir["graph_layout"]) == ({"const": "2"}, MOVED)
    validate_example(DETAIL, saved)


def test_a_quarantined_rule_reads_with_its_hash_no_ir_and_a_null_layout() -> None:
    e = _Env()
    rid = e.create()
    (v1,) = _row(e, rid).versions
    v1.ir["conditions"] = {"bogus": 1}
    body = e.c.get(f"/rules/{rid}").json()
    assert body["quarantined"] and "ir" not in body and v1.ir["graph_layout"] == LOADED
    assert (body["version"], body["ir_hash"], body["graph_layout"]) == (1, v1.ir_hash, None)
    validate_example(DETAIL, body)


def test_a_rule_naming_no_stored_active_version_reads_with_no_ir_and_no_hash() -> None:
    e = _Env()
    rid = e.create()
    _row(e, rid).active_version_id = None
    body = e.c.get(f"/rules/{rid}").json()
    assert not {"ir", "ir_hash"} & set(body)
    assert (body["version"], body["graph_layout"]) == (1, None)
    validate_example(DETAIL, body)
