# ruff: noqa: RUF001  (look-alike unicode is the point of these tests)
"""E40-T02: notify-only alert compiler - accept/reject matrix, triggers, hash, templates."""

from __future__ import annotations

import copy
from typing import Any, get_args

import pytest
from pydantic import BaseModel

from candleviewer.alerts.compiler import (
    ACTION_TYPES,
    MAX_NODES,
    PERMITTED_KINDS,
    AlertCompiler,
)
from candleviewer.alerts.errors import AlertIrInvalid
from candleviewer.rules.ir import (
    ArithmeticNode,
    BooleanNode,
    Comparison,
    Literal_,
    MetricRef,
    Rule,
    RuleLimits,
    TemporalNode,
    Trigger,
)
from candleviewer.rules.ir.models import ActionType
from candleviewer.rules.vocabulary import default_registry

COMPILER = AlertCompiler(default_registry())


def price_cross(**over: Any) -> dict[str, Any]:
    """The OpenAPI `priceCross` example, with `price` (the registry name for last price)."""
    return {
        "ir_version": 1,
        "trigger": {"type": "on_price_update", "debounce_ms": 250},
        "conditions": {
            "node_id": "c1",
            "op": "crosses_above",
            "left": {"metric": "price"},
            "right": {"const": 64000},
        },
    } | over


def reject(raw: Any) -> AlertIrInvalid:
    with pytest.raises(AlertIrInvalid) as exc:
        COMPILER.compile(raw)
    return exc.value


def test_compile_price_cross_ok_populates_hash() -> None:
    out = COMPILER.compile(price_cross())
    assert len(out.condition_hash) == 64 and out.metrics == ("price",)
    assert out.estimated_metrics == () and "actions" not in out.condition_ir


def test_compile_actions_key_at_root_rejected_as_action_node() -> None:
    raw = price_cross(actions=[{"node_id": "a1", "type": "place_order", "params": {}}])
    err = reject(raw)
    assert err.reason == "action_node" and err.issues[0].field == "condition_ir.actions"


def test_compile_action_nested_in_variables_rejected() -> None:
    act = {"node_id": "a9", "type": "place_order", "params": {"side": "buy"}}
    err = reject(price_cross(variables={"x": act}))
    assert err.reason == "action_node" and err.issues[0].node_id == "a9"


