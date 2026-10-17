"""The audit writer refusing a session-route record (#2251, #2914, C-2.9).

`AuditWriter.emit` raises `AuditUnavailable` (WAL full or unwritable) or `AuditWriterStopped`,
both `AuditError`, while `AuditService.is_active` is still true. At every write-ahead call site
the session routes then answer the fail-closed 503 and change nothing. After the service has
acted, a lost outcome record never turns the answer into a 500: it is counted
(`auth_audit_outcome_lost_total`) and logged. Fixed user ids, unknown-session id, client address
and clock; the session ids and tokens are the service's own random ones, compared by value, never
by position.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.api.csrf import AUDIT_TIMEOUT_S
from candleviewer.api.sessions import (
    LOGOUT_INTENT_SESSION_IDS_MAX,
    REFRESH_COOKIE,
    make_session_router,
)
from candleviewer.audit.actions import validate_action
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.audit.redact import redact
from candleviewer.audit.writer import AuditUnavailable, AuditWriterStopped
from candleviewer.auth.models import (
    MintedSession,
    RefreshOutcome,
    SessionRecord,
    SessionView,
    UserStatus,
)
from candleviewer.auth.session_service import SessionService
from candleviewer.auth.throttle import PerIpLoginThrottle
from tests.csrf_helpers import arm_csrf, csrf_headers
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
_UNKNOWN_SESSION = uuid.UUID("00000000-0000-4000-8000-0000000000d1")
_CLIENT_IP = "198.51.100.7"  # documentation range (RFC 5737): the address every request comes from
ErrorFactory = Callable[[], Exception]
#: What `AuditWriter.emit` raises for a record it cannot make durable. A fresh instance per test.
_WRITER_ERRORS: list[ErrorFactory] = [
    lambda: AuditUnavailable("audit WAL unavailable: OSError"),
    AuditWriterStopped,
]
_ERROR_IDS = ["wal_unavailable", "writer_stopped"]
_LOST_EVENT = "auth.session_audit.outcome_lost"


def _count(name: str, **labels: str) -> float:
    """A counter's value on the process-default registry (series are never reset)."""
    return float(REGISTRY.get_sample_value(name, labels) or 0.0)


def _outcome_lost(action: str) -> float:
    return _count("auth_audit_outcome_lost_total", action=action)


class _RefusingWriter(RecordingWriter):
    """The started `AuditWriter` refusing records with *error*: `accept` is how many further
    records it still takes (`None`: all), every later one is refused and listed in `refused`.
    `probe`, when set, snapshots the live sessions of `_USER` at each accepted record
    (`live_at`); `after_accept` runs after each accepted one."""

    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error
        self.accept: int | None = None
        self.refused: list[str] = []
        self.probe: Callable[[], Awaitable[set[str]]] | None = None
        self.live_at: list[tuple[str, frozenset[str]]] = []
        self.after_accept: Callable[[str], None] | None = None

    async def emit(self, action: str, **kw: Any) -> None:
        if self.accept is not None:
            if self.accept == 0:
                validate_action(action)  # as the real writer: only a registered action is refused
                self.refused.append(action)
                raise self.error
            self.accept -= 1
        if self.probe is not None:
            self.live_at.append((action, frozenset(await self.probe())))
        await super().emit(action, **kw)
        if self.after_accept is not None:
            self.after_accept(action)


class _RacedSessionService(SessionService):
    """A competing request rotates the presented token between the router's lookup and its
    `refresh()`: the second call finds the token rotated, revokes the family and raises."""

    async def refresh(self, raw_refresh_token: str, **kw: Any) -> RefreshOutcome:
        await super().refresh(raw_refresh_token, **kw)
        return await super().refresh(raw_refresh_token, **kw)


