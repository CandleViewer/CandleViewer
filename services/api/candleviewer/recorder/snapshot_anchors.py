"""Periodic book seek anchors (#2223, 24-internal-schemas.md §13.7, ADR-0035 proposed).

Every `interval_s` (`CV_RECORDER_SNAPSHOT_INTERVAL_S`, default 60 s, at any book depth) the
recorder writes the full maintained book of each recorded symbol as an `orderbook_snapshot` row,
so a seek finds an anchor no more than one interval before its target (E26-K01).

* Same path as the deltas: `StreamWriter.on_book_anchor` admits the row into the
  `orderbook_snapshots` lane, so it rides the writer's ladder (bounded queue, then the WAL, then
  a `backpressure_drop` gap, C-2.18). Admission never awaits I/O except the writer's own
  bounded spill drain.
* Source: an injected `AnchorBooks`. The recorder may not import `book` or `ingestion`
  (CONSTITUTION §3), so the composition root adapts the ingestion `BookStream`; no new edge.
* Owner: no task of its own. The recorder runtime's supervised tick calls `tick()` once a
  second under its step timeout; the cadence is read from the injected monotonic clock on a
  fixed grid, so a late tick never bunches anchors.
* A book that is missing, not LIVE or stale, a source or admit that raises, and a slot a stalled
  loop missed are skipped. No data is lost (the deltas are still recorded), so a skip is not a
  `DataGap`: a seek falls back to the previous anchor. Each skip is logged and counted in
  `recorder_anchor_skipped_total{reason}`. A resync's own gap and anchor, or a writer drop's
  `backpressure_drop` gap, already mark what the deltas lack.
* Plain code, never a statechart (C-2.20).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Final, Literal, Protocol

import structlog

from candleviewer.recorder.metrics import recorder_anchor_skipped_total
from candleviewer.recorder.writer import BookSnapshotLike

#: Why the source has no anchor for a symbol (`BookStream.anchor`).
NoAnchor = Literal["no_book", "not_live", "stale"]
#: The default cadence (24 §13.1 `RecordingPolicy.snapshot_interval_s`, `RecorderConfig`).
DEFAULT_INTERVAL_S: Final = 60


def logger() -> structlog.stdlib.BoundLogger:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)  # type: ignore[no-any-return]  # structlog returns Any


class AnchorBooks(Protocol):
    """The maintained book of `symbol` at its active depth, stamped with its last applied
    event, or why there is none. Synchronous and cheap: one copy of one book."""

    def anchor(self, symbol: str) -> BookSnapshotLike | NoAnchor: ...


class AnchorSink(Protocol):
    """The `StreamWriter` surface used: its effective set and its anchor admission."""

    def recorded(self) -> frozenset[str]: ...

    async def on_book_anchor(self, ev: BookSnapshotLike) -> None: ...


class SnapshotAnchors:
    def __init__(
        self,
        books: AnchorBooks,
        sink: AnchorSink,
        *,
        interval_s: float,
        clock: Callable[[], float],
    ) -> None:
        """`clock` is monotonic seconds. The first `tick()` arms the grid: the first anchor is
        one interval later (a subscribe writes its own snapshot, so a new book is anchored)."""
        if not 0 < interval_s < math.inf:
            raise ValueError("interval_s must be positive and finite")
        self._books, self._sink = books, sink
        self._interval, self._clock = interval_s, clock
        self._next_at: float | None = None

    async def tick(self) -> None:
        """Anchor every recorded symbol once the slot is due; else do nothing."""
        now = self._clock()
        if self._next_at is None:
            self._next_at = now + self._interval
            return
        if now < self._next_at:
            return
        missed = int((now - self._next_at) // self._interval)
        self._next_at += (missed + 1) * self._interval
        symbols = sorted(self._sink.recorded())
        if missed and symbols:
            recorder_anchor_skipped_total.labels(reason="late").inc(missed * len(symbols))
            logger().warning("recorder_anchor_late", missed_slots=missed, symbols=len(symbols))
        for symbol in symbols:
            await self._anchor(symbol)

    async def _anchor(self, symbol: str) -> None:
        try:
            book = self._books.anchor(symbol)
        except Exception as exc:  # an adapter bug never stops the other symbols' anchors
            self._skip(symbol, "error", type(exc).__name__)
            return
        if isinstance(book, str):
            self._skip(symbol, book)
            return
        try:
            await self._sink.on_book_anchor(book)
        except Exception as exc:  # never a CancelledError: the runtime's cancel goes through
            self._skip(symbol, "error", type(exc).__name__)

    @staticmethod
    def _skip(symbol: str, reason: str, error: str | None = None) -> None:
        recorder_anchor_skipped_total.labels(reason=reason).inc()
        extra = {} if error is None else {"error": error}
        logger().warning("recorder_anchor_skipped", symbol=symbol, reason=reason, **extra)
