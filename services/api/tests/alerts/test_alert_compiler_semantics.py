# ruff: noqa: RUF001  (look-alike unicode is the point of these tests)
"""E40-T02: metric resolution, estimated flag, shared condition_hash and template allow-list."""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.alerts.compiler import AlertCompiler, validate_template
from candleviewer.alerts.errors import AlertIrInvalid
from candleviewer.rules.ir import Rule
from candleviewer.rules.ir.canonical import condition_hash
from candleviewer.rules.vocabulary import default_registry

COMPILER = AlertCompiler(default_registry())


def price_cross(**over: Any) -> dict[str, Any]:
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


def test_compile_unknown_metric_names_metric_node_and_suggestions() -> None:
    raw = price_cross()
    raw["conditions"]["left"] = {"metric": "last_price"}
    issue = reject(raw).issues[0]
    assert issue.rule == "unknown_metric" and issue.node_id == "c1"
    assert "last_price" in issue.message and "price" in issue.suggestions
    assert issue.to_dict()["suggestions"] == list(issue.suggestions)


def test_compile_unknown_metric_without_close_match_has_no_hint() -> None:
    raw = price_cross()
    raw["conditions"]["left"] = {"metric": "qqqqqqqqqqqq"}
    issue = reject(raw).issues[0]
    assert issue.suggestions == () and "Did you mean" not in issue.message
    assert "suggestions" not in issue.to_dict()


def test_compile_unknown_metric_in_variables_and_arith() -> None:
    arith = {"node_id": "x1", "op": "add", "operands": [{"metric": "zzz_unknown"}, {"const": 1}]}
    issue = reject(price_cross(variables={"v": arith})).issues[0]
    assert issue.node_id == "x1" and issue.field.startswith("variables.v")


def test_compile_semantic_error_from_e35_validator_surfaces() -> None:
    raw = price_cross()
    raw["conditions"]["op"] = "between"
    err = reject(raw)
    assert err.reason == "schema" and err.issues


def test_compile_schema_error_from_pydantic_surfaces() -> None:
    raw = price_cross()
    raw["conditions"]["node_id"] = 5
    err = reject(raw)
    assert err.reason == "schema" and err.issues[0].rule == "schema_error"


def test_compile_flags_estimated_detector_metrics() -> None:
    raw = price_cross(
        conditions={"node_id": "c1", "op": "is_true", "left": {"metric": "absorption"}}
    )
    assert COMPILER.compile(raw).estimated_metrics == ("absorption",)


def test_condition_hash_equal_for_rule_and_alert_with_same_condition() -> None:
    alert = price_cross()
    rule = Rule.model_validate(
        {
            "rule_id": "00000000-0000-4000-8000-000000000001",
            "version": 3,
            "name": "r",
            "enabled": True,
            "mode": "simulate",
            "scope": {"level": "global"},
            "trigger": alert["trigger"],
            "conditions": dict(alert["conditions"], node_id="zz"),
            "actions": [{"node_id": "a1", "type": "place_order", "params": {}}],
        }
    )
    assert COMPILER.compile(alert).condition_hash == condition_hash(rule.model_dump())


def test_condition_hash_ignores_key_order_and_node_ids_but_not_values() -> None:
    a = COMPILER.compile(price_cross()).condition_hash
    raw = price_cross()
    raw["conditions"] = dict(reversed(list(raw["conditions"].items())), node_id="other")
    assert COMPILER.compile(raw).condition_hash == a
    raw["conditions"]["right"] = {"const": 64001}
    assert COMPILER.compile(raw).condition_hash != a


def test_template_allow_listed_namespaces_ok() -> None:
    tpl = "{{market.last_price}} {{ footprint.sell_stack_size }} {{position.side}} {{alert.name}}"
    assert validate_template(tpl) == (
        "market.last_price",
        "footprint.sell_stack_size",
        "position.side",
        "alert.name",
    )
    assert validate_template("no placeholders") == ()


@pytest.mark.parametrize(
    "tpl",
    [
        "{{secrets.api_key}}",
        "{{env.PATH}}",
        "{{market}}",
        "{{alert.webhook_url}}",
        "{{position.api_key}}",
        "{{market.__class__}}",
        "{{#market.x}}",
        "{{market.x",
        "a }} b",
        "{{account.token}}",
        "{{market.Price}}",
    ],
)
def test_template_outside_allow_list_rejected_naming_placeholder(tpl: str) -> None:
    with pytest.raises(AlertIrInvalid) as exc:
        validate_template(tpl)
    assert exc.value.reason == "bad_template"
    assert exc.value.issues[0].field == "message_template"


@pytest.mark.parametrize(
    "tpl",
    [
        "{{position.account.apikey}}",
        "{{position.exchange_account.api_key_id}}",
        "{{alert.owner.email}}",
        "{{position.account_id}}",
        "{{market.last_price.__class__}}",
        "{{{market.last_price}}}",
        "{{ {{market.last_price}} }}",
        "{{market.last_price!r}}",
        "{{market.last_price:>{width}}}",
        "{{market.last_price\n}}",
        "{{market.\nlast_price}}",
        "{{market.lаst_price}}",
        "{{market.ｌast_price}}",
        "{{market.last_price​}}",
    ],
)
def test_template_secret_nested_and_trick_placeholders_rejected(tpl: str) -> None:
    with pytest.raises(AlertIrInvalid) as exc:
        validate_template(tpl)
    assert exc.value.reason == "bad_template"


def test_template_context_derived_from_condition_metrics() -> None:
    assert validate_template("{{footprint.sell_stack_size}} {{market.price}}")
    with pytest.raises(AlertIrInvalid):
        validate_template("{{market.some_metric}}")
    assert validate_template("{{market.some_metric}}", ("some_metric",)) == ("market.some_metric",)
    for name in ("symbol", "last", "bid", "ask", "mark", "funding_rate"):
        assert validate_template("{{market." + name + "}}")
    for name in ("side", "size", "entry", "unrealised_pnl", "leverage", "liquidation_price"):
        assert validate_template("{{position." + name + "}}")


@pytest.mark.parametrize("tail", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_template_leaf_ending_in_a_newline_is_refused_even_as_a_named_metric(tail: str) -> None:
    """#3555: `$` also matches before a final newline, so `match` took the leaf, and a metric name
    given with that newline then passed the membership check behind it."""
    assert validate_template("{{market.some_metric}}", ("some_metric",)) == ("market.some_metric",)
    with pytest.raises(AlertIrInvalid) as exc:
        validate_template("{{market.some_metric" + tail + "}}", ("some_metric" + tail,))
    assert exc.value.reason == "bad_template"
