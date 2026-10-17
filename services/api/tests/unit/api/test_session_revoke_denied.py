"""`DELETE /me/sessions/{sessionId}` for an id that is not one of the caller's live sessions
(E09-X02 AC-CSRF-05, #2319 item 2, SR-019): the 404 is unchanged (a foreign id, an unknown id and
the caller's own ended session are indistinguishable), and the attempt is counted
(`auth_session_revoke_denied_total`) and audited (`auth.session_revoke_denied`) within a per-user
and a global budget, through the same in-flight-capped, shielded writer path as the fixation row.
A slow, failed or cancelled write never changes the answer, and a probe that is counted but not
written (past a budget or the in-flight cap) is logged with its cause.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.api.csrf import RefusalAuditTracker
from candleviewer.api.sessions import PROBE_AUDIT_WINDOW_S, make_session_router
from candleviewer.audit.errors import AuditError
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.models import MintedSession
from candleviewer.auth.throttle import PerIpLoginThrottle
from tests.unit.api._fakes import (
    BASE,
    CSRF_CODEC,
    AuditService,
    Identity,
    RecordingWriter,
    SessionsAuth,
    sessions,
)
from tests.unit.auth.session_fakes import FakeSessionRepository

ACTION = "auth.session_revoke_denied"


def _denied() -> float:
    return float(REGISTRY.get_sample_value("auth_session_revoke_denied_total") or 0.0)


def _unaudited(cause: str) -> dict[str, str]:
    """The one log line of a probe that is counted but not written; it carries no id."""
    return {"event": ACTION + ".unaudited", "log_level": "warning", "cause": cause}


def _throttle(size: int | None, *, max_tracked: int) -> PerIpLoginThrottle | None:
    if size is None:
        return None
    return PerIpLoginThrottle(
        max_attempts=size, window_s=PROBE_AUDIT_WINDOW_S, max_tracked_ips=max_tracked
    )


class _DiesMidRequest:
    """Active at the route's entry check only; down by the time the probe row is attempted."""

    def __init__(self) -> None:
        self.writer = RecordingWriter()
        self._checks = 0

    @property
    def is_active(self) -> bool:
        self._checks += 1
        return self._checks == 1


class _World:
    """*budget* / *global_budget*: rows per user / for all users per window; None leaves the
    router's shipped default (the constants), a number injects a throttle of that size."""

    def __init__(
        self,
        *,
        budget: int | None = 100,
        global_budget: int | None = 100,
        audit_timeout_s: float = 2.0,
        audit_cap: int = 8,
        audit: AuditService | _DiesMidRequest | None = None,
    ) -> None:
        self.repo = FakeSessionRepository()
        self.svc = sessions(self.repo)
        self.audit = audit or AuditService()
        self.tracker = RefusalAuditTracker(cap=audit_cap)
        self.app = FastAPI()
        per_user = _throttle(budget, max_tracked=10_000)
        overall = _throttle(global_budget, max_tracked=1)
        router = make_session_router(
            SessionsAuth(self.svc),
            self.audit,
            identity=Identity(),
            csrf=CSRF_CODEC,
            probe_throttle=per_user,
            probe_global_throttle=overall,
            audit_tracker=self.tracker,
            audit_timeout_s=audit_timeout_s,
        )
        self.app.include_router(router, prefix="/api/v1")
        self.client = TestClient(self.app, base_url=BASE)

    async def user(self) -> MintedSession:
        return await self.svc.mint(str(uuid.uuid4()))

    def revoke(self, caller: MintedSession, target: uuid.UUID | str) -> httpx.Response:
        headers = {"Authorization": f"Bearer {caller.access_token}"}
        reply: httpx.Response = self.client.delete(f"/api/v1/me/sessions/{target}", headers=headers)
        return reply

    @property
    def rows(self) -> list[dict[str, Any]]:
        return self.audit.writer.of(ACTION)


async def test_a_foreign_and_an_unknown_id_get_the_same_404_and_both_are_counted_and_audited() -> (
    None
):
    w, before = _World(), _denied()
    attacker, victim = await w.user(), await w.user()
    foreign, unknown = w.revoke(attacker, victim.session_id), w.revoke(attacker, uuid.uuid4())
    assert (
        len({(r.status_code, r.headers["content-type"], r.content) for r in (foreign, unknown)})
        == 1
    )
    assert foreign.status_code == 404  # no oracle
    row, _ = w.rows
    assert (row["reason"], row["outcome"], row["severity"]) == (
        "not_live_own_session",
        AuditOutcome.DENIED,
        Severity.WARNING,
    )
    actor = w.repo.sessions[str(attacker.session_id)].user_id
    assert (row["actor_user_id"], row["session_id"]) == (actor, attacker.session_id)
    assert (row["object_kind"], row["object_id"]) == ("session", str(victim.session_id))
    assert _denied() - before == 2 == len(w.rows)
    assert not w.repo.sessions[str(victim.session_id)].is_revoked  # the attack failed


