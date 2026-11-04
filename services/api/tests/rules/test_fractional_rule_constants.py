"""#5807: a rule constant keeps its number through a save and a load.

A rule is authored as the routes read a body (`json.loads`: a fractional JSON number arrives as a
float, which the IR reads as a `Decimal`), saved through `RulesManager.create` (a version stores
the IR's JSON-mode dump), loaded as the evaluator's work list loads it
(`RulesManager.evaluable_rules`) and evaluated. The in-memory store keeps the dumped document as it
is; the Postgres store writes it as JSON text and reads it back with `json.loads`, so both stores
hand the load the same document.

The dump writes a `Decimal` constant as its text (`"0.2"`), so the evaluator reads decimal text as
the number it spells (`Literal_.value`, read once per load). A constant it cannot read as its place
needs is refused at save (the validator runs `check_constants`) and at load (`quarantine_path`, and
an alert's load), and never evaluated.
"""

from __future__ import annotations

import json
import operator
import statistics
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.alerts.compiler import AlertCompiler
from candleviewer.alerts.errors import AlertIrInvalid
from candleviewer.alerts.models import AlertCondition
from candleviewer.rules.compiler import to_form_model
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
from candleviewer.rules.ir import Literal_, MetricRef, Rule, ir_hash
from candleviewer.rules.ir.models import DECIMAL_TEXT, MAX_NUMBER_TEXT, decimal_text
from candleviewer.rules.manager import (
    Actor,
    InMemoryRuleStore,
    RuleError,
    RulesManager,
    quarantine_path,
)
from candleviewer.rules.validator import TEXT_TOO_LONG, validate_rule
from candleviewer.rules.vocabulary import default_registry
from tests.alerts._evaluator_env import Row, make, row
from tests.alerts._evaluator_env import ir as alert_ir
from tests.rules.test_validator_endpoints import (
    _PERF_SAMPLES,
    RULE_ID,
    _assert_median_within,
    _client,
    _jsonable,
    _sample_ms,
)

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

    def __init__(self, value: Decimal | str) -> None:
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
    "0.2x", "abc", "5%", "NaN", "Infinity", "1_000", " 0.2", "1E+99999", "1E+9999999999999999999",
    "", True,
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
        with pytest.raises(RuleError) as rearm:  # arming refuses it too
            await mgr.set_mode(rid, "simulate", OWNER, "k-again")
    finally:
        await mgr.stop()
    assert (rearm.value.status, rearm.value.code) == (422, "rule_invalid")
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
_HUGE, _TINY = "1E+9999999999999999999", "1E-9999999999999999999"  # past the `decimal` module
_EXACT = "0.1" + "0" * 29 + "1"  # 31 significant digits: past the context's 28
# The bound is exact: text of `MAX_NUMBER_TEXT` characters is read, one more character is not.
_AT_BOUND = "1." + "0" * (MAX_NUMBER_TEXT - 2)  # a number the IR holds, in that many characters
_PADDED = _AT_BOUND + "0"  # the same number, one character past the bound
_WIDE = "1" * MAX_NUMBER_TEXT  # decimal text past the IR's range, in that many characters


@pytest.mark.parametrize(
    ("const", "value"),
    [
        (True, True), (False, False), (5, Decimal(5)), (Decimal("0.2"), Decimal("0.2")),
        ("0.2", Decimal("0.2")), ("-0.2", Decimal("-0.2")), ("2E-7", Decimal("2E-7")),
        ("-5e+3", Decimal(-5000)), ("1.50", Decimal("1.5")), ("+.5", Decimal("0.5")),
        ("5.", Decimal(5)), ("-0", Decimal(0)), (_WIDEST, Decimal(_WIDEST)),
        (_EXACT, Decimal(_EXACT)),
        ("long", "long"), ("5%", "5%"), ("NaN", "NaN"), ("Infinity", "Infinity"),
        (" 0.2", " 0.2"), ("1_000", "1_000"), (_INDIC, _INDIC), ("1e", "1e"),
        (".", "."), ("", ""), (_WIDEST + "0", _WIDEST + "0"), ("1E+99999", "1E+99999"),
        (_HUGE, _HUGE), (_TINY, _TINY), (_PADDED, _PADDED),
        pytest.param(_AT_BOUND, Decimal(1), id="a-number-at-the-bound"),
    ],
    ids=repr,
)  # fmt: skip
def test_literal_value_reads_a_number_as_a_decimal_and_other_text_as_itself(
    const: Any, value: Any
) -> None:
    got = Literal_(const=const).value
    assert (got, type(got)) == (value, type(value))


