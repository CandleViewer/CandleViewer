"""The `w` fixture of the idle-lock route tests: a fresh `World` per test."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from tests.conftest import RecordingAuditSink

from ._world import World, _open


@pytest.fixture
async def w(b16_audit: RecordingAuditSink) -> AsyncIterator[World]:
    world = await _open(b16_audit)
    try:
        yield world
    finally:
        await world.client.aclose()
        await world.step_up.stop()
