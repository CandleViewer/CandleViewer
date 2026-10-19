"""Test doubles for the ports the OMS facade wires into B1 (E29-T03 #847, `b01_order.set_ports`):
a write-ahead store that records each step and a command port that records each command."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from candleviewer.statechart.bindings import b01_order as b01

Reply = Callable[..., Awaitable[object]]


@dataclass
class Store:
    """`PersistPort`: records each `Step` and answers the next `seq`; raises *refuse* (S7), or
    never answers when *hang* (a stalled store, cut off by `CV_PERSIST_TIMEOUT`)."""

    steps: list[b01.Step] = field(default_factory=list)
    refuse: BaseException | None = None
    hang: bool = False

    async def __call__(self, step: b01.Step) -> int:
        if self.hang:
            await asyncio.Event().wait()
        if self.refuse is not None:
            raise self.refuse
        self.steps.append(step)
        return len(self.steps) - 1


async def _ok(_command: b01.Command) -> Mapping[str, Any]:
    return {"ok": True, "exchange_order_id": "x1"}


async def _none(_command: b01.Command) -> Mapping[str, Any]:
    return {}


def _mapping(reply: object) -> Mapping[str, Any]:
    return reply if isinstance(reply, Mapping) else {}


@dataclass
class Commands:
    """`CommandPort`: records each command and answers with its kind's reply coroutine."""

    on_place: Reply = _ok
    on_cancel: Reply = _ok
    on_amend: Reply = _ok
    on_attach: Reply = _ok
    on_lookup: Reply = _none
    sent: list[b01.Command] = field(default_factory=list)

    async def place(self, command: b01.Command) -> Mapping[str, Any]:
        self.sent.append(command)
        return _mapping(await self.on_place(command))

    async def cancel(self, command: b01.Command) -> Mapping[str, Any]:
        self.sent.append(command)
        return _mapping(await self.on_cancel(command))

    async def amend(self, command: b01.Command) -> Mapping[str, Any]:
        self.sent.append(command)
        return _mapping(await self.on_amend(command))

    async def attach_stop(self, command: b01.Command) -> Mapping[str, Any]:
        self.sent.append(command)
        return _mapping(await self.on_attach(command))

    async def lookup(self, command: b01.Command) -> Mapping[str, Any]:
        self.sent.append(command)
        return _mapping(await self.on_lookup(command))

    def kinds(self) -> list[str]:
        return [c.kind for c in self.sent]
