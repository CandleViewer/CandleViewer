"""Refusing a number is O(1): a number near either end of the decimal context's range is refused
within the time budget, because its width is decided before its form is built (#4185). A change that
built the form first, and measured it after, would take far longer than the budget over this batch.
"""

from __future__ import annotations

import contextlib
import decimal
import time
from decimal import Decimal

import pytest

from candleviewer.rules.ir import canonical

CTX = decimal.getcontext()
BUDGET_S = 0.005
REPEATS = 25
#: The three exponents either side of the largest and of the smallest the context holds, both signs.
NEAR_THE_RANGE = [
    Decimal((sign, (1,), exponent))
    for exponent in (*range(CTX.Emax - 3, CTX.Emax + 4), *range(CTX.Etiny() - 3, CTX.Etiny() + 4))
    for sign in (0, 1)
]


@pytest.mark.perf
def test_dec_str_refuses_numbers_near_the_context_range_within_the_time_budget() -> None:
    for number in NEAR_THE_RANGE:  # what is timed below is a refusal each time
        with pytest.raises(canonical.IrValueError):
            canonical.dec_str(number)
    best = float("inf")
    for _ in range(5):  # best-of-5 damps scheduler noise
        started = time.perf_counter()
        for _ in range(REPEATS):
            for number in NEAR_THE_RANGE:
                with contextlib.suppress(canonical.IrValueError):
                    canonical.dec_str(number)
        best = min(best, time.perf_counter() - started)
    took = f"{REPEATS * len(NEAR_THE_RANGE)} refusals took {best * 1000:.1f} ms"
    assert best < BUDGET_S, f"{took}, budget {BUDGET_S * 1000:.0f} ms"
