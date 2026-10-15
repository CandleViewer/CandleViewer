"""E42-T01: `DiskBudget.measured_growth()` tells "not measured yet" (`None`) apart from a measured
growth, which `report()` folds together as `daily_growth_bytes = 0` before the first fit."""

from __future__ import annotations

import pytest

from candleviewer.recorder.budget import US_PER_S, Point
from tests.unit.recorder._budget_fakes import GB, NOW, FakeMeter, FakeStore, make_budget

STEP = 600 * US_PER_S
PER_STEP = 10 * GB * 600 // 86_400  # a steady 10 GB/day


async def test_before_any_fit_growth_is_none_while_the_report_says_zero() -> None:
    budget, _, _ = make_budget(FakeMeter(used=10 * GB, symbols={"BTCUSDT": 10 * GB}))
    assert budget.measured_growth() == (None, {})
    await budget.sample_once()
    report = budget.report()
    assert report is not None and report.daily_growth_bytes == 0
    assert budget.measured_growth() == (None, {})


async def test_a_fitted_series_reports_its_growth_and_the_fitted_symbols() -> None:
    points = [
        Point(NOW - (12 - i) * STEP, i * PER_STEP, (("BTCUSDT", i * PER_STEP),)) for i in range(12)
    ]
    size = 12 * PER_STEP
    budget, _, _ = make_budget(
        FakeMeter(used=size, symbols={"BTCUSDT": size}), store=FakeStore(points)
    )
    await budget.load_series()
    await budget.sample_once()
    growth, per_symbol = budget.measured_growth()
    assert growth is not None and abs(growth - 10 * GB) <= GB // 100
    assert set(per_symbol) == {"BTCUSDT"} and abs(per_symbol["BTCUSDT"] - 10 * GB) <= GB // 100
    with pytest.raises(TypeError):  # a read-only copy: callers cannot corrupt the fit
        per_symbol["BTCUSDT"] = 0  # type: ignore[index]  # deliberately mutating a Mapping
