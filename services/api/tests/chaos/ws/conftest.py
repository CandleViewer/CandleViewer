"""Fixtures for the E17-Q02 WS chaos suite (real uvicorn + proxy on 127.0.0.1, virtual clock)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from tests.chaos.ingestion._clock import VirtualClock
from tests.chaos.ws._server import Stack, flag_on
from tests.unit.ws._seq_support import ACC_A, ACC_B


@pytest.fixture
async def stack() -> AsyncIterator[Stack]:
    async with Stack(VirtualClock(), ACC_A, ACC_B) as s:
        yield s


@pytest.fixture
async def stack_on() -> AsyncIterator[Stack]:
    """`CV_WS_BACKPRESSURE_ENABLED` on: the default budget (`_server.flag_on`)."""
    async with flag_on() as s:
        yield s
