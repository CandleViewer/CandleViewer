"""E13 indicator parameter bounds: the ONE constants module (E13 threat model SR-E13-01).

`catalogue.py` builds every `params_schema` from these values and `validate_params()` enforces
them, so the bounds a client renders and the bounds the server checks are the same numbers.
The step (`multipleOf`) is decimal: a client must check it in decimal too, because a stock JSON
Schema validator divides in binary64 and refuses legal values such as 0.3 for a step of 0.1
(`catalogue` docstring, 24-internal-schemas §7.4). Nothing else may hold a literal copy.
`tests/unit/orderflow/indicators/test_limits.py` asserts every value verbatim, so a change is a
reviewed diff (CODEOWNERS: the `orderflow/` owners).

- A period-like parameter (a count of bars: a length, a lookback, a smoothing, a displacement)
  is a whole number from `PERIOD_MIN` to `PERIOD_MAX`: the SCR-035 contract ("Period must be
  between 1 and 5000."), which the threat model's 2026-10-13 sign-off fixed for every
  period-style parameter. The spike measured the kernels O(1) per bar, so the period is not
  the cost driver; the server-instance caps are (SR-E13-03).
- Every other numeric parameter is fractional and has a minimum, a maximum and a step
  (`multipleOf`). A value outside them is refused, never clamped or rounded (SR-E13-01), and
  the step bounds how many distinct instances near-identical values can create (IR-36).

Fractional bounds are `Decimal`, so the step check is exact (`catalogue.validate_params`).

The second block holds the resource caps of the server instances (SR-E13-03) and of their full
recomputes (SR-E13-04), which `leases.InstanceLeases` and `engine.IndicatorEngine` enforce before
anything is allocated or computed, and the third the bounds of an instance's own state. Every
constant the engine and the leases use is here, and pinned.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

PERIOD_MIN: Final = 1
PERIOD_MAX: Final = 5000

#: Band and channel width multipliers (`bollinger`, `keltner`, `supertrend`).
MULTIPLIER_MIN: Final = Decimal("0.1")
MULTIPLIER_MAX: Final = Decimal("10")
MULTIPLIER_STEP: Final = Decimal("0.1")

#: ZigZag's minimum swing, in percent of the last swing of the other kind (0: every pivot).
DEVIATION_PCT_MIN: Final = Decimal("0")
DEVIATION_PCT_MAX: Final = Decimal("50")
DEVIATION_PCT_STEP: Final = Decimal("0.1")

#: Parabolic SAR acceleration factor: its step (the start and the increment) and its maximum.
PSAR_ACCELERATION_MIN: Final = Decimal("0.001")
PSAR_ACCELERATION_MAX: Final = Decimal("1")
PSAR_ACCELERATION_STEP: Final = Decimal("0.001")

# --- Server instances and full recomputes (SR-E13-03, SR-E13-04; `engine`, `leases`) ---------

#: SR-E13-03: the most distinct server instances (`(symbol, spec_hash)`) one user may hold, one
#: symbol may run and the process may run. An instance in its release grace still counts toward
#: the symbol and process caps (it still costs CPU and memory); joining a running instance counts
#: toward the user's caps only; a system consumer (`user=None`) is exempt from the user caps only.
INSTANCE_CAP_PER_USER: Final = 8
INSTANCE_CAP_PER_SYMBOL: Final = 32
INSTANCE_CAP_PROCESS: Final = 128
#: IR-31: the most distinct instances one user may hold and have released that are still in
#: their grace, together (subscribe and unsubscribe churn: a symbol or timeframe flip starts new
#: instances and leaves the old ones folding until their grace ends). Three times the held cap:
#: a flip of three instances every 5 s stays under it for good (at most six releases of three in
#: a grace, plus the three held: 21), and so do two full flips of eight in 30 s (24). Holding a
#: released instance again, by anyone, ends its charge; a WS `ctl` drops the instances it
#: replaces that no one else holds, so a retune leaves none in a grace.
INSTANCE_CHURN_CAP_PER_USER: Final = 3 * INSTANCE_CAP_PER_USER
#: An instance whose last lease is released is kept this long (US-MKT-005's 30 s), so a quick
#: resubscribe finds it computed.
INSTANCE_GRACE_US: Final = 30_000_000
#: The emit path removes instances whose grace has ended at most this often, so an unheld one
#: stops folding closes within a second of its grace (`check` and `release` remove them too).
SWEEP_EVERY_US: Final = 1_000_000
#: SR-E13-04: the most bars one instance's window may span (its warmup, the history a
#: subscription asks for and, for a session-anchored one, the day back to a session start),
#: refused beyond it, never truncated.
MAX_WINDOW_BARS: Final = 250_000
#: SR-E13-04: full recomputes that read stored bars at once; one more is refused, never queued.
MAX_CONCURRENT_RECOMPUTES: Final = 2
#: How long a full recompute's read of stored bars may take; past it the instance is primed from
#: the series store's tail alone.
RECOMPUTE_TIMEOUT_S: Final = 5.0
#: C-2.17: a full recompute reads stored bars in pages of at most this many rows and yields to
#: the event loop after each, and folds them in chunks of this many kernel updates (a time
#: series' fillers included; one bar's fillers, at most `MAX_FILL_SLOTS`, never split) with a
#: yield between.
HISTORY_PAGE_ROWS: Final = 1_000
PRIME_CHUNK_UPDATES: Final = 512
#: C-2.17: the most kernel updates (fillers included) a prime may fold synchronously, its
#: instances together: a full dense series store for eight instances. A prime that needs more
#: runs as a full recompute (a task on a slot, `PRIME_CHUNK_UPDATES` at a time); one that must
#: run at once with no slot free folds only the newest bars within it, split evenly per instance.
MAX_SYNC_PRIME_UPDATES: Final = 8_000

# --- Instance state (`engine`) ---------------------------------------------------------------

#: The most points an instance keeps: the WS `history` cap (23 §6.1), so any snapshot is whole,
#: and the series store's tail (`bars.limits.MAX_TAIL`, which this module may not import). It
#: also bounds the closes an instance holds back while a full recompute folds.
MAX_POINTS: Final = 1_000
#: A time-series instance keeps a kernel snapshot before every this-many real bars, for amended
#: closes (24 §7.4).
CHECKPOINT_EVERY: Final = 8
#: More empty slots than this in one time-series gap restart the kernel instead of being filled.
MAX_FILL_SLOTS: Final = 1_000
#: C-2.17: the most kernel updates (a time series' fillers included) an amended close may replay
#: in one instance, from the checkpoint before it to the newest bar: one filled gap and a
#: checkpoint spacing of bars, about what a close costs. On a sparse series a checkpoint can lie
#: several filled gaps back; a replay that needs more re-primes the series instead (`engine`).
MAX_AMEND_UPDATES: Final = MAX_FILL_SLOTS + CHECKPOINT_EVERY
#: A read of an instance more than this many closes behind its series is `stale`.
STALE_AFTER_BARS: Final = 2
