"""#2802: a sign-in attempt is counted, and the lock applied, before its password is verified.

The account and the source address each reserve the attempt first; only an attempt holding a
reservation taken while the account was unlocked (and the address under its budget) is verified
against the account's hash. A correct password whose attempt was in flight when another attempt's
reservation locked the account is refused (423), so nothing signs in after the lock.
`_verify_sync` is the seam every Argon2id verification passes through, the dummy one included.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from prometheus_client import REGISTRY

from candleviewer.auth.errors import AccountLocked, InvalidCredentials, SignInBusy
from candleviewer.auth.hashing import DEFAULT_ARGON2_PARAMS, DUMMY_PASSWORD_HASH, Hasher
from candleviewer.auth.login_service import (
    LOCKOUT_DURATION,
    LOCKOUT_THRESHOLD,
    EnrolmentOnlyLogin,
    LoginService,
)
from candleviewer.auth.models import LoginRequest, MfaChallengeResult, MfaMethodKind
from candleviewer.auth.throttle import PerIpLoginThrottle, VerifyAdmission
from candleviewer.settings import AUTH_LOGIN_VERIFY_CONCURRENCY_MAX
from tests.unit.auth.auth_fakes import FakeUserRepository, make_user, no_wait
from tests.unit.auth.mfa_fakes import FakeMfaRepository

PASSWORD = "correct-horse-battery-staple"
_NOW = datetime(2026, 1, 1, tzinfo=UTC)
_IP = "10.0.0.1"


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


async def _world(
    *,
    throttle: PerIpLoginThrottle | None = None,
    mfa_methods: tuple[MfaMethodKind, ...] = (MfaMethodKind.TOTP,),
    failed_login_count: int = 0,
    locked_until: datetime | None = None,
) -> tuple[LoginService, FakeUserRepository, _SpyHasher, str]:
    repo, hasher = FakeUserRepository(), _SpyHasher()
    user = make_user(
        password_hash=await hasher.hash(PASSWORD),
        mfa_methods=mfa_methods,
        failed_login_count=failed_login_count,
        locked_until=locked_until,
    )
    repo.add(user)
    service = LoginService(
        repo,
        hasher,
        per_ip_throttle=throttle or PerIpLoginThrottle(max_attempts=10_000),
        clock=lambda: _NOW,
        sleep=no_wait,
        # #4663: every attempt of a burst is admitted, so the reservation is what is tested here.
        verify_concurrency=AUTH_LOGIN_VERIFY_CONCURRENCY_MAX,
    )
    return service, repo, hasher, str(user.id)


async def _attempt(service: LoginService, password: str, identifier: str = "basiltt") -> object:
    try:
        return await service.login(
            LoginRequest(identifier=identifier, password=password), source_ip=_IP
        )
    except (InvalidCredentials, AccountLocked) as exc:
        return exc


def _real(hasher: _SpyHasher, repo: FakeUserRepository, uid: str) -> int:
    """Verifications against the account's own hash: the guesses the attacker got."""
    return sum(h == repo.users[uid].password_hash for h in hasher.verified)


async def test_login_burst_verifies_at_most_threshold_and_refuses_the_correct_password() -> None:
    service, repo, hasher, uid = await _world()

    results = await asyncio.gather(
        *(_attempt(service, "wrong-password") for _ in range(LOCKOUT_THRESHOLD * 2)),
        _attempt(service, PASSWORD),
    )

    assert _real(hasher, repo, uid) == LOCKOUT_THRESHOLD
    assert isinstance(results[-1], AccountLocked)  # the lock had landed: refused unverified
    assert sum(isinstance(r, InvalidCredentials) for r in results) == LOCKOUT_THRESHOLD
    assert repo.users[uid].failed_login_count == LOCKOUT_THRESHOLD
    assert repo.users[uid].locked_until == _NOW + LOCKOUT_DURATION


