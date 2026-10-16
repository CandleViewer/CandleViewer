"""`POST /auth/unlock`, `POST /auth/session/extend` and the lock-aware `GET /auth/session` and
`POST /auth/refresh` (#2300 slice 2/2; contract `22-api-openapi.yaml` info "Idle lock", B16.7).

A real `SessionService` and a real `StepUpService` (so the real B16 chart records the lock and
the unlock) over in-memory fakes, one fixed clock, recording audit sinks that can fail on chosen
actions, and the router's own SR-041 codec. No DB, no network, no sleeps (C-13.5, C-13.7).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from functools import cache
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.csrf import SESSION_REFUSALS_PER_WINDOW
from candleviewer.api.sessions import REFRESH_COOKIE, UnlockBody, make_session_router
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.auth.csrf import CSRF_COOKIE, CSRF_HEADER, CsrfCodec
from candleviewer.auth.envelope import TotpEncryptor
from candleviewer.auth.errors import StepUpRequired
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.login_service import LOCKOUT_THRESHOLD
from candleviewer.auth.metrics import auth_session_fixation_attempts_total
from candleviewer.auth.models import MintedSession, SessionRecord
from candleviewer.auth.session_chart import SessionChart
from candleviewer.auth.session_service import SessionService
from candleviewer.auth.step_up import StepUpService
from candleviewer.auth.throttle import PerIpLoginThrottle
from candleviewer.statechart.bindings import b16_session
from tests.conftest import RecordingAuditSink
from tests.unit.auth.auth_fakes import FakeUserRepository, make_user
from tests.unit.auth.mfa_fakes import FakeMfaRepository
from tests.unit.auth.session_fakes import FakeSessionRepository

_T0 = datetime(2026, 10, 16, 9, 0, 0, tzinfo=UTC)
_ORIGIN = "https://app.example.test"
_PW = "unlock-canary-pw-2300"  # test-only literal, never a credential
_WRONG = "wrong-canary-pw-2300"  # test-only literal, never a credential
_CODEC = CsrfCodec(b"\x07" * 32)
#: Cheap Argon2id parameters: verification reads them from the hash, so the tests stay fast.
_CHEAP_ARGON2 = {"m": 8, "t": 1, "p": 1}
#: Minted with the 5 min minimum, a session locks while its 12 min access token still lives.
_IDLE_S = 300
_SPEC_BASE = "urn:cv:openapi"


@cache
def _spec() -> dict[str, Any]:
    return load_openapi_spec()


def _conforms(value: Any, schema: str) -> None:
    resource = Resource.from_contents(_spec(), default_specification=DRAFT202012)
    Draft202012Validator(
        {"$ref": f"{_SPEC_BASE}#/components/schemas/{schema}"},
        registry=Registry().with_resource(_SPEC_BASE, resource),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    ).validate(value)


class _Clock:
    def __init__(self) -> None:
        self.now = _T0

    def __call__(self) -> datetime:
        return self.now


class _Writer:
    """The router's audit writer: records every emission and, like `AuditWriter.emit`,
    raises `AuditUnavailable` for an action in `fail_on`."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self.fail_on: set[str] = set()

    async def emit(self, action: str, **kw: Any) -> None:
        if action in self.fail_on:
            raise AuditUnavailable("audit WAL unavailable: test")
        self.records.append({"action": action, **kw})

    def actions(self) -> list[str]:
        return [r["action"] for r in self.records]


class _Audit:
    def __init__(self) -> None:
        self.writer = _Writer()
        self.is_active = True


class _FailingB16Sink(RecordingAuditSink):
    """The B16 chart's sink, failing on the chosen actions (B16.7 regression tests)."""

    def __init__(self, *fail_on: str) -> None:
        super().__init__()
        self.fail_on = set(fail_on)

    async def emit(self, action: str, **kwargs: Any) -> None:
        if action in self.fail_on:
            raise AuditUnavailable("audit WAL unavailable: test")
        await super().emit(action, **kwargs)


class _Identity:
    async def user(self, user_id: str) -> dict[str, Any]:
        return {
            "id": user_id,
            "username": "trader",
            "email": "trader@example.test",
            "roles": ["manager"],
            "status": "active",
        }

    async def session_info(self, user_id: str) -> dict[str, Any]:
        return {"permissions": ["accounts:read"], "account_scope": []}