async def test_an_own_session_that_already_ended_is_answered_and_counted_as_not_live() -> None:
    """The ownership read lists live sessions only, so a stale Sessions row for the caller's own
    revoked session takes the path of a foreign or an unknown id: the same 404, counted and audited
    with a reason that says what is known ("not a live session of the caller"). The runbook says so.
    """
    w, before = _World(), _denied()
    user = str(uuid.uuid4())
    mine, other = await w.svc.mint(user), await w.svc.mint(user)
    assert w.revoke(mine, other.session_id).status_code == 204
    assert w.rows == [] and _denied() == before  # revoking one's own other session is no probe
    ended, unknown = w.revoke(mine, other.session_id), w.revoke(mine, uuid.uuid4())
    assert (ended.status_code, ended.headers["content-type"], ended.content) == (
        unknown.status_code,
        unknown.headers["content-type"],
        unknown.content,
    )
    assert ended.status_code == 404
    assert [row["reason"] for row in w.rows] == ["not_live_own_session"] * 2
    assert _denied() - before == 2


async def test_probes_past_the_per_user_budget_keep_the_404_and_the_count_but_write_no_row() -> (
    None
):
    w, before = _World(budget=2), _denied()
    attacker, other = await w.user(), await w.user()
    with capture_logs() as logs:
        assert [w.revoke(attacker, uuid.uuid4()).status_code for _ in range(3)] == [404] * 3
    assert len(w.rows) == 2 and _denied() - before == 3  # counted, not recorded
    assert logs == [_unaudited("audit_throttled")]  # one line, for the probe over the budget
    w.revoke(other, uuid.uuid4())  # the budget is per user: another user still gets a row
    assert len(w.rows) == 3


async def test_probes_past_the_global_budget_keep_the_404_and_the_count_but_write_no_row() -> None:
    w, before = _World(global_budget=2), _denied()
    users = [await w.user() for _ in range(3)]  # one probe each: no per-user budget is reached
    with capture_logs() as logs:
        assert [w.revoke(user, uuid.uuid4()).status_code for user in users] == [404] * 3
    assert len(w.rows) == 2 and _denied() - before == 3  # the third user's probe is not recorded
    assert logs == [_unaudited("audit_throttled")]


async def test_the_shipped_budgets_are_ten_rows_per_user_and_thirty_overall() -> None:
    w = _World(budget=None, global_budget=None)
    loner, *crowd = [await w.user() for _ in range(5)]
    assert [w.revoke(loner, uuid.uuid4()).status_code for _ in range(11)] == [404] * 11
    assert len(w.rows) == 10  # the per-user budget
    for user in crowd:  # four users, eight probes each: under the per-user budget, over the overall
        assert [w.revoke(user, uuid.uuid4()).status_code for _ in range(8)] == [404] * 8
    assert len(w.rows) == 30  # the overall budget


