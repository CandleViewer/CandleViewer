"""Venue-neutral ticker wire delta (E08-S03, `docs/plan/24-internal-schemas.md` §2.3).

An exchange adapter parses its native ticker frame into a `TickerDelta`; the
ingestion merger folds deltas into complete `TickerEvent`s. Absent keys in
`fields` mean *unchanged*, never null.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

#: Neutral field names a delta may carry (the `TickerEvent` field names).
TICKER_FIELDS: tuple[str, ...] = (
    "last_price",
    "mark_price",
    "index_price",
    "bid1_price",
    "bid1_qty",
    "ask1_price",
    "ask1_qty",
    "open_interest",
    "open_interest_value",
    "turnover_24h",
    "volume_24h",
    "price_24h_pcnt",
    "high_24h",
    "low_24h",
    "funding_rate",
    "next_funding_time",
)


@dataclass(frozen=True, slots=True)
class TickerDelta:
    symbol: str
    #: True when the frame is a full replacement (state reset), False for a delta.
    is_snapshot: bool
    #: Envelope timestamp (exchange), microseconds UTC. Never synthesized.
    ts_event_us: int
    #: Only the keys present on the wire; `next_funding_time` is an `int` (µs).
    fields: Mapping[str, Decimal | int]
