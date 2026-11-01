"""No rule loosens a stop, for any role (24-internal-schemas.md section 8.8 rule 5).

`widen_stop`, or a stop action whose `only_tighten` is anything but true, is refused with the issue
code 22 registers (`stop_loosening`) on save, `/rules/validate`, `compileRule` and import, alike
for the Owner, a Manager and a caller holding `*` or the retired `rules.loosen_stop`: no permission
reaches it, an import is refused, never stripped, and a version stored before the refusal is never
armed. Each route keeps its forbidden-role and cross-account refusals (C-12.4).
"""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.rules.compiler import to_form_model, to_graph_model
from candleviewer.rules.ir import Rule
from candleviewer.rules.manager import Actor, RuleError
from candleviewer.rules.validator import validate_rule
from candleviewer.rules.vocabulary import default_registry
from tests.rules.test_rules_manager import _mgr
from tests.rules.test_rules_routes import BASE, _Env, _ir
from tests.rules.test_scope import A, C, FakeState, _http
from tests.rules.test_scope_crud import _scoped, _setup
from tests.rules.test_validator_endpoints import RULE_ID, _jsonable
from tests.rules.test_vocabulary import _P, _client

REG = default_registry()
CODE = "stop_loosening"
REASON = "Not available — rules never loosen a stop."
RETIRED = "rules.loosen_stop"  # the permission the validator once read; never seeded
TYPE, FLAG = "actions[0].type", "actions[0].params.only_tighten"
GRANTED = frozenset({str(A)})  # a Manager saves only with a grant


def _action(kind: str, **params: Any) -> dict[str, Any]:
    return {"node_id": "a1", "type": kind, "params": params}


def _stop(kind: str, **params: Any) -> dict[str, Any]:
    return _action(kind, mode="atr", value=2, **params)


#: Every way an action could loosen a stop, and the path its refusal names.
LOOSENING: dict[str, tuple[dict[str, Any], str]] = {
    "widen_stop": (_stop("widen_stop"), TYPE),
    "widen_stop_only_tighten": (_stop("widen_stop", only_tighten=True), TYPE),
    "modify_stop_loss": (_stop("modify_stop_loss", only_tighten=False), FLAG),
    "tighten_stop": (_stop("tighten_stop", only_tighten=False), FLAG),
    "move_to_breakeven": (_action("move_to_breakeven", only_tighten=False), FLAG),
    "only_tighten_null": (_stop("modify_stop_loss", only_tighten=None), FLAG),
    "only_tighten_text": (_stop("modify_stop_loss", only_tighten="false"), FLAG),
}
FORMS = pytest.mark.parametrize("form", ["widen_stop", "modify_stop_loss"])
ROLES = pytest.mark.parametrize("role", ["owner", "manager", "star"])
#: Save callers: the Owner holding the retired permission, a Manager, and a `*` grant.
SAVERS: dict[str, dict[str, Any]] = {
    "owner": {"perms": BASE | {RETIRED}},
    "manager": {"perms": {"rules:read", "rules:write"}, "owner": False, "granted": GRANTED},
    "star": {"perms": {"*", "rules:read", "rules:write"}},
}
IMPORTERS = {
    "owner": Actor("u1", "s1", frozenset({"rules:arm_live", RETIRED}), is_owner=True),
    "manager": Actor("u2", "s2", frozenset({"orders:write"}), GRANTED),
    "star": Actor("u3", "s3", frozenset({"*"}), is_owner=True),
}


def _issue(path: str, n: int = 1) -> dict[str, Any]:
    message = f"Action {n} could loosen a stop. {REASON}"
    return {"path": path, "code": CODE, "message": message, "severity": "error", "class": "safety"}


def _refused(issue: dict[str, Any]) -> dict[str, Any]:
    """`issue` as a refused save names it in 22's `errors[]` (#4834's C-row)."""
    return {"field": issue["path"], "rule": issue["code"], "message": issue["message"]}


