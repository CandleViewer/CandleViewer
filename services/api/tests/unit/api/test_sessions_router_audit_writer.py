"""The audit writer refusing a session-route record (#2251, C-2.9).

`AuditWriter.emit` raises `AuditUnavailable` (WAL full or unwritable) or `AuditWriterStopped`,
both `AuditError`, while `AuditService.is_active` is still true. At every write-ahead call site
the session routes then answer the fail-closed 503 they already give for an inactive sink, and
change nothing: no rotation, no revocation, no socket closed, no cookie set or cleared. After the
service has acted, a lost outcome record never turns the answer into a 500. Fixed ids and clock,
no network.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from candleviewer.api.sessions import REFRESH_COOKIE, make_session_router
from candleviewer.audit.actions import validate_action
from candleviewer.audit.errors import AuditError
from candleviewer.audit.writer import AuditUnavailable, AuditWriterStopped
from candleviewer.auth.models import MintedSession, RefreshOutcome, UserStatus
from candleviewer.auth.session_service import SessionService
from candleviewer.auth.throttle import PerIpLoginThrottle
from tests.csrf_helpers import arm_csrf
from tests.unit.api._fakes import (
    BASE,
    CSRF_CODEC,
    HASHER,
    NOW,
    AuditService,
    Identity,
    RecordingWriter,
    SessionsAuth,
)
from tests.unit.auth.session_fakes import FakeSessionRepository

_USER = uuid.UUID("00000000-0000-4000-8000-0000000000c1")
_OTHER = uuid.UUID("00000000-0000-4000-8000-0000000000c2")
ErrorFactory = Callable[[], AuditError]
#: What `AuditWriter.emit` raises for a record it cannot make durable. A fresh instance per test.
_WRITER_ERRORS: list[ErrorFactory] = [
    lambda: AuditUnavailable("audit WAL unavailable: OSError"),
    AuditWriterStopped,
]
_ERROR_IDS = ["wal_unavailable", "writer_stopped"]


class _RefusingWriter(RecordingWriter):
    """The started `AuditWriter` refusing records with *error*: `accept` is how many further
    records it still takes (`None`: all), every later one is refused and listed in `refused`."""

    def __init__(self, error: AuditError) -> None:
        super().__init__()
        self.error = error
        self.accept: int | None = None
        self.refused: list[str] = []

    async def emit(self, action: str, **kw: Any) -> None:
        if self.accept is not None:
            if self.accept == 0:
                validate_action(action)  # as the real writer: only a registered action is refused
                self.refused.append(action)
                raise self.error
            self.accept -= 1
        await super().emit(action, **kw)


class _RacedSessionService(SessionService):
    """A competing request rotates the presented token between the router's lookup and its
    `refresh()`: the second call finds the token rotated, revokes the family and raises."""

    async def refresh(self, raw_refresh_token: str, **kw: Any) -> RefreshOutcome:
        await super().refresh(raw_refresh_token, **kw)
        return await super().refresh(raw_refresh_token, **kw)


def _throttle() -> PerIpLoginThrottle:
    return PerIpLoginThrottle(max_attempts=10, window_s=60.0, clock=lambda: 0.0)


class _World:
    def __init__(self, make_error: ErrorFactory | None = None, *, raced: bool = False) -> None:
        self.repo = FakeSessionRepository()
        self.published: list[tuple[str, str]] = []

        async def publish(session_id: str, reason: str) -> None:
            self.published.append((session_id, reason))

        # #2272: the service publishes every revocation; the router publishes nothing.
        factory: type[SessionService] = _RacedSessionService if raced else SessionService
        self.svc = factory(self.repo, HASHER, clock=lambda: NOW, publish_revocation=publish)
        make = make_error or _WRITER_ERRORS[0]
        self.writer = _RefusingWriter(make())
        self.audit = AuditService()  # active: the writer is what refuses
        self.audit.writer = self.writer

        app = FastAPI()
        app.include_router(
            make_session_router(
                SessionsAuth(self.svc),
                self.audit,
                identity=Identity(),
                ip_throttle=_throttle(),
                session_throttle=_throttle(),
                csrf=CSRF_CODEC,
            ),
            prefix="/api/v1",
        )
        # An unhandled error must show as the 500 a client would get, not as a raised exception.
        self.client = TestClient(app, base_url=BASE, raise_server_exceptions=False)

    async def mint(self, user: uuid.UUID = _USER) -> MintedSession:
        minted = await self.svc.mint(str(user))
        arm_csrf(self.client, CSRF_CODEC, minted.session_id)  # the SR-041 pair a browser holds
        return minted

    def refresh(self, token: str) -> httpx.Response:
        # The body token is under test: never replay the cookie an earlier refresh set.
        self.client.cookies.delete(REFRESH_COOKIE, path="/api/v1/auth")
        response: httpx.Response = self.client.post(
            "/api/v1/auth/refresh", json={"refresh_token": token}
        )
        return response

    async def live(self, user: uuid.UUID = _USER) -> set[str]:
        return {str(s.id) for s in await self.repo.find_live_by_user(str(user))}


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize("make_error", _WRITER_ERRORS, ids=_ERROR_IDS)
async def test_refresh_write_ahead_record_refused_is_503_and_rotates_nothing(
    make_error: ErrorFactory,
) -> None:
    w = _World(make_error)
    m = await w.mint()
    w.writer.accept = 0
    with capture_logs() as logs:
        r = w.refresh(m.refresh_token)
    assert r.status_code == 503
    assert r.headers["content-type"].startswith("application/problem+json")
    assert "set-cookie" not in r.headers  # no rotated cookie
    assert w.writer.refused == ["auth.session_refreshed"]
    assert await w.live() == {str(m.session_id)}  # nothing rotated, no successor minted
    assert w.published == []
    (entry,) = [e for e in logs if e["event"] == "auth.session_audit.writer_refused"]
    assert (entry["log_level"], entry["action"], entry["error"]) == (
        "error",
        "auth.session_refreshed",
        type(w.writer.error).__name__,
    )
    assert m.refresh_token not in repr(logs)


@pytest.mark.parametrize("make_error", _WRITER_ERRORS, ids=_ERROR_IDS)
async def test_refresh_reuse_record_refused_is_503_and_the_family_stays_live(
    make_error: ErrorFactory,
) -> None:
    w = _World(make_error)
    m = await w.mint()
    first = w.refresh(m.refresh_token)
    assert first.status_code == 200
    successor = await w.svc.authenticate_access_token(first.json()["tokens"]["access_token"])
    w.writer.accept = 0
    r = w.refresh(m.refresh_token)  # the rotated token again: reuse
    assert r.status_code == 503
    assert w.writer.refused == ["auth.refresh_reuse_detected"]
    assert await w.live() == {str(successor.id)}  # C-2.9: no revocation without the record
    stale = await w.repo.find_by_id(str(m.session_id))
    assert stale is not None and stale.revoked_reason == "rotated"
    assert w.published == []


@pytest.mark.parametrize("make_error", _WRITER_ERRORS, ids=_ERROR_IDS)
async def test_refresh_race_outcome_record_refused_keeps_the_401_and_closes_the_family(
    make_error: ErrorFactory,
) -> None:
    w = _World(make_error, raced=True)
    m = await w.mint()
    w.writer.accept = 1  # the write-ahead record lands; the outcome record is refused
    with capture_logs() as logs:
        r = w.refresh(m.refresh_token)
    assert r.status_code == 401
    assert r.json()["detail"] == "refresh_token_invalid"
    assert w.writer.refused == ["auth.refresh_reuse_detected"]
    assert await w.live() == set()  # the service revoked the whole family
    family = set(w.repo.sessions)
    assert len(family) == 2
    assert {sid for sid, _ in w.published} == family  # every socket still closes
    assert {reason for _, reason in w.published} == {"rotation_reuse"}  # the service publishes
    (lost,) = [e for e in logs if e["event"] == "auth.refresh_reuse_detected.audit_unavailable"]
    assert (lost["log_level"], lost["session_id"]) == ("error", str(m.session_id))


@pytest.mark.parametrize("make_error", _WRITER_ERRORS, ids=_ERROR_IDS)
async def test_refresh_refusal_record_of_a_disabled_user_refused_keeps_the_401_and_logs_it(
    make_error: ErrorFactory,
) -> None:
    """#2911: the user was disabled with this session live. The write-ahead intent lands, the
    refusal record is refused: the 401 stands (never a 500), nothing is rotated, minted or
    published, and the lost record is logged."""
    w = _World(make_error)
    m = await w.mint()
    w.repo.user_statuses[str(_USER)] = UserStatus.DISABLED
    w.writer.accept = 1  # the write-ahead record lands; the refusal record is refused
    with capture_logs() as logs:
        r = w.refresh(m.refresh_token)
    assert (r.status_code, r.json()["detail"]) == (401, "refresh_token_invalid")
    assert "set-cookie" not in r.headers
    assert w.writer.refused == ["auth.session_refreshed"]
    assert await w.live() == {str(m.session_id)} and len(w.repo.sessions) == 1
    assert w.published == []
    (lost,) = [e for e in logs if e["event"] == "auth.session_refresh_refused.audit_unavailable"]
    assert (lost["log_level"], lost["session_id"]) == ("error", str(m.session_id))


@pytest.mark.parametrize(
    ("all_sessions", "accept", "refused"),
    [
        (False, 0, "auth.logout"),
        (False, 1, "auth.session_revoked"),
        (True, 0, "auth.logout"),
        (True, 3, "auth.session_revoked"),
    ],
)
async def test_logout_record_refused_is_503_and_revokes_nothing(
    all_sessions: bool, accept: int, refused: str
) -> None:
    w = _World()
    a = await w.mint()
    await w.mint()
    await w.mint()
    before = await w.live()
    w.writer.accept = accept
    r = w.client.post(
        "/api/v1/auth/logout", json={"all_sessions": all_sessions}, headers=_h(a.access_token)
    )
    assert r.status_code == 503
    assert r.headers["content-type"].startswith("application/problem+json")
    assert "set-cookie" not in r.headers  # the cookies stay: the session was not ended
    assert w.writer.refused == [refused]
    assert await w.live() == before and len(before) == 3
    assert w.published == []


@pytest.mark.parametrize("make_error", _WRITER_ERRORS, ids=_ERROR_IDS)
@pytest.mark.parametrize("target", ["other", "own"])
async def test_revoke_own_session_record_refused_is_503_and_keeps_it(
    make_error: ErrorFactory, target: str
) -> None:
    w = _World(make_error)
    a = await w.mint()
    b = await w.mint()
    w.writer.accept = 0
    victim = b if target == "other" else a
    r = w.client.delete(f"/api/v1/me/sessions/{victim.session_id}", headers=_h(a.access_token))
    assert r.status_code == 503
    assert "set-cookie" not in r.headers  # not even the caller's own cookies are cleared
    assert w.writer.refused == ["auth.session_revoked"]
    assert await w.live() == {str(a.session_id), str(b.session_id)}
    assert w.published == []


async def test_revoke_foreign_session_with_the_writer_refusing_is_still_the_plain_404() -> None:
    w = _World()
    mine = await w.mint(_USER)
    theirs = await w.mint(_OTHER)
    w.writer.accept = 0
    foreign = w.client.delete(
        f"/api/v1/me/sessions/{theirs.session_id}", headers=_h(mine.access_token)
    )
    unknown = w.client.delete(f"/api/v1/me/sessions/{uuid.uuid4()}", headers=_h(mine.access_token))
    assert foreign.status_code == unknown.status_code == 404
    assert foreign.json() == unknown.json()  # the ownership check answers before any audit write
    assert w.writer.refused == [] and w.writer.events == []
    assert await w.live(_OTHER) == {str(theirs.session_id)}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/auth/logout"),
        ("DELETE", f"/api/v1/me/sessions/{uuid.UUID(int=7)}"),
        ("POST", "/api/v1/auth/refresh"),
    ],
)
async def test_unauthenticated_request_with_the_writer_refusing_is_401_not_503(
    method: str, path: str
) -> None:
    w = _World()
    w.writer.accept = 0  # the sink's state is not observable without a session
    assert w.client.request(method, path).status_code == 401
    assert w.writer.refused == []
