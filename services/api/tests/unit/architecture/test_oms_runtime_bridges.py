"""#913 slice 3 L2 (the orchestrator's carries of 2026-10-25 14:32Z, from vw3's #4525): the order
lane's bridges, and the one reader of the runtime off the app's state.

- Each `OnLane*` bridge re-declares the coroutines it hops to the order lane (20 Sec.6.2), so a
  parameter the wrapped coroutine has and the bridge lacks is a `TypeError` in the route that
  passes it, or a value the service never sees (`OnLaneExits.deny`'s `step`, #4525). Every public
  coroutine of a bridge is listed here with the class whose same-named coroutine it wraps, and
  takes exactly its parameters, by name, kind and default: `OnLane` and `OnLaneGroups` against
  the pipeline, the anchors and the reads they wrap, `OnLaneExits` and `OnLaneCancelAll` against
  their services. The bridge the other way, `LaneStreams` (#913 L1d-2b), opens and closes on the
  serving loop through the adapter's stream registry, `PrivateStreams`, and takes its parameters.
- `app.state.oms_runtime` is read only through `app.oms_runtime_of`, typed, so the type checker
  holds the runtime to each route's protocol: the composition root assigns it, and nothing else
  reads Starlette's untyped attribute.
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from starlette.datastructures import State

import candleviewer
from candleviewer import app
from candleviewer.accounts.trade_group_repository import TradeGroupReader
from candleviewer.exchange.bybit.private_stream import PrivateStreams
from candleviewer.oms.cancel_all import CancelAll
from candleviewer.oms.exits import OrderExits
from candleviewer.oms.idempotency import AnchorService
from candleviewer.oms.repository import OrderRepository
from candleviewer.oms.submit import OrderSubmission
from candleviewer.oms_streams import LaneStreams
from candleviewer.oms_wiring import (
    OnLane,
    OnLaneCancelAll,
    OnLaneExits,
    OnLaneGroups,
    OnLanePreview,
    PreviewFigures,
    TradingAccountsBinding,
)

PKG = Path(candleviewer.__file__).resolve().parent
#: Each bridge's public coroutines, by the class whose same-named coroutine it hops to the lane.
WRAPPED: dict[type, dict[str, type]] = {
    OnLane: {
        "submit": OrderSubmission,
        "answer_replay": OrderSubmission,
        "lookup": AnchorService,
        "environment_of": TradingAccountsBinding,
        "get": OrderRepository,
    },
    OnLaneGroups: {"get": TradeGroupReader},
    OnLaneExits: dict.fromkeys(
        ("scope", "accounts_in_scope", "deny", "cancel_admitted", "amend"), OrderExits
    ),
    OnLaneCancelAll: dict.fromkeys(("scope", "run"), CancelAll),
    OnLanePreview: {"peeked": PreviewFigures},  # E28-T05 S3c: the preview's figures
    LaneStreams: dict.fromkeys(("open", "aclose"), PrivateStreams),
}
HOPS = [(bridge, name) for bridge, wrapped in WRAPPED.items() for name in wrapped]


def _parameters(function: Callable[..., Any]) -> list[tuple[str, object, object]]:
    return [(p.name, p.kind, p.default) for p in inspect.signature(function).parameters.values()]


@pytest.mark.parametrize("bridge", list(WRAPPED), ids=lambda bridge: bridge.__name__)
def test_every_coroutine_a_bridge_hops_to_the_lane_is_listed_with_what_it_wraps(
    bridge: type,
) -> None:
    hops = {n for n, _ in inspect.getmembers(bridge, inspect.iscoroutinefunction) if n[0] != "_"}
    assert hops == set(WRAPPED[bridge])


@pytest.mark.parametrize(("bridge", "name"), HOPS, ids=[f"{b.__name__}.{n}" for b, n in HOPS])
def test_each_bridge_coroutine_takes_exactly_the_parameters_of_the_one_it_wraps(
    bridge: type, name: str
) -> None:
    wrapped = getattr(WRAPPED[bridge][name], name)
    assert inspect.iscoroutinefunction(wrapped)
    assert _parameters(getattr(bridge, name)) == _parameters(wrapped)


class _Readers(ast.NodeVisitor):
    """Each read of `<x>.state.oms_runtime`, or `getattr(<x>, "oms_runtime", ...)`, by the
    innermost function it is in (`<module>` outside one)."""

    def __init__(self) -> None:
        self.where: list[str] = ["<module>"]
        self.found: set[str] = set()

    def _within(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.where.append(node.name)
        self.generic_visit(node)
        self.where.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._within(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._within(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        state = isinstance(node.value, ast.Attribute) and node.value.attr == "state"
        if node.attr == "oms_runtime" and state and isinstance(node.ctx, ast.Load):
            self.found.add(self.where[-1])
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        named = isinstance(node.func, ast.Name) and node.func.id == "getattr"
        key = node.args[1] if named and len(node.args) > 1 else None
        if isinstance(key, ast.Constant) and key.value == "oms_runtime":
            self.found.add(self.where[-1])
        self.generic_visit(node)


def test_only_the_typed_accessor_reads_the_runtime_off_the_app_state() -> None:
    readers = set[tuple[str, str]]()
    for path in sorted(PKG.rglob("*.py")):
        visitor = _Readers()
        visitor.visit(ast.parse(path.read_text(encoding="utf-8")))
        readers |= {(path.relative_to(PKG).as_posix(), where) for where in visitor.found}
    assert readers == {("app.py", "oms_runtime_of")}


def test_the_accessor_gives_the_states_runtime_or_none() -> None:
    state, runtime = State(), object()
    assert app.oms_runtime_of(state) is None  # the fake backend composes none
    state.oms_runtime = runtime
    assert app.oms_runtime_of(state) is runtime
