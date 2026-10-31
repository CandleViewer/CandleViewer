"""E29-T06 #914 (#5185's merge-queue run 41230017059): the startup's reconciliation pass and the
requests the startup sweep resumed, on the composed runtime (24 Sec.8.5: a pass never races a
request in flight; 24 Sec.8.2 "Recovery"; BQ-14). The create a crash left `submitting` is resumed
by the sweep's hydration while the account's job is sent `startup`. The venue holds the create at
its door, so the order of its calls is the code's and never the scheduler's. No network, no
sleeps."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import pytest

from candleviewer.oms.order_machine import OrderMachines
from tests.unit.oms import command_rig as cr
from tests.unit.oms.test_handovers import _Store
from tests.unit.oms.test_oms_runtime import SENDING, Port, World, crashed, started, until
from tests.unit.test_oms_reconcile_wiring import Reads


def _methods(port: Port) -> list[str]:
    return [call.method for call in port.calls]


def _held(monkeypatch: pytest.MonkeyPatch) -> asyncio.Event:
    """The venue's creates held at a door the caller opens."""
    door, place = asyncio.Event(), Port.place_order

    async def held(self: Port, request: Any) -> Any:
        await door.wait()
        return await place(self, request)

    monkeypatch.setattr(Port, "place_order", held)
    return door


async def _crashed_world() -> World:
    world = World(handover_store=_Store(), reconcile_reads=Reads())
    await crashed(world)
    for flag in world.flags:
        flag.read()
    return world


async def test_the_startup_pass_reads_nothing_before_the_resumed_create_has_left(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The door opens when the pass reads the executions (it raced the create) or when it waits
    for the create's order to leave `submitting` (it did not), whichever comes first. Before the
    create, only its own lookup reaches the venue; the pass reads after it."""
    world, door = await _crashed_world(), _held(monkeypatch)
    executions, settled = Port.executions, OrderMachines.settled

    async def read(self: Port, *args: Any) -> Any:
        door.set()
        return await executions(self, *args)

    async def waited(self: OrderMachines, account_id: UUID, order_id: UUID, **kw: Any) -> str:
        if order_id == SENDING.id:
            door.set()
        return await settled(self, account_id, order_id, **kw)

    monkeypatch.setattr(Port, "executions", read)
    monkeypatch.setattr(OrderMachines, "settled", waited)
    async with started(world.runtime()) as runtime:
        await asyncio.wait_for(runtime.wait_ready(), 10)  # a bound on the test
        [port] = world.venue.ports
        await until(lambda: "executions" in _methods(port))
        methods = _methods(port)
    sent = methods.index("place_order")
    assert set(methods[:sent]) <= {"open_orders", "order_history"}
    assert "executions" in methods[sent:]
    assert world.store._orders[SENDING.id].lifecycle_state == "submitted"


async def test_ready_waits_neither_for_the_pass_nor_for_the_create_it_holds_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BQ-14: `startup` is sent before `ready`, which waits for neither the pass nor a resumed
    request the pass holds for. With the create held, the runtime is ready and the job fetching,
    and nothing has been read; once the create is let through, the pass reads."""
    world, door = await _crashed_world(), _held(monkeypatch)
    async with started(world.runtime()) as runtime:
        await asyncio.wait_for(runtime.wait_ready(), 10)  # a bound on the test
        reconcile = runtime._composed().reconcile
        assert reconcile is not None
        await until(lambda: reconcile.jobs.state(cr.ACCOUNT) == "fetching")
        [port] = world.venue.ports
        for _ in range(64):
            await asyncio.sleep(0)
        assert runtime.state == "ok" and not {"place_order", "executions"} & set(_methods(port))
        door.set()
        await until(lambda: "executions" in _methods(port))
    assert _methods(port).index("place_order") < _methods(port).index("executions")
