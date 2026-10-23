"""E35-Q02 corpus gate: >=30 hand-authored rules are hash-stable in both directions.

Each ``tests/fixtures/rule_corpus/*.json`` rule has a golden canonical hash in
``tests/fixtures/rule_corpus/golden_hashes.json``. Any change to canonicalisation, the IR models or
the compilers that alters a hash fails here. Updating a golden is a reviewed decision: run
``uv run python -m tests.rules.roundtrip.update_goldens --reason "<why>"`` and copy the reason into
the PR (the reason is stored next to the hashes and checked to be non-empty).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, get_args

import pytest

from candleviewer.rules.ir import Rule, form_compatible, ir_hash, parse_ir_json
from candleviewer.rules.ir.models import (
    ActionType,
    ArithmeticNode,
    BooleanNode,
    Comparison,
    ComparisonOp,
    TemporalNode,
    TriggerType,
)
from candleviewer.rules.validator import validate_rule
from candleviewer.rules.vocabulary import default_registry
from tests.rules.roundtrip.chain import full_chain, to_form, to_node

CORPUS = Path(__file__).parents[2] / "fixtures/rule_corpus"
GOLDEN = CORPUS / "golden_hashes.json"
RULES = sorted(CORPUS.glob("[0-9][0-9]_*.json"))
SYSTEM_RULES = {
    "sys.native_sl_watchdog", "sys.daily_loss_lockout", "sys.max_positions_guard",
    "sys.clock_drift_block", "sys.stale_feed_block", "sys.breakeven_at_1r", "sys.time_stop",
    "sys.funding_flip_flatten",
}  # fmt: skip


def load(path: Path) -> Rule:
    return parse_ir_json(path.read_text(encoding="utf-8"))  # Decimal, never float


def goldens() -> dict[str, Any]:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _walk(node: Any, out: dict[str, set[Any]], parents: dict[str, int]) -> None:
    nid = getattr(node, "node_id", None)
    if nid is not None:
        parents[nid] = parents.get(nid, 0) + 1
        if parents[nid] > 1:
            return
    if isinstance(node, Comparison):
        out["cmp"].add(node.op)
        for o in (node.left, node.right, node.right2):
            _walk(o, out, parents)
    elif isinstance(node, BooleanNode):
        out["bool"].add(node.op)
        for c in node.children:
            _walk(c, out, parents)
    elif isinstance(node, TemporalNode):
        out["temporal"].add(node.op)
        _walk(node.child, out, parents)
    elif isinstance(node, ArithmeticNode):
        out["arith"].add(node.op)
        if any(isinstance(o, ArithmeticNode) for o in node.operands):
            out["nested_arith"].add(True)
        for o in node.operands:
            _walk(o, out, parents)


def test_corpus_rules_are_valid_but_the_one_that_would_loosen_a_stop() -> None:
    """Rule 20 keeps its round trip and golden hash, and is refused for every caller: no rule
    loosens a stop (24-internal-schemas.md section 8.8 rule 5)."""
    assert len(RULES) >= 30
    reg = default_registry()
    loosens = {"20_widen_stop_through_funding_owner.json": [("actions[0].type", "stop_loosening")]}
    for p in RULES:
        res = validate_rule(load(p), reg)
        assert [(e.path, e.code) for e in res.errors] == loosens.get(p.name, []), p.name


def test_corpus_covers_the_whole_vocabulary() -> None:
    seen: dict[str, set[Any]] = {k: set() for k in
                                 ("cmp", "bool", "temporal", "arith", "nested_arith", "trigger",
                                  "action", "level", "name")}  # fmt: skip
    shared = False
    for p in RULES:
        r = load(p)
        parents: dict[str, int] = {}
        _walk(r.conditions, seen, parents)
        shared |= any(n > 1 for n in parents.values())
        seen["trigger"].add(r.trigger.type)
        seen["action"].update(a.type for a in r.actions)
        seen["level"].add(r.scope.level)
        seen["name"].add(r.name)
    assert seen["trigger"] == set(get_args(TriggerType))
    assert seen["action"] == set(get_args(ActionType))
    assert seen["cmp"] == set(get_args(ComparisonOp))
    assert seen["bool"] == {"all_of", "any_of", "none_of", "n_of"}
    assert seen["temporal"] == {"sustained_for", "occurred_within", "count_within", "stable_for"}
    assert seen["level"] == {"global", "account", "symbol", "position", "trade_group"}
    assert seen["nested_arith"] and shared
    assert SYSTEM_RULES <= seen["name"]


def test_corpus_golden_file_matches_the_corpus_and_states_a_reason() -> None:
    g = goldens()
    assert set(g["hashes"]) == {p.name for p in RULES}, "corpus and golden file out of sync"
    assert g.get("reason", "").strip(), "golden update must record a written reason"


@pytest.mark.parametrize("path", RULES, ids=lambda p: p.stem)
def test_corpus_rule_is_hash_stable_both_directions(path: Path) -> None:
    """Scenario: The thirty-rule corpus is hash-stable both directions."""
    ir = load(path)
    want = goldens()["hashes"][path.name]
    assert ir_hash(ir) == want, (
        f"{path.name}: canonical hash drifted ({ir_hash(ir)}); a golden update needs a written "
        "reason - see the module docstring"
    )
    assert full_chain(ir) == want
    if form_compatible(ir):
        form_side = to_form(ir)  # form -> graph -> form
        assert ir_hash(to_form(to_node(form_side))) == want
    graph_side = to_node(ir)  # graph -> form -> graph (form hop only where representable)
    back = to_node(to_form(graph_side)) if form_compatible(ir) else to_node(graph_side)
    assert ir_hash(back) == want


def test_corpus_golden_drift_fails_the_gate_and_needs_a_written_reason(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Scenario: Golden drift requires a human decision."""
    import candleviewer.rules.ir.canonical as canonical
    from tests.rules.roundtrip import update_goldens

    path = RULES[0]
    real = canonical.canonicalize
    monkeypatch.setattr(canonical, "canonicalize", lambda ir: real(ir) + b" ")  # semantic drift
    with pytest.raises(AssertionError, match="golden update needs a written reason"):
        test_corpus_rule_is_hash_stable_both_directions(path)
    monkeypatch.setattr(update_goldens, "GOLDEN", tmp_path / "g.json")
    assert update_goldens.main(["--reason", "   "]) == 2  # an empty reason is refused
    assert not (tmp_path / "g.json").exists()
    assert update_goldens.main(["--reason", "IR hash v2 upcaster"]) == 0
    assert json.loads((tmp_path / "g.json").read_text())["reason"] == "IR hash v2 upcaster"
