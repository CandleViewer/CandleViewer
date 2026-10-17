"""A real `DiskBudget` over a fake meter and clock, sampled once, for the admin storage tests
(E42-T01): the adapter is tested against the producer's own report, never a hand-written copy."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from candleviewer.recorder.budget import US_PER_S, BudgetConfig, DiskBudget, Point
from tests.unit.recorder._budget_fakes import GB, NOW, FakeMeter, FakeSeriesStore, make_budget

#: When the fake budget stamps its sample: its clock stays frozen at `NOW`.
AT = datetime.fromtimestamp(NOW / US_PER_S, UTC)
BTC, ETH = "BTCUSDT", "ETHUSDT"
_STEP = 600 * US_PER_S
_PER_STEP = 10 * GB * 600 // 86_400  # a steady 10 GB/day
SIZE = 12 * _PER_STEP


def clock(age_s: float = 0.0) -> Callable[[], datetime]:
    """The admin clock, `age_s` seconds after the budget's sample."""
    return lambda: AT + timedelta(seconds=age_s)


def unsampled() -> DiskBudget:
    return make_budget(FakeMeter())[0]


async def sampled(
    *,
    used: int | None = None,
    free: int | None = None,
    symbols: dict[str, int] | None = None,
    pinned: frozenset[str] = frozenset(),
    config: BudgetConfig | None = None,
    measured: bool = False,
) -> DiskBudget:
    """A budget after one `sample_once()`. `measured` first loads a series of a steady 10 GB/day
    for BTCUSDT, so the fit has a growth; without it nothing is measured yet (a fresh start)."""
    series: list[Point] = []
    default_used, default_symbols = 50 * GB, {BTC: 30 * GB, ETH: 20 * GB}
    if measured:
        series = [
            Point(NOW - (12 - i) * _STEP, i * _PER_STEP, ((BTC, i * _PER_STEP),)) for i in range(12)
        ]
        default_used, default_symbols = SIZE, {BTC: SIZE}
    meter = FakeMeter(
        used=default_used if used is None else used,
        symbols=default_symbols if symbols is None else symbols,
    )
    if free is not None:
        meter.free = free
    budget, _, _ = make_budget(
        meter, store=FakeSeriesStore(series) if series else None, pinned=pinned, config=config
    )
    await budget.load_series()
    await budget.sample_once()
    return budget