class _LateSignInService(SessionService):
    """A sign-in lands after the router read the target ids and before `revoke_all`."""

    late: MintedSession | None = None

    async def list_sessions(
        self, user_id: str, *, current_session_id: str | None = None
    ) -> tuple[SessionView, ...]:
        views = await super().list_sessions(user_id, current_session_id=current_session_id)
        if self.late is None:
            self.late = await self.mint(user_id)
        return views


class _ConcurrentlyRevokedService(SessionService):
    """Another request revokes the session first, so the router's `revoke` finds nothing."""

    async def revoke(self, session_id: str, *, reason: str) -> SessionRecord | None:
        await super().revoke(session_id, reason="admin")
        return await super().revoke(session_id, reason=reason)


class _LoopClock:
    """The running loop's clock plus a skew the test advances: an `asyncio.timeout` fires when the
    test says so and nothing waits; other timers keep real time, so a hang still fails."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        loop = asyncio.get_running_loop()
        real, self._skew = loop.time, 0.0
        monkeypatch.setattr(loop, "time", lambda: real() + self._skew)

    def advance(self, seconds: float) -> None:
        self._skew += seconds


def _throttle() -> PerIpLoginThrottle:
    return PerIpLoginThrottle(max_attempts=10, window_s=60.0, clock=lambda: 0.0)


class _World:
    def __init__(
        self,
        make_error: ErrorFactory | None = None,
        *,
        service: type[SessionService] = SessionService,
    ) -> None:
        self.repo = FakeSessionRepository()
        self.published: list[tuple[str, str]] = []
        #: Runs inside each revocation publish, after the revocation is committed.
        self.on_publish: Callable[[], Awaitable[None]] | None = None

        async def publish(session_id: str, reason: str) -> None:
            self.published.append((session_id, reason))
            if self.on_publish is not None:
                await self.on_publish()

        # #2272: the service publishes every revocation; the router publishes nothing.
        self.svc = service(self.repo, HASHER, clock=lambda: NOW, publish_revocation=publish)
        make = make_error or _WRITER_ERRORS[0]
        self.writer = _RefusingWriter(make())
        self.writer.probe = self.live
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
        self.client = TestClient(
            app, base_url=BASE, raise_server_exceptions=False, client=(_CLIENT_IP, 50000)
        )

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

    def logout(self, token: str, *, all_sessions: bool) -> httpx.Response:
        response: httpx.Response = self.client.post(
            "/api/v1/auth/logout", json={"all_sessions": all_sessions}, headers=_h(token)
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
    w = _World(make_error, service=_RacedSessionService)
    m = await w.mint()
    w.writer.accept = 1  # the write-ahead record lands; the outcome record is refused
    lost_before = _outcome_lost("auth.refresh_reuse_detected")
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
    (lost,) = [e for e in logs if e["event"] == _LOST_EVENT]
    assert (lost["log_level"], lost["action"], lost["session_id"]) == (
        "error",
        "auth.refresh_reuse_detected",
        str(m.session_id),
    )
    assert lost["error"] == type(w.writer.error).__name__
    assert _outcome_lost("auth.refresh_reuse_detected") - lost_before == 1  # counted, so it pages
    assert m.refresh_token not in repr(logs)


async def test_refresh_race_with_a_healthy_sink_writes_the_critical_denial_row() -> None:
    """The row that closes a concurrent-refresh race is a CRITICAL denial of the presented session
    from the caller's address; a row downgraded or written without its address must fail here."""
    w = _World(service=_RacedSessionService)
    m = await w.mint()
    lost_before = _outcome_lost("auth.refresh_reuse_detected")
    assert w.refresh(m.refresh_token).status_code == 401
    intent, outcome = w.writer.events  # the write-ahead record, then the race outcome
    assert outcome["action"] == "auth.refresh_reuse_detected"
    assert (outcome["outcome"], outcome["severity"]) == (AuditOutcome.DENIED, Severity.CRITICAL)
    assert (outcome["reason"], str(outcome["session_id"])) == ("rotation_reuse", str(m.session_id))
    assert outcome["actor_ip"] == intent["actor_ip"] == _CLIENT_IP
    assert _outcome_lost("auth.refresh_reuse_detected") == lost_before  # written: nothing lost


