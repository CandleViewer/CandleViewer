"""#913 L1d-1: no product module builds the adapter's serving-loop port.

`ExchangeBybitService.trading_port` builds a `TradingPort` that M2's serving-loop borrower signs
for, on the adapter's own account transport. Since L1d-1 the OMS trades through the adapter's
lane port (`lane_trading_port`), signed on the order lane, so nothing in `candleviewer/` or
`cvdev/` calls `trading_port`: a port built from it would sign on the serving loop and send
outside the OMS's anchors and write-ahead audit (C-2.9). An attribute `trading_port` anywhere
there, called or passed on, or a call that reaches it by its name, fails here, and a security
review decides it (C-2.2). Whether the method stays is L1d-2's call (E29's ticket map,
`E29-oms.md` §11): the private streams stay on the serving loop (ruling Q2 (b)), and its own
tests still call it.

Limits: these are AST checks, as in `test_account_rest_transport_callers.py`: an alias of the
method or a name built at run time is not caught.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import candleviewer
import cvdev
from candleviewer.exchange.bybit.service import ExchangeBybitService

ROOTS = (Path(candleviewer.__file__).resolve().parent, Path(cvdev.__file__).resolve().parent)
#: The adapter's method that builds a port signed on the serving loop.
NAME = "trading_port"
#: The calls that reach an attribute by its name.
BY_NAME = frozenset({"getattr", "attrgetter", "methodcaller"})


def _name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    return node.attr if isinstance(node, ast.Attribute) else None


def _uses(source: str) -> list[int]:
    """The line of each attribute `trading_port`, called or passed on, and of each call that
    reaches it by its name (`getattr`, `operator.attrgetter`, `operator.methodcaller`)."""
    lines = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute) and node.attr == NAME:
            lines.append(node.lineno)
        elif (
            isinstance(node, ast.Call)
            and _name(node.func) in BY_NAME
            and any(isinstance(arg, ast.Constant) and arg.value == NAME for arg in node.args)
        ):
            lines.append(node.lineno)
    return lines


def _found() -> list[str]:
    found = []
    for root in ROOTS:
        for path in sorted(root.rglob("*.py")):
            text, name = path.read_text(encoding="utf-8"), path.relative_to(root.parent).as_posix()
            if NAME in text:
                found += [f"{name}:{line}" for line in _uses(text)]
    return found


@pytest.mark.parametrize(
    "source",
    [
        "ctx.exchange_bybit.trading_port(env)",
        "self._venue.trading_port(env, clock_offset_ms=offset)",
        "super().trading_port(env)",
        "build = venue.trading_port",
        "functools.partial(venue.trading_port, 'demo')",
        "getattr(venue, 'trading_port')('demo')",
        "operator.attrgetter('trading_port')(venue)",
        "operator.methodcaller('trading_port', 'demo')(venue)",
    ],
)
def test_a_use_is_found(source: str) -> None:
    assert _uses(source) == [1]


@pytest.mark.parametrize(
    "source",
    [
        "self._venue.lane_trading_port(env, credentials=borrower)",
        "closers.insert(0, ('trading_port', close))",
        "getattr(venue, 'lane_trading_port')",
        "def trading_port(self, env): ...",
    ],
)
def test_a_non_use_is_allowed(source: str) -> None:
    assert _uses(source) == []


def test_no_product_module_builds_the_adapters_serving_loop_port() -> None:
    """Counted, none: the OMS's port is the lane's (#913 L1d-1). The method is still there, so
    the count guards something until L1d-2 decides whether it stays."""
    assert callable(getattr(ExchangeBybitService, NAME, None))
    assert _found() == []
