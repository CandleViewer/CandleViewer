"""#2893 S4: only the composition root routes a transport into the exchange adapter.

The account REST transport reaches `ExchangeBybitService` through two calls in
`candleviewer/app.py`: `create_app` hands the door's handle to
`build_app_context(account_fixture=...)`, which builds the adapter with `rest_transport=`. In any
other product module (`candleviewer/`, `cvdev/`), passing either keyword or a `**` splat to either
call, or naming the adapter's `_rest_transport`, would send signed key-verification calls to a
transport that the `CV_ACCOUNT_FIXTURE` gate never checked (C-2.11, C-12.2). Such a change fails
here, and a security review decides it.

Limits: these are AST checks, so an alias of either callee or a name built at run time is not
caught, as in `test_dev_module_confined.py`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import candleviewer
import cvdev

ROOTS = (Path(candleviewer.__file__).resolve().parent, Path(cvdev.__file__).resolve().parent)
#: Each call on the transport's way into the adapter, and the keyword that carries it.
CARRIERS = {"ExchangeBybitService": "rest_transport", "build_app_context": "account_fixture"}
PRIVATE = "_rest_transport"
#: The adapter, which owns `_rest_transport`.
OWNER = "candleviewer/exchange/bybit/service.py"


def _name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    return node.attr if isinstance(node, ast.Attribute) else None


def _carried(call: ast.Call) -> set[str]:
    """The keyword that would carry the transport in `call`, if it calls a carrier directly,
    through `__init__` or as the first argument (`functools.partial`)."""
    callees = {_name(call.func), *(_name(arg) for arg in call.args[:1])}
    if isinstance(call.func, ast.Attribute) and call.func.attr == "__init__":
        callees.add(_name(call.func.value))
    return {CARRIERS[callee] for callee in callees if callee in CARRIERS}


def _injections(source: str, *, owner: bool = False) -> list[int]:
    """The line of each call that passes a carrier its keyword or a `**` splat and, outside the
    adapter, of each attribute or string naming its private transport."""
    lines = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute | ast.Constant):
            named = node.attr if isinstance(node, ast.Attribute) else node.value
            if named == PRIVATE and not owner:
                lines.append(node.lineno)
        elif (
            isinstance(node, ast.Call)
            and (carried := _carried(node))
            and any(kw.arg is None or kw.arg in carried for kw in node.keywords)
        ):
            lines.append(node.lineno)
    return lines


def _found() -> list[str]:
    found = []
    for root in ROOTS:
        for path in sorted(root.rglob("*.py")):
            text, name = path.read_text(encoding="utf-8"), path.relative_to(root.parent).as_posix()
            if any(word in text for word in (*CARRIERS, PRIVATE)):
                found += [f"{name}:{line}" for line in _injections(text, owner=name == OWNER)]
    return found


@pytest.mark.parametrize(
    "source",
    [
        "ExchangeBybitService(credentials=c, rest_transport=t)",
        "bybit.ExchangeBybitService(**kwargs)",
        "ExchangeBybitService.__init__(svc, rest_transport=t)",
        "functools.partial(ExchangeBybitService, rest_transport=t)",
        "build_app_context(settings, account_fixture=handle)",
        "svc._rest_transport = t",
        "setattr(svc, '_rest_transport', t)",
    ],
)
def test_an_injection_is_found(source: str) -> None:
    assert _injections(source) == [1]


@pytest.mark.parametrize(
    "source",
    [
        "ExchangeBybitService(credentials=c)",
        "build_app_context(settings, auth_clock=clock)",
        "_Fixture(rest_transport=t, private_ws_connect=connect)",
        "transport = handle.rest_transport",
    ],
)
def test_a_non_injection_is_allowed(source: str) -> None:
    assert _injections(source) == []


def test_only_the_composition_root_routes_a_transport_into_the_adapter() -> None:
    """Its two calls, counted, so a third anywhere fails as well; this also shows the scan sees
    them."""
    assert [found.rsplit(":", 1)[0] for found in _found()] == ["candleviewer/app.py"] * 2
