"""#5512 (C-2.9): the routes over a B16 chart that cannot record.

A step-up on a stale chart (one revoked over a live row) answers `503 audit_unavailable` with the
grant ended and no success record, and the retry records as any step-up does. An Owner's revoke of
one session (`DELETE /users/{userId}/sessions/{sessionId}`, `revokeUserSession`) whose bound expires
while B16 records it rolls back with the session's chart dropped, so the session's next step-up
records. Over `test_step_up_router._build`'s step-up world, on the test's own loop; `LoopClock`
moves the loop's clock past the bound. No network, no sleeps.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from functools import partial
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.api.users import ADMIN_REVOKE_REASON
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.session_service import OWNER_REVOKE_AUDIT_TIMEOUT_S
from candleviewer.statechart.bindings import b16_session
from candleviewer.storage.repositories.user_roles_sqlalchemy import bounded_write_ahead
from tests.unit.api.test_role_change_revocation import _http, _role_route
from tests.unit.api.test_step_up_rotation_router import _chart, _live, _rows, _users_body
from tests.unit.api.test_step_up_router import _build
from tests.unit.auth.session_fakes import FakeSessionRepository, LoopClock

_ROTATION = [
    ("auth.step_up_granted", "users"),
    ("auth.session_revoked", "rotated"),
    ("auth.session_created", None),
]


def _auth_records(calls: list[dict[str, Any]]) -> list[tuple[str, str | None]]:
    return [(x["action"], x.get("reason")) for x in calls if x["action"][:5] == "auth."]


async def test_a_step_up_on_a_stale_chart_answers_503_with_the_grant_ended() -> None:
    """The Gherkin of #5512: the send raises a typed error, the step-up answers 503 with the grant
    ended and nothing elevated or rotated, and no success record is written. The chart is
    dropped, so the next step-up (a fresh code) records as any other."""
    c, em, seed, clock, user = await _build()
    (session,) = _live(c, user)
    sid = str(session.id)
    await _chart(c).record(session, clock(), "REVOKE", reason="admin")  # revoked over a live row
    mark = len(em.calls)
    with capture_logs() as logs:
        async with _http(c) as http:
            r = await http.post("/auth/step-up", json=_users_body(seed, clock))
    assert (r.status_code, r.json()["code"]) == (503, "audit_unavailable")
    row = _rows(c).sessions[sid]
    assert row.revoked_at is None and "users" not in row.step_up_elevations
    assert em.calls[mark:] == []
    (line,) = [e for e in logs if e["event"] == "auth.step_up.grant_unrecorded"]
    assert (line["session_id"], line["error"]) == (sid, "SessionChartUnrecorded")
    assert _chart(c).interpreter(sid) is None
    clock.now += timedelta(seconds=30)  # a fresh TOTP time step: the first code is spent
    async with _http(c) as http:
        ok = await http.post("/auth/step-up", json=_users_body(seed, clock))
    assert ok.status_code == 200, ok.text
    assert _auth_records(em.calls[mark:]) == _ROTATION


class _SlowOwnerRevocation:
    """B16's sink: the Owner's revocation record (`auth.session_revoked`, reason `admin`) waits for
    `release`, as a slow audit writer does; every other record goes straight to *sink*."""

    def __init__(self, sink: Any) -> None:
        self.sink, self.parked, self.release = sink, asyncio.Event(), asyncio.Event()

    async def emit(self, action: str, **kwargs: Any) -> None:
        if (action, kwargs.get("reason")) == ("auth.session_revoked", ADMIN_REVOKE_REASON):
            self.parked.set()
            await self.release.wait()
        await self.sink.emit(action, **kwargs)


async def _bounded_revoke_by_owner(
    rows: FakeSessionRepository,
    session_id: str,
    *,
    user_id: str,
    actor_user_id: str,
    reason: str,
    now: datetime,
    write_ahead: Callable[[SessionRecord], Awaitable[None]],
    audit_timeout_s: float,
) -> SessionRecord | None:
    """The fake's `revoke_by_owner` under the Postgres store's bound on its hook
    (`bounded_write_ahead`): past it, the unit of work rolls back with nothing revoked."""
    session = rows.sessions.get(session_id)
    if session is None or session.revoked_at is not None or str(session.user_id) != user_id:
        return None
    await bounded_write_ahead(write_ahead(session), audit_timeout_s)
    return await rows.revoke(session_id, reason=reason, now=now)


async def test_an_owner_revoke_past_its_bound_drops_the_chart_and_the_next_step_up_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Owner's revoke bound (`OWNER_REVOKE_AUDIT_TIMEOUT_S`) expires while B16 records the
    revocation: `503 audit_unavailable`, the session stays live, and its chart is dropped, not
    kept. Once the writer answers, the session's next step-up records as any other does."""
    c, em, seed, clock, user = await _build()
    (session,) = _live(c, user)
    sid, rows = str(session.id), _rows(c)
    monkeypatch.setattr(rows, "revoke_by_owner", partial(_bounded_revoke_by_owner, rows))
    _role_route(c, "patch", user, clock, em)  # the admin router, `revokeUserSession` among them
    sink, loop_clock = _SlowOwnerRevocation(em), LoopClock(monkeypatch)
    b16_session.set_audit_sink(sink)
    async with _http(c) as http:
        revoking = asyncio.create_task(http.delete(f"/users/{user}/sessions/{sid}"))
        await asyncio.wait_for(sink.parked.wait(), timeout=5)
        loop_clock.advance(OWNER_REVOKE_AUDIT_TIMEOUT_S)  # the bound expires, not the real clock
        r = await asyncio.wait_for(revoking, timeout=5)
    assert (r.status_code, r.json()["code"]) == (503, "audit_unavailable")
    assert rows.sessions[sid].revoked_at is None
    assert _chart(c).interpreter(sid) is None
    sink.release.set()  # the audit writer answers at last
    async with _http(c) as http:
        ok = await http.post("/auth/step-up", json=_users_body(seed, clock))
    assert ok.status_code == 200, ok.text
    assert _auth_records(em.calls) == _ROTATION
