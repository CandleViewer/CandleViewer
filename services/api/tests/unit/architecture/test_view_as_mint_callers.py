"""#3085 (SR-013): only a refresh puts a view-as context on a new session.

`SessionService.mint(view_as=...)` inserts the row with the context it is given, with no start
request, no `admin.view_as_started` record and no eligibility check behind it. Its one production
caller that passes one is `SessionService.refresh`, which hands the successor the context the
rotation claim returned (`claimed.view_as`, never the presented row's). A sign-in
(`mint_enrolment_only`, the MFA step, the enrolment) never passes one. Any other call of `mint` in
`candleviewer` that names `view_as`, or passes a `**` splat that could, fails here and must be
reviewed as a way to start a context without its record first (C-2.9).

Limits: these are AST checks, so an alias of `mint` or a name built at run time is not caught, as
in `test_account_rest_transport_callers.py`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import candleviewer
from candleviewer.auth import session_service

PKG = Path(candleviewer.__file__).resolve().parent
#: The one module that passes a context to `mint`, and the one function in it.
CALLER, FUNCTION = "auth/session_service.py", "refresh"


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


def test_only_the_session_service_passes_a_view_as_context_to_mint() -> None:
    found = {
        path.relative_to(PKG).as_posix()
        for path in PKG.rglob("*.py")
        if "mint" in (text := path.read_text(encoding="utf-8")) and _carriers(ast.parse(text))
    }
    assert found == {CALLER}


def test_the_one_call_is_in_refresh_and_carries_the_claims_context() -> None:
    tree = ast.parse(Path(session_service.__file__).read_text(encoding="utf-8"))
    (call,) = _carriers(tree)
    (refresh,) = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == FUNCTION
    ]
    assert call in ast.walk(refresh)
    assert {kw.arg: ast.unparse(kw.value) for kw in call.keywords}["view_as"] == "claimed.view_as"
