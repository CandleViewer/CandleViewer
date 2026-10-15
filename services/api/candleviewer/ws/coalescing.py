"""Per-topic coalescing queue (E17-T03, `23-ws-protocol.md` §8.1-§8.2).

One `CoalescingQueue` per (connection, topic) holds what the topic produced since its last
emission. A family merged by its §8.2 rule keeps a merge buffer keyed by level, bar, cell, column
or entity, so a merge is O(changes) and memory is O(state), not O(updates). `trades` and
`liquidations` keep an append list (§8.2 "append, never merge"). Every other throttled family,
and a merged family whose subscriber set `coalesce: false`, queues whole frames; a merged family
folds them into its merge at the frame bound rather than overflow. `never_throttled` families
(`orders`, `executions`, S4) are never queued; a queue for them cannot be built.

Exactly one pending update leaves verbatim, with its binary `part` and its own replay `ts_ms`; two
or more leave as one merged structured payload with `coalesced_count` and the latest `ts_ms` (the
emitter adds the §8.2 disclosure). The producer's CVWB parts cannot be merged here, so a merged
frame is structured even for a binary subscriber. An update that carries nothing new is discarded
as the client would discard it: an entity older than the pending one (§15 `updated_at_ms`), or a
column for a heatmap bucket already sent complete.

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
import json
from abc import ABC, abstractmethod
from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

from candleviewer.ws.bar_coalescer import BarCoalescer, BarKey, bar_key
from candleviewer.ws.binary import Frame
from candleviewer.ws.topics import FAMILIES

Payload = Mapping[str, Any]

#: §8.2: append, never merge; throttling batches them into arrays.
APPENDED_FAMILIES: Final = frozenset({"trades", "liquidations"})

#: Distinct keys (levels, bars, cells, columns, entities) one merge buffer may hold.
MAX_PENDING_KEYS: Final = 4096
#: Items one append list may hold before the topic is re-snapshotted instead of truncated.
MAX_PENDING_ITEMS: Final = 20_000
#: Whole frames one frame queue may hold.
MAX_PENDING_FRAMES: Final = 256
#: Complete heatmap columns remembered as already sent (one snapshot's worth, §6.1.1).
SENT_COLUMNS_MEMORY: Final = 2000

#: Wire disclosure fields belong to the emitter (§8.2); a producer's copy is never kept.
_DISCLOSURE: Final = frozenset({"coalesced", "coalesced_count"})
#: Footprint cell fields that are increments within one bar (§8.2 "values summed").
_SUMMED_DECIMALS: Final = ("bid_volume", "ask_volume", "delta", "total_volume")
_SUMMED_COUNTS: Final = ("trades",)


class _BufferFullError(Exception):
    """A merge buffer hit its bound; the update was refused."""


#: What an update the queue cannot take raises: a bound, or a malformed producer payload (a
#: pathologically nested one included).
_REFUSED: Final = (
    _BufferFullError,
    ArithmeticError,
    LookupError,
    RecursionError,
    TypeError,
    ValueError,
)


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


#: Largest decimal exponent a summed footprint value may carry before it is refused.
_MAX_EXPONENT: Final = 40


def _plain(value: Decimal) -> str:
    """Wire decimal form (`^-?[0-9]+(\\.[0-9]+)?$`): never an exponent, never absurdly long."""
    if abs(value.adjusted()) > _MAX_EXPONENT:
        raise ValueError(f"decimal out of range: {value!r}")
    return format(value, "f")


class _Merge(ABC):
    """Root fields are last-write-wins; subclasses merge their list fields, keep `bytes` (the
    estimated size of the merged lists) current, return False when an update changed nothing (the
    client would discard it) and raise one of `_REFUSED` instead of taking an update. `result` is
    called once per window, before `reset`."""

    def __init__(self, limit: int, lists: tuple[str, ...]) -> None:
        self.limit = limit
        self.lists = frozenset(lists) | _DISCLOSURE
        self.root: dict[str, Any] = {}
        self.root_bytes = 0
        self.bytes = 0
        #: Part of an update was dropped (a heatmap bucket already sent): no verbatim emission.
        self.trimmed = False

    def add(self, body: Payload) -> bool:
        """Merge one update; a discarded update's root fields are discarded with it."""
        changed = self.merge(body)
        if changed:
            self.root.update((k, v) for k, v in body.items() if k not in self.lists)
            self.root_bytes = _size(self.root)
        return changed

    @abstractmethod
    def merge(self, body: Payload) -> bool:
        """Merge the list fields of one update."""

    @abstractmethod
    def result(self) -> dict[str, Any]:
        """The window's merged payload."""

    def splits(self, body: Payload) -> bool:
        """True when `body` cannot join the pending merge and must start a new frame."""
        return False

    def emitted(self, body: Payload) -> None:
        """Called with each emitted payload; only a family that remembers what it sent uses it."""
        return None

    def reset(self) -> None:
        """Forget the pending state after an emission."""
        self.root, self.root_bytes, self.bytes, self.trimmed = {}, 0, 0, False


