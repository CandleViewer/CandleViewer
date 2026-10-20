"""Composition of the replay read path (E26-T02).

Turns settings into the `ReplayTiers` a `ReplaySource` reads through and the `ReadAheadConfig`
that bounds it. QuestDB is read over one lazily opened, lock-serialised PGWire connection, and
Parquet through the `CV_PARQUET_ROOT` registry. The Parquet reader is also the manifest coverage
that `source_tier="auto"` routes on (never the roll-off watermark), and gaps come from
`recording_gaps`. Each reader's deadline sits below the merge's, so a slow read fails typed in
its tier first. Only on the `real` storage backend: the replay session service (E26-T01/T05)
builds the wiring once per process, so every session shares the cold reader's verified-file
cache and scan slots, opens one `ReplaySource` per session over `ReplayWiring.tiers`, and calls
`ReplayWiring.aclose()` when the app stops, which closes the QuestDB connection and the cold
reader's scan pool.

E26-T03 adds the injection side (20 Sec.3.9): `build_replay_injector` wires one session's
`ReplayInjector` to the bus, the live event models (M12 may not import M3) and `ReplayBooks`,
the session's replay-scoped book engines, the hook the injector feeds book events through.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from candleviewer.book.resync import BookEngine
from candleviewer.bus.bus import Bus
from candleviewer.bus.models import Topic, replay_env
from candleviewer.domain.events import MarketEvent
from candleviewer.exchange.base.models import BookDelta, BookSnapshot, TradeEvent
from candleviewer.replay import (
    LiveEventModels,
    ReadAheadConfig,
    ReplayEventRefused,
    ReplayInjector,
    ReplayRequest,
    ReplayTiers,
)
from candleviewer.settings import QUESTDB_PG_DEFAULT_PORT, Settings
from candleviewer.storage.cold.layout import DatasetRegistry
from candleviewer.storage.cold.recorded_reader import ParquetRecordedReader
from candleviewer.storage.questdb.recorded_reader import QuestDbRecordedReader
from candleviewer.storage.questdb.wiring import LazyPgWire
from candleviewer.storage.repositories.recorded import RecordingGapReader


def readahead_config(settings: Settings) -> ReadAheadConfig:
    """`ReadAheadConfig` from `CV_REPLAY_READAHEAD_EVENTS`, `CV_REPLAY_READAHEAD_BYTES` and
    `CV_REPLAY_MEMORY_CEILING_BYTES`."""
    return ReadAheadConfig(
        readahead_events=settings.replay_readahead_events,
        readahead_bytes=settings.replay_readahead_bytes,
        memory_ceiling_bytes=settings.replay_memory_ceiling_bytes,
    )


@dataclass(frozen=True, slots=True)
class ReplayWiring:
    """The tiers a `ReplaySource` reads through, and what they hold open: one QuestDB
    connection and the cold reader's scan pool, both released by `aclose()`."""

    tiers: ReplayTiers
    pg: LazyPgWire
    cold: ParquetRecordedReader

    async def aclose(self) -> None:
        """At app stop: the cold reader refuses new scans and its queued ones fail typed (a
        running scan finishes, or is stopped by its read), then the QuestDB connection closes."""
        self.cold.shutdown()
        await self.pg.close()


def build_replay_wiring(settings: Settings, gaps: RecordingGapReader | None) -> ReplayWiring | None:
    """The real storage ports, or `None` off the `real` backend or without a gap reader."""
    if settings.storage_backend != "real" or gaps is None:
        return None
    host, _, port = settings.questdb_pg.partition(":")
    pg = LazyPgWire(
        host,
        int(port or QUESTDB_PG_DEFAULT_PORT),
        settings.questdb_pg_user,
        settings.questdb_pg_password.get_secret_value(),
        name="replay",
    )
    cold = ParquetRecordedReader(DatasetRegistry(settings.parquet_root))
    tiers = ReplayTiers(hot=QuestDbRecordedReader(pg), cold=cold, coverage=cold, gaps=gaps)
    return ReplayWiring(tiers=tiers, pg=pg, cold=cold)


