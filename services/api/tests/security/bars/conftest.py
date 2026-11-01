"""Fixtures for the E12-X02 bars abuse suite (#452).

`stores` is E12-Q04's fixture-backed market app (`tests/contract/_market_world.py`, recorded data
only, C-13.5) with a spy on each of its four storage calls: the recording-start read, the print
count behind the non-time estimate (`trade_totals`), the bar read and the hot kline read. A
`faults` entry replaces one call's answer (a hang on an `asyncio.Event` nobody sets, or a raise),
so a deadline is tested without a sleep and without a real store.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

from tests.contract import _market_world as mw
from tests.contract.test_market_bars_contract import _tape_totals
from tests.contract.ws._harness import OFFERS, reset_wire, use_wire

#: The four storage calls a market request can make, by the name `Stores.calls` counts them under.
RECORDING, TOTALS, BAR_READ, HOT_READ = "recording_started", "trade_totals", "bar_read", "hot_read"
Fault = Callable[[], Awaitable[Any]]


@dataclass
class Stores:
    """The spied world: `calls` counts each storage call; `faults[name]` replaces its answer."""

    calls: Counter[str] = field(default_factory=Counter)
    faults: dict[str, Fault] = field(default_factory=dict)
    _world: mw.MarketWorld | None = None

    @property
    def world(self) -> mw.MarketWorld:
        """Built on first use, so a test may first patch a constant the routes bind at build."""
        if self._world is None:
            self._world = mw.MarketWorld()
        return self._world

    def get(
        self, op: str, query: Mapping[str, object], headers: Mapping[str, str] = mw.READER
    ) -> httpx.Response:
        return self.world.get(op, query, headers)

    def total(self) -> int:
        return sum(self.calls.values())

    def asgi(self) -> httpx.AsyncClient:
        """An in-process async client (no socket): a hung handler can be cut by the test."""
        transport = httpx.ASGITransport(app=self.world.app, raise_app_exceptions=False)
        return httpx.AsyncClient(transport=transport, base_url="http://cv.test")


async def hang() -> None:
    """A store call that never answers: it waits on an event nobody sets (cancellable)."""
    await asyncio.Event().wait()


@pytest.fixture
def stores(monkeypatch: pytest.MonkeyPatch) -> Stores:
    """The spied `MarketWorld`: its storage callables are wrapped before it is built (it binds
    them at build)."""
    holder: list[Stores] = []

    def spy(name: str, real: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        async def wrapped(*args: Any, **kwargs: Any) -> Any:
            s = holder[0]
            s.calls[name] += 1
            if name in s.faults:
                return await s.faults[name]()
            return await real(*args, **kwargs)

        return wrapped

    monkeypatch.setattr(mw, "_recording_started", spy(RECORDING, mw._recording_started))
    monkeypatch.setattr(mw, "_tape_totals", spy(TOTALS, _tape_totals))
    monkeypatch.setattr(mw._Rows, "fetch", _method(spy(BAR_READ, mw._Rows.fetch)))
    hot = mw._CountedHot.read_klines
    monkeypatch.setattr(mw._CountedHot, "read_klines", _method(spy(HOT_READ, hot)))
    holder.append(Stores())
    return holder[0]


def _method(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    """`fn` as an instance method (the bound `self` is passed through to the real one)."""

    async def method(self: object, *args: Any, **kwargs: Any) -> Any:
        return await fn(self, *args, **kwargs)

    return method


@pytest.fixture(params=list(OFFERS))
def wire(request: pytest.FixtureRequest) -> Iterator[str]:
    """The WS wire a socket-driven test speaks: each runs under both subprotocols (§2.2)."""
    name = str(request.param)
    token = use_wire(name)
    try:
        yield name
    finally:
        reset_wire(token)
