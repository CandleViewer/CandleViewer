"""Fixtures for the E17-Q02 WS chaos suite (real uvicorn + proxy on 127.0.0.1, virtual clock)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from tests.chaos.ingestion._clock import VirtualClock
from tests.chaos.ws._server import Stack, granted
from tests.unit.ws._seq_support import ACC_A, ACC_B


@pytest.fixture
async def stack() -> AsyncIterator[Stack]:
    async with Stack(VirtualClock(), ACC_A, ACC_B) as s:
        yield s


@pytest.fixture
async def stack_on() -> AsyncIterator[Stack]:
    """The same stack as `stack` (`_server.granted`): the name is the one the scenarios that
    needed the budget took while E17-T03's flag existed (#2409 removed it)."""
    async with granted() as s:
        yield s
