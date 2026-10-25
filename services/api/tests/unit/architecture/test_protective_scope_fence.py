"""#3085, #913: every protective write resolves its account scope through `scope_for_target`.

22 admits a protective write in a live view-as context only when both the viewer's own RBAC and the
target's `x-rbac` allow it. The view-as guard checks the target's permission for every registered
protective write; the account half is `api.order_principal.scope_for_target`, the viewer's scope
narrowed to the target's trade grants (22 "View-as session", Protective writes). A module of
`candleviewer` that registers a protective write (`ProtectiveWrites.register`, by a literal or a
module-level constant) and never takes its scope from the helper fails here, so no route can forget
the target's grants. Registering in the route's own module is what this enforces: a registration in
`app.py`, which scopes nothing, fails too.

A module takes its scope from the helper when it calls `scope_for_target(<viewer>, <x>.target)`,
the second argument an attribute named `target`, by position or as `target=`; or when it calls a
function it imports from another `candleviewer.api` module (`from candleviewer.api.x import f`,
or `from candleviewer.api import x` and `x.f(...)`) whose own body makes such a call. That is one
hop: the routes of `order_exits.py` call `exit_caller` of `order_exits_common.py`.

Limits: these are AST checks of presence, not of flow. A name built at run time, a bound-method
alias of `register`, an imported constant and a registration outside the package are not seen, as
in `test_view_as_mint_callers.py`; nor is a helper that is a method or a class, a relative or
dotted import of it, or a second hop. A call is not proven to be the scope the route's reads take,
so one in dead code, or with its result unused, passes: each protective route's own tests are that
guarantee. The scan fails when it read fewer than `MIN_MODULES` modules, since one of an emptied or
moved root finds nothing. No protective route is mounted on `main` yet; the positive controls
below prove the scan finds one.
"""

from __future__ import annotations

import ast
import warnings
from collections.abc import Mapping
from pathlib import Path

import pytest

import candleviewer
from candleviewer.api.view_as_policy import PROTECTIVE_WRITES

PKG = Path(candleviewer.__file__).resolve().parent
HELPER = "scope_for_target"
API = "candleviewer.api"
#: The scan reads some 880 modules today; one that read far fewer lost its input (a moved root, a
#: changed pattern), and a scan of nothing finds nothing.
MIN_MODULES = 400


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
    """The protective writes the module registers: `<x>.register(<operationId>)`, positionally
    or as `operation_id=`."""
    constants, found = _constants(tree), set[str]()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _name(node.func) == "register"):
            continue
        named = [k.value for k in node.keywords if k.arg == "operation_id"]
        if not (arg := node.args[0] if node.args else next(iter(named), None)):
            continue
        value = arg.value if isinstance(arg, ast.Constant) else None
        if isinstance(arg, ast.Name):
            value = constants.get(arg.id)
        if isinstance(value, str) and value in PROTECTIVE_WRITES:
            found.add(value)
    return found


def _passes_target(call: ast.Call) -> bool:
    """The call's second argument, by position or as `target=`, is a `<x>.target` attribute."""
    named = [k.value for k in call.keywords if k.arg == "target"]
    arg = call.args[1] if len(call.args) > 1 else next(iter(named), None)
    return isinstance(arg, ast.Attribute) and arg.attr == "target"


def _scopes_here(node: ast.AST) -> bool:
    """*node* holds a call of the helper that passes the target."""
    return any(
        isinstance(n, ast.Call) and _name(n.func) == HELPER and _passes_target(n)
        for n in ast.walk(node)
    )


def _api_imports(tree: ast.Module) -> dict[str, tuple[str, str | None]]:
    """What the module imports from `candleviewer.api`, by the name it binds: the module's path
    under the package, and the name taken from it (`None`: the module itself)."""
    found: dict[str, tuple[str, str | None]] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ImportFrom) and node.level == 0 and node.module):
            continue
        if node.module == API:
            found.update({a.asname or a.name: (f"api/{a.name}.py", None) for a in node.names})
        elif node.module.startswith(f"{API}."):
            path = node.module.removeprefix("candleviewer.").replace(".", "/") + ".py"
            found.update({a.asname or a.name: (path, a.name) for a in node.names})
    return found


def _callee(
    call: ast.Call, imported: Mapping[str, tuple[str, str | None]]
) -> tuple[str, str] | None:
    """The (module path, function) a call names through an import from `candleviewer.api`:
    `f(...)` after `from candleviewer.api.x import f`, `x.f(...)` after `from candleviewer.api
    import x`; `None` for any other call."""
    func = call.func
    if isinstance(func, ast.Name) and func.id in imported:
        path, taken = imported[func.id]
        return (path, taken) if taken else None
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        bound = imported.get(func.value.id)
        return (bound[0], func.attr) if bound and bound[1] is None else None
    return None


def _scopes_by_hop(tree: ast.Module, trees: Mapping[str, ast.Module]) -> bool:
    """The module calls a function of another `candleviewer.api` module, one it imports, whose own
    body passes the target to the helper (one hop, by name)."""
    imported = _api_imports(tree)
    for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
        callee = _callee(call, imported)
        if callee is None or callee[0] not in trees:
            continue
        path, name = callee
        defs = [
            n for n in trees[path].body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
        ]
        if any(d.name == name and _scopes_here(d) for d in defs):
            return True
    return False


def _offenders(sources: Mapping[str, str]) -> list[str]:
    with warnings.catch_warnings():  # an immutable migration's escape sequences (C-5.4)
        warnings.simplefilter("ignore", SyntaxWarning)
        trees = {name: ast.parse(source, filename=name) for name, source in sources.items()}
    return sorted(
        name
        for name, tree in trees.items()
        if _registered(tree) and not (_scopes_here(tree) or _scopes_by_hop(tree, trees))
    )


