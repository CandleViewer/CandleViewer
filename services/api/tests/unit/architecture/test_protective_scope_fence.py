"""#3085, #913: every protective write resolves its account scope through `scope_for_target`.

22 admits a protective write in a live view-as context only when both the viewer's own RBAC and the
target's `x-rbac` allow it. The view-as guard checks the target's permission for every registered
protective write; the account half is `api.order_principal.scope_for_target`, the viewer's scope
narrowed to the target's trade grants (the orchestrator's ruling of 2026-10-24 23:10Z). A module
of `candleviewer` that registers a protective write (`ProtectiveWrites.register`, by a literal or
a module-level constant) and never calls `scope_for_target` fails here, so no route can forget the
target's grants. Registering in the route's own module is what this enforces: a registration in
`app.py`, which scopes nothing, fails too.

Limits: these are AST checks, so a name built at run time is not caught, as in
`test_view_as_mint_callers.py`. No protective route is mounted on `main` yet; the positive
controls below prove the scan finds one.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import candleviewer
from candleviewer.api.view_as_policy import PROTECTIVE_WRITES

PKG = Path(candleviewer.__file__).resolve().parent
HELPER = "scope_for_target"


def _name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    return node.attr if isinstance(node, ast.Attribute) else None


def _constants(tree: ast.Module) -> dict[str, str]:
    """The module's top-level string constants (`X = "..."`, `X: Final = "..."`)."""
    found: dict[str, str] = {}
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else []
        if isinstance(node, ast.AnnAssign):
            targets = [node.target]
        value = getattr(node, "value", None)
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            found.update({t.id: value.value for t in targets if isinstance(t, ast.Name)})
    return found


def _registered(tree: ast.Module) -> set[str]:
    """The protective writes the module registers: `<x>.register(<operationId>)`."""
    constants, found = _constants(tree), set[str]()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _name(node.func) == "register" and node.args):
            continue
        arg = node.args[0]
        value = arg.value if isinstance(arg, ast.Constant) else None
        if isinstance(arg, ast.Name):
            value = constants.get(arg.id)
        if isinstance(value, str) and value in PROTECTIVE_WRITES:
            found.add(value)
    return found


def _scopes(tree: ast.Module) -> bool:
    return any(isinstance(n, ast.Call) and _name(n.func) == HELPER for n in ast.walk(tree))


def _offenders(sources: dict[str, str]) -> list[str]:
    trees = {name: ast.parse(source) for name, source in sources.items()}
    return sorted(name for name, tree in trees.items() if _registered(tree) and not _scopes(tree))


@pytest.mark.parametrize(
    ("source", "offends"),
    [
        ('app.state.protective_writes.register("cancelOrder")', True),
        ('_OP: Final = "cancelAllOrders"\nprotective.register(_OP)', True),
        ('_OP = "amendOrder"\nprotective.register(_OP)', True),
        ('protective.register("cancelOrder")\nscope = scope_for_target(viewer, target)', False),
        ('protective.register("cancelOrder")\nscope = principals.scope_for_target(v, t)', False),
        ('atexit.register("placeOrder")', False),  # not a protective write
        ("protective.register(operation)", False),  # not a constant: out of the scan's reach
    ],
)
def test_the_scan_finds_a_protective_registration_with_no_scope(source: str, offends: bool) -> None:
    assert _offenders({"m.py": source}) == (["m.py"] if offends else [])


def test_every_module_registering_a_protective_write_scopes_through_the_helper() -> None:
    sources = {str(path.relative_to(PKG)): path.read_text() for path in PKG.rglob("*.py")}
    assert _offenders(sources) == []
