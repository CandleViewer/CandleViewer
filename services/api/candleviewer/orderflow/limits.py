"""E22 big-trade bounds — the ONE constants module (E22 threat model §7, SR-E22-01..11).

Imported by the engine, the REST validator and the WS option validator; nothing else may
hold a literal copy. `tests/unit/orderflow/test_bigtrade_limits.py` asserts every value
verbatim, so a change is a reviewed diff (CODEOWNER: backend + security)."""

from __future__ import annotations

from decimal import ROUND_CEILING, Decimal
from typing import Final

TRADES_MAX_WINDOW_MS: Final = 21_600_000  # 6 h (SR-E22-01)
TRADES_MAX_WINDOW_CLUSTERED_MS: Final = 900_000  # 15 min when cluster_window_ms > 2000
TRADES_MAX_LIMIT: Final = 500  # SR-E22-02
CLUSTER_WINDOW_MS_MAX_REST: Final = 5000  # SR-E22-04
CLUSTER_WINDOW_MS_MAX_WS: Final = 2000  # SR-E22-04
CLUSTER_TOLERANCE_TICKS_MAX: Final = 20  # SR-E22-04
CLUSTER_KEYS_MAX: Final = 4096  # SR-E22-05, per symbol
PRINTS_BUFFER_MAX: Final = 16384  # SR-E22-05, per symbol — a FLOOR (24-internal-schemas §2.10)
PRINTS_PER_MS_BUDGET: Final = 5  # budget #5: 5 000 prints/s
CLUSTER_IDS_MAX: Final = 64  # §2.10 bounded membership
TRADES_SUBS_PER_USER_MAX: Final = 60  # SR-E22-06
CONNECTIONS_PER_USER_MAX: Final = 8  # SR-E22-06
OPTION_SETS_PER_SYMBOL_MAX: Final = 2  # SR-E22-07
CONN_BUDGET_FRAMES: Final = 2000  # SR-E22-08 (23-ws §8.4)
CONN_BUDGET_BYTES: Final = 8 * 1024 * 1024
TRADES_BUDGET_SHARE: Final = Decimal("0.5")  # trades.* soft fair share of the conn budget
RING_BUFFER_MAX_PRINTS: Final = 50_000  # SR-E22-09
RING_BUFFER_MAX_BYTES: Final = 32 * 1024 * 1024
VISIBLE_BUBBLES_MAX: Final = 5000
BUBBLE_FLASH_MAX_HZ: Final = 3  # SR-E22-10
THRESHOLD_SYMBOLS_PER_USER_MAX: Final = 200  # SR-E22-11

# Engine-only bounds (§2.10; fixed-size state regardless of window length).
PERCENTILE_WINDOW_MS_MIN: Final = 60_000
PERCENTILE_WINDOW_MS_MAX: Final = 86_400_000
PERCENTILE_WINDOW_BUCKETS: Final = 12  # bucketed sub-estimators per trailing window
THRESHOLD_REFRESH_US: Final = 5_000_000  # 5 s of print time
OVERFLAG_FRACTION: Final = Decimal("0.20")
OVERFLAG_CAP_QUANTILE: Final = 0.80
OVERFLAG_MIN_SAMPLES: Final = 20  # below this the trailing fraction is noise
DEDUPE_IDS_MAX: Final = 50_000  # mirrors the ingest dedupe ring (24-internal-schemas §2.1)


def prints_buffer_effective_max(cluster_window_ms: int) -> int:
    """`PRINTS_BUFFER_EFFECTIVE_MAX = max(PRINTS_BUFFER_MAX, cluster_window_ms * 5)`."""
    return max(PRINTS_BUFFER_MAX, cluster_window_ms * PRINTS_PER_MS_BUDGET)


def min_size_floor(lot_size: Decimal, tick_notional: Decimal) -> Decimal:
    """`MIN_SIZE_FLOOR` per instrument: max(lot_size, one tick-notional) (SR-E22-03). As ruled
    (2026-10-28), `lot_size` is the instrument's `min_order_qty` and `tick_notional` the size of
    its minimum order notional at the reference price (`notional_size`)."""
    return max(lot_size, tick_notional)


def notional_size(min_notional: Decimal, ref_price: Decimal | None, qty_step: Decimal) -> Decimal:
    """The size worth `min_notional` at `ref_price`, ceiled to `qty_step` (SR-E22-03). 0 while no
    price is known yet, or when the instrument has no minimum notional: `MIN_SIZE_FLOOR` then
    collapses to `min_order_qty`."""
    if ref_price is None or ref_price <= 0 or min_notional <= 0 or qty_step <= 0:
        return Decimal(0)
    steps = (min_notional / ref_price / qty_step).to_integral_value(rounding=ROUND_CEILING)
    return steps * qty_step