class _Auth:
    def __init__(self, sessions: SessionService) -> None:
        self.sessions = sessions
        self.sessions_is_active = True


class World:
    def __init__(self, b16: RecordingAuditSink, *, throttle_max: int, authority: bool) -> None:
        self.b16 = b16
        self.clock = _Clock()
        self.repo = FakeSessionRepository()
        self.users = FakeUserRepository()
        self.sessions = SessionService(self.repo, Hasher(), clock=self.clock)
        self.step_up = StepUpService(
            FakeMfaRepository(),
            self.repo,
            TotpEncryptor(os.urandom(32)),
            self.users,
            Hasher(),
            clock=self.clock,
            chart=SessionChart(),
        )
        self.audit = _Audit()
        self.published: list[tuple[str, str]] = []

        async def publish(session_id: str, reason: str) -> None:
            self.published.append((session_id, reason))

        app = FastAPI()
        app.include_router(
            make_session_router(
                _Auth(self.sessions),
                self.audit,
                identity=_Identity(),
                publish_revocation=publish,
                allowed_origins=frozenset({_ORIGIN}),
                csrf=_CODEC,
                unlock_authority=(lambda: self.step_up) if authority else None,
                unlock_throttle=PerIpLoginThrottle(
                    max_attempts=throttle_max, window_s=60.0, clock=lambda: 0.0
                ),
            ),
            prefix="/api/v1",
        )
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
        self.client = httpx.AsyncClient(transport=transport, base_url="https://testserver")

    async def add_user(self, username: str = "trader") -> uuid.UUID:
        hashed = await Hasher().hash(_PW, _CHEAP_ARGON2)
        user = make_user(username=username, email=f"{username}@example.test", password_hash=hashed)
        self.users.add(user)
        return user.id

    async def mint(self, user_id: uuid.UUID, *, idle_timeout_s: int = _IDLE_S) -> MintedSession:
        return await self.sessions.mint(str(user_id), idle_timeout_s=idle_timeout_s)

    def lock(self, seconds: int = _IDLE_S) -> None:
        """Let a session last seen now pass its idle deadline."""
        self.clock.now += timedelta(seconds=seconds + 1)

    async def row(self, minted: MintedSession) -> SessionRecord:
        found = await self.repo.find_by_id(str(minted.session_id))
        assert found is not None
        return found

    def failed_logins(self, user_id: uuid.UUID) -> int:
        return self.users.users[str(user_id)].failed_login_count

    def chart_state(self, minted: MintedSession) -> frozenset[str]:
        return self.step_up.chart.state(str(minted.session_id))


def _bearer(minted: MintedSession, *, csrf_for: uuid.UUID | None = None) -> dict[str, str]:
    """Access token plus the SR-041 pair a browser holds for that session."""
    token = _CODEC.issue(str(csrf_for or minted.session_id))
    return {
        "Authorization": f"Bearer {minted.access_token}",
        CSRF_HEADER: token,
        "Cookie": f"{CSRF_COOKIE}={token}",
    }


def _cookie(
    minted: MintedSession, *, origin: str | None = _ORIGIN, csrf_for: uuid.UUID | None = None
) -> dict[str, str]:
    """Only the `cv_refresh` cookie (a long lock or a reload), the Origin and the SR-041 pair."""
    token = _CODEC.issue(str(csrf_for or minted.session_id))
    headers = {
        CSRF_HEADER: token,
        "Cookie": f"{CSRF_COOKIE}={token}; {REFRESH_COOKIE}={minted.refresh_token}",
    }
    if origin is not None:
        headers["Origin"] = origin
    return headers


async def _unlock(w: World, headers: dict[str, str], password: str = _PW) -> httpx.Response:
    return await w.client.post("/api/v1/auth/unlock", json={"password": password}, headers=headers)


async def _open(
    b16: RecordingAuditSink, *, throttle_max: int = 100, authority: bool = True
) -> World:
    return World(b16, throttle_max=throttle_max, authority=authority)