@pytest.mark.parametrize("make_error", _WRITER_ERRORS, ids=_ERROR_IDS)
async def test_refresh_refusal_record_of_a_disabled_user_refused_keeps_the_401_and_counts_it(
    make_error: ErrorFactory,
) -> None:
    """#2911: the user was disabled with this session live. The write-ahead intent lands, the
    refusal record is refused: the 401 stands (never a 500), nothing is rotated, minted or
    published, and the lost record is counted and logged like any outcome record (#2914)."""
    w = _World(make_error)
    m = await w.mint()
    w.repo.user_statuses[str(_USER)] = UserStatus.DISABLED
    w.writer.accept = 1  # the write-ahead record lands; the refusal record is refused
    lost_before = _outcome_lost("auth.session_refreshed")
    with capture_logs() as logs:
        r = w.refresh(m.refresh_token)
    assert (r.status_code, r.json()["detail"]) == (401, "refresh_token_invalid")
    assert "set-cookie" not in r.headers
    assert w.writer.refused == ["auth.session_refreshed"]
    assert await w.live() == {str(m.session_id)} and len(w.repo.sessions) == 1
    assert w.published == []
    (lost,) = [e for e in logs if e["event"] == _LOST_EVENT]
    assert (lost["log_level"], lost["action"], lost["session_id"], lost["error"]) == (
        "error",
        "auth.session_refreshed",
        str(m.session_id),
        type(w.writer.error).__name__,
    )
    assert _outcome_lost("auth.session_refreshed") - lost_before == 1  # counted, so it tickets


async def test_disabled_user_refresh_with_a_healthy_sink_writes_the_warning_denial_row() -> None:
    """The same refusal row when the sink works: a WARNING denial of the presented session from
    the caller's address, after the write-ahead record of the attempt."""
    w = _World()
    m = await w.mint()
    w.repo.user_statuses[str(_USER)] = UserStatus.DISABLED
    lost_before = _outcome_lost("auth.session_refreshed")
    assert w.refresh(m.refresh_token).status_code == 401
    intent, outcome = w.writer.events
    assert (intent["action"], intent["outcome"]) == ("auth.session_refreshed", AuditOutcome.SUCCESS)
    assert outcome["action"] == "auth.session_refreshed"
    assert (outcome["outcome"], outcome["severity"]) == (AuditOutcome.DENIED, Severity.WARNING)
    assert (outcome["reason"], str(outcome["session_id"])) == ("user_disabled", str(m.session_id))
    assert outcome["actor_ip"] == intent["actor_ip"] == _CLIENT_IP
    assert _outcome_lost("auth.session_refreshed") == lost_before  # written: nothing lost


@pytest.mark.parametrize("make_error", _WRITER_ERRORS, ids=_ERROR_IDS)
@pytest.mark.parametrize("all_sessions", [False, True])
async def test_logout_intent_record_refused_is_503_and_a_retry_writes_exactly_one_set(
    make_error: ErrorFactory, all_sessions: bool
) -> None:
    w = _World(make_error)
    a = await w.mint()
    await w.mint()
    await w.mint()
    before = await w.live()
    w.writer.accept = 0
    r = w.logout(a.access_token, all_sessions=all_sessions)
    assert r.status_code == 503
    assert r.headers["content-type"].startswith("application/problem+json")
    assert "set-cookie" not in r.headers  # the cookies stay: the session was not ended
    assert w.writer.refused == ["auth.logout"]
    assert w.writer.events == []  # nothing accepted, so a retry has nothing to repeat
    assert await w.live() == before and len(before) == 3
    assert w.published == []
    w.writer.accept = None  # the sink recovers
    retry = w.logout(a.access_token, all_sessions=all_sessions)
    assert retry.status_code == 204
    revoked = 3 if all_sessions else 1
    assert [e["action"] for e in w.writer.events] == ["auth.logout"] + [
        "auth.session_revoked"
    ] * revoked


