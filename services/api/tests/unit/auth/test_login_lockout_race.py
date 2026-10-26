"""SR-015/SR-016: login lockout ordering under concurrent failures (unit level).

Scope: the in-memory fake repository is atomic by construction (no `await` between
read and write), so these tests do NOT prove the real repository is race-safe; they
check `LoginService` ordering/lock semantics only (it must delegate the increment
to the repository and never compute counts from a stale user snapshot). The real
lost-update race is covered against Postgres in
`tests/integration/auth/test_login_lockout_race_pg.py` (CI only; no docker locally).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from candleviewer.auth.errors import AccountLocked, InvalidCredentials
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.login_service import LOCKOUT_THRESHOLD, LoginService
from candleviewer.auth.models import LoginRequest
from candleviewer.auth.throttle import PerIpLoginThrottle
from tests.unit.auth.auth_fakes import FakeUserRepository, make_user

PASSWORD = "correct-horse-battery-staple"
_NOW = datetime(2026, 1, 1, tzinfo=UTC)


class _RecordingRepository(FakeUserRepository):
    """Fake that records every `record_login_failure` outcome."""

    def __init__(self) -> None:
        super().__init__()
        self.failure_counts: list[int] = []
        self.lock_transitions = 0

    async def record_login_failure(
        self, user_id: str, *, lockout_threshold: int, lock_duration: timedelta, now: datetime
    ) -> datetime | None:
        was_locked = self.users[user_id].locked_until is not None
        result = await super().record_login_failure(
            user_id, lockout_threshold=lockout_threshold, lock_duration=lock_duration, now=now
        )
        self.failure_counts.append(self.users[user_id].failed_login_count)
        if result is not None and not was_locked:
            self.lock_transitions += 1
        return result


async def _setup() -> tuple[_RecordingRepository, LoginService, str]:
    repo = _RecordingRepository()
    hasher = Hasher(pepper="test-pepper")
    user = make_user(password_hash=await hasher.hash(PASSWORD))
    repo.add(user)
    service = LoginService(
        repo,
        hasher,
        per_ip_throttle=PerIpLoginThrottle(max_attempts=10_000),
        clock=lambda: _NOW,
        failure_floor=timedelta(0),
    )
    return repo, service, str(user.id)


async def _fail(service: LoginService) -> BaseException | None:
    try:
        await service.login(
            LoginRequest(identifier="basiltt", password="wrong-password"), source_ip="10.0.0.1"
        )
    except (InvalidCredentials, AccountLocked) as exc:
        return exc
    return None


@pytest.mark.asyncio
async def test_concurrent_failures_lock_exactly_at_threshold_with_no_lost_update() -> None:
    repo, service, uid = await _setup()
    n = LOCKOUT_THRESHOLD * 3

    results = await asyncio.gather(*(_fail(service) for _ in range(n)))

    assert all(isinstance(r, InvalidCredentials | AccountLocked) for r in results)
    # No lost increments: every recorded failure got a distinct, consecutive count.
    assert repo.failure_counts == list(range(1, len(repo.failure_counts) + 1))
    assert repo.users[uid].failed_login_count == len(repo.failure_counts)
    # The lock is applied exactly once, on the transition at LOCKOUT_THRESHOLD.
    assert repo.failure_counts.index(LOCKOUT_THRESHOLD) == LOCKOUT_THRESHOLD - 1
    assert repo.lock_transitions == 1
    assert repo.users[uid].locked_until is not None


@pytest.mark.asyncio
async def test_threshold_minus_one_concurrent_failures_do_not_lock() -> None:
    repo, service, uid = await _setup()

    await asyncio.gather(*(_fail(service) for _ in range(LOCKOUT_THRESHOLD - 1)))

    assert repo.users[uid].failed_login_count == LOCKOUT_THRESHOLD - 1
    assert repo.users[uid].locked_until is None
    assert repo.lock_transitions == 0


@pytest.mark.asyncio
async def test_correct_password_refused_after_concurrent_lockout() -> None:
    repo, service, uid = await _setup()
    await asyncio.gather(*(_fail(service) for _ in range(LOCKOUT_THRESHOLD * 2)))
    assert repo.users[uid].locked_until is not None

    with pytest.raises(AccountLocked) as exc:
        await service.login(
            LoginRequest(identifier="basiltt", password=PASSWORD), source_ip="10.0.0.1"
        )
    assert exc.value.retry_after_s > 0
