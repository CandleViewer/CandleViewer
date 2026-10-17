"""`GET /auth/session` of a locked session (#2300; contract info "Idle lock"): read-only
introspection the lock screen can use, by access token or `cv_refresh` cookie."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

import pytest

from candleviewer.api.sessions import REFRESH_COOKIE
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.metrics import auth_session_fixation_attempts_total
from candleviewer.auth.models import MintedSession, UserStatus

from ._world import (
    _IDLE_S,
    _T0,
    World,
    _bearer,
    _conforms,
    _session,
)


async def test_introspection_is_not_activity_and_the_session_locks_on_time(w: World) -> None:
    """AC "Introspection is not activity": polling every 10 s for 60 s from 30 s before the
    deadline never moves it, and the locked session still reads 200 with `locked: true`."""
    minted = await w.mint(await w.add_user())
    deadline = _T0 + timedelta(seconds=_IDLE_S)
    w.clock.now = deadline - timedelta(seconds=30)
    seen: list[tuple[str, bool]] = []
    for _ in range(7):
        r = await _session(w, _bearer(minted))
        assert r.status_code == 200, r.text
        _conforms(r.json(), "SessionInfo")
        seen.append((r.json()["session"]["idle_deadline"], r.json()["session"]["locked"]))
        w.clock.now += timedelta(seconds=10)
    assert {d for d, _ in seen} == {deadline.isoformat()}
    assert [locked for _, locked in seen] == [False] * 3 + [True] * 4


async def test_a_locked_session_reads_no_step_up_elevation(w: World) -> None:
    minted = await w.mint(await w.add_user())
    until = w.clock.now + timedelta(minutes=10)
    await w.repo.save_step_up_state(
        str(minted.session_id), elevations={"keys": until}, failures=0, readonly_until=None
    )
    assert (await _session(w, _bearer(minted))).json()["step_up_expires_at"] == until.isoformat()
    w.lock()
    assert (await _session(w, _bearer(minted))).json()["step_up_expires_at"] is None


async def test_the_lock_screen_reads_its_session_with_the_cookie_after_a_reload(
    w: World,
) -> None:
    minted = await w.mint(await w.add_user(), idle_timeout_s=900)
    w.lock(900)
    assert (await _session(w, _bearer(minted))).status_code == 401  # access token gone
    r = await _session(w, {"Cookie": f"{REFRESH_COOKIE}={minted.refresh_token}"})
    assert r.status_code == 200 and r.json()["session"]["locked"] is True


async def test_introspection_of_a_revoked_or_expired_session_is_the_uniform_401(
    w: World,
) -> None:
    uid = await w.add_user()
    revoked = await w.mint(uid)
    await w.sessions.revoke(str(revoked.session_id), reason="logout")
    refused = await _session(w, _bearer(revoked))
    assert refused.status_code == 401 and refused.json().get("code") is None
    expired = await w.mint(uid, idle_timeout_s=900)
    w.clock.now += timedelta(hours=12, seconds=1)
    r = await _session(w, {"Cookie": f"{REFRESH_COOKIE}={expired.refresh_token}"})
    assert r.status_code == 401 and r.json().get("code") is None


async def test_a_rotated_away_refresh_cookie_is_audited_as_a_reuse_probe(w: World) -> None:
    """Outside `/auth/refresh` a rotated-away cookie stays the uniform 401 and revokes no
    family, but it is counted and audited (`auth.refresh_reuse_detected`, denied), so probing
    whether a stolen refresh token is still current is not silent."""
    minted = await w.mint(await w.add_user(), idle_timeout_s=900)
    successor = await w.sessions.refresh(minted.refresh_token)
    probes = auth_session_fixation_attempts_total.labels(reason="rotated")
    before = probes._value.get()
    r = await _session(w, {"Cookie": f"{REFRESH_COOKIE}={minted.refresh_token}"})
    assert r.status_code == 401 and r.json().get("code") is None
    assert probes._value.get() == before + 1
    (probe,) = w.audit.writer.records
    assert (probe["action"], probe["outcome"], probe["severity"]) == (
        "auth.refresh_reuse_detected",
        AuditOutcome.DENIED,
        Severity.WARNING,
    )
    assert probe["session_id"] == minted.session_id
    assert probe["after_state"] == {
        "vector": "refresh_cookie",
        "path": "/auth/session",  # the route template, never the raw path
        "family_revoked": False,
    }
    assert minted.refresh_token not in repr(probe)
    assert not (await w.row(successor.minted)).is_revoked


async def test_a_never_issued_refresh_cookie_is_audited_as_a_fixation_attempt(w: World) -> None:
    """A `cv_refresh` cookie this server never issued stays the uniform 401, but it is counted
    and audited as a fixation attempt (`auth.session_fixation_attempt`, vector
    `refresh_cookie`, contract "Idle lock"); the cookie itself is never recorded."""
    attempts = auth_session_fixation_attempts_total.labels(reason="unknown_token")
    before = attempts._value.get()
    forged = "never-issued-" + "c" * 32
    r = await _session(w, {"Cookie": f"{REFRESH_COOKIE}={forged}"})
    assert r.status_code == 401 and r.json().get("code") is None
    assert attempts._value.get() == before + 1
    (attempt,) = w.audit.writer.records
    assert (attempt["action"], attempt["outcome"], attempt["reason"]) == (
        "auth.session_fixation_attempt",
        AuditOutcome.DENIED,
        "unknown_token",
    )
    assert attempt["after_state"] == {"vector": "refresh_cookie", "path": "/auth/session"}
    assert forged not in repr(attempt)


def _refresh_cookie(minted: MintedSession) -> dict[str, str]:
    return {"Cookie": f"{REFRESH_COOKIE}={minted.refresh_token}"}


@pytest.mark.parametrize("credential", [_bearer, _refresh_cookie], ids=["token", "cookie"])
async def test_a_locked_session_of_a_disabled_user_is_revoked_when_read(
    w: World, credential: Callable[[MintedSession], dict[str, str]]
) -> None:
    """#2911 holds on the lock-aware read: a session no disable revoked is revoked as
    `user_disabled` and refused when it is read, locked or not, however identified."""
    uid = await w.add_user()
    minted = await w.mint(uid)
    w.lock()
    w.repo.user_statuses[str(uid)] = UserStatus.DISABLED
    r = await _session(w, credential(minted))
    assert r.status_code == 401 and r.json().get("code") is None
    assert (await w.row(minted)).revoked_reason == "user_disabled"
    assert w.published == [(str(minted.session_id), "user_disabled")]
