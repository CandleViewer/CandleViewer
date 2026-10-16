"""`POST /auth/session/extend` (#2300; contract info "Idle lock", CMP-098): the explicit
activity call; no activity lifts a lock."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta

import httpx
import pytest
from structlog.testing import capture_logs

from candleviewer.audit.models import AuditOutcome
from candleviewer.auth.models import MintedSession, SessionRecord

from ._world import (
    _IDLE_S,
    _T0,
    World,
    _bearer,
    _conforms,
    _lost,
    _session,
)


async def _extend(w: World, minted: MintedSession) -> httpx.Response:
    return await w.client.post("/api/v1/auth/session/extend", headers=_bearer(minted))


async def test_extend_moves_only_the_idle_deadline_and_audits_first(w: World) -> None:
    minted = await w.mint(await w.add_user())
    w.clock.now += timedelta(seconds=200)
    r = await _extend(w, minted)
    assert r.status_code == 200, r.text
    _conforms(r.json(), "SessionExtendResponse")
    state = r.json()["session"]
    assert state["idle_deadline"] == (w.clock.now + timedelta(seconds=_IDLE_S)).isoformat()
    assert state["expires_at"] == minted.expires_at.isoformat() and state["locked"] is False
    assert r.json()["server_time"] == w.clock.now.isoformat()
    assert w.audit.writer.actions() == ["auth.session_extended"]
    assert (await w.row(minted)).last_seen_at == w.clock.now


async def test_extend_with_the_audit_sink_down_is_503_and_the_deadline_does_not_move(
    w: World,
) -> None:
    minted = await w.mint(await w.add_user())
    w.clock.now += timedelta(seconds=200)
    w.audit.writer.fail_on = {"auth.session_extended"}
    assert (await _extend(w, minted)).status_code == 503
    assert (await w.row(minted)).last_seen_at == _T0


async def test_an_extend_refused_after_its_record_is_followed_by_a_denied_record(
    w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-12.8: the session locked after the route let the request in, so `touch()` refuses
    it; the write-ahead `auth.session_extended` is followed by a DENIED one, and the lock
    stays (activity never lifts it)."""
    minted = await w.mint(await w.add_user())
    deadline = _T0 + timedelta(seconds=_IDLE_S)
    w.clock.now = deadline - timedelta(seconds=1)
    touch = w.sessions.touch

    async def deadline_passes(session_id: str) -> SessionRecord:
        w.clock.now = deadline  # after the route authenticated and wrote its record
        return await touch(session_id)

    monkeypatch.setattr(w.sessions, "touch", deadline_passes)
    r = await _extend(w, minted)
    assert (r.status_code, r.json()["code"]) == (401, "session_idle_locked")
    assert r.json()["idle_locked_at"] == deadline.isoformat()
    assert (await w.row(minted)).last_seen_at == _T0
    intent, refused = w.audit.writer.records
    assert (intent["action"], intent["outcome"]) == ("auth.session_extended", AuditOutcome.SUCCESS)
    assert (refused["action"], refused["outcome"], refused["reason"]) == (
        "auth.session_extended",
        AuditOutcome.DENIED,
        "idle_locked",
    )


async def test_a_denied_extend_record_that_cannot_be_written_is_counted_and_still_refuses(
    w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`touch()` refused after the intent record and the DENIED record fails: the refusal is
    the answer either way and nothing changed; the lost outcome record is counted and logged
    like refresh's (`_audit_outcomes`, 04-security-program.md section 8.3 rule 2)."""
    minted = await w.mint(await w.add_user())
    deadline = _T0 + timedelta(seconds=_IDLE_S)
    w.clock.now = deadline - timedelta(seconds=1)
    touch = w.sessions.touch

    async def deadline_passes(session_id: str) -> SessionRecord:
        w.clock.now = deadline
        w.audit.writer.fail_on = {"auth.session_extended"}  # the DENIED record, not the intent
        return await touch(session_id)

    monkeypatch.setattr(w.sessions, "touch", deadline_passes)
    before = _lost("auth.session_extended")
    with capture_logs() as logs:
        r = await _extend(w, minted)
    assert (r.status_code, r.json()["code"]) == (401, "session_idle_locked")
    assert [rec["outcome"] for rec in w.audit.writer.records] == [AuditOutcome.SUCCESS]
    (lost,) = [e for e in logs if e["event"] == "auth.session_audit.outcome_lost"]
    assert (lost["action"], lost["error"]) == ("auth.session_extended", "AuditUnavailable")
    assert _lost("auth.session_extended") - before == 1  # counted, so it tickets
    assert (await w.row(minted)).last_seen_at == _T0


async def test_extend_without_the_session_backend_is_503_and_moves_nothing(w: World) -> None:
    minted = await w.mint(await w.add_user())
    w.clock.now += timedelta(seconds=10)
    w.auth.sessions_is_active = False
    r = await _extend(w, minted)
    assert r.status_code == 503
    assert w.audit.writer.records == [] and (await w.row(minted)).last_seen_at == _T0


async def _revoke(w: World, session_id: str) -> None:
    await w.sessions.revoke(session_id, reason="admin")


async def _remove(w: World, session_id: str) -> None:
    del w.repo.sessions[session_id]


@pytest.mark.parametrize(("end", "reason"), [(_revoke, "revoked"), (_remove, "not_found")])
async def test_an_extend_of_a_session_ended_after_its_record_is_401_then_denied(
    w: World,
    monkeypatch: pytest.MonkeyPatch,
    end: Callable[[World, str], Awaitable[None]],
    reason: str,
) -> None:
    """C-12.8: the session was revoked or removed after the route let the request in, so
    `touch()` refuses it with the uniform 401, and a DENIED record follows the intent."""
    minted = await w.mint(await w.add_user())
    touch = w.sessions.touch

    async def ended_first(session_id: str) -> SessionRecord:
        await end(w, session_id)  # after the route authenticated and wrote its record
        return await touch(session_id)

    monkeypatch.setattr(w.sessions, "touch", ended_first)
    r = await _extend(w, minted)
    assert r.status_code == 401 and r.json().get("code") is None
    intent, refused = w.audit.writer.records
    assert (intent["action"], intent["outcome"]) == ("auth.session_extended", AuditOutcome.SUCCESS)
    assert (refused["action"], refused["outcome"], refused["reason"]) == (
        "auth.session_extended",
        AuditOutcome.DENIED,
        reason,
    )


async def test_activity_never_lifts_the_lock(w: World) -> None:
    """Extend, introspection, listing and refresh all leave a locked session locked."""
    minted = await w.mint(await w.add_user())
    w.lock()
    locked_at = (_T0 + timedelta(seconds=_IDLE_S)).isoformat()
    extend = await _extend(w, minted)
    assert (extend.status_code, extend.json()["code"]) == (401, "session_idle_locked")
    assert extend.json()["idle_locked_at"] == locked_at
    introspect = await _session(w, _bearer(minted))
    assert introspect.status_code == 200 and introspect.json()["session"]["locked"] is True
    listing = await w.client.get("/api/v1/auth/sessions", headers=_bearer(minted))
    assert listing.status_code == 401
    refresh = await w.client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": minted.refresh_token},
        headers=_bearer(minted),
    )
    assert (refresh.status_code, refresh.json()["code"]) == (401, "session_idle_locked")
    row = await w.row(minted)
    assert row.last_seen_at == _T0 and row.is_idle_locked(now=w.clock.now) and not row.is_revoked
    assert w.audit.writer.records == []  # refused before any record (no session_refreshed)
