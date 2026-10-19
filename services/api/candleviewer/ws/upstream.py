"""Upstream reference counting across every WS connection (E17-S02; US-MKT-005).

One upstream subscription per `(symbol, family, params)` no matter how many connections or panes
want it. When the last consumer leaves, the key enters a 30 s grace period and is dropped only
if nobody re-acquires it before the deadline, so a pane close + reopen never churns the exchange
connection. Time is injected (`now` in seconds on a monotonic clock); `sweep(now)` performs the
deferred drops, so tests drive time instead of sleeping. `run()` is the supervised sweeper.

Bounded (C-2.18): one entry per distinct upstream key; keys are only created for topics that
passed the registry parser and the per-connection caps (200 subs x 8 connections per user). An
entry whose open is pending holds one future, never a task (`acquire`, #2227).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Final, Protocol

import structlog

from candleviewer.observability.metrics import Gauge
from candleviewer.ws.errors import WsError

GRACE_S: Final = 30.0
SWEEP_INTERVAL_S: Final = 1.0

#: Cardinality bound on the `symbol` label (catalogue max_series=200): the first
#: MAX_SYMBOL_LABELS distinct tracked symbols get their own label value; any further
#: symbol is recorded as "other" until a labelled symbol is fully dropped.
MAX_SYMBOL_LABELS: Final = 20
OTHER_SYMBOL: Final = "other"

UpstreamKey = tuple[str, str, tuple[str, ...]]  # (symbol, family, params)

#: Module-level, so it assumes one `UpstreamRefs` per process: the gateway's (`app.py`). A second
#: instance would write the same series, each overwriting the other's count.
cv_ws_upstream_consumers_in_use = Gauge(
    "cv_ws_upstream_consumers_in_use",
    "Consumers of upstream subscriptions per symbol and topic family (the topic label "
    "holds the topic family); symbols beyond MAX_SYMBOL_LABELS share symbol=other; "
    "the series is removed when it reaches 0.",
    labelnames=("symbol", "topic"),
)


class UpstreamSink(Protocol):
    """The E08 upstream manager the refcount drives (open on first consumer, drop after grace)."""

    async def open(self, key: UpstreamKey) -> None:
        """An open that suspends makes every acquire of the key wait on it, and its caller's
        cancellation (any close of that socket) fails them all (`UpstreamRefs.acquire`); wiring
        such a sink needs an open timeout and a decision between this and a refs-owned open
        (#2227)."""
        ...

    async def drop(self, key: UpstreamKey) -> None: ...


class UpstreamOpenFailed(WsError):
    """The open a joined `acquire` waited for did not complete (#2227): the sink raised, or the
    acquire running it was cancelled. `__cause__` is what ended it."""


@dataclass
class _Entry:
    consumers: set[str] = field(default_factory=set)
    expires_at: float | None = None
    label: str = OTHER_SYMBOL
    #: Set while the first acquire's `sink.open` runs; resolved with None once it returns, or
    #: with what it raised. Every acquire that finds it set waits on it (#2227).
    opening: asyncio.Future[BaseException | None] | None = None


class UpstreamRefs:
    def __init__(self, sink: UpstreamSink | None = None, *, grace_s: float = GRACE_S) -> None:
        self._sink = sink
        self._grace_s = grace_s
        self._entries: dict[UpstreamKey, _Entry] = {}
        self._labelled: set[str] = set()

    def __len__(self) -> int:
        return len(self._entries)

    def consumers(self, key: UpstreamKey) -> int:
        entry = self._entries.get(key)
        return 0 if entry is None else len(entry.consumers)

    def active(self) -> set[UpstreamKey]:
        return set(self._entries)

    async def acquire(self, key: UpstreamKey, consumer: str) -> None:
        """Add `consumer`; return once the key's upstream is open. Only a brand-new key is opened
        (a key in grace is re-adopted without touching the exchange).

        One open per key (#2227): an acquire that finds the key's open pending joins it and
        waits, so no caller returns holding an upstream that never opened. If the open raises,
        the key is removed and no acquirer stays a consumer: the opening acquire re-raises the
        error, and each joined one raises `UpstreamOpenFailed` from it. A joined acquire that is
        cancelled leaves at once, as on `release`, and the open goes on for the others.

        The open runs in the opening acquire's own task, so cancelling that acquire cancels the
        open, and each joined one fails as above. That is the simpler correct choice: an open
        that outlived its caller would be a task this object must own, bound and cancel at
        shutdown (AGENTS.md §5.2, C-2.18). Its cost is that a cancelled opener fails the
        acquires that joined it, and those exist only while a sink's `open` is suspended."""
        entry = self._entries.get(key)
        fresh = entry is None
        if entry is None:
            entry = self._entries[key] = _Entry(label=self._label_for(key[0]))
        entry.consumers.add(consumer)
        entry.expires_at = None
        self._gauge(key)
        if fresh and self._sink is not None:
            await self._open(self._sink, key, entry)
        elif (opening := entry.opening) is not None:
            await self._join(key, entry, consumer, opening)

    async def _open(self, sink: UpstreamSink, key: UpstreamKey, entry: _Entry) -> None:
        opening = entry.opening = asyncio.get_running_loop().create_future()
        failure: BaseException | None = None
        try:
            await sink.open(key)
        except BaseException as exc:  # a cancel too: it propagates once the key is gone
            failure = exc
            self._entries.pop(key, None)
            self._gauge_label(entry.label, key[1])
            self._forget_label(entry.label)
            raise
        finally:
            entry.opening = None
            opening.set_result(failure)  # every joined acquire learns the outcome

    async def _join(
        self,
        key: UpstreamKey,
        entry: _Entry,
        consumer: str,
        opening: asyncio.Future[BaseException | None],
    ) -> None:
        try:
            failure = await asyncio.shield(opening)  # this acquire's cancel stays its own
        except BaseException:  # its cancellation: it leaves now; a key left empty: `sweep`
            entry.consumers.discard(consumer)
            self._gauge(key)
            raise
        if failure is not None:
            raise UpstreamOpenFailed(key) from failure

    def release(self, key: UpstreamKey, consumer: str, now: float) -> None:
        """Idempotent; the last release starts the grace period, while the key's open is pending
        too (`sweep` then waits for that open to complete)."""
        entry = self._entries.get(key)
        if entry is None or consumer not in entry.consumers:
            return
        entry.consumers.discard(consumer)
        if not entry.consumers:
            entry.expires_at = now + self._grace_s
        self._gauge(key)

    async def sweep(self, now: float) -> list[UpstreamKey]:
        """Drop every key whose grace expired; returns the dropped keys. A key whose open is
        pending is never swept. One that a cancelled joined acquire left with no consumer has no
        deadline (that acquire had no `now`), so its grace starts at the first sweep it meets."""
        due: list[UpstreamKey] = []
        for k, e in self._entries.items():
            if e.consumers or e.opening is not None:
                continue
            if e.expires_at is None:
                e.expires_at = now + self._grace_s
            elif e.expires_at <= now:
                due.append(k)
        for key in due:
            entry = self._entries.pop(key)
            self._gauge_label(entry.label, key[1])
            self._forget_label(entry.label)
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

    def _label_for(self, symbol: str) -> str:
        if symbol in self._labelled:
            return symbol
        if len(self._labelled) < MAX_SYMBOL_LABELS:
            self._labelled.add(symbol)
            return symbol
        return OTHER_SYMBOL

    def _forget_label(self, label: str) -> None:
        if label != OTHER_SYMBOL and not any(e.label == label for e in self._entries.values()):
            self._labelled.discard(label)

    def _gauge(self, key: UpstreamKey) -> None:
        entry = self._entries.get(key)
        if entry is not None:
            self._gauge_label(entry.label, key[1])

    def _gauge_label(self, label: str, family: str) -> None:
        """Set the series to the summed consumers; remove it once that reaches 0."""
        total = sum(
            len(e.consumers)
            for k, e in self._entries.items()
            if e.label == label and k[1] == family
        )
        if total:
            cv_ws_upstream_consumers_in_use.labels(symbol=label, topic=family).set(total)
        else:
            try:
                cv_ws_upstream_consumers_in_use.remove(label, family)
            except KeyError:
                pass
