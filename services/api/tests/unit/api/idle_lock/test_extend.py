"""`POST /auth/session/extend` (#2300; contract info "Idle lock", CMP-098): the explicit
activity call. It is audited write-ahead, it never lifts a lock, and its own authentication is
no activity, so a refused record leaves the deadline where it was. A refusal after the record
(the session locked or ended meanwhile) leaves that intent record alone, as refresh's does."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta

import httpx
import pytest

from candleviewer.audit.models import AuditOutcome
from candleviewer.auth.models import MintedSession, SessionRecord

from ._world import _IDLE_S, _T0, World, _bearer, _conforms, _cookie, _session


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
    row = await w.row(minted)
    (record,) = w.audit.writer.records
    assert record["action"] == "auth.session_extended"
    assert (record["actor_user_id"], record["session_id"]) == (row.user_id, minted.session_id)
    assert record["actor_ip"] == "127.0.0.1"
    assert row.last_seen_at == w.clock.now


async def test_extend_with_the_audit_sink_down_is_503_and_the_deadline_does_not_move(
    w: World,
) -> None:
    minted = await w.mint(await w.add_user())
    w.clock.now += timedelta(seconds=200)
    w.audit.writer.fail_on = {"auth.session_extended"}
    assert (await _extend(w, minted)).status_code == 503
    assert (await w.row(minted)).last_seen_at == _T0


async def test_an_extend_locked_after_its_record_is_session_idle_locked_and_stays_locked(
    w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The session locked after the route let the request in, so `touch()` refuses it: the
    answer is the lock, the write-ahead record stands alone, and activity never lifts it."""
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
    (intent,) = w.audit.writer.records
    assert (intent["action"], intent["outcome"]) == ("auth.session_extended", AuditOutcome.SUCCESS)


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


@pytest.mark.parametrize("end", [_revoke, _remove])
async def test_an_extend_of_a_session_ended_after_its_record_is_the_uniform_401(
    w: World,
    monkeypatch: pytest.MonkeyPatch,
    end: Callable[[World, str], Awaitable[None]],
) -> None:
    minted = await w.mint(await w.add_user())
    touch = w.sessions.touch

    async def ended_first(session_id: str) -> SessionRecord:
        await end(w, session_id)  # after the route authenticated and wrote its record
        return await touch(session_id)

    monkeypatch.setattr(w.sessions, "touch", ended_first)
    r = await _extend(w, minted)
    assert r.status_code == 401 and r.json().get("code") is None
    assert w.audit.writer.actions() == ["auth.session_extended"]


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
    assert (listing.status_code, listing.json()["code"]) == (401, "session_idle_locked")
    refresh = await w.client.post("/api/v1/auth/refresh", headers=_cookie(minted))
    assert (refresh.status_code, refresh.json()["code"]) == (401, "session_idle_locked")
    row = await w.row(minted)
    assert row.last_seen_at == _T0 and row.is_idle_locked(now=w.clock.now) and not row.is_revoked
    assert w.audit.writer.records == []  # refused before any record