#: The live market-event models every replay re-emits (24 Sec.13.7).
LIVE_EVENT_MODELS = LiveEventModels(
    trade=TradeEvent, book_delta=BookDelta, book_snapshot=BookSnapshot
)


class ReplayBooks:
    """One session's replay-scoped `BookEngine`s (20 Sec.3.9): the `ReplayBookHook` its injector
    feeds. One engine per (symbol, depth), built as `orderbook_wiring.BookStream` builds a live
    one, publishing what it applies on `replay-{session_id}.md.{symbol}.book`. Its wiring makes
    the unchanged engine replay-safe:

    - its resubscribe never touches the live feed: after a gap the book holds the deltas back
      and waits for the next recorded snapshot (24 Sec.13.7);
    - a recorded snapshot is a full refresh: the engine re-enters `snapshot_pending`, dropping
      what it holds and buffers (the snapshot supersedes it in the read order), and rebuilds from
      it. On its own the engine takes a snapshot while LIVE for a server reset and waits for a
      fresh one, which a recording never sends;
    - its clock is the replay time of the event it applies, never the wall clock (RP-T12)."""

    def __init__(self, bus: Bus, session_id: UUID) -> None:
        self._bus, self._env = bus, replay_env(session_id)
        self._engines: dict[tuple[str, int], BookEngine] = {}
        self._now_us = 0

    def engine(self, symbol: str, depth: int) -> BookEngine | None:
        """The (symbol, depth) book, once a book event of it arrived."""
        return self._engines.get((symbol, depth))

    async def apply(self, event: MarketEvent) -> None:
        if not isinstance(event, BookSnapshot | BookDelta) or event.source != "replay":
            raise ReplayEventRefused("a replay book applies re-emitted book events only")
        self._now_us = event.ts_event
        engine = self._engines.get((event.symbol, event.depth))
        if engine is None:
            engine = await self._open(event.symbol, event.depth)
        if isinstance(event, BookSnapshot):
            await engine.request_snapshot()  # a recorded full refresh: rebuild from it
        await engine.on_event(event)

    async def reset(self, reason: str, *, symbol: str | None = None) -> None:
        """Every LIVE book, or only `symbol`'s, leaves LIVE (its consumers are told why); a book
        already waiting for a snapshot keeps waiting, and the deltas it holds die with that
        snapshot."""
        for (book_symbol, _depth), engine in self._engines.items():
            if symbol is None or book_symbol == symbol:
                await engine.invalidate(reason)  # a no-op unless LIVE

    async def _open(self, symbol: str, depth: int) -> BookEngine:
        topic = Topic(env=self._env, domain="md", symbol=symbol, detail="book")

        async def publish(obj: object) -> None:
            await self._bus.publish(topic, obj)

        async def resubscribe() -> None:
            """A gap waits for the next recorded snapshot: never the live feed."""

        engine = BookEngine(
            symbol=symbol, depth=depth, publish=publish, resubscribe=resubscribe, now_us=self._now
        )
        self._engines[symbol, depth] = engine
        await engine.start()
        return engine

    def _now(self) -> int:
        return self._now_us


def build_replay_injector(
    *,
    session_id: UUID,
    request: ReplayRequest,
    tick_sizes: Mapping[str, Decimal],
    bus: Bus,
    loop_start_us: int | None = None,
) -> ReplayInjector:
    """One session's injector over its own `ReplayBooks`, both in the session's namespace.
    `tick_sizes` is what the session pinned from the instrument-info cache at creation."""
    return ReplayInjector(
        session_id=session_id,
        request=request,
        tick_sizes=tick_sizes,
        bus=bus,
        books=ReplayBooks(bus, session_id),
        models=LIVE_EVENT_MODELS,
        loop_start_us=loop_start_us,
    )