async def test_logout_all_writes_one_intent_then_revokes_then_one_outcome_per_session() -> None:
    w = _World()
    a = await w.mint()
    b = await w.mint()
    c = await w.mint()
    elsewhere = await w.mint(_OTHER)  # another user's session is never targeted
    lost_before = _outcome_lost("auth.session_revoked")
    r = w.logout(a.access_token, all_sessions=True)
    assert r.status_code == 204
    mine = {str(a.session_id), str(b.session_id), str(c.session_id)}
    intent, *outcomes = w.writer.events
    assert (intent["action"], intent["reason"]) == ("auth.logout", "logout_all")
    assert set(intent["after_state"]["session_ids"]) == mine  # the target ids, in one record
    assert intent["after_state"]["session_count"] == 3
    assert redact(intent["after_state"]) == intent["after_state"]  # the ids survive redaction
    assert [e["action"] for e in outcomes] == ["auth.session_revoked"] * 3
    assert {str(e["session_id"]) for e in outcomes} == mine
    assert {e["reason"] for e in outcomes} == {"logout_all"}
    # Content, not only presence: every row is a plain success from the caller's address.
    assert {(e["outcome"], e["severity"]) for e in (intent, *outcomes)} == {
        (AuditOutcome.SUCCESS, Severity.INFO)
    }
    assert {e["actor_ip"] for e in outcomes} == {intent["actor_ip"]} == {_CLIENT_IP}
    # Write-ahead order: every session is still live at the intent record, and already ended at
    # each outcome record (04 section 8.3 rule 1: no record that implies success before it).
    assert (
        w.writer.live_at
        == [("auth.logout", frozenset(mine))] + [("auth.session_revoked", frozenset())] * 3
    )
    assert await w.live(_OTHER) == {str(elsewhere.session_id)}
    assert _outcome_lost("auth.session_revoked") == lost_before  # all written: nothing lost


async def test_logout_writes_the_intent_naming_the_caller_then_revokes_then_the_outcome() -> None:
    w = _World()
    a = await w.mint()
    b = await w.mint()
    r = w.logout(a.access_token, all_sessions=False)
    assert r.status_code == 204
    intent, outcome = w.writer.events
    assert (intent["action"], intent["reason"]) == ("auth.logout", "logout")
    assert intent["after_state"] == {"session_ids": [str(a.session_id)], "session_count": 1}
    assert (outcome["action"], str(outcome["session_id"]), outcome["reason"]) == (
        "auth.session_revoked",
        str(a.session_id),
        "logout",
    )
    assert w.writer.live_at == [
        ("auth.logout", frozenset({str(a.session_id), str(b.session_id)})),
        ("auth.session_revoked", frozenset({str(b.session_id)})),
    ]


@pytest.mark.parametrize("make_error", _WRITER_ERRORS, ids=_ERROR_IDS)
@pytest.mark.parametrize("accept", [1, 2])
async def test_logout_all_outcome_records_refused_keep_the_204_and_count_each_loss(
    make_error: ErrorFactory, accept: int
) -> None:
    w = _World(make_error)
    a = await w.mint()
    b = await w.mint()
    c = await w.mint()
    w.writer.accept = accept  # the intent record, then accept - 1 outcome records, then refusal
    lost_before = _outcome_lost("auth.session_revoked")
    with capture_logs() as logs:
        r = w.logout(a.access_token, all_sessions=True)
    assert r.status_code == 204  # the user is signed out whatever the sink does now
    assert "max-age=0" in r.headers["set-cookie"].lower()
    assert await w.live() == set()
    written = accept - 1
    lost = 3 - written
    assert [e["action"] for e in w.writer.events] == ["auth.logout"] + [
        "auth.session_revoked"
    ] * written
    assert w.writer.refused == ["auth.session_revoked"] * lost
    # No record exists for a session that was not revoked: every written row names a revoked one.
    revoked = {str(a.session_id), str(b.session_id), str(c.session_id)}
    assert {str(e["session_id"]) for e in w.writer.events[1:]} <= revoked
    assert _outcome_lost("auth.session_revoked") - lost_before == lost
    lost_logs = [e for e in logs if e["event"] == _LOST_EVENT]
    assert [(e["log_level"], e["action"], e["error"]) for e in lost_logs] == [
        ("error", "auth.session_revoked", type(w.writer.error).__name__)
    ] * lost
    assert a.access_token not in repr(logs) and a.refresh_token not in repr(logs)


