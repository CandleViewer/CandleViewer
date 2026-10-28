"""Fakes for the scan (E08-T09 PR 2b, #4708): tickers, a `UniverseTickerSource` and a
`RecordingReads` in memory, and a router-only app over `ScannerService` built on PR 2a's
`_scanner_env`."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any

from candleviewer.api.scanner_service import ScannerService
from candleviewer.exchange.base.models import TickerEvent
from candleviewer.exchange.base.universe import UniverseSnapshot
from candleviewer.recorder.control import EntryPage, EntryQuery, RecordedEntry

#: The venue's answer time and its receipt here (µs), and the scan's wall clock.
TS_US = 1_793_000_000_000_000
NOW_US = TS_US + 1_000_000


def ticker(symbol: str, **over: Any) -> TickerEvent:
    """A full linear ticker; `over` replaces fields (`None` empties one)."""
    fields: dict[str, Any] = {
        "event_id": uuid.uuid4(),
        "ts_event": TS_US,
        "ts_ingest": TS_US,
        "source": "live",
        "symbol": symbol,
        "last_price": Decimal("100"),
        "mark_price": Decimal("100"),
        "index_price": Decimal("100"),
        "bid1_price": Decimal("99.99"),
        "bid1_qty": Decimal("1"),
        "ask1_price": Decimal("100.01"),
        "ask1_qty": Decimal("1"),
        "open_interest": Decimal("1000"),
        "open_interest_value": Decimal("100000"),
        "turnover_24h": Decimal("5000000"),
        "volume_24h": Decimal("50000"),
        "price_24h_pcnt": Decimal("0.01"),
        "high_24h": Decimal("110"),
        "low_24h": Decimal("100"),
        "funding_rate": Decimal("0.0001"),
        "next_funding_time": TS_US + 3_600_000_000,
        "is_delta": False,
    }
    return TickerEvent(**(fields | over))


def universe(tickers: Iterable[TickerEvent]) -> dict[str, TickerEvent]:
    return {t.symbol: t for t in tickers}


class FakeUniverse:
    """A `UniverseTickerSource`: `snapshot` is what `latest()` answers (`None`: past its bound);
    `refresh()` counts its calls and raises `fail` when set."""

    def __init__(
        self, tickers: Mapping[str, TickerEvent] | None = None, *, received_at_us: int = TS_US
    ) -> None:
        self.snapshot: UniverseSnapshot | None = (
            None if tickers is None else UniverseSnapshot(dict(tickers), received_at_us, TS_US)
        )
        self.refreshes = 0
        self.fail: BaseException | None = None
        self.gate: Any = None  # an `asyncio.Event` `refresh()` waits on, when set

    def latest(self) -> UniverseSnapshot | None:
        return self.snapshot

    async def refresh(self) -> UniverseSnapshot | None:
        self.refreshes += 1
        if self.gate is not None:
            await self.gate.wait()
        if self.fail is not None:
            raise self.fail
        return self.snapshot


def entry(
    symbol: str,
    state: str = "recording",
    reasons: tuple[str, ...] = ("manual",),
) -> RecordedEntry:
    return RecordedEntry(str(uuid.uuid4()), symbol, reasons, state)  # type: ignore[arg-type]


@dataclass
class FakeRecording:
    """`RecordingReads.list` over `entries`, paged by `(symbol, id)` like the store, leaving out
    the entries held only by the query's `hidden` causes; `fail` is raised by every read."""

    entries: list[RecordedEntry]
    fail: Exception | None = None
    calls: int = 0

    async def list(self, query: EntryQuery) -> EntryPage:
        self.calls += 1
        if self.fail is not None:
            raise self.fail
        held = [
            e
            for e in sorted(self.entries, key=lambda e: (e.symbol, e.id))
            if any(r not in query.hidden for r in e.reasons)
            and (query.after is None or (e.symbol, e.id) > query.after)
        ]
        return EntryPage(tuple(held[: query.limit]), len(held) > query.limit)

    async def get(self, entry_id: str) -> RecordedEntry | None:
        return next((e for e in self.entries if e.id == entry_id), None)


class Counter:
    """A facade metric's stand-in: every child's increments and observations, by label."""

    def __init__(self) -> None:
        self.values: dict[tuple[str, ...], float] = {}
        self.observed: list[float] = []

    def labels(self, *values: str) -> Any:
        metric = self

        class _Child:
            def inc(self, amount: float = 1) -> None:
                metric.values[values] = metric.values.get(values, 0) + amount

            def observe(self, amount: float) -> None:
                metric.observed.append(amount)

        return _Child()

    def total(self, *values: str) -> float:
        return self.values.get(values, 0)


@dataclass
class Clock:
    """Injected clocks: `mono` for the cache, `wall_us` for `generated_at` and staleness."""

    mono: float = 1000.0
    wall_us: int = NOW_US

    def monotonic(self) -> float:
        return self.mono

    def now_us(self) -> int:
        return self.wall_us


def service(
    source: FakeUniverse | None,
    recording: FakeRecording | None,
    *,
    clock: Clock | None = None,
    metrics: Any = None,
    **kw: Any,
) -> ScannerService:
    clock = clock or Clock()
    return ScannerService(
        lambda: source,
        lambda: recording,
        metrics,
        clock_us=clock.now_us,
        monotonic=clock.monotonic,
        **kw,
    )


__all__ = [
    "NOW_US",
    "TS_US",
    "Clock",
    "Counter",
    "FakeRecording",
    "FakeUniverse",
    "entry",
    "replace",
    "service",
    "ticker",
    "universe",
]