@pytest.fixture
async def w(b16_audit: RecordingAuditSink) -> AsyncIterator[World]:
    world = await _open(b16_audit)
    try:
        yield world
    finally:
        await world.client.aclose()
        await world.step_up.stop()


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


async def test_fifth_wrong_password_revokes_and_publishes_then_unlock_is_session_revoked(
    w: World,
) -> None:
    """AC "Five wrong unlock passwords revoke the session" (#2272 revocation frame)."""
    minted = await w.mint(await w.add_user())
    w.lock()
    for _ in range(4):
        assert (await _unlock(w, _bearer(minted), _WRONG)).json()["code"] == "unlock_invalid"
    fifth = await _unlock(w, _bearer(minted), _WRONG)
    assert fifth.status_code == 401
    assert (fifth.json()["code"], fifth.json()["revoked_reason"]) == (
        "session_revoked",
        "unlock_attempts_exceeded",
    )
    assert (await w.row(minted)).revoked_reason == "unlock_attempts_exceeded"
    assert w.published == [(str(minted.session_id), "session_revoked")]
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
    """AC "Unlock after absolute expiry becomes a full sign-in": no password is checked."""
    uid = await w.add_user()
    minted = await w.mint(uid, idle_timeout_s=900)
    w.clock.now += timedelta(hours=12, seconds=1)
    r = await _unlock(w, _cookie(minted))
    assert r.status_code == 401
    _conforms(r.json(), "Problem")
    assert (r.json()["code"], r.json()["revoked_reason"]) == ("session_revoked", "expired")
    assert w.failed_logins(uid) == 0 and w.audit.writer.records == []


async def test_a_revoked_session_is_session_revoked_without_its_cause(w: World) -> None:
    uid = await w.add_user()
    minted = await w.mint(uid)
    await w.sessions.revoke(str(minted.session_id), reason="admin")
    r = await _unlock(w, _bearer(minted))
    assert (r.status_code, r.json()["revoked_reason"]) == (401, "revoked")
    assert w.failed_logins(uid) == 0


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
    r = await _unlock(w, _bearer(minted))
    assert (r.status_code, r.json()["code"]) == (401, "unlock_invalid")


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


async def test_lock_record_failing_is_503_with_the_row_still_locked_and_no_password_check(
    b16_audit: RecordingAuditSink,
) -> None:
    """B16.7 regression (b): `auth.idle_locked` is recorded before `unlock()` runs."""
    sink = _FailingB16Sink("auth.idle_locked")
    b16_session.set_audit_sink(sink)
    w = await _open(sink)
    try:
        uid = await w.add_user()
        minted = await w.mint(uid)
        w.lock()
        r = await _unlock(w, _bearer(minted))
        assert r.status_code == 503
        assert (await w.row(minted)).is_idle_locked(now=w.clock.now)
        assert w.failed_logins(uid) == 0 and w.audit.writer.records == []
        sink.fail_on = set()
        retry = await _unlock(w, _bearer(minted))
        assert retry.status_code == 200, retry.text
        assert sink.actions() == ["auth.idle_locked"]
    finally:
        await w.client.aclose()
        await w.step_up.stop()


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


