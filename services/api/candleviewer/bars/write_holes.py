"""Closed bars not stored, kept as coverage holes until stored (#5396; 24 §19.81).

A closed bar whose store write reaches a terminal outcome without being stored is recorded once
here, served in `meta.coverage_holes` by REST `/market/bars` and `/market/klines` and by the WS
`bars` snapshot (22 `DataMeta`, 23 §13 `snapMeta`), counted by `bars_write_holes_total{reason}`
and queued for heal (`pending()`, the rebuild path's hand-off). It is never silently dropped.

**Identity.** A key is `(symbol, spec_hash, generation, index, open_time_us)`, as a stored row
(24 §3.1). A time bar is also identified by its open time alone: a stored row at that open time
(a kline row included) fills it.

**Records.** One record per range of contiguous indexes of one generation, with its span
`[from_us, to_us)` (a bar's span is `[open_time, close_time + 1)`), the reason of its first key,
the time it was first seen and the number of terminal outcomes it holds. Keys are recorded only
at a terminal outcome, never per attempt; a repeat raises `count` and is not counted again by the
metric. A key stored since (`written`) leaves its record, which splits around it. A key stored
just before its loss is reported is not recorded: the store holds a row for it
(`MAX_RECENT_WRITTEN` keys are remembered).

**Bound.** At most `MAX_RANGES_PER_SERIES` records per series. Past that, the oldest records merge
into one span: a merged span over-reports (a key stored inside it does not split it), never
under-reports.

**Reads.** `holes_for` is synchronous and in memory (the WS snapshot build is synchronous): the
spans inside the page's span, minus the bars the page serves.

**Journal.** One versioned orjson file, `<bars_state_root>/write_holes.json`, written atomically
(write, flush, fsync, rename, in a worker thread) after every change, and loaded before the writer
starts. A file that cannot be read back is discarded, logged and counted
(`bars_blob_discarded_total{reason="write_holes"}`); it never stops the start.
"""

from __future__ import annotations

import asyncio
import bisect
import os
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Protocol, get_args

import orjson
import structlog

from candleviewer.bars.metrics import (
    WRITE_HOLE_REASONS,
    bars_blob_discarded_total,
    bars_write_holes_total,
)
from candleviewer.bars.models import BarKind
from candleviewer.bars.state_store import SPEC_HASH_PATTERN, SYMBOL_PATTERN
from candleviewer.observability.context import run_in_thread, spawn

JOURNAL_VERSION: Final = 1
JOURNAL_NAME: Final = "write_holes.json"
MAX_JOURNAL_BYTES: Final = 8 * 1024 * 1024
MAX_RANGES_PER_SERIES: Final = 256
MAX_RECENT_WRITTEN: Final = 4096
#: The closed `reason` values of `bars_write_holes_total` and of a record.
HOLE_REASONS: Final = WRITE_HOLE_REASONS
_KINDS: Final = frozenset(get_args(BarKind))


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _wall_us() -> int:
    return time.time_ns() // 1000


@dataclass(frozen=True, slots=True)
class HoleKey:
    """One closed bar of a series: its identity and its span `[open_us, end_us)`. `generation`
    and `index` are None for a row with no builder index (a kline row)."""

    symbol: str
    spec_hash: str
    kind: str
    bar_param: str
    generation: int | None
    index: int | None
    open_us: int
    end_us: int


@dataclass(frozen=True, slots=True)
class Present:
    """A bar a response serves: `(generation, index, open_us, end_us)`."""

    generation: int | None
    index: int | None
    open_us: int
    end_us: int


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
            parts.append(self._part(self.first, min(left_last, self.last), self.from_us,
                                    min(left_to, self.to_us)))  # fmt: skip
        if max(right_from, self.from_us) < self.to_us and (
            kind == "time" or right_first <= self.last
        ):
            parts.append(self._part(max(right_first, self.first), self.last,
                                    max(right_from, self.from_us), self.to_us))  # fmt: skip
        return parts

    def _part(self, first: int, last: int, from_us: int, to_us: int) -> _Range:
        return _Range(self.generation, first, max(first, last), from_us, to_us, self.reason,
                      self.first_seen_us, self.count, self.merged)  # fmt: skip