async def test_logout_all_outcome_records_name_what_revoke_all_returned_not_what_was_read() -> None:
    w = _World(service=_LateSignInService)
    a = await w.mint()
    b = await w.mint()
    r = w.logout(a.access_token, all_sessions=True)
    assert r.status_code == 204
    assert isinstance(w.svc, _LateSignInService) and w.svc.late is not None
    late = str(w.svc.late.session_id)
    intent, *outcomes = w.writer.events
    assert set(intent["after_state"]["session_ids"]) == {str(a.session_id), str(b.session_id)}
    assert {str(e["session_id"]) for e in outcomes} == {str(a.session_id), str(b.session_id), late}
    assert await w.live() == set()  # the late session ended too, and has its record


async def test_logout_sink_going_inactive_after_the_intent_still_signs_out_and_counts() -> None:
    w = _World()
    a = await w.mint()
    await w.mint()
    # The audit service stops after taking the intent record (an inactive sink flipping
    # mid-request, #2914 item 4): the outcome records cannot be written, the sign-out stands.
    w.writer.after_accept = lambda action: setattr(w.audit, "is_active", False)
    lost_before = _outcome_lost("auth.session_revoked")
    with capture_logs() as logs:
        r = w.logout(a.access_token, all_sessions=True)
    assert r.status_code == 204
    assert await w.live() == set()
    assert [e["action"] for e in w.writer.events] == ["auth.logout"]
    assert _outcome_lost("auth.session_revoked") - lost_before == 2
    assert [e["error"] for e in logs if e["event"] == _LOST_EVENT] == ["inactive"] * 2


async def test_logout_cancelled_mid_outcome_loop_counts_every_unwritten_row_as_lost() -> None:
    """A cancelled request (shutdown, a timeout) is not a silent stop (#2914): the sign-out stands,
    and the outcome record in flight and each one not yet tried are counted and logged as lost."""
    w = _World()
    a = await w.mint()
    await w.mint()
    await w.mint()
    in_flight = asyncio.Event()

    async def hang() -> set[str]:
        if w.writer.events:  # the intent record is in: this is the first outcome record
            in_flight.set()
            await asyncio.wait_for(asyncio.Event().wait(), timeout=5)  # bounded: fails, not hangs
        return set()

    w.writer.probe = hang
    lost_before = _outcome_lost("auth.session_revoked")
    transport = httpx.ASGITransport(app=w.client.app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE) as http:
        request = asyncio.create_task(
            http.post(
                "/api/v1/auth/logout", json={"all_sessions": True}, headers=_h(a.access_token)
            )
        )
        await asyncio.wait_for(in_flight.wait(), timeout=5)
        with capture_logs() as logs:
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request
    assert await w.live() == set()  # every session was revoked before the first record
    assert [e["action"] for e in w.writer.events] == ["auth.logout"]
    assert _outcome_lost("auth.session_revoked") - lost_before == 3
    lost = [e for e in logs if e["event"] == _LOST_EVENT]
    assert [e["error"] for e in lost] == ["cancelled"] * 3
    assert {e["session_id"] for e in lost} == set(w.repo.sessions)  # one line per revoked session