def _loosening(form: str, **over: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """A rule whose one action is `form`, and the issue its refusal carries."""
    action, path = LOOSENING[form]
    return _ir(actions=[action], **over), _issue(path)


#: `/rules/validate` and compile callers; the principal fake reads `*` as every permission.
CHECKERS = {
    "owner": _P("rules:read", "orders:write", "rules:arm_live", RETIRED),
    "manager": _P("rules:read", "orders:write"),
    "star": _P("*"),
}


def _compile_body(ir: dict[str, Any], editor: str = "form") -> dict[str, Any]:
    model = (to_form_model if editor == "form" else to_graph_model)(Rule.model_validate(ir))
    return {"editor": editor, "model": _jsonable(model)}


@pytest.mark.parametrize("form", sorted(LOOSENING))
def test_validator_refuses_every_action_that_could_loosen_a_stop(form: str) -> None:
    ir, issue = _loosening(form)
    res = validate_rule(Rule.model_validate(ir), REG)
    assert [i.to_dict() for i in res.errors] == [issue] and res.blocks_arming
    ir["actions"] = [_stop("tighten_stop"), {**ir["actions"][0], "node_id": "a2"}]  # second one
    (later,) = validate_rule(Rule.model_validate(ir), REG).errors
    assert later.to_dict() == _issue(issue["path"].replace("[0]", "[1]"), 2)


@pytest.mark.parametrize(
    "action",
    [
        _stop("modify_stop_loss"),
        _stop("modify_stop_loss", only_tighten=True),
        _stop("tighten_stop"),
        _action("move_to_breakeven", offset_ticks=2),
    ],
)
def test_validator_never_refuses_a_stop_action_that_only_tightens(action: dict[str, Any]) -> None:
    assert validate_rule(Rule.model_validate(_ir(actions=[action])), REG).valid


def test_validator_never_refuses_a_take_profit_edit() -> None:
    action = _stop("modify_take_profit", only_tighten=False)  # a take profit is no stop
    assert validate_rule(Rule.model_validate(_ir(actions=[action])), REG).valid


@ROLES
@FORMS
def test_save_refuses_a_rule_that_could_loosen_a_stop_for_every_role(role: str, form: str) -> None:
    e = _Env(**SAVERS[role])
    ir, issue = _loosening(form)
    created = e.c.post("/rules", json={"ir": ir})
    assert created.status_code == 422 and created.json()["code"] == "rule_ir_invalid"
    assert created.json()["errors"] == [_refused(issue)] and "issues" not in created.json()
    rid = e.create()
    updated = e.c.put(f"/rules/{rid}", json={"ir": ir}, headers={"If-Match": "1"})
    assert updated.status_code == 422 and updated.json()["errors"] == [_refused(issue)]
    assert [r["latest_version"] for r in e.c.get("/rules").json()["items"]] == [1]
    assert [a for a, _ in e.audits] == ["rule.created"]


def test_save_keeps_its_forbidden_role_and_cross_account_refusals() -> None:
    ir, _ = _loosening("widen_stop")
    reader = _Env({"rules:read"})
    refused = reader.c.post("/rules", json={"ir": ir})
    assert refused.status_code == 403 and refused.json()["code"] == "forbidden"
    assert reader.c.get("/rules").json()["items"] == []
    c, audits, _src, _m = _setup()  # account C is not granted
    refused = c.post("/rules", json={"ir": {**_scoped(C), "actions": ir["actions"]}})
    assert refused.status_code == 403 and refused.json()["code"] == "forbidden"
    assert audits == ["rule_scope_denied"] and c.get("/rules").json()["items"] == []


@ROLES
@FORMS
def test_validate_and_compile_refuse_exactly_as_save_for_every_role(role: str, form: str) -> None:
    c = _client(CHECKERS[role])
    ir, issue = _loosening(form)
    checked = c.post("/rules/validate", json={"ir": ir}).json()
    assert checked["valid"] is False and checked["errors"] == [issue] and checked["blocks_arming"]
    for editor in ("form", "graph"):
        compiled = c.post(f"/rules/{RULE_ID}/compile", json=_compile_body(ir, editor))
        assert compiled.status_code == 200 and compiled.json()["blocks_arming"] is True
        assert [i for i in compiled.json()["issues"] if i["severity"] == "error"] == [issue]


def test_validate_and_compile_keep_their_forbidden_role_and_cross_account_refusals() -> None:
    ir, _ = _loosening("widen_stop")
    no_read = _client(_P("orders:write"))
    assert no_read.post("/rules/validate", json={"ir": ir}).status_code == 403
    assert no_read.post(f"/rules/{RULE_ID}/compile", json=_compile_body(ir)).status_code == 403
    scoped = _http(FakeState())  # every permission, and account C is not granted
    foreign = {**ir, "scope": {"level": "account", "account_ids": [str(C)]}}
    assert scoped.post("/rules/validate", json={"ir": foreign}).status_code == 403
    assert scoped.post(f"/rules/{RULE_ID}/compile", json=_compile_body(foreign)).status_code == 403


@ROLES
@FORMS
async def test_import_refuses_a_rule_that_could_loosen_a_stop_and_stores_nothing(
    role: str, form: str
) -> None:
    m, audits, _ = _mgr()
    ir, issue = _loosening(form)
    with pytest.raises(RuleError) as refused:
        await m.import_rule({"format": "cv-rule-bundle/1", "ir": ir}, IMPORTERS[role])
    assert (refused.value.status, refused.value.code) == (422, "rule_ir_invalid")
    assert refused.value.message == "1 error in the rule IR."
    assert refused.value.extra["errors"] == [_refused(issue)]
    assert (await m.list_rules(IMPORTERS[role]))["items"] == [] and audits == []


async def test_import_keeps_its_cross_account_refusal() -> None:
    m, audits, _ = _mgr()
    ir, _ = _loosening("widen_stop", scope={"level": "account", "account_ids": [str(C)]})
    with pytest.raises(RuleError) as refused:
        await m.import_rule({"ir": ir}, IMPORTERS["manager"])
    assert (refused.value.status, refused.value.code) == (403, "forbidden")
    assert [a for a, _ in audits] == ["rule.import_refused"]


@pytest.mark.parametrize("role", ["owner", "star"])
async def test_arming_refuses_a_stored_version_that_could_loosen_a_stop(role: str) -> None:
    """A version stored before the refusal existed (no real database holds one) is never armed."""
    m, _, _ = _mgr()
    rid = (await m.create(_ir(), IMPORTERS["owner"]))["id"]
    row = await m._s.get(rid)
    assert row is not None
    row.versions[0].ir["actions"] = [LOOSENING["widen_stop"][0]]
    await m.set_mode(rid, "simulate", IMPORTERS["owner"], "k-sim")
    await m.record_simulation(rid, row.versions[0].ir_hash, 5, 0.0)
    with pytest.raises(RuleError) as refused:
        await m.set_mode(rid, "armed", IMPORTERS[role], "k-arm")
    assert (refused.value.status, refused.value.code) == (422, "rule_invalid")
    assert (await m.get(rid, IMPORTERS["owner"]))["mode"] == "simulate"
