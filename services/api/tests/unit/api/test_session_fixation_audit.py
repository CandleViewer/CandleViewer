"""Session-fixation signal on the session routes (E09-X02 AC2, #2144, U6/SR-013).

A bearer or refresh token this server never issued is refused with the uniform 401 and is
counted and audited within per-IP and global budgets through the shielded, in-flight-capped
writer path; an expired or revoked token of a real session is not an attempt; a slow, failed
or cancelled audit write never changes the 401. Fixed clock, no network.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from candleviewer.api.csrf import AUDIT_TIMEOUT_S, RefusalAuditTracker
from candleviewer.api.sessions import (
    FIXATION_AUDIT_WINDOW_S,
    FIXATION_AUDITS_GLOBAL_PER_WINDOW,
    FIXATION_AUDITS_PER_WINDOW,
    REFRESH_COOKIE,
    make_session_router,
)
from candleviewer.audit.errors import AuditError
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.throttle import PerIpLoginThrottle
from tests.unit.api._fakes import (
    BASE,
    CSRF_CODEC,
    FIXATION,
    NOW,
    AuditService,
    Identity,
    SessionsAuth,
    fixation_count,
    sessions,
)
from tests.unit.auth.session_fakes import FakeSessionRepository

_ORIGIN = "https://app.example"
_FORGED = "forged-" + "f" * 40
_BEARER = {"Authorization": f"Bearer {_FORGED}"}
_USER = "00000000-0000-4000-8000-0000000000a1"
_LATE = "auth.session_fixation_attempt.audit_failed_late"  # the tracker's line


class _World:
    def __init__(
        self,
        *,
        budget: int = FIXATION_AUDITS_PER_WINDOW,
        global_budget: int = FIXATION_AUDITS_GLOBAL_PER_WINDOW,
        audit_timeout_s: float = AUDIT_TIMEOUT_S,
    ) -> None:
        self.repo = FakeSessionRepository()
        self.svc = sessions(self.repo)
        self.audit = AuditService()
        self.tracker = RefusalAuditTracker()
        window = FIXATION_AUDIT_WINDOW_S
        self.app = FastAPI()
        self.app.include_router(
            make_session_router(
                SessionsAuth(self.svc),
                self.audit,
                identity=Identity(),
                allowed_origins=frozenset({_ORIGIN}),
                csrf=CSRF_CODEC,
                fixation_throttle=PerIpLoginThrottle(max_attempts=budget, window_s=window),
                fixation_global_throttle=PerIpLoginThrottle(
                    max_attempts=global_budget, window_s=window
                ),
                audit_tracker=self.tracker,
                audit_timeout_s=audit_timeout_s,
            ),
            prefix="/api/v1",
        )
        self.client = TestClient(self.app, base_url=BASE)

    def session(self, token: str, client: TestClient | None = None) -> int:
        headers = {"Authorization": f"Bearer {token}"}
        return int((client or self.client).get("/api/v1/auth/session", headers=headers).status_code)

    @property
    def rows(self) -> list[dict[str, Any]]:
        return self.audit.writer.of(FIXATION)


def test_never_issued_bearer_is_401_counted_and_audited_without_the_token() -> None:
    w, before = _World(), fixation_count("unknown_token")
    assert w.session(_FORGED) == 401
    (row,) = w.rows
    assert (row["reason"], row["outcome"], row["severity"]) == (
        "unknown_token",
        AuditOutcome.DENIED,
        Severity.WARNING,
    )
    assert row["after_state"] == {"vector": "bearer", "path": "/auth/session"}
    assert row.get("actor_user_id") is None and _FORGED not in repr(w.audit.writer.events)
    assert fixation_count("unknown_token") - before == 1


async def test_expired_or_revoked_token_of_a_real_session_is_not_an_attempt() -> None:
    w, before = _World(), fixation_count("unknown_token")
    expired = await sessions(w.repo, now=NOW - timedelta(minutes=30)).mint(_USER)
    revoked = await w.svc.mint(_USER)
    await w.svc.revoke(str(revoked.session_id), reason="logout")
    assert w.session(expired.access_token) == w.session(revoked.access_token) == 401
    assert w.rows == [] and fixation_count("unknown_token") == before


@pytest.mark.parametrize("vector", ["refresh_body", "refresh_cookie"])
def test_never_issued_refresh_token_is_401_and_audited_per_vector(vector: str) -> None:
    w = _World()
    if vector == "refresh_body":
        r = w.client.post("/api/v1/auth/refresh", json={"refresh_token": _FORGED})
    else:
        headers = {"Cookie": f"{REFRESH_COOKIE}={_FORGED}", "Origin": _ORIGIN}
        r = w.client.post("/api/v1/auth/refresh", headers=headers)
    assert r.status_code == 401 and r.json()["detail"] == "refresh_token_invalid"
    (row,) = w.rows
    assert row["after_state"] == {"vector": vector, "path": "/auth/refresh"}


def test_attempts_past_the_per_ip_budget_keep_the_401_counted_but_unaudited() -> None:
    w = _World(budget=2)
    throttled, attempts = fixation_count("audit_throttled"), fixation_count("unknown_token")
    assert [w.session(f"{_FORGED}-{i}") for i in range(3)] == [401, 401, 401]
    assert len(w.rows) == 2
    assert fixation_count("audit_throttled") - throttled == 1
    assert fixation_count("unknown_token") - attempts == 3


def test_unavailable_audit_sink_keeps_the_uniform_401() -> None:
    w, before = _World(), fixation_count("audit_unavailable")
    w.audit.is_active = False
    assert w.session(_FORGED) == 401
    assert w.rows == [] and fixation_count("audit_unavailable") - before == 1


def test_global_budget_caps_audit_rows_across_rotating_source_addresses() -> None:
    w = _World(global_budget=2)  # one attempt per address: the per-IP budget is never reached
    throttled, attempts = fixation_count("audit_throttled"), fixation_count("unknown_token")
    clients = [TestClient(w.app, base_url=BASE, client=(f"10.9.0.{i}", 1)) for i in range(3)]
    assert [w.session(f"{_FORGED}-{i}", c) for i, c in enumerate(clients)] == [401] * 3
    assert len(w.rows) == 2  # the third address writes nothing
    assert fixation_count("audit_throttled") - throttled == 1
    assert fixation_count("unknown_token") - attempts == 3


@pytest.mark.parametrize("write_first", [False, True], ids=["cancel_first", "write_first"])
@pytest.mark.parametrize("fails", [False, True], ids=["lands", "fails"])
async def test_a_cancelled_requests_row_lands_or_its_failure_is_reported_and_counted_once(
    monkeypatch: pytest.MonkeyPatch, fails: bool, write_first: bool
) -> None:
    # write_first: the write ends in the very loop iteration of the cancel, ahead of it, so it is
    # already done when the route hands it over, and the tracker reports it then (#3054).
    w, entered, release = _World(), asyncio.Event(), asyncio.Event()
    unavailable, rows = fixation_count("audit_unavailable"), list[str]()

    async def emit(action: str, **_kw: Any) -> None:  # a stalled WAL append, then it ends
        entered.set()
        await release.wait()
        if fails:
            raise AuditError("wal unavailable")
        rows.append(action)

    monkeypatch.setattr(w.audit.writer, "emit", emit)
    transport = httpx.ASGITransport(app=w.app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE) as client:
        request = asyncio.ensure_future(client.get("/api/v1/auth/session", headers=_BEARER))
        async with asyncio.timeout(5):
            await entered.wait()
        with capture_logs() as logs:
            if write_first:
                release.set()  # the write ends in the next iteration ...
            request.cancel()  # ... and the client goes away in it (or while the write still runs)
            with pytest.raises(asyncio.CancelledError):
                await request
            release.set()
            assert await w.tracker.drain(5.0) == 0
    reported = [(e["event"], e["log_level"], e["error"]) for e in logs]
    assert reported == ([(_LATE, "error", "AuditError")] if fails else [])  # under this path's name
    assert fixation_count("audit_unavailable") - unavailable == int(fails)  # and counted, once
    assert rows == ([] if fails else [FIXATION])


@pytest.mark.parametrize("failure", [AuditError("wal unavailable"), TimeoutError("wal lock")])
def test_a_failed_audit_write_keeps_the_401_and_is_counted_unavailable_not_slow(
    failure: Exception,
) -> None:
    # The writer's own `TimeoutError` reaches the route as the clock's does: the task's outcome
    # decides, so it is a failed write (counted and logged as one, nothing left running), as the
    # CSRF guard reads it, and not a slow one.
    w = _World()
    unavailable, slow = fixation_count("audit_unavailable"), fixation_count("audit_slow")
    w.audit.writer.fail_with = failure
    with capture_logs() as logs:
        assert w.session(_FORGED) == 401
    assert w.rows == [] and len(w.tracker) == 0
    assert fixation_count("audit_unavailable") - unavailable == 1
    assert fixation_count("audit_slow") == slow
    assert [(e["event"], e["log_level"], e["error"]) for e in logs] == [
        ("auth.session_fixation_attempt.audit_unavailable", "error", type(failure).__name__)
    ]


async def test_a_slow_write_that_then_fails_is_reported_by_the_tracker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w, release = _World(audit_timeout_s=0.05), asyncio.Event()
    slow, unavailable = fixation_count("audit_slow"), fixation_count("audit_unavailable")

    async def failing_emit(action: str, **_kw: Any) -> None:  # outlasts the wait, then fails
        await release.wait()
        raise AuditError("wal unavailable")

    monkeypatch.setattr(w.audit.writer, "emit", failing_emit)
    transport = httpx.ASGITransport(app=w.app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE) as client:
        reply = await client.get("/api/v1/auth/session", headers=_BEARER)
    assert reply.status_code == 401 and fixation_count("audit_slow") - slow == 1
    assert fixation_count("audit_unavailable") == unavailable  # still running: not lost yet
    with capture_logs() as logs:
        release.set()
        assert await w.tracker.drain(5.0) == 0
    assert [(e["event"], e["log_level"], e["error"]) for e in logs] == [
        (_LATE, "error", "AuditError")
    ]
    assert fixation_count("audit_unavailable") - unavailable == 1  # counted, not only logged


async def test_never_issued_expired_and_revoked_tokens_get_a_byte_identical_401() -> None:
    w = _World()
    expired = await sessions(w.repo, now=NOW - timedelta(minutes=30)).mint(_USER)
    revoked = await w.svc.mint(_USER)
    await w.svc.revoke(str(revoked.session_id), reason="logout")
    replies = [
        w.client.get("/api/v1/auth/session", headers={"Authorization": f"Bearer {token}"})
        for token in (_FORGED, expired.access_token, revoked.access_token)
    ]
    shapes = {(r.status_code, r.headers["content-type"], r.content) for r in replies}
    assert len(shapes) == 1 and replies[0].status_code == 401  # no oracle
