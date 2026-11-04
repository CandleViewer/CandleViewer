"""#5807: a rule constant keeps its number through a save and a load.

A rule is authored as the routes read a body (`json.loads`: a fractional JSON number arrives as a
float, which the IR reads as a `Decimal`), saved through `RulesManager.create` (a version stores
the IR's JSON-mode dump), loaded as the evaluator's work list loads it
(`RulesManager.evaluable_rules`) and evaluated. The in-memory store keeps the dumped document as it
is; the Postgres store writes it as JSON text and reads it back with `json.loads`, so both stores
hand the load the same document.

The dump writes a `Decimal` constant as its text (`"0.2"`), so the evaluator reads decimal text as
the number it spells (`Literal_.value`). A constant it cannot read as its place needs is refused
at load (`check_constants`, through `quarantine_path`) and never evaluated.
"""

from __future__ import annotations

import json
import operator
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.alerts.models import AlertCondition
from candleviewer.rules.errors import ConstantTypeError
from candleviewer.rules.evaluator import EvaluationResult, Evaluator, MetricValue, SnapshotBuilder
from candleviewer.rules.evaluator.engine import scope_instance
from candleviewer.rules.evaluator.nodes import (
    NOT_A_NUMBER,
    EvalContext,
    InstanceState,
    check_constants,
    evaluate,
    referenced_metrics,
)
from candleviewer.rules.ir import Literal_, MetricRef, Rule
from candleviewer.rules.manager import Actor, InMemoryRuleStore, RulesManager, quarantine_path
from candleviewer.rules.vocabulary import default_registry

FIX = Path(__file__).parents[1] / "fixtures/rule_ir"
OWNER = Actor("u1", "s1", frozenset({"rules:arm_live"}), is_owner=True, step_up_fresh=True)
NOW = 1_000_000
INSTANCE = scope_instance("BTCUSDT", None)


def _doc(const: str, op: str = "gt") -> dict[str, Any]:
    """`form_simple_0` with the condition `spread_bps <op> <const>`, the constant spelled as JSON
    text, so it reaches the IR as a request body's constant does."""
    doc: dict[str, Any] = json.loads((FIX / "form_simple_0.json").read_text(encoding="utf-8"))
    left, right = '{"metric": "spread_bps"}', f'{{"const": {const}}}'
    doc["conditions"] = json.loads(
        f'{{"node_id": "c1", "op": "{op}", "left": {left}, "right": {right}}}'
    )
    doc["actions"][0]["params"] = {"channel": "ui", "severity": "info", "template": "x"}
    return doc


class _Reading:
    """A metric source with one fresh reading for every metric."""

    def __init__(self, value: Decimal) -> None:
        self.value = value

    def read(self, ref: MetricRef) -> MetricValue:
        return MetricValue(self.value, NOW)


def _evaluate(rule: Rule, reading: str) -> EvaluationResult:
    ev = Evaluator(rule, SnapshotBuilder(_Reading(Decimal(reading))), lambda: NOW, lambda: 0)
    return ev.on_trigger(INSTANCE, "on_price_update")


async def _authored_and_loaded(doc: dict[str, Any]) -> tuple[Rule, Rule]:
    """`doc` as authored, and as the evaluator loads it once saved: created, moved to simulate and
    read back through `evaluable_rules`."""
    mgr = RulesManager(InMemoryRuleStore(), default_registry())
    try:
        rid = (await mgr.create(doc, OWNER))["id"]
        await mgr.set_mode(rid, "simulate", OWNER, "k-sim")
        (item,) = await mgr.evaluable_rules(("simulate",))
    finally:
        await mgr.stop()
    return Rule.model_validate({**doc, "rule_id": rid}), item.rule


