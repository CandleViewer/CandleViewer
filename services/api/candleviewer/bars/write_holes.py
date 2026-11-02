"""Closed bars not stored, kept as coverage holes until stored (#5396; 24 §19.81).

A closed bar whose store write reaches a terminal outcome without being stored is recorded once
here, served in `meta.coverage_holes` by REST `/market/bars` and `/market/klines` and by the WS
`bars` snapshot (22 `DataMeta`, 23 §13 `snapMeta`), counted by `bars_write_holes_total{reason}`
and queued for heal (`pending()`, the rebuild path's hand-off). It is never silently dropped.
`pending()` has no consumer yet: the rebuild executor is a no-op until #535 wires one.

**Identity.** A key is `(symbol, spec_hash, generation, index, open_time_us)`, as a stored row
(24 §3.1). A time bar is also identified by its open time alone, so a stored row at that open
time (a kline row included) is the same key; whether a served row suppresses its record is a
question of version (**Versions**, **Reads**).

**Records.** One record per range of contiguous indexes of one generation, with its span
`[from_us, to_us)` (a bar's span is `[open_time, close_time + 1)`), the reason of its first key,
the time it was first seen and the number of terminal outcomes it holds. Keys are recorded only
at a terminal outcome, never per attempt; a repeat raises `count` and is not counted again by the
metric. Each record keeps, per key, the row checksum of the version lost. A key whose loss is
reported for two different versions, or for an unknown one, is unknown for good: a served copy of
either version could otherwise hide the other's loss. At most `MAX_VERSIONS` slots a record and
`MAX_TOTAL_VERSIONS` in all; past either, and on a merged span, a key's version is unknown. An
unknown key is never suppressed by a tape-built bar (an exchange kline on `/market/klines` and the
time-edge trim still apply) and is not cleared by a store: only a heal (#535) clears it (an
over-report).

**Versions.** A key leaves its record only when the version lost is stored (`written` with the
same checksum). A store of another version keeps the record (`stale_served`): the store serves a
row that is not the one lost. A later write of a key already stored (an amend) that is not stored
is recorded with reason `superseded`; `MAX_RECENT_KEYS` stored keys are remembered with their
checksums, and a loss reported for the very version stored is no hole. None of this depends on
that memory: a read compares versions, below.

**Bound.** At most `MAX_RANGES_PER_SERIES` records per series and `MAX_TOTAL_RANGES` in all (the
series with the most merges first). Past either, the oldest records merge into one span: a merged
span over-reports (a key stored inside it does not split it), never under-reports. A key new to a
merged span is still counted. Past `MAX_SERIES_SOFT` series the stalest series collapse to one
merged span each. A record never expires with age (a pinned symbol or a raised retention policy
keeps serving old rows), and a series with records is never dropped below `MAX_SERIES`. Past
`MAX_SERIES` (the server builds far fewer) the stalest series is dropped: counted by
`bars_write_holes_dropped_total`, logged, and `dropped` degrades `bars_writer` (the ruled
exception of 24 §19.81).

**Reads.** `holes_for` is synchronous and in memory (the WS snapshot build is synchronous): the
spans inside the page's span, minus the bars the page serves that are the version lost (equal
checksums) or `trusted` (`Present`: an exchange kline only). A served bar of another or an
unknown version suppresses nothing: an over-report, never a stale row read as complete.

**Journal.** One versioned orjson file, `<bars_state_root>/write_holes.json`, written atomically
(write, flush, fsync, rename, directory fsync) after every change, one write at a time, and loaded
before the writer starts. The loop copies the records; serialising and writing run in a worker
thread, which keeps the file within `MAX_JOURNAL_BYTES` by merging the oldest records. A change is
written even when a write fails or its waiter is cancelled (the next change or `flush` writes it).
A file that cannot be read back is discarded, logged and counted
(`bars_blob_discarded_total{reason="write_holes"}`), and sets `dropped` (its records are no
longer listed); it never stops the start.
"""

from __future__ import annotations

import asyncio
import bisect
import os
import sys
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Protocol, get_args

import orjson
import structlog

from candleviewer.bars.metrics import (
    SUPERSEDED,
    WRITE_HOLE_REASONS,
    bars_blob_discarded_total,
    bars_write_holes_dropped_total,
    bars_write_holes_total,
)
from candleviewer.bars.models import BarKind
from candleviewer.bars.state_store import SPEC_HASH_PATTERN, SYMBOL_PATTERN
from candleviewer.observability.context import run_in_thread, spawn, thread_future

