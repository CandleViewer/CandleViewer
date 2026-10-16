"""Per-topic coalescing queue (E17-T03, `23-ws-protocol.md` §8.1-§8.2).

One `CoalescingQueue` per (connection, topic) holds what the topic produced since its last
emission. A family merged by its §8.2 rule keeps a merge buffer (`book`: keyed by price level),
so a merge is O(changes) and memory is O(state), not O(updates). `trades` and
`liquidations` keep an append list (§8.2 "append, never merge"). Every other throttled family,
and a merged family whose subscriber set `coalesce: false`, queues whole frames; a merged family
folds them into its merge at the frame bound rather than overflow. `never_throttled` families
(`orders`, `executions`, S4) are never queued; a queue for them cannot be built.

Exactly one pending update leaves verbatim, with its binary `part` and its own replay `ts_ms`; two
or more leave as one merged structured payload with `coalesced_count` and the latest `ts_ms` (the
emitter adds the §8.2 disclosure). The producer's CVWB parts cannot be merged here, so a merged
frame is structured even for a binary subscriber.

`pending_bytes` estimates the JSON size of what `take()` would emit, so the connection budget
(§8.4) counts pending state as well as queued frames; every buffer is also bounded by count. A
queue that hits a bound, or gets an update it cannot merge (a non-finite price, a missing key),
refuses it and reports `overflowed`: its pending state no longer equals the applied stream, so the
caller must `clear()` it and re-snapshot the topic (§8.4) instead of emitting it.

A queue belongs to one connection and never mutates its input. It copies the top level of what it
keeps and every merged entity; nested values of a public family's verbatim update are shared, as
the hub fans one payload out to every connection and producers never mutate a published payload.
A private family's update is deep-copied on entry, so nothing of it is shared between
subscriptions (SR-190).
"""

from __future__ import annotations

import copy
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

from candleviewer.ws.binary import Frame
from candleviewer.ws.topics import FAMILIES

Payload = Mapping[str, Any]

#: §8.2: append, never merge; throttling batches them into arrays.
APPENDED_FAMILIES: Final = frozenset({"trades", "liquidations"})

#: Distinct keys (price levels) one merge buffer may hold.
MAX_PENDING_KEYS: Final = 4096
#: Items one append list may hold before the topic is re-snapshotted instead of truncated.
MAX_PENDING_ITEMS: Final = 20_000
#: Whole frames one frame queue may hold.
MAX_PENDING_FRAMES: Final = 256

#: Wire disclosure fields belong to the emitter (§8.2); a producer's copy is never kept.
_DISCLOSURE: Final = frozenset({"coalesced", "coalesced_count"})


class _BufferFullError(Exception):
    """A merge buffer hit its bound; the update was refused."""


#: What a merge raises for an update it cannot take: a bound, or a malformed producer payload.
_REFUSED: Final = (_BufferFullError, ArithmeticError, LookupError, TypeError, ValueError)


@dataclass(frozen=True, slots=True)
class Emission:
    """One frame's payload. `part` is the producer's CVWB form, kept only for an unmerged update.
    `coalesced_count` is the number of source updates merged into `body` (always 1 for the append
    families, which never merge). `ts_ms` is the source event time a replay frame carries."""

    body: dict[str, Any]
    part: Frame | None = None
    coalesced_count: int = 1
    ts_ms: int | None = None


def _size(value: Any) -> int:
    """Approximate compact-JSON length of `value`."""
    if isinstance(value, str):
        return len(value) + 2
    if isinstance(value, Mapping):
        return 1 + sum(len(str(k)) + 4 + _size(v) for k, v in value.items())
    if isinstance(value, list | tuple):
        return 1 + sum(_size(v) + 1 for v in value)
    return len(str(value))


def _dec(value: Any) -> Decimal:
    key = Decimal(str(value))
    if not key.is_finite():
        raise ValueError(f"non-finite decimal {value!r}")
    return key