async def test_login_correct_password_in_flight_when_the_lock_lands_is_refused() -> None:
    service, repo, hasher, uid = await _world()
    hasher.hold_correct = True
    correct = asyncio.create_task(_attempt(service, PASSWORD))
    await hasher.correct_entered.wait()  # its reservation is taken; its verification is held

    wrong = await asyncio.gather(
        *(_attempt(service, "wrong-password") for _ in range(LOCKOUT_THRESHOLD))
    )
    hasher.release_correct.set()
    outcome = await correct

    assert isinstance(outcome, AccountLocked)
    assert _real(hasher, repo, uid) == LOCKOUT_THRESHOLD  # 1 correct + 4 wrong; the 5th refused
    assert sum(isinstance(r, AccountLocked) for r in wrong) == 1
    assert repo.users[uid].failed_login_count == LOCKOUT_THRESHOLD
    assert repo.users[uid].locked_until == _NOW + LOCKOUT_DURATION


async def test_login_per_ip_bucket_bounds_verifications_in_a_burst() -> None:
    budget = 3
    service, _, hasher, _ = await _world(throttle=PerIpLoginThrottle(max_attempts=budget))

    results = await asyncio.gather(*(_attempt(service, "wrong-password") for _ in range(10)))

    assert len(hasher.verified) == budget  # every refused attempt verified nothing
    assert all(isinstance(r, InvalidCredentials) for r in results)


async def test_login_sequential_correct_login_succeeds_and_clears_the_counter() -> None:
    # One-attempt address budget: a success that kept its address reservation would block the next.
    service, repo, _, uid = await _world(
        throttle=PerIpLoginThrottle(max_attempts=1),
        mfa_methods=(),
        failed_login_count=LOCKOUT_THRESHOLD - 1,
    )

    for _ in range(2):
        assert isinstance(await _attempt(service, PASSWORD), EnrolmentOnlyLogin)
        assert repo.users[uid].failed_login_count == 0
        assert repo.users[uid].locked_until is None


async def test_login_correct_password_before_the_second_factor_gives_its_reservation_back() -> None:
    # Its own reservation reached the threshold; the password was right, so the count is as before.
    service, repo, _, uid = await _world(failed_login_count=LOCKOUT_THRESHOLD - 1)

    assert isinstance(await _attempt(service, PASSWORD), MfaChallengeResult)
    assert repo.users[uid].failed_login_count == LOCKOUT_THRESHOLD - 1
    assert repo.users[uid].locked_until is None


async def test_login_correct_password_after_the_lock_expired_signs_in() -> None:
    service, repo, hasher, uid = await _world(
        mfa_methods=(),
        failed_login_count=LOCKOUT_THRESHOLD,
        locked_until=_NOW - timedelta(seconds=1),
    )

    assert isinstance(await _attempt(service, PASSWORD), EnrolmentOnlyLogin)
    assert _real(hasher, repo, uid) == 1
    assert repo.users[uid].failed_login_count == 0


async def test_login_locked_account_runs_one_dummy_verification_only() -> None:
    service, repo, hasher, uid = await _world(
        failed_login_count=LOCKOUT_THRESHOLD, locked_until=_NOW + timedelta(minutes=1)
    )

    assert isinstance(await _attempt(service, PASSWORD), AccountLocked)
    assert hasher.verified == [DUMMY_PASSWORD_HASH]  # same Argon2id work, never the real hash
    assert repo.users[uid].failed_login_count == LOCKOUT_THRESHOLD


async def test_login_unknown_identifier_is_unchanged() -> None:
    service, repo, hasher, _ = await _world()
    rows = dict(repo.users)

    assert isinstance(await _attempt(service, PASSWORD, identifier="ghost"), InvalidCredentials)
    assert hasher.verified == [DUMMY_PASSWORD_HASH]
    assert repo.users == rows


def test_throttle_reservation_is_refused_at_the_budget_and_released_on_success() -> None:
    throttle = PerIpLoginThrottle(max_attempts=2)
    first, second = throttle.try_reserve(_IP), throttle.try_reserve(_IP)

    assert first is not None and second is not None
    assert throttle.try_reserve(_IP) is None
    throttle.release(_IP, second)
    assert not throttle.is_blocked(_IP)
    throttle.release(_IP, first)
    throttle.release(_IP, first)  # already gone: nothing to give back
    throttle.release("10.9.9.9", first)  # never reserved: nothing to give back
    assert throttle.retry_after_s(_IP) == 0