#: 3: a record row has 12 fields (`stale_served`, the lost versions, `overflow`); an older file
#: is discarded as `version`.
JOURNAL_VERSION: Final = 3
JOURNAL_NAME: Final = "write_holes.json"
MAX_JOURNAL_BYTES: Final = 8 * 1024 * 1024
MAX_RANGES_PER_SERIES: Final = 256
#: Records in all; with `MAX_SERIES` it keeps the journal far below `MAX_JOURNAL_BYTES` (a
#: record serialises to under 200 bytes), which the write enforces as well.
MAX_TOTAL_RANGES: Final = 16_384
#: Past this many series the stalest collapse to one merged span each (an over-report).
MAX_SERIES_SOFT: Final = 1_024
#: Series held at most (<= `MAX_TOTAL_RANGES`, so every series keeps a record). Past it a series
#: is dropped: an under-report that is counted, logged and degrades `bars_writer` (24 §19.81).
MAX_SERIES: Final = 16_384
#: Keys remembered as stored lately (a later loss is `superseded`) and as counted lately (a repeat
#: inside a merged span is not counted again).
MAX_RECENT_KEYS: Final = 4096
#: Lost versions kept per record and in all; past either a key's version is unknown: a tape-built
#: bar never suppresses it (a kline and the edge trim still apply); only a heal (#535) clears it.
MAX_VERSIONS: Final = 64
MAX_TOTAL_VERSIONS: Final = 16_384
#: Recorded and superseded losses are logged at most once per series per minute.
LOG_EVERY_US: Final = 60_000_000
#: The closed `reason` values `lost` takes; a record also takes `superseded` (a stored key's).
HOLE_REASONS: Final = WRITE_HOLE_REASONS
_RECORD_REASONS: Final = (*WRITE_HOLE_REASONS, SUPERSEDED)
_KINDS: Final = frozenset(get_args(BarKind))


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _wall_us() -> int:
    return time.time_ns() // 1000


@dataclass(frozen=True, slots=True)
class HoleKey:
    """One closed bar of a series: its identity and its span `[open_us, end_us)`. `generation`
    and `index` are None for a row with no builder index (a kline row). `checksum` is the row's
    `row_checksum` when known: it tells the version stored from a later one."""

    symbol: str
    spec_hash: str
    kind: str
    bar_param: str
    generation: int | None
    index: int | None
    open_us: int
    end_us: int
    checksum: int | None = None


@dataclass(frozen=True, slots=True)
class Present:
    """A bar a response serves: `(generation, index, open_us, end_us)`, and the version served.
    It suppresses a recorded key only when it is the version that was lost (`checksum` equal to
    the record's lost checksum), or when `trusted`: a bar of another source that fills the
    interval (an exchange kline on `/market/klines`). A tape-built bar is never trusted, a WS
    series store's in-memory one included (a read hydrates the stored row, which can be the
    version before a lost amend). An unknown version suppresses nothing (an over-report)."""

    generation: int | None
    index: int | None
    open_us: int
    end_us: int
    checksum: int | None = None
    trusted: bool = False


@dataclass(frozen=True, slots=True)
class HoleRange:
    """One record, as `pending()` hands it to the heal path."""

    symbol: str
    spec_hash: str
    kind: str
    bar_param: str
    generation: int
    first_index: int
    last_index: int
    from_us: int
    to_us: int
    reason: str
    first_seen_us: int
    count: int
    merged: bool
    stale_served: bool