@pytest.mark.parametrize("all_sessions", [False, True])
async def test_logout_cancelled_inside_the_revocation_counts_every_target_row_as_lost(
    all_sessions: bool,
) -> None:
    """The revocation is committed, then the request is cancelled while the service publishes it
    to the sockets (a shutdown): `revoke` and `revoke_all` never return what they revoked, so no
    outcome record can be written for sessions that are already ended. Every target the intent
    record named is counted and logged as lost (a session the cancellation reached first is counted
    too: a false loss is the safe direction), and the cancellation goes on (#2914, 04 section 8.3
    rule 2). Without this the sessions end with only the intent record and nothing alerts."""
    w = _World()
    a = await w.mint()
    b = await w.mint()
    c = await w.mint()
    publishing = asyncio.Event()

    async def hang() -> None:
        publishing.set()
        await asyncio.wait_for(asyncio.Event().wait(), timeout=5)  # bounded: fails, not hangs

    w.on_publish = hang
    targets = {str(x.session_id) for x in ((a, b, c) if all_sessions else (a,))}
    lost_before = _outcome_lost("auth.session_revoked")
    transport = httpx.ASGITransport(app=w.client.app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE) as http:
        request = asyncio.create_task(
            http.post(
                "/api/v1/auth/logout",
                json={"all_sessions": all_sessions},
                headers=_h(a.access_token),
            )
        )
        await asyncio.wait_for(publishing.wait(), timeout=5)
        with capture_logs() as logs:
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request
    assert await w.live() == {str(x.session_id) for x in (a, b, c)} - targets  # committed first
    intent, *outcomes = w.writer.events
    assert (intent["action"], set(intent["after_state"]["session_ids"])) == ("auth.logout", targets)
    assert outcomes == []  # no outcome record was written
    assert _outcome_lost("auth.session_revoked") - lost_before == len(targets)
    lost = [e for e in logs if e["event"] == _LOST_EVENT]
    assert [(e["log_level"], e["action"], e["error"]) for e in lost] == [
        ("error", "auth.session_revoked", "cancelled")
    ] * len(targets)
    assert {e["session_id"] for e in lost} == targets  # one line per target session
    assert a.access_token not in repr(logs) and a.refresh_token not in repr(logs)


async def _cancel_refresh_in_the_revocation_publish(
    w: _World, token: str, session_id: uuid.UUID
) -> list[MutableMapping[str, Any]]:
    """POST /auth/refresh with `token`, cancel the request while the service publishes the
    revocation of a family to the sockets (it commits it first), and return what that logged."""
    publishing = asyncio.Event()

    async def hang() -> None:
        publishing.set()
        await asyncio.wait_for(asyncio.Event().wait(), timeout=5)  # bounded: fails, not hangs

    w.on_publish = hang
    transport = httpx.ASGITransport(app=w.client.app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE) as http:
        request = asyncio.create_task(
            http.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": token},
                headers=csrf_headers(CSRF_CODEC, session_id),
            )
        )
        await asyncio.wait_for(publishing.wait(), timeout=5)
        with capture_logs() as logs:
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request
    return logs


async def test_refresh_race_cancelled_in_the_revocation_counts_the_unwritten_reuse_row() -> None:
    """A concurrent-refresh race the service finds after the router saw a live token: it commits
    the revocation of the family, then publishes it to the sockets, and a request cancelled in that
    publish (a shutdown) never sees the answer (#2914, 04 section 8.3 rule 2). The critical outcome
    record was never attempted, so it is counted and logged as lost, once, and the cancellation
    goes on. Without this the family ends with only the intent record and nothing alerts."""
    w = _World(service=_RacedSessionService)
    m = await w.mint()
    lost_before = _outcome_lost("auth.refresh_reuse_detected")
    logs = await _cancel_refresh_in_the_revocation_publish(w, m.refresh_token, m.session_id)
    assert await w.live() == set()  # the whole family was revoked before the publish
    assert [e["action"] for e in w.writer.events] == ["auth.session_refreshed"]  # the intent only
    assert _outcome_lost("auth.refresh_reuse_detected") - lost_before == 1
    (lost,) = [e for e in logs if e["event"] == _LOST_EVENT]
    assert (lost["log_level"], lost["action"], lost["session_id"], lost["error"]) == (
        "error",
        "auth.refresh_reuse_detected",
        str(m.session_id),
        "cancelled",
    )
    assert m.refresh_token not in repr(logs)


