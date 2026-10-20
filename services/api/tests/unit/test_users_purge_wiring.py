"""E42-T10 (#2650): the composition root's purge reaper (`build_users_purge_task`) and the port it
ends sessions through (`PurgedSessions`). A session the anonymisation revoked ends as the disable
cascade's do (S4): its sockets close, then B16 REVOKE records it, whose action writes
`auth.session_revoked` (R5); the chart is looked up when a session ends, as it exists only once
`AuthService.start()` ran. The reaper is built on the real backend only, over one store."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from candleviewer.settings import Settings
from candleviewer.storage.repositories.sessions_sqlalchemy import SqlAlchemySessionRepository
from candleviewer.storage.repositories.user_purge_sqlalchemy import SqlAlchemyUserPurgeStore
from candleviewer.storage.retention.users_purge_tasks import UsersPurgeTask
from candleviewer.user_cascade_wiring import PurgedSessions, build_users_purge_task

_SID = uuid.uuid4()
_NOW = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)


class _World:
    """The sink, the session rows and the chart in one log, so a test reads their order."""

    def __init__(self, record: object | None = "row") -> None:
        self.log: list[tuple[Any, ...]] = []
        self.record = record

    async def publish(self, session_id: str, reason: str) -> None:
        self.log.append(("socket", session_id, reason))

    async def find_by_id(self, session_id: str) -> object | None:
        self.log.append(("row", session_id))
        return self.record

    async def revoke(self, record: object, now: datetime, reason: str) -> None:
        self.log.append(("b16", record, now, reason))


def _auth(w: _World) -> Any:
    return SimpleNamespace(step_up=SimpleNamespace(chart=SimpleNamespace(revoke=w.revoke)))


async def test_a_purged_session_closes_its_sockets_then_records_b16_revoke() -> None:
    """As a disable's session (`users.disable.step`): `bye user_disabled` on its sockets, then the
    REVOKE on the session's chart, read from its row, at the anonymisation's instant."""
    w = _World()
    await PurgedSessions(_auth(w), w, w.publish).end(_SID, _NOW)
    assert w.log == [
        ("socket", str(_SID), "user_disabled"),
        ("row", str(_SID)),
        ("b16", "row", _NOW, "user_disabled"),
    ]


async def test_a_purged_session_whose_row_is_gone_fails_after_its_sockets_close() -> None:
    """No row, no chart to record on: the end fails (the reaper counts it) once the sockets are
    closed, and no REVOKE is forged."""
    w = _World(record=None)
    with pytest.raises(LookupError):
        await PurgedSessions(_auth(w), w, w.publish).end(_SID, _NOW)
    assert w.log == [("socket", str(_SID), "user_disabled"), ("row", str(_SID))]


async def test_the_chart_is_looked_up_when_a_session_ends_not_when_built() -> None:
    w, auth = _World(), SimpleNamespace()
    ender = PurgedSessions(auth, w, w.publish)  # before `AuthService.start()`: no step-up yet
    auth.step_up = SimpleNamespace(chart=SimpleNamespace(revoke=w.revoke))
    await ender.end(_SID, _NOW)
    assert w.log[-1] == ("b16", "row", _NOW, "user_disabled")


def test_the_reaper_is_built_on_the_real_backend_only_over_one_store() -> None:
    """One relational repository for the store and the session rows; the app's clock; no I/O."""
    w = _World()
    ports = {"auth": _auth(w), "audit": SimpleNamespace(), "publish_revocation": w.publish}
    assert build_users_purge_task(Settings(), **ports) is None
    task = build_users_purge_task(Settings(storage_backend="real"), clock=lambda: _NOW, **ports)
    assert isinstance(task, UsersPurgeTask) and not task.running
    store, sessions = task._store, task._sessions
    assert isinstance(store, SqlAlchemyUserPurgeStore) and isinstance(sessions, PurgedSessions)
    assert store._clock() == _NOW and store._audit is ports["audit"]
    rows = sessions._rows
    assert isinstance(rows, SqlAlchemySessionRepository)
    assert rows._relational is store._relational
    assert sessions._publish == w.publish
