"""One admin world per test module, in the elevation state the module names (`STATE`).

Module scope is deliberate: a world costs one `create_app()`, four enrolments and, for the fresh
and stale states, one step-up per actor and grace class. Its patches are applied through an
explicit `MonkeyPatch` undone at module teardown, so none outlives the module (C-13.7).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import httpx
import pytest

from candleviewer.auth.step_up import GRACE_WINDOW
from candleviewer.statechart.bindings import b16_session
from tests.security.admin._cells import GRACE_CLASSES, STATES
from tests.security.admin._world import AdminWorld, open_admin_world


@pytest.fixture(scope="module")
def admin_world(request: pytest.FixtureRequest) -> Iterator[AdminWorld]:
    state = getattr(request.module, "STATE", "none")
    assert state in STATES, state
    mp = pytest.MonkeyPatch()
    try:
        with open_admin_world(mp) as world:
            if state != "none":
                world.elevate(GRACE_CLASSES)
            if state == "stale":
                world.tick(GRACE_WINDOW + timedelta(seconds=1))  # past every window
            yield world
    finally:
        mp.undo()


@pytest.fixture
def world(admin_world: AdminWorld, b16_audit: object) -> AdminWorld:
    """The module's world, with B16's records flowing into its audit log as `create_app` wires
    them. The root conftest's autouse `b16_audit` gives every test a sink of its own and clears it
    after, so each test points it back here; one log holds every record, as in production."""
    b16_session.set_audit_sink(admin_world.audit)
    return admin_world


@pytest.fixture
def sent(world: AdminWorld, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every request `world.send` makes names its own correlation id, listed here in order (#3990:
    an audit record must carry the id the middleware bound for its request)."""
    ids: list[str] = []
    real = world.send

    def send(actor: str, method: str, path: str, request: Any, **kw: Any) -> httpx.Response:
        cid = str(uuid.uuid4())
        ids.append(cid)
        stamped = {**request, "headers": {**request.get("headers", {}), "X-Correlation-Id": cid}}
        return real(actor, method, path, stamped, **kw)

    monkeypatch.setattr(world, "send", send)
    return ids