@dataclass(slots=True)
class _Range:
    generation: int
    first: int
    last: int
    from_us: int
    to_us: int
    reason: str
    first_seen_us: int
    count: int
    merged: bool = False
    #: A version other than the lost one is stored for a key here (informational: `holes_for`
    #: compares versions, `versions`).
    stale_served: bool = False
    #: The lost version's row checksum per key (`_vkey`: open time for a time bar, else index),
    #: at most `MAX_VERSIONS` a record. None: unknown for good (an unknown version was lost, or
    #: two different ones were). A key with no slot is unknown too. Empty on a merged span.
    versions: dict[int, int | None] = field(default_factory=dict)
    #: The record could not keep a slot (`MAX_VERSIONS`, or the global budget): a key with no slot
    #: never gets one, so it stays unknown.
    overflow: bool = False

    def holds(self, kind: str, key: Present) -> bool:
        """True when `key` is one of this record's keys (a time bar: by its open time)."""
        if not self.from_us <= key.open_us < self.to_us:
            return False
        if kind == "time" or self.merged:
            return True
        same = key.generation == self.generation and key.index is not None
        return same and self.first <= (key.index or 0) <= self.last

    def without(self, kind: str, key: Present) -> list[_Range]:
        """This record with `key` taken out: 0, 1 or 2 records. A merged span of a non-time series
        keeps the key (over-report: its siblings at one open time cannot be told apart)."""
        if self.merged and kind != "time":
            return [self]
        same = key.generation == self.generation and key.index is not None
        parts: list[_Range] = []
        if kind == "time":
            left_to, right_from = key.open_us, key.end_us
        else:  # a neighbour may share an open time: each side keeps it
            left_to, right_from = key.open_us + 1, key.end_us - 1
        left_last = key.index - 1 if same and key.index is not None else self.last
        right_first = key.index + 1 if same and key.index is not None else self.first
        if self.from_us < min(left_to, self.to_us) and (kind == "time" or left_last >= self.first):
            parts.append(self._part(kind, self.first, min(left_last, self.last), self.from_us,
                                    min(left_to, self.to_us)))  # fmt: skip
        if max(right_from, self.from_us) < self.to_us and (
            kind == "time" or right_first <= self.last
        ):
            parts.append(self._part(kind, max(right_first, self.first), self.last,
                                    max(right_from, self.from_us), self.to_us))  # fmt: skip
        return parts

    def _part(self, kind: str, first: int, last: int, from_us: int, to_us: int) -> _Range:
        last = max(first, last)
        kept = {k: v for k, v in self.versions.items()
                if (from_us <= k < to_us if kind == "time" else first <= k <= last)}  # fmt: skip
        return _Range(
            self.generation, first, last, from_us, to_us, self.reason, self.first_seen_us,
            self.count, self.merged, self.stale_served, kept, self.overflow,
        )  # fmt: skip


@dataclass(slots=True)
class _Series:
    kind: str
    bar_param: str
    ranges: list[_Range]
    touched_us: int = 0  # last record change (the series cap drops the stalest)


class HoleRecorder(Protocol):
    """What the write path calls: terminal outcomes of closed bars."""

    def lost(self, keys: Sequence[HoleKey], reason: str) -> int: ...
    def written(self, keys: Sequence[HoleKey]) -> None: ...


def hole_key_for_row(row: dict[str, object], spec_hash: str, kind: str) -> HoleKey:
    """The key of a stored row (`bars.rows.bar_row`'s shape; `ts`/`close_ts` in µs). A kline row
    (no builder index) stores the next interval's open as its `close_ts` (`bars.kline_rows`)."""
    gen, idx = row.get("generation"), row.get("index")
    open_us = int(str(row["ts"]))
    close = row.get("close_ts")
    last = 0 if idx is None else 1  # a builder bar's close is its last µs
    end_us = open_us + 1 if close is None else int(str(close)) + last
    return HoleKey(
        str(row["symbol"]), spec_hash, kind, str(row.get("bar_param") or ""),
        None if gen is None else int(str(gen)), None if idx is None else int(str(idx)),
        open_us, max(end_us, open_us + 1),
        None if row.get("row_checksum") is None else int(str(row["row_checksum"])),
    )  # fmt: skip


