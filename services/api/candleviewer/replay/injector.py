"""`ReplayInjector`: one replay session's recorded market events, re-emitted as the live event
types on the session's own bus namespace (E26-T03; 24 Sec.13.7 and Sec.2.9; 20 Sec.3.9).

It is the clock's `ReplaySink`. Each recorded trade becomes a `TradeEvent` published on
`replay-{session_id}.md.{symbol}.trade`; each book update (one `RegroupedStream` event) becomes a
`BookDelta` and each recorded snapshot a `BookSnapshot`, both handed to the session's replay-scoped
book through `ReplayBookHook` (the live book reads raw frames, not the bus, so the replay feeds
its own `BookEngine`s, which publish on `replay-{session_id}.md.{symbol}.book`). The namespace is
derived from the session id and nothing else, and no topic it publishes on can be a live one
(`bus.models`, C-2.11). Recorded fields keep their stored values; the derived ones follow the 24
Sec.13.7 table exactly, `source="replay"` first, so two replays of one session under the same
controls re-emit identical events (C-2.15).

**Refusals.** Anything else is refused with a typed error before any of it is published: a gap
marker, a stream whose derivations 24 Sec.13.7 does not list, a book row that was not regrouped,
a symbol outside the session, an event that does not fit the live model, or a price off the
session's pinned tick grid (`ReplayPriceOffGrid`, never rounded). The clock then stops with
`error`, and every event before it stays delivered. A session whose request names a stream the
replay does not re-emit, or a symbol with no pinned tick size, is refused at construction.

**Identity.** `event_id` hashes the session id, a generation and the event's ordinal (24 Sec.13.7):
the ordinal is the event's 0-based position among the session's re-emitted events from
`range_start`, and advances only once the event was handed on, so an event the clock delivers
again after a failure keeps its id. `restart(ordinal=...)` is the seek hook (E26-T04) and the
loop wrap: a new generation, so ids never repeat within a session. The injector remembers the
ordinal of the first event at or after the configured loop start, and `restart_loop()` resumes
there (US-RPL-008).

**Backpressure.** Awaiting the bus or the book is the clock's backpressure: nothing is dropped and
nothing is buffered here. The M12 rules keep `exchange.base` and `book` out of this module
(CONSTITUTION Sec.3): the composition root hands in the live event models (`LiveEventModels`) and
the book hook (`replay_wiring.py`).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal, Protocol
from uuid import UUID

from pydantic import ValidationError

from candleviewer.bus.bus import Bus
from candleviewer.bus.models import Topic, replay_env
from candleviewer.domain.events import MarketEvent
from candleviewer.domain.primitives import EventId
from candleviewer.replay.errors import (
    ReplayClockStateError,
    ReplayConfigInvalid,
    ReplayEventRefused,
    ReplayLoopStartUnknown,
    ReplayPriceOffGrid,
    ReplayRequestInvalid,
    ReplayTickSizeMissing,
)
from candleviewer.replay.models import ReplayRequest
from candleviewer.storage.models import StreamKind
from candleviewer.storage.repositories.recorded import (
    Level,
    RecordedBookDelta,
    RecordedBookSnapshot,
    RecordedBookUpdate,
    RecordedEvent,
    RecordedTrade,
)

#: The recorded streams the replay re-emits (24 Sec.13.7); the others wait for their derivations.
REEMITTED_STREAMS: Final = frozenset(
    {StreamKind.TRADES, StreamKind.ORDERBOOK_DELTA, StreamKind.ORDERBOOK_SNAPSHOT}
)
_MS_MASK: Final = (1 << 48) - 1
_MAX_GENERATION: Final = (1 << 32) - 1  # `generation` is hashed as 4 bytes
_ORDINALS: Final = 1 << 64  # and `ordinal` as 8
#: A snapshot's `reason`: the anchor a seek starts from, or any other recorded full refresh.
SnapshotReason = Literal["resync", "replay_seek"]
type _Fields = dict[str, object]


def replay_event_id(ts_us: int, session_id: UUID, generation: int, ordinal: int) -> EventId:
    """The re-emitted event's id (24 Sec.13.7): UUIDv7-shaped, laid out as
    `orderflow/bigtrade.py` `_event_id` lays out its ids, with the 48-bit millisecond of `ts_us`
    and then the first 80 bits of a BLAKE2b digest of the session, generation and ordinal, the
    version (7) and RFC 4122 variant bits overwritten."""
    digest = hashlib.blake2b(
        session_id.bytes + generation.to_bytes(4, "big") + ordinal.to_bytes(8, "big"),
        digest_size=16,
    ).digest()
    value = ((ts_us // 1000) & _MS_MASK) << 80 | int.from_bytes(digest[:10], "big")
    value = (value & ~(0xF << 76)) | (0x7 << 76)
    return EventId(UUID(int=(value & ~(0x3 << 62)) | (0x2 << 62)))


def price_ticks(price: Decimal, tick_size: Decimal, *, symbol: str, stream: StreamKind) -> int:
    """`price / tick_size`, which must be an exact integer (24 Sec.13.7): `price` is the recorded
    price as the readers convert the stored DOUBLE, `Decimal(repr(x))`. Off the grid, or not a
    number, it raises `ReplayPriceOffGrid`: never a rounded value."""
    try:
        ticks, rest = divmod(price, tick_size) if price.is_finite() else (None, None)
    except ArithmeticError:  # a quotient beyond the decimal context: not a grid price either
        ticks, rest = None, None
    if ticks is None or rest != 0:
        raise ReplayPriceOffGrid(symbol=symbol, stream=stream)
    return int(ticks)


@dataclass(frozen=True, slots=True)
class LiveEventModels:
    """The live market-event models the injector builds (`exchange.base.models` `TradeEvent`,
    `BookDelta`, `BookSnapshot`). M12 may not import M3 (CONSTITUTION Sec.3, `.importlinter`), so
    the composition root hands them in; each re-emitted event is validated against its model
    exactly as the live adapter's are (`model_validate`)."""

    trade: type[MarketEvent]
    book_delta: type[MarketEvent]
    book_snapshot: type[MarketEvent]