@pytest.mark.parametrize(
    ("const", "reading"),
    [("0.2", "0.3"), ("5", "6"), ("-0.2", "-0.1"), ("2E-7", "3E-7")],
    ids=["fractional", "whole", "negative", "exponent"],
)
async def test_rule_constant_saved_and_loaded_fires_as_authored(const: str, reading: str) -> None:
    """`spread_bps > <const>` read above its constant fires as authored, and again once saved and
    loaded (the reproduction: on `c56a10bc3` only the whole constant fires after the load)."""
    authored, loaded = await _authored_and_loaded(_doc(const))
    assert _evaluate(authored, reading).fired
    assert _evaluate(loaded, reading).fired


async def _armed(mgr: RulesManager, doc: dict[str, Any]) -> str:
    """`doc` saved and armed as an Owner arms it: simulate, the simulation's evidence, armed."""
    made = await mgr.create(doc, OWNER)
    rid = str(made["id"])
    await mgr.set_mode(rid, "simulate", OWNER, "k-sim")
    await mgr.record_simulation(rid, made["version"]["ir_hash"], 5, 0.0)
    await mgr.set_mode(rid, "armed", OWNER, "k-arm")
    return rid


async def test_a_fractional_threshold_fires() -> None:
    """Scenario: a fractional threshold fires. Given an armed rule with the condition
    `spread_bps > 0.2`, when the metric reads 0.3, then the rule fires, and the saved and reloaded
    rule evaluates identically to the authored one (below, at and just above its threshold too)."""
    doc = _doc("0.2")
    mgr = RulesManager(InMemoryRuleStore(), default_registry())
    try:
        rid = await _armed(mgr, doc)
        (item,) = await mgr.evaluable_rules()
    finally:
        await mgr.stop()
    assert item.mode == "armed"
    assert _evaluate(item.rule, "0.3").fired
    authored = Rule.model_validate({**doc, "rule_id": rid})
    for reading in ("0.1", "0.2", "0.2000000000000000001", "0.3"):
        assert _evaluate(item.rule, reading) == _evaluate(authored, reading), reading


#: Constants no number reads as in a comparison that orders its operands.
UNTYPABLE: list[Any] = [
    "0.2x", "abc", "5%", "NaN", "Infinity", "1_000", " 0.2", "1E+99999", "", True,
]  # fmt: skip


@pytest.mark.parametrize("const", UNTYPABLE, ids=repr)
async def test_an_untypable_constant_is_refused_never_compared_as_text(const: Any) -> None:
    """Scenario: an untypable constant is refused, never compared as text. Given a stored rule
    document whose constant is not a valid Decimal, when the rule is loaded, then the load is
    refused with a typed error and the rule is not evaluated: the evaluator's work list skips it,
    and reading it disarms it as quarantined, its view naming the constant's path."""
    audits: list[tuple[str, dict[str, Any]]] = []

    async def _audit(action: str, payload: dict[str, Any]) -> None:
        audits.append((action, payload))

    mgr = RulesManager(InMemoryRuleStore(), default_registry(), audit=_audit)
    try:
        rid = await _armed(mgr, _doc("0.2"))
        row = await mgr._s.get(rid)
        assert row is not None
        stored = row.versions[0].ir
        stored["conditions"]["right"]["const"] = const
        with pytest.raises(ConstantTypeError) as refused:
            check_constants(Rule.model_validate(stored).conditions)
        assert await mgr.evaluable_rules() == []
        view = await mgr.get(rid, OWNER)
    finally:
        await mgr.stop()
    assert refused.value.loc == ("conditions", "right", "const")
    assert refused.value.reason == NOT_A_NUMBER
    assert quarantine_path(stored) == "/conditions/right/const"
    assert (view["quarantined"], view["mode"]) == (True, "disabled")
    assert view["failing_path"] == "/conditions/right/const"
    assert [p["reason"] for a, p in audits if a == "rule.disarmed"] == ["quarantined"]


def _rule(conditions: dict[str, Any]) -> Rule:
    """`form_simple_0` with `conditions`, as the model reads it."""
    doc: dict[str, Any] = json.loads((FIX / "form_simple_0.json").read_text(encoding="utf-8"))
    return Rule.model_validate({**doc, "conditions": conditions})


