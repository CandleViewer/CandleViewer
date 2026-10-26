"""Periodic book seek anchors (#2223, 24-internal-schemas.md §13.7, ADR-0035 proposed).

Every `interval_s` (`CV_RECORDER_SNAPSHOT_INTERVAL_S`, default 60 s, at any book depth) the
recorder writes the full maintained book of each recorded symbol as an `orderbook_snapshot` row
(`source='synthetic'`, 21-database-schema.md §4.3), so a seek finds an anchor no more than one
interval plus `STAMP_MARGIN_US` (5 s) before its target (E26-K01): a quiet book is stamped up to
the margin before its slot. A symbol's first LIVE book in this session is anchored at
the first tick that sees it, not a whole interval later.

* Same path as the deltas: `StreamWriter.on_book_anchor` queues the row on the
  `orderbook_snapshots` lane. An anchor never spends the WAL budget the deltas need: it is shed
  while the lane spills, and while the disk gate drops the symbol.
* Source: an injected `AnchorBooks`. The recorder may not import `book` or `ingestion`
  (CONSTITUTION §3), so the composition root adapts the ingestion `BookStream`; no new edge.
  A LIVE book is anchored however long it has been quiet: the exchange sends nothing while a
  book does not change, and the feed watchdog takes a dead feed out of LIVE.
* Stamp (`anchor_ts`): the book holds every delta up to its last applied event, so the anchor is
  stamped after that event and no later than any delta it lacks: a seek from it re-applies
  exactly the deltas after it, and a quiet book's anchor stays inside the replay's lookback.
* Owner: no task of its own. The recorder runtime's supervised tick calls `tick()` once a
  second under its step timeout; slots are a fixed grid of the injected monotonic clock.
* A skip loses no data (the deltas are still recorded), so it is not a `DataGap`: a seek falls
  back to the previous anchor. Each skip is logged and counted in
  `recorder_anchor_skipped_total{reason}`; a resync's own gap and anchor, or a writer drop's
  `backpressure_drop` gap, already mark what the deltas lack.
* Plain code, never a statechart (C-2.20).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Final, Literal, Protocol

import structlog

from candleviewer.recorder.metrics import recorder_anchor_skipped_total
from candleviewer.recorder.writer import AnchorShed, BookSnapshotLike

#: Why the source has no anchor for a symbol (`BookStream.anchor`).
NoAnchor = Literal["no_book", "not_live"]
#: How far a quiet book's anchor is stamped before the slot's wall-clock time: the bound on a
#: frame still in flight (network, dispatch lane) plus the local clock's lead on the exchange's
#: (its default receive window). A delta the book lacks was stamped by the exchange after it.
STAMP_MARGIN_US: Final = 5_000_000
_MS_US: Final = 1_000


def logger() -> structlog.stdlib.BoundLogger:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)  # type: ignore[no-any-return]  # structlog returns Any


def anchor_ts(last_applied_us: int, slot_wall_us: int) -> int:
    """The anchor's `ts` (UTC µs): strictly after the book's last applied event (a seek never
    re-delivers a delta the anchor holds) and, for a quiet book, the slot less
    `STAMP_MARGIN_US`, so it stays within one interval of the slot. Exchange stamps are whole
    milliseconds, so the anchor is moved off one: its `(ts, symbol, depth)` key can never equal
    an exchange snapshot's, and it stays before the next delta, assuming the exchange never pushes
    two book frames in the same millisecond (its push cadence is 10 to 200 ms); if it did, a
    seek would see a sequence gap at the second and resync, never apply a wrong book."""
    ts = max(last_applied_us + 1, slot_wall_us - STAMP_MARGIN_US)
    return ts + 1 if ts % _MS_US == 0 else ts


class AnchorBooks(Protocol):
    """The maintained book of `symbol` at its active depth, stamped with its last applied
    event, or why there is none. Synchronous and cheap: one copy of one book."""

    def anchor(self, symbol: str) -> BookSnapshotLike | NoAnchor: ...


class AnchorSink(Protocol):
    """The `StreamWriter` surface used: its effective set and its anchor admission."""

    def recorded(self) -> frozenset[str]: ...

    async def on_book_anchor(self, ev: BookSnapshotLike, *, at_us: int) -> AnchorShed | None: ...


class SnapshotAnchors:
    def __init__(
        self,
        books: AnchorBooks,
        sink: AnchorSink,
        *,
        interval_s: float,
        clock: Callable[[], float],
        wall_us: Callable[[], int],
    ) -> None:
        """`clock` is monotonic seconds (the grid), `wall_us` UTC epoch µs (the stamp)."""
        if not 0 < interval_s < math.inf:
            raise ValueError("interval_s must be positive and finite")
        self._books, self._sink = books, sink
        self._interval, self._clock, self._wall_us = interval_s, clock, wall_us
        self._next_at: float | None = None
        #: Symbols anchored in this session; one LIVE for the first time is anchored at once.
        self._anchored: set[str] = set()

    async def tick(self) -> None:
        """On a due slot anchor every recorded symbol; otherwise anchor only the symbols with
        no anchor yet whose book is LIVE (quietly: a book not yet LIVE is not a skip)."""
        now, symbols = self._clock(), sorted(self._sink.recorded())
        self._anchored.intersection_update(symbols)  # a re-added symbol is new again
        if self._next_at is None:
            self._next_at = now + self._interval
        elif now >= self._next_at:
            missed = int((now - self._next_at) // self._interval)
            self._next_at += (missed + 1) * self._interval
            if missed and symbols:
                recorder_anchor_skipped_total.labels(reason="late").inc(missed * len(symbols))
                logger().warning("recorder_anchor_late", missed_slots=missed, symbols=len(symbols))
            await self._slot(symbols)
            return
        for symbol in symbols:
            if symbol not in self._anchored:
                await self._anchor(symbol, self._wall_us(), quiet=True)

    async def _slot(self, symbols: list[str]) -> None:
        """One slot. A cut (the runtime's step timeout) counts every symbol it did not finish."""
        wall, done = self._wall_us(), 0
        try:
            for symbol in symbols:
                await self._anchor(symbol, wall, quiet=False)
                done += 1
        finally:
            if done < len(symbols):
                recorder_anchor_skipped_total.labels(reason="timeout").inc(len(symbols) - done)
                logger().warning("recorder_anchor_skipped", reason="timeout",
                                 symbols=len(symbols) - done)  # fmt: skip

    async def _anchor(self, symbol: str, wall: int, *, quiet: bool) -> None:
        try:
            book = self._books.anchor(symbol)
        except Exception as exc:  # an adapter bug never stops the other symbols' anchors
            self._skip(symbol, "error", type(exc).__name__, quiet=quiet)
            return
        if isinstance(book, str):
            self._skip(symbol, book, quiet=quiet)
            return
        try:
            shed = await self._sink.on_book_anchor(book, at_us=anchor_ts(book.ts_event, wall))
        except Exception as exc:  # never a CancelledError: the runtime's cancel goes through
            self._skip(symbol, "error", type(exc).__name__, quiet=quiet)
            return
        if shed is not None:
            self._skip(symbol, shed, quiet=quiet)
        else:
            self._anchored.add(symbol)

    @staticmethod
    def _skip(symbol: str, reason: str, error: str | None = None, *, quiet: bool) -> None:
        """Count and log a slot's skip. Between slots (`quiet`) a symbol not yet anchored is
        only retried, every tick: the next slot counts whatever still stops it."""
        if quiet:
            return
        recorder_anchor_skipped_total.labels(reason=reason).inc()
        extra = {} if error is None else {"error": error}
        logger().warning("recorder_anchor_skipped", symbol=symbol, reason=reason, **extra)
