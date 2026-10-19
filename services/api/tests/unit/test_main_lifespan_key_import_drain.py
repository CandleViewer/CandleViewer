"""#836 slice 2b4: the ASGI lifespan drains the key imports in flight before the audit module
stops. An import its request no longer awaits writes its closing record through the audit writer
and M2, which `stop_all` stops; `KeyImports.drain` waits for it, then releases the import's
Postgres pool. Behavioural, through the `test_main_lifespan.py` harness as
`test_main_lifespan_access_drain.py` is: the fake `audit` module marks the event log when it is
stopped, so removing or reordering the drain fails here."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import FastAPI

from candleviewer.accounts.key_import import KeyImportFailed
from candleviewer.key_import_wiring import KeyImports
from candleviewer.main import _lifespan
from tests.unit.accounts.test_key_import import World
from tests.unit.test_main_lifespan import _fake_ctx


class _AuditModule:
    def __init__(self, events: list[tuple[Any, ...]]) -> None:
        self.events = events

    async def start(self, ctx: object) -> None:
        return None

    async def stop(self, grace_s: float) -> None:
        self.events.append(("audit stopped",))


async def test_a_stop_waits_for_an_import_in_flight_to_write_its_closing_record() -> None:
    world = World()
    world.gate.clear()  # the import waits inside M2's check until the shutdown has begun
    world.written = False  # then the verified columns change no row: M2 destroys the key

    async def release() -> None:
        world.events.append(("pool released",))

    app, ctx = FastAPI(), _fake_ctx()
    ctx.audit = _AuditModule(world.events)
    app.state.app_context, app.state.key_imports = ctx, KeyImports(world.flow, release)
    work = app.state.key_imports.run(world.run())
    await world.entered.wait()
    async with _lifespan(app):
        # It goes on at the next turn of the loop, which only the drain gives it before the
        # audit module stops (the fake modules never suspend).
        asyncio.get_running_loop().call_soon(world.gate.set)
    with pytest.raises(KeyImportFailed):
        await work
    closing = ["destroy", ("audit", "failure"), "pool released", "audit stopped"]
    assert world.kinds()[-4:] == closing
