"""#3085 (SR-013): only a rotation puts a view-as context on a new session, through one carrier.

`SessionService.mint(view_as=...)` inserts the row with the context it is given, with no start
request, no `admin.view_as_started` record and no eligibility check behind it. Its one production
call that passes one is in `SessionService._mint_successor`, which hands a rotation's successor
the context the rotation's claim returned (`claimed.view_as`, never a row read before the claim).
The helper's callers are `refresh` and `rotate` (a step-up's rotation, #2101), each passing the
row its own claim returned: a rotation hands over a context that already has its record (C-2.9),
the same context with the same target and expiry, never a wider one. A sign-in
(`mint_enrolment_only`, the MFA step, the enrolment) never passes one. Any other call of `mint` in
`candleviewer` that names `view_as`, or passes a `**` splat that could, and any other caller of
the helper fails here and must be reviewed as a way to start a context without its record first
(C-2.9).

Limits: these are AST checks, so an alias of `mint` or a name built at run time is not caught, as
in `test_account_rest_transport_callers.py`. The helper's checks see every name or attribute
`_mint_successor`, so an alias of the helper is caught.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import candleviewer
from candleviewer.auth import session_service

PKG = Path(candleviewer.__file__).resolve().parent
#: The one module that passes a context to `mint`, the one function in it that does, and the two
#: rotations that call that function, each with the row its claim returned.
CALLER, HELPER, ROTATIONS = "auth/session_service.py", "_mint_successor", ("refresh", "rotate")
_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    return node.attr if isinstance(node, ast.Attribute) else None


def _carries_a_context(call: ast.Call) -> bool:
    """A call of `mint`, directly or as `functools.partial`'s first argument, that names
    `view_as` or passes a `**` splat."""
    callees = {_name(call.func), *(_name(arg) for arg in call.args[:1])}
    return "mint" in callees and any(kw.arg in (None, "view_as") for kw in call.keywords)


def _carriers(tree: ast.AST) -> list[ast.Call]:
    return [
        node for node in ast.walk(tree) if isinstance(node, ast.Call) and _carries_a_context(node)
    ]


def _helper_references(tree: ast.AST) -> list[tuple[str, ast.expr]]:
    """Each name or attribute `_mint_successor` in *tree*, a call's or an alias's, with the name
    of the innermost function it is in (`""` at module level)."""
    found: list[tuple[str, ast.expr]] = []

    def visit(node: ast.AST, function: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.Name, ast.Attribute)) and _name(child) == HELPER:
                found.append((function, child))
            visit(child, child.name if isinstance(child, _DEFS) else function)

    visit(tree, "")
    return found


@pytest.mark.parametrize(
    "source",
    [
        "sessions.mint(uid, view_as=state)",
        "sessions.mint(uid, view_as=None)",
        "sessions.mint(uid, **kwargs)",
        "mint(uid, view_as=state)",
        "functools.partial(sessions.mint, view_as=state)",
    ],
)
def test_a_mint_that_can_carry_a_context_is_found(source: str) -> None:
    assert len(_carriers(ast.parse(source))) == 1


@pytest.mark.parametrize(
    "source",
    [
        "sessions.mint(uid)",
        "sessions.mint(uid, ip=ip, user_agent=ua, session_id=sid)",
        "self.mint(user_id, mfa_satisfied=False, expires_at=deadline)",
        "sessions.mint_enrolment_only(uid, session_id=sid)",
        "other.view_as(state)",
    ],
)
def test_a_mint_that_names_no_context_is_allowed(source: str) -> None:
    assert _carriers(ast.parse(source)) == []


@pytest.mark.parametrize(
    "source",
    [
        "async def f(self):\n    await self._mint_successor(claimed, user_id=uid)",
        "def f(self):\n    carry = self._mint_successor",
        "def f(self):\n    return functools.partial(self._mint_successor, claimed)",
        "async def g(self):\n    async def f():\n        await _mint_successor(claimed)",
    ],
)
def test_a_reference_to_the_helper_is_found_in_its_innermost_function(source: str) -> None:
    assert [function for function, _ in _helper_references(ast.parse(source))] == ["f"]


def test_only_the_session_service_passes_a_view_as_context_to_mint() -> None:
    found = {
        path.relative_to(PKG).as_posix()
        for path in PKG.rglob("*.py")
        if "mint" in (text := path.read_text(encoding="utf-8")) and _carriers(ast.parse(text))
    }
    assert found == {CALLER}


def test_the_one_call_is_in_the_helper_and_carries_the_claims_context() -> None:
    tree = ast.parse(Path(session_service.__file__).read_text(encoding="utf-8"))
    (call,) = _carriers(tree)
    (helper,) = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == HELPER
    ]
    assert call in ast.walk(helper)
    assert {kw.arg: ast.unparse(kw.value) for kw in call.keywords}["view_as"] == "claimed.view_as"


def test_only_refresh_and_rotate_call_the_helper_each_with_its_claim() -> None:
    """Once each, as a call (no alias), the row its own claim returned (`claimed`) passed as the
    helper's one positional argument, never a row read before the claim."""
    tree = ast.parse(Path(session_service.__file__).read_text(encoding="utf-8"))
    calls = {id(node.func): node for node in ast.walk(tree) if isinstance(node, ast.Call)}
    found = _helper_references(tree)
    assert tuple(sorted(function for function, _ in found)) == ROTATIONS
    for _, reference in found:
        call = calls.get(id(reference))
        assert call is not None, "an alias of the helper, not a call"
        assert [ast.unparse(arg) for arg in call.args] == ["claimed"]


def test_no_other_module_names_the_helper() -> None:
    found = {
        path.relative_to(PKG).as_posix()
        for path in PKG.rglob("*.py")
        if HELPER in (text := path.read_text(encoding="utf-8"))
        and _helper_references(ast.parse(text))
    }
    assert found == {CALLER}