@pytest.mark.parametrize(
    ("op", "const"),
    [("eq", "long"), ("neq", "flat"), ("eq", True), ("changed", "up"), ("eq", "0.2"),
     ("gt", "-5E-7"), ("gt", "+.5"), ("between", 3), ("crosses_above", Decimal("0.1")),
     ("eq", _PADDED),  # past the bound, text is an enum value, never parsed
     pytest.param("eq", _WIDE + "1", id="eq-wide-one-past-the-bound")],
)  # fmt: skip
def test_check_constants_passes_a_constant_its_place_reads(op: str, const: Any) -> None:
    check_constants(_rule(_cmp(op, const)).conditions)


@pytest.mark.parametrize(
    ("op", "const"),
    [("gte", "abc"), ("lt", False), ("lte", "0.2x"), ("between", "x"), ("outside", True),
     ("crosses_above", "up"), ("crosses_below", "NaN"), ("crosses_below", "up"), ("eq", "5%"),
     ("neq", "NaN"), ("eq", " 1"), ("changed", "Infinity"), ("eq", "1E+99999"), ("eq", _HUGE),
     ("neq", _TINY), ("gt", _HUGE), ("gt", _PADDED),
     pytest.param("eq", _WIDE, id="eq-wide-at-the-bound")],
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


_FIRST = {"node_id": "x1", "op": "mul", "operands": [{"const": "a"}, {"metric": "spread_bps"}]}


@pytest.mark.parametrize(
    ("conditions", "loc"),
    [(_cmp("between", 1) | {"right2": {"const": "abc"}}, ("right2",)),
     (_cmp("outside", 1) | {"right2": {"const": "5%"}}, ("right2",)),
     (_cmp("eq", 1, _FIRST), ("left", "operands", 0))],
    ids=["between-right2", "outside-right2", "first-operand"],
)  # fmt: skip
def test_check_constants_refuses_an_upper_bound_and_a_first_operand(
    conditions: dict[str, Any], loc: tuple[str | int, ...]
) -> None:
    with pytest.raises(ConstantTypeError) as refused:
        check_constants(_rule(conditions).conditions)
    assert refused.value.loc == ("conditions", *loc, "const")


@pytest.mark.parametrize(
    ("op", "const", "reading"),
    [("eq", '"0.3"', "0.3"), ("gte", '"0.1"', "0.1"), ("eq", "0.3", "0.3"),
     ("gt", '"0.1000000000000000001"', "0.1000000000000000002"),
     ("lt", '"-0.1000000000000000002"', "-0.1000000000000000003"),
     ("lt", f'"{_EXACT}"', "0.1" + "0" * 30 + "5")],  # between it and its 28-digit rounding
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


async def test_a_constant_past_the_decimal_range_skips_only_its_own_rule() -> None:
    """A stored constant the `decimal` module cannot construct quarantines its own rule; the work
    list still holds the sound rule beside it."""
    mgr = RulesManager(InMemoryRuleStore(), default_registry())
    try:
        ids = [(await mgr.create(_doc("0.2") | {"name": n}, OWNER))["id"] for n in ("a", "b")]
        for rid in ids:
            await mgr.set_mode(rid, "simulate", OWNER, f"k-{rid}")
        row = await mgr._s.get(ids[1])
        assert row is not None
        row.versions[0].ir["conditions"]["right"]["const"] = _TINY
        items = await mgr.evaluable_rules()
    finally:
        await mgr.stop()
    assert [str(i.rule.rule_id) for i in items] == [str(ids[0])]


async def test_a_loaded_constant_is_read_once_however_often_it_is_evaluated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A constant's read is bounded and done once per load: evaluating the loaded rule again, at
    another reading and by another evaluator, reads nothing again."""
    _, loaded = await _authored_and_loaded(_doc('"0.2"'))
    reads: list[str] = []

    def counting(text: str) -> Decimal | None:
        reads.append(text)
        return decimal_text(text)

    monkeypatch.setattr("candleviewer.rules.ir.models.decimal_text", counting)
    for reading in ("0.1", "0.3", "0.2"):
        _evaluate(loaded, reading)
    assert reads == ["0.2"]


def test_reading_the_constants_leaves_the_dump_and_the_hash_as_they_were() -> None:
    """The read is cached outside the model's fields: the dump, the content hash and equality are
    the unread rule's, and a literal keeps its hash and stays frozen."""
    doc = json.loads((FIX / "form_simple_0.json").read_text(encoding="utf-8"))
    rule, unread = Rule.model_validate(doc), Rule.model_validate(doc)
    check_constants(rule.conditions)  # reads, and caches, every constant
    assert (rule.model_dump_json(), ir_hash(rule)) == (unread.model_dump_json(), ir_hash(unread))
    assert rule == unread
    lit = Literal_(const="0.2")
    before = hash(lit)
    assert (lit.value, hash(lit)) == (Decimal("0.2"), before)
    with pytest.raises(ValueError, match="frozen"):  # read, and still frozen
        lit.__setattr__("const", "0.3")


@pytest.mark.parametrize("deep", [False, True], ids=["shallow", "deep"])
def test_a_copy_that_sets_the_constant_reads_the_new_one(deep: bool) -> None:
    """The cached read belongs to its instance: a copy given another `const` reads that one, and
    the literal it was copied from keeps its own."""
    lit = Literal_(const="0.2")
    assert lit.value == Decimal("0.2")  # read, and cached
    moved = lit.model_copy(update={"const": "0.3"}, deep=deep)
    assert (moved.value, lit.value) == (Decimal("0.3"), Decimal("0.2"))


def test_no_enum_value_of_the_vocabulary_is_decimal_text() -> None:
    """An enum value compares as text, so none may spell a number the read would take; each one
    passes the load check under `eq`."""
    enums = [(d.name, v) for d in default_registry() for v in d.enum_values]
    assert enums
    for metric, v in enums:
        assert decimal_text(v) is None, (metric, v)
        check_constants(_rule(_cmp("eq", v, {"metric": metric})).conditions)


def _quotient(const: Any) -> dict[str, Any]:
    return {"node_id": "x1", "op": "div", "operands": [{"metric": "spread_bps"}, {"const": const}]}


@pytest.mark.parametrize("const", ["5%", "NaN", "1_000", "1E+9999999999999999999999999"])
@pytest.mark.parametrize("beside", [True, False], ids=["beside-a-product", "in-a-quotient"])
async def test_a_save_refuses_a_constant_the_evaluator_cannot_read(
    const: str, beside: bool
) -> None:
    """The unit checks read `5%`, `NaN` and `1_000` as numbers, and a product or a quotient as any
    unit; the save runs the load's check, so it refuses what the load would quarantine."""
    doc = _doc("0")
    product = _quotient(1) | {"op": "mul"}
    doc["conditions"] = _cmp("neq", const, product) if beside else _cmp("gt", 1, _quotient(const))
    mgr = RulesManager(InMemoryRuleStore(), default_registry())
    try:
        with pytest.raises(RuleError) as refused:
            await mgr.create(doc, OWNER)
    finally:
        await mgr.stop()
    field = "conditions.right" if beside else "conditions.left.operands[1]"
    issue = {"field": field, "rule": "type_mismatch", "message": NOT_A_NUMBER}
    assert (refused.value.code, refused.value.extra["errors"]) == ("rule_ir_invalid", [issue])


def test_an_alert_save_refuses_a_constant_the_evaluator_cannot_read() -> None:
    """The alert compiler runs the same validator: `5%` beside a product, which the unit checks
    take for a number, is refused when the alert is saved, not parked when it is loaded."""
    raw = {
        "ir_version": 1,
        "trigger": {"type": "on_price_update"},
        "conditions": _cmp("neq", "5%", _quotient(1) | {"op": "mul"}),
    }
    with pytest.raises(AlertIrInvalid) as refused:
        AlertCompiler(default_registry()).compile(raw)
    assert refused.value.reason == "schema"
    issue = ("conditions.right", "type_mismatch", NOT_A_NUMBER)
    assert [(i.field, i.rule, i.message) for i in refused.value.issues] == [issue]


async def test_an_alert_whose_constant_its_place_cannot_read_is_parked_at_load() -> None:
    """Alerts share the evaluator, so their load runs the rules' check: a stored alert holding such
    a constant is never subscribed, and a sound one beside it is."""
    parked = alert_ir("gt")
    parked["conditions"]["right"] = {"const": "5%"}
    ev, *_ = make(row("sound"), Row("parked", condition_ir=parked, condition_hash="h-parked"))
    await ev.warm_up()
    assert list(ev.alerts) == ["sound"]
    assert [s.members for s in ev.subscriptions.values()] == [{"sound"}]


#: A text constant is an enum value, so it sits beside a metric of enum unit, where `eq` takes text.
_SIDE = {"metric": "imbalance_zone_side"}
#: How a text constant past the bound is refused: the validator's issue at the constant, as
#: `(path, code, message)`; the validator files it under class `syntax`.
_TEXT_ISSUE = ("conditions.right", "schema_error", TEXT_TOO_LONG)


def _text_doc(length: int, char: str = "x") -> dict[str, Any]:
    """`form_simple_0` with the condition `imbalance_zone_side eq <text of `length` characters>`."""
    return _doc("0") | {"conditions": _cmp("eq", char * length, _SIDE)}


@pytest.mark.parametrize("char", ["x", "é"], ids=["one-byte", "two-byte"])
async def test_a_save_takes_a_text_constant_of_the_bound_and_refuses_one_more(char: str) -> None:
    """A text constant holds at most `MAX_NUMBER_TEXT` characters, counted as characters (a
    validation limit, 22 `RuleOperand`): create and update take exactly that many and refuse one
    more with the validator's issue at the constant, with no record and no count."""
    records: list[str] = []

    async def _audit(action: str, payload: dict[str, Any]) -> None:
        records.append(action)

    mgr = RulesManager(
        InMemoryRuleStore(), default_registry(), audit=_audit,
        on_metric=lambda name, labels: records.append(name),
    )  # fmt: skip
    try:
        await mgr.create(_text_doc(MAX_NUMBER_TEXT, char) | {"name": "at-the-bound"}, OWNER)
        rid = (await mgr.create(_text_doc(3, char), OWNER))["id"]
        await mgr.update(rid, _text_doc(MAX_NUMBER_TEXT, char), 1, OWNER)
        taken = list(records)
        with pytest.raises(RuleError) as created:
            await mgr.create(_text_doc(MAX_NUMBER_TEXT + 1, char) | {"name": "past"}, OWNER)
        with pytest.raises(RuleError) as updated:
            await mgr.update(rid, _text_doc(MAX_NUMBER_TEXT + 1, char), 2, OWNER)
    finally:
        await mgr.stop()
    issue = dict(zip(("field", "rule", "message"), _TEXT_ISSUE, strict=True))
    for refused in (created.value, updated.value):
        assert (refused.code, refused.extra["errors"]) == ("rule_ir_invalid", [issue])
    assert records == taken


def test_validate_and_compile_hold_a_text_constant_to_the_bound() -> None:
    """`/rules/validate` and `/rules/{id}/compile` answer 200: no issue at exactly the bound, and
    past it the one issue (`valid: false` and `blocks_arming: true`)."""
    client = _client()
    for length, want in ((MAX_NUMBER_TEXT, []), (MAX_NUMBER_TEXT + 1, [(*_TEXT_ISSUE, "syntax")])):
        doc = _text_doc(length)
        model = _jsonable(to_form_model(Rule.model_validate(doc)))
        validated = client.post("/rules/validate", json={"ir": doc}).json()
        body = {"editor": "form", "model": model}
        compiled = client.post(f"/rules/{RULE_ID}/compile", json=body).json()
        for answer, key in ((validated, "errors"), (compiled, "issues")):
            got = [(i["path"], i["code"], i["message"], i["class"]) for i in answer[key]]
            assert [g for g in got if g[1] == "schema_error"] == want
        assert (validated["valid"], compiled["blocks_arming"]) == (not want, bool(want))


def test_the_alert_compiler_holds_a_text_constant_to_the_bound() -> None:
    """The alert compiler runs the same validator: exactly the bound compiles, one more is refused
    with the same issue."""

    def alert(length: int) -> dict[str, Any]:
        conditions = _cmp("eq", "x" * length, _SIDE)
        return {"ir_version": 1, "trigger": {"type": "on_price_update"}, "conditions": conditions}

    compiler = AlertCompiler(default_registry())
    compiler.compile(alert(MAX_NUMBER_TEXT))
    with pytest.raises(AlertIrInvalid) as refused:
        compiler.compile(alert(MAX_NUMBER_TEXT + 1))
    assert refused.value.reason == "schema"
    assert [(i.field, i.rule, i.message) for i in refused.value.issues] == [_TEXT_ISSUE]


def test_a_text_constant_past_the_bound_is_refused_for_its_length_alone() -> None:
    """The text is never read for its unit: `gt` against a long text is the one issue, not also a
    mismatch of units."""
    doc = _doc("0") | {"conditions": _cmp("gt", "x" * (MAX_NUMBER_TEXT + 1))}
    res = validate_rule(Rule.model_validate(doc), default_registry())
    assert [(i.path, i.code, i.message) for i in res.errors] == [_TEXT_ISSUE]


async def test_a_stored_text_constant_past_the_bound_is_still_read_as_an_enum_value() -> None:
    """The bound is a validation limit, not a load rule: an armed rule stored with text past it
    keeps loading, is not quarantined, and reads its constant as the enum value it spells."""
    mgr = RulesManager(InMemoryRuleStore(), default_registry())
    try:
        rid = await _armed(mgr, _text_doc(3))
        row = await mgr._s.get(rid)
        assert row is not None
        stored = row.versions[0].ir
        stored["conditions"]["right"]["const"] = text = "x" * (MAX_NUMBER_TEXT + 1)
        (item,) = await mgr.evaluable_rules()
        view = await mgr.get(rid, OWNER)
    finally:
        await mgr.stop()
    assert quarantine_path(stored) is None
    assert (view["read_only"], view["mode"]) == (False, "armed")
    ev = Evaluator(item.rule, SnapshotBuilder(_Reading(text)), lambda: NOW, lambda: 0)
    assert ev.on_trigger(INSTANCE, "on_price_update").fired


async def test_arming_a_stored_text_constant_past_the_bound_needs_it_shortened() -> None:
    """Arming runs the validator, as it does for any current validation error: a simulating rule
    stored with text past the bound is refused until a save shortens it."""
    mgr = RulesManager(InMemoryRuleStore(), default_registry())
    try:
        made = await mgr.create(_text_doc(3), OWNER)
        rid = str(made["id"])
        await mgr.set_mode(rid, "simulate", OWNER, "k-sim")
        await mgr.record_simulation(rid, made["version"]["ir_hash"], 5, 0.0)
        row = await mgr._s.get(rid)
        assert row is not None
        row.versions[0].ir["conditions"]["right"]["const"] = "x" * (MAX_NUMBER_TEXT + 1)
        with pytest.raises(RuleError) as arming:
            await mgr.set_mode(rid, "armed", OWNER, "k-arm")
    finally:
        await mgr.stop()
    assert (arming.value.status, arming.value.code) == (422, "rule_invalid")


#: An enum constant as long as a rule body holds, digits and then a letter, so a read that scans it
#: scans it to its end. A save refuses it (a text constant holds at most `MAX_NUMBER_TEXT`); a
#: version stored before that is held to the body bound alone, 2,000,000 bytes, and is read.
_LONG = "1" * 1_990_000 + "x"


@pytest.mark.perf
def test_a_long_constant_is_read_within_the_perf_budget() -> None:
    """A constant's read is bounded: the load check of a rule whose enum constant fills the body
    costs at most twice the schema validation it starts with, plus 5 ms; the check of a fresh
    load, and one evaluation of one (its first, which reads the constant), stay within 5 ms."""
    ir = _rule(_cmp("eq", _LONG, {"metric": "imbalance_zone_side"})).model_dump(mode="json")
    validate = statistics.median(_sample_ms(lambda: Rule.model_validate(ir)))
    _assert_median_within(lambda: quarantine_path(ir), budget_ms=2 * validate + 5)
    loads = [Rule.model_validate(ir) for _ in range(2 * (_PERF_SAMPLES + 1))]
    _assert_median_within(lambda: check_constants(loads.pop().conditions), budget_ms=5)
    _assert_median_within(lambda: _evaluate(loads.pop(), "1"), budget_ms=5)


@pytest.mark.perf
def test_the_decimal_text_match_never_backtracks() -> None:
    """The bound caps one read and the match caps many: at the bound, text that fails at its last
    character costs under three times what matching text does, so a rule of many constants at the
    bound costs what one of numbers does."""

    def cost(text: str) -> float:
        work = [text] * 960
        return statistics.median(_sample_ms(lambda: [DECIMAL_TEXT.fullmatch(t) for t in work]))

    fails, matches = cost("1" * (MAX_NUMBER_TEXT - 1) + "x"), cost("1" * MAX_NUMBER_TEXT)
    assert fails < 3 * matches, (fails, matches)
