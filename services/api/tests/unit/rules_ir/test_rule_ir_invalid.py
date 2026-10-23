"""E35-T01 rule IR tests, part 2: invalid documents, schema agreement, drift guard, properties."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from candleviewer.alerts.models import AlertCondition
from candleviewer.domain.text import UNSTORABLE_TEXT
from candleviewer.rules.ir import Rule, canonicalize, ir_hash, to_json_schema

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests" / "fixtures" / "rule_ir"


def load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return data


def _leaf() -> dict[str, Any]:
    leaf: dict[str, Any] = load("form_simple_0")["conditions"]
    return leaf


def _temporal(window: int | None) -> dict[str, Any]:
    t: dict[str, Any] = {"node_id": "t", "op": "sustained_for", "child": _leaf()}
    if window is not None:
        t["window_ms"] = window
    return t


BAD: list[tuple[str, str, Any, str]] = [
    ("unknown_action", "actions.0.type", "withdraw_funds", "actions"),
    ("33_children", "conditions", {"node_id": "g", "op": "all_of", "children": [_leaf()] * 33},
     "children"),
    ("no_window", "conditions", _temporal(None), "window_ms"),
    ("window_low", "conditions", _temporal(99), "window_ms"),
    ("window_high", "conditions", _temporal(86_400_001), "window_ms"),
    ("9_operands", "conditions.left",
     {"node_id": "x", "op": "add", "operands": [{"const": 1}] * 9}, "operands"),
    ("11_actions", "actions", [{"node_id": "a", "type": "pause_rule", "params": {}}] * 11,
     "actions"),
    ("extra_field", "backdoor", "x", "backdoor"),
    ("bad_metric", "conditions.left.metric", "Bad Metric", "metric"),
    ("timer_no_interval", "trigger", {"type": "on_timer"}, "trigger"),
    ("bad_operand", "conditions.left", {"nonsense": 1}, "left"),
    ("bad_condition", "conditions", {"node_id": "x"}, "conditions"),
    ("bad_symbol", "scope.symbols", ["btc"], "symbols"),
]  # fmt: skip


def _set(d: dict[str, Any], path: str, value: Any) -> None:
    keys = path.split(".")
    for k in keys[:-1]:
        d = d[int(k)] if isinstance(d, list) else d[k]
    d[keys[-1]] = value


@pytest.mark.parametrize(("name", "path", "value", "loc"), BAD, ids=[b[0] for b in BAD])
def test_structurally_invalid_document_is_rejected_loudly(
    name: str, path: str, value: Any, loc: str
) -> None:
    doc = load("form_simple_0")
    _set(doc, path, value)
    with pytest.raises(ValidationError) as ei:
        Rule.model_validate(doc)
    assert any(loc in [str(p) for p in e["loc"]] for e in ei.value.errors()), name
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, to_json_schema())


@pytest.mark.parametrize("model", [Rule, AlertCondition], ids=["rule", "alert-condition"])
def test_ir_model_unstorable_text_in_any_key_or_value_is_a_schema_error(model: Any) -> None:
    """Postgres cannot store U+0000: each document root refuses it at any depth, keys too."""
    doc = load("form_simple_0")
    if model is AlertCondition:
        doc = {k: doc[k] for k in ("ir_version", "trigger", "conditions")}
    doc["conditions"]["left"]["params"][f"k{chr(0)}"] = 1
    with pytest.raises(ValidationError) as ei:
        model.model_validate(doc)
    assert [(e["type"], e["msg"]) for e in ei.value.errors()] == [
        ("unstorable_text", UNSTORABLE_TEXT)
    ]


def test_trigger_validators_and_schema_agree() -> None:
    valid: dict[str, dict[str, Any]] = {
        "on_timer": {"interval_ms": 500},
        "on_bar_close": {"timeframe": "1m"},
        "on_schedule": {"cron": "* * * * *"},
        "on_metric_change": {"metric": "rsi"},
    }
    schema = to_json_schema()
    for ttype, extra in valid.items():
        ok: dict[str, Any] = {**load("form_simple_0"), "trigger": {"type": ttype, **dict(extra)}}
        Rule.model_validate(ok)
        jsonschema.validate(ok, schema)
        bad: dict[str, Any] = {**load("form_simple_0"), "trigger": {"type": ttype}}
        with pytest.raises(ValidationError):
            Rule.model_validate(bad)
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad, schema)


def test_schema_forbids_additional_properties_everywhere() -> None:
    schema = to_json_schema()
    assert schema["additionalProperties"] is False
    for name, d in schema["$defs"].items():
        if d.get("type") == "object":
            assert d.get("additionalProperties") is False, name


def test_canonicalize_rejects_non_ir_types() -> None:
    from candleviewer.rules.ir.canonical import _normalise

    with pytest.raises(TypeError):
        _normalise(object())


def test_schema_drift_is_caught_in_ci(tmp_path: Path) -> None:
    script = ROOT / "scripts" / "generate_rule_ir_schema.py"
    cmd = [sys.executable, str(script), "--check"]
    ok = subprocess.run(cmd, cwd=ROOT, capture_output=True)  # noqa: S603
    assert ok.returncode == 0, ok.stderr.decode()
    spec = importlib.util.spec_from_file_location("gen_schema", script)
    assert spec is not None and spec.loader is not None
    mod: Any = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.TARGET = tmp_path / "rule-ir.json"
    assert mod.main(["--check"]) == 1  # missing file
    assert mod.main([]) == 0
    assert mod.main(["--check"]) == 0
    mod.TARGET.write_text("{}", encoding="utf-8")
    assert mod.main(["--check"]) == 1  # drift


def test_model_change_without_regeneration_fails_drift_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative case: edit a model field, keep the committed schema -> --check exits 1."""
    from candleviewer.rules.ir import models, schema

    script = ROOT / "scripts" / "generate_rule_ir_schema.py"
    spec = importlib.util.spec_from_file_location("gen_schema_neg", script)
    assert spec is not None and spec.loader is not None
    mod: Any = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    committed = ROOT / "candleviewer" / "rules" / "ir" / "rule-ir.json"
    mod.TARGET = tmp_path / "rule-ir.json"
    mod.TARGET.write_text(committed.read_text(encoding="utf-8"), encoding="utf-8")
    assert mod.main(["--check"]) == 0

    class DriftedRule(models.Rule):
        drifted_field: int = 0

    monkeypatch.setattr(schema, "Rule", DriftedRule)
    assert mod.main(["--check"]) == 1
    assert committed.read_text(encoding="utf-8") == mod.TARGET.read_text(encoding="utf-8")