class WriteHoleLedger:
    """The ledger of the module docstring. Every method but `load`/`flush` is synchronous and
    runs on the event loop; the journal's serialisation and write run in a worker thread."""

    def __init__(self, root: Path, *, now_us: Callable[[], int] = _wall_us) -> None:
        self._path = root / JOURNAL_NAME
        self._now = now_us
        self._series: dict[tuple[str, str], _Series] = {}
        self._revisions: dict[tuple[str, str], int] = {}
        #: Keys stored lately, with the stored row's checksum (None: unknown).
        self._recent: OrderedDict[_KeyId, int | None] = OrderedDict()
        self._counted: OrderedDict[_KeyId, None] = OrderedDict()  # keys counted lately
        self._logged: dict[tuple[tuple[str, str], str], int] = {}
        self._dirty = False
        self._task: asyncio.Task[None] | None = None
        self._writing: asyncio.Future[None] | None = None
        #: Sticky: records are no longer listed (a series dropped past `MAX_SERIES`, or a journal
        #: discarded on `load`): an under-report, so `bars_writer` reports DEGRADED.
        self.dropped = False

    # -- the write path ---------------------------------------------------------------------

    def lost(self, keys: Sequence[HoleKey], reason: str) -> int:
        """Record the terminal outcome of closed bars not stored; returns the keys new to the
        ledger (the metric's increments). A key with no builder index is not recorded. A key
        stored before is recorded as `superseded` and `stale_served` (module docstring)."""
        if reason not in HOLE_REASONS:
            raise ValueError(f"unknown write-hole reason {reason!r}")
        new: dict[tuple[str, str], int] = {}
        superseded: dict[tuple[str, str], int] = {}
        for key in keys:
            gen, idx = key.generation, key.index
            if gen is None or idx is None:
                continue
            series_key = (key.symbol, key.spec_hash)
            kid = _key_id(key)
            if kid in self._recent and key.checksum is not None:
                if self._recent[kid] == key.checksum:
                    continue  # this very version is stored: no hole
            stale = kid in self._recent  # an earlier row of it is served
            if stale:  # its latest version is not stored now; a later store re-adds it
                del self._recent[kid]
            series = self._series.get(series_key) or self._add_series(series_key, key)
            series.touched_us = self._now()
            added, spans = self._insert(
                series, key, gen, idx, SUPERSEDED if stale else reason, stale=stale
            )
            if added:
                tally = superseded if stale else new
                tally[series_key] = tally.get(series_key, 0) + 1
                _remember(self._counted, _key_id(key), MAX_RECENT_KEYS)
            self._changed(series_key, spans=spans)
        self._collapse_stale()
        self._enforce_total()
        for series_key, n in new.items():
            bars_write_holes_total.labels(reason=reason).inc(n)
            self._log_due(series_key, "bars_write_holes_recorded", "error", reason=reason, bars=n)
        for series_key, n in superseded.items():
            bars_write_holes_total.labels(reason=SUPERSEDED).inc(n)
            self._log_due(series_key, "bars_write_holes_superseded", "warning", bars=n)
        return sum(new.values()) + sum(superseded.values())

    def written(self, keys: Sequence[HoleKey]) -> None:
        """Keys now stored (and remembered for `lost`). A key leaves its record only when the
        version stored is the one lost (equal checksums); another version leaves the record in
        place, `stale_served`: the store now serves a row that is not the lost one."""
        for key in keys:
            self._recent[_key_id(key)] = key.checksum
            self._recent.move_to_end(_key_id(key))
            while len(self._recent) > MAX_RECENT_KEYS:
                self._recent.popitem(last=False)
            series_key = (key.symbol, key.spec_hash)
            series = self._series.get(series_key)
            if series is None:
                continue
            p = Present(key.generation, key.index, key.open_us, key.end_us, key.checksum)
            changed = False
            ranges: list[_Range] = []
            for r in series.ranges:
                if not r.holds(series.kind, p):
                    ranges.append(r)
                elif _same_version(series.kind, r, p):
                    ranges += r.without(series.kind, p)
                    self._counted.pop(_key_id(key), None)  # a later loss of it is new
                    changed = True
                else:
                    changed = changed or not r.stale_served
                    r.stale_served = True
                    ranges.append(r)
            if changed:
                series.ranges = ranges
                if not ranges:
                    del self._series[series_key]
                self._changed(series_key, spans=True)

    def _add_series(self, series_key: tuple[str, str], key: HoleKey) -> _Series:
        """A new series. At `MAX_SERIES` the stalest series is dropped (counted, logged, `dropped`
        set): the ruled exception of 24 §19.81."""
        while len(self._series) >= MAX_SERIES:
            old_key = min(self._series, key=lambda k: self._series[k].touched_us)
            lost = self._series.pop(old_key)
            bars_write_holes_dropped_total.inc(len(lost.ranges))
            self.dropped = True
            _log().error("bars_write_holes_series_dropped", spec_hash=old_key[1],
                         records=len(lost.ranges))  # fmt: skip
            self._changed(old_key, spans=True)
        series = _Series(key.kind, key.bar_param, [])
        self._series[series_key] = series
        return series

    def _insert(
        self, series: _Series, key: HoleKey, gen: int, idx: int, reason: str, *, stale: bool
    ) -> tuple[bool, bool]:
        """Add `key` (generation `gen`, index `idx`; `stale`: an earlier row of it is served):
        (new to the ledger, spans changed). Inside a merged span a key is new unless it was
        counted lately (`MAX_RECENT_KEYS`). A record that holds a `stale` key becomes
        `stale_served`."""
        p = Present(gen, idx, key.open_us, key.end_us)
        vk = _vkey(series.kind, p)
        for r in series.ranges:
            if r.holds(series.kind, p):
                r.count += 1
                r.stale_served = r.stale_served or stale
                versions = _note_version(r, vk, key.checksum)  # the latest version lost
                if not r.merged or _key_id(key) in self._counted:
                    return False, versions
                grown = key.end_us > r.to_us  # a key new to a merged span: its whole bar is in
                r.to_us = max(r.to_us, key.end_us)
                return True, grown or versions
        open_ = [r for r in series.ranges if not r.merged and r.generation == gen]
        before = next((r for r in open_ if r.last == idx - 1), None)
        after = next((r for r in open_ if r.first == idx + 1), None)
        if before is not None:
            before.last, before.to_us = idx, max(before.to_us, key.end_us)
            before.count += 1
            before.stale_served = before.stale_served or stale
            _note_version(before, vk, key.checksum)
            if after is not None:  # the key joins two records
                before.last, before.to_us = after.last, max(before.to_us, after.to_us)
                before.count += after.count
                before.stale_served = before.stale_served or after.stale_served
                before.overflow = before.overflow or after.overflow
                for k, v in after.versions.items():
                    _note_version(before, k, v)
                series.ranges.remove(after)
        elif after is not None:
            after.first, after.from_us = idx, min(after.from_us, key.open_us)
            after.count += 1
            after.stale_served = after.stale_served or stale
            _note_version(after, vk, key.checksum)
        else:
            fresh = _Range(gen, idx, idx, key.open_us, key.end_us, reason, self._now(), 1,
                           stale_served=stale)  # fmt: skip
            _note_version(fresh, vk, key.checksum)
            series.ranges.append(fresh)
        series.ranges.sort(key=lambda r: (r.from_us, r.to_us))
        while len(series.ranges) > MAX_RANGES_PER_SERIES:
            _merge_oldest(series)
        return True, True

    def _enforce_total(self) -> None:
        """At most `MAX_TOTAL_RANGES` records in all: the series with the most merges its oldest
        (a series with one record is left as it is). At most `MAX_TOTAL_VERSIONS` slots in all:
        the record with the most gives all of them up (its keys become unknown: an over-report)."""
        slots = sum(len(r.versions) for s in self._series.values() for r in s.ranges)
        while slots > MAX_TOTAL_VERSIONS:
            series_key, r = max(
                ((k, r) for k, s in self._series.items() for r in s.ranges),
                key=lambda kr: len(kr[1].versions),
            )
            slots -= len(r.versions)
            r.versions, r.overflow = {}, True
            self._changed(series_key, spans=True)
        total = sum(len(s.ranges) for s in self._series.values())
        while total > MAX_TOTAL_RANGES and self._series:
            series_key = max(self._series, key=lambda k: len(self._series[k].ranges))
            if len(self._series[series_key].ranges) < 2:
                return
            _merge_oldest(self._series[series_key])
            total -= 1
            self._changed(series_key, spans=True)

    def _collapse_stale(self) -> None:
        """Past `MAX_SERIES_SOFT` series every series but the `MAX_SERIES_SOFT` changed most
        recently collapses to one merged span."""
        excess = len(self._series) - MAX_SERIES_SOFT
        if excess <= 0:
            return
        for series_key in sorted(self._series, key=lambda k: self._series[k].touched_us)[:excess]:
            series = self._series[series_key]
            if len(series.ranges) > 1:
                while len(series.ranges) > 1:
                    _merge_oldest(series)
                self._changed(series_key, spans=True)

    def _changed(self, series_key: tuple[str, str], *, spans: bool) -> None:
        """A change to persist; `spans` when the series' reported spans changed (a render cache
        keys on the revision)."""
        if spans:
            self._revisions[series_key] = self._revisions.get(series_key, 0) + 1
        self._dirty = True
        self._schedule()

    def _log_due(self, series_key: tuple[str, str], event: str, level: str, **fields: Any) -> None:
        """Log `event` for a series at most once per `LOG_EVERY_US`."""
        now = self._now()
        last = self._logged.get((series_key, event))
        if last is not None and now - last < LOG_EVERY_US:
            return
        if len(self._logged) >= 4 * MAX_SERIES:
            self._logged.clear()
        self._logged[series_key, event] = now
        getattr(_log(), level)(event, spec_hash=series_key[1], **fields)

    # -- the read path ----------------------------------------------------------------------

    def revision(self, symbol: str, spec_hash: str) -> int:
        """Changes whenever the series' reported spans change (a render cache keys on it)."""
        return self._revisions.get((symbol, spec_hash), 0)

    def holes_for(
        self, symbol: str, spec_hash: str, from_us: int, to_us: int, present: Iterable[Present]
    ) -> list[tuple[int, int]]:
        """The series' spans inside `[from_us, to_us)`, minus the bars in `present` (those a
        response serves) that are the version lost or trusted (`Present`), oldest first,
        overlapping and touching spans joined."""
        series = self._series.get((symbol, spec_hash))
        if series is None or from_us >= to_us:
            return []
        served = sorted(present, key=lambda p: p.open_us)
        opens = [p.open_us for p in served]
        spans: list[tuple[int, int]] = []
        for r in series.ranges:
            if r.to_us <= from_us or r.from_us >= to_us:
                continue
            parts = [r]
            for p in served[
                bisect.bisect_left(opens, r.from_us) : bisect.bisect_left(opens, r.to_us)
            ]:
                parts = _subtract(series.kind, parts, p)
            spans += [(max(x.from_us, from_us), min(x.to_us, to_us)) for x in parts]
        return join_spans(s for s in spans if s[0] < s[1])

    def pending(self) -> list[HoleRange]:
        """Every record, for the heal path. Nothing consumes it yet: the rebuild executor is a
        no-op until #535 (module docstring)."""
        return [
            HoleRange(sym, h, s.kind, s.bar_param, r.generation, r.first, r.last, r.from_us,
                      r.to_us, r.reason, r.first_seen_us, r.count, r.merged, r.stale_served)
            for (sym, h), s in self._series.items() for r in s.ranges
        ]  # fmt: skip

    # -- the journal ------------------------------------------------------------------------

    def _schedule(self) -> None:
        """Start the journal write when none is in flight (it writes again while changes come)."""
        if self._task is not None and not self._task.done():
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:  # no loop (a synchronous caller): `flush` writes it
            return
        self._task = spawn(self._flush_loop(), name="bars-write-holes-journal")

    async def _flush_loop(self) -> None:
        """Write while changed. `_dirty` is set again unless the write completed, so neither a
        failure nor a cancellation loses a change: the next change or `flush` writes it."""
        while self._dirty:
            snapshot = self._snapshot()
            self._dirty = False
            try:
                await self._write(snapshot)
            except asyncio.CancelledError:
                self._dirty = True
                raise
            except Exception as exc:
                self._dirty = True
                _log().error("bars_write_holes_journal_write_failed", error=type(exc).__name__)
                return

    async def _write(self, snapshot: _Snapshot) -> None:
        """One write at a time: a write still running (its waiter cancelled) finishes first. The
        thread's future is shielded, so a cancelled waiter never cuts a write short."""
        prior = self._writing
        if prior is not None and not prior.done():
            await asyncio.wait({prior})
        fut = thread_future(_serialise_and_write, self._path, snapshot)
        fut.add_done_callback(_retrieve)
        self._writing = fut
        await asyncio.shield(fut)

    async def flush(self) -> None:
        """Write the journal now if it changed since its last write, and wait for the write in
        flight (the stop path)."""
        task = self._task
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        if self._dirty:
            self._task = spawn(self._flush_loop(), name="bars-write-holes-journal")
            await self._task
        writing = self._writing
        if writing is not None and not writing.done():
            await asyncio.wait({writing})

    def _snapshot(self) -> _Snapshot:
        """A copy of the records as plain tuples (cheap; serialised in the worker thread)."""
        return [
            (sym, h, s.kind, s.bar_param,
             [(r.generation, r.first, r.last, r.from_us, r.to_us, r.reason, r.first_seen_us,
               r.count, r.merged, r.stale_served, sorted(r.versions.items()), r.overflow)
              for r in s.ranges])
            for (sym, h), s in sorted(self._series.items())
        ]  # fmt: skip

    async def load(self) -> str:
        """Read the journal before the writer starts: `"ok"`, `"missing"` or the reason the file
        was discarded (counted, logged, `dropped` set; the ledger then starts empty). Never
        raises."""
        loaded, reason = await run_in_thread(_read_journal, self._path)
        if loaded is None:
            if reason != "missing":  # the holes it held are no longer listed: an under-report
                self.dropped = True
                bars_blob_discarded_total.labels(reason="write_holes").inc()
                _log().error("bars_write_holes_journal_discarded", reason=reason)
            return reason
        for series_key, series in loaded.items():
            self._series[series_key] = series
            self._revisions[series_key] = self._revisions.get(series_key, 0) + 1
        self._collapse_stale()
        self._enforce_total()
        return reason


