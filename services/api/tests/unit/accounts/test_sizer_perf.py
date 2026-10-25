"""E28-T03 (#907) performance: one leg p95 <= 1 ms, a group of 5 legs <= 5 ms (06-performance
budget #4, fan-out sub-clause), on the golden vectors' inputs (QA's and the ticket's), built
before the clock starts.

Wall-clock budgets, so `-m perf` (C-13.9; the `py-perf` job). GC is disabled while timing. The
figures are printed (`-s`) for the PR to quote."""

from __future__ import annotations

import gc
import time
from decimal import Decimal
from typing import Any, Final

import pytest

from candleviewer.accounts import sizer as sz
from candleviewer.accounts import sizer_metrics as sm
from candleviewer.observability.metrics import Metrics
from tests.unit.accounts.test_sizer import atr, instrument, profile, wallet
from tests.unit.accounts.test_sizer_golden import VECTORS

D = Decimal
SINGLE_P95_S: Final = 1e-3
GROUP_S: Final = 5e-3
ROUNDS: Final = 200


def _inputs(v: dict[str, Any]) -> tuple[Any, ...]:
    """`run`'s inputs for one vector (test_sizer_caps), without the call."""
    m, it = v["market"], v["intent"]
    intent = sz.SizingIntent.model_validate(it | {"side": it["side"].lower()})
    p = profile(v["profile"]["id"], **v["profile"]["set"])
    reading = atr(D(m["atr"]), p.sl_atr_period) if m["atr"] else None
    market = sz.SizingMarket(mid=m.get("mid"), last_price=m.get("last_price"), atr=reading)
    w = wallet(v["wallet"]["equity"], m["taker_fee_rate"], realised_loss_today=m["daily_loss_used"])
    w = w.model_copy(update={"available_margin": D(v["wallet"]["available_margin"])})
    return intent, p, w, instrument(intent.symbol), market


assert len(VECTORS) >= 40  # a renamed or emptied golden set must not pass the bench
_LEGS: Final = [_inputs(v) for v in VECTORS]


def _timed(legs: list[tuple[Any, ...]], observer: sm.SizerMetrics | None = None) -> list[float]:
    """Each round's seconds to size every leg of `legs` once (recorded, with an `observer`)."""
    gc.collect()
    gc.disable()
    try:
        out = []
        for _ in range(ROUNDS):
            t0 = time.perf_counter()
            for args in legs:
                if observer is None:
                    sz.size_leg(*args)
                else:
                    sm.size_leg_observed(*args, observer=observer)
            out.append(time.perf_counter() - t0)
    finally:
        gc.enable()
    return out


def _p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    return ordered[int(len(ordered) * 0.95) - 1]


@pytest.mark.perf
def test_size_leg_single_leg_p95_is_within_1_ms() -> None:
    worst = 0.0
    for args in _LEGS:  # every golden vector, each one's p95 over ROUNDS
        worst = max(worst, _p95(_timed([args])))
    print(f"\nsize_leg single leg: worst p95 {worst * 1e6:.1f} us over {len(_LEGS)} vectors")
    assert 0 < worst <= SINGLE_P95_S


@pytest.mark.perf
def test_size_leg_five_leg_group_is_within_5_ms() -> None:
    oks = [args for args, v in zip(_LEGS, VECTORS, strict=True) if v["expected"]["outcome"] == "ok"]
    group = oks[:5]  # the full path: caps, margin and take-profits
    assert len(group) == 5
    samples = _timed(group, sm.SizerMetrics.register(Metrics("dev")))  # as callers run it
    p95, worst = _p95(samples), max(samples)
    print(f"\nsize_leg_observed 5-leg group: p95 {p95 * 1e6:.1f} us, max {worst * 1e6:.1f} us")
    assert 0 < p95 <= GROUP_S