def _sources(root: Path) -> dict[str, str]:
    """Every module under *root*, by its path relative to it."""
    return {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
        for path in root.rglob("*.py")
    }


def _scan(root: Path, *, at_least: int) -> list[str]:
    """The modules under *root* that register a protective write and never take its scope from
    the helper. A scan that read fewer than *at_least* modules fails: it found nothing to judge."""
    sources = _sources(root)
    assert len(sources) >= at_least, (
        f"the scan read {len(sources)} modules under {root}, not {at_least}"
    )
    return _offenders(sources)


_REGISTERS = 'protective.register("cancelOrder")\n'


@pytest.mark.parametrize(
    ("source", "offends"),
    [
        ('app.state.protective_writes.register("cancelOrder")', True),
        ('_OP: Final = "cancelAllOrders"\nprotective.register(_OP)', True),
        ('_OP = "amendOrder"\nprotective.register(_OP)', True),
        ('protective.register(operation_id="cancelOrder")', True),
        (_REGISTERS + "scope = scope_for_target(p.snapshot, p.target)", False),
        (_REGISTERS + "scope = principals.scope_for_target(v, p.target)", False),
        (_REGISTERS + "scope = scope_for_target(p.snapshot, target=p.target)", False),
        (_REGISTERS + "scope = scope_for_target(p.snapshot, None)", True),  # no target passed
        (_REGISTERS + "scope = scope_for_target(p.snapshot, t)", True),  # a name, not `.target`
        (_REGISTERS + "scope = scope_for_target(p.snapshot, p.snapshot)", True),  # not `.target`
        (_REGISTERS + "scope = scope_for_target(p.snapshot)", True),
        ('atexit.register("placeOrder")', False),  # not a protective write
        ("protective.register(operation)", False),  # not a constant: out of the scan's reach
        ("protective.register()", False),  # names nothing
    ],
)
def test_the_scan_finds_a_protective_registration_with_no_scope(source: str, offends: bool) -> None:
    assert _offenders({"m.py": source}) == (["m.py"] if offends else [])


def _route(imports: str, call: str) -> str:
    """A route module: it imports, registers a protective write and calls."""
    return f"{imports}\n{_REGISTERS}{call}\n"


_COMMON = "from candleviewer.api.common import caller"
_SCOPED = "def caller(p):\n    return scope_for_target(p.snapshot, p.target)\n"


@pytest.mark.parametrize(
    ("sources", "offenders"),
    [
        ({"api/r.py": _route(_COMMON, "caller(p)"), "api/common.py": _SCOPED}, []),
        ({"api/r.py": _route(_COMMON + " as c", "c(p)"), "api/common.py": _SCOPED}, []),
        (
            {
                "api/r.py": _route("from candleviewer.api import common as k", "k.caller(p)"),
                "api/common.py": _SCOPED,
            },
            [],
        ),
        ({"api/r.py": _route(_COMMON, ""), "api/common.py": _SCOPED}, ["api/r.py"]),  # not called
        (
            {"api/r.py": _route(_COMMON, "caller(p)"), "api/common.py": "def caller(p): ..."},
            ["api/r.py"],  # the helper scopes nothing
        ),
        (
            {
                "api/r.py": _route(_COMMON, "caller(p)"),
                "api/common.py": "def caller(p):\n    return scope_for_target(p.snapshot, None)",
            },
            ["api/r.py"],  # and one that passes no target scopes nothing either
        ),
        (
            {
                "api/r.py": _route(_COMMON.replace("caller", "other"), "other(p)"),
                "api/common.py": _SCOPED + "def other(p): ...",
            },
            ["api/r.py"],  # another function of the module it imports
        ),
        (
            {
                "api/r.py": _route("from candleviewer.oms.common import caller", "caller(p)"),
                "oms/common.py": _SCOPED,
            },
            ["api/r.py"],  # outside `candleviewer.api`
        ),
        (
            {
                "api/r.py": _route(_COMMON, "caller(p)"),
                "api/common.py": "from candleviewer.api.leaf import caller as inner\n"
                "def caller(p):\n    return inner(p)",
                "api/leaf.py": _SCOPED,
            },
            ["api/r.py"],  # a second hop
        ),
        # a module the scan did not read: no hop to follow, and named, never a KeyError
        ({"api/r.py": _route(_COMMON, "caller(p)")}, ["api/r.py"]),
    ],
)
def test_the_scan_follows_one_import_hop_within_the_api_package(
    sources: dict[str, str], offenders: list[str]
) -> None:
    """`order_exits.py` registers its routes and calls `exit_caller` of `order_exits_common.py`,
    which takes the scope: a call there counts, by name and one hop only."""
    assert _offenders(sources) == offenders


def test_a_module_that_does_not_parse_is_named() -> None:
    with pytest.raises(SyntaxError) as raised:
        _offenders({"api/broken.py": "def ("})
    assert raised.value.filename == "api/broken.py"


def test_a_scan_that_read_too_few_modules_fails(tmp_path: Path) -> None:
    """A scan of an emptied or moved root finds nothing and passes: it must have read its input."""
    (tmp_path / "m.py").write_text(_REGISTERS, encoding="utf-8")
    with pytest.raises(AssertionError, match="read 1 modules"):
        _scan(tmp_path, at_least=2)
    assert _scan(tmp_path, at_least=1) == ["m.py"]  # and what it read, it judged


def test_every_module_registering_a_protective_write_scopes_through_the_helper() -> None:
    assert _scan(PKG, at_least=MIN_MODULES) == []
