"""LiquidityTracker config, events and results (24-internal-schemas §2.11, E21-T04, #710).

L2-only inference: every event carries `estimated=True` (no L3/MBO data exists, so a refill is
inferred from book changes against the tape). All `*_pct` values are fractions in (0, 1]."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from candleviewer.domain.events import MarketEvent
from candleviewer.domain.primitives import Px, Qty, Ticks
from candleviewer.orderflow.errors import OrderflowError

BookSide = Literal["bid", "ask"]

BUCKETS_MAX = 256  # BQ-10: hard cap on price buckets; coarsen `bucket_ticks`, never grow
MAX_LEVELS_MAX = 1000  # per side, per sample: bounds the work on a pathological book
WINDOW_MS_MAX = 60_000
SAMPLES_MAX = 6_000  # ring columns (ring_ms / cadence_ms): with BUCKETS_MAX, 12.3 MB (C-2.18)
MAX_EVENTS_MAX = 256  # events one sample may emit; the rest are counted, never silently lost


class LiquidityConfigInvalid(OrderflowError, ValueError):
    """A config value outside its bound; the message names the field only."""


@dataclass(frozen=True, slots=True)
class LiquidityConfig:
    """Keys `liquidity.*` (24 §2.11). `min_size=None` resolves to 10 x `qty_step`."""

    bands_ticks: tuple[int, ...] = (5, 10, 25, 50, 100)
    reload_consume_pct: Decimal = Decimal("0.5")
    reload_replenish_pct: Decimal = Decimal("0.9")
    reload_window_ms: int = 5_000
    min_size: Decimal | None = None
    tolerance_pct: Decimal = Decimal("0.1")
    buckets: int = 200
    bucket_ticks: int = 1
    ring_ms: int = 600_000
    cadence_ms: int = 100
    max_levels: int = 500
    max_events: int = 16

    def validated(self) -> LiquidityConfig:
        unit = Decimal(1)
        checks = (
            (bool(self.bands_ticks) and all(b > 0 for b in self.bands_ticks), "bands_ticks"),
            (list(self.bands_ticks) == sorted(set(self.bands_ticks)), "bands_ticks"),
            (Decimal(0) < self.reload_consume_pct <= unit, "reload_consume_pct"),
            (Decimal(0) < self.reload_replenish_pct <= unit, "reload_replenish_pct"),
            (Decimal(0) <= self.tolerance_pct <= unit, "tolerance_pct"),
            (0 < self.reload_window_ms <= WINDOW_MS_MAX, "reload_window_ms"),
            (self.min_size is None or self.min_size >= 0, "min_size"),
            (0 < self.buckets <= BUCKETS_MAX, "buckets"),
            (self.bucket_ticks > 0, "bucket_ticks"),
            (0 < self.cadence_ms <= self.ring_ms, "cadence_ms"),
            (self.cadence_ms > 0 and self.ring_ms // self.cadence_ms <= SAMPLES_MAX, "ring_ms"),
            (0 < self.max_levels <= MAX_LEVELS_MAX, "max_levels"),
            (0 < self.max_events <= MAX_EVENTS_MAX, "max_events"),
        )
        for ok, field in checks:
            if not ok:
                raise LiquidityConfigInvalid(field)
        return self

    @property
    def samples(self) -> int:
        return self.ring_ms // self.cadence_ms


@dataclass(frozen=True, slots=True)
class BandDepth:
    """Cumulative resting size within `band_ticks` of the mid (inclusive); exact Decimal."""

    band_ticks: int
    bid: Decimal
    ask: Decimal
    diff: Decimal  # bid - ask


class LiquidityReload(MarketEvent):
    """A level consumed by aggressive prints and replenished within the window."""

    side: BookSide
    price: Px
    price_ticks: Ticks
    prior_size: Qty
    replenished_size: Qty
    refill_count: int
    estimated: Literal[True] = True


class LiquidityPulled(MarketEvent):
    """A level dropped without matching prints at or through its price in the window."""

    side: BookSide
    price: Px
    price_ticks: Ticks
    prior_size: Qty
    remaining_size: Qty
    traded_qty: Qty
    estimated: Literal[True] = True


@dataclass(frozen=True, slots=True)
class LiquiditySample:
    """One sample's result: bands (empty when not live), the events it emits (at most
    `max_events`, nearest the mid first) and `overflow`, the events past that cap (counted by the
    caller, never published)."""

    ts_us: int
    estimated: bool
    bands: tuple[BandDepth, ...]
    events: tuple[LiquidityReload | LiquidityPulled, ...]
    overflow: int = 0
