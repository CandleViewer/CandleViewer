"""E40-S02 (#1130): value formatting is bounded at save and at render, and the served `context`
`values` follow the renderer's scope rule.

At save the compiler refuses a text constant or a listed value over 1,000 characters, a number
wider than the IR's plain width and a list longer than `MAX_SET_VALUES`, each decided before the
value is converted. At render a value is formatted from cheap properties of it (its length, its
bit length), and the restatement stops building text the body could never show.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from candleviewer.alerts.compiler import MAX_SET_VALUES, MAX_TEXT, AlertCompiler
from candleviewer.alerts.delivery_view import public_context
from candleviewer.alerts.errors import AlertIrInvalid
from candleviewer.alerts.models import AlertCondition
from candleviewer.alerts.render import (
    BODY_MAX,
    NO_VALUE,
    VALUE_MAX,
    FiringFacts,
    fmt_value,
    registry_titles,
    render_body,
    restate,
)
from candleviewer.domain.plain_decimal import MAX_PLAIN_WIDTH
from candleviewer.rules.vocabulary import default_registry
from tests.alerts._evaluator_env import T0

COMPILER = AlertCompiler(default_registry())
TITLES = registry_titles(default_registry())
FACTS = FiringFacts("a1", "n", "info", "BTCUSDT", None, T0, {"price": "65012.5"})


def compare(op: str, metric: str, **kw: Any) -> dict[str, Any]:
    node = {"node_id": "c", "op": op, "left": {"metric": metric}, **kw}
    return {"ir_version": 1, "trigger": {"type": "on_price_update"}, "conditions": node}


def with_const(const: Any, op: str = "neq", metric: str = "price") -> dict[str, Any]:
    return compare(op, metric, right={"const": const})


def with_set(values: list[Any]) -> dict[str, Any]:
    return compare("in_set", "market_regime", set_values=values)


def refused(raw: dict[str, Any]) -> AlertIrInvalid:
    with pytest.raises(AlertIrInvalid) as exc:
        COMPILER.compile(raw)
    return exc.value


def stored(raw: dict[str, Any]) -> Any:
    """A condition as a row holds it, not passed through the compiler."""
    return AlertCondition.model_validate(raw).conditions


# --- at save ------------------------------------------------------------------------------


def test_value_formatting_is_bounded_case_1_list_length() -> None:
    COMPILER.compile(with_set([f"v{i}" for i in range(MAX_SET_VALUES)]))
    exc = refused(with_set([f"v{i}" for i in range(MAX_SET_VALUES + 1)]))
    assert exc.reason == "too_large"
    assert [i.field for i in exc.issues] == ["conditions.set_values"]


def test_value_formatting_is_bounded_case_2_listed_value_width() -> None:
    COMPILER.compile(with_set(["v" * MAX_TEXT]))
    exc = refused(with_set(["ok", "v" * (MAX_TEXT + 1)]))
    assert exc.reason == "schema"
    assert [i.field for i in exc.issues] == ["conditions.set_values[1]"]


def test_value_formatting_is_bounded_case_3_list_entries_are_strings() -> None:
    exc = refused(with_set(["ok", 3]))
    assert exc.reason == "action_node"
    assert [i.field for i in exc.issues] == ["conditions.set_values"]


def test_value_formatting_is_bounded_case_4b_text_constant_at_the_bound() -> None:
    COMPILER.compile(with_const("x" * MAX_TEXT, op="eq", metric="market_regime"))


@pytest.mark.parametrize(
    "const",
    ["0" * MAX_TEXT + "1", "1." + "0" * MAX_TEXT, "x" * (MAX_TEXT + 1)],
)
def test_value_formatting_is_bounded_case_4_text_constant_width(const: str) -> None:
    exc = refused(with_const(const))
    assert exc.reason == "schema"
    assert [i.field for i in exc.issues] == ["conditions.right.const"]


@pytest.mark.parametrize(
    "const",
    [10**MAX_PLAIN_WIDTH, -(10 ** (MAX_PLAIN_WIDTH - 1)), 10**4000, 1e300],
    ids=["wide", "wide-negative", "huge", "float"],
)
def test_value_formatting_is_bounded_case_5_number_constant_width(const: Any) -> None:
    exc = refused(with_const(const))
    assert exc.reason == "schema"
    assert [i.field for i in exc.issues] == ["conditions.right.const"]


@pytest.mark.parametrize(
    "const", [10 ** (MAX_PLAIN_WIDTH - 1), -(10 ** (MAX_PLAIN_WIDTH - 2)), 2.5, "65000.5"]
)
def test_value_formatting_is_bounded_case_6_constants_within_width_compile(const: Any) -> None:
    COMPILER.compile(with_const(const))


def test_value_bound_case_13_tolerance_width() -> None:
    COMPILER.compile(
        compare("eq", "price", right={"const": 1}, tolerance=10 ** (MAX_PLAIN_WIDTH - 1))
    )
    exc = refused(compare("eq", "price", right={"const": 1}, tolerance=10**MAX_PLAIN_WIDTH))
    assert exc.reason == "schema"
    assert [i.field for i in exc.issues] == ["conditions.tolerance"]


# --- at render ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "text"),
    [("0" * 200 + "1", NO_VALUE), ("-" + "9" * 200, NO_VALUE), ("x" * 10_000, "x" * VALUE_MAX),
     (10**5000, NO_VALUE), (-(10**5000), NO_VALUE), ("1" * 2 * VALUE_MAX, "1.111111E+127")],
    ids=["zeros", "nines", "text", "int", "negative-int", "at-bound"],
)  # fmt: skip
def test_value_formatting_is_bounded_case_7_formatting_from_length(value: Any, text: str) -> None:
    assert fmt_value(value) == text


def test_value_formatting_is_bounded_case_8_long_list_restated_as_its_head() -> None:
    values = [f"value-{i:05d}" for i in range(50_000)]
    long = restate(stored(with_set(values)), {}, TITLES)
    head = restate(stored(with_set(values[:200])), {}, TITLES)
    assert long == head and len(long) == BODY_MAX


def test_value_formatting_is_bounded_case_9_wide_tree_restated_as_its_head() -> None:
    kids = [compare("in_set", "market_regime", set_values=["v" * 900])["conditions"]
            | {"node_id": f"k{i}"} for i in range(32)]  # fmt: skip
    raw = {"ir_version": 1, "trigger": {"type": "on_price_update"},
           "conditions": {"node_id": "r", "op": "any_of", "children": kids}}  # fmt: skip
    body = render_body("{{alert.condition_summary}}" * 18, stored(raw), FACTS, TITLES)
    assert len(body) == BODY_MAX and body.startswith("Any of: market regime")


def test_value_formatting_is_bounded_case_10_two_children_still_read_either_or() -> None:
    wide = ["v" * MAX_TEXT] * MAX_SET_VALUES
    kids = [compare("in_set", "market_regime", set_values=wide)["conditions"]
            | {"node_id": f"k{i}"} for i in range(2)]  # fmt: skip
    raw = {"ir_version": 1, "trigger": {"type": "on_price_update"},
           "conditions": {"node_id": "r", "op": "any_of", "children": kids}}  # fmt: skip
    assert restate(stored(raw), {}, TITLES).startswith("Either market regime")


@pytest.mark.perf
def test_value_formatting_is_bounded_case_11_stored_wide_values_render_within_budget() -> None:
    widest = stored(with_set(["x" * MAX_TEXT] * MAX_SET_VALUES))
    widest_const = stored(with_const("x" * MAX_TEXT))
    big_list = stored(with_set(["x" * 10] * 400_000))
    big_const = stored(with_const("1." + "0" * 5_000_000))
    start = time.perf_counter()
    for cond in (widest, widest_const, big_list, big_const):
        render_body("", cond, FACTS, TITLES)
        render_body("{{alert.condition_summary}}" * 18, cond, FACTS, TITLES)
    fmt_value(10**100_000)
    fmt_value("9" * 5_000_000)
    assert time.perf_counter() - start < 0.05  # C-2.17: never blocks the loop past 50 ms


@pytest.mark.perf
def test_value_formatting_is_bounded_case_12_widest_accepted_condition_renders_in_budget() -> None:
    """The most the compiler accepts: 32 comparisons (the widest any_of), each a full list of
    full-width text."""
    wide = ["x" * MAX_TEXT] * MAX_SET_VALUES
    kids = [compare("in_set", "market_regime", set_values=wide)["conditions"]
            | {"node_id": f"k{i}"} for i in range(32)]  # fmt: skip
    raw = {"ir_version": 1, "trigger": {"type": "on_price_update"},
           "conditions": {"node_id": "r", "op": "any_of", "children": kids}}  # fmt: skip
    COMPILER.compile(raw)
    cond = stored(raw)
    start = time.perf_counter()
    render_body("{{alert.condition_summary}}" * 18, cond, FACTS, TITLES)
    render_body("", cond, FACTS, TITLES)
    elapsed = time.perf_counter() - start
    print(f"widest-accepted-render-seconds={elapsed:.5f}")
    assert elapsed < 0.05  # C-2.17: never blocks the loop past 50 ms


# --- the served context -------------------------------------------------------------------


def test_public_context_serves_only_values_the_body_may_show() -> None:
    values = {"price": "65012.5", "account_equity": "812.40", "position_qty": "0.5",
              "made_up_metric": "1", "market_regime": "trend"}  # fmt: skip
    got = public_context({"values": values}, TITLES)
    assert got == {"values": {"price": "65012.5", "market_regime": "trend"}}
    assert public_context({"values": values}) == {"values": {}}  # no registry: none served