class _BookMerge(_Merge):
    """§8.2 `book`: per (side, price) level, last write wins; a `"0"` size deletes the level, so a
    later delete wins over an earlier update and a later update re-creates the level."""

    def __init__(self, limit: int) -> None:
        super().__init__(limit, ("bids", "asks"))
        self.sides: dict[str, dict[Decimal, list[str]]] = {"bids": {}, "asks": {}}

    def merge(self, body: Payload) -> bool:
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
        return True

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
        self.sizes: dict[BarKey, int] = {}

    def merge(self, body: Payload) -> bool:
        changed = False
        for item in body.get("bars") or ():
            if self.bars.add(item):
                key, size = bar_key(item), _size(item)
                self.bytes += size - self.sizes.get(key, 0)
                self.sizes[key] = size
                changed = True
            elif self.bars.take_overflow():
                raise _BufferFullError
        return changed

    def result(self) -> dict[str, Any]:
        items, _ = self.bars.flush()
        return {**self.root, "bars": items}

    def reset(self) -> None:
        super().reset()
        self.bars = BarCoalescer(max_pending=self.limit)
        self.sizes = {}


class _KeyedMerge(_Merge):
    """One list of entities, last write wins per key (`ticker`, `metrics`, `wallet`); `newer(old,
    new)` may discard a replacement."""

    def __init__(
        self,
        limit: int,
        field: str,
        key: Callable[[Payload], Hashable],
        *,
        newer: Callable[[Payload, Payload], bool] | None = None,
        extra: tuple[str, ...] = (),
    ) -> None:
        super().__init__(limit, (field, *extra))
        self.field = field
        self.key = key
        self.newer = newer
        self.items: dict[Hashable, dict[str, Any]] = {}
        self.sizes: dict[Hashable, int] = {}

    def merge(self, body: Payload) -> bool:
        changed = False
        for item in body.get(self.field) or ():
            changed = self.upsert(self.key(item), item) or changed
        return changed

    def upsert(self, key: Hashable, item: Payload) -> bool:
        cur = self.items.get(key)
        if cur is None:
            if len(self.items) >= self.limit:
                raise _BufferFullError
        elif self.newer is not None and not self.newer(cur, item):
            return False
        else:
            del self.items[key]  # re-inserted below: entities leave in last-write order
        self.items[key] = dict(item)
        self._resize(key, _size(item))
        return True

    def _resize(self, key: Hashable, size: int) -> None:
        self.bytes += size - self.sizes.pop(key, 0)
        if size:
            self.sizes[key] = size

    def result(self) -> dict[str, Any]:
        return {**self.root, self.field: list(self.items.values())}

    def reset(self) -> None:
        super().reset()
        self.items, self.sizes = {}, {}


def _not_older(old: Payload, new: Payload) -> bool:
    """§15: entities carry `updated_at_ms` so a late-arriving older frame is discarded; the field
    is mandatory, so an entity without it is refused (overflow) rather than guessed."""
    return int(new["updated_at_ms"]) >= int(old["updated_at_ms"])


