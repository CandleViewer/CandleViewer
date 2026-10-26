"""#3085 S8: every access-token check is classified as answering for the subject or the session.

A resolver that turns the bearer into a principal must ask `view_as_subject`, so a viewing
session's request answers in its target's scope (Q2). Every other check reads the session's own
row, for the reason named. A new call site fails here until it is classified.
"""

from __future__ import annotations

import ast
from pathlib import Path

import candleviewer

_ROOT = Path(candleviewer.__file__).resolve().parent

#: The resolvers: each builds the request's principal, so each asks whose scope it answers in.
_SUBJECT = frozenset(
    {
        ("api/audit_principal.py", "resolve"),
        ("api/me.py", "make_me_router._gate"),
        ("api/order_principal.py", "_read"),
        ("api/rules_actor.py", "resolve"),
        ("api/session_snapshot.py", "resolve"),
    }
)

#: The checks of the session's own row, the viewer's while viewing, and why.
_SESSIONS_OWN = {
    ("api/auth.py", "make_auth_router._enrolling_caller"): "enrols the session's own user",
    ("api/enrolment_guard.py", "make_enrolment_only_guard.enrolment_only_guard"): (
        "classifies the session as enrolment-only, then refuses or passes"
    ),
    ("api/idle_lock.py", "_idle_lock_refusal"): "the session's own idle lock",
    ("api/sessions.py", "make_session_router._authenticate"): (
        "the session's own row: its own operations act on it, and GET /auth/sessions asks the"
        " subject itself"
    ),
    ("api/step_up.py", "make_read_only_guard.guard"): "the session's read-only state",
    ("api/step_up.py", "request_elevation.demand"): (
        "the session's own step-up elevation, for a handler-gated route (#2304 slice 3b)"
    ),
    ("api/step_up.py", "make_step_up_router._session"): (
        "the session's step-up state; the owner check compares the subject (`_owner`)"
    ),
    ("api/users.py", "_elevated"): "the session's own step-up elevation",
    ("api/users.py", "make_users_router.put_user_roles"): (
        "a write, refused by the view-as guard while viewing"
    ),
    ("api/view_as.py", "make_view_as_router._caller"): (
        "the viewer's own session's context, which the routes read and leave (S12)"
    ),
    ("api/view_as.py", "make_view_as_start_router.start_view_as"): (
        "the viewer's own session's row, whose context the start checks and begins (S13b)"
    ),
    ("api/view_as_guard.py", "make_view_as_guard.view_as_guard"): (
        "classifies the session's context (S7)"
    ),
    ("app.py", "_session_authenticator._authenticate"): (
        "the WebSocket's auth: the gateway resolves the target itself (S10, S11)"
    ),
}


class _Sites(ast.NodeVisitor):
    """Each function of one module that calls `authenticate_access_token`, with its callees."""

    def __init__(self, module: str, found: dict[tuple[str, str], set[str]]) -> None:
        self.module, self.found = module, found
        self.stack: list[tuple[str, set[str]]] = []

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.stack.append((node.name, set()))
        self.generic_visit(node)
        name, calls = self.stack.pop()
        if "authenticate_access_token" in calls:
            qualname = ".".join([*(outer for outer, _ in self.stack), name])
            self.found[(self.module, qualname)] = calls

    visit_FunctionDef = visit_AsyncFunctionDef = _function

    def visit_Call(self, node: ast.Call) -> None:
        if self.stack:
            self.stack[-1][1].add(ast.unparse(node.func).rpartition(".")[2])
        self.generic_visit(node)


def _sites() -> dict[tuple[str, str], set[str]]:
    """Each function that calls `authenticate_access_token`, and every callee it calls."""
    found: dict[tuple[str, str], set[str]] = {}
    for path in sorted(_ROOT.rglob("*.py")):
        visitor = _Sites(path.relative_to(_ROOT).as_posix(), found)
        visitor.visit(ast.parse(path.read_bytes(), filename=str(path)))
    return found


def test_each_access_token_check_is_classified() -> None:
    assert set(_sites()) == _SUBJECT | set(_SESSIONS_OWN)


def test_each_resolver_asks_whose_scope_it_answers_in() -> None:
    sites = _sites()
    assert {site for site in _SUBJECT if "view_as_subject" not in sites[site]} == set()