@dataclass(slots=True)
class _Series:
    kind: str
    bar_param: str
    ranges: list[_Range]


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
    )  # fmt: skip


class WriteHoleLedger:
    """The ledger of the module docstring. Every method but `load`/`flush` is synchronous and
    runs on the event loop; the journal write is the only blocking work, in a worker thread."""

    def __init__(self, root: Path, *, now_us: Callable[[], int] = _wall_us) -> None:
        self._path = root / JOURNAL_NAME
        self._now = now_us
        self._series: dict[tuple[str, str], _Series] = {}
        self._revisions: dict[tuple[str, str], int] = {}
        self._recent: OrderedDict[tuple[str, str, int, int, int], None] = OrderedDict()
        self._dirty = False
        self._task: asyncio.Task[None] | None = None

    # -- the write path ---------------------------------------------------------------------

    def lost(self, keys: Sequence[HoleKey], reason: str) -> int:
        """Record the terminal outcome of closed bars not stored; returns the keys new to the
        ledger (the metric's increment). A key with no builder index is not recorded."""
        if reason not in HOLE_REASONS:
            raise ValueError(f"unknown write-hole reason {reason!r}")
        new = 0
        for key in keys:
            gen, idx = key.generation, key.index
            if gen is None or idx is None or self._recent_key(key) in self._recent:
                continue
            series_key = (key.symbol, key.spec_hash)
            series = self._series.setdefault(series_key, _Series(key.kind, key.bar_param, []))
            if self._insert(series, key, gen, idx, reason):
                new += 1
            self._changed(series_key)
        if new:
            bars_write_holes_total.labels(reason=reason).inc(new)
            _log().error("bars_write_holes_recorded", reason=reason, bars=new)
        return new

    def written(self, keys: Sequence[HoleKey]) -> None:
        """Keys now stored: each leaves its record (and is remembered for `lost`)."""
        for key in keys:
            self._recent[self._recent_key(key)] = None
            self._recent.move_to_end(self._recent_key(key))
            series_key = (key.symbol, key.spec_hash)
            series = self._series.get(series_key)
            if series is None:
                continue
            p = Present(key.generation, key.index, key.open_us, key.end_us)
            ranges = _subtract(series.kind, series.ranges, p)
            if ranges != series.ranges:
                series.ranges = ranges
                if not ranges:
                    del self._series[series_key]
                self._changed(series_key)
        while len(self._recent) > MAX_RECENT_WRITTEN:
            self._recent.popitem(last=False)

    @staticmethod
    def _recent_key(key: HoleKey) -> tuple[str, str, int, int, int]:
        if key.kind == "time":
            return key.symbol, key.spec_hash, -1, -1, key.open_us
        gen = -1 if key.generation is None else key.generation
        return key.symbol, key.spec_hash, gen, -1 if key.index is None else key.index, key.open_us

    def _insert(self, series: _Series, key: HoleKey, gen: int, idx: int, reason: str) -> bool:
        """Add `key` (generation `gen`, index `idx`); False when it is a repeat."""
        p = Present(gen, idx, key.open_us, key.end_us)
        for r in series.ranges:
            if r.holds(series.kind, p):
                r.count += 1
                return False
        open_ = [r for r in series.ranges if not r.merged and r.generation == gen]
        before = next((r for r in open_ if r.last == idx - 1), None)
        after = next((r for r in open_ if r.first == idx + 1), None)
        if before is not None:
            before.last, before.to_us = idx, max(before.to_us, key.end_us)
            before.count += 1
            if after is not None:  # the key joins two records
                before.last, before.to_us = after.last, max(before.to_us, after.to_us)
                before.count += after.count
                series.ranges.remove(after)
        elif after is not None:
            after.first, after.from_us = idx, min(after.from_us, key.open_us)
            after.count += 1
        else:
            series.ranges.append(
                _Range(gen, idx, idx, key.open_us, key.end_us, reason, self._now(), 1)
            )
        series.ranges.sort(key=lambda r: (r.from_us, r.to_us))
        while len(series.ranges) > MAX_RANGES_PER_SERIES:  # the oldest two become one span
            a, b = series.ranges[0], series.ranges[1]
            series.ranges[0:2] = [
                _Range(a.generation, min(a.first, b.first), max(a.last, b.last),
                       min(a.from_us, b.from_us), max(a.to_us, b.to_us), a.reason,
                       min(a.first_seen_us, b.first_seen_us), a.count + b.count, merged=True)
            ]  # fmt: skip
        return True

    def _changed(self, series_key: tuple[str, str]) -> None:
        self._revisions[series_key] = self._revisions.get(series_key, 0) + 1
        self._dirty = True
        self._schedule()

    # -- the read path ----------------------------------------------------------------------

    def revision(self, symbol: str, spec_hash: str) -> int:
        """Changes whenever the series' records change (a render cache keys on it)."""
        return self._revisions.get((symbol, spec_hash), 0)

    def holes_for(
        self, symbol: str, spec_hash: str, from_us: int, to_us: int, present: Iterable[Present]
    ) -> list[tuple[int, int]]:
        """The series' spans inside `[from_us, to_us)`, minus the bars in `present` (those a
        response serves), oldest first, overlapping and touching spans joined."""
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
        """Every record, for the heal path (the rebuild executor, a no-op today)."""
        return [
            HoleRange(sym, h, s.kind, s.bar_param, r.generation, r.first, r.last, r.from_us,
                      r.to_us, r.reason, r.first_seen_us, r.count, r.merged)
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
        while self._dirty:
            self._dirty = False
            data = self._dump()
            try:
                await run_in_thread(_write_atomic, self._path, data)
            except Exception as exc:  # kept dirty: the next change or `flush` writes it again
                self._dirty = True
                _log().error("bars_write_holes_journal_write_failed", error=type(exc).__name__)
                return

    async def flush(self) -> None:
        """Write the journal now if it changed since its last write (the stop path)."""
        task = self._task
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        if self._dirty:
            self._task = spawn(self._flush_loop(), name="bars-write-holes-journal")
            await self._task

    def _dump(self) -> bytes:
        series = [
            {"symbol": sym, "spec_hash": h, "kind": s.kind, "bar_param": s.bar_param,
             "ranges": [[r.generation, r.first, r.last, r.from_us, r.to_us, r.reason,
                         r.first_seen_us, r.count, r.merged] for r in s.ranges]}
            for (sym, h), s in sorted(self._series.items())
        ]  # fmt: skip
        return orjson.dumps({"v": JOURNAL_VERSION, "series": series})

    async def load(self) -> str:
        """Read the journal before the writer starts: `"ok"`, `"missing"` or the reason the file
        was discarded (counted, logged; the ledger then starts empty). Never raises."""
        loaded, reason = await run_in_thread(_read_journal, self._path)
        if loaded is None:
            if reason != "missing":
                bars_blob_discarded_total.labels(reason="write_holes").inc()
                _log().error("bars_write_holes_journal_discarded", reason=reason)
            return reason
        for series_key, series in loaded.items():
            self._series[series_key] = series
            self._revisions[series_key] = self._revisions.get(series_key, 0) + 1
        return reason


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


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
    for gen, first, last, from_us, to_us, reason, seen, count, merged in rows:
        if reason not in HOLE_REASONS or type(merged) is not bool:
            raise ValueError("reason or merged")
        r = _Range(_int(gen), _int(first), _int(last), _int(from_us), _int(to_us), reason,
                   _int(seen), _int(count, 1), merged)  # fmt: skip
        if r.last < r.first or r.to_us <= r.from_us:
            raise ValueError("empty range")
        ranges.append(r)
    return _Series(kind, param, sorted(ranges, key=lambda r: (r.from_us, r.to_us)))


def _subtract(kind: str, ranges: list[_Range], p: Present) -> list[_Range]:
    out: list[_Range] = []
    for r in ranges:
        out += r.without(kind, p) if r.holds(kind, p) else [r]
    return out


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
