"""`POST /auth/lock` (#4743, E09-S03-F1; contract `authLock`, CMP-098 "Lock now"): the session its
access token names locks at once, as if its idle deadline fell due, without moving it; its
refusals; one write-ahead `auth.session_locked` per lock (C-2.9), and B16's own
`auth.idle_locked` at its next read of the row (28 B16.7). A real `SessionService` and B16 chart
over the in-memory fakes; no DB, no network. The router runs bare here: the guards that answer
before it in the app are pinned through the app, the CSRF guard in
`tests/security/auth/test_idle_lock_http.py` and the enrolment guard in
`tests/contract/rbac/test_enrolment_only_matrix.py`."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import httpx
import pytest
from structlog.testing import capture_logs

from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.models import MintedSession, SessionRecord, UserStatus
from candleviewer.auth.session_chart import to_us
from candleviewer.auth.session_service import ACCESS_TOKEN_TTL
from candleviewer.statechart.bindings.b16_session import elevation_view
from tests.conftest import RecordingAuditSink
from tests.unit.auth.session_fakes import LoopClock

from ._world import (
    _IDLE_S,
    _T0,
    World,
    _bearer,
    _conforms,
    _cookie,
    _Identity,
    _open,
    _unlock,
)


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


async def test_lock_sends_b16_nothing_and_its_next_read_records_the_lock_at_its_moment(
    w: World,
) -> None:
    """The orchestrator's ruling (option c; 28 B16.7, C-2.21): as extend, the lock sends B16
    nothing, never a `REQUEST`; the row is the truth. The chart's next read of the row, here the
    unlock's, records `auth.idle_locked` with the row's `locked_at` as its moment, not the time
    of that read (INV-B16-e)."""
    minted = await _live(w)
    assert (await _lock(w, _bearer(minted))).status_code == 200
    assert w.b16.calls == [] and w.chart_state(minted) == frozenset()
    locked_at = (await w.row(minted)).locked_at
    assert locked_at is not None
    w.clock.now += timedelta(minutes=3)  # the read comes later than the lock
    assert (await _unlock(w, _bearer(minted))).status_code == 200
    [recorded] = w.b16.calls
    assert recorded["action"] == "auth.idle_locked"
    assert recorded["after_state"]["idle_locked_at_us"] == to_us(locked_at) != to_us(w.clock.now)


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
    """The lifetime ended while the access token still lives (as after a refresh near its end)."""
    uid = await w.add_user()
    minted = await w.sessions.mint(str(uid), expires_at=w.clock.now + timedelta(minutes=5))
    w.clock.now += timedelta(minutes=5, seconds=1)  # the token's 12 minutes are not over
    r = await _lock(w, _bearer(minted))
    assert (r.status_code, r.json()["code"], r.json()["revoked_reason"]) == (
        401, "session_revoked", "expired",
    )  # fmt: skip
    assert (await w.row(minted)).locked_at is None
    assert w.audit.writer.records == [] and w.b16.calls == []


async def test_a_session_of_a_disabled_user_is_revoked_never_locked(w: World) -> None:
    """#2911's on-use backstop, before anything is recorded: the session is revoked as
    `user_disabled` and published, its cause undisclosed."""
    uid = await w.add_user()
    minted = await w.mint(uid)
    w.repo.user_statuses[str(uid)] = UserStatus.DISABLED
    r = await _lock(w, _bearer(minted))
    assert (r.status_code, r.json()["revoked_reason"]) == (401, "revoked")
    row = await w.row(minted)
    assert (row.revoked_reason, row.locked_at) == ("user_disabled", None)
    assert w.published == [(str(minted.session_id), "user_disabled")]
    assert w.audit.writer.records == [] and w.b16.calls == []


async def test_a_rotated_away_access_token_is_unauthenticated_never_session_revoked(
    w: World,
) -> None:
    minted = await _live(w)
    rotated = await w.sessions.refresh(minted.refresh_token)
    r = await _lock(w, _bearer(minted))
    assert (r.status_code, r.json().get("code")) == (401, "unauthenticated")
    assert (await w.row(rotated.minted)).locked_at is None


async def test_a_session_gone_before_the_backstop_re_reads_it_is_unauthenticated(
    w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The row went after the route read it: the uniform 401, as from unlock, nothing recorded."""
    minted = await _live(w)
    peek = w.sessions.peek_access_token

    async def then_gone(token: str) -> SessionRecord | None:
        found = await peek(token)
        del w.repo.sessions[str(minted.session_id)]
        return found

    monkeypatch.setattr(w.sessions, "peek_access_token", then_gone)
    r = await _lock(w, _bearer(minted))
    assert (r.status_code, r.json().get("code")) == (401, "unauthenticated")
    assert w.audit.writer.records == [] and w.b16.calls == []


@pytest.mark.parametrize(
    ("meanwhile", "status", "code"),
    [("rotated", 401, "unauthenticated"), ("admin", 401, "session_revoked"),
     ("gone", 401, "unauthenticated")],
)  # fmt: skip
async def test_a_session_ended_while_the_lock_waited_is_refused_and_nothing_is_recorded(
    w: World, monkeypatch: pytest.MonkeyPatch, meanwhile: str, status: int, code: str
) -> None:
    """A refresh claim (`rotated`), a revoke or a deletion lands before the lock's unit reads the
    row: a rotated-away session gets the uniform 401 (22 `authLock`), a revoked one
    `session_revoked`, a gone one the uniform 401; nothing is recorded or locked."""
    minted = await _live(w)
    sid, lock_session = str(minted.session_id), w.repo.lock_session

    async def ended_first(session_id: str, **kw: Any) -> tuple[SessionRecord, bool] | None:
        if meanwhile == "gone":
            del w.repo.sessions[sid]
        else:
            await w.repo.revoke(sid, reason=meanwhile, now=w.clock.now)
        return await lock_session(session_id, **kw)

    monkeypatch.setattr(w.repo, "lock_session", ended_first)
    r = await _lock(w, _bearer(minted))
    assert (r.status_code, r.json().get("code")) == (status, code)
    assert w.audit.writer.records == [] and w.b16.calls == []
    assert sid not in w.repo.sessions or w.repo.sessions[sid].locked_at is None


