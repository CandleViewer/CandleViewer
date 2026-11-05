"""E29-Q02 (#1147, C4a): the conformance world, one per module, and the E29-Q02 report registered
for a run of this directory."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.contract.e29_q02_report import pytest_configure  # noqa: F401 (E29-Q02's report)
from tests.qa.oms._world import OmsWorld, oms_world


@pytest.fixture(scope="module")
def _oms(tmp_path_factory: pytest.TempPathFactory) -> Iterator[OmsWorld]:
    with oms_world(tmp_path_factory.mktemp("bars-state")) as world:
        yield world


@pytest.fixture
def world(_oms: OmsWorld) -> Iterator[OmsWorld]:
    """The module's world, its venue as the test before left it, undone once the test is over.
    A test runs once in it: an order a test leaves `unknown` keeps its symbol's position key, so
    the same test again would be refused (its fills' ids are the order's own, so they are not)."""
    yield _oms
    _oms.reset()
