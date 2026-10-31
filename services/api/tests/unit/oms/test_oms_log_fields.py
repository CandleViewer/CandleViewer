"""E29-T08 BQ-9 (#916; 20-architecture.md Sec.12.2, ADR-0006 rule 1): an OMS log line about one
order carries `order_link_id`, `account_id` and `state`, and every line carries `env`.

The order facade binds the order's three fields as structlog contextvars around each step it
takes and each command it judges (`_holding`, every caller's critical section on an order), and
binds the step's own around each write-ahead step (`_persist`), which B1's actions after it read on
the machine's own task. `configure_logging` binds `env` on the serving thread; the order lane runs
its own loop on its own thread, so `env` must reach it there: each lane call runs in its caller's
context, and a task begun on the lane copies the context it began in.

Three guards: an AST one on the facade's source (the binding is where every order's critical
section and step goes through), a `capture_logs` one that drives orders through the real facade and
B1 and reads every line they log, and the lane's thread's own context.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
from collections import OrderedDict
from collections.abc import AsyncIterator, Mapping
from typing import Any

import pytest
import structlog
from structlog.testing import capture_logs

from candleviewer.exchange.base.errors import NotFoundError
from candleviewer.observability import spawn
from candleviewer.oms import order_machine
from candleviewer.oms_lane import OrderLane
from candleviewer.statechart.bindings import b01_order as b01
from tests.unit.oms.order_rig import ACCOUNT, Rig, build_rig, order_of

_FIELDS = ("order_link_id", "account_id", "state")
#: The facade's entry points that act on one order, each through the order's critical section.
_HELD = (
    "command", "push", "push_protection", "settled", "abandon", "hydrate", "_kill_one", "_first",
    "_replay", "_resync", "_turn",
)  # fmt: skip


def _facade_methods() -> dict[str, ast.AST]:
    tree = ast.parse(inspect.getsource(order_machine))
    facade = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "OrderMachines")
    return {n.name: n for n in facade.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)}


def _calls(node: ast.AST) -> set[str]:
    """The dotted names `node` calls (`self._holding`, `structlog.contextvars.bind_contextvars`)."""
    found: set[str] = set()
    for call in ast.walk(node):
        if isinstance(call, ast.Call):
            found.add(ast.unparse(call.func))
    return found


def test_every_entry_point_on_one_order_goes_through_its_critical_section() -> None:
    methods = _facade_methods()
    missing = [name for name in _HELD if "self._holding" not in _calls(methods[name])]
    assert missing == []


def test_the_critical_section_and_the_step_bind_the_orders_fields() -> None:
    methods = _facade_methods()
    assert "structlog.contextvars.bound_contextvars" in _calls(methods["_holding"])
    assert "_order_scope" in _calls(methods["_holding"])
    assert "structlog.contextvars.bind_contextvars" in _calls(methods["_persist"])
    assert "_step_scope" in _calls(methods["_persist"])


def test_the_scopes_name_the_order_its_account_and_its_state() -> None:
    step = b01.Step(
        order_id="o", account_id=str(ACCOUNT), order_link_id="cvl-1", from_state="validated",
        to_state="submitting", event="SEND", payload={}, context={},
    )  # fmt: skip
    assert order_machine._step_scope(step) == {
        "order_link_id": "cvl-1", "account_id": str(ACCOUNT), "state": "submitting"
    }  # fmt: skip


@pytest.fixture
async def rig(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Rig]:
    monkeypatch.setattr(b01, "_ATTEMPTS", OrderedDict())
    built = build_rig()
    yield built
    await built.facade.stop()


def _unscoped(lines: list[Mapping[str, Any]]) -> list[str]:
    """The events of lines that name an order but miss one of its fields."""
    return [
        str(line.get("event"))
        for line in lines
        if line.get("order_link_id") and not all(line.get(field) for field in _FIELDS)
    ]


async def test_every_line_that_names_an_order_carries_its_account_and_state(rig: Rig) -> None:
    """Orders driven through the real facade and B1: a create acked, a create with no known
    outcome, a cancel the venue answered 110001 and a pass that found a live row nowhere."""

    async def ambiguous(_command: b01.Command) -> Mapping[str, Any]:
        raise TimeoutError

    async def gone(_command: b01.Command) -> Mapping[str, Any]:
        raise NotFoundError("no such order", exchange_ret_code=110001)

    with capture_logs(processors=[structlog.contextvars.merge_contextvars]) as lines:
        first = await rig.submitted()
        rig.commands.on_cancel = gone
        await rig.facade.command(ACCOUNT, first.id, "CANCEL", actor="user")
        await rig.quiet()
        second = await rig.submitted(order_of(2))
        await rig.facade.command(
            ACCOUNT, second.id, "RECON_MISS", {"pass_id": "p1"}, actor="system"
        )
        rig.commands.on_place = ambiguous
        third = order_of(3)
        await rig.start(third)
        await rig.facade.command(ACCOUNT, third.id, "SEND", actor="user")
        await rig.quiet()
    named = [line for line in lines if line.get("order_link_id")]
    assert len(named) >= 4  # the guard reads real lines
    assert _unscoped(lines) == []


async def test_env_reaches_the_lane_thread() -> None:
    """`configure_logging` binds `env` on the serving thread: a call on the order lane, and a task
    begun there, read it in their own context, on the lane's own thread."""
    structlog.contextvars.bind_contextvars(env="demo")
    lane = OrderLane(name="oms-env-test")
    await lane.start()
    try:

        async def spawned() -> dict[str, Any]:
            return dict(structlog.contextvars.get_contextvars())

        async def on_lane() -> tuple[dict[str, Any], dict[str, Any], str]:
            import threading

            inner = await spawn(spawned(), name="oms-env-test-child")
            return (dict(structlog.contextvars.get_contextvars()), inner,
                    threading.current_thread().name)  # fmt: skip

        bound, inner, thread = await lane.call(on_lane(), timeout_s=5.0)
    finally:
        await lane.stop()
        structlog.contextvars.unbind_contextvars("env")
    assert thread == "oms-env-test"  # it ran on the lane's own thread
    assert bound.get("env") == "demo", "env is not bound on the order lane"
    assert inner.get("env") == "demo", "env is not bound on a task begun on the lane"


async def test_a_line_logged_on_the_lane_carries_env() -> None:
    structlog.contextvars.bind_contextvars(env="demo")
    lane = OrderLane(name="oms-env-line")
    await lane.start()
    try:

        async def logs() -> None:
            structlog.get_logger("candleviewer.oms.test").info("oms_lane_line")
            await asyncio.sleep(0)

        with capture_logs(processors=[structlog.contextvars.merge_contextvars]) as lines:
            await lane.call(logs(), timeout_s=5.0)
    finally:
        await lane.stop()
        structlog.contextvars.unbind_contextvars("env")
    assert [line.get("env") for line in lines if line["event"] == "oms_lane_line"] == ["demo"]
