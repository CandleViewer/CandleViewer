"""One recorded event per book update, before the clock (E26-T03, 24 Sec.13.7).

The recorder stores one `orderbook_deltas` row per changed level (21 Sec.4.2), while a live
`BookDelta` carries every level of one `(symbol, depth, update_id)`. `RegroupedStream` wraps the
`ReplayStream` the clock reads and folds the rows of one update into one `RecordedEvent` whose
payload is a `RecordedBookUpdate`, so a clock step (`step_event`) is one book update and the
injector's ordinal counts re-emitted events. The rows of one update share `ts`, symbol and
`seq` (its `cross_seq`, else its `update_id`), so the read order puts them next to each other:
only the tiebreak's side and price tell them apart.

It reads one item ahead. Everything else passes through as is: `ReplayGap` markers, trades,
snapshots and every other stream. Consecutive rows form one update only when they agree on
everything but side, price and size; rows that disagree (corrupt data) form separate updates
with one `update_id`, which the replay book sees as a sequence mismatch, never as one silently
merged update. An update holds at most `4 * depth` rows, as long as any delta the live book
applies (`2 * depth` levels a side): a longer run of one update's rows is corrupt data, refused
(`ReplayEventRefused`) before another row is buffered, and the partial update is dropped. If
the wrapped stream fails while an update is being read, the failure is raised at once and the
partial update is dropped: an update is delivered whole or not at all. A cancelled read keeps
the rows read so far. `aclose()` closes the wrapped stream.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Self

from candleviewer.replay.errors import ReplayEventRefused
from candleviewer.replay.models import ReplayItem
from candleviewer.replay.playback import ReplayStream
from candleviewer.storage.repositories.recorded import (
    Level,
    RecordedBookDelta,
    RecordedBookUpdate,
    RecordedEvent,
)

#: What the rows of one update share: `(ts_us, seq, symbol)` and the payload's
#: `(depth, update_id, cross_seq, prev_update_id, ts_match)`.
type _Key = tuple[int, int, str, int, int, int | None, int | None, int | None]


def _delta(item: ReplayItem) -> tuple[RecordedEvent, RecordedBookDelta] | None:
    """`item` and its row if it is a recorded book-delta row, else `None`."""
    if isinstance(item, RecordedEvent):
        row = item.payload
        if isinstance(row, RecordedBookDelta):
            return item, row
    return None


def _key(event: RecordedEvent, row: RecordedBookDelta) -> _Key:
    return (
        event.ts_us,
        event.seq,
        event.symbol,
        row.depth,
        row.update_id,
        row.cross_seq,
        row.prev_update_id,
        row.ts_match,
    )


def _price(level: Level) -> Decimal:
    return level[0]


def _max_rows(depth: int) -> int:
    """The rows one update may hold: the live book applies a delta of up to `2 * depth` levels
    a side (`book/state.py` `BookState.apply`), as levels leave its window while others enter."""
    return 4 * depth


def _fold(head: RecordedEvent, rows: list[RecordedBookDelta]) -> RecordedEvent:
    """The update's rows as one event, levels best first: bids descending, asks ascending."""
    bids: list[Level] = []
    asks: list[Level] = []
    for row in rows:
        if row.side == "bid":
            bids.append((row.price, row.size))
        elif row.side == "ask":
            asks.append((row.price, row.size))
        else:  # the readers refuse it (`_BOOK_SIDES`); a row built past them is a bug
            raise ReplayEventRefused("a recorded orderbook_delta row has no book side")
    bids.sort(key=_price, reverse=True)
    asks.sort(key=_price)
    first = rows[0]
    update = RecordedBookUpdate(
        depth=first.depth,
        update_id=first.update_id,
        cross_seq=first.cross_seq,
        bids=tuple(bids),
        asks=tuple(asks),
        prev_update_id=first.prev_update_id,
        ts_match=first.ts_match,
    )
    tiebreak = (first.update_id, first.depth)
    return RecordedEvent(head.ts_us, head.seq, head.symbol, head.stream, tiebreak, update)


class RegroupedStream:
    """The `ReplayStream` the clock reads, with each book update's rows folded into one event
    (see module doc)."""

    def __init__(self, inner: ReplayStream) -> None:
        self._inner = inner
        self._head: RecordedEvent | None = None  # the first row of the update being read
        self._key: _Key | None = None
        self._rows: list[RecordedBookDelta] = []
        self._held: ReplayItem | None = None  # the item read after the update
        self._ended = False

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> ReplayItem:
        head = self._head
        if head is None:  # else a cancelled read left an update half read: go on with it
            item = await self._next()  # StopAsyncIteration at the end
            delta = _delta(item)
            if delta is None:
                return item
            head, row = delta
            self._head, self._key, self._rows = head, _key(head, row), [row]
        cap = _max_rows(self._rows[0].depth)
        while True:
            try:
                item = await self._next()
            except StopAsyncIteration:
                break
            except Exception:
                self._drop()  # never a partial update: the failure ends the replay here
                raise
            delta = _delta(item)
            if delta is None or _key(*delta) != self._key:
                self._held = item
                break
            if len(self._rows) >= cap:  # corrupt data: refused before it is buffered
                self._drop()
                raise ReplayEventRefused(
                    "a recorded orderbook_delta update has more rows than its depth allows"
                )
            self._rows.append(delta[1])
        rows = self._rows
        self._drop()
        return _fold(head, rows)

    async def aclose(self) -> None:
        self._drop()
        self._held, self._ended = None, True
        await self._inner.aclose()

    async def _next(self) -> ReplayItem:
        held = self._held
        if held is not None:
            self._held = None
            return held
        if self._ended:
            raise StopAsyncIteration
        try:
            return await anext(self._inner)
        except StopAsyncIteration:
            self._ended = True
            raise

    def _drop(self) -> None:
        self._head, self._key, self._rows = None, None, []
