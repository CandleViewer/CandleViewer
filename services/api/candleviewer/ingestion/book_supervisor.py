"""B14 `book` health supervision, off the per-delta path (E08-S05).

The book engine (`candleviewer.book`) enforces its lifecycle as plain code
(C-2.20, C-2.21) and emits lifecycle edges to a `HealthSink`. This module is
the only place a B14 chart is built for a live book: one interpreter per
`(env, symbol, depth)`, built through `statechart.factory.build("book")` and
injected into `BookStream` by `create_app`. Edges are forwarded
fire-and-forget (no receipt wait, CV-C51); the chart records, it never drives
the book. Nothing here runs per delta.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from candleviewer.observability.context import spawn
from candleviewer.statechart import build
from candleviewer.statechart.bindings import b14_book  # noqa: F401  (registers "book")
from candleviewer.statechart.factory import default_clock
from candleviewer.statechart.plugins import FeedBinding, MachineStatePort, feed_plugins


class B14BookSupervisor:
    """Owns the B14 interpreters for every live book."""

    def __init__(self, *, feed: MachineStatePort | None = None) -> None:
        self._interps: dict[str, Any] = {}
        self._feed = feed  # 23 §6.4: `machines.book:{symbol}.state`, an unscoped kind

    async def attach(self, key: str, symbol: str) -> Callable[[str], Awaitable[None]]:
        result = await build(
            "book",
            ctx={"book_key": key, "symbol": symbol},
            clock=default_clock(),
            lane="platform",
            plugins=feed_plugins(self._feed, FeedBinding("book", symbol)),
        )
        interp = result.interpreter
        self._interps[key] = interp

        async def sink(event: str) -> None:
            await interp.send(event)  # enqueue only; never awaits a receipt

        return sink

    def detach(self, key: str) -> None:
        interp = self._interps.pop(key, None)
        if interp is not None:
            spawn(interp.stop(), name="book-chart-stop")

    def interpreter(self, key: str) -> Any:
        return self._interps.get(key)


__all__ = ["B14BookSupervisor"]
