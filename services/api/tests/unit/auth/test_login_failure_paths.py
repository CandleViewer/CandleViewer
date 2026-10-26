"""#4540 (SR-014): an unknown identifier and a wrong password perform the same steps by
construction, and an unknown identifier never signs in, locks no one and adds no row.

Spies record every repository, hasher, throttle and clock call in one list; the hasher spy
never runs Argon2id. No sleeps, no network.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from argon2 import PasswordHasher, extract_parameters
from prometheus_client import REGISTRY

from candleviewer.auth.errors import InvalidCredentials
from candleviewer.auth.hashing import DEFAULT_ARGON2_PARAMS, DUMMY_PASSWORD_HASH, Hasher
from candleviewer.auth.login_service import (
    ABSENT_USER_ID,
    LOCKOUT_DURATION,
    LOCKOUT_THRESHOLD,
    LoginService,
)
from candleviewer.auth.models import LoginRequest, MfaChallengeResult, UserRecord
from candleviewer.auth.throttle import PerIpLoginThrottle
from tests.unit.auth.auth_fakes import FakeUserRepository, make_user

_NOW = datetime(2026, 1, 1, tzinfo=UTC)
Event = tuple[Any, ...]


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

    def __init__(self, events: list[Event], *, verdict: bool) -> None:
        super().__init__(pepper="test-pepper")
        self.events = events
        self.verdict = verdict
        self.seen: list[str] = []

    async def verify(self, password_hash: str, password: str) -> bool:
        self.events.append(("verify", extract_parameters(password_hash)))
        self.seen.append(password_hash)
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
    stored_hash: str, *, verdict: bool, user: UserRecord | None = None
) -> tuple[LoginService, _SpyRepository, list[Event]]:
    events: list[Event] = []
    repo = _SpyRepository(events)
    repo.add(user or make_user(password_hash=stored_hash))

    def clock() -> datetime:
        events.append(("clock",))
        return _NOW

    service = LoginService(
        repo,
        _SpyHasher(events, verdict=verdict),
        per_ip_throttle=_SpyThrottle(events),
        clock=clock,
    )
    return service, repo, events


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
    assert events[-1][0] == "record_login_failure"


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
