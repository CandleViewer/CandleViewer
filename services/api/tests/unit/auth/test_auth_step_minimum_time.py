"""#4664: the second factor, the recovery code and step-up hold their refusals to the minimum time.

Each refusal returns no sooner than the minimum time after its step started, after its failure
write; a refusal that is already slower is not held further and is counted; a success is never
held; a cancellation during the wait propagates; a minimum time below the setting's lowest value
is refused. Time is a fake monotonic clock that moves only when a spy does work or the service
waits (C-13.7). No sleeps, no network.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from prometheus_client import REGISTRY

from candleviewer.auth.errors import (
    MfaChallengeInvalid,
    MfaChallengeLocked,
    MfaCodeInvalid,
    MfaCodeReused,
    RecoveryCodeInvalid,
    RecoveryCodesExhausted,
    SessionReadOnly,
    SessionRevoked,
    StepUpCodeInvalid,
    UnknownActionClass,
)
from candleviewer.auth.failure_hold import FAILURE_MINIMUM, FAILURE_MINIMUM_LOWEST, FailureHold
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.mfa_service import CHALLENGE_ATTEMPT_CAP, MfaService, _hash_token
from candleviewer.auth.models import (
    MfaChallengeRecord,
    MfaMethodKind,
    MfaVerifyRequest,
    SessionRecord,
)
from candleviewer.auth.recovery_codes import generate_recovery_codes, hash_recovery_code
from candleviewer.auth.session_repository import StepUpChange
from candleviewer.auth.step_up import FAILURE_CAP, StepUpService
from candleviewer.auth.totp import generate_code, generate_secret, time_step_for
from candleviewer.settings import AUTH_LOGIN_FAILURE_FLOOR_MIN_MS
from tests.unit.auth.mfa_fakes import FakeMfaKeyring

from .auth_fakes import FakeUserRepository, make_user
from .mfa_fakes import FakeMfaRepository
from .session_fakes import FakeSessionRepository

_NOW = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)
_MIN_S = FAILURE_MINIMUM.total_seconds()
_WORK_S = 0.01
_RC_KEY = b"k" * 32
_TOKEN = "an-opaque-challenge-token"
PASSWORD = "correct horse battery staple"
Event = tuple[Any, ...]
#: #4664: minimum times every service refuses (zero, and just below the setting's lowest).
_BELOW_THE_LOWEST = [timedelta(0), FAILURE_MINIMUM_LOWEST - timedelta(milliseconds=1)]


class _FakeTime:
    """A monotonic clock that only moves when a spy works or the service waits."""

    def __init__(self, events: list[Event], *, work_s: float) -> None:
        self.events = events
        self.work_s = work_s
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def work(self) -> None:
        self.now += self.work_s

    async def sleep(self, delay: float) -> None:
        self.events.append(("sleep", delay))
        self.now += delay


def _missed() -> float:
    return float(REGISTRY.get_sample_value("auth_login_failure_floor_missed_total") or 0.0)


def _sleeps(events: list[Event]) -> list[Event]:
    return [e for e in events if e[0] == "sleep"]


# --- the second factor and the recovery code (MfaService) ---------------------------------


class _SpyMfaRepository(FakeMfaRepository):
    def __init__(self, events: list[Event], time: _FakeTime) -> None:
        super().__init__()
        self.events = events
        self.time = time

    async def find_open_challenge_by_token_hash(
        self, mfa_token_hash: str
    ) -> MfaChallengeRecord | None:
        self.time.work()  # the lookup's work, on the fake clock
        return await super().find_open_challenge_by_token_hash(mfa_token_hash)

    async def record_challenge_attempt(self, challenge_id: str) -> int:
        self.events.append(("record_challenge_attempt",))
        return await super().record_challenge_attempt(challenge_id)


class _MfaWorld:
    def __init__(self, *, work_s: float = _WORK_S) -> None:
        self.events: list[Event] = []
        self.time = _FakeTime(self.events, work_s=work_s)
        self.repo = _SpyMfaRepository(self.events, self.time)
        self.enc = FakeMfaKeyring(os.urandom(32), _RC_KEY)
        self.user = uuid.uuid4()
        self.seed = generate_secret()
        self.svc = MfaService(
            self.repo,
            self.enc,
            clock=lambda: _NOW,
            monotonic=self.time.monotonic,
            sleep=self.time.sleep,
        )

    async def add_method(self) -> None:
        method = await self.repo.create_pending_method(
            str(self.user),
            secret_enc=self.enc.encrypt(self.seed),
            secret_key_ref=self.enc.key_ref,
            label="",
        )
        await self.repo.seed_confirmed(str(method.id), now=_NOW)

    async def open_challenge(self, *, attempts: int = 0, expired: bool = False) -> str:
        expires = _NOW - timedelta(seconds=1) if expired else _NOW + timedelta(minutes=5)
        challenge = await self.repo.create_challenge(
            str(self.user), purpose="login", mfa_token_hash=_hash_token(_TOKEN), expires_at=expires
        )
        self.repo.challenges[str(challenge.id)] = challenge.model_copy(
            update={"attempts": attempts}
        )
        return str(challenge.id)

    def code(self) -> str:
        return generate_code(self.seed, time_step_for(_NOW.timestamp()))

    def wrong_code(self) -> str:
        return "000000" if self.code() != "000000" else "111111"

    async def verify(self, code: str, method: MfaMethodKind = MfaMethodKind.TOTP) -> None:
        await self.svc.verify(MfaVerifyRequest(mfa_token=_TOKEN, method=method, code=code))

    async def add_recovery_codes(self, count: int = 10) -> list[str]:
        codes = generate_recovery_codes(count=count)
        await self.repo.replace_recovery_codes(
            str(self.user), code_hashes=tuple(hash_recovery_code(c, key=_RC_KEY) for c in codes)
        )
        return codes


async def _totp_ready(*, work_s: float = _WORK_S) -> _MfaWorld:
    world = _MfaWorld(work_s=work_s)
    await world.add_method()
    await world.open_challenge()
    return world


async def test_mfa_verify_wrong_code_returns_exactly_at_the_minimum_time() -> None:
    world = await _totp_ready()

    with pytest.raises(MfaCodeInvalid):
        await world.verify(world.wrong_code())

    assert world.time.now == pytest.approx(_MIN_S)
    assert _sleeps(world.events) == [("sleep", pytest.approx(_MIN_S - _WORK_S))]


async def test_mfa_verify_attempt_count_is_written_before_the_wait() -> None:
    world = await _totp_ready()

    with pytest.raises(MfaCodeInvalid):
        await world.verify(world.wrong_code())

    assert [e[0] for e in world.events] == ["record_challenge_attempt", "sleep"]


async def test_mfa_verify_reused_code_is_held_after_its_attempt_count() -> None:
    world = await _totp_ready()
    await world.verify(world.code())  # accepted, never held
    await world.open_challenge()
    world.events.clear()
    world.time.now = 0.0

    with pytest.raises(MfaCodeReused):
        await world.verify(world.code())

    assert world.time.now == pytest.approx(_MIN_S)
    assert [e[0] for e in world.events] == ["record_challenge_attempt", "sleep"]


async def test_mfa_verify_attempt_that_locks_the_challenge_is_held() -> None:
    world = _MfaWorld()
    await world.add_method()
    await world.open_challenge(attempts=CHALLENGE_ATTEMPT_CAP - 1)

    with pytest.raises(MfaChallengeLocked):
        await world.verify(world.wrong_code())

    assert world.time.now == pytest.approx(_MIN_S)
    assert [e[0] for e in world.events] == ["record_challenge_attempt", "sleep"]


@pytest.mark.parametrize(
    ("state", "refusal"),
    [
        ("no_challenge", MfaChallengeInvalid),
        ("expired", MfaChallengeInvalid),
        ("locked", MfaChallengeLocked),
        ("no_method", MfaCodeInvalid),
        ("other_method", MfaCodeInvalid),
    ],
)
async def test_mfa_verify_every_other_refusal_is_held_to_the_minimum_time(
    state: str, refusal: type[Exception]
) -> None:
    world = _MfaWorld()
    if state != "no_method":
        await world.add_method()
    if state == "expired":
        await world.open_challenge(expired=True)
    elif state == "locked":
        await world.open_challenge(attempts=CHALLENGE_ATTEMPT_CAP)
    elif state != "no_challenge":
        await world.open_challenge()
    method = MfaMethodKind.WEBAUTHN if state == "other_method" else MfaMethodKind.TOTP

    with pytest.raises(refusal):
        await world.verify(world.code(), method)

    assert world.time.now == pytest.approx(_MIN_S)
    assert len(_sleeps(world.events)) == 1


async def test_mfa_verify_success_is_never_held() -> None:
    world = await _totp_ready(work_s=_MIN_S + 0.5)
    before = _missed()

    await world.verify(world.code())

    assert not _sleeps(world.events)
    assert _missed() == before


async def test_mfa_verify_slow_refusal_is_not_held_further_and_is_counted() -> None:
    slow = _MIN_S + 0.5
    world = await _totp_ready(work_s=slow)
    before = _missed()

    with pytest.raises(MfaCodeInvalid):
        await world.verify(world.wrong_code())

    assert world.time.now == pytest.approx(slow)
    assert not _sleeps(world.events)
    assert _missed() == before + 1


async def test_mfa_verify_cancellation_during_the_wait_propagates() -> None:
    world = await _totp_ready()
    waiting = asyncio.Event()

    async def held(delay: float) -> None:
        world.events.append(("sleep", delay))
        waiting.set()
        await asyncio.Event().wait()  # never set: only a cancellation ends it

    world.svc._failure_hold._sleep = held
    attempt = asyncio.create_task(world.verify(world.wrong_code()))
    async with asyncio.timeout(5):  # a guard only: a correct service starts the wait at once
        await waiting.wait()
    attempt.cancel()

    with pytest.raises(asyncio.CancelledError):
        await attempt
    assert [e[0] for e in world.events] == ["record_challenge_attempt", "sleep"]


async def test_mfa_recovery_wrong_code_is_held_after_its_attempt_count() -> None:
    world = _MfaWorld()
    await world.add_recovery_codes()
    await world.open_challenge()

    with pytest.raises(RecoveryCodeInvalid):
        await world.svc.check_recovery(_TOKEN, "not-a-recovery-code")

    assert world.time.now == pytest.approx(_MIN_S)
    assert [e[0] for e in world.events] == ["record_challenge_attempt", "sleep"]


async def test_mfa_recovery_with_no_codes_left_is_held_after_its_attempt_count() -> None:
    world = _MfaWorld()
    await world.open_challenge()

    with pytest.raises(RecoveryCodesExhausted):
        await world.svc.check_recovery(_TOKEN, "not-a-recovery-code")

    assert world.time.now == pytest.approx(_MIN_S)
    assert [e[0] for e in world.events] == ["record_challenge_attempt", "sleep"]


async def test_mfa_recovery_without_an_open_challenge_is_held() -> None:
    world = _MfaWorld()

    with pytest.raises(MfaChallengeInvalid):
        await world.svc.check_recovery(_TOKEN, "not-a-recovery-code")

    assert world.time.now == pytest.approx(_MIN_S)


async def test_mfa_recovery_match_is_never_held() -> None:
    world = _MfaWorld()
    codes = await world.add_recovery_codes()
    await world.open_challenge()

    check = await world.svc.check_recovery(_TOKEN, codes[0])

    assert check.user_id == world.user
    assert not _sleeps(world.events)


async def test_mfa_recovery_slow_refusal_is_not_held_further_and_is_counted() -> None:
    slow = _MIN_S + 0.5
    world = _MfaWorld(work_s=slow)
    await world.add_recovery_codes()
    await world.open_challenge()
    before = _missed()

    with pytest.raises(RecoveryCodeInvalid):
        await world.svc.check_recovery(_TOKEN, "not-a-recovery-code")

    assert world.time.now == pytest.approx(slow)
    assert not _sleeps(world.events)
    assert _missed() == before + 1


async def test_mfa_recovery_spent_first_by_another_request_is_answered_at_once() -> None:
    world = _MfaWorld()
    codes = await world.add_recovery_codes()
    await world.open_challenge()
    check = await world.svc.check_recovery(_TOKEN, codes[0])
    await world.svc.complete_recovery(check)  # the other request spends it first
    world.events.clear()

    with pytest.raises(RecoveryCodeInvalid):
        await world.svc.complete_recovery(check)

    assert [e[0] for e in world.events] == ["record_challenge_attempt"]
    assert not _sleeps(world.events)


@pytest.mark.parametrize("below", _BELOW_THE_LOWEST)
def test_mfa_service_refuses_a_minimum_time_below_the_settings_lowest_value(
    below: timedelta,
) -> None:
    with pytest.raises(ValueError, match=str(AUTH_LOGIN_FAILURE_FLOOR_MIN_MS)):
        MfaService(
            FakeMfaRepository(),
            FakeMfaKeyring(os.urandom(32), _RC_KEY),
            failure_floor=below,
        )


# --- step-up and its password re-check (StepUpService) ------------------------------------

_HASHER = Hasher()
_PW_HASH: list[str] = []


async def _pw_hash() -> str:
    if not _PW_HASH:  # one Argon2id hash for the whole module (slow by design)
        _PW_HASH.append(await _HASHER.hash(PASSWORD))
    return _PW_HASH[0]


class _SpySessions(FakeSessionRepository):
    def __init__(self, events: list[Event], time: _FakeTime) -> None:
        super().__init__()
        self.events = events
        self.time = time
        #: The session is revoked between the read and this write (the write finds no live row).
        self.revoked_at_the_write = False

    async def update_step_up_state(
        self, session_id: str, change: StepUpChange
    ) -> SessionRecord | None:
        self.events.append(("update_step_up_state",))
        self.time.work()  # the write's work, on the fake clock
        if self.revoked_at_the_write:
            return None
        return await super().update_step_up_state(session_id, change)


class _SpyUsers(FakeUserRepository):
    def __init__(self, events: list[Event], time: _FakeTime) -> None:
        super().__init__()
        self.events = events
        self.time = time

    async def record_login_failure(
        self, user_id: str, *, lockout_threshold: int, lock_duration: timedelta, now: datetime
    ) -> datetime | None:
        self.events.append(("record_login_failure",))
        self.time.work()
        return await super().record_login_failure(
            user_id, lockout_threshold=lockout_threshold, lock_duration=lock_duration, now=now
        )


def _session(user: uuid.UUID) -> SessionRecord:
    return SessionRecord(
        id=uuid.uuid4(),
        user_id=user,
        refresh_token_hash=uuid.uuid4().hex,
        access_token_jti=None,
        issued_at=_NOW,
        last_seen_at=_NOW,
        expires_at=_NOW + timedelta(hours=12),
        revoked_at=None,
        revoked_reason=None,
        ip=None,
        user_agent=None,
        device_label=None,
        is_electron=False,
        mfa_satisfied_at=_NOW,
    )


class _StepUpWorld:
    def __init__(self, *, work_s: float) -> None:
        self.events: list[Event] = []
        self.time = _FakeTime(self.events, work_s=work_s)
        self.mfa = _MfaWorld()
        self.sessions = _SpySessions(self.events, self.time)
        self.users = _SpyUsers(self.events, self.time)
        self.user = self.mfa.user
        self.sessions.sessions["s1"] = _session(self.user)
        self.svc = StepUpService(
            self.mfa.repo,
            self.sessions,
            self.mfa.enc,
            self.users,
            _HASHER,
            clock=lambda: _NOW,
            monotonic=self.time.monotonic,
            sleep=self.time.sleep,
        )

    def wrong_code(self) -> str:
        return self.mfa.wrong_code()

    async def step_up(self, code: str, password: str = PASSWORD) -> object:
        return await self.svc.step_up(str(self.user), "s1", "keys", code, password)


async def _step_up_world(*, work_s: float = _WORK_S) -> _StepUpWorld:
    world = _StepUpWorld(work_s=work_s)
    await world.mfa.add_method()
    world.users.add(make_user(password_hash=await _pw_hash()).model_copy(update={"id": world.user}))
    return world


@pytest.mark.parametrize("factor", ["password", "code"])
async def test_step_up_wrong_factor_returns_exactly_at_the_minimum_time(factor: str) -> None:
    world = await _step_up_world()
    code = world.wrong_code() if factor == "code" else world.mfa.code()
    password = "a-guess" if factor == "password" else PASSWORD

    with pytest.raises(StepUpCodeInvalid):
        await world.step_up(code, password)

    assert world.time.now == pytest.approx(_MIN_S)
    assert len(_sleeps(world.events)) == 1


async def test_step_up_strike_is_written_before_the_wait() -> None:
    world = await _step_up_world()

    with pytest.raises(StepUpCodeInvalid):
        await world.step_up(world.wrong_code())

    names = [e[0] for e in world.events]
    assert names.index("update_step_up_state") < names.index("sleep")
    assert names[-1] == "sleep"


async def test_step_up_refusal_that_downgrades_the_session_is_held() -> None:
    world = await _step_up_world()
    for _ in range(FAILURE_CAP - 1):
        with pytest.raises(StepUpCodeInvalid):
            await world.step_up(world.wrong_code())
    world.events.clear()
    world.time.now = 0.0

    with pytest.raises(SessionReadOnly):
        await world.step_up(world.wrong_code())

    assert world.time.now == pytest.approx(_MIN_S)
    assert [e[0] for e in world.events][-1] == "sleep"


async def test_step_up_grant_is_never_held() -> None:
    world = await _step_up_world(work_s=_MIN_S + 0.5)
    before = _missed()

    await world.step_up(world.mfa.code())

    assert not _sleeps(world.events)
    assert _missed() == before


async def test_step_up_slow_refusal_is_not_held_further_and_is_counted() -> None:
    slow = _MIN_S + 0.5
    world = await _step_up_world(work_s=slow)
    before = _missed()

    with pytest.raises(StepUpCodeInvalid):
        await world.step_up(world.wrong_code())

    assert world.time.now == pytest.approx(slow)
    assert not _sleeps(world.events)
    assert _missed() == before + 1


async def test_step_up_refusal_decided_before_the_factors_is_answered_at_once() -> None:
    world = await _step_up_world()

    with pytest.raises(UnknownActionClass):
        await world.svc.step_up(str(world.user), "s1", "no-such-class", world.mfa.code(), PASSWORD)

    assert not _sleeps(world.events)


async def test_step_up_session_revoked_during_the_check_is_held() -> None:
    world = await _step_up_world()
    world.sessions.revoked_at_the_write = True

    with pytest.raises(SessionRevoked):
        await world.step_up(world.wrong_code())

    assert world.time.now == pytest.approx(_MIN_S)
    assert [e[0] for e in world.events][-2:] == ["update_step_up_state", "sleep"]


async def test_step_up_session_revoked_before_the_check_is_answered_at_once() -> None:
    world = await _step_up_world()
    await world.sessions.revoke("s1", reason="logout", now=_NOW)

    with pytest.raises(SessionRevoked):
        await world.step_up(world.wrong_code())

    assert not _sleeps(world.events)


async def test_step_up_cancellation_during_the_wait_propagates() -> None:
    world = await _step_up_world()
    waiting = asyncio.Event()

    async def held(delay: float) -> None:
        world.events.append(("sleep", delay))
        waiting.set()
        await asyncio.Event().wait()  # never set: only a cancellation ends it

    world.svc._failure_hold._sleep = held
    attempt = asyncio.create_task(world.step_up(world.wrong_code()))
    async with asyncio.timeout(30):  # a guard only (one Argon2id verify runs first)
        await waiting.wait()
    attempt.cancel()

    with pytest.raises(asyncio.CancelledError):
        await attempt
    assert [e[0] for e in world.events][-2:] == ["update_step_up_state", "sleep"]


async def test_step_up_password_recheck_failure_is_held_after_its_failure_count() -> None:
    world = await _step_up_world()

    verdict = await world.svc.verify_password(str(world.user), "a-guess")

    assert not verdict.ok
    assert world.time.now == pytest.approx(_MIN_S)
    assert [e[0] for e in world.events] == ["record_login_failure", "sleep"]


async def test_step_up_password_recheck_for_an_unknown_account_is_held() -> None:
    world = await _step_up_world()

    verdict = await world.svc.verify_password(str(uuid.uuid4()), PASSWORD)

    assert not verdict.ok
    assert len(_sleeps(world.events)) == 1


async def test_step_up_password_recheck_slow_failure_is_not_held_further_and_is_counted() -> None:
    slow = _MIN_S + 0.5
    world = await _step_up_world(work_s=slow)
    before = _missed()

    verdict = await world.svc.verify_password(str(world.user), "a-guess")

    assert not verdict.ok
    assert world.time.now == pytest.approx(slow)
    assert not _sleeps(world.events)
    assert _missed() == before + 1


async def test_step_up_password_recheck_left_to_the_caller_is_not_held_here() -> None:
    world = await _step_up_world()

    verdict = await world.svc.verify_password(str(world.user), "a-guess", hold=False)

    assert not verdict.ok
    assert [e[0] for e in world.events] == ["record_login_failure"]
    assert world.svc.failure_hold.minimum == FAILURE_MINIMUM


async def test_step_up_password_recheck_success_is_never_held() -> None:
    world = await _step_up_world()

    verdict = await world.svc.verify_password(str(world.user), PASSWORD)

    assert verdict.ok
    assert not _sleeps(world.events)


@pytest.mark.parametrize("below", _BELOW_THE_LOWEST)
def test_step_up_service_refuses_a_minimum_time_below_the_settings_lowest_value(
    below: timedelta,
) -> None:
    with pytest.raises(ValueError, match=str(AUTH_LOGIN_FAILURE_FLOOR_MIN_MS)):
        StepUpService(
            FakeMfaRepository(),
            FakeSessionRepository(),
            FakeMfaKeyring(os.urandom(32)),
            FakeUserRepository(),
            _HASHER,
            failure_floor=below,
        )


# --- the hold itself ------------------------------------------------------------------------


async def test_failure_hold_wait_is_bounded_by_the_minimum_when_the_clock_steps_back() -> None:
    events: list[Event] = []
    time = _FakeTime(events, work_s=0.0)
    readings = iter([100.0, 40.0])  # started, then an earlier reading at the wait
    hold = FailureHold(monotonic=lambda: next(readings), sleep=time.sleep)

    await hold.hold(hold.start())

    assert _sleeps(events) == [("sleep", _MIN_S)]
