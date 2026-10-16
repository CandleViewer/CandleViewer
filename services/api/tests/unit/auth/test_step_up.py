"""Unit tests for `StepUpService` (E09-S04); names map to Gherkin scenarios."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from candleviewer.auth.envelope import TotpEncryptor
from candleviewer.auth.errors import (
    SessionReadOnly,
    StepUpCodeInvalid,
    StepUpRequired,
    UnknownActionClass,
)
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.mfa_service import MfaService
from candleviewer.auth.models import MfaEnrollRequest, MfaMethodKind, SessionRecord
from candleviewer.auth.step_up import StepUpService
from candleviewer.auth.totp import generate_code, time_step_for

from .auth_fakes import FakeUserRepository, make_user
from .mfa_fakes import FakeMfaRepository
from .session_fakes import FakeSessionRepository

_RC_KEY = b"k" * 32
PASSWORD = "correct horse battery staple"
_HASHER = Hasher()
_PW_HASH: list[str] = []


async def _pw_hash() -> str:
    if not _PW_HASH:  # one Argon2id hash for the whole module (slow by design)
        _PW_HASH.append(await _HASHER.hash(PASSWORD))
    return _PW_HASH[0]


_T0 = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)


async def _noop(methods: int, sessions: int, /) -> None:
    """An accepting write-ahead audit hook for `reset_totp` (#2510)."""


class _Clock:
    def __init__(self) -> None:
        self.now = _T0

    def __call__(self) -> datetime:
        return self.now


class _Positions:
    source = "oms"

    def __init__(self, count: int) -> None:
        self.count = count

    async def open_position_count(self, user_id: str) -> int | None:
        return self.count


class _NoStore:
    source = "not_deployed"

    async def open_position_count(self, user_id: str) -> int | None:
        return None


async def _setup() -> tuple[StepUpService, _Clock, bytes, uuid.UUID, FakeSessionRepository]:
    clock = _Clock()
    repo = FakeMfaRepository()
    enc = TotpEncryptor(os.urandom(32))
    mfa = MfaService(repo, enc, recovery_code_key=_RC_KEY, clock=clock)
    user = uuid.uuid4()
    res = await mfa.enroll(
        str(user), MfaEnrollRequest(method=MfaMethodKind.TOTP, label=""), account_name="o"
    )
    seed = enc.decrypt(repo.methods[str(res.method_id)].secret_enc)  # type: ignore[arg-type]
    code = generate_code(seed, time_step_for(_T0.timestamp()) - 1)
    await mfa.confirm_enrollment(str(user), method_id=str(res.method_id), code=code)
    sessions = FakeSessionRepository()
    for alias in ("s1", "s2", "o1"):  # the actor's own live session rows
        sessions.sessions[alias] = _session(user)
    users = FakeUserRepository()
    users.add(make_user(password_hash=await _pw_hash()).model_copy(update={"id": user}))
    svc = StepUpService(repo, sessions, enc, users, _HASHER, clock=clock)
    return svc, clock, seed, user, sessions


def _code(seed: bytes, clock: _Clock) -> str:
    return generate_code(seed, time_step_for(clock.now.timestamp()))


async def test_dangerous_action_requires_step_up() -> None:
    svc, *_ = await _setup()
    with pytest.raises(StepUpRequired):
        await svc.require_elevation("s1", "keys")


async def test_grace_window_within_action_class() -> None:
    svc, clock, seed, user, _ = await _setup()
    await svc.step_up(str(user), "s1", "keys", _code(seed, clock), PASSWORD)
    clock.now += timedelta(minutes=3)
    await svc.require_elevation("s1", "keys")
    assert await svc.remaining_grace("s1", "keys") == timedelta(minutes=2)
    with pytest.raises(StepUpRequired):  # other class gets no grace
        await svc.require_elevation("s1", "users")
    clock.now += timedelta(minutes=3)
    with pytest.raises(StepUpRequired):
        await svc.require_elevation("s1", "keys")


@pytest.mark.parametrize("cls", ["live_enablement", "killswitch"])
async def test_grace_never_applies_to_no_grace_classes(cls: str) -> None:
    svc, clock, seed, user, _ = await _setup()
    await svc.step_up(str(user), "s1", "keys", _code(seed, clock), PASSWORD)
    with pytest.raises(StepUpRequired):
        await svc.require_elevation("s1", cls)
    clock.now += timedelta(minutes=1)
    grant = await svc.step_up(str(user), "s1", cls, _code(seed, clock), PASSWORD)
    assert grant.single_use
    with pytest.raises(StepUpRequired):
        await svc.require_elevation("s1", cls)
    await svc.consume_single_use("s1", cls)  # one-shot grant honoured once
    with pytest.raises(StepUpRequired):
        await svc.consume_single_use("s1", cls)


async def test_three_failures_downgrade_to_readonly_for_five_minutes() -> None:
    svc, clock, seed, user, _ = await _setup()
    await svc.step_up(str(user), "s1", "keys", _code(seed, clock), PASSWORD)
    with pytest.raises(StepUpCodeInvalid) as e1:
        await svc.step_up(str(user), "s1", "keys", "000000", PASSWORD)
    assert e1.value.failures_remaining == 2
    with pytest.raises(StepUpCodeInvalid):
        await svc.step_up(str(user), "s1", "keys", "000000", PASSWORD)
    with pytest.raises(SessionReadOnly):
        await svc.step_up(str(user), "s1", "keys", "000000", PASSWORD)
    with pytest.raises(SessionReadOnly):
        await svc.assert_writable("s1")
    with pytest.raises(SessionReadOnly):  # elevation wiped by the downgrade
        await svc.require_elevation("s1", "keys")
    clock.now += timedelta(minutes=5)
    await svc.assert_writable("s1")


async def test_replayed_code_is_rejected() -> None:
    svc, clock, seed, user, _ = await _setup()
    code = _code(seed, clock)
    await svc.step_up(str(user), "s1", "keys", code, PASSWORD)
    with pytest.raises(StepUpCodeInvalid):
        await svc.step_up(str(user), "s2", "keys", code, PASSWORD)


async def test_elevation_is_bound_to_session_id() -> None:
    svc, clock, seed, user, _ = await _setup()
    await svc.step_up(str(user), "s1", "keys", _code(seed, clock), PASSWORD)
    with pytest.raises(StepUpRequired):
        await svc.require_elevation("s2", "keys")


async def test_unknown_action_class_rejected() -> None:
    svc, clock, seed, user, _ = await _setup()
    with pytest.raises(UnknownActionClass):
        await svc.step_up(str(user), "s1", "bogus", _code(seed, clock), PASSWORD)
    with pytest.raises(StepUpRequired):
        await svc.require_elevation("s1", "bogus")


def _session(user: uuid.UUID) -> SessionRecord:
    return SessionRecord(
        id=uuid.uuid4(),
        user_id=user,
        refresh_token_hash=uuid.uuid4().hex,
        access_token_jti=None,
        issued_at=_T0,
        last_seen_at=_T0,
        expires_at=_T0 + timedelta(hours=12),
        revoked_at=None,
        revoked_reason=None,
        ip=None,
        user_agent=None,
        device_label=None,
        is_electron=False,
        mfa_satisfied_at=_T0,
    )


async def test_owner_reset_revokes_sessions_without_oms_effects_or_secret() -> None:
    svc, clock, seed, owner, sessions = await _setup()
    target = uuid.uuid4()
    s = _session(target)
    await sessions.create_session(s)
    positions = _Positions(3)
    preview = await svc.preview_reset(str(target), positions)
    assert preview.open_position_count == 3
    assert "NOT cancel" in preview.message
    with pytest.raises(StepUpRequired):  # reset itself needs fresh step-up
        await svc.reset_totp(
            actor_session_id="o1", actor_user_id=str(owner), target_user_id=str(target), audit=_noop
        )
    await svc.step_up(str(owner), "o1", "users", _code(seed, clock), PASSWORD)
    result = await svc.reset_totp(
        actor_session_id="o1", actor_user_id=str(owner), target_user_id=str(target), audit=_noop
    )
    assert result.sessions_revoked == 1
    assert sessions.sessions[str(s.id)].revoked_at is not None
    assert not hasattr(result, "secret") and not hasattr(result, "recovery_codes")
    assert positions.count == 3  # read-only provider; no OMS mutation API exists


async def test_owner_cannot_reset_self() -> None:
    svc, clock, seed, owner, _ = await _setup()
    await svc.step_up(str(owner), "o1", "users", _code(seed, clock), PASSWORD)
    with pytest.raises(StepUpRequired):
        await svc.reset_totp(
            actor_session_id="o1", actor_user_id=str(owner), target_user_id=str(owner), audit=_noop
        )


async def test_preview_with_no_position_store_reports_unknown_not_zero() -> None:
    svc, *_ = await _setup()
    preview = await svc.preview_reset(str(uuid.uuid4()), _NoStore())
    assert preview.open_position_count is None
    assert not preview.positions_known
    assert preview.position_source == "not_deployed"
    assert "UNAVAILABLE" in preview.message and "0 open" not in preview.message


async def test_preview_with_real_store_reports_count() -> None:
    svc, *_ = await _setup()
    preview = await svc.preview_reset(str(uuid.uuid4()), _Positions(2))
    assert preview.positions_known and preview.open_position_count == 2
    assert preview.position_source == "oms"


async def test_elevation_persists_on_session_row_across_restart() -> None:
    svc, clock, seed, user, sessions = await _setup()
    await svc.step_up(str(user), "s1", "keys", _code(seed, clock), PASSWORD)
    assert "keys" in sessions.sessions["s1"].step_up_elevations
    # Process restart: a brand-new service over the same session store.
    rebuilt = StepUpService(
        FakeMfaRepository(), sessions, svc._encryptor, svc._users, svc._hasher, clock=clock
    )
    clock.now += timedelta(minutes=4)
    await rebuilt.require_elevation("s1", "keys")
    clock.now += timedelta(minutes=2)  # past the 5-minute expiry
    with pytest.raises(StepUpRequired):
        await rebuilt.require_elevation("s1", "keys")


async def test_strikes_and_readonly_persist_across_restart() -> None:
    svc, clock, seed, user, sessions = await _setup()
    for _ in range(2):
        with pytest.raises(StepUpCodeInvalid):
            await svc.step_up(str(user), "s1", "keys", "000000", PASSWORD)
    rebuilt = StepUpService(
        svc._mfa, sessions, svc._encryptor, svc._users, svc._hasher, clock=clock
    )
    with pytest.raises(SessionReadOnly):  # third strike counted after restart
        await rebuilt.step_up(str(user), "s1", "keys", "000000", PASSWORD)
    again = StepUpService(svc._mfa, sessions, svc._encryptor, svc._users, svc._hasher, clock=clock)
    with pytest.raises(SessionReadOnly):
        await again.assert_writable("s1")


async def test_elevation_is_revoked_with_the_session() -> None:
    svc, clock, seed, user, sessions = await _setup()
    await svc.step_up(str(user), "s1", "keys", _code(seed, clock), PASSWORD)
    await sessions.revoke("s1", reason="logout", now=clock.now)
    with pytest.raises(StepUpRequired):
        await svc.require_elevation("s1", "keys")


def _sample(name: str, **labels: str) -> float:
    from prometheus_client import REGISTRY

    return REGISTRY.get_sample_value(name, labels) or 0.0


async def test_step_up_and_reset_metrics_are_emitted() -> None:
    svc, clock, seed, owner, sessions = await _setup()
    ok0 = _sample("auth_step_up_total", action_class="users")
    bad0 = _sample("auth_step_up_failures_total", action_class="keys")
    ro0 = _sample("auth_readonly_downgrades_total")
    rs0 = _sample("auth_mfa_resets_total")
    await svc.step_up(str(owner), "o1", "users", _code(seed, clock), PASSWORD)
    assert _sample("auth_step_up_total", action_class="users") == ok0 + 1
    for _ in range(2):
        with pytest.raises(StepUpCodeInvalid):
            await svc.step_up(str(owner), "s1", "keys", "000000", PASSWORD)
    with pytest.raises(SessionReadOnly):
        await svc.step_up(str(owner), "s1", "keys", "000000", PASSWORD)
    assert _sample("auth_step_up_failures_total", action_class="keys") == bad0 + 3
    assert _sample("auth_readonly_downgrades_total") == ro0 + 1
    target = uuid.uuid4()
    await sessions.create_session(_session(target))
    await svc.reset_totp(
        actor_session_id="o1", actor_user_id=str(owner), target_user_id=str(target), audit=_noop
    )
    assert _sample("auth_mfa_resets_total") == rs0 + 1


# -- #1778 AE (D-2): password + TOTP ---------------------------------------------


async def test_wrong_password_refused_counts_lockout_and_keeps_totp_step_unburnt() -> None:
    svc, clock, seed, user, _ = await _setup()
    code = _code(seed, clock)
    with pytest.raises(StepUpCodeInvalid) as bad_pw:
        await svc.step_up(str(user), "s1", "keys", code, "wrong password")
    with pytest.raises(StepUpCodeInvalid) as bad_code:
        await svc.step_up(str(user), "s1", "keys", "000000", PASSWORD)
    assert str(bad_pw.value) == str(bad_code.value)  # indistinguishable
    assert svc._users.users[str(user)].failed_login_count == 1  # type: ignore[attr-defined]
    # the code was never consumed by the wrong-password attempt
    grant = await svc.step_up(str(user), "s1", "keys", code, PASSWORD)
    assert grant.action_class == "keys"


async def test_wrong_password_lockout_uses_login_counters_and_refuses_correct_factors() -> None:
    svc, clock, seed, user, _ = await _setup()
    for i, sid in enumerate(("s1", "s2", "o1", "s1", "s2")):
        clock.now += timedelta(minutes=6)  # clear the 3-strike read-only window between tries
        with pytest.raises((StepUpCodeInvalid, SessionReadOnly)):
            await svc.step_up(str(user), sid, "keys", "000000", f"bad{i}")
    assert svc._users.users[str(user)].locked_until is not None  # type: ignore[attr-defined]
    clock.now += timedelta(minutes=6)
    with pytest.raises(StepUpCodeInvalid):  # locked: correct factors still refused
        await svc.step_up(str(user), "o1", "keys", _code(seed, clock), PASSWORD)


# -- SR-125 / #2117: `auth_stepup_failures_total` and `auth_lockouts_total` -------------------


async def test_step_up_failures_move_the_catalogue_counter_for_password_and_code() -> None:
    svc, clock, seed, user, _ = await _setup()
    before = _sample("auth_stepup_failures_total")
    code = _code(seed, clock)
    with pytest.raises(StepUpCodeInvalid):
        await svc.step_up(str(user), "s1", "keys", code, "wrong password")  # wrong password
    with pytest.raises(StepUpCodeInvalid):
        await svc.step_up(str(user), "s1", "keys", "000000", PASSWORD)  # wrong code
    assert _sample("auth_stepup_failures_total") == before + 2
    grant = await svc.step_up(str(user), "s1", "keys", code, PASSWORD)  # the code was not burnt
    assert grant.action_class == "keys"
    assert _sample("auth_stepup_failures_total") == before + 2  # success does not move it


async def test_step_up_refused_before_verification_does_not_move_the_failure_counter() -> None:
    svc, _, _, user, _ = await _setup()
    before = _sample("auth_stepup_failures_total")
    with pytest.raises(UnknownActionClass):
        await svc.step_up(str(user), "s1", "not-a-class", "000000", PASSWORD)
    with pytest.raises(StepUpRequired):  # no live session row for this id
        await svc.step_up(str(user), "no-such-session", "keys", "000000", PASSWORD)
    assert _sample("auth_stepup_failures_total") == before


async def test_step_up_wrong_password_that_trips_the_lock_moves_auth_lockouts_total() -> None:
    svc, clock, _, user, _ = await _setup()
    before = _sample("auth_lockouts_total")
    for i, sid in enumerate(("s1", "s2", "o1", "s1")):  # one short of the threshold
        clock.now += timedelta(minutes=6)  # clear the 3-strike read-only window between tries
        with pytest.raises((StepUpCodeInvalid, SessionReadOnly)):
            await svc.step_up(str(user), sid, "keys", "000000", f"bad{i}")
    assert _sample("auth_lockouts_total") == before
    clock.now += timedelta(minutes=6)
    with pytest.raises((StepUpCodeInvalid, SessionReadOnly)):
        await svc.step_up(str(user), "s2", "keys", "000000", "bad-last")
    assert svc._users.users[str(user)].locked_until is not None  # type: ignore[attr-defined]
    assert _sample("auth_lockouts_total") == before + 1


async def test_step_up_on_a_locked_account_does_not_move_the_lockout_counter() -> None:
    svc, clock, _, user, _ = await _setup()
    for i, sid in enumerate(("s1", "s2", "o1", "s1", "s2")):
        clock.now += timedelta(minutes=6)
        with pytest.raises((StepUpCodeInvalid, SessionReadOnly)):
            await svc.step_up(str(user), sid, "keys", "000000", f"bad{i}")
    locked = _sample("auth_lockouts_total")
    clock.now += timedelta(minutes=6)  # still inside the 15 minute lock
    with pytest.raises((StepUpCodeInvalid, SessionReadOnly)):
        await svc.step_up(str(user), "o1", "keys", "000000", "bad-again")
    assert _sample("auth_lockouts_total") == locked