def _cmp(op: str, const: Any, left: dict[str, Any] | None = None) -> dict[str, Any]:
    left = {"metric": "spread_bps"} if left is None else left
    return {"node_id": "c1", "op": op, "left": left, "right": {"const": const}}


_WIDEST = "1" + "0" * 63  # a 64-character plain form: the widest number the IR holds
_INDIC = chr(0x661) + chr(0x662)  # Arabic-Indic "12": `Decimal` reads it, the IR does not


@pytest.mark.parametrize(
    ("const", "value"),
    [
        (True, True), (False, False), (5, Decimal(5)), (Decimal("0.2"), Decimal("0.2")),
        ("0.2", Decimal("0.2")), ("-0.2", Decimal("-0.2")), ("2E-7", Decimal("2E-7")),
        ("-5e+3", Decimal(-5000)), ("1.50", Decimal("1.5")), ("+.5", Decimal("0.5")),
        ("5.", Decimal(5)), ("-0", Decimal(0)), (_WIDEST, Decimal(_WIDEST)),
        ("long", "long"), ("5%", "5%"), ("NaN", "NaN"), ("Infinity", "Infinity"),
        (" 0.2", " 0.2"), ("1_000", "1_000"), (_INDIC, _INDIC), ("1e", "1e"),
        (".", "."), ("", ""), (_WIDEST + "0", _WIDEST + "0"), ("1E+99999", "1E+99999"),
    ],
    ids=repr,
)  # fmt: skip
def test_literal_value_reads_a_number_as_a_decimal_and_other_text_as_itself(
    const: Any, value: Any
) -> None:
    got = Literal_(const=const).value()
    assert (got, type(got)) == (value, type(value))


@pytest.mark.parametrize(
    ("op", "const"),
    [("eq", "long"), ("neq", "flat"), ("eq", True), ("changed", "up"), ("eq", "0.2"),
     ("gt", "-5E-7"), ("gt", "+.5"), ("between", 3), ("crosses_above", Decimal("0.1"))],
)  # fmt: skip
def test_check_constants_passes_a_constant_its_place_reads(op: str, const: Any) -> None:
    check_constants(_rule(_cmp(op, const)).conditions)


@pytest.mark.parametrize(
    ("op", "const"),
    [("gte", "abc"), ("lt", False), ("lte", "0.2x"), ("between", "x"), ("outside", True),
     ("crosses_above", "up"), ("crosses_below", "NaN"), ("eq", "5%"), ("neq", "NaN"),
     ("eq", " 1"), ("changed", "Infinity"), ("eq", "1E+99999")],
)  # fmt: skip
def test_check_constants_refuses_a_constant_its_place_cannot_read(op: str, const: Any) -> None:
    with pytest.raises(ConstantTypeError) as refused:
        check_constants(_rule(_cmp(op, const)).conditions)
    assert refused.value.loc == ("conditions", "right", "const")


def test_check_constants_names_the_path_of_a_constant_deep_in_the_rule() -> None:
    """Under `eq`, text is an enum value, but an arithmetic node's operand is a number."""
    product = {"node_id": "x1", "op": "mul", "operands": [{"metric": "spread_bps"}, {"const": "a"}]}
    later = {"node_id": "t1", "op": "sustained_for", "window_ms": 1000,
             "child": _cmp("eq", 1, product) | {"node_id": "c2"}}  # fmt: skip
    conditions = {"node_id": "b1", "op": "any_of", "children": [_cmp("eq", "long"), later]}
    with pytest.raises(ConstantTypeError) as refused:
        check_constants(_rule(conditions).conditions)
    loc = ("conditions", "children", 1, "child", "left", "operands", 1, "const")
    assert refused.value.loc == loc
    assert str(refused.value) == f"{NOT_A_NUMBER} at /" + "/".join(map(str, loc))
    assert refused.value.args == (loc, NOT_A_NUMBER)


