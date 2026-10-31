"""Fixtures for the E16-Q04 recorder chaos suite (fakes and `tmp_path`: no docker, no sleeps)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

from candleviewer.storage.cold import exporter as exporter_mod
from tests.chaos.recorder._ladder import LadderRig


@pytest.fixture
async def ladder(tmp_path: Path) -> AsyncIterator[LadderRig]:
    rig = LadderRig(tmp_path)
    await rig.start()
    try:
        yield rig
    finally:
        await rig.stop()


@pytest.fixture
def crash_hooks() -> Iterator[None]:
    """The exporter's test-only crash points are disarmed after every test, pass or fail."""
    try:
        yield
    finally:
        exporter_mod._TEST_HOOKS.clear()
