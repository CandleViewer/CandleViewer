"""Per-topic coalescing queue (E17-T03, `23-ws-protocol.md` §8.1-§8.2).

One `CoalescingQueue` per (connection, topic) holds what the topic produced since its last
emission. A family merged by its §8.2 rule keeps a merge buffer keyed by level or bar, so a merge
is O(changes) and memory is O(state), not O(updates). `trades` and `liquidations` keep a bounded
append list (§8.2 "append, never merge"). Every other throttled family, and a merged family whose
subscriber set `coalesce: false`, queues whole frames, which loses nothing. `orders` and
`executions` are never queued (S4); a queue for them cannot be built.

Exactly one pending update is emitted verbatim, binary `part` included; two or more leave as one
merged structured payload with `coalesced_count` (the emitter adds the §8.2 disclosure). The
producer's CVWB parts cannot be merged here, so a merged frame is structured even for a binary
subscriber.

A queue copies what it keeps, never mutates its input and belongs to one connection; a private
family's update is deep-copied on entry, so nothing of it is shared between subscriptions
(SR-190). A full queue refuses further updates and reports `overflowed`: its pending state no
longer equals the applied stream, so the caller must `clear()` it and re-snapshot the topic (§8.4)
instead of emitting it.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

from candleviewer.ws.bar_coalescer import BarCoalescer
from candleviewer.ws.binary import Frame
from candleviewer.ws.topics import FAMILIES

Payload = Mapping[str, Any]

#: Families merged by their §8.2 rule; any other throttled family queues whole frames.
MERGED_FAMILIES: Final = frozenset({"book", "bars"})
#: §8.2: append, never merge; throttling batches them into arrays.
APPENDED_FAMILIES: Final = frozenset({"trades", "liquidations"})
#: §8.2 / S4: never coalesced, never throttled.
NEVER_QUEUED: Final = frozenset({"orders", "executions"})

#: Distinct keys (levels, bars) one merge buffer may hold.
MAX_PENDING_KEYS: Final = 4096
#: Items one append list may hold before the topic is re-snapshotted instead of truncated.
MAX_PENDING_ITEMS: Final = 20_000
#: Whole frames one frame queue may hold.
MAX_PENDING_FRAMES: Final = 256

#: Wire disclosure fields belong to the emitter (§8.2); a producer's copy is never kept.
_DISCLOSURE: Final = frozenset({"coalesced", "coalesced_count"})


@dataclass(frozen=True, slots=True)
class Emission:
    """One frame's payload. `part` is the producer's CVWB form, kept only for an unmerged update;
    `coalesced_count` is the number of source updates merged into `body`."""

    body: dict[str, Any]
    part: Frame | None = None
    coalesced_count: int = 1


class _BufferFullError(Exception):
    """A merge buffer hit its bound; the update was refused."""


class _Merge:
    """Root fields are last-write-wins; subclasses merge their list fields and raise
    `_BufferFullError` at the bound. `result` is called once per window, before `reset`."""

    def __init__(self, limit: int, lists: tuple[str, ...]) -> None:
        self.limit = limit
        self.lists = frozenset(lists) | _DISCLOSURE
        self.root: dict[str, Any] = {}

    def add(self, body: Payload) -> None:
        self.root.update((k, v) for k, v in body.items() if k not in self.lists)
        self.merge(body)

    def merge(self, body: Payload) -> None:
        raise NotImplementedError

    def result(self) -> dict[str, Any]:
        raise NotImplementedError

    def reset(self) -> None:
        """Forget the pending state after an emission."""
        self.root = {}


class _BookMerge(_Merge):
    """§8.2 `book`: per (side, price) level, last write wins; a `"0"` size deletes the level, so a
    later delete wins over an earlier update and a later update re-creates the level."""

    def __init__(self, limit: int) -> None:
        super().__init__(limit, ("bids", "asks"))
        self.sides: dict[str, dict[Decimal, list[str]]] = {"bids": {}, "asks": {}}

    def merge(self, body: Payload) -> None:
        for side, levels in self.sides.items():
            for price, size in body.get(side) or ():
                key = Decimal(str(price))
                if key not in levels and self._levels() >= self.limit:
                    raise _BufferFullError
                levels[key] = [price, size]

    def _levels(self) -> int:
        return len(self.sides["bids"]) + len(self.sides["asks"])

    def result(self) -> dict[str, Any]:
        bids = [level for _, level in sorted(self.sides["bids"].items(), reverse=True)]
        asks = [level for _, level in sorted(self.sides["asks"].items())]
        return {**self.root, "bids": bids, "asks": asks}

    def reset(self) -> None:
        super().reset()
        self.sides = {"bids": {}, "asks": {}}


class _BarsMerge(_Merge):
    """§8.2 `bars`: per `(generation, index)`, with the confirmed / amended precedence of the
    existing `BarCoalescer` (#2018)."""

    def __init__(self, limit: int) -> None:
        super().__init__(limit, ("bars",))
        self.bars = BarCoalescer(max_pending=limit)

    def merge(self, body: Payload) -> None:
        for item in body.get("bars") or ():
            self.bars.add(item)
            if self.bars.take_overflow():
                raise _BufferFullError

    def result(self) -> dict[str, Any]:
        items, _ = self.bars.flush()
        return {**self.root, "bars": items}

    def reset(self) -> None:
        super().reset()
        self.bars = BarCoalescer(max_pending=self.limit)


class _AppendMerge(_Merge):
    """§8.2 `trades` / `liquidations`: items appended in arrival order, never merged; `summed`
    counters (the trades `dropped` count since the previous frame) add up."""

    def __init__(self, limit: int, field: str, summed: tuple[str, ...] = ()) -> None:
        super().__init__(limit, (field, *summed))
        self.field = field
        self.summed = summed
        self.items: list[dict[str, Any]] = []
        self.sums: dict[str, int] = {}

    def merge(self, body: Payload) -> None:
        items = body.get(self.field) or ()
        if len(self.items) + len(items) > self.limit:
            raise _BufferFullError
        self.items.extend(dict(item) for item in items)
        for name in self.summed:
            if name in body:
                self.sums[name] = self.sums.get(name, 0) + int(body[name])

    def result(self) -> dict[str, Any]:
        return {**self.root, self.field: self.items, **self.sums}

    def reset(self) -> None:
        super().reset()
        self.items = []
        self.sums = {}


def _new_merge(family: str, limit: int | None) -> _Merge:
    keys = MAX_PENDING_KEYS if limit is None else limit
    if family == "book":
        return _BookMerge(keys)
    if family == "bars":
        return _BarsMerge(keys)
    items = MAX_PENDING_ITEMS if limit is None else limit
    if family == "trades":
        return _AppendMerge(items, "trades", ("dropped",))
    return _AppendMerge(items, "liquidations")


class CoalescingQueue:
    """Pending updates of one (connection, topic) between two emissions."""

    def __init__(self, family: str, *, coalesce: bool = True, limit: int | None = None) -> None:
        if family in NEVER_QUEUED:
            raise ValueError(f"{family} is never coalesced or throttled (S4)")
        self.family = family
        self.limit = limit
        self.overflowed = False
        self._private = FAMILIES[family].private
        self._coalesce = coalesce
        self._merge = (
            _new_merge(family, limit)
            if family in MERGED_FAMILIES or family in APPENDED_FAMILIES
            else None
        )
        self._first: Emission | None = None
        self._count = 0
        self._frames: list[Emission] = []

    @property
    def merging(self) -> bool:
        """True while updates are merged (or appended) rather than queued as whole frames."""
        return self._merge is not None and (self._coalesce or self.family in APPENDED_FAMILIES)

    @property
    def pending(self) -> bool:
        return bool(self._count or self._frames)

    def set_coalesce(self, coalesce: bool) -> None:
        """Turning coalescing on folds any whole frames queued meanwhile into one merge at once;
        turning it off takes effect once the pending merge has been taken, so it leaves whole."""
        if coalesce == self._coalesce:
            return
        self._coalesce = coalesce
        if coalesce and self._merge is not None and self._frames and not self._count:
            frames, self._frames = self._frames, []
            for frame in frames:
                self.offer(frame.body, frame.part)

    def offer(self, body: Payload, part: Frame | None = None) -> bool:
        """Queue one source update; False when refused because the queue is (or was) full."""
        if self.overflowed:
            return False
        if self._private:
            body = copy.deepcopy(body)  # SR-190: nothing of a private update is shared
        merge = self._merge
        if merge is None or not (self.merging or self._count):
            if len(self._frames) >= (MAX_PENDING_FRAMES if self.limit is None else self.limit):
                self.overflowed = True
                return False
            self._frames.append(Emission(_own(body), part))
            return True
        try:
            merge.add(body)
        except _BufferFullError:
            self.overflowed = True
            return False
        self._count += 1
        if self._count == 1:
            self._first = Emission(_own(body), part)
        return True

    def take(self) -> list[Emission]:
        """The frames to emit now (none after an overflow), resetting the pending state."""
        if self.overflowed:
            return []
        out, self._frames = self._frames, []
        merge = self._merge
        if merge is None or not self._count:
            return out
        if self._count == 1 and self._first is not None:
            out.append(self._first)
        else:
            count = 1 if self.family in APPENDED_FAMILIES else self._count
            out.append(Emission(merge.result(), None, count))
        merge.reset()
        self._count, self._first = 0, None
        return out

    def clear(self) -> None:
        """Drop all pending state (§8.4 step 1) and accept updates again."""
        self._frames = []
        self._count, self._first = 0, None
        if self._merge is not None:
            self._merge = _new_merge(self.family, self.limit)
        self.overflowed = False


def _own(body: Payload) -> dict[str, Any]:
    """A fresh top-level dict without the emitter-owned disclosure fields."""
    return {k: v for k, v in body.items() if k not in _DISCLOSURE}
