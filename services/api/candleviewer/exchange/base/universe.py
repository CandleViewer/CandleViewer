"""The venue-wide ticker universe (E08-T08, #4707): one read of every listed linear ticker, shared.

Neutral vocabulary only (C-2.2): the adapter's read (`TickersFetcher`, answering a `TickerPage` of
neutral rows) and the read-only port its consumers share (`UniverseTickerSource`: the bulk route
`GET /market/tickers` and the scanner, #4708), so the venue sees one poller. The implementation
lives in `ingestion.ticker_bulk`; the composition root injects it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from candleviewer.exchange.base.models import TickerEvent
from candleviewer.exchange.base.ticker_delta import TickerDelta


@dataclass(frozen=True, slots=True)
class TickerPage:
    """One venue-wide read: a full `TickerDelta` (`is_snapshot`) per listed symbol, all at
    `ts_event_us`, the venue's answer time; `rejected` counts the rows refused."""

    ts_event_us: int
    tickers: Mapping[str, TickerDelta]
    rejected: int = 0


#: The venue-wide read as a plain callable (the adapter builds it, C-2.2).
TickersFetcher = Callable[[], Awaitable[TickerPage]]


@dataclass(frozen=True, slots=True)
class UniverseSnapshot:
    """The last venue-wide answer, normalised."""

    #: Every listed linear symbol in the answer.
    tickers: Mapping[str, TickerEvent]
    #: Its receipt on this server's clock (wall µs), which ages the 5 s and 15 s bounds.
    received_at_us: int
    #: The venue's answer time (µs): each item's `ts`.
    exchange_ts_us: int


class UniverseTickerSource(Protocol):
    """Read-only, shared by every consumer: one venue budget (at most one read per 5 s)."""

    def latest(self) -> UniverseSnapshot | None:
        """The last snapshot while it is at most 15 s old, else `None`: no I/O, no demand and no
        refresh."""
        ...

    async def refresh(self) -> UniverseSnapshot | None:
        """The snapshot, read again first when it is over 5 s old: single flight, at most one
        venue read per 5 s shared with `GET /market/tickers`. After a failed read, the last
        snapshot until it is 15 s old, then `None`. Never takes a WS upstream lease."""
        ...


__all__ = ["TickerPage", "TickersFetcher", "UniverseSnapshot", "UniverseTickerSource"]
