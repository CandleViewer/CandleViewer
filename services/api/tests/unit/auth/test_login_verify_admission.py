"""#4663: sign-in verification runs for at most `verify_concurrency` attempts at a time.

An attempt beyond that is refused at once with `SignInBusy` and a retry-after, before its
identifier is looked up or any password is checked, and is counted. It never waits for a place
and is never held to the failure floor. A place is given back on every way out: success,
failure, an error and a cancellation. The per-IP throttle still answers first.

The hasher is a gate: each verify waits on an `asyncio.Event` the test sets, so attempts are held
in flight without sleeps or real hashing (C-13.7). The one timeout only bounds a wrong result.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from prometheus_client import REGISTRY

from candleviewer.auth.errors import InvalidCredentials, SignInBusy
from candleviewer.auth.hashing import DUMMY_PASSWORD_HASH, Hasher
from candleviewer.auth.login_service import (
    LOGIN_BUSY_RETRY_AFTER_S,
    LOGIN_VERIFY_CONCURRENCY,
    EnrolmentOnlyLogin,
    LoginService,
)
from candleviewer.auth.models import LoginRequest, MfaChallengeResult, UserRecord
from candleviewer.auth.throttle import PerIpLoginThrottle, VerifyAdmission
from candleviewer.settings import AUTH_LOGIN_VERIFY_CONCURRENCY
from tests.unit.auth.auth_fakes import FakeUserRepository, make_user

_NOW = datetime(2026, 1, 1, tzinfo=UTC)
Outcome = MfaChallengeResult | EnrolmentOnlyLogin
_GUESS = "a-guess"  # a test value, never a credential
_BOUND_S = 5.0  # bounds a wrong result (an attempt that waits); a correct run never reaches it


class _GateHasher(Hasher):
    """Each verify waits until `release` is set; `all_in` is set once `expected` are waiting."""

    def __init__(self, *, verdict: bool, expected: int) -> None:
        super().__init__(pepper="test-pepper")
        self.verdict = verdict
        self.expected = expected
        self.calls = 0
        self.release = asyncio.Event()
        self.all_in = asyncio.Event()

    async def verify(self, password_hash: str, password: str) -> bool:
        self.calls += 1
        if self.calls >= self.expected:
            self.all_in.set()
        await self.release.wait()
        return self.verdict


class _CountingRepository(FakeUserRepository):
    def __init__(self, *, lookup_error: Exception | None = None) -> None:
        super().__init__()
        self.lookups = 0
        self.lookup_error = lookup_error

    async def find_by_identifier(self, identifier: str) -> UserRecord | None:
        self.lookups += 1
        if self.lookup_error is not None:
            raise self.lookup_error
        return await super().find_by_identifier(identifier)


class _Sleeps:
    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.waits.append(delay)


def _service(
    *,
    limit: int,
    verdict: bool = True,
    expected: int | None = None,
    repository: _CountingRepository | None = None,
    throttle: PerIpLoginThrottle | None = None,
    sleeps: _Sleeps | None = None,
) -> tuple[LoginService, VerifyAdmission, _GateHasher, _CountingRepository]:
    repo = repository or _CountingRepository()
    repo.add(make_user(password_hash=DUMMY_PASSWORD_HASH))
    admission = VerifyAdmission(limit)
    hasher = _GateHasher(verdict=verdict, expected=limit if expected is None else expected)
    service = LoginService(
        repo,
        hasher,
        per_ip_throttle=throttle or PerIpLoginThrottle(max_attempts=10_000),
        clock=lambda: _NOW,
        failure_floor=timedelta(milliseconds=500),
        monotonic=lambda: 0.0,
        sleep=sleeps or _Sleeps(),
        admission=admission,
    )
    return service, admission, hasher, repo


def _attempt(
    service: LoginService, *, password: str = _GUESS, ip: str = "10.0.0.1"
) -> Coroutine[Any, Any, Outcome]:
    return service.login(LoginRequest(identifier="basiltt", password=password), source_ip=ip)


def _refused() -> float:
    return float(REGISTRY.get_sample_value("auth_login_verify_refused_total") or 0.0)


async def _fill(
    service: LoginService, hasher: _GateHasher, count: int
) -> list[asyncio.Task[Outcome]]:
    tasks = [asyncio.create_task(_attempt(service)) for _ in range(count)]
    async with asyncio.timeout(_BOUND_S):
        await hasher.all_in.wait()
    return tasks


# --- VerifyAdmission ---------------------------------------------------------------------------


def test_verify_admission_admits_up_to_its_limit_then_refuses_without_waiting() -> None:
    admission = VerifyAdmission(2)

    assert [admission.try_enter() for _ in range(3)] == [True, True, False]
    assert admission.in_flight == 2


def test_verify_admission_leave_frees_a_place() -> None:
    admission = VerifyAdmission(1)
    assert admission.try_enter()

    admission.leave()

    assert admission.in_flight == 0 and admission.try_enter()


@pytest.mark.parametrize("limit", [0, -1])
def test_verify_admission_below_one_is_refused(limit: int) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        VerifyAdmission(limit)


def test_verify_admission_leave_without_enter_raises() -> None:
    with pytest.raises(RuntimeError, match="without a matching"):
        VerifyAdmission(1).leave()


# --- LoginService ------------------------------------------------------------------------------


async def test_login_admits_the_limit_and_refuses_the_next_attempt_at_once() -> None:
    service, admission, hasher, repo = _service(limit=3)
    before = _refused()
    held = await _fill(service, hasher, 3)
    lookups = repo.lookups

    async with asyncio.timeout(_BOUND_S):  # a waiting attempt would hit this and fail
        with pytest.raises(SignInBusy) as refused:
            await _attempt(service)

    assert refused.value.retry_after_s == LOGIN_BUSY_RETRY_AFTER_S == 1
    assert _refused() - before == 1
    assert (repo.lookups, hasher.calls, admission.in_flight) == (lookups, 3, 3)
    hasher.release.set()
    results = await asyncio.gather(*held)
    assert all(isinstance(r, MfaChallengeResult) for r in results)
    assert admission.in_flight == 0


async def test_login_refusal_is_not_held_to_the_failure_floor() -> None:
    sleeps = _Sleeps()
    service, _, hasher, _ = _service(limit=1, sleeps=sleeps)
    held = await _fill(service, hasher, 1)

    with pytest.raises(SignInBusy):
        await _attempt(service)

    assert sleeps.waits == []
    hasher.release.set()
    await asyncio.gather(*held)


async def test_login_admits_again_once_a_place_is_free() -> None:
    service, admission, hasher, _ = _service(limit=1)
    held = await _fill(service, hasher, 1)
    with pytest.raises(SignInBusy):
        await _attempt(service)

    hasher.release.set()
    await asyncio.gather(*held)

    assert isinstance(await _attempt(service), MfaChallengeResult)
    assert admission.in_flight == 0


async def test_login_success_under_the_bound_returns_the_challenge_and_frees_the_place() -> None:
    service, admission, hasher, _ = _service(limit=2)
    hasher.release.set()

    result = await _attempt(service)

    assert isinstance(result, MfaChallengeResult) and admission.in_flight == 0


async def test_login_failure_frees_the_place() -> None:
    service, admission, hasher, _ = _service(limit=1, verdict=False)
    hasher.release.set()

    with pytest.raises(InvalidCredentials):
        await _attempt(service, password="wrong")

    assert admission.in_flight == 0


async def test_login_error_inside_verification_frees_the_place() -> None:
    repo = _CountingRepository(lookup_error=RuntimeError("store down"))
    service, admission, _, _ = _service(limit=1, repository=repo)

    with pytest.raises(RuntimeError, match="store down"):
        await _attempt(service)

    assert admission.in_flight == 0


async def test_login_cancelled_during_verification_frees_the_place() -> None:
    service, admission, hasher, _ = _service(limit=1)
    (held,) = await _fill(service, hasher, 1)
    assert admission.in_flight == 1

    held.cancel()
    with pytest.raises(asyncio.CancelledError):
        await held

    assert admission.in_flight == 0


async def test_login_blocked_address_is_refused_by_the_throttle_before_the_bound() -> None:
    throttle = PerIpLoginThrottle(max_attempts=1)
    throttle.record_failure("10.9.9.9")
    throttle.record_failure("10.9.9.9")
    service, admission, hasher, _ = _service(limit=1, throttle=throttle)
    held = await _fill(service, hasher, 1)
    before = _refused()

    with pytest.raises(InvalidCredentials):
        await _attempt(service, ip="10.9.9.9")

    assert _refused() == before and admission.in_flight == 1
    hasher.release.set()
    await asyncio.gather(*held)


def test_login_service_default_bound_is_the_setting_default() -> None:
    service = LoginService(FakeUserRepository(), Hasher(pepper="p"))

    assert LOGIN_VERIFY_CONCURRENCY == AUTH_LOGIN_VERIFY_CONCURRENCY == 4
    assert service._admission.limit == LOGIN_VERIFY_CONCURRENCY


def test_login_service_builds_its_bound_from_verify_concurrency() -> None:
    service = LoginService(FakeUserRepository(), Hasher(pepper="p"), verify_concurrency=7)

    assert service._admission.limit == 7
