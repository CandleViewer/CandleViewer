"""Shared fixtures for the indicator kernel tests."""

from __future__ import annotations

import pytest

from candleviewer.orderflow.indicators import BarInput
from tests.unit.orderflow.indicators._golden import load_inputs


@pytest.fixture(scope="session")
def kline() -> list[BarInput]:
    """The densified recorded kline window (450 bars, a 15-bar filled gap)."""
    return load_inputs("kline_gap")[1]
