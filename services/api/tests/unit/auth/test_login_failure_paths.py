"""#4540 (SR-014): an unknown identifier and a wrong password perform the same steps by
construction, and an unknown identifier never signs in, locks no one and adds no row.

#4648: every failed sign-in returns no sooner than the failure floor after the attempt
started; the failure write comes first, a slower failure and a success are never held.

Spies record every repository, hasher, throttle, clock and wait call in one list; the hasher
spy never runs Argon2id, and time is a fake monotonic clock (C-13.7). No sleeps, no network.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from argon2 import PasswordHasher, extract_parameters
from prometheus_client import REGISTRY

from candleviewer.auth.errors import AccountDisabled, AccountLocked, InvalidCredentials
from candleviewer.auth.hashing import DEFAULT_ARGON2_PARAMS, DUMMY_PASSWORD_HASH, Hasher
from candleviewer.auth.login_service import (
    ABSENT_USER_ID,
    LOCKOUT_DURATION,
    LOCKOUT_THRESHOLD,
    LOGIN_FAILURE_FLOOR,
    LoginService,
)
from candleviewer.auth.models import LoginRequest, MfaChallengeResult, UserRecord, UserStatus
from candleviewer.auth.throttle import PerIpLoginThrottle
from tests.unit.auth.auth_fakes import FakeUserRepository, make_user

_NOW = datetime(2026, 1, 1, tzinfo=UTC)
_FLOOR_S = LOGIN_FAILURE_FLOOR.total_seconds()
Event = tuple[Any, ...]


class _FakeTime:
    """A monotonic clock that only moves when the hasher spy works or the service waits."""

    def __init__(self, events: list[Event], *, work_s: float = 0.0) -> None:
        self.events = events
        self.work_s = work_s
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, delay: float) -> None:
        self.events.append(("sleep", delay))
        self.now += delay


@pytest.fixture(scope="module")
def real_hash() -> str:
    params = DEFAULT_ARGON2_PARAMS
    return PasswordHasher(
        time_cost=params["t"], memory_cost=params["m"], parallelism=params["p"]
    ).hash("stored-password")


class _SpyRepository(FakeUserRepository):
    def __init__(self, events: list[Event]) -> None:
        super().__init__()
        self.events = events

    async def find_by_identifier(self, identifier: str) -> UserRecord | None:
        self.events.append(("find_by_identifier",))
        return await super().find_by_identifier(identifier)

    async def record_login_success(self, user_id: str) -> None:
        self.events.append(("record_login_success",))
        await super().record_login_success(user_id)

    async def record_login_failure(
        self, user_id: str, *, lockout_threshold: int, lock_duration: timedelta, now: datetime
    ) -> datetime | None:
        self.events.append(("record_login_failure", lockout_threshold, lock_duration, now))
        return await super().record_login_failure(
            user_id, lockout_threshold=lockout_threshold, lock_duration=lock_duration, now=now
        )


class _SpyHasher(Hasher):
    """Records each verify with the Argon2id parameters of its target; never hashes."""

    def __init__(
        self, events: list[Event], *, verdict: bool, time: _FakeTime | None = None
    ) -> None:
        super().__init__(pepper="test-pepper")
        self.events = events
        self.verdict = verdict
        self.time = time
        self.seen: list[str] = []

    async def verify(self, password_hash: str, password: str) -> bool:
        self.events.append(("verify", extract_parameters(password_hash)))
        self.seen.append(password_hash)
        if self.time is not None:
            self.time.now += self.time.work_s  # the verify's work, on the fake clock
        return self.verdict


class _SpyThrottle(PerIpLoginThrottle):
    def __init__(self, events: list[Event]) -> None:
        super().__init__(max_attempts=10_000)
        self.events = events

    def is_blocked(self, source_ip: str) -> bool:
        self.events.append(("is_blocked",))
        return super().is_blocked(source_ip)

    def record_failure(self, source_ip: str) -> None:
        self.events.append(("record_failure",))
        super().record_failure(source_ip)


def _world(
    stored_hash: str,
    *,
    verdict: bool,
    user: UserRecord | None = None,
    work_s: float = 0.0,
    throttle: PerIpLoginThrottle | None = None,
) -> tuple[LoginService, _SpyRepository, list[Event]]:
    service, repo, events, _ = _timed_world(
        stored_hash, verdict=verdict, user=user, work_s=work_s, throttle=throttle
    )
    return service, repo, events


def _timed_world(
    stored_hash: str,
    *,
    verdict: bool,
    user: UserRecord | None = None,
    work_s: float = 0.0,
    throttle: PerIpLoginThrottle | None = None,
) -> tuple[LoginService, _SpyRepository, list[Event], _FakeTime]:
    events: list[Event] = []
    repo = _SpyRepository(events)
    repo.add(user or make_user(password_hash=stored_hash))
    time = _FakeTime(events, work_s=work_s)

    def clock() -> datetime:
        events.append(("clock",))
        return _NOW

    service = LoginService(
        repo,
        _SpyHasher(events, verdict=verdict, time=time),
        per_ip_throttle=throttle or _SpyThrottle(events),
        clock=clock,
        monotonic=time.monotonic,
        sleep=time.sleep,
    )
    return service, repo, events, time


async def _failed_login(service: LoginService, identifier: str) -> None:
    with pytest.raises(InvalidCredentials):
        await service.login(
            LoginRequest(identifier=identifier, password="a-guess"), source_ip="10.0.0.1"
        )


def _lockouts() -> float:
    return float(REGISTRY.get_sample_value("auth_lockouts_total") or 0.0)


async def test_login_unknown_and_wrong_password_make_the_same_calls(real_hash: str) -> None:
    unknown_service, _, unknown = _world(real_hash, verdict=False)
    wrong_service, _, wrong = _world(real_hash, verdict=False)

    await _failed_login(unknown_service, "ghost")
    await _failed_login(wrong_service, "basiltt")

    assert unknown == wrong
    assert [e[0] for e in unknown] == [
        "is_blocked",
        "find_by_identifier",
        "clock",
        "verify",
        "record_failure",
        "clock",
        "record_login_failure",
        "sleep",
    ]


def test_login_placeholder_hash_has_a_stored_hash_shape(real_hash: str) -> None:
    assert extract_parameters(DUMMY_PASSWORD_HASH) == extract_parameters(real_hash)
    assert len(DUMMY_PASSWORD_HASH) == len(real_hash)


async def test_login_unknown_identifier_adds_no_row_and_locks_no_one(real_hash: str) -> None:
    near_lock = make_user(password_hash=real_hash, failed_login_count=LOCKOUT_THRESHOLD - 1)
    service, repo, _ = _world(real_hash, verdict=False, user=near_lock)
    rows_before = dict(repo.users)
    lockouts_before = _lockouts()

    for _ in range(LOCKOUT_THRESHOLD + 1):
        await _failed_login(service, "ghost")

    assert repo.users == rows_before
    assert str(ABSENT_USER_ID) not in repo.users
    assert _lockouts() == lockouts_before


async def test_login_unknown_identifier_fails_even_when_verify_matches(real_hash: str) -> None:
    service, _, events = _world(real_hash, verdict=True)

    await _failed_login(service, "ghost")

    assert ("record_login_success",) not in events
    assert [e[0] for e in events[-2:]] == ["record_login_failure", "sleep"]


async def test_login_record_carrying_the_placeholder_id_never_signs_in(real_hash: str) -> None:
    impostor = make_user(password_hash=real_hash).model_copy(update={"id": ABSENT_USER_ID})
    service, _, events = _world(real_hash, verdict=True, user=impostor)

    await _failed_login(service, "basiltt")

    assert ("record_login_success",) not in events


async def test_login_record_carrying_the_placeholder_id_is_verified_as_the_placeholder(
    real_hash: str,
) -> None:
    impostor = make_user(password_hash=real_hash).model_copy(update={"id": ABSENT_USER_ID})
    service, _, _ = _world(real_hash, verdict=True, user=impostor)

    await _failed_login(service, "basiltt")

    hasher = service._hasher
    assert isinstance(hasher, _SpyHasher) and hasher.seen == [DUMMY_PASSWORD_HASH]


async def test_login_success_path_is_unchanged(real_hash: str) -> None:
    service, _, events = _world(real_hash, verdict=True)

    result = await service.login(
        LoginRequest(identifier="basiltt", password="stored-password"), source_ip="10.0.0.1"
    )

    assert isinstance(result, MfaChallengeResult)
    assert [e[0] for e in events] == [
        "is_blocked",
        "find_by_identifier",
        "clock",
        "verify",
        "record_login_success",
    ]


@pytest.fixture
def model_copies(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[uuid.UUID]]:
    copied: list[uuid.UUID] = []
    real = UserRecord.model_copy

    def counting(self: UserRecord, *args: Any, **kwargs: Any) -> UserRecord:
        copied.append(self.id)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(UserRecord, "model_copy", counting)
    yield copied


async def test_fake_failure_for_an_absent_id_does_the_same_work_and_keeps_no_row(
    model_copies: list[uuid.UUID],
) -> None:
    repo = FakeUserRepository()
    user = make_user(password_hash="unused")
    repo.add(user)
    kw: dict[str, Any] = {
        "lockout_threshold": LOCKOUT_THRESHOLD,
        "lock_duration": LOCKOUT_DURATION,
        "now": _NOW,
    }

    await repo.record_login_failure(str(user.id), **kw)
    present = len(model_copies)
    absent = await repo.record_login_failure(str(ABSENT_USER_ID), **kw)

    assert present == 1 and len(model_copies) == 2  # the same record work for both ids
    assert absent is None
    assert list(repo.users) == [str(user.id)]


# --- #4648: the failed sign-in floor -------------------------------------------------------


@pytest.mark.parametrize("identifier", ["ghost", "basiltt"])
async def test_login_fast_failure_returns_exactly_at_the_floor(
    real_hash: str, identifier: str
) -> None:
    service, _, events, time = _timed_world(real_hash, verdict=False, work_s=0.01)

    await _failed_login(service, identifier)

    assert time.now == pytest.approx(_FLOOR_S)
    assert [e for e in events if e[0] == "sleep"] == [("sleep", pytest.approx(_FLOOR_S - 0.01))]


async def test_login_both_failure_arms_wait_out_the_same_deadline(real_hash: str) -> None:
    unknown_service, _, _, unknown_time = _timed_world(real_hash, verdict=False, work_s=0.02)
    wrong_service, _, _, wrong_time = _timed_world(real_hash, verdict=False, work_s=0.02)

    await _failed_login(unknown_service, "ghost")
    await _failed_login(wrong_service, "basiltt")

    assert unknown_time.now == wrong_time.now == pytest.approx(_FLOOR_S)


@pytest.mark.parametrize("identifier", ["ghost", "basiltt"])
async def test_login_slow_failure_is_not_held_further(real_hash: str, identifier: str) -> None:
    slow = _FLOOR_S + 0.5
    service, _, events, time = _timed_world(real_hash, verdict=False, work_s=slow)

    await _failed_login(service, identifier)

    assert time.now == pytest.approx(slow)
    assert not [e for e in events if e[0] == "sleep"]


async def test_login_success_is_never_held(real_hash: str) -> None:
    service, _, events, time = _timed_world(real_hash, verdict=True, work_s=0.01)

    result = await service.login(
        LoginRequest(identifier="basiltt", password="stored-password"), source_ip="10.0.0.1"
    )

    assert isinstance(result, MfaChallengeResult)
    assert time.now == pytest.approx(0.01)
    assert not [e for e in events if e[0] == "sleep"]


@pytest.mark.parametrize("identifier", ["ghost", "basiltt"])
async def test_login_failure_write_happens_before_the_wait(real_hash: str, identifier: str) -> None:
    service, _, events, _ = _timed_world(real_hash, verdict=False, work_s=0.01)

    await _failed_login(service, identifier)

    names = [e[0] for e in events]
    assert names.index("record_failure") < names.index("sleep")
    assert names.index("record_login_failure") < names.index("sleep")
    assert names[-1] == "sleep"


async def test_login_locked_account_refusal_is_held_to_the_floor(real_hash: str) -> None:
    locked = make_user(password_hash=real_hash, locked_until=_NOW + timedelta(minutes=5))
    service, _, _, time = _timed_world(real_hash, verdict=False, user=locked, work_s=0.01)

    with pytest.raises(AccountLocked):
        await service.login(
            LoginRequest(identifier="basiltt", password="a-guess"), source_ip="10.0.0.1"
        )

    assert time.now == pytest.approx(_FLOOR_S)


async def test_login_disabled_account_refusal_is_held_to_the_floor(real_hash: str) -> None:
    disabled = make_user(password_hash=real_hash, status=UserStatus.DISABLED)
    service, _, _, time = _timed_world(real_hash, verdict=True, user=disabled, work_s=0.01)

    with pytest.raises(AccountDisabled):
        await service.login(
            LoginRequest(identifier="basiltt", password="stored-password"), source_ip="10.0.0.1"
        )

    assert time.now == pytest.approx(_FLOOR_S)


async def test_login_throttled_source_refusal_is_held_to_the_floor(real_hash: str) -> None:
    throttle = PerIpLoginThrottle(max_attempts=1)
    throttle.record_failure("10.0.0.1")
    service, _, events, time = _timed_world(real_hash, verdict=False, throttle=throttle)

    await _failed_login(service, "basiltt")

    assert time.now == pytest.approx(_FLOOR_S)
    assert [e[0] for e in events] == ["sleep"]  # no lookup and no verify behind the refusal


async def test_login_wait_is_bounded_by_the_floor_when_the_clock_steps_back(
    real_hash: str,
) -> None:
    service, _, events, time = _timed_world(real_hash, verdict=False)
    readings = iter([100.0, 40.0])  # started, then an earlier reading at the wait
    service._monotonic = lambda: next(readings)

    await _failed_login(service, "basiltt")

    assert [e for e in events if e[0] == "sleep"] == [("sleep", _FLOOR_S)]
    assert time.now == pytest.approx(_FLOOR_S)


async def test_login_cancellation_during_the_wait_propagates(real_hash: str) -> None:
    service, _, events, _ = _timed_world(real_hash, verdict=False)
    waiting = asyncio.Event()

    async def held(delay: float) -> None:
        events.append(("sleep", delay))
        waiting.set()
        await asyncio.Event().wait()  # never set: only a cancellation ends it

    service._sleep = held
    attempt = asyncio.create_task(
        service.login(LoginRequest(identifier="ghost", password="a-guess"), source_ip="10.0.0.1")
    )
    async with asyncio.timeout(5):  # a guard only: a correct service starts the wait at once
        await waiting.wait()
    attempt.cancel()

    with pytest.raises(asyncio.CancelledError):
        await attempt
    assert attempt.cancelled()
    assert ("record_login_failure",) == events[-2][:1]  # the write was already done