#: `(symbol, spec_hash, generation, index, open_us)`; a time bar's is `(…, -1, -1, open_us)`.
_KeyId = tuple[str, str, int, int, int]
_Row = tuple[int, int, int, int, int, str, int, int, bool, bool, list[tuple[int, int | None]], bool]
_Snapshot = list[tuple[str, str, str, str, list[_Row]]]


def _key_id(key: HoleKey) -> _KeyId:
    if key.kind == "time":
        return key.symbol, key.spec_hash, -1, -1, key.open_us
    gen = -1 if key.generation is None else key.generation
    return key.symbol, key.spec_hash, gen, -1 if key.index is None else key.index, key.open_us


def _remember(lru: OrderedDict[_KeyId, None], key: _KeyId, bound: int) -> None:
    lru[key] = None
    lru.move_to_end(key)
    while len(lru) > bound:
        lru.popitem(last=False)


def _merge_oldest(series: _Series) -> None:
    """The series' two oldest records become one merged span."""
    a, b = series.ranges[0], series.ranges[1]
    series.ranges[0:2] = [
        _Range(a.generation, min(a.first, b.first), max(a.last, b.last),
               min(a.from_us, b.from_us), max(a.to_us, b.to_us), a.reason,
               min(a.first_seen_us, b.first_seen_us), a.count + b.count, merged=True,
               stale_served=a.stale_served or b.stale_served)  # versions unknown: over-report
    ]  # fmt: skip


