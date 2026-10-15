"""SR-125 `auth_lockouts_total` (#2117): the counter moves when, and only when, the login
lockout is applied (SR-016: five consecutive failures lock the account for 15 minutes).

The decision is `UserRepository.record_login_failure` (atomic increment-and-lock); these tests
drive the real `LoginService` over the in-memory repository and read the process-default
registry, where the module-level counter lives.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from prometheus_client import REGISTRY

from candleviewer.auth.errors import AccountLocked, InvalidCredentials
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.login_service import LOCKOUT_DURATION, LOCKOUT_THRESHOLD, LoginService
from candleviewer.auth.models import LoginRequest
from candleviewer.auth.throttle import PerIpLoginThrottle
from tests.unit.auth.auth_fakes import FakeUserRepository, make_user

PASSWORD = "correct-horse-battery-staple"
_T0 = datetime(2026, 1, 1, tzinfo=UTC)


class _Clock:
    def __init__(self) -> None:
        self.now = _T0

    def __call__(self) -> datetime:
        return self.now


def _lockouts() -> float:
    return float(REGISTRY.get_sample_value("auth_lockouts_total") or 0.0)


async def _service() -> tuple[LoginService, _Clock]:
    clock = _Clock()
    repo, hasher = FakeUserRepository(), Hasher(pepper="test-pepper")
    repo.add(make_user(password_hash=await hasher.hash(PASSWORD)))
    service = LoginService(
        repo, hasher, per_ip_throttle=PerIpLoginThrottle(max_attempts=10_000), clock=clock
    )
    return service, clock


async def _wrong_password(service: LoginService) -> None:
    with pytest.raises(InvalidCredentials):
        await service.login(
            LoginRequest(identifier="basiltt", password="wrong-password"), source_ip="10.0.0.1"
        )


async def test_lockout_counter_does_not_move_below_the_threshold() -> None:
    service, _ = await _service()
    before = _lockouts()
    for _ in range(LOCKOUT_THRESHOLD - 1):
        await _wrong_password(service)
    assert _lockouts() == before


async def test_lockout_counter_increments_once_at_the_failure_that_locks() -> None:
    service, _ = await _service()
    before = _lockouts()
    for _ in range(LOCKOUT_THRESHOLD):
        await _wrong_password(service)
    assert _lockouts() == before + 1


async def test_lockout_counter_ignores_attempts_refused_while_locked() -> None:
    service, _ = await _service()
    for _ in range(LOCKOUT_THRESHOLD):
        await _wrong_password(service)
    locked = _lockouts()
    for password in ("wrong-password", PASSWORD, "wrong-password"):  # even the right one
        with pytest.raises(AccountLocked):
            await service.login(
                LoginRequest(identifier="basiltt", password=password), source_ip="10.0.0.1"
            )
    assert _lockouts() == locked


async def test_lockout_counter_counts_a_relock_after_the_lock_expired() -> None:
    service, clock = await _service()
    before = _lockouts()
    for _ in range(LOCKOUT_THRESHOLD):
        await _wrong_password(service)
    clock.now += LOCKOUT_DURATION + timedelta(seconds=1)
    # failed_login_count is only reset by a successful login, so one more wrong password locks again
    await _wrong_password(service)
    assert _lockouts() == before + 2


async def test_lockout_counter_ignores_a_successful_login() -> None:
    service, _ = await _service()
    before = _lockouts()
    for _ in range(LOCKOUT_THRESHOLD - 1):
        await _wrong_password(service)
    result = await service.login(
        LoginRequest(identifier="basiltt", password=PASSWORD), source_ip="10.0.0.1"
    )
    assert result.methods
    assert _lockouts() == before