async def test_refresh_of_a_spent_token_cancelled_in_the_revocation_loses_no_row() -> None:
    """The router saw the token already spent: it wrote the critical record before it called the
    service (write-ahead), so a request cancelled while the service publishes the revocation of
    the family has lost nothing and counts nothing."""
    w = _World()
    m = await w.mint()
    await w.svc.refresh(m.refresh_token)  # the token is spent: the replay below is the reuse
    lost_before = _outcome_lost("auth.refresh_reuse_detected")
    logs = await _cancel_refresh_in_the_revocation_publish(w, m.refresh_token, m.session_id)
    assert await w.live() == set()  # the whole family was revoked before the publish
    assert [e["action"] for e in w.writer.events] == ["auth.refresh_reuse_detected"]  # ahead
    assert _outcome_lost("auth.refresh_reuse_detected") == lost_before
    assert [e for e in logs if e["event"] == _LOST_EVENT] == []


async def test_logout_outcome_record_that_never_returns_is_bounded_and_counted_as_a_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The outcome write is bounded by the audit timeout (#2914 security review): a sink that
    never answers cannot hold the reply of a sign-out that has already revoked. The 204 stands,
    the record in flight and each one after it are counted and logged as `timeout`, and the sink
    is asked once, not once per session."""
    w = _World()
    a = await w.mint()
    await w.mint()
    await w.mint()
    asked, wedged = list[str](), asyncio.Event()

    async def never_answers() -> set[str]:
        if w.writer.events:  # the intent record is in: this is the first outcome record
            asked.append("auth.session_revoked")
            wedged.set()
            await asyncio.Event().wait()  # only the audit timeout ends this
        return set()

    w.writer.probe = never_answers
    clock, lost_before = _LoopClock(monkeypatch), _outcome_lost("auth.session_revoked")
    transport = httpx.ASGITransport(app=w.client.app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE) as http:
        request = asyncio.create_task(
            http.post(
                "/api/v1/auth/logout", json={"all_sessions": True}, headers=_h(a.access_token)
            )
        )
        await asyncio.wait_for(wedged.wait(), timeout=5)
        with capture_logs() as logs:
            clock.advance(AUDIT_TIMEOUT_S)  # the bound expires; the real clock has not moved
            reply = await asyncio.wait_for(request, timeout=5)
    assert reply.status_code == 204 and await w.live() == set()
    assert asked == ["auth.session_revoked"]  # the sink was asked once, not once per session
    assert [e["action"] for e in w.writer.events] == ["auth.logout"]
    assert _outcome_lost("auth.session_revoked") - lost_before == 3
    lost = [e for e in logs if e["event"] == _LOST_EVENT]
    assert [e["error"] for e in lost] == ["timeout"] * 3
    assert {e["session_id"] for e in lost} == set(w.repo.sessions)  # one line per revoked session


async def test_logout_all_intent_names_at_most_the_cap_but_every_session_has_its_own_row() -> None:
    """The intent record does not grow with the user's session count: it carries the first
    `LOGOUT_INTENT_SESSION_IDS_MAX` target ids and the total; each revoked session still has its
    own outcome record."""
    assert LOGOUT_INTENT_SESSION_IDS_MAX == 50  # the runbooks say "the first 50"
    w = _World()
    first = await w.mint()
    for _ in range(LOGOUT_INTENT_SESSION_IDS_MAX + 1):
        await w.mint()
    live = await w.live()
    assert w.logout(first.access_token, all_sessions=True).status_code == 204
    intent, *outcomes = w.writer.events
    named = intent["after_state"]["session_ids"]
    assert len(named) == len(set(named)) == LOGOUT_INTENT_SESSION_IDS_MAX
    assert set(named) < live  # targets, but not all of them
    assert intent["after_state"]["session_count"] == len(live) == LOGOUT_INTENT_SESSION_IDS_MAX + 2
    assert {str(e["session_id"]) for e in outcomes} == live


async def test_logout_that_revokes_nothing_writes_no_outcome_record_and_still_answers_204() -> None:
    w = _World(service=_ConcurrentlyRevokedService)
    a = await w.mint()
    r = w.logout(a.access_token, all_sessions=False)
    assert r.status_code == 204  # the other request wrote its own record
    assert [e["action"] for e in w.writer.events] == ["auth.logout"]


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
    unknown = w.client.delete(
        f"/api/v1/me/sessions/{_UNKNOWN_SESSION}", headers=_h(mine.access_token)
    )
    assert foreign.status_code == unknown.status_code == 404
    assert foreign.json() == unknown.json()  # no oracle: the probe row (#2319) is best-effort
    assert w.writer.refused == ["auth.session_revoke_denied"] * 2 and w.writer.events == []
    assert await w.live(_OTHER) == {str(theirs.session_id)}


async def test_csrf_refusal_record_writer_bug_is_not_swallowed_into_the_403() -> None:
    """#2914 item 6: the handler absorbs only the sink's own refusal (`AuditError`). Any other
    failure of the write is a defect and must surface, not hide behind a plain refusal."""
    w = _World(lambda: RuntimeError("writer bug"))
    m = await w.svc.mint(str(_USER))
    w.writer.accept = 0
    gap_before = _count("auth_csrf_refused_total", reason="audit_unavailable")
    r = w.refresh(m.refresh_token)
    assert r.status_code == 500  # an unhandled error, not the 403 a refusal would give
    assert w.writer.refused == ["auth.csrf_refused"]
    assert _count("auth_csrf_refused_total", reason="audit_unavailable") == gap_before
    assert await w.live() == {str(m.session_id)}  # and nothing was rotated either


async def test_logout_outcome_writer_bug_stays_a_500_and_counts_every_unwritten_row() -> None:
    """#2914 item 6: the outcome handler absorbs only the sink's own refusal (`AuditError`) into the
    204; any other failure of the write is a defect and still surfaces as a 500. The sessions are
    already revoked, so the rows the defect leaves unwritten (the one that raised, which may have
    landed, and the two not tried) are counted and logged as lost, by class name and never by
    message: a failed outcome write must alert (04 section 8.3 rule 2)."""
    w = _World(lambda: RuntimeError("writer bug"))
    a = await w.mint()
    await w.mint()
    await w.mint()
    w.writer.accept = 1  # the intent record lands; the first outcome record raises
    lost_before = _outcome_lost("auth.session_revoked")
    with capture_logs() as logs:
        r = w.logout(a.access_token, all_sessions=True)
    assert r.status_code == 500
    assert w.writer.refused == ["auth.session_revoked"]  # and the loop stopped there
    assert await w.live() == set()  # every session was revoked before the first record
    assert [e["action"] for e in w.writer.events] == ["auth.logout"]
    assert _outcome_lost("auth.session_revoked") - lost_before == 3
    lost = [e for e in logs if e["event"] == _LOST_EVENT]
    assert [e["error"] for e in lost] == ["RuntimeError"] * 3
    assert {e["session_id"] for e in lost} == set(w.repo.sessions)  # one line per revoked session
    assert "writer bug" not in repr(logs)  # the class name, never the message


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