async def test_unlock_brings_b16_up_to_the_lock_and_never_sends_request(
    w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B16.7 ("the route records `UNLOCK_OK` or `UNLOCK_FAILED`, never `REQUEST`"): the lock
    is recorded by `observe` before `unlock()` runs, then the unlock itself."""
    minted = await w.mint(await w.add_user())
    w.lock()
    events: list[str] = []
    record = w.step_up.chart.record

    async def spy(row: SessionRecord, at: datetime, event: str, **payload: Any) -> None:
        events.append(event)
        await record(row, at, event, **payload)

    monkeypatch.setattr(w.step_up.chart, "record", spy)
    assert (await _unlock(w, _bearer(minted))).status_code == 200
    assert events == ["UNLOCK_OK"]
    assert w.b16.actions() == ["auth.idle_locked"]
    assert w.chart_state(minted) >= {"auth.active", "elevation.normal"}


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


# -- activity is explicit: extend, introspection, refresh ------------------------------------


async def _extend(w: World, minted: MintedSession) -> httpx.Response:
    return await w.client.post("/api/v1/auth/session/extend", headers=_bearer(minted))


async def _session(w: World, headers: dict[str, str]) -> httpx.Response:
    return await w.client.get("/api/v1/auth/session", headers=headers)


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


async def test_refresh_is_not_activity_and_carries_the_idle_deadline_over(w: World) -> None:
    minted = await w.mint(await w.add_user())
    w.clock.now += timedelta(seconds=200)
    r = await w.client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": minted.refresh_token},
        headers=_bearer(minted),
    )
    assert r.status_code == 200, r.text
    successor = r.json()["tokens"]["access_token"]
    info = await _session(w, {"Authorization": f"Bearer {successor}"})
    assert info.json()["session"]["idle_deadline"] == (_T0 + timedelta(seconds=_IDLE_S)).isoformat()


async def test_a_refresh_refused_while_locked_works_again_after_the_unlock(w: World) -> None:
    minted = await w.mint(await w.add_user())
    w.lock()
    refresh = {"refresh_token": minted.refresh_token}
    locked = await w.client.post("/api/v1/auth/refresh", json=refresh, headers=_bearer(minted))
    assert (locked.status_code, locked.json()["code"]) == (401, "session_idle_locked")
    assert (await _unlock(w, _bearer(minted))).status_code == 200
    again = await w.client.post("/api/v1/auth/refresh", json=refresh, headers=_bearer(minted))
    assert again.status_code == 200, again.text


async def test_logout_of_a_session_past_its_lifetime_is_the_uniform_401(w: World) -> None:
    """#2389 gap J at the edge: an expired session is refused like a revoked one by the
    allow-locked routes, even while its access token lives; nothing is audited."""
    uid = await w.add_user()
    minted = await w.sessions.mint(str(uid), expires_at=_T0 + timedelta(minutes=5))
    w.clock.now = _T0 + timedelta(minutes=5)
    r = await w.client.post("/api/v1/auth/logout", headers=_bearer(minted))
    assert r.status_code == 401 and w.audit.writer.records == [] and w.published == []


# -- the other operations of a locked session: logout, revoke, the cookie ------------------


async def _logout(
    w: World, headers: dict[str, str], body: dict[str, Any] | None = None
) -> httpx.Response:
    return await w.client.post("/api/v1/auth/logout", json=body, headers=headers)


async def test_a_locked_session_cannot_sign_out_every_session(w: World) -> None:
    """#2389 gap H / decision 8 (#2290 ruling, rule 3b): whoever is at a locked terminal has
    not proved who they are. `all_sessions` is `401 session_idle_locked`: no session ends,
    nothing is audited or published, no cookie is cleared. Ending itself still works."""
    uid = await w.add_user()
    locked = await w.mint(uid)
    elsewhere = await w.mint(uid, idle_timeout_s=3600)  # the owner's live session elsewhere
    w.lock()
    r = await _logout(w, _bearer(locked), {"all_sessions": True})
    assert (r.status_code, r.json()["code"]) == (401, "session_idle_locked")
    assert r.json()["idle_locked_at"] == (_T0 + timedelta(seconds=_IDLE_S)).isoformat()
    assert not (await w.row(locked)).is_revoked and not (await w.row(elsewhere)).is_revoked
    assert w.audit.writer.records == [] and w.published == []
    assert "set-cookie" not in r.headers
    alone = await _logout(w, _bearer(locked))  # SCR-005 "Sign out instead"
    assert alone.status_code == 204, alone.text
    assert (await w.row(locked)).revoked_reason == "logout"
    assert not (await w.row(elsewhere)).is_revoked


async def test_after_a_reload_the_refresh_cookie_alone_signs_the_locked_session_out(
    w: World,
) -> None:
    """#2389 decision 9: with no access token inside its lifetime, `cv_refresh` identifies the
    session, so "Sign out instead" works for the whole lock: it revokes the session, writes
    `auth.logout` and `auth.session_revoked` and clears both cookies."""
    minted = await w.mint(await w.add_user(), idle_timeout_s=900)
    w.lock(900)  # 15 min: the 12 min access token is gone too
    assert (await _logout(w, _bearer(minted))).status_code == 401
    r = await _logout(w, _cookie(minted))
    assert r.status_code == 204, r.text
    assert w.audit.writer.actions() == ["auth.logout", "auth.session_revoked"]
    assert (await w.row(minted)).revoked_reason == "logout"
    assert w.published == [(str(minted.session_id), "session_revoked")]
    cleared = r.headers.get_list("set-cookie")
    for name in (REFRESH_COOKIE, CSRF_COOKIE):
        (cookie,) = [c for c in cleared if c.startswith(f"{name}=")]
        assert "max-age=0" in cookie.lower()


async def test_the_refresh_cookie_alone_never_signs_out_every_session(w: World) -> None:
    """Ending every session needs an access token: with only the cookie, `all_sessions` is
    `session_idle_locked` for a locked session, else the uniform 401, and revokes nothing."""
    uid = await w.add_user()
    locked = await w.mint(uid, idle_timeout_s=900)
    unlocked = await w.mint(uid, idle_timeout_s=3600)
    w.lock(900)
    for minted, code in ((locked, "session_idle_locked"), (unlocked, None)):
        r = await _logout(w, _cookie(minted), {"all_sessions": True})
        assert (r.status_code, r.json().get("code")) == (401, code)
    assert not (await w.row(locked)).is_revoked and not (await w.row(unlocked)).is_revoked
    assert w.audit.writer.records == [] and w.published == []


async def test_cookie_logout_without_an_allowed_origin_is_refused_before_any_record(
    w: World,
) -> None:
    minted = await w.mint(await w.add_user(), idle_timeout_s=900)
    w.lock(900)
    for origin in (None, "https://evil.example"):
        assert (await _logout(w, _cookie(minted, origin=origin))).status_code == 403  # SR-042
    assert not (await w.row(minted)).is_revoked and w.audit.writer.records == []


async def test_cookie_logout_with_a_csrf_token_of_another_session_is_refused_and_audited(
    w: World,
) -> None:
    """SR-041 against the session the cookie identifies (the contract's CSRF "Validation")."""
    uid = await w.add_user()
    minted = await w.mint(uid, idle_timeout_s=900)
    other = await w.mint(uid, idle_timeout_s=900)
    w.lock(900)
    r = await _logout(w, _cookie(minted, csrf_for=other.session_id))
    assert (r.status_code, r.json()["code"]) == (403, "csrf_token_invalid")
    (refused,) = w.audit.writer.records
    assert (refused["action"], refused["reason"]) == ("auth.csrf_refused", "wrong_session")
    assert refused["session_id"] == minted.session_id
    assert not (await w.row(minted)).is_revoked and not (await w.row(other)).is_revoked


async def test_route_checked_csrf_refusals_are_audited_within_a_per_session_budget(
    w: World,
) -> None:
    """Contract "CSRF", "Refusal": a cookie-identified logout has no request throttle, so its
    refusals are audited up to the per-session budget; past it the same 403, no record."""
    minted = await w.mint(await w.add_user(), idle_timeout_s=900)
    w.lock(900)
    forged = _cookie(minted, csrf_for=uuid.uuid4())
    replies = [await _logout(w, forged) for _ in range(SESSION_REFUSALS_PER_WINDOW + 1)]
    assert {(r.status_code, r.json()["code"]) for r in replies} == {(403, "csrf_token_invalid")}
    assert w.audit.writer.actions() == ["auth.csrf_refused"] * SESSION_REFUSALS_PER_WINDOW
    assert "retry-after" not in replies[0].headers
    assert int(replies[-1].headers["retry-after"]) >= 1
    assert not (await w.row(minted)).is_revoked


async def test_a_locked_session_cannot_revoke_another_session(w: World) -> None:
    """#2389 gap F: refused by the route itself, not only by `IdleLockMiddleware` (absent
    here), so the router never relies on how it is mounted; nothing is audited."""
    uid = await w.add_user()
    locked = await w.mint(uid)
    elsewhere = await w.mint(uid, idle_timeout_s=3600)
    w.lock()
    r = await w.client.delete(
        f"/api/v1/me/sessions/{elsewhere.session_id}", headers=_bearer(locked)
    )
    assert (r.status_code, r.json()["code"]) == (401, "session_idle_locked")
    assert not (await w.row(elsewhere)).is_revoked
    assert w.audit.writer.records == [] and w.published == []


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
