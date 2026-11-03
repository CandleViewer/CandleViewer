"""#5563: a step-up password attempt is counted, and the lock applied, before it is verified.

Step-up takes the account reservation sign-in takes since #2802 (`reserve_login_attempt`); only an
attempt holding one is verified against the account's hash. A locked account runs only the dummy
verification; a correct password whose attempt was in flight when another attempt's lock landed is
refused in step-up's own refusal shape; a correct step-up gives its reservation back.
`_verify_sync` is the seam every Argon2id verification passes through, the dummy one included.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from prometheus_client import REGISTRY

from candleviewer.auth.errors import SessionReadOnly, StepUpCodeInvalid
from candleviewer.auth.hashing import DUMMY_PASSWORD_HASH, Hasher
from candleviewer.auth.login_service import LOCKOUT_DURATION, LOCKOUT_THRESHOLD
from candleviewer.auth.mfa_service import MfaService
from candleviewer.auth.models import MfaEnrollRequest, MfaMethodKind, SessionRecord
from candleviewer.auth.step_up import StepUpService
from candleviewer.auth.totp import generate_code, time_step_for
from tests.unit.auth.auth_fakes import FakeUserRepository, make_user, no_wait
from tests.unit.auth.mfa_fakes import FakeMfaKeyring, FakeMfaRepository
from tests.unit.auth.session_fakes import FakeSessionRepository

PASSWORD = "correct horse battery staple"
_NOW = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)
_RC_KEY = b"k" * 32
_BURST = LOCKOUT_THRESHOLD * 2


class _SpyHasher(Hasher):
    """Counts every Argon2id verification by its target hash; can hold the correct password's
    verification until the test lets it go."""

    def __init__(self) -> None:
        super().__init__(pepper="test-pepper")
        self.verified: list[str] = []
        self.hold_correct = False
        self.correct_entered = asyncio.Event()
        self.release_correct = asyncio.Event()

    def _verify_sync(self, password_hash: str, peppered_password: str) -> bool:
        self.verified.append(password_hash)  # list.append is atomic across the worker threads
        return super()._verify_sync(password_hash, peppered_password)

    async def verify(self, password_hash: str, password: str) -> bool:
        if self.hold_correct and password == PASSWORD:
            self.correct_entered.set()
            await self.release_correct.wait()
        return await super().verify(password_hash, password)


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


class _World:
    svc: StepUpService
    users: FakeUserRepository
    hasher: _SpyHasher
    user: uuid.UUID
    seed: bytes

    @property
    def uid(self) -> str:
        return str(self.user)

    def code(self) -> str:
        return generate_code(self.seed, time_step_for(_NOW.timestamp()))

    def real(self) -> int:
        """Verifications against the account's own hash: the guesses the attacker got."""
        own = self.users.users[self.uid].password_hash
        return sum(h == own for h in self.hasher.verified)

    async def attempt(self, session: str, password: str, code: str = "000000") -> object:
        try:
            return await self.svc.step_up(self.uid, session, "keys", code, password)
        except (StepUpCodeInvalid, SessionReadOnly) as exc:
            return exc


async def _world(
    *, failed_login_count: int = 0, locked_until: datetime | None = None, sessions: int = 1
) -> _World:
    world = _World()
    repo = FakeMfaRepository()
    enc = FakeMfaKeyring(os.urandom(32), _RC_KEY)
    mfa = MfaService(repo, enc, clock=lambda: _NOW, sleep=no_wait)
    world.user = uuid.uuid4()
    res = await mfa.enroll(
        world.uid, MfaEnrollRequest(method=MfaMethodKind.TOTP, label=""), account_name="o"
    )
    secret = repo.methods[str(res.method_id)].secret_enc
    assert secret is not None
    world.seed = enc.decrypt(secret)
    confirm = generate_code(world.seed, time_step_for(_NOW.timestamp()) - 1)
    await mfa.confirm_enrollment(world.uid, method_id=str(res.method_id), code=confirm)
    session_repo = FakeSessionRepository()
    for i in range(sessions):  # one session per attempt: no attempt meets another's strikes
        session_repo.sessions[f"s{i}"] = _session(world.user)
    world.hasher = _SpyHasher()
    world.users = FakeUserRepository()
    world.users.add(
        make_user(
            password_hash=await world.hasher.hash(PASSWORD),
            failed_login_count=failed_login_count,
            locked_until=locked_until,
        ).model_copy(update={"id": world.user})
    )
    world.hasher.verified.clear()
    world.svc = StepUpService(
        repo, session_repo, enc, world.users, world.hasher, clock=lambda: _NOW, sleep=no_wait
    )
    return world


