"""E13 indicator parameter bounds: the ONE constants module (E13 threat model SR-E13-01).

`catalogue.py` builds every `params_schema` from these values and `validate_params()` enforces
them, so the form a client renders and the check the server runs cannot drift. Nothing else
may hold a literal copy. `tests/unit/orderflow/indicators/test_limits.py` asserts every value
verbatim, so a change is a reviewed diff (CODEOWNER: backend + security).

- A period-like parameter (a count of bars: a length, a lookback, a smoothing, a displacement)
  is a whole number from `PERIOD_MIN` to `PERIOD_MAX`: the SCR-035 contract ("Period must be
  between 1 and 5000."), which the threat model's 2026-10-13 sign-off fixed for every
  period-style parameter. The spike measured the kernels O(1) per bar, so the period is not
  the cost driver; the server-instance caps are (SR-E13-03).
- Every other numeric parameter is fractional and has a minimum, a maximum and a step
  (`multipleOf`). A value outside them is refused, never clamped or rounded (SR-E13-01), and
  the step bounds how many distinct instances near-identical values can create (IR-36).

Fractional bounds are `Decimal`, so the step check is exact (`catalogue.validate_params`).
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
