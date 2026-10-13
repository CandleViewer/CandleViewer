"""Builders shared by the replay unit tests (E26-T02).

Time is given as integer microsecond offsets from `T0` (2026-10-01 00:00 UTC) so tests read as
arithmetic on the replay window; every builder returns the storage-side `RecordedEvent` the
in-memory tiers serve.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from candleviewer.replay import ReplayItem, ReplayRequest, ReplayTiers, SourceTier
from candleviewer.replay.merge import RecordedMerge
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.repositories.recorded import (
    ArchiveCoverage,
    RecordedBookDelta,
    RecordedBookSnapshot,
    RecordedEvent,
    RecordedStreamReader,
    RecordedTicker,
    RecordedTrade,
)
from candleviewer.storage.testing import (
    InMemoryRecordedTier,
    StaticArchiveCoverage,
    StaticGapReader,
)

SYM = "BTCUSDT"
EPOCH = datetime(2026, 10, 1, tzinfo=UTC)
T0 = (EPOCH - datetime(1970, 1, 1, tzinfo=UTC)) // timedelta(microseconds=1)
SECOND = 1_000_000
#: Large enough that no default read is ever capped.
ROOMY = 1 << 30


def at(offset_us: int) -> datetime:
    return EPOCH + timedelta(microseconds=offset_us)


def trade(
    offset_us: int, *, seq: int = 0, trade_id: str | None = None, symbol: str = SYM
) -> RecordedEvent:
    tid = trade_id or f"t{offset_us}-{seq}"
    payload = RecordedTrade("buy", Decimal("100.5"), Decimal("0.01"), tid, None)
    return RecordedEvent(T0 + offset_us, seq, symbol, StreamKind.TRADES, (tid,), payload)


def delta(
    offset_us: int,
    *,
    update_id: int = 1,
    cross_seq: int | None = None,
    side: str = "bid",
    price: str = "100",
    depth: int = 200,
    symbol: str = SYM,
) -> RecordedEvent:
    px = Decimal(price)
    payload = RecordedBookDelta(depth, side, px, Decimal(1), update_id, cross_seq)
    seq = update_id if cross_seq is None else cross_seq
    key = (update_id, depth, side, px)
    return RecordedEvent(T0 + offset_us, seq, symbol, StreamKind.ORDERBOOK_DELTA, key, payload)


def snapshot(
    offset_us: int, *, update_id: int = 1, depth: int = 200, symbol: str = SYM
) -> RecordedEvent:
    level = (Decimal("100"), Decimal("1"))
    payload = RecordedBookSnapshot(depth, update_id, None, (level,), (level,))
    stream = StreamKind.ORDERBOOK_SNAPSHOT
    return RecordedEvent(T0 + offset_us, update_id, symbol, stream, (update_id, depth, -1), payload)


def ticker(offset_us: int, *, symbol: str = SYM) -> RecordedEvent:
    payload = RecordedTicker(Decimal("100"), None, None, None, None, None, None, None, None)
    return RecordedEvent(T0 + offset_us, 0, symbol, StreamKind.TICKERS, (), payload)


def request(
    *,
    start_us: int = 0,
    end_us: int = 60 * SECOND,
    symbols: tuple[str, ...] = (SYM,),
    streams: tuple[StreamKind, ...] = (StreamKind.TRADES,),
    depth: int = 200,
    tier: SourceTier = "auto",
) -> ReplayRequest:
    return ReplayRequest.model_validate(
        {
            "symbols": symbols,
            "streams": streams,
            "start": at(start_us),
            "end": at(end_us),
            "depth": depth,
            "source_tier": tier,
        }
    )


class Harness:
    """In-memory tiers plus a request; the tiers stay inspectable after a read. Nothing is
    archived unless `archived` says so, so `auto` reads QuestDB (`hot`) by default."""

    def __init__(
        self,
        *,
        cold: Iterable[RecordedEvent] = (),
        hot: Iterable[RecordedEvent] = (),
        archived: bool = False,
        req: ReplayRequest | None = None,
    ) -> None:
        self.cold = InMemoryRecordedTier(cold)
        self.hot = InMemoryRecordedTier(hot)
        self.coverage = StaticArchiveCoverage()
        self.gaps = StaticGapReader()
        self.tiers = ReplayTiers(
            hot=self.hot, cold=self.cold, coverage=self.coverage, gaps=self.gaps
        )
        self.req = req or request()
        if archived:
            self.archive(0, self.req.end_us - T0)

    def archive(
        self, start_us: int, end_us: int, *, streams: Iterable[StreamKind] | None = None
    ) -> Harness:
        """Manifest `[T0 + start_us, T0 + end_us)` of `streams` (default: all requested)."""
        rng = TimeRange(start_us=T0 + start_us, end_us=T0 + end_us)
        for symbol in self.req.symbols:
            for stream in self.req.streams if streams is None else streams:
                self.coverage.archive(symbol, stream, rng)
        return self

    def replace_ports(
        self,
        *,
        hot: RecordedStreamReader | None = None,
        cold: RecordedStreamReader | None = None,
        coverage: ArchiveCoverage | None = None,
    ) -> Harness:
        self.tiers = ReplayTiers(
            hot=hot or self.hot,
            cold=cold or self.cold,
            coverage=coverage or self.coverage,
            gaps=self.gaps,
        )
        return self

    def merge(
        self, *, budget_bytes: int = ROOMY, window_us: int = 30 * SECOND, timeout_s: float = 5.0
    ) -> RecordedMerge:
        return RecordedMerge(
            self.req,
            self.tiers,
            budget_bytes=budget_bytes,
            window_us=window_us,
            io_timeout_s=timeout_s,
        )

    async def read_all(
        self, *, batch: int = 64, budget_bytes: int = ROOMY, window_us: int = 30 * SECOND
    ) -> list[ReplayItem]:
        merge = self.merge(budget_bytes=budget_bytes, window_us=window_us)
        return [item async for b in merge.batches(max_events=batch, max_bytes=ROOMY) for item in b]


def digest(items: Iterable[ReplayItem]) -> str:
    """SHA-256 over the canonical text of a replayed sequence (`repr` of frozen dataclasses)."""
    sha = hashlib.sha256()
    for item in items:
        sha.update(repr(item).encode())
        sha.update(b"\n")
    return sha.hexdigest()