@pytest.mark.parametrize(
    ("op", "const", "reading"),
    [("eq", '"0.3"', "0.3"), ("gte", '"0.1"', "0.1"), ("eq", "0.3", "0.3"),
     ("gt", '"0.1000000000000000001"', "0.1000000000000000002"),
     ("lt", '"-0.1000000000000000002"', "-0.1000000000000000003")],
)  # fmt: skip
async def test_a_saved_constant_compares_exactly_never_through_a_float(
    op: str, const: str, reading: str
) -> None:
    """A constant sent as decimal text (or as a JSON number) compares as the number it spells:
    `0.3` equals a reading of 0.3, and digits past a float's precision still order."""
    authored, loaded = await _authored_and_loaded(_doc(const, op))
    assert _evaluate(authored, reading).fired
    assert _evaluate(loaded, reading) == _evaluate(authored, reading)


def test_a_fixture_text_constant_is_read_as_its_number() -> None:
    """`form_simple_0` holds `price > "65000.50"` as text, as the corpus fixtures hold theirs."""
    rule = Rule.model_validate(json.loads((FIX / "form_simple_0.json").read_text(encoding="utf-8")))
    assert _evaluate(rule, "65000.51").fired
    assert not _evaluate(rule, "65000.50").fired


def test_a_stored_alert_condition_reads_its_fractional_threshold_as_a_number() -> None:
    """Alerts share the condition IR and its evaluation: an alert's stored condition (its JSON-mode
    dump) keeps a fractional threshold a number too."""
    authored = AlertCondition.model_validate(
        {"ir_version": 1, "trigger": {"type": "on_price_update"}, "conditions": _cmp("gt", 0.2)}
    )
    stored = AlertCondition.model_validate(authored.model_dump(mode="json", exclude_defaults=True))
    assert stored.model_dump(mode="json")["conditions"]["right"] == {"const": "0.2"}
    snapshot = SnapshotBuilder(_Reading(Decimal("0.3"))).build(
        referenced_metrics(stored.conditions), NOW
    )
    assert evaluate(stored.conditions, EvalContext(snapshot, InstanceState(), NOW, lambda: None))


#: Any number the IR holds: up to 19 digits, scaled by 10^-30..10^30 (every plain form fits in 64
#: characters), so `str()` spells it in each of its forms: `0.00012`, `1.20`, `1.2E+21`, `-0`.
_NUMBERS = st.builds(
    lambda digits, exp: Decimal(f"{digits}E{exp}"),
    st.integers(-(10**19) + 1, 10**19 - 1),
    st.integers(-30, 30),
)
_ORACLE: dict[str, Callable[[Decimal, Decimal], bool]] = {
    "gt": operator.gt, "gte": operator.ge, "lt": operator.lt, "lte": operator.le,
    "eq": operator.eq, "neq": operator.ne,
}  # fmt: skip


@given(const=_NUMBERS, op=st.sampled_from(sorted(_ORACLE)), as_text=st.booleans(), data=st.data())
async def test_save_load_evaluate_equals_evaluate_on_the_authored_rule(
    const: Decimal, op: str, as_text: bool, data: st.DataObject
) -> None:
    """For any number the IR holds, authored as a `Decimal` or as its decimal text, the rule saved
    and loaded evaluates as the authored rule does, at, next to and away from its constant, and
    both fire exactly when the comparison holds."""
    near = (const, const.next_plus(), const.next_minus())
    reading = data.draw(st.one_of(st.sampled_from(near), _NUMBERS), label="reading")
    doc = _doc("0", op)
    doc["conditions"]["right"] = {"const": str(const) if as_text else const}
    authored, loaded = await _authored_and_loaded(doc)
    want = _evaluate(authored, str(reading))
    assert _evaluate(loaded, str(reading)) == want
    assert want.fired is _ORACLE[op](reading, const)
