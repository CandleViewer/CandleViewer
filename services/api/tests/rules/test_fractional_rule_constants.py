"""#5807: a rule constant keeps its number through a save and a load.

A rule is authored as the routes read a body (`json.loads`: a fractional JSON number arrives as a
float, which the IR reads as a `Decimal`), saved through `RulesManager.create` (a version stores
the IR's JSON-mode dump), loaded as the evaluator's work list loads it
(`RulesManager.evaluable_rules`) and evaluated. The in-memory store keeps the dumped document as it
is; the Postgres store writes it as JSON text and reads it back with `json.loads`, so both stores
hand the load the same document.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from candleviewer.rules.evaluator import EvaluationResult, Evaluator, MetricValue, SnapshotBuilder
from candleviewer.rules.evaluator.engine import scope_instance
from candleviewer.rules.ir import MetricRef, Rule
from candleviewer.rules.manager import Actor, InMemoryRuleStore, RulesManager
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
