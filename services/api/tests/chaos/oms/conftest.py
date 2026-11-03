"""Fixtures for E29-Q04's OMS chaos scenarios (#1148): no network, no Docker, virtual time.

Every world a test builds (`_world.World`) must end checked by the oracle (`_oracle.check`), or the
test fails at its teardown (#1148, "The oracle is authoritative"). E29-T05's s1 to s4 build none."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.chaos.oms._world import BUILT, unchecked


@pytest.fixture(autouse=True)
def _every_world_meets_the_oracle() -> Iterator[None]:
    BUILT.clear()
    yield
    left = unchecked()
    BUILT.clear()
    if left:
        pytest.fail(f"{len(left)} world(s) ended without the oracle's check (#1148)")
