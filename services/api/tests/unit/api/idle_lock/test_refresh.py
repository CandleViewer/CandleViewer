"""`POST /auth/refresh` and the idle lock (#2300; contract info "Idle lock"): a refresh is
not activity, and a locked session refreshes again once unlocked."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import httpx
import pytest
from structlog.testing import capture_logs

from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.models import MintedSession, RefreshOutcome, UserStatus

from ._world import _IDLE_S, _T0, World, _bearer, _lost, _refresh, _session, _unlock


async def test_refresh_is_not_activity_and_carries_the_idle_deadline_over(w: World) -> None:
    minted = await w.mint(await w.add_user())
    w.clock.now += timedelta(seconds=200)
    r = await _refresh(w, minted)
    assert r.status_code == 200, r.text
    successor = r.json()["tokens"]["access_token"]
    info = await _session(w, {"Authorization": f"Bearer {successor}"})
    assert info.json()["session"]["idle_deadline"] == (_T0 + timedelta(seconds=_IDLE_S)).isoformat()


async def test_a_refresh_refused_while_locked_works_again_after_the_unlock(w: World) -> None:
    minted = await w.mint(await w.add_user())
    w.lock()
    locked = await _refresh(w, minted)
    assert (locked.status_code, locked.json()["code"]) == (401, "session_idle_locked")
    assert (await _unlock(w, _bearer(minted))).status_code == 200
    again = await _refresh(w, minted)
    assert again.status_code == 200, again.text


async def _refresh_locking_inside(
    w: World, monkeypatch: pytest.MonkeyPatch, minted: MintedSession, *refuse: str
) -> httpx.Response:
    """`POST /auth/refresh` whose idle deadline passes inside `refresh()`, after the route's
    pre-check and its awaited intent record; from then on the writer refuses *refuse*."""
    w.clock.now = _T0 + timedelta(seconds=_IDLE_S - 1)
    refresh = w.sessions.refresh

    async def deadline_passes(raw_refresh_token: str, **kwargs: Any) -> RefreshOutcome:
        w.clock.now += timedelta(seconds=1)  # after the pre-check and the intent record
        w.audit.writer.fail_on = set(refuse)
        return await refresh(raw_refresh_token, **kwargs)

    monkeypatch.setattr(w.sessions, "refresh", deadline_passes)
    return await _refresh(w, minted)


async def test_a_refresh_locked_after_its_check_is_session_idle_locked_then_denied(
    w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lock engaged after the route's pre-check (the window includes the awaited intent
    record), so `refresh()` refuses it: the answer is still `session_idle_locked`, never
    `refresh_token_invalid`, and a DENIED outcome record follows the intent; nothing rotates."""
    minted = await w.mint(await w.add_user())
    r = await _refresh_locking_inside(w, monkeypatch, minted)
    assert (r.status_code, r.json()["code"]) == (401, "session_idle_locked")
    assert r.json()["idle_locked_at"] == (_T0 + timedelta(seconds=_IDLE_S)).isoformat()
    intent, refused = w.audit.writer.records
    assert (intent["action"], intent["outcome"]) == ("auth.session_refreshed", AuditOutcome.SUCCESS)
    assert (refused["action"], refused["outcome"], refused["reason"]) == (
        "auth.session_refreshed",
        AuditOutcome.DENIED,
        "idle_locked",
    )
    row = await w.row(minted)
    assert not row.is_revoked and row.is_idle_locked(now=w.clock.now)


async def test_a_lost_idle_locked_refusal_record_is_counted_and_the_401_stands(
    w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The DENIED `idle_locked` record of that refusal cannot be written: it is an outcome
    record (EX-07 names it), so the loss is counted and logged and the answer stands."""
    minted = await w.mint(await w.add_user())
    before = _lost("auth.session_refreshed")
    with capture_logs() as logs:
        r = await _refresh_locking_inside(w, monkeypatch, minted, "auth.session_refreshed")
    assert (r.status_code, r.json()["code"]) == (401, "session_idle_locked")
    (lost,) = [e for e in logs if e["event"] == "auth.session_audit.outcome_lost"]
    assert (lost["action"], lost["error"]) == ("auth.session_refreshed", "AuditUnavailable")
    assert _lost("auth.session_refreshed") - before == 1  # counted, so it tickets


async def test_a_spent_token_past_the_idle_timeout_still_reaches_reuse_detection(w: World) -> None:
    """The pre-check sees every row: right only because `is_idle_locked` skips revoked ones."""
    minted = await w.mint(await w.add_user())
    successor = await w.sessions.refresh(minted.refresh_token)
    w.lock()
    r = await _refresh(w, minted)
    assert (r.status_code, r.json().get("code")) == (401, None)  # not `session_idle_locked`
    (rec,) = w.audit.writer.records
    assert (rec["action"], rec["severity"]) == ("auth.refresh_reuse_detected", Severity.CRITICAL)
    assert (await w.row(successor.minted)).revoked_reason == "rotation_reuse"


async def test_a_locked_disabled_users_refresh_is_the_lock_with_no_record(w: World) -> None:
    """U45: the pre-check comes before the intent record, so nothing is written or revoked."""
    uid = await w.add_user()
    minted = await w.mint(uid)
    w.lock()
    w.repo.user_statuses[str(uid)] = UserStatus.DISABLED
    r = await _refresh(w, minted)
    assert (r.status_code, r.json()["code"]) == (401, "session_idle_locked")
    assert w.audit.writer.records == [] and w.published == []
    assert not (await w.row(minted)).is_revoked
