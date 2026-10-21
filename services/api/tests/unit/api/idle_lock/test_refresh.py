"""`POST /auth/refresh` of an idle-locked session (#3331, G2 of #2712; contract info "Idle lock" and
`authRefresh`): `401 session_idle_locked` with `idle_locked_at`, before the write-ahead record, so
nothing is audited, rotated or revoked, and the same token refreshes once the session is unlocked.
What `refresh()` decides before its lock check (the SR-041 pair, the absolute expiry, a disabled
user) still comes first."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import httpx
import pytest
from prometheus_client import REGISTRY

from candleviewer.audit.models import Severity
from candleviewer.auth.models import RefreshOutcome, UserStatus
from candleviewer.auth.session_service import ABSOLUTE_LIFETIME

from ._world import _IDLE_S, _T0, World, _conforms, _cookie, _unlock

_LOCKED_AT = (_T0 + timedelta(seconds=_IDLE_S)).isoformat()  # the session's `idle_deadline`


async def _refresh(w: World, headers: dict[str, str]) -> httpx.Response:
    return await w.client.post("/api/v1/auth/refresh", headers=headers)


def _idle_locks_refused() -> float:
    """`auth_idle_locks_total`: one per request refused because its session was idle-locked."""
    return float(REGISTRY.get_sample_value("auth_idle_locks_total") or 0.0)


@pytest.mark.parametrize(
    "fail_on", [set(), {"auth.session_refreshed"}], ids=["sink_up", "sink_refusing"]
)
async def test_a_locked_sessions_refresh_is_401_session_idle_locked_and_changes_nothing(
    w: World, fail_on: set[str]
) -> None:
    """The lock is answered before the write-ahead record: a sink that refuses that record still
    gets the lock's 401, never a 503, and nothing is audited, rotated, revoked or published."""
    minted = await w.mint(await w.add_user())
    w.lock()
    w.audit.writer.fail_on = fail_on
    before = _idle_locks_refused()
    r = await _refresh(w, _cookie(minted))
    assert (r.status_code, r.json()["code"]) == (401, "session_idle_locked")
    assert r.json()["idle_locked_at"] == _LOCKED_AT
    assert _idle_locks_refused() == before + 1
    _conforms(r.json(), "Problem")
    assert "set-cookie" not in r.headers
    assert w.audit.writer.records == [] and w.published == []
    assert not (await w.row(minted)).is_revoked
    assert len(w.repo.sessions) == 1 and w.repo.rotation_next == {}


async def test_the_same_token_refreshes_after_unlock(w: World) -> None:
    minted = await w.mint(await w.add_user())
    w.lock()
    assert (await _refresh(w, _cookie(minted))).json()["code"] == "session_idle_locked"
    assert (await _unlock(w, _cookie(minted))).status_code == 200
    r = await _refresh(w, _cookie(minted))
    assert r.status_code == 200, r.text
    assert (await w.row(minted)).revoked_reason == "rotated"


@pytest.mark.parametrize(
    ("case", "status", "code", "revoked"),
    [
        ("disabled", 401, None, "user_disabled"),
        ("expired", 401, None, "expired"),
        ("wrong_csrf_pair", 403, "csrf_token_invalid", None),
    ],
)
async def test_refresh_decides_before_the_lock(
    w: World, case: str, status: int, code: str | None, revoked: str | None
) -> None:
    """A locked session is never answered "locked" when `refresh()` would refuse it first: a
    disabled user's is revoked as `user_disabled` (U45) and an expired one as `expired`, each
    with the uniform 401; the SR-041 check comes before either."""
    uid = await w.add_user()
    minted = await w.mint(uid)
    headers = _cookie(minted)
    if case == "disabled":
        w.repo.user_statuses[str(uid)] = UserStatus.DISABLED
    elif case == "expired":
        w.clock.now += ABSOLUTE_LIFETIME  # idle-locked too
    else:
        headers = _cookie(minted, csrf_for=uuid.uuid4())
    w.lock()
    before = _idle_locks_refused()
    r = await _refresh(w, headers)
    assert (r.status_code, r.json().get("code")) == (status, code)
    assert _idle_locks_refused() == before  # not a lock refusal
    assert (await w.row(minted)).revoked_reason == revoked
    sid = str(minted.session_id)
    assert w.published == ([] if revoked is None else [(sid, revoked)])
    assert w.repo.rotation_next == {}


async def test_a_rotated_token_is_reuse_even_once_its_successor_has_locked(w: World) -> None:
    """Reuse detection comes before the lock: the old token of a session that has rotated,
    presented again once the successor has locked, gets the uniform 401 and the critical reuse
    record, and the family is revoked as `rotation_reuse`; it is never answered "locked"."""
    minted = await w.mint(await w.add_user())
    old = _cookie(minted)  # the old `cv_refresh` and its SR-041 pair
    assert (await _refresh(w, old)).status_code == 200
    successor = w.repo.rotation_next[str(minted.session_id)]
    w.lock()
    before = _idle_locks_refused()
    r = await _refresh(w, old)
    assert (r.status_code, r.json().get("code")) == (401, None)
    reuse = [e for e in w.audit.writer.records if e["action"] == "auth.refresh_reuse_detected"]
    assert [(e["severity"], e["reason"]) for e in reuse] == [(Severity.CRITICAL, "rotation_reuse")]
    assert (successor, "rotation_reuse") in w.published
    assert _idle_locks_refused() == before


async def test_a_lock_that_engages_after_the_routes_check_is_answered_locked(
    w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The service checks the lock again: one that engages after the route's check gets the same
    answer, with the intent record already written, and nothing is rotated."""
    minted = await w.mint(await w.add_user())
    refresh = w.sessions.refresh

    async def lock_first(raw_refresh_token: str, **kw: Any) -> RefreshOutcome:
        w.lock()
        return await refresh(raw_refresh_token, **kw)

    monkeypatch.setattr(w.sessions, "refresh", lock_first)
    before = _idle_locks_refused()
    r = await _refresh(w, _cookie(minted))
    assert (r.status_code, r.json()["code"]) == (401, "session_idle_locked")
    assert _idle_locks_refused() == before + 1
    assert r.json()["idle_locked_at"] == _LOCKED_AT
    assert w.audit.writer.actions() == ["auth.session_refreshed"]
    assert not (await w.row(minted)).is_revoked and w.repo.rotation_next == {}