class _PositionsMerge(_KeyedMerge):
    """§8.2 `positions`: whole object per `id`; `removed` ids (went flat) apply after the upserts
    of the same update. An upsert of an id removed earlier in the window starts a new frame: one
    payload cannot say "removed, then re-opened" to a client that discards older entities."""

    def __init__(self, limit: int) -> None:
        super().__init__(limit, "positions", _id_key, newer=_not_older, extra=("removed",))
        self.removed: dict[str, None] = {}

    def splits(self, body: Payload) -> bool:
        return any(str(item["id"]) in self.removed for item in body.get("positions") or ())

    def merge(self, body: Payload) -> bool:
        changed = super().merge(body)
        for removed in body.get("removed") or ():
            pid = str(removed)
            if pid not in self.removed and len(self.removed) >= self.limit:
                raise _BufferFullError
            self.items.pop(pid, None)
            self._resize(pid, 0)
            if pid not in self.removed:
                self.removed[pid] = None
                self.bytes += _size(pid) + 1
            changed = True
        return changed

    def result(self) -> dict[str, Any]:
        out = super().result()
        if self.removed:
            out["removed"] = list(self.removed)
        return out

    def reset(self) -> None:
        super().reset()
        self.removed = {}


class _HeatmapMerge(_KeyedMerge):
    """§8.2 `heatmap`: per time-bucket column, last write wins; once a bucket's complete column
    was sent, any later column for that bucket is dropped, so a final column is never re-sent or
    regressed, unless the update also changes a root field (e.g. `max_value`). Columns leave in
    time order."""

    def __init__(self, limit: int) -> None:
        super().__init__(limit, "columns", _t_key)
        self.sent: dict[int, None] = {}
        self.known: dict[str, Any] = {}  # root fields as last seen, across emissions

    def add(self, body: Payload) -> bool:
        root = {k: v for k, v in body.items() if k not in self.lists}
        root_changed = any(k not in self.known or self.known[k] != v for k, v in root.items())
        changed = self.merge(body) or root_changed
        self.known.update(root)
        if changed:
            self.root.update(root)
            self.root_bytes = _size(self.root)
        return changed

    def upsert(self, key: Hashable, item: Payload) -> bool:
        if key in self.sent:
            self.trimmed = True
            return False
        return super().upsert(key, item)

    def result(self) -> dict[str, Any]:
        columns = sorted(self.items.values(), key=lambda col: int(col["t_ms"]))
        return {**self.root, "columns": columns}

    def emitted(self, body: Payload) -> None:
        for col in body.get("columns") or ():
            if col.get("complete") is True:
                self.sent[int(col["t_ms"])] = None
        while len(self.sent) > SENT_COLUMNS_MEMORY:
            del self.sent[next(iter(self.sent))]


class _FootprintMerge(_Merge):
    """§8.2 `footprint`: per (bar, price) cell the volume fields are increments summed within the
    same bar, never across bars; every other bar and cell field is last-write-wins. The bar key is
    `t_ms`, the only bar identity the §14.4 payload carries."""

    def __init__(self, limit: int) -> None:
        super().__init__(limit, ("bars",))
        self.bars: dict[int, tuple[dict[str, Any], dict[Decimal, dict[str, Any]]]] = {}
        self.keys = 0

    def merge(self, body: Payload) -> bool:
        bars = body.get("bars") or ()
        for bar in bars:
            t_ms = int(bar["t_ms"])
            entry = self.bars.get(t_ms)
            if entry is None:
                self._grow()
                entry = self.bars[t_ms] = ({}, {})
            fields, cells = entry
            before = _size(fields)
            fields.update((k, v) for k, v in bar.items() if k != "cells")
            self.bytes += _size(fields) - before
            for cell in bar.get("cells") or ():
                self._cell(cells, cell)
        return bool(bars)

    def _grow(self) -> None:
        if self.keys >= self.limit:
            raise _BufferFullError
        self.keys += 1

    def _cell(self, cells: dict[Decimal, dict[str, Any]], cell: Payload) -> None:
        price = _dec(cell["price"])
        cur = cells.get(price)
        if cur is None:
            self._grow()
            cur = cells[price] = {}
        before = _size(cur)
        for key, value in cell.items():
            if key in _SUMMED_DECIMALS:
                cur[key] = _plain(_dec(cur.get(key, 0)) + _dec(value))
            elif key in _SUMMED_COUNTS:
                cur[key] = int(cur.get(key, 0)) + int(value)
            else:
                cur[key] = value
        self.bytes += _size(cur) - before

    def result(self) -> dict[str, Any]:
        bars = []
        for t_ms in sorted(self.bars):
            fields, cells = self.bars[t_ms]
            bars.append({**fields, "cells": [cells[price] for price in sorted(cells)]})
        return {**self.root, "bars": bars}

    def reset(self) -> None:
        super().reset()
        self.bars, self.keys = {}, 0