class ReplayBookHook(Protocol):
    """Where the injector hands book events: the session's replay-scoped `BookEngine`s
    (`replay_wiring.ReplayBooks`, 20 Sec.3.9), which publish what they apply on the session's
    own book topic. Awaiting is backpressure."""

    async def apply(self, event: MarketEvent) -> None:
        """Apply one re-emitted `BookSnapshot` or `BookDelta`."""
        ...

    async def reset(self, reason: str) -> None:
        """The stream jumped (a seek or a loop restart): every replay book leaves LIVE and waits
        for its next recorded snapshot (or the seek anchor), never for the live feed; nothing it
        held before the jump is applied after it."""
        ...


class ReplayInjector:
    """The `ReplaySink` of one replay session (see module doc)."""

    def __init__(
        self,
        *,
        session_id: UUID,
        request: ReplayRequest,
        tick_sizes: Mapping[str, Decimal],
        bus: Bus,
        books: ReplayBookHook,
        models: LiveEventModels,
        loop_start_us: int | None = None,
    ) -> None:
        if not isinstance(session_id, UUID):
            raise ReplayConfigInvalid("a replay session id is a UUID")
        refused = sorted(s.value for s in request.streams if s not in REEMITTED_STREAMS)
        if refused:
            raise ReplayRequestInvalid(
                f"invalid replay request: streams {', '.join(refused)} are not re-emitted yet "
                "(24 Sec.13.7 lists no derivation for them)"
            )
        missing = [s for s in request.symbols if s not in tick_sizes]
        if missing:
            raise ReplayTickSizeMissing(symbols=missing)
        ticks = {s: tick_sizes[s] for s in request.symbols}
        if not all(isinstance(t, Decimal) and t.is_finite() and t > 0 for t in ticks.values()):
            raise ReplayConfigInvalid("a pinned tick size is a positive, finite Decimal")
        self._session, self._env = session_id, replay_env(session_id)
        self._ticks, self._bus, self._books, self._models = ticks, bus, books, models
        self._trades = {
            s: Topic(env=self._env, domain="md", symbol=s, detail="trade") for s in request.symbols
        }
        self._generation = 0
        self._next = 0  # the ordinal of the next event handed on
        self._prev_ts: int | None = None  # ts of the event at `_next - 1` in this generation
        self._loop_start = loop_start_us
        self._loop_ordinal: int | None = None
        self._busy = False

    @property
    def env(self) -> str:
        """The session's bus namespace, `replay-{session_id}`."""
        return self._env

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def next_ordinal(self) -> int:
        """The ordinal the next re-emitted event takes."""
        return self._next

    @property
    def loop_start_ordinal(self) -> int | None:
        """The ordinal of the first event at or after the loop start, once playback reached it."""
        return self._loop_ordinal

    async def deliver(self, event: RecordedEvent) -> None:
        """Re-emit `event` (the `ReplaySink`). Raises before anything of it is published."""
        await self._emit(event, "resync")

    async def deliver_seek_anchor(self, event: RecordedEvent) -> None:
        """E26-T04's hook: re-emit the snapshot a seek starts from, `reason="replay_seek"`. It
        takes the next ordinal like any event, so the seek calls `restart` first."""
        if not isinstance(getattr(event, "payload", None), RecordedBookSnapshot):
            raise ReplayEventRefused("a seek anchor is a recorded orderbook_snapshot")
        await self._emit(event, "replay_seek")

    def set_loop_start(self, ts_us: int | None) -> None:
        """Configure (or clear) the loop start. Its ordinal is learnt the next time playback
        reaches the first event at or after it: an event whose predecessor in the read order
        was delivered before the loop start, or the very first event of the session."""
        self._loop_start, self._loop_ordinal = ts_us, None

    async def restart(self, *, ordinal: int) -> None:
        """The seek hook (E26-T04) and the loop wrap: the stream continues with the event at
        `ordinal`, its 0-based position among the session's re-emitted events from
        `range_start`, under a new generation, so no id repeats. The replay books drop what they
        hold first (`ReplayBookHook.reset`). The caller repositions the clock to that event, on a
        new source wrapped in a `RegroupedStream`."""
        if self._busy:
            raise ReplayClockStateError("the injector is re-emitting an event")
        if not 0 <= ordinal < _ORDINALS:
            raise ReplayRequestInvalid("a replay ordinal is between 0 and 2**64 - 1")
        if self._generation >= _MAX_GENERATION:
            raise ReplayClockStateError("the replay session has restarted too often")
        await self._books.reset("replay_restart")
        self._generation += 1
        self._next, self._prev_ts = ordinal, None

    async def restart_loop(self) -> None:
        """US-RPL-008's wrap: `restart` at the loop start's ordinal. `ReplayLoopStartUnknown` if
        playback has not reached the loop start since it was configured."""
        ordinal = self._loop_ordinal
        if ordinal is None:
            raise ReplayLoopStartUnknown()
        await self.restart(ordinal=ordinal)

    # -- re-emission ---------------------------------------------------------------------------
    async def _emit(self, event: RecordedEvent, reason: SnapshotReason) -> None:
        if self._busy:
            raise ReplayClockStateError("the injector re-emits one event at a time")
        if not isinstance(event, RecordedEvent):
            raise ReplayEventRefused("only recorded market events are re-emitted, never a marker")
        payload, ordinal = event.payload, self._next
        if event.symbol not in self._ticks:
            raise ReplayEventRefused(f"a recorded {event.stream.value} event outside the session")
        self._busy = True
        try:
            if isinstance(payload, RecordedTrade):
                trade = self._build(self._models.trade, event, self._trade(event, payload, ordinal))
                await self._bus.publish(self._trades[event.symbol], trade)
            elif isinstance(payload, RecordedBookUpdate):
                fields = self._delta(event, payload, ordinal)
                await self._books.apply(self._build(self._models.book_delta, event, fields))
            elif isinstance(payload, RecordedBookSnapshot):
                fields = self._snapshot(event, payload, ordinal, reason)
                await self._books.apply(self._build(self._models.book_snapshot, event, fields))
            elif isinstance(payload, RecordedBookDelta):
                raise ReplayEventRefused("an orderbook_delta row is re-emitted only regrouped")
            else:
                raise ReplayEventRefused(f"the replay does not re-emit {event.stream.value} yet")
        finally:
            self._busy = False
        self._handed_on(event.ts_us, ordinal)

    def _handed_on(self, ts_us: int, ordinal: int) -> None:
        start = self._loop_start
        if (
            start is not None
            and self._loop_ordinal is None
            and ts_us >= start
            and (ordinal == 0 or (self._prev_ts is not None and self._prev_ts < start))
        ):
            self._loop_ordinal = ordinal
        self._prev_ts, self._next = ts_us, ordinal + 1

    def _envelope(self, event: RecordedEvent, ordinal: int) -> _Fields:
        return {
            "event_id": replay_event_id(event.ts_us, self._session, self._generation, ordinal),
            "ts_event": event.ts_us,
            "ts_ingest": event.ts_us,  # replay reads no wall clock
            "source": "replay",
            "symbol": event.symbol,
        }

    def _ticks_of(self, price: Decimal, event: RecordedEvent) -> int:
        return price_ticks(
            price, self._ticks[event.symbol], symbol=event.symbol, stream=event.stream
        )

    def _levels(self, levels: tuple[Level, ...], event: RecordedEvent) -> tuple[_Fields, ...]:
        return tuple(
            {"price": px, "qty": qty, "price_ticks": self._ticks_of(px, event)}
            for px, qty in levels
        )

    def _trade(self, event: RecordedEvent, trade: RecordedTrade, ordinal: int) -> _Fields:
        return self._envelope(event, ordinal) | {
            "trade_id": trade.trade_id,
            "price": trade.price,
            "qty": trade.size,
            "side": trade.side,
            "is_block_trade": trade.is_block is True,  # NULL: written before the recorder set it
            "price_ticks": self._ticks_of(trade.price, event),
            "notional": trade.price * trade.size,  # as the live tape derives it
            "seq": event.seq,  # the recorded ingest counter (NULL reads 0)
        }

    def _delta(self, event: RecordedEvent, update: RecordedBookUpdate, ordinal: int) -> _Fields:
        uid = update.update_id
        prev = update.prev_update_id
        return self._envelope(event, ordinal) | {
            "depth": update.depth,
            "bids": self._levels(update.bids, event),
            "asks": self._levels(update.asks, event),
            "update_id": uid,
            "prev_update_id": uid - 1 if prev is None else prev,  # as the live adapter emits it
            "cross_seq": uid if update.cross_seq is None else update.cross_seq,
            "ts_match": event.ts_us if update.ts_match is None else update.ts_match,
        }

    def _snapshot(
        self,
        event: RecordedEvent,
        snap: RecordedBookSnapshot,
        ordinal: int,
        reason: SnapshotReason,
    ) -> _Fields:
        uid = snap.update_id
        return self._envelope(event, ordinal) | {
            "depth": snap.depth,
            "bids": self._levels(snap.bids, event),
            "asks": self._levels(snap.asks, event),
            "update_id": uid,
            "cross_seq": uid if snap.cross_seq is None else snap.cross_seq,
            "ts_match": event.ts_us if snap.ts_match is None else snap.ts_match,
            "reason": reason,
        }

    @staticmethod
    def _build(model: type[MarketEvent], event: RecordedEvent, fields: _Fields) -> MarketEvent:
        """`fields` as a validated live event; a misfit is refused naming the fields at fault
        (raised after the handler, so no exception context keeps the recorded values)."""
        try:
            return model.model_validate(fields)
        except ValidationError as exc:
            where = sorted({".".join(str(p) for p in err["loc"]) for err in exc.errors()})
        raise ReplayEventRefused(
            f"a recorded {event.stream.value} event does not fit {model.__name__}: "
            f"{', '.join(where)}"
        )