@pytest.mark.parametrize("tail", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_compile_a_variable_name_ending_in_a_newline_is_rejected(tail: str) -> None:
    """#3555: `$` also matches before a final newline, so `match` took the name."""
    out = COMPILER.compile(price_cross(variables={"v": {"const": 1}}))
    assert out.condition_ir["variables"] == {"v": {"const": 1}}
    err = reject(price_cross(variables={"v" + tail: {"const": 1}}))
    assert (err.reason, err.issues[0].rule) == ("action_node", "not_permitted")
    assert err.issues[0].field == f"variables.v{tail}"


def test_compile_action_as_operand_rejected_with_node_id() -> None:
    raw = price_cross()
    raw["conditions"]["right"] = {"node_id": "a2", "type": "flatten_all_positions", "params": {}}
    err = reject(raw)
    assert err.reason == "action_node" and err.issues[0].node_id == "a2"


def test_compile_action_hidden_in_logical_children_rejected() -> None:
    leaf = price_cross()["conditions"]
    act = {"node_id": "a3", "op": "gt", "type": "place_order", "left": {"const": 1}}
    raw = price_cross(conditions={"node_id": "b1", "op": "all_of", "children": [leaf, act]})
    assert reject(raw).issues[0].node_id == "a3"


LOOKALIKE_KEYS = [
    "Actions",
    "action",
    "then",
    "on_fire",
    "\u0430ctions",
    "actions\u200b",
    "\uff41ctions",
]
LOOKALIKE_OPS = ["gt\u200b", "\u0261t", "GT", "place_order", "\u0430ll_of"]


@pytest.mark.parametrize("key", LOOKALIKE_KEYS)
def test_compile_renamed_or_lookalike_root_keys_rejected(key: str) -> None:
    assert reject(price_cross(**{key: []})).reason == "action_node"


@pytest.mark.parametrize("op", LOOKALIKE_OPS)
def test_compile_lookalike_ops_rejected(op: str) -> None:
    raw = price_cross()
    raw["conditions"]["op"] = op
    assert reject(raw).reason == "action_node"


def test_compile_action_in_metric_params_rejected() -> None:
    raw = price_cross()
    raw["conditions"]["left"]["params"] = {"then": {"type": "place_order"}}
    assert reject(raw).reason == "action_node"


@pytest.mark.parametrize(
    "raw",
    [
        [],
        "x",
        None,
        {"ir_version": 1, "trigger": [], "conditions": {}},
        {"ir_version": 1, "limits": [1]},
        {"ir_version": 1, "trigger": {"type": {"x": 1}}},
        {"ir_version": {"x": 1}},
        {"ir_version": 1, "variables": {"Bad-Name": {"const": 1}}},
    ],
)
def test_compile_malformed_shapes_fail_closed(raw: Any) -> None:
    reject(raw)


def test_compile_bad_children_and_operands_containers_rejected() -> None:
    reject(price_cross(conditions={"node_id": "b", "op": "any_of", "children": {"a": 1}}))
    raw = price_cross()
    raw["conditions"]["left"] = {"node_id": "m", "op": "add", "operands": {"a": 1}}
    reject(raw)
    raw["conditions"]["left"] = {"node_id": "m", "op": "frobnicate"}
    reject(raw)
    raw = price_cross()
    raw["conditions"]["set_values"] = [{"a": 1}]
    reject(raw)


def test_compile_oversized_tree_rejected_as_too_large() -> None:
    leaf = price_cross()["conditions"]
    kids = [dict(leaf, node_id=f"c{i}") for i in range(32)]
    tree: dict[str, Any] = {"node_id": "r", "op": "any_of", "children": kids}
    wide = {"node_id": "top", "op": "any_of", "children": [copy.deepcopy(tree)] * 32}
    assert reject(price_cross(conditions=wide)).reason == "too_large"
    deep: dict[str, Any] = leaf
    for i in range(40):
        deep = {"node_id": f"t{i}", "op": "sustained_for", "child": deep, "window_ms": 1000}
    assert reject(price_cross(conditions=deep)).reason == "too_large"
    assert MAX_NODES >= 100


@pytest.mark.parametrize(
    "trigger",
    [
        {"type": "on_bar_close", "timeframe": "1٣m"},
        {"type": "on_bar_close", "timeframe": "9999w"},
        {"type": "on_bar_close", "timeframe": "7m"},
        {"type": "on_schedule", "cron": "٠ 9 * * 1-5"},
        {"type": "on_schedule", "cron": "0 9 * * 1-٥"},
    ],
)
def test_trigger_non_ascii_digits_and_unsupported_timeframe_rejected(
    trigger: dict[str, Any],
) -> None:
    assert reject(price_cross(trigger=trigger)).reason == "bad_trigger"


def test_oversized_children_list_is_too_large_not_action_node() -> None:
    kids = [{"bogus": 1}] * (MAX_NODES + 88)
    raw = price_cross(conditions={"node_id": "r", "op": "all_of", "children": kids})
    assert reject(raw).reason == "too_large"


@pytest.mark.parametrize("key", ["actions", "Actions", "ａctions", "actions​"])
def test_lookalike_actions_key_inside_operand_rejected(key: str) -> None:
    raw = price_cross()
    raw["conditions"]["left"][key] = [{"type": "place_order"}]
    assert reject(raw).reason == "action_node"


# ----- node-kind enumeration (ticket: adding an E35 kind must fail E40 tests) ---------------
def test_every_e35_action_type_is_outside_the_allow_list() -> None:
    assert set(get_args(ActionType)) == ACTION_TYPES
    permitted_keys = set().union(*PERMITTED_KINDS.values())
    assert "actions" not in permitted_keys
    for t in ACTION_TYPES:
        act = {"node_id": "a1", "type": t, "params": {}}
        assert reject(price_cross(variables={"v": act})).reason == "action_node"
        assert reject(price_cross(actions=[act])).reason == "action_node"


def test_permitted_kinds_cover_exactly_the_e35_condition_models() -> None:
    models: dict[str, type[BaseModel]] = {
        "comparison": Comparison,
        "logical": BooleanNode,
        "temporal": TemporalNode,
        "operand:metric": MetricRef,
        "operand:const": Literal_,
        "operand:arith": ArithmeticNode,
        "trigger": Trigger,
        "limits": RuleLimits,
    }
    for kind, model in models.items():
        assert frozenset(model.model_fields) == PERMITTED_KINDS[kind], kind
    rule_fields = set(Rule.model_fields)
    assert rule_fields | {"variables"} >= PERMITTED_KINDS["root"]
    assert "actions" in rule_fields - PERMITTED_KINDS["root"]


# ----- triggers ------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "trigger",
    [
        {"type": "on_bar_close", "timeframe": "5m"},
        {"type": "on_timer", "interval_ms": 100},
        {"type": "on_schedule", "cron": "0 9 * * 1-5"},
        {"type": "on_schedule", "cron": "*/15 0-23 1,15 * *"},
        {"type": "on_metric_change", "metric": "spread_bps"},
    ],
)
def test_compile_valid_triggers(trigger: dict[str, Any]) -> None:
    COMPILER.compile(price_cross(trigger=trigger))


@pytest.mark.parametrize(
    ("trigger", "reason"),
    [
        ({"type": "on_bar_close"}, "bad_trigger"),
        ({"type": "on_bar_close", "timeframe": "5 minutes"}, "bad_trigger"),
        ({"type": "on_timer", "interval_ms": 99}, "bad_trigger"),
        ({"type": "on_timer"}, "bad_trigger"),
        ({"type": "on_schedule", "cron": "0 9 * *"}, "bad_trigger"),
        ({"type": "on_schedule", "cron": "61 9 * * *"}, "bad_trigger"),
        ({"type": "on_schedule", "cron": "0 9 * * MON"}, "bad_trigger"),
        ({"type": "on_schedule", "cron": "0 9-3 * * *"}, "bad_trigger"),
        ({"type": "on_schedule", "cron": "*/0 * * * *"}, "bad_trigger"),
        ({"type": "on_schedule"}, "bad_trigger"),
        ({"type": "on_metric_change"}, "bad_trigger"),
        ({"type": "on_metric_change", "metric": "nope_metric"}, "unknown_metric"),
    ],
)
def test_compile_invalid_triggers(trigger: dict[str, Any], reason: str) -> None:
    assert reject(price_cross(trigger=trigger)).reason == reason


@pytest.mark.parametrize("tail", ["\n", "\r\n"], ids=["lf", "crlf"])
@pytest.mark.parametrize("cron", ["0 9 * * 1-5{}", "0{} 9 * * 1-5", "*/15 0-23 1,15{} * *"])
def test_compile_a_cron_atom_ending_in_a_newline_is_rejected(cron: str, tail: str) -> None:
    """#3555: `$` also matches before a final newline, so `match` took an atom that ends in one
    (the last field's, or one in the middle of the expression, or one of a comma list)."""
    COMPILER.compile(price_cross(trigger={"type": "on_schedule", "cron": cron.format("")}))
    trigger = {"type": "on_schedule", "cron": cron.format(tail)}
    assert reject(price_cross(trigger=trigger)).reason == "bad_trigger"