async def test_a_user_gone_after_the_lock_committed_is_401_never_a_500(
    w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """As unlock: the lock stands, recorded; the answer the identity read cannot build is 401."""
    minted = await _live(w)

    async def gone(_self: Any, _user_id: str) -> dict[str, Any]:
        raise LookupError("no such user")

    monkeypatch.setattr(_Identity, "user", gone)
    r = await _lock(w, _bearer(minted))
    assert (r.status_code, r.json().get("code")) == (401, "unauthenticated")
    assert (await w.row(minted)).locked_at is not None
    assert w.audit.writer.actions() == ["auth.session_locked"]


async def test_lock_needs_a_credential_and_a_never_issued_one_is_unauthenticated(
    w: World,
) -> None:
    assert (await _lock(w, {})).status_code == 401
    forged = {"Authorization": "Bearer never-issued-" + "x" * 32}
    assert (await _lock(w, forged)).status_code == 401
    assert w.audit.writer.actions() == ["auth.session_fixation_attempt"]


@pytest.mark.parametrize("bearer", ["none", "expired"])
async def test_lock_with_only_the_refresh_cookie_is_refused_and_locks_nothing(
    w: World, bearer: str
) -> None:
    """22 `authLock`: only an access token inside its lifetime identifies the session, and the
    `cv_refresh` cookie identifies no lock. The cookie alone, or beside an expired access token,
    is the uniform 401 here (in the app the CSRF guard refuses the cookie alone first); the cookie
    is never read, so nothing is locked or recorded."""
    minted = await w.mint(await w.add_user(), idle_timeout_s=3600)
    headers = _cookie(minted)
    if bearer == "expired":
        w.clock.now += ACCESS_TOKEN_TTL  # the access token is over, the session is not
        headers["Authorization"] = f"Bearer {minted.access_token}"
    r = await _lock(w, headers)
    assert (r.status_code, r.json().get("code")) == (401, "unauthenticated")
    row = await w.row(minted)
    assert row.locked_at is None and not row.is_idle_locked(now=w.clock.now)
    assert w.audit.writer.records == [] and w.b16.calls == []


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


async def test_lock_needs_no_session_chart_authority(b16_audit: RecordingAuditSink) -> None:
    """The lock sends B16 nothing, so it needs no chart: without the unlock authority (whose chart
    B16 lives on) the session still locks, and only its own record is written."""
    w = await _open(b16_audit, authority=False)
    try:
        minted = await _live(w)
        assert (await _lock(w, _bearer(minted))).status_code == 200
        assert (await w.row(minted)).locked_at is not None
        assert w.audit.writer.actions() == ["auth.session_locked"] and w.b16.calls == []
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


# -- the records: write-ahead, then B16 at its next read of the row (C-2.9, 28 B16.7) -------------


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


async def test_lock_writes_its_record_before_the_row_and_sends_b16_nothing(
    w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-2.9: `auth.session_locked`, the record of the lock, while the row is still unlocked,
    under its lock; nothing reaches B16 at lock time."""
    minted = await _live(w)
    seen: list[tuple[str, Any]] = []
    writer_emit = w.audit.writer.emit

    async def on_writer(action: str, **kw: Any) -> None:
        seen.append((action, w.repo.sessions[str(minted.session_id)].locked_at))
        await writer_emit(action, **kw)

    monkeypatch.setattr(w.audit.writer, "emit", on_writer)
    assert (await _lock(w, _bearer(minted))).status_code == 200
    assert seen == [("auth.session_locked", None)] and w.b16.calls == []
    assert (await w.row(minted)).locked_at == w.clock.now


async def test_a_lock_racing_another_lock_locks_once_writes_one_record_and_both_answer_200(
    w: World,
) -> None:
    minted = await _live(w)
    answers = await asyncio.gather(*(_lock(w, _bearer(minted)) for _ in range(2)))
    assert [a.status_code for a in answers] == [200, 200]
    assert all(a.json()["session"]["locked"] for a in answers)
    assert w.audit.writer.actions() == ["auth.session_locked"] and w.b16.calls == []


async def test_the_lock_records_carry_ids_and_times_only(w: World) -> None:
    """C-12.6: `auth.session_locked` carries the actor, the session and the request, and no
    state of the row (no token hash, no grant); B16's `auth.idle_locked`, written at its next read
    of the row, its elevation view and the lock's moment only: class names, counts and times,
    never a grant key, challenge or token hash."""
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
    assert (await _unlock(w, _bearer(minted))).status_code == 200  # B16's next read of the row
    [b16] = w.b16.calls
    view = set(elevation_view({}))
    assert set(b16["before_state"]) == view
    assert set(b16["after_state"]) == {*view, "idle_locked_at_us"}
    assert b16["before_state"]["elevated_classes"] == ["keys"]
    for secret in (row.refresh_token_hash, str(row.access_token_jti), minted.access_token):
        assert secret not in f"{locked}{b16}"