class _Merge(ABC):
    """Root fields are last-write-wins; subclasses merge their list fields, keep `bytes` (the
    estimated size of the merged lists) current and raise one of `_REFUSED` instead of taking an
    update. `result` is called once per window, before `reset`."""

    def __init__(self, limit: int, lists: tuple[str, ...]) -> None:
        self.limit = limit
        self.lists = frozenset(lists) | _DISCLOSURE
        self.root: dict[str, Any] = {}
        self.bytes = 0

    def add(self, body: Payload) -> None:
        self.root.update((k, v) for k, v in body.items() if k not in self.lists)
        self.merge(body)

    @abstractmethod
    def merge(self, body: Payload) -> None:
        """Merge the list fields of one update."""

    @abstractmethod
    def result(self) -> dict[str, Any]:
        """The window's merged payload."""

    def reset(self) -> None:
        """Forget the pending state after an emission."""
        self.root, self.bytes = {}, 0


class _BookMerge(_Merge):
    """§8.2 `book`: per (side, price) level, last write wins; a `"0"` size deletes the level, so a
    later delete wins over an earlier update and a later update re-creates the level."""

    def __init__(self, limit: int) -> None:
        super().__init__(limit, ("bids", "asks"))
        self.sides: dict[str, dict[Decimal, list[str]]] = {"bids": {}, "asks": {}}

    def merge(self, body: Payload) -> None:
        for side, levels in self.sides.items():
            for price, size in body.get(side) or ():
                key = _dec(price)
                old = levels.get(key)
                if old is not None:
                    self.bytes -= _size(old)
                elif len(self.sides["bids"]) + len(self.sides["asks"]) >= self.limit:
                    raise _BufferFullError
                levels[key] = [price, size]
                self.bytes += _size(levels[key])

    def result(self) -> dict[str, Any]:
        bids = [level for _, level in sorted(self.sides["bids"].items(), reverse=True)]
        asks = [level for _, level in sorted(self.sides["asks"].items())]
        return {**self.root, "bids": bids, "asks": asks}

    def reset(self) -> None:
        super().reset()
        self.sides = {"bids": {}, "asks": {}}


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
        for item in items:
            self.items.append(dict(item))
            self.bytes += _size(item) + 1
        for name in self.summed:
            if name in body:
                self.sums[name] = self.sums.get(name, 0) + int(body[name])

    def result(self) -> dict[str, Any]:
        return {**self.root, self.field: self.items, **self.sums}

    def reset(self) -> None:
        super().reset()
        self.items, self.sums = [], {}


#: The §8.2 merge rule of each merged or appended family: `(keys bound, items bound) -> merge`.
_RULES: Final[Mapping[str, Callable[[int, int], _Merge]]] = {
    "book": lambda keys, _: _BookMerge(keys),
    "trades": lambda _, items: _AppendMerge(items, "trades", ("dropped",)),
    "liquidations": lambda _, items: _AppendMerge(items, "liquidations"),
}
#: §8.1 "Coalescing" row: families merged by their §8.2 rule.
MERGED_FAMILIES: Final = frozenset(_RULES) - APPENDED_FAMILIES


