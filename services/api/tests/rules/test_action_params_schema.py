"""#5963: a rule's action parameters are checked against their published bounds at save.

`validate_rule` checks each action's `params` against its catalogue `params_schema`
(`rules.vocabulary.params_check`, the closed subset the catalogue writes), so validate, compile, a
save and arming answer alike: `schema_error` at `actions[i].params.<name>`, naming the parameter and
its bound, never the value. `place_order`'s `stop_loss` is the native stop (C-2.6): one that is not
a known unit with a value above zero is refused as `native_stop_violation`, as an empty one is.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from typing import Any

import pytest

from candleviewer.rules.ir import Rule
from candleviewer.rules.manager import Actor, InMemoryRuleStore, RuleError, RulesManager
from candleviewer.rules.validator import validate_rule
from candleviewer.rules.vocabulary import default_registry
from candleviewer.rules.vocabulary.catalogue import ACTIONS
from candleviewer.rules.vocabulary.params_check import ANNOTATIONS, KEYWORDS, TYPES, param_defects
from tests.rules.test_rule_never_loosens_a_stop import _compile_body, _refused
from tests.rules.test_rules_routes import _Env, _ir
from tests.rules.test_scope import C
from tests.rules.test_scope_crud import _scoped, _setup
from tests.rules.test_validator_endpoints import RULE_ID
from tests.rules.test_vocabulary import _P, _client

REG = default_registry()
TITLES = {a.type: a.title for a in ACTIONS}
OWNER = Actor("u1", "s1", frozenset({"rules:arm_live"}), is_owner=True, step_up_fresh=True)
NOW = 1_762_300_800_000_000  # the injected clock: no test reads the wall clock
SENTINEL = -987654.321
STOP = {"unit": "atr", "value": 1.5}
#: A test schema: the subset's keywords the catalogue does not write yet, and a closed object.
SCHEMA = {
    "type": "object",
    "required": [],
    "properties": {"a": {"type": "number", "minimum": 1, "exclusiveMaximum": 10}},
    "additionalProperties": False,
}


def _action(kind: str, **params: Any) -> dict[str, Any]:
    return {"node_id": "a1", "type": kind, "params": params}


def _order(**params: Any) -> dict[str, Any]:
    base = {"side": "buy", "order_type": "market", "qty_mode": "explicit", "stop_loss": STOP}
    return _action("place_order", **{**base, **params})


def _errors(*actions: dict[str, Any]) -> list[dict[str, Any]]:
    numbered = [{**a, "node_id": f"a{n}"} for n, a in enumerate(actions, 1)]
    rule = Rule.model_validate(_ir(actions=numbered))
    return [i.to_dict() for i in validate_rule(rule, REG).errors]


def _issue(
    path: str, message: str, code: str = "schema_error", klass: str = "syntax"
) -> dict[str, Any]:
    return {"path": path, "code": code, "message": message, "severity": "error", "class": klass}


# ----- one regression per bound class, on real catalogue actions ----------------------------


@pytest.mark.parametrize(
    ("action", "name", "bound"),
    [
        (_order(qty="1"), "qty", "must be a number"),
        (_order(qty=True), "qty", "must be a number"),
        (_action("move_to_breakeven", offset_ticks=1.5), "offset_ticks", "must be a whole number"),
        (_order(side="hold"), "side", "must be one of buy, sell"),
        (_order(qty=0), "qty", "must be greater than 0"),
        (_order(qty=-1), "qty", "must be greater than 0"),
        (_action("scale_out", order_type="market", qty_pct=101), "qty_pct", "must be at most 100"),
        (_action("flatten_position", symbols=["BTCUSDT", 7]), "symbols", "must be text"),
    ],
    ids=["text", "boolean", "fraction", "enum", "zero", "negative", "maximum", "item"],
)
def test_validator_param_outside_its_published_bound_is_a_schema_error(
    action: dict[str, Any], name: str, bound: str
) -> None:
    subject = "each item of 'symbols'" if name == "symbols" else f"'{name}'"
    message = f"Action 1 ({TITLES[action['type']]}): {subject} {bound}."
    assert _errors(action) == [_issue(f"actions[0].params.{name}", message)]


def test_validator_param_at_its_bound_or_integral_is_taken() -> None:
    assert _errors(_action("scale_out", order_type="market", qty_pct=100)) == []
    assert _errors(_action("move_to_breakeven", offset_ticks=2.0), _order(qty=0.001)) == []


@pytest.mark.parametrize("held", [{}, {"template": None}], ids=["absent", "null"])
def test_validator_required_param_absent_or_null_is_missing_action_param(
    held: dict[str, Any],
) -> None:
    action = _action("send_notification", channel="ui", severity="info", **held)
    message = "Action 1 (Send notification) is missing 'template'."
    path = "actions[0].params.template"
    assert _errors(action) == [_issue(path, message, "missing_action_param", "semantics")]


def test_validator_undeclared_param_is_taken_where_the_schema_takes_any_key() -> None:
    assert _errors(_order(client_note="x")) == []


def test_param_defects_undeclared_key_where_the_schema_takes_none_is_refused_unnamed() -> None:
    (defect,) = param_defects(SCHEMA, {"a": 2, "zz987654": 1})
    assert (defect.param, defect.keyword, defect.text) == (
        "",
        "additionalProperties",
        "'params' takes only a",
    )


@pytest.mark.parametrize(
    ("value", "keyword", "text"),
    [
        (0, "minimum", "'a' must be at least 1"),
        (10, "exclusiveMaximum", "'a' must be less than 10"),
    ],
)
def test_param_defects_numeric_bound_is_held_exactly(value: int, keyword: str, text: str) -> None:
    (defect,) = param_defects(SCHEMA, {"a": value})
    assert (defect.param, defect.keyword, defect.text) == ("a", keyword, text)
    assert param_defects(SCHEMA, {"a": 1}) == param_defects(SCHEMA, {"a": 9.99}) == []


# ----- the native stop (C-2.6) and the stop moves ---------------------------------------------


@pytest.mark.parametrize(
    "stop",
    [
        {"unit": "price", "value": 0},
        {"unit": "ticks", "value": -5},
        {"unit": "atr_multiple", "value": 2},
        {"unit": "atr"},
        {"value": 2},
        {**STOP, "mode": "atr"},
        "atr",
        {},
        None,
    ],
    ids=[
        "zero",
        "negative",
        "unknown_unit",
        "no_value",
        "no_unit",
        "undeclared",
        "text",
        "empty",
        "null",
    ],
)
def test_validator_stop_without_a_known_unit_and_a_positive_value_is_native_stop_violation(
    stop: Any,
) -> None:
    (issue,) = _errors(_order(stop_loss=stop))
    assert (issue["path"], issue["code"], issue["class"]) == (
        "actions[0]",
        "native_stop_violation",
        "safety",
    )


@pytest.mark.parametrize("unit", ["price", "ticks", "percent", "atr", "r_multiple"])
def test_validator_stop_with_a_known_unit_and_a_positive_value_is_taken(unit: str) -> None:
    assert _errors(_order(stop_loss={"unit": unit, "value": 0.5})) == []


@pytest.mark.parametrize("stop", [{}, None, 0, ""], ids=["empty", "null", "zero", "blank"])
def test_validator_empty_or_null_stop_keeps_its_existing_refusal(stop: Any) -> None:
    """The refusal a rule asking for no native stop gets, word for word, and no shape issue."""
    (unprotected,) = _errors(_order(require_native_stop=False))
    assert unprotected["message"].startswith("Action 1 would leave a position without its native")
    assert _errors(_order(stop_loss=stop)) == [unprotected]


def test_validator_order_without_a_stop_is_taken_for_the_profile_stop() -> None:
    action = _order()
    del action["params"]["stop_loss"]  # the account profile's stop applies (oms sizing)
    assert _errors(action) == []


@pytest.mark.parametrize("kind", ["modify_stop_loss", "modify_take_profit", "tighten_stop"])
def test_validator_stop_move_needs_a_known_mode_and_a_value_above_zero(kind: str) -> None:
    title = TITLES[kind]
    zero = _issue("actions[0].params.value", f"Action 1 ({title}): 'value' must be greater than 0.")
    assert _errors(_action(kind, mode="atr", value=0)) == [zero]
    modes = "absolute, offset_from_entry, offset_from_price, atr, structure"
    mode = _issue("actions[0].params.mode", f"Action 1 ({title}): 'mode' must be one of {modes}.")
    assert _errors(_action(kind, mode="atr_multiple", value=2)) == [mode]
    assert _errors(_action(kind, mode="structure", value=2)) == []


@pytest.mark.parametrize(
    "params",
    [
        {"qty": SENTINEL},
        {"side": f"x{SENTINEL}"},
        {"stop_loss": {"unit": "atr", "value": SENTINEL}},
        {"stop_loss": {"unit": f"u{SENTINEL}", "value": 1}},
    ],
    ids=["number", "enum", "stop_value", "stop_unit"],
)
def test_validator_refusal_never_echoes_the_refused_value(params: dict[str, Any]) -> None:
    errors = _errors(_order(**params))
    assert errors and "987654" not in json.dumps(errors)


# ----- one answer from validate, compile and the saves ----------------------------------------

REFUSED = {
    "bound": (_order(qty=0), "actions[0].params.qty"),
    "stop": (_order(stop_loss={}), "actions[0]"),
}


@pytest.mark.parametrize("case", sorted(REFUSED))
@pytest.mark.parametrize("route", ["validate", "compile", "create", "update"])
def test_routes_refused_param_answer_alike(route: str, case: str) -> None:
    action, path = REFUSED[case]
    ir = _ir(actions=[action])
    (issue,) = _errors(action)
    assert issue["path"] == path
    checker = _client(_P("rules:read", "orders:write"))
    if route == "validate":
        body = checker.post("/rules/validate", json={"ir": ir}).json()
        assert body["valid"] is False and body["errors"] == [issue] and body["blocks_arming"]
    elif route == "compile":
        compiled = checker.post(f"/rules/{RULE_ID}/compile", json=_compile_body(ir))
        assert compiled.status_code == 200 and compiled.json()["blocks_arming"] is True
        assert [i for i in compiled.json()["issues"] if i["severity"] == "error"] == [issue]
    else:
        e = _Env()
        if route == "create":
            saved = e.c.post("/rules", json={"ir": ir})
        else:
            rid = e.create()
            saved = e.c.put(f"/rules/{rid}", json={"ir": ir}, headers={"If-Match": "1"})
        assert saved.status_code == 422 and saved.json()["code"] == "rule_ir_invalid"
        assert saved.json()["errors"] == [_refused(issue)]
        assert [a for a, _ in e.audits] == ([] if route == "create" else ["rule.created"])


def test_routes_keep_their_forbidden_role_and_cross_account_refusals() -> None:
    ir = _ir(actions=[_order(qty=0)])
    assert _Env({"rules:read"}).c.post("/rules", json={"ir": ir}).status_code == 403
    assert _client(_P("orders:write")).post("/rules/validate", json={"ir": ir}).status_code == 403
    c, audits, _src, _m = _setup()  # account C is not granted
    refused = c.post("/rules", json={"ir": {**_scoped(C), "actions": ir["actions"]}})
    assert refused.status_code == 403 and refused.json()["code"] == "forbidden"
    assert audits == ["rule_scope_denied"] and c.get("/rules").json()["items"] == []


# ----- the catalogue: its own examples pass, and its subset stays closed ----------------------


def _example(schema: Mapping[str, Any]) -> Any:
    """A value `schema` takes, each declared property included."""
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type")
    if kind == "object":
        return {k: _example(s) for k, s in schema.get("properties", {}).items()}
    if kind == "array":
        return [_example(schema["items"])] if "items" in schema else []
    return {"number": 1, "integer": 1, "boolean": True}.get(str(kind), "x")


@pytest.mark.parametrize("full", [False, True], ids=["required", "every_param"])
@pytest.mark.parametrize("spec", ACTIONS, ids=lambda s: s.type)
def test_catalogue_action_example_params_pass(spec: Any, full: bool) -> None:
    schema = spec.params_schema
    params = {
        n: _example(schema["properties"][n])
        for n in (schema["properties"] if full else schema["required"])
    }
    assert param_defects(schema, params) == []
    assert _errors(_action(spec.type, **params)) == []


def _walk(schema: Mapping[str, Any]) -> Iterator[tuple[str, Any]]:
    for key, value in schema.items():
        yield key, value
        if key == "properties":
            for sub in value.values():
                yield from _walk(sub)
        elif key == "items":
            yield from _walk(value)


@pytest.mark.parametrize("spec", ACTIONS, ids=lambda s: s.type)
def test_catalogue_schema_writes_only_the_closed_subset(spec: Any) -> None:
    for key, value in _walk(spec.params_schema):
        assert key in KEYWORDS | ANNOTATIONS, key
        assert key != "type" or value in TYPES, value
        assert key != "additionalProperties" or isinstance(value, bool), value


# ----- arming re-reads the stored version (D4) ------------------------------------------------


async def test_arming_stored_version_with_a_refused_param_is_refused_until_it_is_resaved() -> None:
    """Arming runs `validate_rule` on the stored version, as for #5807's over-bound constant."""
    m = RulesManager(InMemoryRuleStore(), REG, now_us=lambda: NOW)
    try:
        made = await m.create(_ir(actions=[_order()], limits={"cooldown_ms": 5000}), OWNER)
        rid = str(made["id"])
        await m.set_mode(rid, "simulate", OWNER, "k-sim")
        await m.record_simulation(rid, made["version"]["ir_hash"], 5, 0.0)
        row = await m._s.get(rid)
        assert row is not None
        row.versions[0].ir["actions"][0]["params"]["stop_loss"]["value"] = 0  # stored before #5963
        with pytest.raises(RuleError) as refused:
            await m.set_mode(rid, "armed", OWNER, "k-arm")
        assert (refused.value.status, refused.value.code) == (422, "rule_invalid")
        assert (await m.get(rid, OWNER))["mode"] == "simulate"
        fixed = _ir(
            actions=[_order(stop_loss={"unit": "atr", "value": 2})], limits={"cooldown_ms": 5000}
        )
        resaved = (await m.update(rid, fixed, 1, OWNER))["version"]
        await m.set_active_version(rid, resaved["id"], "re-saved", OWNER)
        await m.record_simulation(rid, resaved["ir_hash"], 5, 0.0)
        assert (await m.set_mode(rid, "armed", OWNER, "k-arm-2"))["mode"] == "armed"
    finally:
        await m.stop()
