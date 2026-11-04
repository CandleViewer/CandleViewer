"""E40-D02 CC-1 (#1130): the message a firing carries, rendered at fire time, and CC-7's kind.

Unit level (`alerts.render`, `alerts.delivery_view`) plus the evaluator writing it: the title is
the alert's name, the body the rendered template or the restated condition, plain text.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.alerts.compiler import AlertCompiler
from candleviewer.alerts.delivery_view import (
    CONTEXT_SYMBOLS_MAX,
    CONTEXT_TEXT_MAX,
    CONTEXT_VALUES_MAX,
    delivery_kind,
    public_context,
    silenced,
    storm_summary,
)
from candleviewer.alerts.errors import AlertIrInvalid
from candleviewer.alerts.evaluator import AlertTick
from candleviewer.alerts.models import AlertCondition
from candleviewer.alerts.render import (
    _NUMBER,
    BODY_MAX,
    NO_VALUE,
    VALUE_MAX,
    FiringFacts,
    MetricInfo,
    clean_text,
    default_title,
    fmt_value,
    inert,
    registry_titles,
    render_body,
    restate,
)
from candleviewer.rules.vocabulary import default_registry
from tests.alerts._evaluator_env import T0, ir, make, row

FACTS = FiringFacts(
    alert_id="a1", name="BTC above 65k", severity="warning", symbol="BTCUSDT", timeframe="5m",
    fired_at_ms=T0, values={"price": "65012.5"},
)  # fmt: skip


TITLES = registry_titles(default_registry())


def cond(raw: dict[str, Any]) -> Any:
    return AlertCondition.model_validate(raw).conditions


def cmp(op: str, right: Any = 65000, metric: str = "price", **kw: Any) -> dict[str, Any]:
    node = {"node_id": "c", "op": op, "left": {"metric": metric}, **kw}
    if right is not None:
        node["right"] = {"const": right}
    return {"ir_version": 1, "trigger": {"type": "on_price_update"}, "conditions": node}


# --- values ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "text"),
    [
        ("65012.5", "65,012.5"), (Decimal("1234567.0300"), "1,234,567.0300"), (3, "3"),
        (2.5, "2.5"), (True, "true"), (False, "false"), (None, NO_VALUE), ("long", "long"),
        ({"a": 1}, NO_VALUE), (float("nan"), NO_VALUE),
    ],
)  # fmt: skip
def test_fmt_value_renders_plain_text(value: Any, text: str) -> None:
    assert fmt_value(value) == text


def test_fmt_value_cuts_long_text() -> None:
    assert fmt_value("x" * 500) == "x" * 64


# --- CC-1: the empty template restates the condition with its values ----------------------


def test_restate_crosses_above_reads_as_d17_example() -> None:
    assert restate(cond(cmp("crosses_above")), {"price": "65012.5"}, TITLES) == (
        "Price 65,012.5 crossed above 65,000"
    )


@pytest.mark.parametrize(
    ("op", "extra", "text"),
    [
        ("gt", {}, "Price 1 was above 65,000"),
        ("gte", {}, "Price 1 was at least 65,000"),
        ("lt", {}, "Price 1 was below 65,000"),
        ("lte", {}, "Price 1 was at most 65,000"),
        ("eq", {}, "Price 1 was 65,000"),
        ("neq", {}, "Price 1 was not 65,000"),
        ("crosses_below", {}, "Price 1 crossed below 65,000"),
        ("between", {"right2": {"const": 66000}}, "Price 1 was between 65,000 and 66,000"),
        ("outside", {"right2": {"const": 66000}}, "Price 1 was outside 65,000 to 66,000"),
    ],
)
def test_restate_uses_past_tense_verbs(op: str, extra: dict[str, Any], text: str) -> None:
    assert restate(cond(cmp(op, **extra)), {"price": "1"}, TITLES) == text


def test_restate_groups_and_windows() -> None:
    a = {"node_id": "a", "op": "gt", "left": {"metric": "price"}, "right": {"const": 1}}
    b = {"node_id": "b", "op": "lt", "left": {"metric": "price"}, "right": {"const": 9}}
    either = {"node_id": "g", "op": "any_of", "children": [a, b]}
    both = {"node_id": "h", "op": "all_of", "children": [a, b]}
    held = {"node_id": "t", "op": "sustained_for", "child": a, "window_ms": 120_000}
    vals = {"price": "5"}
    assert restate(cond(cmp("gt") | {"conditions": either}), vals, TITLES) == (
        "Either price 5 was above 1 or price 5 was below 9"
    )
    assert restate(cond(cmp("gt") | {"conditions": both}), vals, TITLES) == (
        "Price 5 was above 1 and price 5 was below 9"
    )
    assert restate(cond(cmp("gt") | {"conditions": held}), vals, TITLES) == (
        "Price 5 was above 1 for at least 2 min"
    )


def test_restate_without_a_registry_speaks_the_id_and_shows_no_value() -> None:
    """Fail closed: a metric whose scope is unknown never has its value rendered."""
    assert restate(cond(cmp("gt")), {"price": "1"}) == f"Price {NO_VALUE} was above 65,000"


def test_registry_titles_reads_title_estimated_flag_and_scope() -> None:
    assert TITLES("price") == MetricInfo("Price", False, "symbol")
    assert TITLES("account_equity") == MetricInfo("Account equity", False, "account")
    assert TITLES("no_such_metric") is None
    assert registry_titles(None) is default_title


def test_restate_missing_value_renders_dash() -> None:
    assert restate(cond(cmp("gt")), {}, TITLES) == f"Price {NO_VALUE} was above 65,000"


def test_restate_names_the_metric_title_and_estimated_qualifier() -> None:
    def title(name: str) -> MetricInfo | None:
        return {"price": MetricInfo("Tape speed", True, "symbol"),
                "mid": MetricInfo("POC", False, "symbol")}.get(name)  # fmt: skip

    assert restate(cond(cmp("gt", 3)), {"price": "4"}, title) == (
        "Tape speed (estimated) 4 was above 3"
    )
    a = {"node_id": "a", "op": "gt", "left": {"metric": "price"}, "right": {"const": 1}}
    b = {"node_id": "b", "op": "gt", "left": {"metric": "mid"}, "right": {"const": 2}}
    both = cmp("gt") | {"conditions": {"node_id": "g", "op": "all_of", "children": [b, a]}}
    assert restate(cond(both), {}, title) == (
        f"POC {NO_VALUE} was above 2 and tape speed (estimated) {NO_VALUE} was above 1"
    )


# --- M-1: no account data reaches any channel ---------------------------------------------

EQUITY = FiringFacts("a1", "Equity low", "warning", None, None, T0, {"account_equity": "812.40"})
EQUITY_COND = cmp("lt", 1000, metric="account_equity")


@pytest.mark.parametrize(
    ("template", "body"),
    [
        ("", f"Account equity {NO_VALUE} was below 1,000"),
        ("eq {{market.account_equity}} / {{footprint.account_equity}}",
         f"eq {NO_VALUE} / {NO_VALUE}"),
        ("{{alert.condition_summary}}", f"Account equity {NO_VALUE} was below 1,000"),
    ],
)  # fmt: skip
def test_render_body_never_renders_an_account_scope_value(template: str, body: str) -> None:
    out = render_body(template, cond(EQUITY_COND), EQUITY, TITLES)
    assert out == body and "812" not in out


@pytest.mark.parametrize("metric", ["position_qty", "liq_price", "unrealised_pnl"])
def test_render_body_never_renders_a_position_scope_value(metric: str) -> None:
    facts = FiringFacts("a1", "n", "info", "BTCUSDT", None, T0, {metric: "4242.5"})
    out = render_body(f"{{{{market.{metric}}}}} | ", cond(cmp("gt", 1, metric=metric)), facts,
                      TITLES)  # fmt: skip
    assert "4,242.5" not in out and "4242" not in out
    assert "4242" not in restate(cond(cmp("gt", 1, metric=metric)), facts.values, TITLES)


# --- CC-1: the template rendered with this firing's values --------------------------------


def test_render_body_substitutes_each_allow_listed_leaf() -> None:
    template = (
        "{{ market.symbol }} {{market.price}} on {{footprint.timeframe}}: {{alert.name}} "
        "({{alert.severity}}, {{alert.id}}) at {{alert.triggered_at}}"
    )
    assert render_body(template, cond(cmp("gt")), FACTS, TITLES) == (
        "BTCUSDT 65,012.5 on 5m: BTC above 65k (warning, a1) at 2026-09-21T14:13:20Z"
    )


def test_render_body_empty_template_is_the_restatement() -> None:
    assert render_body("  ", cond(cmp("crosses_above")), FACTS, TITLES) == (
        "Price 65,012.5 crossed above 65,000"
    )


def test_render_body_condition_summary_leaf_is_the_restatement() -> None:
    assert render_body("Fired: {{alert.condition_summary}}", cond(cmp("gt")), FACTS, TITLES) == (
        "Fired: Price 65,012.5 was above 65,000"
    )


def test_render_body_position_leaves_render_no_account_data() -> None:
    body = render_body("{{position.size}} @ {{position.entry_price}}", cond(cmp("gt")), FACTS,
                       TITLES)  # fmt: skip
    assert body == f"{NO_VALUE} @ {NO_VALUE}"


def test_render_body_missing_value_and_unknown_namespace_render_dash() -> None:
    body = render_body("{{market.bid}} {{secrets.key}} {{alert.nope}}", cond(cmp("gt")), FACTS,
                       TITLES)  # fmt: skip
    assert body == f"{NO_VALUE} {NO_VALUE} {NO_VALUE}"


# --- m-1 / m-2 / plain text ----------------------------------------------------------------


def test_render_body_strips_control_and_bidi_characters_but_keeps_newlines() -> None:
    facts = FiringFacts("a1", "N\x1b[31m\u202eX\u2066", "info", None, None, T0, {})
    out = render_body("x\x07\x1b[2J\x9b {{alert.name}}\nnext\u200f", cond(cmp("gt")), facts)
    assert out == "x[2J N[31mX\nnext"
    assert clean_text("a\u061cb\u202ac\u2069") == "abc"


def test_render_body_never_carries_a_placeholder_from_a_value() -> None:
    facts = FiringFacts("a1", "N {{market.price}}", "info", None, None, T0, {})
    out = render_body("{{alert.name}} {{alert.id}}", cond(cmp("gt")), facts)
    assert "{{" not in out and "}}" not in out
    assert out == "N { {market.price} } a1"
    assert inert("{{{x}}}") == "{ { {x} } }"


def test_render_body_carries_markup_as_plain_characters() -> None:
    """The no-raw-HTML rule's server half (ticket Security notes): text is never escaped or
    turned into markup here; the client renders it as text, never as HTML."""
    facts = FiringFacts("a1", "<b>bold</b>", "info", None, None, T0, {})
    out = render_body("<script>x</script> {{alert.name}} &amp;", cond(cmp("gt")), facts)
    assert out == "<script>x</script> <b>bold</b> &amp;"


@pytest.mark.parametrize(
    ("value", "text"),
    [("1E+3", "1,000"), ("-2.5e-2", "-0.025"), ("1E+100", "1.000000E+100")],
)
def test_fmt_value_normalises_exponent_decimals(value: str, text: str) -> None:
    assert fmt_value(value) == text


# --- B-1: the display form is chosen before any text is built --------------------------------

HUGE = "1e999999999"


@pytest.mark.parametrize(
    ("value", "text"),
    [(HUGE, HUGE), ("1e9999", "1.000000E+9999"), ("-1e-9999", "-1.000000E-9999"),
     (Decimal(HUGE), "1.000000E+999999999"), (Decimal("-1e-999999999"), "-1.000000E-999999999"),
     (10**200, "1.000000E+200"), ("1" * 65, "1.111111E+64"), ("1e64", "1.000000E+64"),
     ("1e20", "100,000,000,000,000,000,000"), (Decimal("NaN"), NO_VALUE)],
)  # fmt: skip
def test_fmt_value_decides_the_form_from_exponent_and_digits(value: Any, text: str) -> None:
    assert fmt_value(value) == text


def huge_neq() -> Any:
    return cond(cmp("neq", HUGE))


def test_restate_a_huge_exponent_string_literal_is_shown_as_text() -> None:
    out = restate(huge_neq(), {"price": "65012.5"}, TITLES)
    assert out == f"Price 65,012.5 was not {HUGE}"
    body = render_body("{{alert.condition_summary}}", huge_neq(), FACTS, TITLES)
    assert body == out


def test_compiler_refuses_a_numeric_string_constant_too_wide_to_write_out() -> None:
    with pytest.raises(AlertIrInvalid) as exc:
        AlertCompiler(default_registry()).compile(cmp("neq", HUGE))
    assert exc.value.reason == "schema"
    assert [i.field for i in exc.value.issues] == ["conditions.right.const"]
    AlertCompiler(default_registry()).compile(cmp("neq", "65000.5"))  # a sane one still compiles
    AlertCompiler(default_registry()).compile(cmp("neq", "Infinity"))  # not a finite number


@pytest.mark.perf
def test_fmt_value_huge_exponent_returns_within_budget() -> None:
    start = time.perf_counter()
    for v in (HUGE, Decimal(HUGE), Decimal("1e-999999999"), "9" * 100_000):
        fmt_value(v)
    restate(huge_neq(), {"price": Decimal(HUGE)}, TITLES)
    assert time.perf_counter() - start < 0.05  # C-2.17: never blocks the loop past 50 ms


@given(st.from_regex(_NUMBER, fullmatch=True))
def test_fmt_value_of_any_numeric_string_is_bounded(value: str) -> None:
    assert len(fmt_value(value)) <= VALUE_MAX


# --- m-1: braces made inert after control characters are removed ---------------------------


@pytest.mark.parametrize(
    ("name", "template", "body"),
    [("{\x01{", "{{alert.name}}", "{ {"), ("n", "{\x01{alert.name}\x01}", "{ {alert.name} }"),
     ("a{", "{{alert.name}}{x", "a{ {x")],
)  # fmt: skip
def test_render_body_never_joins_a_brace_pair_across_a_removed_character(
    name: str, template: str, body: str
) -> None:
    facts = FiringFacts("a1", name, "info", None, None, T0, {})
    assert render_body(template, cond(cmp("gt")), facts) == body


def test_restate_never_joins_a_brace_pair_across_a_removed_character() -> None:
    out = restate(cond(cmp("in_set", None, set_values=["{\x01{"])), {}, TITLES)
    assert "{{" not in out and out.endswith("{ {")


@given(st.text(max_size=600), st.dictionaries(st.sampled_from(["price", "bid"]), st.text()))
def test_render_body_is_bounded_and_total(template: str, values: dict[str, str]) -> None:
    facts = FiringFacts("a1", "n", "info", "BTCUSDT", None, T0, values)
    out = render_body(template, cond(cmp("gt")), facts, TITLES)
    assert isinstance(out, str) and len(out) <= BODY_MAX
    assert clean_text(out) == out


# --- CC-7: the kind, the summary and the served context -----------------------------------


def test_delivery_kind_flags_must_be_true_booleans() -> None:
    assert delivery_kind({"storm_summary": "yes"}) == "firing"
    assert delivery_kind({"disarmed": 1}) == "firing"
    assert delivery_kind(None) == "firing"


def test_storm_summary_is_none_for_other_kinds_and_clamps_bad_values() -> None:
    assert storm_summary({"symbol": "BTCUSDT"}) is None
    got = storm_summary({"storm_summary": True, "suppressed": True, "symbols": "AB",
                         "window_start_ms": False})  # fmt: skip
    assert got is not None and (got.count, got.symbols, got.window_start_ms) == (0, (), None)


def test_storm_summary_symbols_are_bounded() -> None:
    got = storm_summary({"storm_summary": True, "suppressed": 500,
                         "symbols": ["S" * 2000] + [f"S{i}USDT" for i in range(499)]})  # fmt: skip
    assert got is not None and len(got.symbols) == CONTEXT_SYMBOLS_MAX
    assert len(got.symbols[0]) == CONTEXT_TEXT_MAX


def test_public_context_never_serves_internal_keys() -> None:
    assert public_context({"condition_hash": "h", "gates": [], "symbol": "X"}) == {"symbol": "X"}
    assert public_context(None) == {}


def any_metric(_name: str) -> MetricInfo:
    return MetricInfo("t", False, "symbol")


def test_public_context_drops_negative_counts_and_non_finite_numbers() -> None:
    got = public_context({"suppressed": -1, "failed_delivery_id": -7,
                          "values": {"a": float("nan"), "b": float("inf"), "c": 1.5}},
                         any_metric)  # fmt: skip
    assert got == {"values": {"c": 1.5}}


def test_public_context_drops_a_values_key_past_64_characters() -> None:
    got = public_context({"values": {"k" * 65: "1", "k" * 64: "2"}}, any_metric)
    assert got == {"values": {"k" * 64: "2"}}


def test_public_context_is_bounded() -> None:
    ctx = {"values": {f"m{i}": "x" * 5000 for i in range(500)},
           "symbols": [f"S{i}USDT" for i in range(500)], "reason": "r" * 5000}  # fmt: skip
    got = public_context(ctx, any_metric)
    assert len(got["values"]) == CONTEXT_VALUES_MAX
    assert all(len(v) == CONTEXT_TEXT_MAX for v in got["values"].values())
    assert len(got["symbols"]) == CONTEXT_SYMBOLS_MAX and len(got["reason"]) == CONTEXT_TEXT_MAX


@pytest.mark.parametrize("key", ["suppressed_reason", "suppression_reason"])
def test_public_context_serves_only_contract_suppression_reasons(key: str) -> None:
    assert public_context({key: "storm"}) == {key: "storm"}
    assert public_context({key: "desktop_off"}) == {key: "desktop_off"}
    assert public_context({key: "made_up"}) == {}


@pytest.mark.parametrize(
    ("context", "reason"),
    [({"silenced": "muted_symbol"}, "muted_symbol"), ({"silenced": "quiet_hours"}, "quiet_hours"),
     ({"silenced": "other"}, None), ({"silenced": True}, None), ({}, None), (None, None)],
)  # fmt: skip
def test_silenced_reads_only_the_two_reasons(
    context: dict[str, Any] | None, reason: str | None
) -> None:
    assert silenced(context) == reason
    if context:
        assert ("silenced" in public_context(context)) is (reason is not None)


# --- the evaluator writes it ----------------------------------------------------------------


def tick(ts: int = T0) -> AlertTick:
    return AlertTick("on_price_update", ts, "BTCUSDT")


async def test_evaluator_firing_title_is_the_name_and_body_the_rendered_template() -> None:
    r = row("a1", name="BTC above 65k", channels=("in_app", "desktop"),
            message_template="{{market.symbol}} last {{market.price}}")  # fmt: skip
    ev, store, src, *_ = make(r)
    await ev.warm_up()
    src.set("price", "65012.5", T0)
    await ev.process(tick())
    assert [(d.channel, d.title, d.body) for d in store.deliveries] == [
        ("in_app", "BTC above 65k", "BTCUSDT last 65,012.5"),
        ("desktop", "BTC above 65k", "BTCUSDT last 65,012.5"),
    ]
    assert "{{" not in "".join(d.title + d.body for d in store.deliveries)


async def test_evaluator_empty_template_body_restates_the_condition() -> None:
    ev, store, src, *_ = make(row("a1", name="n", condition_ir=ir("gt", 65000)))
    await ev.warm_up()
    src.set("price", "65012.5", T0)
    await ev.process(tick())
    [d] = store.deliveries
    assert (d.title, d.body) == ("n", "Price 65,012.5 was above 65,000")
    assert delivery_kind(d.context) == "firing"


async def test_evaluator_storm_rows_are_rendered_and_summary_carries_its_window() -> None:
    from candleviewer.alerts.gating import StormSuppressor

    rows = [row(f"a{i}", name=f"n{i}", condition_ir=ir(const=i)) for i in range(3)]
    ev, store, src, clock, _ = make(*rows, storm=StormSuppressor(limit=1, window_ms=60_000))
    await ev.warm_up()
    src.set("price", "70000", T0)
    await ev.process(tick())
    held = [d for d in store.deliveries if d.status == "suppressed"]
    assert [(d.title, d.body) for d in held] == [
        ("n1", "Price 70,000 was above 1"), ("n2", "Price 70,000 was above 2"),
    ]  # fmt: skip
    clock.now = T0 + 60_000
    await ev.flush_storms()
    summary = store.deliveries[-1]
    assert delivery_kind(summary.context) == "storm_summary"
    got = storm_summary(summary.context)
    assert got is not None and (got.count, got.symbols) == (2, ("BTCUSDT",))
    assert (got.window_start_ms, got.window_end_ms) == (T0, T0 + 60_000)


async def test_evaluator_title_is_plain_text() -> None:
    ev, store, src, *_ = make(row("a1", name="BTC\x1b[31m \u202eup"))
    await ev.warm_up()
    src.set("price", "65012.5", T0)
    await ev.process(tick())
    [d] = store.deliveries
    assert d.title == "BTC[31m up"


async def test_evaluator_storm_symbols_fold_the_name_as_plain_text() -> None:
    from candleviewer.alerts.gating import StormSuppressor

    rows = [row(f"a{i}", name=f"n\x1b[{i}\u202e", symbol=None, condition_ir=ir(const=i))
            for i in range(2)]  # fmt: skip
    ev, store, src, clock, _ = make(*rows, storm=StormSuppressor(limit=1, window_ms=60_000))
    await ev.warm_up()
    src.set("price", "70000", T0)
    await ev.process(AlertTick("on_price_update", T0, None))
    clock.now = T0 + 60_000
    await ev.flush_storms()
    got = storm_summary(store.deliveries[-1].context)
    assert got is not None and got.symbols == ("n[1",)