def _retrieve(fut: asyncio.Future[None]) -> None:
    """Mark a write's outcome retrieved (its waiter may be gone; `_flush_loop` logs failures)."""
    if not fut.cancelled():
        fut.exception()


def _serialise_and_write(path: Path, snapshot: _Snapshot) -> None:
    """Worker thread: serialise, keep within `MAX_JOURNAL_BYTES` (merging the oldest records of
    the largest series, an over-report), then write atomically."""
    while True:
        series = [
            {"symbol": sym, "spec_hash": h, "kind": kind, "bar_param": param,
             "ranges": [[*r[:10], [list(v) for v in r[10]], r[11]] for r in rows]}
            for sym, h, kind, param, rows in snapshot
        ]  # fmt: skip
        data = orjson.dumps({"v": JOURNAL_VERSION, "series": series})
        if len(data) <= MAX_JOURNAL_BYTES:
            break
        rows = max((s[4] for s in snapshot), key=len)
        if len(rows) < 2:
            raise ValueError("the write-hole journal cannot fit its bound")
        a, b = rows[0], rows[1]
        rows[0:2] = [(
            a[0], min(a[1], b[1]), max(a[2], b[2]), min(a[3], b[3]), max(a[4], b[4]), a[5],
            min(a[6], b[6]), a[7] + b[7], True, a[9] or b[9], [], True,
        )]  # fmt: skip
    _write_atomic(path, data)


