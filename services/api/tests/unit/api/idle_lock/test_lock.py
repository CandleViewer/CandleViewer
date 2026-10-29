"""`POST /auth/lock` (#4743, E09-S03-F1; contract `authLock`, CMP-098 "Lock now"): the session
locks at once, as if its idle deadline fell due, without moving it; its refusals; one write-ahead
`auth.session_locked` per lock (C-2.9), and B16's own `auth.idle_locked` once it is committed
(28 B16.7). A real `SessionService` and B16 chart over the in-memory fakes; no DB, no network."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import httpx
import pytest
from structlog.testing import capture_logs

from candleviewer.api.enrolment_guard import REFUSAL_ACTION
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.models import MintedSession, SessionRecord, UserStatus
from candleviewer.auth.session_service import ACCESS_TOKEN_TTL, SessionClass
from candleviewer.statechart.bindings import b16_session
from candleviewer.statechart.bindings.b16_session import elevation_view
from candleviewer.statechart.gateway import GatewayError, GatewayOverloadedError
from tests.conftest import RecordingAuditSink
from tests.unit.auth.session_fakes import LoopClock

from ._world import (
    _IDLE_S,
    _T0,
    World,
    _bearer,
    _conforms,
    _cookie,
    _FailingB16Sink,
    _open,
    _unlock,
)

_Credential = Callable[[MintedSession], dict[str, str]]


async def _lock(w: World, headers: dict[str, str], **kw: Any) -> httpx.Response:
    return await w.client.post("/api/v1/auth/lock", headers=headers, **kw)


async def _live(w: World, *, idle_timeout_s: int = _IDLE_S) -> MintedSession:
    """A session of a new user, a minute into its idle timeout: live, its access token too."""
    minted = await w.mint(await w.add_user(), idle_timeout_s=idle_timeout_s)
    w.clock.now += timedelta(seconds=60)
    return minted


# -- the lock -------------------------------------------------------------------------------------


async def test_lock_of_a_live_session_answers_session_info_locked_with_no_elevation(
    w: World,
) -> None:
    minted = await _live(w)
    grace = {"keys": w.clock.now + timedelta(minutes=4)}
    await w.repo.save_step_up_state(
        str(minted.session_id), elevations=grace, failures=0, readonly_until=None
    )
    r = await _lock(w, _bearer(minted))
    assert r.status_code == 200, r.text
    body = r.json()
    _conforms(body, "SessionInfo")
    assert body["session"]["locked"] is True and body["step_up_expires_at"] is None
    assert body["server_time"] == w.clock.now.isoformat()
    assert (await w.row(minted)).locked_at == w.clock.now
    assert w.audit.writer.actions() == ["auth.session_locked"]


async def test_lock_never_moves_last_seen_at_or_the_idle_deadline(w: World) -> None:
    """BQ-5: the deadline, and a later refusal's `idle_locked_at`, stay `last_seen_at +
    idle_timeout_s`; the lock moment is the audit row's time."""
    minted = await _live(w)
    deadline = (_T0 + timedelta(seconds=_IDLE_S)).isoformat()
    r = await _lock(w, _bearer(minted))
    assert r.json()["session"]["idle_deadline"] == deadline
    assert (await w.row(minted)).last_seen_at == _T0
    later = await w.client.get("/api/v1/auth/sessions", headers=_bearer(minted))
    assert (later.status_code, later.json()["code"]) == (401, "session_idle_locked")
    assert later.json()["idle_locked_at"] == deadline


@pytest.mark.parametrize("by", ["deadline", "request"])
async def test_lock_of_an_already_locked_session_is_200_and_writes_no_second_record(
    w: World, by: str
) -> None:
    """BQ-2: one `auth.session_locked` per lock; a call that changes nothing records nothing and
    sends B16 nothing."""
    minted = await _live(w)
    if by == "request":
        assert (await _lock(w, _bearer(minted))).status_code == 200
    else:
        w.lock()
    records, b16 = list(w.audit.writer.records), list(w.b16.calls)
    row = await w.row(minted)
    r = await _lock(w, _bearer(minted))
    assert r.status_code == 200 and r.json()["session"]["locked"] is True
    assert (w.audit.writer.records, w.b16.calls, await w.row(minted)) == (records, b16, row)


async def test_lock_of_a_locked_session_answers_200_even_with_the_audit_sink_down(
    w: World,
) -> None:
    minted = await _live(w)
    assert (await _lock(w, _bearer(minted))).status_code == 200
    w.audit.is_active = False
    r = await _lock(w, _bearer(minted))
    assert r.status_code == 200 and r.json()["session"]["locked"] is True


async def test_lock_records_idle_deadline_on_b16_and_never_request(
    w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BQ-1 (28 B16.7): the chart takes `IDLE_DEADLINE` into `auth.idle_locked` and writes that
    record; the route never sends `REQUEST` (or anything through `record`)."""
    minted = await _live(w)
    sent: list[str] = []

    async def record(_row: SessionRecord, _at: Any, event: str, **_kw: Any) -> None:
        sent.append(event)

    monkeypatch.setattr(w.step_up.chart, "record", record)
    assert (await _lock(w, _bearer(minted))).status_code == 200
    assert sent == [] and w.b16.actions() == ["auth.idle_locked"]
    assert w.chart_state(minted) >= {"auth.idle_locked"}


async def test_every_later_request_of_a_session_locked_by_request_is_session_idle_locked(
    w: World,
) -> None:
    """The row holds the lock: extend, a refresh and every other bearer read are refused as
    locked, and the session reads itself as locked."""
    minted = await _live(w)
    assert (await _lock(w, _bearer(minted))).status_code == 200
    refused = [
        await w.client.post("/api/v1/auth/session/extend", headers=_bearer(minted)),
        await w.client.get("/api/v1/auth/sessions", headers=_bearer(minted)),
        await w.client.post("/api/v1/auth/refresh", headers=_cookie(minted)),
    ]
    assert [(r.status_code, r.json()["code"]) for r in refused] == [
        (401, "session_idle_locked")
    ] * 3
    info = await w.client.get("/api/v1/auth/session", headers=_bearer(minted))
    assert info.status_code == 200 and info.json()["session"]["locked"] is True
    row = await w.row(minted)
    assert row.last_seen_at == _T0 and not row.is_revoked


async def test_a_lock_locks_only_the_calling_session_and_the_users_other_session_acts(
    w: World,
) -> None:
    uid = await w.add_user()
    mine, other = await w.mint(uid), await w.mint(uid)
    assert (await _lock(w, _bearer(mine))).status_code == 200
    assert (await w.client.get("/api/v1/auth/sessions", headers=_bearer(other))).status_code == 200
    assert (await w.row(other)).locked_at is None


async def test_unlock_lifts_a_lock_by_request_with_the_password_only(w: World) -> None:
    minted = await _live(w)
    assert (await _lock(w, _bearer(minted))).status_code == 200
    w.clock.now += timedelta(seconds=30)
    r = await _unlock(w, _bearer(minted))
    assert r.status_code == 200, r.text
    assert r.json()["session"]["locked"] is False
    row = await w.row(minted)
    assert (row.locked_at, row.unlocked_at, row.last_seen_at) == (None, w.clock.now, w.clock.now)
    assert w.audit.writer.actions() == ["auth.session_locked", "auth.session_unlocked"]
    assert w.b16.actions() == ["auth.idle_locked"]  # the chart writes no unlock row (B16.7)
    again = await w.client.get("/api/v1/auth/sessions", headers=_bearer(minted))
    assert again.status_code == 200


# -- refusals -------------------------------------------------------------------------------------


async def test_lock_of_a_revoked_session_is_session_revoked_without_its_cause(w: World) -> None:
    minted = await _live(w)
    await w.sessions.revoke(str(minted.session_id), reason="admin")
    r = await _lock(w, _bearer(minted))
    assert (r.status_code, r.json()["code"], r.json()["revoked_reason"]) == (
        401, "session_revoked", "revoked",
    )  # fmt: skip
    _conforms(r.json(), "Problem")
    assert w.audit.writer.records == [] and w.b16.calls == []


async def test_lock_after_the_absolute_lifetime_is_session_revoked_expired(w: World) -> None:
    minted = await w.mint(await w.add_user(), idle_timeout_s=900)
    w.clock.now += timedelta(hours=12, seconds=1)
    r = await _lock(w, _cookie(minted))
    assert (r.status_code, r.json()["code"], r.json()["revoked_reason"]) == (
        401, "session_revoked", "expired",
    )  # fmt: skip
    assert (await w.row(minted)).locked_at is None
    assert w.audit.writer.records == [] and w.b16.calls == []


@pytest.mark.parametrize("credential", [_bearer, _cookie], ids=["token", "cookie"])
async def test_a_session_of_a_disabled_user_is_revoked_never_locked(
    w: World, credential: _Credential
) -> None:
    """#2911's on-use backstop, before anything is recorded: the session is revoked as
    `user_disabled` and published, its cause undisclosed."""
    uid = await w.add_user()
    minted = await w.mint(uid)
    w.repo.user_statuses[str(uid)] = UserStatus.DISABLED
    r = await _lock(w, credential(minted))
    assert (r.status_code, r.json()["revoked_reason"]) == (401, "revoked")
    row = await w.row(minted)
    assert (row.revoked_reason, row.locked_at) == ("user_disabled", None)
    assert w.published == [(str(minted.session_id), "user_disabled")]
    assert w.audit.writer.records == [] and w.b16.calls == []


async def test_rotated_away_credentials_are_unauthenticated_never_session_revoked(
    w: World,
) -> None:
    minted = await _live(w)
    rotated = await w.sessions.refresh(minted.refresh_token)
    for headers in (_bearer(minted), _cookie(minted)):
        r = await _lock(w, headers)
        assert (r.status_code, r.json().get("code")) == (401, "unauthenticated")
    assert (await w.row(rotated.minted)).locked_at is None


async def test_lock_needs_a_credential_and_a_never_issued_one_is_unauthenticated(
    w: World,
) -> None:
    assert (await _lock(w, {})).status_code == 401
    forged = {"Authorization": "Bearer never-issued-" + "x" * 32}
    assert (await _lock(w, forged)).status_code == 401
    assert w.audit.writer.actions() == ["auth.session_fixation_attempt"]


async def test_lock_with_only_the_refresh_cookie_after_the_access_token_expired(
    w: World,
) -> None:
    """After a reload, the current `cv_refresh` cookie identifies the session (Origin and
    SR-041 checked here); an expired access token alone does not."""
    minted = await w.mint(await w.add_user(), idle_timeout_s=3600)
    w.clock.now += ACCESS_TOKEN_TTL
    assert (await _lock(w, _bearer(minted))).status_code == 401
    r = await _lock(w, _cookie(minted))
    assert r.status_code == 200, r.text
    assert r.json()["session"]["locked"] is True
    assert w.audit.writer.actions() == ["auth.session_locked"]


async def test_cookie_lock_without_an_allowed_origin_is_refused_before_any_record(
    w: World,
) -> None:
    """SR-042: `403 csrf_token_invalid` (the declared response), before anything is recorded."""
    minted = await _live(w)
    for origin in (None, "https://evil.example"):
        r = await _lock(w, _cookie(minted, origin=origin))
        assert (r.status_code, r.json()["code"]) == (403, "csrf_token_invalid")
    assert w.audit.writer.records == [] and (await w.row(minted)).locked_at is None


async def test_cookie_lock_with_a_csrf_token_of_another_session_is_refused_and_audited(
    w: World,
) -> None:
    """SR-041 against the session the cookie names: another session's token is refused, and the
    refusal recorded; nothing is locked."""
    uid = await w.add_user()
    minted, other = await w.mint(uid), await w.mint(uid)
    r = await _lock(w, _cookie(minted, csrf_for=other.session_id))
    assert (r.status_code, r.json()["code"]) == (403, "csrf_token_invalid")
    assert w.audit.writer.actions() == ["auth.csrf_refused"]
    assert (await w.row(minted)).locked_at is None and (await w.row(other)).locked_at is None


async def test_lock_with_an_undeclared_query_parameter_is_422_and_locks_nothing(
    w: World,
) -> None:
    """SR-026, self only: a query naming another session or user is refused, never ignored."""
    minted = await _live(w)
    for params in ({"session_id": "00000000-0000-4000-8000-0000000000ff"}, {"user_id": "x"}):
        assert (await _lock(w, _bearer(minted), params=params)).status_code == 422
    assert (await w.row(minted)).locked_at is None and w.audit.writer.records == []


async def test_lock_ignores_a_body_naming_another_session_and_locks_only_the_callers(
    w: World,
) -> None:
    uid = await w.add_user()
    mine, other = await w.mint(uid), await w.mint(uid)
    r = await _lock(w, _bearer(mine), json={"session_id": str(other.session_id)})
    assert r.status_code == 200 and r.json()["session"]["id"] == str(mine.session_id)
    assert (await w.row(mine)).locked_at is not None and (await w.row(other)).locked_at is None


async def test_lock_refuses_an_enrolment_only_session_its_cookie_names(w: World) -> None:
    """Lock is not among the session's five operations, and the cookie reaches no bearer guard:
    the route refuses as the guard does, before anything is locked or recorded but the guard's
    own refusal row."""
    minted = await _live(w)
    w.auth.enrolment_gate_is_active, w.auth.verdict = True, SessionClass.ENROLMENT_ONLY
    r = await _lock(w, _cookie(minted))
    assert (r.status_code, r.json()["code"]) == (403, "mfa_enrollment_required")
    [row] = w.audit.writer.records
    assert (row["action"], row["session_id"]) == (REFUSAL_ACTION, minted.session_id)
    assert row["after_state"] == {"channel": "http", "method": "POST", "path": "/auth/lock"}
    assert (await w.row(minted)).locked_at is None and w.b16.calls == []


async def test_lock_without_a_session_chart_authority_is_503_and_locks_nothing(
    b16_audit: RecordingAuditSink,
) -> None:
    w = await _open(b16_audit, authority=False)
    try:
        minted = await _live(w)
        assert (await _lock(w, _bearer(minted))).status_code == 503
        assert (await w.row(minted)).locked_at is None and w.audit.writer.records == []
    finally:
        await w.client.aclose()
        await w.step_up.stop()


async def test_lock_without_an_identity_provider_is_501_and_locks_nothing(
    b16_audit: RecordingAuditSink,
) -> None:
    w = await _open(b16_audit, identity=False)
    try:
        minted = await _live(w)
        assert (await _lock(w, _bearer(minted))).status_code == 501
        assert (await w.row(minted)).locked_at is None and w.audit.writer.records == []
    finally:
        await w.client.aclose()
        await w.step_up.stop()


# -- the records: write-ahead, then B16 once committed (C-2.9, 28 B16.7) ------------------------


async def test_lock_with_the_audit_record_refused_is_503_and_the_session_stays_unlocked(
    w: World,
) -> None:
    minted = await _live(w)
    w.audit.writer.fail_on = {"auth.session_locked"}
    r = await _lock(w, _bearer(minted))
    assert r.status_code == 503 and r.headers["content-type"].startswith("application/problem")
    assert (await w.row(minted)).locked_at is None and w.b16.calls == []
    w.audit.writer.fail_on = set()
    assert (await _lock(w, _bearer(minted))).status_code == 200  # the retry locks
    assert w.audit.writer.actions() == ["auth.session_locked"]


async def test_lock_with_an_inactive_audit_sink_is_503_and_locks_nothing(w: World) -> None:
    minted = await _live(w)
    w.audit.is_active = False
    assert (await _lock(w, _bearer(minted))).status_code == 503
    assert (await w.row(minted)).locked_at is None and w.b16.calls == []


async def test_lock_whose_write_ahead_outlasts_its_bound_is_503_and_locks_nothing(
    w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The record is written under the row's lock, bounded (`audit_timeout_s`): past it the unit
    rolls back (`WriteAheadTimeout`) and nothing is locked."""
    loop_clock = LoopClock(monkeypatch)
    minted = await _live(w)
    emit = w.audit.writer.emit

    async def stalls(action: str, **kw: Any) -> None:
        if action == "auth.session_locked":
            loop_clock.advance(5.0)  # past the router's 2 s bound: it fires, nothing waits
            await asyncio.Event().wait()
        await emit(action, **kw)

    monkeypatch.setattr(w.audit.writer, "emit", stalls)
    with capture_logs() as logs:
        r = await _lock(w, _bearer(minted))
    assert r.status_code == 503
    assert {"event": "auth.lock.audit_unavailable", "error": "WriteAheadTimeout"}.items() <= next(
        e for e in logs if e["event"] == "auth.lock.audit_unavailable"
    ).items()
    assert (await w.row(minted)).locked_at is None and w.b16.calls == []


async def test_lock_writes_its_record_before_the_row_and_b16_after_it(
    w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-2.9: `auth.session_locked` while the row is still unlocked, under its lock; B16's
    `auth.idle_locked` only once the row shows the lock (C-2.21)."""
    minted = await _live(w)
    seen: list[tuple[str, Any]] = []
    writer_emit, b16_emit = w.audit.writer.emit, w.b16.emit

    async def row_locked_at() -> Any:
        return w.repo.sessions[str(minted.session_id)].locked_at

    async def on_writer(action: str, **kw: Any) -> None:
        seen.append((action, await row_locked_at()))
        await writer_emit(action, **kw)

    async def on_b16(action: str, **kw: Any) -> None:
        seen.append((action, await row_locked_at()))
        await b16_emit(action, **kw)

    monkeypatch.setattr(w.audit.writer, "emit", on_writer)
    monkeypatch.setattr(w.b16, "emit", on_b16)
    assert (await _lock(w, _bearer(minted))).status_code == 200
    assert seen == [("auth.session_locked", None), ("auth.idle_locked", w.clock.now)]


async def test_a_lock_the_chart_misses_answers_200_and_the_chart_records_it_on_next_use() -> None:
    """The lock committed with `auth.session_locked` written ahead, so a failed `IDLE_DEADLINE`
    step answers the committed state, 200 and locked, never 503 (B16 only records, C-2.21), as
    an unlock's does. The chart is dropped; its next use, the unlock's, rebuilds it from the row
    and records the lock before the unlock (INV-B16-e). A retry in between writes nothing."""
    sink = _FailingB16Sink("auth.idle_locked")
    b16_session.set_audit_sink(sink)
    w = await _open(sink)
    try:
        minted = await _live(w)
        with capture_logs() as logs:
            r = await _lock(w, _bearer(minted))
        assert r.status_code == 200, r.text
        assert r.json()["session"]["locked"] is True
        failed = [e for e in logs if e["event"] == "auth.lock.chart_failed"]
        assert [(e["b16_event"], e["error"]) for e in failed] == [
            ("IDLE_DEADLINE", "SessionChartError")
        ]
        assert (await w.row(minted)).is_idle_locked(now=w.clock.now)
        assert w.audit.writer.actions() == ["auth.session_locked"] and sink.actions() == []
        assert w.step_up.chart.interpreter(str(minted.session_id)) is None  # dropped
        assert (await _lock(w, _bearer(minted))).status_code == 200
        assert w.audit.writer.actions() == ["auth.session_locked"] and sink.actions() == []
        sink.fail_on = set()
        assert (await _unlock(w, _bearer(minted))).status_code == 200
        assert sink.actions() == ["auth.idle_locked"]
    finally:
        await w.client.aclose()
        await w.step_up.stop()


@pytest.mark.parametrize("refusal", [GatewayOverloadedError("s", "control")], ids=["overloaded"])
async def test_a_gateway_refusal_after_the_commit_answers_200_and_drops_the_chart(
    w: World, monkeypatch: pytest.MonkeyPatch, refusal: GatewayError
) -> None:
    """The statechart gateway refuses the step after the lock committed: the committed lock is
    the answer, never 500 or 503, the miss is logged, and the chart is dropped."""
    minted = await _live(w)

    async def refused(_record: SessionRecord, _at: Any) -> None:
        raise refusal

    monkeypatch.setattr(w.step_up.chart, "observe", refused)
    with capture_logs() as logs:
        r = await _lock(w, _bearer(minted))
    assert r.status_code == 200 and r.json()["session"]["locked"] is True
    failed = [e for e in logs if e["event"] == "auth.lock.chart_failed"]
    assert [(e["b16_event"], e["error"]) for e in failed] == [
        ("IDLE_DEADLINE", type(refusal).__name__)
    ]
    assert (await w.row(minted)).locked_at is not None
    assert w.step_up.chart.interpreter(str(minted.session_id)) is None


async def test_a_lock_cancelled_during_its_b16_step_drops_the_chart_and_stays_cancelled(
    w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The client goes away while the lock is recorded on B16, after it committed: the
    cancellation goes on, and the chart is dropped as for a failed step, so its next use
    rebuilds it from the row and records the lock."""
    minted = await _live(w)
    observe, pending = w.step_up.chart.observe, asyncio.Event()

    async def stall(row: SessionRecord, at: Any) -> None:
        await observe(row, at)  # the chart is up: the drop below is what removes it
        pending.set()
        await asyncio.Event().wait()  # until the request is cancelled

    monkeypatch.setattr(w.step_up.chart, "observe", stall)
    request = asyncio.create_task(_lock(w, _bearer(minted)))
    await pending.wait()
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    assert (await w.row(minted)).locked_at is not None
    assert w.audit.writer.actions() == ["auth.session_locked"]
    assert w.step_up.chart.interpreter(str(minted.session_id)) is None


async def test_a_lock_racing_another_lock_locks_once_writes_one_record_and_both_answer_200(
    w: World,
) -> None:
    minted = await _live(w)
    answers = await asyncio.gather(*(_lock(w, _bearer(minted)) for _ in range(2)))
    assert [a.status_code for a in answers] == [200, 200]
    assert all(a.json()["session"]["locked"] for a in answers)
    assert w.audit.writer.actions() == ["auth.session_locked"]
    assert w.b16.actions() == ["auth.idle_locked"]


async def test_the_lock_records_carry_ids_and_times_only(w: World) -> None:
    """C-12.6: `auth.session_locked` carries the actor, the session and the request, and no
    state of the row (no token hash, no grant); B16's `auth.idle_locked` its elevation view only:
    class names, counts and times, never a grant key, challenge or token hash."""
    minted = await _live(w)
    sid = str(minted.session_id)
    grace = {"keys": w.clock.now + timedelta(minutes=4)}
    await w.repo.save_step_up_state(sid, elevations=grace, failures=0, readonly_until=None)
    row = await w.row(minted)
    assert (await _lock(w, _bearer(minted))).status_code == 200
    [locked] = w.audit.writer.records
    assert {k: v for k, v in locked.items() if k != "request_id"} == {
        "action": "auth.session_locked",
        "actor_label": str(row.user_id),
        "actor_user_id": row.user_id,
        "actor_ip": "127.0.0.1",
        "session_id": row.id,
        "outcome": AuditOutcome.SUCCESS,
        "severity": Severity.INFO,
        "reason": None,
        "after_state": None,
    }
    [b16] = w.b16.calls
    view = set(elevation_view({}))
    assert set(b16["before_state"]) == set(b16["after_state"]) == view
    assert b16["before_state"]["elevated_classes"] == ["keys"]
    for secret in (row.refresh_token_hash, str(row.access_token_jti), minted.access_token):
        assert secret not in f"{locked}{b16}"