@pytest.mark.parametrize("failure", [AuditError("wal unavailable"), TimeoutError("wal lock")])
async def test_a_failed_audit_write_keeps_the_404_and_the_count_and_is_not_called_slow(
    failure: Exception, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The writer's own `TimeoutError` reaches the route as the clock's does: the task's outcome
    # decides, so it is a failed write (logged as one, nothing left running), not a slow one.
    w, before = _World(), _denied()
    attacker = await w.user()

    async def failing(action: str, **_kw: Any) -> None:
        raise failure

    monkeypatch.setattr(w.audit.writer, "emit", failing)
    with capture_logs() as logs:
        assert w.revoke(attacker, uuid.uuid4()).status_code == 404
    assert w.rows == [] and _denied() - before == 1 and len(w.tracker) == 0
    assert [(e["event"], e["log_level"], e["error"]) for e in logs] == [
        ("auth.session_revoke_denied.audit_unavailable", "error", type(failure).__name__)
    ]


async def test_an_audit_sink_that_dies_mid_request_keeps_the_404_and_the_count_and_logs_it() -> (
    None
):
    w, before = _World(audit=_DiesMidRequest()), _denied()
    attacker = await w.user()
    with capture_logs() as logs:
        assert w.revoke(attacker, uuid.uuid4()).status_code == 404
    assert w.rows == [] and _denied() - before == 1
    assert [(e["event"], e["log_level"], e["error"]) for e in logs] == [
        ("auth.session_revoke_denied.audit_unavailable", "error", "inactive")
    ]


@pytest.mark.parametrize("fails", [False, True], ids=["lands", "fails"])
async def test_a_slow_audit_write_keeps_the_404_and_is_left_to_finish_or_reported_if_it_fails(
    monkeypatch: pytest.MonkeyPatch, fails: bool
) -> None:
    w, entered, release = _World(audit_timeout_s=0.05), asyncio.Event(), asyncio.Event()
    attacker, rows = await w.user(), list[str]()

    async def slow_emit(action: str, **_kw: Any) -> None:  # a stalled WAL append, then it ends
        entered.set()
        await release.wait()
        if fails:
            raise AuditError("wal unavailable")
        rows.append(action)

    monkeypatch.setattr(w.audit.writer, "emit", slow_emit)
    headers = {"Authorization": f"Bearer {attacker.access_token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=w.app), base_url=BASE) as c:
        with capture_logs() as logs:
            reply = await c.delete(f"/api/v1/me/sessions/{uuid.uuid4()}", headers=headers)
    assert (reply.status_code, entered.is_set(), rows) == (404, True, [])  # answered, still writing
    assert [(e["event"], e["log_level"]) for e in logs] == [(ACTION + ".audit_slow", "warning")]
    with capture_logs() as logs:
        release.set()
        assert await w.tracker.drain(5.0) == 0
    assert rows == ([] if fails else [ACTION])  # never cancelled mid-append
    late = [(ACTION + ".audit_failed_late", "error", "AuditError")]  # the tracker's, under our name
    assert [(e["event"], e["log_level"], e["error"]) for e in logs] == (late if fails else [])


async def test_probes_while_the_writer_is_saturated_keep_the_404_and_the_count_but_write_no_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w, release = _World(audit_timeout_s=0.05, audit_cap=1), asyncio.Event()
    attacker, started, before = await w.user(), [], _denied()

    async def stalled_emit(action: str, **_kw: Any) -> None:  # the first write never returns
        started.append(action)
        await release.wait()

    monkeypatch.setattr(w.audit.writer, "emit", stalled_emit)
    headers = {"Authorization": f"Bearer {attacker.access_token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=w.app), base_url=BASE) as c:
        url = f"/api/v1/me/sessions/{uuid.uuid4()}"
        with capture_logs() as logs:
            replies = [await c.delete(url, headers=headers) for _ in range(2)]
    assert [r.status_code for r in replies] == [404, 404]
    assert started == [ACTION] and _denied() - before == 2  # the second probe starts no write
    assert logs == [
        {"event": ACTION + ".audit_slow", "log_level": "warning"},  # the first write, still running
        _unaudited("audit_saturated"),  # the cap, not a budget
    ]
    release.set()
    assert await w.tracker.drain(5.0) == 0


@pytest.mark.parametrize("write_first", [False, True], ids=["cancel_first", "write_first"])
@pytest.mark.parametrize("fails", [False, True], ids=["lands", "fails"])
async def test_a_cancelled_requests_row_lands_or_its_failure_is_reported_once(
    monkeypatch: pytest.MonkeyPatch, fails: bool, write_first: bool
) -> None:
    # write_first: the write ends in the very loop iteration of the cancel, ahead of it, so it is
    # already done when the route hands it over, and the tracker reports it then (#3054).
    w, entered, release = _World(), asyncio.Event(), asyncio.Event()
    attacker, rows, before = await w.user(), list[str](), _denied()

    async def emit(action: str, **_kw: Any) -> None:  # a stalled WAL append, then it ends
        entered.set()
        await release.wait()
        if fails:
            raise AuditError("wal unavailable")
        rows.append(action)

    monkeypatch.setattr(w.audit.writer, "emit", emit)
    headers = {"Authorization": f"Bearer {attacker.access_token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=w.app), base_url=BASE) as c:
        url = f"/api/v1/me/sessions/{uuid.uuid4()}"
        request = asyncio.ensure_future(c.delete(url, headers=headers))
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
    late = [(ACTION + ".audit_failed_late", "error", "AuditError")]
    assert [(e["event"], e["log_level"], e["error"]) for e in logs] == (late if fails else [])
    assert rows == ([] if fails else [ACTION]) and _denied() - before == 1
