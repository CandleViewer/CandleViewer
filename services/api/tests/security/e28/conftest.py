"""E28-X03 (#976): the live-target guard and the suite's one world per module.

The guard (`_guard.py`, the ticket's Security notes) aborts the whole run, at collection and
again before each module, when the target is live: this suite never runs against a live UID.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from candleviewer.statechart.bindings import b16_session
from tests.security.e28._guard import live_target_refusal
from tests.security.e28._world import E28World, e28_world


def _abort_if_live() -> None:
    if (why := live_target_refusal(os.environ)) is not None:
        pytest.exit(f"E28-X03 security suite refused to run: {why}", returncode=4)


_abort_if_live()  # at collection, before any module of this suite is imported


@pytest.fixture(scope="module", autouse=True)
def _live_guard() -> None:
    """Again before each module: a variable set since collection aborts the run as well."""
    _abort_if_live()


@pytest.fixture(scope="module")
def _e28(_live_guard: None) -> Iterator[E28World]:
    with e28_world() as world:
        yield world


@pytest.fixture
def world(_e28: E28World, b16_audit: object) -> E28World:
    """The module's world, reset: the stores as seeded and an empty audit log."""
    _e28.reset()
    b16_session.set_audit_sink(_e28.writes.world.audit)
    return _e28