def _write_atomic(path: Path, data: bytes) -> None:
    """Write, flush, fsync, rename, then fsync the directory so the rename is durable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    if sys.platform != "win32":
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _read_journal(path: Path) -> tuple[dict[tuple[str, str], _Series] | None, str]:
    try:
        with path.open("rb") as f:
            data = f.read(MAX_JOURNAL_BYTES + 1)
    except FileNotFoundError:
        return None, "missing"
    except OSError:
        return None, "unreadable"
    if len(data) > MAX_JOURNAL_BYTES:
        return None, "too_large"
    try:
        doc = orjson.loads(data)
        if doc["v"] != JOURNAL_VERSION:
            return None, "version"
        if len(doc["series"]) > MAX_SERIES:
            return None, "corrupt"  # never written by this server
        out = {_series_key(s): _parse_series(s) for s in doc["series"]}
    except (ValueError, KeyError, TypeError, IndexError, AttributeError):
        return None, "corrupt"
    return out, "ok"


def _int(value: object, low: int = 0) -> int:
    if type(value) is not int or value < low:
        raise ValueError("not a bounded integer")
    return value


def _series_key(doc: dict[str, Any]) -> tuple[str, str]:
    symbol, spec_hash = doc["symbol"], doc["spec_hash"]
    if not (isinstance(symbol, str) and SYMBOL_PATTERN.fullmatch(symbol)):
        raise ValueError("symbol")
    if not (isinstance(spec_hash, str) and SPEC_HASH_PATTERN.fullmatch(spec_hash)):
        raise ValueError("spec_hash")
    return symbol, spec_hash


def _parse_series(doc: dict[str, Any]) -> _Series:
    kind, param, rows = doc["kind"], doc["bar_param"], doc["ranges"]
    if kind not in _KINDS or not isinstance(param, str) or len(param) > 64:
        raise ValueError("kind or bar_param")
    if not isinstance(rows, list) or not 0 < len(rows) <= MAX_RANGES_PER_SERIES:
        raise ValueError("ranges")
    ranges = []
    for gen, first, last, from_us, to_us, reason, seen, count, merged, stale, pairs, over in rows:
        flags = (merged, stale, over)
        if reason not in _RECORD_REASONS or any(type(f) is not bool for f in flags):
            raise ValueError("reason, merged, stale_served or overflow")
        r = _Range(_int(gen), _int(first), _int(last), _int(from_us), _int(to_us), reason,
                   _int(seen), _int(count, 1), merged, stale, _versions(pairs, merged),
                   over)  # fmt: skip
        if r.last < r.first or r.to_us <= r.from_us:
            raise ValueError("empty range")
        ranges.append(r)
    return _Series(kind, param, sorted(ranges, key=lambda r: (r.from_us, r.to_us)))


def _versions(pairs: object, merged: bool) -> dict[int, int | None]:
    """A journal row's lost versions: `[[slot, checksum or null], ...]`, none on a merged span."""
    if not isinstance(pairs, list) or len(pairs) > MAX_VERSIONS or (merged and pairs):
        raise ValueError("versions")
    out: dict[int, int | None] = {}
    for pair in pairs:
        ok = isinstance(pair, list) and len(pair) == 2
        if not ok or not (pair[1] is None or type(pair[1]) is int):
            raise ValueError("version pair")
        out[_int(pair[0])] = pair[1]
    return out


