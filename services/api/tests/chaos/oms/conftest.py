"""Fixtures for E29-Q04's OMS chaos scenarios (#1148): the in-process tier runs with no network, no
Docker and on virtual time; the Postgres tier (`_pg.py`, markers `chaos`, `integration` and
`nightly`) on a real node, with wall-time bounds.

Every world a test builds (`_world.World`, `_pg.PgWorld`) must end checked by the oracle
(`_oracle.check`), or the test fails at its teardown (#1148, "The oracle is authoritative"), unless
the test itself failed: that one failure is the report, not a second one on top of it. E29-T05's
s1 to s4 build none."""

from __future__ import annotations

from collections.abc import Generator, Iterator
from typing import Final

import pytest

from tests.chaos.oms._world import BUILT, unchecked

#: Whether the running test's own call failed: set as its report is made, read at its teardown.
_CALL_FAILED: Final = pytest.StashKey[bool]()


def pytest_configure(config: pytest.Config) -> None:
    """Registers the Postgres tier's marker here, as `--strict-markers` is on."""
    config.addinivalue_line(
        "markers",
        "nightly: the OMS chaos Postgres tier, which the merge group's integration step leaves "
        "out and the nightly job selects",
    )


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item,
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    if report.when == "call":
        item.stash[_CALL_FAILED] = report.failed
    return report


@pytest.fixture(autouse=True)
def _every_world_meets_the_oracle(request: pytest.FixtureRequest) -> Iterator[None]:
    BUILT.clear()
    yield
    left = unchecked()
    BUILT.clear()
    if left and not request.node.stash.get(_CALL_FAILED, False):
        pytest.fail(f"{len(left)} world(s) ended without the oracle's check (#1148)")