def _lockouts() -> float:
    return float(REGISTRY.get_sample_value("auth_lockouts_total") or 0.0)


class _SettleRaises(FakeUserRepository):
    async def settle_login_attempt(
        self, user_id: str, *, slot: int, complete: bool, now: datetime
    ) -> bool:
        raise RuntimeError("settle failed")


class _SettleRefuses(FakeUserRepository):
    async def settle_login_attempt(
        self, user_id: str, *, slot: int, complete: bool, now: datetime
    ) -> bool:
        return False  # another attempt's lock landed while this one was in flight


async def test_login_cancelled_after_a_lock_applying_reserve_counts_the_lock_once() -> None:
    service, repo, hasher, uid = await _world(failed_login_count=LOCKOUT_THRESHOLD - 1)
    hasher.hold_correct = True
    before = _lockouts()
    task = asyncio.create_task(
        service.login(LoginRequest(identifier="basiltt", password=PASSWORD), source_ip=_IP)
    )
    await hasher.correct_entered.wait()  # its reservation applied the lock; the verify is held

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert _lockouts() == before + 1
    assert repo.users[uid].locked_until == _NOW + LOCKOUT_DURATION  # the lock stands


async def test_login_settle_error_after_a_lock_applying_reserve_counts_the_lock_once() -> None:
    repo, hasher = _SettleRaises(), Hasher(pepper="test-pepper")
    user = make_user(
        password_hash=await hasher.hash(PASSWORD), failed_login_count=LOCKOUT_THRESHOLD - 1
    )
    repo.add(user)
    service = LoginService(
        repo,
        hasher,
        per_ip_throttle=PerIpLoginThrottle(max_attempts=10_000),
        clock=lambda: _NOW,
        sleep=no_wait,
    )
    before = _lockouts()

    with pytest.raises(RuntimeError, match="settle failed"):
        await service.login(LoginRequest(identifier="basiltt", password=PASSWORD), source_ip=_IP)

    assert _lockouts() == before + 1
    assert repo.users[str(user.id)].locked_until == _NOW + LOCKOUT_DURATION


async def test_login_settle_refused_is_locked_with_no_challenge_and_no_rehash() -> None:
    repo, mfa_repo = _SettleRefuses(), FakeMfaRepository()
    hasher = _SpyHasher()
    # Hashed with weaker params than the defaults, so a settled sign-in would rehash it.
    user = make_user(
        password_hash=await hasher.hash(PASSWORD, {"m": 8192, "t": 1, "p": 1}),
        mfa_methods=(MfaMethodKind.TOTP,),
    )
    repo.add(user)
    assert hasher.needs_rehash(user.password_hash, DEFAULT_ARGON2_PARAMS)
    service = LoginService(
        repo,
        hasher,
        per_ip_throttle=PerIpLoginThrottle(max_attempts=10_000),
        clock=lambda: _NOW,
        sleep=no_wait,
        mfa_repository=mfa_repo,
    )

    assert isinstance(await _attempt(service, PASSWORD), AccountLocked)
    assert mfa_repo.challenges == {}
    assert repo.rehash_calls == []


async def test_login_sign_in_busy_releases_the_address_reservation() -> None:
    throttle = PerIpLoginThrottle(max_attempts=1)
    admission = VerifyAdmission(1)
    assert admission.try_enter()  # every verification place is taken
    repo, hasher = FakeUserRepository(), _SpyHasher()
    repo.add(make_user(password_hash=await hasher.hash(PASSWORD)))
    service = LoginService(
        repo,
        hasher,
        per_ip_throttle=throttle,
        clock=lambda: _NOW,
        sleep=no_wait,
        admission=admission,
    )

    with pytest.raises(SignInBusy):
        await service.login(LoginRequest(identifier="basiltt", password=PASSWORD), source_ip=_IP)

    assert hasher.verified == []
    assert not throttle.is_blocked(_IP)  # the one-attempt budget is whole again
