"""Hypothesis strategies for schema-valid rule IR documents (E35-Q02).

Documents are *valid* against the IR models (``Rule.model_validate`` accepts them) but deliberately
not semantically sensible: this suite tests the compilers, not the validator. Generation is biased
toward the constructs where round-tripping is hard (ticket technical notes): shared sub-expressions,
``n_of``, booleans at the 32-child bound, temporal nodes wrapping booleans and arithmetic nested in
arithmetic. A second, narrower strategy produces form-compatible documents so the form hop is
exercised on a large share of the budget rather than only on the rare accidental hit.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, get_args

from hypothesis import strategies as st

from candleviewer.rules.ir.models import (
    MAX_ACTIONS,
    MAX_ARITHMETIC_OPERANDS,
    MAX_BOOLEAN_CHILDREN,
    ActionType,
    ArithmeticOp,
    BooleanOp,
    ComparisonOp,
    TemporalOp,
    TriggerType,
)

COMPARISON_OPS: tuple[str, ...] = get_args(ComparisonOp)
ARITHMETIC_OPS: tuple[str, ...] = get_args(ArithmeticOp)
BOOLEAN_OPS: tuple[str, ...] = get_args(BooleanOp)
TEMPORAL_OPS: tuple[str, ...] = get_args(TemporalOp)
TRIGGER_TYPES: tuple[str, ...] = get_args(TriggerType)
ACTION_TYPES: tuple[str, ...] = get_args(ActionType)
UNARY_OPS = frozenset({"is_true", "is_false", "changed", "in_set", "not_in_set"})
TERNARY_OPS = frozenset({"between", "outside"})
METRICS = ("price", "atr", "rsi", "vwap", "cvd", "spread_bps", "position_open", "market_regime")
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
RULE_ID = "00000000-0000-4000-8000-0000000000aa"

Doc = dict[str, Any]

_decimals = st.decimals(
    min_value=Decimal("-1e12"), max_value=Decimal("1e12"), allow_nan=False, allow_infinity=False,
    places=8,
)  # fmt: skip
_scalars = st.one_of(
    st.booleans(), st.integers(-(10**9), 10**9), _decimals, st.text("abcxyz_ ", max_size=6)
)
_keys = st.sampled_from(("n", "anchor", "source", "window_ms", "z", "mode", "k"))
#: Params also take JSON floats (#4132): a metric param's becomes a Decimal, an action param's
#: hashes through the canonicaliser's float arm.
_params = st.dictionaries(
    _keys, st.one_of(_scalars, st.floats(allow_nan=False, allow_infinity=False)), max_size=3
)
_layout = st.one_of(
    st.none(),
    st.fixed_dictionaries(
        {
            "positions": st.dictionaries(
                st.sampled_from(("c1", "g1", "a1")),
                st.fixed_dictionaries({"x": st.integers(0, 2000), "y": st.integers(0, 2000)}),
                min_size=1,
                max_size=3,
            )
        },
        optional={"zoom": st.sampled_from((1, 2, Decimal("0.5"))), "note": st.text(max_size=8)},
    ),
)


class _Ids:
    """Unique node ids per document (the hash renumbers them, so their spelling is irrelevant)."""

    def __init__(self) -> None:
        self.n = 0

    def __call__(self, prefix: str) -> str:
        self.n += 1
        return f"{prefix}{self.n}"


@st.composite
def metric_ref(draw: st.DrawFn) -> Doc:
    out: Doc = {"metric": draw(st.sampled_from(METRICS)), "params": draw(_params)}
    if draw(st.booleans()):
        out["symbol"] = draw(st.sampled_from(SYMBOLS))
    if draw(st.integers(0, 3)) == 0:
        out["timeframe"] = draw(st.sampled_from(("1m", "5m", "1h")))
    return out


def _const() -> st.SearchStrategy[Doc]:
    return _scalars.map(lambda v: {"const": v})


@st.composite
def operand(draw: st.DrawFn, ids: _Ids, depth: int, arithmetic: bool) -> Doc:
    kind = draw(st.integers(0, 4)) if arithmetic and depth < 3 else draw(st.integers(0, 1))
    if kind == 0:
        return draw(metric_ref())
    if kind == 1:
        return draw(_const())
    # Arithmetic, nested inside arithmetic with high probability (ticket bias).
    # Occasionally sit on the 8-operand bound, but with leaf operands so size stays bounded.
    wide = draw(st.integers(0, 9)) == 0
    n = MAX_ARITHMETIC_OPERANDS if wide else draw(st.integers(1, 3))
    return {
        "node_id": ids("x"),
        "op": draw(st.sampled_from(ARITHMETIC_OPS)),
        "operands": [draw(operand(ids, 3 if wide else depth + 1, True)) for _ in range(n)],
    }


@st.composite
def comparison(draw: st.DrawFn, ids: _Ids, arithmetic: bool = True) -> Doc:
    op = draw(st.sampled_from(COMPARISON_OPS))
    out: Doc = {"node_id": ids("c"), "op": op, "left": draw(operand(ids, 0, arithmetic))}
    if op not in UNARY_OPS:
        out["right"] = draw(operand(ids, 0, arithmetic))
    if op in TERNARY_OPS:
        out["right2"] = draw(operand(ids, 0, arithmetic))
    if op in ("in_set", "not_in_set"):
        out["set_values"] = draw(st.lists(st.sampled_from(("trend", "range", "long")),
                                          min_size=1, max_size=3))  # fmt: skip
    if draw(st.integers(0, 4)) == 0:
        out["tolerance"] = draw(st.decimals(min_value=0, max_value=10, places=4))
    return out


@st.composite
def condition(draw: st.DrawFn, ids: _Ids, pool: list[Doc], depth: int = 0) -> Doc:
    """Any condition node; previously built nodes are re-used verbatim to create shared nodes."""
    if pool and draw(st.integers(0, 5)) == 0:  # shared sub-expression (same node_id, same body)
        return draw(st.sampled_from(pool))
    kind = draw(st.integers(0, 9)) if depth < 3 else 0
    if kind <= 3:
        node = draw(comparison(ids))
    elif kind <= 6:
        op = draw(st.sampled_from(BOOLEAN_OPS))
        wide = draw(st.integers(0, 9)) == 0  # sometimes sit exactly on the 32-child bound
        n = MAX_BOOLEAN_CHILDREN if wide else draw(st.integers(1, 3))
        children = [
            (
                draw(comparison(ids, arithmetic=False))
                if wide
                else draw(condition(ids, pool, depth + 1))
            )
            for _ in range(n)
        ]
        node = {"node_id": ids("g"), "op": op, "children": children}
        if op == "n_of" or draw(st.integers(0, 6)) == 0:
            node["n"] = draw(st.integers(1, n + 1))  # schema-valid; n > len is a validator matter
    else:
        node = {
            "node_id": ids("t"),
            "op": draw(st.sampled_from(TEMPORAL_OPS)),
            "child": draw(condition(ids, pool, depth + 1)),  # often a boolean: hard case
            "window_ms": draw(st.integers(100, 86_400_000)),
            "min_count": draw(st.integers(1, 50)),
        }
    pool.append(node)
    return node


@st.composite
def form_condition(draw: st.DrawFn, ids: _Ids) -> Doc:
    """Form subset: ``all_of`` of ``any_of`` of comparisons / ``sustained_for(comparison)``."""

    def leaf() -> Doc:
        c = draw(comparison(ids, arithmetic=False))
        if draw(st.integers(0, 3)) == 0:
            return {"node_id": ids("t"), "op": "sustained_for", "child": c,
                    "window_ms": draw(st.integers(100, 3_600_000))}  # fmt: skip
        return c

    shape = draw(st.integers(0, 3))
    if shape == 0:
        return leaf()
    if shape == 1:
        return {"node_id": ids("g"), "op": "any_of",
                "children": [leaf() for _ in range(draw(st.integers(1, 4)))]}  # fmt: skip
    kids: list[Doc] = []
    for _ in range(draw(st.integers(1, 4))):
        if draw(st.booleans()):
            kids.append({"node_id": ids("g"), "op": "any_of",
                         "children": [leaf() for _ in range(draw(st.integers(1, 3)))]})  # fmt: skip
        else:
            kids.append(leaf())
    return {"node_id": ids("g"), "op": "all_of", "children": kids}


@st.composite
def action(draw: st.DrawFn, ids: _Ids) -> Doc:
    out: Doc = {
        "node_id": ids("a"),
        "type": draw(st.sampled_from(ACTION_TYPES)),
        "params": draw(_params),
    }
    if draw(st.booleans()):
        out["on_error"] = draw(st.sampled_from(("abort_remaining", "continue", "retry_once")))
    if draw(st.integers(0, 3)) == 0:
        out["targets"] = draw(st.sampled_from(("scope_accounts", "originating_account",
                                               "all_accounts")))  # fmt: skip
    if draw(st.integers(0, 3)) == 0:
        out["dry_run_only"] = True
    return out


@st.composite
def trigger(draw: st.DrawFn) -> Doc:
    t = draw(st.sampled_from(TRIGGER_TYPES))
    out: Doc = {"type": t}
    req = {"on_timer": ("interval_ms", st.integers(100, 10**7)),
           "on_bar_close": ("timeframe", st.sampled_from(("1m", "15m", "4h"))),
           "on_schedule": ("cron", st.sampled_from(("0 0 * * *", "*/5 * * * *"))),
           "on_metric_change": ("metric", st.sampled_from(METRICS))}  # fmt: skip
    if t in req:
        k, s = req[t]
        out[k] = draw(s)
    if draw(st.booleans()):
        out["debounce_ms"] = draw(st.integers(0, 60_000))
    return out


@st.composite
def scope(draw: st.DrawFn) -> Doc:
    out: Doc = {"level": draw(st.sampled_from(("global", "account", "symbol", "position",
                                                "trade_group")))}  # fmt: skip
    if draw(st.booleans()):
        out["symbols"] = draw(st.lists(st.sampled_from(SYMBOLS), max_size=3))
    if draw(st.integers(0, 2)) == 0:
        out["account_ids"] = [str(uuid.UUID(int=draw(st.integers(1, 2**64))))]
    if draw(st.integers(0, 2)) == 0:
        out["environments"] = draw(st.lists(st.sampled_from(("demo", "testnet", "live")),
                                            min_size=1, max_size=2, unique=True))  # fmt: skip
    if draw(st.booleans()):
        out["applies_to"] = draw(st.sampled_from(("open_positions", "pending_orders", "any")))
    return out


@st.composite
def limits(draw: st.DrawFn) -> Doc:
    return draw(st.fixed_dictionaries({}, optional={
        "once": st.booleans(),
        "once_per": st.sampled_from(("position", "day", "group", "rule_lifetime")),
        "cooldown_ms": st.integers(0, 10**7),
        "max_fires_per_hour": st.integers(1, 1000),
        "max_actions_per_fire": st.integers(1, MAX_ACTIONS),
        "max_notional_per_fire": st.decimals(min_value=1, max_value=10**6, places=2),
        "require_confirmation": st.booleans(),
        "evaluation_timeout_ms": st.integers(10, 5000),
    }))  # fmt: skip


@st.composite
def rule_doc(draw: st.DrawFn, form_only: bool = False) -> Doc:
    """One schema-valid IR document (a JSON-ish dict, Decimals for fractional numbers)."""
    ids = _Ids()
    cond = draw(form_condition(ids)) if form_only else draw(condition(ids, []))
    doc: Doc = {
        "rule_id": RULE_ID,
        "version": draw(st.integers(1, 1000)),
        "name": draw(st.text(min_size=1, max_size=20).filter(str.strip)),
        "description": draw(st.text(max_size=30)),
        "enabled": draw(st.booleans()),
        "mode": draw(st.sampled_from(("disabled", "simulate", "armed"))),
        "scope": draw(scope()),
        "trigger": draw(trigger()),
        "conditions": cond,
        "actions": [
            draw(action(ids)) for _ in range(draw(st.sampled_from((1, 2, 3, MAX_ACTIONS))))
        ],
        "limits": draw(limits()),
        "editor": draw(st.sampled_from(("form", "graph"))),
    }
    layout = draw(_layout)
    if layout is not None:
        doc["graph_layout"] = layout
    return doc


any_rule = rule_doc()
form_rule = rule_doc(form_only=True)
