"""#837 (E27-T04): who may build an order-entry gate.

`OrderEntryGate(maintenance, *account_checks)` is where orders are refused (C-2.21): a gate of the
maintenance check alone would admit an account that is down, keyless or disabled.
`FeatureFlagsRuntime.compose_order_entry_gate` builds the app's one gate, once and never without
the account check, and `create_app` serves it to every router and holder. Nothing else of
`candleviewer` may build one. `test_order_entry_gate_wiring.py` watches what `create_app` builds
at run time; this reads the source, so a gate built anywhere else is a reviewed edit to `ALLOWED`.

A function builds one where it names the class outside an annotation: a call, a reference kept in
a variable and a subclass alike. An import that renames the class counts too, since the scan would
not know the new name; `import X as X`, the explicit re-export idiom, renames nothing.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import candleviewer

PKG = Path(candleviewer.__file__).resolve().parent
GATE = "OrderEntryGate"
#: Module -> the functions in it that name the class outside an annotation.
ALLOWED = {"flags_wiring.py": frozenset({"FeatureFlagsRuntime.compose_order_entry_gate"})}
_SCOPES = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def _annotations(tree: ast.AST) -> set[int]:
    """The ids of every node inside an annotation."""
    roots: list[ast.expr] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.arg | ast.AnnAssign) and node.annotation is not None:
            roots.append(node.annotation)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.returns:
            roots.append(node.returns)
    return {id(inner) for root in roots for inner in ast.walk(root)}


def _builders(text: str) -> frozenset[str]:
    """The dotted names of the functions that name `OrderEntryGate` outside an annotation
    (`<module>` at module level), and `import as` for an import that renames it."""
    tree = ast.parse(text)
    annotated, found = _annotations(tree), set[str]()

    def visit(node: ast.AST, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            named = (isinstance(child, ast.Name) and child.id == GATE) or (
                isinstance(child, ast.Attribute) and child.attr == GATE
            )
            if named and id(child) not in annotated:
                found.add(scope)
            if (
                isinstance(child, ast.alias)
                and child.name == GATE
                and child.asname not in (None, GATE)
            ):
                found.add("import as")
            inner = scope
            if isinstance(child, _SCOPES):
                inner = child.name if scope == "<module>" else f"{scope}.{child.name}"
            visit(child, inner)

    visit(tree, "<module>")
    return frozenset(found)


def _builds() -> dict[str, frozenset[str]]:
    found: dict[str, frozenset[str]] = {}
    for path in PKG.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if GATE in text and (builders := _builders(text)):
            found[path.relative_to(PKG).as_posix()] = builders
    return found


def test_only_compose_order_entry_gate_builds_an_order_entry_gate() -> None:
    assert _builds() == ALLOWED


@pytest.mark.parametrize(
    ("source", "builders"),
    [
        ("class R:\n    def build(self, m):\n        return OrderEntryGate(m)", {"R.build"}),
        ("make = order_entry.OrderEntryGate", {"<module>"}),
        ("class Lax(OrderEntryGate): ...", {"Lax"}),  # a class's bases count as its own
        ("from candleviewer.domain.order_entry import OrderEntryGate as Gate", {"import as"}),
        # the explicit re-export idiom keeps the name, so the scan still knows it
        ("from candleviewer.domain.order_entry import OrderEntryGate as OrderEntryGate", set()),
        ("def read(g: OrderEntryGate) -> OrderEntryGate | None:\n    h: OrderEntryGate = g", set()),
    ],
    ids=["call", "reference", "subclass", "renaming-import", "re-export-idiom", "annotations"],
)
def test_the_scan_sees_each_way_to_build_a_gate_and_skips_annotations(
    source: str, builders: set[str]
) -> None:
    assert _builders(source) == builders
