"""Break-glass notice on the WS `system` topic (E09-S11 #2119 slice 6, decision O4, scenario S9).

`BreakGlassNotice` caches whether an `auth`/`break_glass_used` event is unresolved: it reads the
port at start-up (bounded) and then every minute, never per connection, and the gateway's
first-`auth_ok` hook reads only the cached flag. The S9 tests drive the real `create_app()` wiring
through a socket with the store faked; the SQL statement is checked here against a scripted unit
of work and on real Postgres in tests/integration/auth/test_break_glass_reset_pg.py (CI only).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
import structlog
from fastapi.testclient import TestClient

from candleviewer import app as app_module
from candleviewer.app import AppContext, create_app
from candleviewer.auth.break_glass_notice import (
    BREAK_GLASS_NOTICE_REASON,
    REFRESH_INTERVAL_S,
    BreakGlassEvents,
    BreakGlassNotice,
)
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.auth.service import AuthService
from candleviewer.settings import Environment, Settings
from candleviewer.storage.repositories.break_glass_sqlalchemy import SqlAlchemyBreakGlassEvents
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.unit.ws._seq_support import validate

_ORIGIN = "http://testserver"  # the TestClient's own origin (§2.5 allow-list)
_USER = uuid.UUID(int=0x2119)
_EXPIRES = datetime(2100, 1, 1, tzinfo=UTC)  # far future: expiry is tested elsewhere
_TASK = "break-glass-notice-refresh"


class _Events:
    """`BreakGlassEvents` fake: the scripted answer, or the error to raise."""

    def __init__(self, answer: bool | BaseException) -> None:
        self.answer = answer
        self.reads = 0

    async def has_unresolved_break_glass(self) -> bool:
        self.reads += 1
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer


async def _authenticate(token: str) -> tuple[str, uuid.UUID, datetime]:
    if token != "tok":
        raise PermissionError("bad token")
    return "sess-1", _USER, _EXPIRES


@contextmanager
def _app(
    monkeypatch: pytest.MonkeyPatch, events: _Events, role: str = "manager"
) -> Iterator[tuple[TestClient, AuthService]]:
    """`create_app()` with the auth module over `events`, started as the supervisor starts it."""
    auth = AuthService(break_glass_events=events)
    monkeypatch.setattr(app_module, "build_auth_service", lambda *_a, **_k: auth)

    async def principal(user_id: uuid.UUID) -> PrincipalSnapshot:
        return PrincipalSnapshot(user_id, frozenset({role}), frozenset())

    settings = Settings(
        environment=Environment.DEMO, ws_shutdown_grace_ms=0, allowed_origins=_ORIGIN
    )
    app = create_app(settings, ws_authenticate=_authenticate, snapshot_loader=principal)
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        assert client.portal is not None
        client.portal.call(auth.start, app.state.app_context)
        try:
            yield client, auth
        finally:
            client.portal.call(auth.stop, 1.0)


@contextmanager
def _authenticated(client: TestClient) -> Iterator[Any]:
    """A socket whose next frame is the one right after its first `auth_ok`."""
    with client.websocket_connect(
        "/ws", subprotocols=["cv.v1.json"], headers={"origin": _ORIGIN}
    ) as ws:
        ws.send_json({"t": "hello", "id": "h", "p": {"clock_ms": 1}})
        assert ws.receive_json()["t"] == "welcome"
        ws.send_json({"t": "auth", "id": "a", "p": {"access_token": "tok"}})
        assert ws.receive_json()["t"] == "auth_ok"
        yield ws


def _queued(ws: Any) -> list[dict[str, Any]]:
    """Every frame queued so far, up to the reply to a fresh `ping` (heartbeats skipped)."""
    ws.send_json({"t": "ping", "id": "p"})
    frames = []
    while (frame := ws.receive_json())["t"] != "pong":
        if frame["t"] != "ping":
            frames.append(frame)
    return frames


@pytest.mark.parametrize("role", ["owner", "manager", "viewer"])
def test_notice_after_auth_ok_while_unresolved(monkeypatch: pytest.MonkeyPatch, role: str) -> None:
    with _app(monkeypatch, _Events(True), role) as (client, _), _authenticated(client) as ws:
        (frame,) = _queued(ws)  # one notice per first authentication
    validate(frame)  # the §15.9 `system` schema
    assert frame["ch"] == "system" and set(frame["p"]) == {"kind", "severity", "message", "reason"}
    body = frame["p"]  # role-neutral: the same frame for every role, naming no user
    assert (body["kind"], body["severity"]) == ("notice", "critical")
    assert body["reason"] == BREAK_GLASS_NOTICE_REASON == "auth.break_glass_used"
    assert str(_USER) not in str(frame)


def test_no_notice_when_resolved_or_reauth(monkeypatch: pytest.MonkeyPatch) -> None:
    events = _Events(True)
    with _app(monkeypatch, events) as (client, auth):
        with _authenticated(client) as ws:
            assert [f["p"]["reason"] for f in _queued(ws)] == [BREAK_GLASS_NOTICE_REASON]
            ws.send_json({"t": "auth", "id": "b", "p": {"access_token": "tok"}})
            assert ws.receive_json()["t"] == "auth_ok"  # an in-place re-auth ...
            assert _queued(ws) == []  # ... does not repeat it
        events.answer = False  # the Owner resolved the event
        assert client.portal is not None
        client.portal.call(auth.break_glass_notice.refresh)
        with _authenticated(client) as ws:
            assert _queued(ws) == []


def test_state_read_failure_never_blocks_auth_ok_and_is_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = _Events(ConnectionRefusedError("db down at 10.0.0.5"))
    with structlog.testing.capture_logs() as logs, _app(monkeypatch, events) as (client, auth):
        notice = auth.break_glass_notice
        assert (notice.read_failures, notice.unresolved) == (1, None)  # counted, nothing guessed
        with _authenticated(client) as ws:  # auth_ok still arrives ...
            assert _queued(ws) == []  # ... with no notice
    failed = [e for e in logs if e["event"] == "auth.break_glass_state_read_failed"]
    assert [(e["log_level"], e["error"], e["failures"]) for e in failed] == [
        ("error", "ConnectionRefusedError", 1)
    ]
    assert "10.0.0.5" not in repr(logs)  # the class only, never the message


async def test_failed_refresh_keeps_the_last_state_read() -> None:
    events = _Events(True)
    source = BreakGlassNotice(events)
    await source.refresh()
    events.answer = OSError("connection reset")
    await source.refresh()
    assert (source.unresolved, source.read_failures, len(source.notices())) == (True, 1, 1)


async def test_hung_read_is_bounded_by_the_timeout() -> None:
    class _Hung:
        async def has_unresolved_break_glass(self) -> bool:
            await asyncio.Event().wait()
            return True

    source = BreakGlassNotice(_Hung(), timeout_s=0.0)  # a deadline already due
    async with asyncio.timeout(5):  # an unbounded wait on the read fails here
        await source.refresh()
    assert (source.unresolved, source.read_failures, source.notices()) == (None, 1, [])


async def test_cancellation_is_never_swallowed() -> None:
    source = BreakGlassNotice(_Events(asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        await source.refresh()
    assert source.read_failures == 0


async def test_refreshes_every_interval_until_stopped() -> None:
    events, parked, sleeps = _Events(True), asyncio.Event(), []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 2:  # park the loop after its first periodic read
            parked.set()
            await asyncio.Event().wait()

    source = BreakGlassNotice(events, sleep=sleep)
    await source.start()
    assert (events.reads, len(source.notices())) == (1, 1)  # preloaded before start returns
    events.answer = False
    async with asyncio.timeout(5):
        await parked.wait()
    assert (events.reads, sleeps, source.notices()) == (2, [REFRESH_INTERVAL_S] * 2, [])
    (task,) = [t for t in asyncio.all_tasks() if t.get_name() == _TASK]
    await source.stop()
    assert task.cancelled()


async def test_auth_module_starts_and_stops_the_refresh() -> None:
    auth = AuthService(break_glass_events=_Events(True))
    await auth.start(cast(AppContext, None))  # the context is read only to wire MFA
    (task,) = [t for t in asyncio.all_tasks() if t.get_name() == _TASK]
    assert len(auth.break_glass_notice.notices()) == 1
    await auth.stop(1.0)
    assert task.cancelled()


async def test_without_a_store_nothing_is_read_or_sent() -> None:
    source = BreakGlassNotice(None)  # the fake backend: no `system_events` table
    await source.start()
    await source.refresh()
    assert not [t for t in asyncio.all_tasks() if t.get_name() == _TASK]
    assert (source.unresolved, source.read_failures, source.notices()) == (None, 0, [])
    await source.stop()


class _Rel:
    """One-statement unit of work answering `row`; records the SQL."""

    def __init__(self, row: bool) -> None:
        self.row, self.sql = row, list[str]()

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[SimpleNamespace]:
        async def execute(stmt: object) -> SimpleNamespace:
            self.sql.append(" ".join(str(stmt).split()))
            return SimpleNamespace(scalar_one=lambda: self.row)

        yield SimpleNamespace(session=SimpleNamespace(execute=execute))


@pytest.mark.parametrize("row", [True, False])
async def test_store_reads_one_exists_over_unresolved_events(row: bool) -> None:
    rel = _Rel(row)
    # cast: `_Rel` is a structural fake of the one method the reader calls.
    store: BreakGlassEvents = SqlAlchemyBreakGlassEvents(cast(SqlAlchemyRelationalRepository, rel))
    assert not hasattr(store, "reset_owner_mfa")  # cv-api's side can only read
    assert await store.has_unresolved_break_glass() is row
    assert rel.sql == [
        "SELECT EXISTS (SELECT 1 FROM system_events WHERE component = 'auth' "
        "AND kind = 'break_glass_used' AND resolved_at IS NULL)"
    ]