def test_drift_check_is_wired_into_py_ci_lane() -> None:
    workflow = ROOT.parents[1] / ".github" / "workflows" / "_job-py.yml"
    text = workflow.read_text(encoding="utf-8")
    assert "scripts/generate_rule_ir_schema.py --check" in text


_num = st.one_of(st.integers(-(10**6), 10**6), st.decimals(-1000, 1000, places=6))
_ids = st.text("abcdef0123456789", min_size=1, max_size=6)


@st.composite
def _rules(draw: st.DrawFn) -> dict[str, Any]:
    counter = [0]

    def nid() -> str:
        counter[0] += 1
        return f"{draw(_ids)}{counter[0]}"

    def leaf() -> dict[str, Any]:
        return {
            "node_id": nid(),
            "op": draw(st.sampled_from(["gt", "lt", "gte"])),
            "left": {"metric": "price"},
            "right": {"const": draw(_num)},
        }

    def tree(depth: int) -> dict[str, Any]:
        if depth == 0 or draw(st.booleans()):
            return leaf()
        kids = [tree(depth - 1) for _ in range(draw(st.integers(1, 3)))]
        return {
            "node_id": nid(),
            "op": draw(st.sampled_from(["all_of", "any_of"])),
            "children": kids,
        }

    doc = load("form_simple_0")
    doc["conditions"] = tree(3)
    doc["graph_layout"] = {"x": draw(st.integers())}
    return doc


@settings(max_examples=200, deadline=None)
@given(_rules())
def test_property_round_trip_and_hash_stability(doc: dict[str, Any]) -> None:
    rule = Rule.model_validate(doc)
    rt = Rule.model_validate(rule.model_dump(mode="python"))
    assert rt == rule
    assert ir_hash(rt) == ir_hash(rule)
    other = Rule.model_validate({**doc, "graph_layout": None})
    assert ir_hash(other) == ir_hash(rule)
    assert canonicalize(rule) == canonicalize(rt)