def _subtract(kind: str, ranges: list[_Range], p: Present) -> list[_Range]:
    """`ranges` minus the served bar `p` where it is the version lost (or `trusted`), or where it
    is another bar that a time record's span reaches (same generation, an index outside it)."""
    out: list[_Range] = []
    for r in ranges:
        hit = r.holds(kind, p) and (
            p.trusted or _same_version(kind, r, p) or _another_bar(kind, r, p)
        )
        out += r.without(kind, p) if hit else [r]
    return out


def _another_bar(kind: str, r: _Range, p: Present) -> bool:
    """A served time bar that is not one of `r`'s keys: a time record holds by open time, so its
    span's edge can reach a neighbour, which then trims it whatever its version."""
    if kind != "time" or r.merged or p.index is None or p.generation != r.generation:
        return False
    return not r.first <= p.index <= r.last


def _vkey(kind: str, p: Present) -> int:
    """A key's slot in `_Range.versions`: its open time for a time bar, else its index."""
    return p.open_us if kind == "time" or p.index is None else p.index


def _same_version(kind: str, r: _Range, p: Present) -> bool:
    """`p` is the version lost for its key here (an unknown version on either side is not)."""
    lost = r.versions.get(_vkey(kind, p))
    return lost is not None and p.checksum is not None and lost == p.checksum


def _note_version(r: _Range, vk: int, checksum: int | None) -> bool:
    """Record `checksum` (None: unknown) as a version lost for slot `vk`; True when a version
    a read compares with changed. A slot that holds another version, or an unknown one, becomes
    unknown for good: a served copy of either version could otherwise hide the other's loss. A
    merged span keeps none; a full record keeps no new slot (`overflow`)."""
    if r.merged:
        return False
    if vk in r.versions:
        held = r.versions[vk]
        if held is None or held == checksum:
            return False
        r.versions[vk] = None
        return True
    if r.overflow or len(r.versions) >= MAX_VERSIONS:
        r.overflow = True
        return False
    r.versions[vk] = checksum
    return checksum is not None


def cap_spans(spans: list[tuple[int, int]], limit: int) -> list[tuple[int, int]]:
    """At most `limit` (>= 1) of the sorted, disjoint `spans`: past it the oldest are joined into
    one span, which may cover served bars (over-report) and never leaves a hole out."""
    if len(spans) <= limit:
        return spans
    cut = len(spans) - limit + 1
    return [(spans[0][0], spans[cut - 1][1]), *spans[cut:]]


def join_spans(spans: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    """`spans` sorted, overlapping and touching ones joined."""
    out: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out
