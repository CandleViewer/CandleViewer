"""`POST /auth/unlock` (#2300; contract info "Idle lock", SCR-005): the password only,
its refusals, and the write-ahead audit and B16 records (C-2.9, B16.7)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from prometheus_client import REGISTRY

from candleviewer.api.sessions import UnlockBody
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.errors import StepUpRequired
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.login_service import LOCKOUT_THRESHOLD
from candleviewer.auth.models import MintedSession, SessionRecord, UserStatus
from tests.conftest import RecordingAuditSink

from ._world import (
    _CHEAP_ARGON2,
    _IDLE_S,
    _PW,
    _T0,
    _WRONG,
    World,
    _bearer,
    _conforms,
    _cookie,
    _open,
    _spec,
    _unlock,
)

# -- POST /auth/unlock: the happy path ------------------------------------------------------


async def test_unlock_with_the_password_lifts_the_lock_and_restamps_the_deadline(w: World) -> None:
    """AC "Unlock with the password only": no TOTP, `idle_deadline` re-stamped, audited."""
    minted = await w.mint(await w.add_user())
    w.lock()
    r = await _unlock(w, _bearer(minted))
    assert r.status_code == 200, r.text
    body = r.json()
    _conforms(body, "SessionInfo")
    assert body["session"]["locked"] is False
    assert (
        body["session"]["idle_deadline"] == (w.clock.now + timedelta(seconds=_IDLE_S)).isoformat()
    )
    assert body["server_time"] == w.clock.now.isoformat()
    assert (await w.row(minted)).last_seen_at == w.clock.now
    assert w.audit.writer.actions() == ["auth.session_unlocked"]
    assert w.b16.actions() == ["auth.idle_locked"]  # the chart writes no unlock row (B16.7)
    assert w.chart_state(minted) >= {"auth.active", "elevation.normal"}


async def test_unlock_clears_every_step_up_grant_in_the_one_write_that_lifts_the_lock(
    w: World,
) -> None:
    """B16.7 / #2290 rule 4d: grace windows, one-shot grants and pending challenges all go, in
    the same write that re-stamps `last_seen_at`; no unlock carries elevation."""
    minted = await w.mint(await w.add_user())
    until = w.clock.now + timedelta(minutes=10)
    grants = {"keys": until, "once:killswitch": until, "pending:users": until}
    await w.repo.save_step_up_state(
        str(minted.session_id), elevations=grants, failures=1, readonly_until=None
    )
    w.lock()
    writes: list[str] = []
    for name in ("lift_idle_lock", "touch_last_seen", "save_step_up_state", "revoke"):
        real = getattr(w.repo, name)

        async def spy(*args: Any, _real: Any = real, _name: str = name, **kw: Any) -> Any:
            writes.append(_name)
            return await _real(*args, **kw)

        setattr(w.repo, name, spy)
    r = await _unlock(w, _bearer(minted))
    assert r.status_code == 200, r.text
    assert r.json()["step_up_expires_at"] is None
    assert writes == ["lift_idle_lock"]
    row = await w.row(minted)
    assert (row.step_up_elevations, row.step_up_failures) == ({}, 1)
    sid = str(minted.session_id)
    with pytest.raises(StepUpRequired):
        await w.step_up.require_elevation(sid, "keys")
    assert await w.step_up.pending_action_class(sid) is None


async def test_unlock_with_only_the_refresh_cookie_after_the_access_token_expired(
    w: World,
) -> None:
    """A long lock or a reload leaves no live access token: the current `cv_refresh` cookie
    identifies the session, with the Origin and SR-041 checks of `/auth/refresh`."""
    minted = await w.mint(await w.add_user(), idle_timeout_s=900)
    w.lock(900)  # 15 min: the 12 min access token is gone too
    assert (await _unlock(w, _bearer(minted))).status_code == 401
    r = await _unlock(w, _cookie(minted))
    assert r.status_code == 200, r.text
    assert r.json()["session"]["locked"] is False


# -- POST /auth/unlock: refusals ------------------------------------------------------------


async def test_wrong_password_is_unlock_invalid_counted_toward_the_account_lockout(
    w: World,
) -> None:
    uid = await w.add_user()
    minted = await w.mint(uid)
    w.lock()
    r = await _unlock(w, _bearer(minted), _WRONG)
    assert r.status_code == 401
    _conforms(r.json(), "Problem")
    assert (r.json()["code"], r.json()["detail"]) == (
        "unlock_invalid",
        "The password is incorrect.",
    )
    assert w.failed_logins(uid) == 1  # login's lockout counter (SR-015, SR-016)
    (failed,) = w.audit.writer.records
    assert (failed["action"], failed["reason"]) == ("auth.unlock_failed", "invalid_password")
    assert (await w.row(minted)).is_idle_locked(now=w.clock.now)
    assert "auth.idle_locked" in w.chart_state(minted)


def _sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


async def test_fifth_wrong_password_revokes_and_publishes_then_unlock_is_session_revoked(
    w: World,
) -> None:
    """AC "Five wrong unlock passwords revoke the session" (#2272 revocation frame), counted
    as every revocation is: `auth_session_revocations_total` up, `auth_sessions_active` down."""
    minted = await w.mint(await w.add_user())
    w.lock()
    revocations = _sample("auth_session_revocations_total", reason="unlock_attempts_exceeded")
    active = _sample("auth_sessions_active")
    for _ in range(4):
        assert (await _unlock(w, _bearer(minted), _WRONG)).json()["code"] == "unlock_invalid"
    fifth = await _unlock(w, _bearer(minted), _WRONG)
    counted = _sample("auth_session_revocations_total", reason="unlock_attempts_exceeded")
    assert (counted, _sample("auth_sessions_active")) == (revocations + 1, active - 1)
    assert fifth.status_code == 401
    assert (fifth.json()["code"], fifth.json()["revoked_reason"]) == (
        "session_revoked",
        "unlock_attempts_exceeded",
    )
    assert (await w.row(minted)).revoked_reason == "unlock_attempts_exceeded"
    assert w.published == [(str(minted.session_id), "unlock_attempts_exceeded")]
    # The fifth wrong password is also the account's fifth (SR-016): it locks the account.
    assert w.audit.writer.actions() == ["auth.unlock_failed"] * 5 + [
        "auth.account_locked",
        "auth.session_revoked",
    ]
    assert w.b16.actions() == ["auth.idle_locked"]  # no second `auth.session_revoked` (replay)
    assert w.chart_state(minted) >= {"auth.revoked", "elevation.dead"}
    later = await _unlock(w, _bearer(minted))  # even the right password
    assert (later.status_code, later.json()["code"]) == (401, "session_revoked")
    assert later.json()["revoked_reason"] == "unlock_attempts_exceeded"


async def test_unlock_of_a_session_that_is_not_locked_is_409_and_checks_nothing(
    w: World,
) -> None:
    uid = await w.add_user()
    minted = await w.mint(uid)
    w.clock.now += timedelta(seconds=_IDLE_S - 1)
    r = await _unlock(w, _bearer(minted), _WRONG)
    assert r.status_code == 409
    _conforms(r.json(), "Problem")
    assert r.json()["code"] == "conflict"
    assert w.failed_logins(uid) == 0 and w.audit.writer.records == [] and w.b16.calls == []
    assert (await w.row(minted)).last_seen_at == _T0
    assert w.step_up.chart.interpreter(str(minted.session_id)) is None


async def test_unlock_after_the_absolute_lifetime_is_session_revoked_expired(w: World) -> None:
    """AC "Unlock after absolute expiry becomes a full sign-in": the route's own check answers
    before B16 records the lock, so nothing is recorded and no password is checked."""
    uid = await w.add_user()
    minted = await w.mint(uid, idle_timeout_s=900)
    w.clock.now += timedelta(hours=12, seconds=1)
    r = await _unlock(w, _cookie(minted))
    assert r.status_code == 401
    _conforms(r.json(), "Problem")
    assert (r.json()["code"], r.json()["revoked_reason"]) == ("session_revoked", "expired")
    assert w.failed_logins(uid) == 0 and w.audit.writer.records == []
    assert w.b16.calls == []  # refused before the lock is recorded or the body read


async def test_a_revoked_session_is_session_revoked_without_its_cause(w: World) -> None:
    uid = await w.add_user()
    minted = await w.mint(uid)
    await w.sessions.revoke(str(minted.session_id), reason="admin")
    r = await _unlock(w, _bearer(minted))
    assert (r.status_code, r.json()["revoked_reason"]) == (401, "revoked")
    assert w.failed_logins(uid) == 0


@pytest.mark.parametrize("credential", [_bearer, _cookie], ids=["token", "cookie"])
async def test_a_locked_session_of_a_disabled_user_is_revoked_never_unlocked(
    w: World, credential: Callable[[MintedSession], dict[str, str]]
) -> None:
    """#2911 holds on unlock as on `GET /auth/session`: a session no disable revoked is revoked
    as `user_disabled` and refused, its cause undisclosed, before any password check, B16
    step or audit record."""
    uid = await w.add_user()
    minted = await w.mint(uid)
    w.lock()
    w.repo.user_statuses[str(uid)] = UserStatus.DISABLED
    r = await _unlock(w, credential(minted))
    assert r.status_code == 401
    assert (r.json()["code"], r.json()["revoked_reason"]) == ("session_revoked", "revoked")
    assert (await w.row(minted)).revoked_reason == "user_disabled"
    assert w.published == [(str(minted.session_id), "user_disabled")]
    assert w.failed_logins(uid) == 0 and w.audit.writer.records == [] and w.b16.calls == []


async def test_a_session_gone_before_the_backstop_re_reads_it_is_unauthenticated(
    w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The row went after the route read it: the uniform 401, as from `GET /auth/session`,
    and nothing is checked, recorded or audited."""
    minted = await w.mint(await w.add_user())
    w.lock()
    peek = w.sessions.peek_access_token

    async def then_gone(token: str) -> SessionRecord | None:
        found = await peek(token)
        del w.repo.sessions[str(minted.session_id)]
        return found

    monkeypatch.setattr(w.sessions, "peek_access_token", then_gone)
    r = await _unlock(w, _bearer(minted))
    assert r.status_code == 401 and r.json().get("code") is None
    assert w.audit.writer.records == [] and w.b16.calls == []


async def test_rotated_away_credentials_are_unauthenticated_never_session_revoked(
    w: World,
) -> None:
    minted = await w.mint(await w.add_user())
    rotated = await w.sessions.refresh(minted.refresh_token)
    w.lock()
    for headers in (_bearer(minted), _cookie(minted)):
        r = await _unlock(w, headers)
        assert r.status_code == 401
        assert r.json().get("code") != "session_revoked"
    assert not (await w.row(rotated.minted)).is_revoked


async def test_unlock_needs_a_credential_and_a_never_issued_one_is_unauthenticated(
    w: World,
) -> None:
    assert (await _unlock(w, {})).status_code == 401
    forged = {"Authorization": "Bearer never-issued-" + "x" * 32}
    assert (await _unlock(w, forged)).status_code == 401
    assert w.audit.writer.actions() == ["auth.session_fixation_attempt"]


async def test_cookie_unlock_without_an_allowed_origin_is_refused_before_any_check(
    w: World,
) -> None:
    uid = await w.add_user()
    minted = await w.mint(uid, idle_timeout_s=900)
    w.lock(900)
    for origin in (None, "https://evil.example"):
        r = await _unlock(w, _cookie(minted, origin=origin))
        assert r.status_code == 403
    assert w.failed_logins(uid) == 0 and w.audit.writer.records == []


async def test_unlock_with_a_csrf_token_of_another_session_is_refused_and_audited(
    w: World,
) -> None:
    """SR-041 against the session the route acts on, for the cookie and the bearer alike."""
    uid = await w.add_user()
    minted = await w.mint(uid)
    other = await w.mint(uid)
    w.lock()
    for headers in (
        _bearer(minted, csrf_for=other.session_id),
        _cookie(minted, csrf_for=other.session_id),
    ):
        r = await _unlock(w, headers)
        assert (r.status_code, r.json()["code"]) == (403, "csrf_token_invalid")
    assert w.audit.writer.actions() == ["auth.csrf_refused", "auth.csrf_refused"]
    assert w.failed_logins(uid) == 0
    assert (await w.row(minted)).is_idle_locked(now=w.clock.now)


async def test_unlock_is_throttled_per_source_ip_and_a_throttled_attempt_checks_no_password(
    b16_audit: RecordingAuditSink,
) -> None:
    w = await _open(b16_audit, throttle_max=2)
    try:
        uid = await w.add_user()
        minted = await w.mint(uid)
        w.lock()
        for _ in range(2):
            assert (await _unlock(w, _bearer(minted), _WRONG)).status_code == 401
        r = await _unlock(w, _bearer(minted))
        assert r.status_code == 429
        assert int(r.headers["retry-after"]) >= 1
        assert w.failed_logins(uid) == 2
        assert (await w.row(minted)).is_idle_locked(now=w.clock.now)
    finally:
        await w.client.aclose()
        await w.step_up.stop()


async def test_unlock_without_a_step_up_authority_fails_closed_with_503(
    b16_audit: RecordingAuditSink,
) -> None:
    w = await _open(b16_audit, authority=False)
    try:
        minted = await w.mint(await w.add_user())
        w.lock()
        assert (await _unlock(w, _bearer(minted))).status_code == 503
    finally:
        await w.client.aclose()
        await w.step_up.stop()


async def test_unlock_without_an_identity_provider_is_501_and_checks_nothing(
    b16_audit: RecordingAuditSink,
) -> None:
    """No identity provider (E09-T03) to answer `SessionInfo` with: unlock is disabled before
    any throttle, credential, password check, B16 step or audit record."""
    w = await _open(b16_audit, identity=False)
    try:
        uid = await w.add_user()
        minted = await w.mint(uid)
        w.lock()
        r = await _unlock(w, _bearer(minted))
        assert r.status_code == 501
        assert w.failed_logins(uid) == 0 and w.audit.writer.records == [] and w.b16.calls == []
        assert (await w.row(minted)).is_idle_locked(now=w.clock.now)
    finally:
        await w.client.aclose()
        await w.step_up.stop()


@pytest.mark.parametrize(
    "body",
    [
        {"password": _PW, "totp": "123456"},  # unlock never takes a second factor
        {},
        {"password": ""},
        {"password": "x" * 513},
        ["not", "an", "object"],
    ],
)
async def test_unlock_body_is_the_password_only(w: World, body: Any) -> None:
    uid = await w.add_user()
    minted = await w.mint(uid)
    w.lock()
    r = await w.client.post("/api/v1/auth/unlock", json=body, headers=_bearer(minted))
    assert r.status_code == 422
    assert _PW not in r.text and "x" * 64 not in r.text
    assert w.failed_logins(uid) == 0 and w.audit.writer.records == []


async def test_unlock_with_an_undeclared_query_parameter_is_422_and_checks_nothing(
    w: World,
) -> None:
    """SR-026 (#2742): unlock takes no query parameter, a target user included, and refuses
    one before it tells the lock state or checks the password, here the right one."""
    uid = await w.add_user()
    minted = await w.mint(uid)
    w.lock()
    r = await w.client.post(
        "/api/v1/auth/unlock",
        params={"user_id": str(uid)},
        json={"password": _PW},
        headers=_bearer(minted),
    )
    assert (r.status_code, r.json()["code"]) == (422, "validation_failed")
    assert w.failed_logins(uid) == 0 and w.audit.writer.records == [] and w.b16.calls == []
    assert (await w.row(minted)).is_idle_locked(now=w.clock.now)


def test_unlock_body_model_matches_the_contract_unlock_request() -> None:
    contract = _spec()["components"]["schemas"]["UnlockRequest"]
    field = UnlockBody.model_json_schema()["properties"]["password"]
    assert contract["additionalProperties"] is False and contract["required"] == ["password"]
    assert set(UnlockBody.model_fields) == set(contract["properties"])
    password = contract["properties"]["password"]
    assert (field["minLength"], field["maxLength"]) == (
        password["minLength"],
        password["maxLength"],
    )
    assert UnlockBody.model_config.get("extra") == "forbid"


async def test_another_users_password_does_not_unlock_the_session(w: World) -> None:
    """Cross-user: the password is checked against the identified session's own user only."""
    uid = await w.add_user("trader")
    await w.add_user("other")  # the same password, a different account
    minted = await w.mint(uid)
    w.users.users[str(uid)] = w.users.users[str(uid)].model_copy(
        update={"password_hash": await Hasher().hash(_WRONG, _CHEAP_ARGON2)}
    )
    w.lock()
    r = await _unlock(w, _bearer(minted))  # `_PW` is the other account's password
    assert (r.status_code, r.json()["code"]) == (401, "unlock_invalid")
    assert (await w.row(minted)).is_idle_locked(now=w.clock.now)


async def test_a_locked_account_fails_like_a_wrong_password(w: World) -> None:
    uid = await w.add_user()
    minted = await w.mint(uid)
    w.users.users[str(uid)] = w.users.users[str(uid)].model_copy(
        update={"locked_until": w.clock.now + timedelta(hours=1)}
    )
    w.lock()
    codes = [(await _unlock(w, _bearer(minted))).json()["code"] for _ in range(5)]
    assert codes == ["unlock_invalid"] * 4 + ["session_revoked"]
    assert "auth.account_locked" not in w.audit.writer.actions()


# -- write-ahead audit and the B16 record (C-2.9, B16.7) -------------------------------------


async def test_audit_sink_down_is_503_and_no_password_is_checked(w: World) -> None:
    uid = await w.add_user()
    minted = await w.mint(uid)
    w.lock()
    w.audit.is_active = False
    assert (await _unlock(w, _bearer(minted))).status_code == 503
    assert w.failed_logins(uid) == 0 and w.b16.calls == []
    assert (await w.row(minted)).is_idle_locked(now=w.clock.now)


async def test_correct_password_with_the_unlock_record_failing_is_503_and_stays_locked(
    w: World,
) -> None:
    """B16.7 regression (a): never `2xx` without `auth.session_unlocked`."""
    minted = await w.mint(await w.add_user())
    until = w.clock.now + timedelta(minutes=10)
    await w.repo.save_step_up_state(
        str(minted.session_id), elevations={"keys": until}, failures=0, readonly_until=None
    )
    w.lock()
    w.audit.writer.fail_on = {"auth.session_unlocked"}
    r = await _unlock(w, _bearer(minted))
    assert r.status_code == 503
    row = await w.row(minted)
    assert row.is_idle_locked(now=w.clock.now) and set(row.step_up_elevations) == {"keys"}
    assert "auth.idle_locked" in w.chart_state(minted)


async def test_fifth_wrong_password_with_the_records_failing_is_503_never_a_plain_401(
    w: World,
) -> None:
    """B16.7 regression (a): the revoking failure is not revoked without its records, yet it
    stays counted, so the next wrong password revokes once the sink is back."""
    minted = await w.mint(await w.add_user())
    w.lock()
    for _ in range(4):
        assert (await _unlock(w, _bearer(minted), _WRONG)).status_code == 401
    w.audit.writer.fail_on = {"auth.unlock_failed", "auth.session_revoked"}
    assert (await _unlock(w, _bearer(minted), _WRONG)).status_code == 503
    assert not (await w.row(minted)).is_revoked and w.published == []
    w.audit.writer.fail_on = set()
    sixth = await _unlock(w, _bearer(minted), _WRONG)
    assert (sixth.status_code, sixth.json()["code"]) == (401, "session_revoked")
    assert (await w.row(minted)).revoked_reason == "unlock_attempts_exceeded"


async def test_a_wrong_password_with_its_record_failing_is_503_and_still_counted(
    w: World,
) -> None:
    minted = await w.mint(await w.add_user())
    w.lock()
    w.audit.writer.fail_on = {"auth.unlock_failed"}
    for _ in range(4):
        assert (await _unlock(w, _bearer(minted), _WRONG)).status_code == 503
    w.audit.writer.fail_on = set()
    fifth = await _unlock(w, _bearer(minted), _WRONG)
    assert (fifth.status_code, fifth.json()["code"]) == (401, "session_revoked")


async def test_unlock_audit_records_precede_the_change_they_describe(
    w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    minted = await w.mint(await w.add_user())
    w.lock()
    order: list[str] = []
    emit, lift, revoke = w.audit.writer.emit, w.repo.lift_idle_lock, w.repo.revoke

    async def emit_spy(action: str, **kw: Any) -> None:
        order.append(action)
        await emit(action, **kw)

    async def lift_spy(session_id: str, **kw: Any) -> Any:
        order.append("lift")
        return await lift(session_id, **kw)

    async def revoke_spy(session_id: str, **kw: Any) -> Any:
        order.append("revoke")
        return await revoke(session_id, **kw)

    monkeypatch.setattr(w.audit.writer, "emit", emit_spy)
    monkeypatch.setattr(w.repo, "lift_idle_lock", lift_spy)
    monkeypatch.setattr(w.repo, "revoke", revoke_spy)
    assert (await _unlock(w, _bearer(minted))).status_code == 200
    assert order == ["auth.session_unlocked", "lift"]
    second = await w.mint((await w.row(minted)).user_id)
    w.lock()
    order.clear()
    for _ in range(5):
        await _unlock(w, _bearer(second), _WRONG)
    assert order == ["auth.unlock_failed"] * 5 + [
        "auth.account_locked",
        "auth.session_revoked",
        "revoke",
    ]


async def test_unlock_never_logs_returns_or_audits_the_password(
    w: World, capsys: pytest.CaptureFixture[str]
) -> None:
    from structlog.testing import capture_logs

    minted = await w.mint(await w.add_user())
    w.lock()
    with capture_logs() as logs:
        replies = [
            await _unlock(w, _bearer(minted), _WRONG),
            await w.client.post(
                "/api/v1/auth/unlock", json={"password": _WRONG * 30}, headers=_bearer(minted)
            ),
            await _unlock(w, _bearer(minted)),
        ]
    assert [r.status_code for r in replies] == [401, 422, 200]
    seen = repr(logs) + repr(w.audit.writer.records) + repr(w.b16.calls)
    seen += "".join(r.text for r in replies) + "".join(capsys.readouterr())
    assert _PW not in seen and _WRONG not in seen


async def test_the_wrong_unlock_password_that_locks_the_account_writes_account_locked(
    w: World,
) -> None:
    """SR-016: a wrong unlock password counts toward the account lockout, and the one that
    locks the account is audited; the next unlock, right password included, fails like a
    wrong one and locks nothing new."""
    uid = await w.add_user()
    w.users.users[str(uid)] = w.users.users[str(uid)].model_copy(
        update={"failed_login_count": LOCKOUT_THRESHOLD - 1}
    )
    minted = await w.mint(uid)
    w.lock()
    r = await _unlock(w, _bearer(minted), _WRONG)
    assert (r.status_code, r.json()["code"]) == (401, "unlock_invalid")
    assert w.audit.writer.actions() == ["auth.unlock_failed", "auth.account_locked"]
    locked = w.audit.writer.records[-1]
    assert (locked["outcome"], locked["severity"]) == (AuditOutcome.DENIED, Severity.WARNING)
    assert locked["session_id"] == minted.session_id
    assert w.users.users[str(uid)].locked_until is not None
    again = await _unlock(w, _bearer(minted))
    assert (again.status_code, again.json()["code"]) == (401, "unlock_invalid")
    assert w.audit.writer.actions()[2:] == ["auth.unlock_failed"]
    assert (await w.row(minted)).is_idle_locked(now=w.clock.now)
