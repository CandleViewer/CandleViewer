"""Upstream reference counting across every WS connection (E17-S02; US-MKT-005).

One upstream subscription per `(symbol, family, params)` no matter how many connections or panes
want it. When the last consumer leaves, the key enters a 30 s grace period and is dropped only
if nobody re-acquires it before the deadline, so a pane close + reopen never churns the exchange
connection. Time is injected (`now` in seconds on a monotonic clock); `sweep(now)` performs the
deferred drops, so tests drive time instead of sleeping. `run()` is the supervised sweeper.

Bounded (C-2.18): one entry per distinct upstream key; keys are only created for topics that
passed the registry parser and the per-connection caps (200 subs x 8 connections per user).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Final, Protocol

import structlog

from candleviewer.observability.metrics import Gauge

GRACE_S: Final = 30.0
SWEEP_INTERVAL_S: Final = 1.0

UpstreamKey = tuple[str, str, tuple[str, ...]]  # (symbol, family, params)

cv_ws_upstream_refcount = Gauge(
    "cv_ws_upstream_refcount",
    "Consumers of one upstream subscription (0 while in its release grace).",
    labelnames=("symbol", "topic"),
)


class UpstreamSink(Protocol):
    """The E08 upstream manager the refcount drives (open on first consumer, drop after grace)."""

    async def open(self, key: UpstreamKey) -> None: ...

    async def drop(self, key: UpstreamKey) -> None: ...


@dataclass
class _Entry:
    consumers: set[str] = field(default_factory=set)
    expires_at: float | None = None


class UpstreamRefs:
    def __init__(self, sink: UpstreamSink | None = None, *, grace_s: float = GRACE_S) -> None:
        self._sink = sink
        self._grace_s = grace_s
        self._entries: dict[UpstreamKey, _Entry] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def consumers(self, key: UpstreamKey) -> int:
        entry = self._entries.get(key)
        return 0 if entry is None else len(entry.consumers)

    def active(self) -> set[UpstreamKey]:
        return set(self._entries)

    async def acquire(self, key: UpstreamKey, consumer: str) -> None:
        """Add `consumer`; opens the upstream only for a brand-new key (a key in grace is
        re-adopted without touching the exchange)."""
        entry = self._entries.get(key)
        fresh = entry is None
        if entry is None:
            entry = self._entries[key] = _Entry()
        entry.consumers.add(consumer)
        entry.expires_at = None
        self._gauge(key)
        if fresh and self._sink is not None:
            try:
                await self._sink.open(key)
            except BaseException:
                self._entries.pop(key, None)
                raise

    def release(self, key: UpstreamKey, consumer: str, now: float) -> None:
        """Idempotent; the last release starts the grace period."""
        entry = self._entries.get(key)
        if entry is None or consumer not in entry.consumers:
            return
        entry.consumers.discard(consumer)
        if not entry.consumers:
            entry.expires_at = now + self._grace_s
        self._gauge(key)

    async def sweep(self, now: float) -> list[UpstreamKey]:
        """Drop every key whose grace expired; returns the dropped keys."""
        due = [
            k
            for k, e in self._entries.items()
            if not e.consumers and e.expires_at is not None and e.expires_at <= now
        ]
        for key in due:
            del self._entries[key]
            cv_ws_upstream_refcount.remove(key[0], key[1])
            if self._sink is not None:
                try:
                    await self._sink.drop(key)
                except Exception:
                    structlog.get_logger(__name__).warning(
                        "ws upstream drop failed", symbol=key[0], family=key[1], exc_info=True
                    )
        return due

    async def run(
        self,
        clock: Callable[[], float],
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Supervised sweeper loop (spawned by the owning service)."""
        while True:
            await sleep(SWEEP_INTERVAL_S)
            await self.sweep(clock())

    def _gauge(self, key: UpstreamKey) -> None:
        entry = self._entries.get(key)
        cv_ws_upstream_refcount.labels(symbol=key[0], topic=key[1]).set(
            0 if entry is None else len(entry.consumers)
        )
