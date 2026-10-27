"""#913 L1d-1 and L1d-2c: no product module builds the adapter's serving-loop port, and the
adapter no longer has one.

`ExchangeBybitService.trading_port` built a `TradingPort` that M2's serving-loop borrower signed
for, on the adapter's own account transport. Since L1d-1 the OMS trades through the adapter's
lane port (`lane_trading_port`), signed on the order lane, and L1d-2c removed the method (E29's
ticket map, `E29-oms.md` §11): its tests build the lane's port or an exposure port, or open the
account's stream from the adapter's one registry (`open_private_stream`). A port built on the
serving loop for trading would sign there and send outside the OMS's anchors and write-ahead
audit (C-2.9). An attribute `trading_port` anywhere in `candleviewer/` or `cvdev/`, called or
passed on, a call that reaches it by its name, or the method added back fails here, and a
security review decides it (C-2.2).

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
#: The adapter's method that built a port signed on the serving loop, removed in #913 L1d-2c.
NAME = "trading_port"
#: The serving loop's one remaining port builder (#913 L1d-2c), and its one product caller: the
#: exposure read (#898 B2a).
EXPOSURE = "exposure_port"
EXPOSURE_CALLERS = ["candleviewer/exposure_wiring.py"]
#: The calls that reach an attribute by its name.
BY_NAME = frozenset({"getattr", "attrgetter", "methodcaller"})


def _name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    return node.attr if isinstance(node, ast.Attribute) else None


def _uses(source: str, name: str = NAME) -> list[int]:
    """The line of each attribute `name`, called or passed on, and of each call that reaches it
    by its name (`getattr`, `operator.attrgetter`, `operator.methodcaller`)."""
    lines = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute) and node.attr == name:
            lines.append(node.lineno)
        elif (
            isinstance(node, ast.Call)
            and _name(node.func) in BY_NAME
            and any(isinstance(arg, ast.Constant) and arg.value == name for arg in node.args)
        ):
            lines.append(node.lineno)
    return lines


def _found(name: str = NAME) -> list[str]:
    found = []
    for root in ROOTS:
        for path in sorted(root.rglob("*.py")):
            text, where = path.read_text(encoding="utf-8"), path.relative_to(root.parent).as_posix()
            if name in text:
                found += [f"{where}:{line}" for line in _uses(text, name)]
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
    """Counted, none: the OMS's port is the lane's (#913 L1d-1), and the adapter has no
    `trading_port` to build one with (#913 L1d-2c)."""
    assert not hasattr(ExchangeBybitService, NAME)
    assert _found() == []


def test_the_serving_loops_one_remaining_port_keeps_its_one_product_caller() -> None:
    """`exposure_port` builds the serving loop's one remaining port, signed for by M2's
    serving-loop borrower. Its one product caller is the exposure read; another would be a trading
    path outside the OMS's anchors and write-ahead audit (C-2.9), so it fails here and a security
    review decides it (C-2.2)."""
    assert sorted({use.rsplit(":", 1)[0] for use in _found(EXPOSURE)}) == EXPOSURE_CALLERS