class _AppendMerge(_Merge):
    """§8.2 `trades` / `liquidations`: items appended in arrival order, never merged; `summed`
    counters (the trades `dropped` count since the previous frame) add up."""

    def __init__(self, limit: int, field: str, summed: tuple[str, ...] = ()) -> None:
        super().__init__(limit, (field, *summed))
        self.field = field
        self.summed = summed
        self.items: list[dict[str, Any]] = []
        self.sums: dict[str, int] = {}

    def merge(self, body: Payload) -> bool:
        items = body.get(self.field) or ()
        if len(self.items) + len(items) > self.limit:
            raise _BufferFullError
        for item in items:
            self.items.append(dict(item))
            self.bytes += _size(item) + 1
        for name in self.summed:
            if name in body:
                self.sums[name] = self.sums.get(name, 0) + int(body[name])
        return True

    def result(self) -> dict[str, Any]:
        return {**self.root, self.field: self.items, **self.sums}

    def reset(self) -> None:
        super().reset()
        self.items, self.sums = [], {}


def _id_key(item: Payload) -> Hashable:
    return str(item["id"])


def _t_key(item: Payload) -> Hashable:
    return int(item["t_ms"])


def _symbol_key(item: Payload) -> Hashable:
    return str(item["symbol"])


def _balance_key(item: Payload) -> Hashable:
    return (str(item["exchange_account_id"]), str(item["coin"]))


def _metric_key(item: Payload) -> Hashable:
    """Per metric code; `params` tells two series of the same code apart."""
    params = item.get("params")
    return (str(item["metric"]), json.dumps(params, sort_keys=True) if params else "")


#: The §8.2 merge rule of each merged or appended family: `(keys bound, items bound) -> merge`.
_RULES: Final[Mapping[str, Callable[[int, int], _Merge]]] = {
    "book": lambda keys, _: _BookMerge(keys),
    "bars": lambda keys, _: _BarsMerge(keys),
    "footprint": lambda keys, _: _FootprintMerge(keys),
    "heatmap": lambda keys, _: _HeatmapMerge(keys),
    "metrics": lambda keys, _: _KeyedMerge(keys, "series", _metric_key),
    "ticker": lambda keys, _: _KeyedMerge(keys, "tickers", _symbol_key),
    "wallet": lambda keys, _: _KeyedMerge(keys, "balances", _balance_key, newer=_not_older),
    "positions": lambda keys, _: _PositionsMerge(keys),
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
        merged = merge.bytes + merge.root_bytes if merge is not None and self._count else 0
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
        """Queue one source update; False when refused, i.e. the queue is (or was) overflowed.
        `body` is the structured payload every family needs; `part` is its optional CVWB form."""
        if self._overflowed:
            return False
        if not isinstance(body, Mapping):
            self._overflowed = True  # a producer bug: refused like any other unmergeable update
            return False
        if self._private:
            try:
                body = copy.deepcopy(body)  # SR-190: nothing of a private update is shared
            except (*_REFUSED, copy.Error):
                self._overflowed = True
                return False
        merge = self._merge
        if merge is None or not (self.merging or self._count):
            if len(self._frames) < self._max_frames:
                emission = Emission(_own(body), part, 1, ts_ms)
                try:
                    size = _size(emission.body)
                except _REFUSED:
                    self._overflowed = True
                    return False
                self._frames.append(emission)
                self._frame_bytes += size
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
            if self._count and merge.splits(body):
                if len(self._frames) >= self._max_frames:
                    raise _BufferFullError  # windows split off count against the frame bound
                self._close_window(merge)
            changed = merge.add(body)
        except _REFUSED:
            self._overflowed = True
            return False
        if changed:
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
        if merge is not None:
            for emission in out:
                merge.emitted(emission.body)
        return out

    def _close_window(self, merge: _Merge) -> None:
        """Move the pending merge to the frame list as one emission (verbatim if unmerged)."""
        if self._count == 1 and self._first is not None and not merge.trimmed:
            emission = self._first
        elif self._count:
            count = 1 if self.family in APPENDED_FAMILIES else self._count
            emission = Emission(merge.result(), None, count, self._ts_ms)
        else:
            merge.reset()  # only discarded updates: nothing of theirs may leak into the next window
            return
        self._frames.append(emission)
        self._frame_bytes += merge.bytes + merge.root_bytes
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