class CoalescingQueue:
    """Pending updates of one (connection, topic) between two emissions."""

    def __init__(
        self,
        family: str,
        *,
        coalesce: bool = True,
        max_keys: int = MAX_PENDING_KEYS,
        max_items: int = MAX_PENDING_ITEMS,
        max_frames: int = MAX_PENDING_FRAMES,
    ) -> None:
        topic = FAMILIES.get(family)
        if topic is None:
            raise ValueError(f"unknown topic family {family!r}")
        if topic.never_throttled:
            raise ValueError(f"{family} is never coalesced or throttled (S4)")
        self.family = family
        self._private = topic.private
        self._coalesce = coalesce
        self._bounds = (max_keys, max_items)
        self._max_frames = max_frames
        rule = _RULES.get(family)
        self._rule = rule
        self._merge = rule(max_keys, max_items) if rule is not None else None
        self._first: Emission | None = None
        self._count = 0
        self._ts_ms: int | None = None
        self._frames: list[Emission] = []
        self._frame_bytes = 0
        self._overflowed = False

    @property
    def merging(self) -> bool:
        """True while updates are merged (or appended) rather than queued as whole frames."""
        return self._merge is not None and (self._coalesce or self.family in APPENDED_FAMILIES)

    @property
    def overflowed(self) -> bool:
        """An update was refused: `take()` yields nothing until `clear()` (§8.4)."""
        return self._overflowed

    @property
    def pending(self) -> bool:
        """True when `take()` would emit something."""
        return not self._overflowed and bool(self._count or self._frames)

    @property
    def pending_bytes(self) -> int:
        """Estimated JSON size of the pending state, for the connection budget (§8.4)."""
        merge = self._merge
        merged = merge.bytes + _size(merge.root) if merge is not None and self._count else 0
        return self._frame_bytes + merged

    def set_coalesce(self, coalesce: bool) -> None:
        """Turning coalescing on folds any whole frames queued meanwhile into one merge at once;
        turning it off takes effect once the pending merge has been taken, so it leaves whole."""
        if coalesce == self._coalesce:
            return
        self._coalesce = coalesce
        if coalesce and self._merge is not None and self._frames and not self._count:
            self._fold(self._merge)

    def offer(self, body: Payload, part: Frame | None = None, *, ts_ms: int | None = None) -> bool:
        """Queue one source update; False when refused, i.e. the queue is (or was) overflowed."""
        if self._overflowed:
            return False
        if self._private:
            body = copy.deepcopy(body)  # SR-190: nothing of a private update is shared
        merge = self._merge
        if merge is None or not (self.merging or self._count):
            if len(self._frames) < self._max_frames:
                emission = Emission(_own(body), part, 1, ts_ms)
                self._frames.append(emission)
                self._frame_bytes += _size(emission.body)
                return True
            if merge is None:
                self._overflowed = True
                return False
            self._fold(merge)  # a mergeable family merges rather than overflow
            if self._overflowed:
                return False
        return self._merge_one(merge, body, part, ts_ms)

    def _fold(self, merge: _Merge) -> None:
        frames, self._frames, self._frame_bytes = self._frames, [], 0
        for frame in frames:
            if not self._merge_one(merge, frame.body, frame.part, frame.ts_ms):
                return

    def _merge_one(
        self, merge: _Merge, body: Payload, part: Frame | None, ts_ms: int | None
    ) -> bool:
        try:
            merge.add(body)
        except _REFUSED:
            self._overflowed = True
            return False
        self._count += 1
        if ts_ms is not None:
            self._ts_ms = ts_ms
        if self._count == 1:
            self._first = Emission(_own(body), part, 1, ts_ms)
        return True

    def take(self) -> list[Emission]:
        """The frames to emit now (none after an overflow), resetting the pending state."""
        if self._overflowed:
            return []
        merge = self._merge
        if merge is not None:
            self._close_window(merge)
        out, self._frames, self._frame_bytes = self._frames, [], 0
        return out

    def _close_window(self, merge: _Merge) -> None:
        """Move the pending merge to the frame list as one emission (verbatim if unmerged)."""
        if self._count == 1 and self._first is not None:
            emission = self._first
        elif self._count:
            count = 1 if self.family in APPENDED_FAMILIES else self._count
            emission = Emission(merge.result(), None, count, self._ts_ms)
        else:
            return
        self._frames.append(emission)
        self._frame_bytes += merge.bytes + _size(merge.root)
        merge.reset()
        self._count, self._first, self._ts_ms = 0, None, None

    def clear(self) -> None:
        """Drop all pending state (§8.4 step 1) and accept updates again."""
        self._frames, self._frame_bytes = [], 0
        self._count, self._first, self._ts_ms = 0, None, None
        if self._rule is not None:
            self._merge = self._rule(*self._bounds)
        self._overflowed = False


def _own(body: Payload) -> dict[str, Any]:
    """A fresh top-level dict without the emitter-owned disclosure fields."""
    return {k: v for k, v in body.items() if k not in _DISCLOSURE}
