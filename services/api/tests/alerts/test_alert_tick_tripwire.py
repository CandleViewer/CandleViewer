"""Tripwire (E40-X01): no production code builds an `AlertTick` yet.

`AlertsService.submit_tick` and `AlertEvaluator.submit` have no production caller today, so no
alert is evaluated. The write routes check every account an alert names against its author's
grants; evaluation must re-check those grants before anything feeds the evaluator ticks. This
test is to be replaced by that re-check's own tests.
"""

from __future__ import annotations

import ast
import warnings
from pathlib import Path

import candleviewer

_ROOT = Path(candleviewer.__file__).parent
_NAME = "AlertTick"
_HOMES = frozenset({"alerts/evaluator.py", "alerts/service.py"})
_WHY = (
    "Wiring a producer of alert ticks needs the evaluation-time grant re-check first (E40-X01): "
    "grants can be revoked after an alert is created."
)


def _is_tick(node: ast.AST) -> bool:
    """`AlertTick` or `<anything>.AlertTick`."""
    if isinstance(node, ast.Attribute):
        return node.attr == _NAME
    return isinstance(node, ast.Name) and node.id == _NAME


def _names_tick(node: ast.AST) -> bool:
    """The name in use: bare or dotted, imported, defined as a class, or as a string."""
    if isinstance(node, ast.alias):
        return _NAME in (node.name.rpartition(".")[2], node.asname)
    if isinstance(node, ast.ClassDef):
        return node.name == _NAME
    if isinstance(node, ast.Constant):
        return node.value == _NAME
    return _is_tick(node)


def _scan() -> tuple[set[str], set[str]]:
    """(modules that call `AlertTick`, modules that name it), as paths under `candleviewer/`."""
    built: set[str] = set()
    named: set[str] = set()
    for path in sorted(_ROOT.rglob("*.py")):
        module = path.relative_to(_ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        if _NAME not in text:  # every use of the name contains its text: nothing to parse
            continue
        with warnings.catch_warnings():
            # A migration's SQL literal holds `\:`: its SyntaxWarning is no concern of this scan.
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(text, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_tick(node.func):
                built.add(module)
            if _names_tick(node):
                named.add(module)
    return built, named


def test_alert_tick_in_production_code_never_built_and_named_only_in_its_modules() -> None:
    built, named = _scan()
    assert built == set(), _WHY
    assert named <= _HOMES, _WHY
    assert "alerts/evaluator.py" in named, "the scan no longer finds AlertTick: update this test"
