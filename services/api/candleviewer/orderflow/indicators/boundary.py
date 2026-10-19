"""The C3 Decimal boundary for indicator values (24-internal-schemas §1.1 C3, plan §3.3).

The kernels are float64 inside. A value that reaches the OMS, the journal or audit crosses here,
as `Decimal(str(x)).quantize(quantum)`: `str(float)` is the shortest round-trip repr, so the
Decimal holds exactly the digits the kernel produced, and rounding happens once, half to even,
at the consumer's quantum. `None`, NaN and infinities never cross as numbers: they become a
typed `Unavailable` (SR-E13-12), so a consumer must handle "no value" explicitly and can never
read it as 0.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Final

from candleviewer.orderflow.errors import IndicatorBoundaryError
from candleviewer.orderflow.indicators.types import Unavailable, UnavailableReason

#: Any finite binary64 has at most 309 integer digits; with quanta down to 1e-80 the quantised
#: coefficient fits in 400 digits, so `quantize` never signals InvalidOperation (the default
#: 28-digit context would, for large values).
_PREC: Final = 400
_MIN_EXPONENT: Final = -80
_MAX_EXPONENT: Final = 80


def to_decimal(
    x: float | None, quantum: Decimal, *, if_none: UnavailableReason = "missing"
) -> Decimal | Unavailable:
    """`Decimal(str(x)).quantize(quantum)`, or `Unavailable` for `None` (`if_none`) and
    non-finite values (`"nan"`). Negative zero becomes zero."""
    exponent = quantum.as_tuple().exponent
    if not isinstance(exponent, int) or not _MIN_EXPONENT <= exponent <= _MAX_EXPONENT:
        raise IndicatorBoundaryError(
            f"The quantum must be a finite Decimal with an exponent between "
            f"{_MIN_EXPONENT} and {_MAX_EXPONENT}."
        )
    if x is None:
        return Unavailable(if_none)
    if not math.isfinite(x):
        return Unavailable("nan")
    with localcontext() as ctx:
        ctx.prec = _PREC
        value = Decimal(str(x)).quantize(quantum, rounding=ROUND_HALF_EVEN)
    return value.copy_abs() if value.is_zero() else value
