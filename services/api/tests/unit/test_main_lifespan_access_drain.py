"""#2648 S9c: the ASGI lifespan drains the grant pushes in flight before the audit module stops.

A push writes WS audit rows, and the WS registry's own bounds are all that end one that outlived
its request, so the drain at shutdown is what waits for it. Behavioural, through the
`test_main_lifespan.py` harness as `test_main_lifespan_csrf_drain.py` is: the fake `audit` module
records whether the push had ended when it was stopped, so removing or reordering the drain fails
here.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI

from candleviewer.admin.account_access import AccountAccessService
from candleviewer.main import _lifespan
from candleviewer.storage.repositories.account_access import AccessChange, AccessLevel
from tests.unit.admin.test_account_access_service import _Positions
from tests.unit.test_main_lifespan import _fake_ctx

_USER, _ACCOUNT = uuid.uuid4(), uuid.uuid4()
_TURNS = 5  # loop turns the push needs after its release: more than shutdown yields on its own


class _Store:
    """`GrantStore`: a replacement that adds a grant, so a push is due."""

    async def replace_grants(
        self, user_id: uuid.UUID, grants: Mapping[uuid.UUID, AccessLevel], **_kw: Any
    ) -> AccessChange:
        return AccessChange(user_id, {}, dict(grants))


class _Push:
    """`WsEvents.grants_changed`: it ends once released, after a few turns of the loop."""

    def __init__(self, order: list[str]) -> None:
        self.release, self.order = asyncio.Event(), order

    async def grants_changed(self, user_id: uuid.UUID) -> None:
        await self.release.wait()
        for _ in range(_TURNS):
            await asyncio.sleep(0)
        self.order.append("push ended")


class _AuditModule:
    def __init__(self, order: list[str]) -> None:
        self.order = order

    async def start(self, ctx: object) -> None:
        return None

    async def stop(self, grace_s: float) -> None:
        self.order.append("audit stopped")


async def test_lifespan_drains_in_flight_grant_pushes_before_the_audit_module_stops() -> None:
    order: list[str] = []
    push = _Push(order)
    service = AccountAccessService(_Store(), push, positions=_Positions(0), push_wait_s=0.0)
    app, ctx = FastAPI(), _fake_ctx()
    ctx.audit = _AuditModule(order)
    app.state.app_context, app.state.account_access_service = ctx, service
    # The request stops waiting at once (a zero wait), so the push is still in flight at shutdown.
    await service.replace(
        _USER, {_ACCOUNT: "read"}, actor_user_id=uuid.uuid4(), acknowledge_unknown_positions=False
    )
    async with _lifespan(app):
        # It is released at the next turn of the loop, which only the drain gives it before the
        # audit module stops (the fake modules never suspend).
        asyncio.get_running_loop().call_soon(push.release.set)

    assert order == ["push ended", "audit stopped"]
