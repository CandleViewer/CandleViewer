"""Fixtures for the E12-Q06 bars chaos suite (virtual clock, seeded, no network)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from candleviewer.bars.builder_set import BarBuilderSet
from tests.chaos.ingestion._rig import Rig

#: The suite's fixed seed (same convention as the ingestion suite).
SEED = 20261101


@pytest.fixture(autouse=True)
def _no_real_time_ticker(monkeypatch: pytest.MonkeyPatch) -> None:
    """`BarBuilderSet.start()` spawns a ticker on real `asyncio.sleep`: forbidden here. The
    rig drives `tick()` from the virtual clock instead (see `test_harness_guards.py`)."""

    async def refuse(self: BarBuilderSet) -> None:
        raise AssertionError("bars chaos rig must drive tick() from the virtual clock")

    monkeypatch.setattr(BarBuilderSet, "start", refuse)


@pytest.fixture
async def rig() -> AsyncIterator[Rig]:
    r = Rig(seed=SEED)
    await r.start()
    try:
        yield r
    finally:
        await r.stop()
