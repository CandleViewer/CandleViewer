"""Exchange-neutral instrument-catalogue port (E08-S01-2, C-2.2).

The adapter fetches *and* parses the exchange's instrument list; consumers
(`candleviewer.ingestion`) only ever see neutral `Instrument` objects plus a
per-row rejection list, never a raw exchange payload or the parser.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from candleviewer.domain.events import Instrument

from .models import RiskLimitTier


class InstrumentParseError(ValueError):
    """A raw instrument row is missing a required field or has a value that
    cannot be coerced to the expected type. Raised per-row so the caller
    decides whether one bad row fails the refresh or is skipped-and-logged."""


@dataclass(frozen=True, slots=True)
class RejectedInstrument:
    """One row the adapter could not normalise (symbol if known + reason)."""

    symbol: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class InstrumentsFetchResult:
    """Normalised output of one full catalogue fetch (all pages)."""

    instruments: tuple[Instrument, ...]
    rejected: tuple[RejectedInstrument, ...] = ()


#: Fetch every instrument page and normalise it. `now_us` is sampled by the
#: adapter once the fetch completes and stamped as `Instrument.fetched_at`.
InstrumentsFetcher = Callable[[Callable[[], int]], Awaitable[InstrumentsFetchResult]]

#: S-RL (#913): one symbol's risk-limit tiers, ascending by `risk_limit_value`
#: (`MarketDataPort.fetch_risk_limits`'s answer as a plain callable, like the fetcher above).
RiskLimitsFetcher = Callable[[str], Awaitable[Sequence[RiskLimitTier]]]
