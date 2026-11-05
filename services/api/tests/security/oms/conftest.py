"""E29-X02 (#982): the live-target guard and the suite's one world per module.

The guard is E28-X03's (`tests/security/e28/conftest.py`, which alone may spell C-13.5's deny-listed
hosts): it aborts the whole run, at collection and again before each module, when the target is
live (a live switch, any exchange-key variable, a host list naming the venue). It names a
variable, never a value.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from candleviewer.statechart.bindings import b16_session
from tests.security.e28.conftest import live_target_refusal, target_env
from tests.security.oms._world import OmsWorld, oms_world


def _abort_if_live() -> None:
    if (why := live_target_refusal(target_env())) is not None:
        pytest.exit(f"E29-X02 security suite refused to run: {why}", returncode=4)


_abort_if_live()  # at collection, before any module of this suite is imported


@pytest.fixture(scope="module", autouse=True)
def _live_guard() -> None:
    """Again before each module: a variable set since collection aborts the run as well."""
    _abort_if_live()


@pytest.fixture(scope="module")
def _oms(_live_guard: None, tmp_path_factory: pytest.TempPathFactory) -> Iterator[OmsWorld]:
    with oms_world(tmp_path_factory.mktemp("bars-state")) as world:
        yield world


@pytest.fixture
def world(_oms: OmsWorld, b16_audit: object) -> OmsWorld:
    """The module's world, its audit index emptied; B16's records land in its audit too."""
    _oms.reset()
    b16_session.set_audit_sink(_oms.pack.audit)
    return _oms