def _lockouts() -> float:
    return REGISTRY.get_sample_value("auth_lockouts_total") or 0.0


async def test_step_up_burst_of_wrong_passwords_verifies_at_most_threshold() -> None:
    world = await _world(sessions=_BURST)
    before = _lockouts()

    results = await asyncio.gather(*(world.attempt(f"s{i}", f"bad{i}") for i in range(_BURST)))

    assert world.real() == LOCKOUT_THRESHOLD
    assert world.hasher.verified.count(DUMMY_PASSWORD_HASH) == _BURST - LOCKOUT_THRESHOLD
    assert all(isinstance(r, StepUpCodeInvalid) for r in results)  # one refusal shape for all
    assert world.users.users[world.uid].failed_login_count == LOCKOUT_THRESHOLD
    assert world.users.users[world.uid].locked_until == _NOW + LOCKOUT_DURATION
    assert _lockouts() == before + 1  # one lock, counted once


async def test_step_up_correct_password_in_flight_when_the_lock_lands_is_refused() -> None:
    world = await _world(sessions=LOCKOUT_THRESHOLD + 1)
    world.hasher.hold_correct = True
    correct = asyncio.create_task(world.attempt("s0", PASSWORD, world.code()))
    await world.hasher.correct_entered.wait()  # its reservation is taken; its verify is held

    await asyncio.gather(*(world.attempt(f"s{i}", f"bad{i}") for i in range(1, 6)))
    assert world.users.users[world.uid].locked_until == _NOW + LOCKOUT_DURATION
    world.hasher.release_correct.set()

    assert isinstance(await correct, StepUpCodeInvalid)  # step-up's own refusal, no grant
    assert world.users.users[world.uid].locked_until == _NOW + LOCKOUT_DURATION


async def test_step_up_on_a_locked_account_runs_only_the_dummy_verify() -> None:
    world = await _world(failed_login_count=LOCKOUT_THRESHOLD, locked_until=_NOW + timedelta(1))

    result = await world.attempt("s0", PASSWORD, world.code())

    assert isinstance(result, StepUpCodeInvalid)
    assert world.hasher.verified == [DUMMY_PASSWORD_HASH]
    assert world.users.users[world.uid].failed_login_count == LOCKOUT_THRESHOLD


async def test_step_up_password_recheck_on_a_locked_account_runs_only_the_dummy_verify() -> None:
    world = await _world(failed_login_count=LOCKOUT_THRESHOLD, locked_until=_NOW + timedelta(1))

    verdict = await world.svc.verify_password(world.uid, PASSWORD)

    assert not verdict.ok
    assert verdict.locked_until is None  # not this attempt's lock
    assert world.hasher.verified == [DUMMY_PASSWORD_HASH]


async def test_step_up_with_correct_factors_still_succeeds_and_gives_the_attempt_back() -> None:
    world = await _world(failed_login_count=LOCKOUT_THRESHOLD - 1)

    grant = await world.svc.step_up(world.uid, "s0", "keys", world.code(), PASSWORD)

    assert grant.action_class == "keys"
    assert world.real() == 1
    row = world.users.users[world.uid]
    assert row.failed_login_count == LOCKOUT_THRESHOLD - 1  # unchanged, as before
    assert row.locked_until is None  # its own reservation's lock was given back


async def test_step_up_wrong_password_that_locks_reports_the_lock_once() -> None:
    world = await _world(failed_login_count=LOCKOUT_THRESHOLD - 1)
    before = _lockouts()

    verdict = await world.svc.verify_password(world.uid, "a-guess")

    assert not verdict.ok
    assert verdict.locked_until == _NOW + LOCKOUT_DURATION
    assert _lockouts() == before + 1


async def test_step_up_cancelled_mid_verify_keeps_the_failure_and_counts_its_lock() -> None:
    world = await _world(failed_login_count=LOCKOUT_THRESHOLD - 1)
    before = _lockouts()
    world.hasher.hold_correct = True
    attempt = asyncio.create_task(world.svc.verify_password(world.uid, PASSWORD))
    await world.hasher.correct_entered.wait()

    attempt.cancel()
    with pytest.raises(asyncio.CancelledError):
        await attempt

    assert world.users.users[world.uid].failed_login_count == LOCKOUT_THRESHOLD
    assert world.users.users[world.uid].locked_until == _NOW + LOCKOUT_DURATION
    assert _lockouts() == before + 1
