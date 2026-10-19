"""Builders shared by the `ReplaySource` tests (E26-T02).

`MintingTier` and `MintingGaps` hand the merge fresh, weakly referenced rows and count how many
are still alive, so a test can say exactly what a source keeps: the stored rows themselves are
never the ones the merge holds (a slotted `RecordedEvent` cannot be weakly referenced, its
plain subclass can).
"""

from __future__ import annotations

import asyncio
import weakref
from collections.abc import Collection, Iterable

from candleviewer.replay import ReadAheadConfig, ReplayItem, ReplaySource
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.repositories.recorded import RecordedEvent, RecordedGap
from candleviewer.storage.testing import StaticGapReader
from tests.unit.replay._events import SECOND, T0, BoundedTier, trade

#: Four batches of 64 events fit 256 events (a queue of two slots), and 1 MiB is roomy: events
#: bind before bytes. Reads are 1 s windows, and every storage await and close is bounded by 2 s,
#: so a mutant that never ends or never stops fails a test within seconds.
SMALL = ReadAheadConfig(
    window_us=SECOND,
    readahead_events=256,
    batch_events=64,
    readahead_bytes=1 << 20,
    io_timeout_s=2.0,
)
#: A source that never ends or never answers fails the test after this, it does not hang it.
BOUND_S = 10.0
#: More items than any test stores: a source that yields more is repeating itself, and an `async
#: for` that never suspends cannot be stopped by a timeout, so the helpers count.
MAX_ITEMS = 200_000


def many(count: int, *, symbol: str = "BTCUSDT") -> list[RecordedEvent]:
    """`count` trades 2 ms apart from the window start, in the default 60 s request."""
    return [trade(i * 2_000, trade_id=f"t{i:05}", symbol=symbol) for i in range(count)]


async def until_parked(source: ReplaySource, *, at_least: int) -> None:
    """Yield until the producer has filled the read-ahead and parked on the full queue: the
    buffer holds `at_least` events and has not changed for 20 scheduler turns."""
    last, quiet = -1, 0
    for _ in range(100_000):
        await asyncio.sleep(0)
        held = source.buffered_events
        quiet = quiet + 1 if held == last else 0
        last = held
        if held >= at_least and quiet >= 20:
            return
    raise AssertionError("the producer never filled the read-ahead buffer")


async def count_items(source: ReplaySource) -> int:
    """Iterate to the end keeping nothing: the consumer holds no row once this returns."""
    count = 0
    async with asyncio.timeout(BOUND_S):
        async for _ in source:
            count += 1
            assert count <= MAX_ITEMS, "the source yields more items than any test stores"
    return count


async def drain(source: ReplaySource) -> list[ReplayItem]:
    """Every item the source yields from here to its end."""
    got: list[ReplayItem] = []
    await drain_into(source, got)
    return got


async def drain_into(source: ReplaySource, got: list[ReplayItem]) -> None:
    """Like `drain`, but into `got`, which keeps what was yielded when the source raises."""
    async with asyncio.timeout(BOUND_S):
        async for item in source:
            got.append(item)
            assert len(got) <= MAX_ITEMS, "the source yields more items than any test stores"


async def pull(source: ReplaySource) -> ReplayItem:
    """The next item (or the error that ends the replay)."""
    async with asyncio.timeout(BOUND_S):
        return await anext(source)


class Minted(RecordedEvent):
    """A recorded event that can be weakly referenced (the slotted base cannot)."""


class MintingTier(BoundedTier):
    """A tier that serves fresh `Minted` copies of its rows, each remembered weakly."""

    def __init__(self, events: Iterable[RecordedEvent] = ()) -> None:
        super().__init__(events)
        self._minted: list[weakref.ref[Minted]] = []

    async def read(
        self, symbol: str, stream: StreamKind, rng: TimeRange, *, depth: int, limit: int
    ) -> list[RecordedEvent]:
        rows = await super().read(symbol, stream, rng, depth=depth, limit=limit)
        fresh = [Minted(r.ts_us, r.seq, r.symbol, r.stream, r.tiebreak, r.payload) for r in rows]
        self._minted += [weakref.ref(row) for row in fresh]
        return list(fresh)

    def alive(self, symbol: str | None = None) -> int:
        """Rows served and still referenced, of `symbol` or of every symbol."""
        rows = (ref() for ref in self._minted)
        return sum(1 for row in rows if row is not None and symbol in (None, row.symbol))


class Cause(str):
    """A gap cause that can be weakly referenced; the markers built from it hold it."""


class MintingGaps(StaticGapReader):
    """A gap reader serving fresh rows whose `Cause` is remembered weakly, so a test can count
    the markers still alive: a marker keeps the object it was built from."""

    def __init__(self, rows: Iterable[tuple[str, int, int]]) -> None:
        super().__init__()
        self._rows = list(rows)
        self._causes: list[tuple[str, weakref.ref[Cause]]] = []

    async def recording_gaps(
        self, symbol: str, rng: TimeRange, *, streams: Collection[StreamKind], limit: int
    ) -> list[RecordedGap]:
        out: list[RecordedGap] = []
        if StreamKind.TRADES not in streams:  # every row it serves is a trades gap
            return out
        for owner, start_us, end_us in self._rows:
            start, end = T0 + start_us, T0 + end_us
            if owner == symbol and start < rng.end_us and end > rng.start_us:
                cause = Cause("ws_disconnect")
                self._causes.append((owner, weakref.ref(cause)))
                out.append(RecordedGap(owner, StreamKind.TRADES, start, end, cause))
        return out[:limit]

    def alive(self, symbol: str) -> int:
        return sum(1 for owner, ref in self._causes if owner == symbol and ref() is not None)
