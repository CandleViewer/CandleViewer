"""Unit tests for `candleviewer.auth.login_service.LoginService` (E09-S01),
covering every Gherkin scenario in the ticket."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest

from candleviewer.auth.errors import AccountDisabled, AccountLocked, InvalidCredentials
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.login_service import LOCKOUT_THRESHOLD, EnrolmentOnlyLogin, LoginService
from candleviewer.auth.models import LoginRequest, MfaMethodKind, UserStatus
from candleviewer.auth.throttle import PerIpLoginThrottle
from tests.unit.auth.auth_fakes import FakeUserRepository, make_user
from tests.unit.auth.mfa_fakes import FakeMfaRepository

PASSWORD = "correct-horse-battery-staple"


def _clock_factory(start: datetime | None = None) -> tuple[list[datetime], object]:
    box = [start or datetime(2026, 1, 1, tzinfo=UTC)]

    def clock() -> datetime:
        return box[0]

    return box, clock


def _service(repo: FakeUserRepository, *, clock: object = None) -> LoginService:
    hasher = Hasher(pepper="test-pepper")
    kwargs: dict[str, object] = {"per_ip_throttle": PerIpLoginThrottle(max_attempts=1000)}
    if clock is not None:
        kwargs["clock"] = clock
    return LoginService(repo, hasher, **kwargs)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_successful_login_advances_to_mfa_challenge() -> None:
    repo = FakeUserRepository()
    hasher = Hasher(pepper="test-pepper")
    repo.add(
        make_user(password_hash=await hasher.hash(PASSWORD), mfa_methods=(MfaMethodKind.TOTP,))
    )
    service = LoginService(repo, hasher, per_ip_throttle=PerIpLoginThrottle(max_attempts=1000))

    result = await service.login(
        LoginRequest(identifier="basiltt", password=PASSWORD), source_ip="10.0.0.1"
    )

    assert result.methods == (MfaMethodKind.TOTP,)
    assert result.mfa_token
    assert result.expires_in == 300


@pytest.mark.asyncio
async def test_wrong_password_raises_invalid_credentials_with_uniform_message() -> None:
    repo = FakeUserRepository()
    hasher = Hasher(pepper="test-pepper")
    repo.add(make_user(password_hash=await hasher.hash(PASSWORD)))
    service = LoginService(repo, hasher, per_ip_throttle=PerIpLoginThrottle(max_attempts=1000))

    with pytest.raises(InvalidCredentials) as exc:
        await service.login(
            LoginRequest(identifier="basiltt", password="wrong-password"), source_ip="10.0.0.1"
        )
    assert str(exc.value) == "Username or password is incorrect"


@pytest.mark.asyncio
async def test_disabled_account_with_correct_password_raises_account_disabled() -> None:
    repo = FakeUserRepository()
    hasher = Hasher(pepper="test-pepper")
    repo.add(make_user(password_hash=await hasher.hash(PASSWORD), status=UserStatus.DISABLED))
    service = LoginService(repo, hasher, per_ip_throttle=PerIpLoginThrottle(max_attempts=1000))

    with pytest.raises(AccountDisabled):
        await service.login(
            LoginRequest(identifier="basiltt", password=PASSWORD), source_ip="10.0.0.1"
        )


@pytest.mark.asyncio
async def test_lockout_after_five_failures_refuses_even_correct_password() -> None:
    repo = FakeUserRepository()
    hasher = Hasher(pepper="test-pepper")
    box, clock = _clock_factory()
    user = make_user(password_hash=await hasher.hash(PASSWORD))
    repo.add(user)
    service = _service(repo, clock=clock)

    for _ in range(LOCKOUT_THRESHOLD):
        with pytest.raises(InvalidCredentials):
            await service.login(
                LoginRequest(identifier="basiltt", password="wrong-password"),
                source_ip="10.0.0.1",
            )

    with pytest.raises(AccountLocked) as exc:
        await service.login(
            LoginRequest(identifier="basiltt", password=PASSWORD), source_ip="10.0.0.1"
        )
    assert exc.value.retry_after_s > 0


@pytest.mark.asyncio
async def test_lockout_persists_and_expires_after_window() -> None:
    repo = FakeUserRepository()
    hasher = Hasher(pepper="test-pepper")
    box, clock = _clock_factory()
    repo.add(make_user(password_hash=await hasher.hash(PASSWORD)))
    service = _service(repo, clock=clock)

    for _ in range(LOCKOUT_THRESHOLD):
        with pytest.raises(InvalidCredentials):
            await service.login(
                LoginRequest(identifier="basiltt", password="wrong-password"),
                source_ip="10.0.0.1",
            )

    box[0] += timedelta(minutes=16)
    result = await service.login(
        LoginRequest(identifier="basiltt", password=PASSWORD), source_ip="10.0.0.1"
    )
    assert result.mfa_token


@pytest.mark.asyncio
async def test_unknown_user_indistinguishable_from_wrong_password() -> None:
    repo = FakeUserRepository()
    hasher = Hasher(pepper="test-pepper")
    repo.add(make_user(password_hash=await hasher.hash(PASSWORD)))
    service = LoginService(repo, hasher, per_ip_throttle=PerIpLoginThrottle(max_attempts=1000))

    with pytest.raises(InvalidCredentials) as unknown_exc:
        await service.login(
            LoginRequest(identifier="no-such-user", password="anything"), source_ip="10.0.0.1"
        )
    with pytest.raises(InvalidCredentials) as wrong_exc:
        await service.login(
            LoginRequest(identifier="basiltt", password="wrong-password"), source_ip="10.0.0.2"
        )
    assert str(unknown_exc.value) == str(wrong_exc.value)


class _RecordingHasher(Hasher):
    def __init__(self) -> None:
        super().__init__(pepper="test-pepper")
        self.verify_calls = 0

    async def verify(self, password_hash: str, password: str) -> bool:
        self.verify_calls += 1
        return await super().verify(password_hash, password)


@pytest.mark.asyncio
async def test_unknown_user_path_runs_exactly_one_hash_verification() -> None:
    """Structural timing-equalisation check (C-13.7): the unknown-user path
    does the same single Argon2 verify as a wrong password."""
    repo = FakeUserRepository()
    hasher = _RecordingHasher()
    repo.add(make_user(password_hash=await hasher.hash(PASSWORD)))
    service = LoginService(repo, hasher, per_ip_throttle=PerIpLoginThrottle(max_attempts=1000))

    with pytest.raises(InvalidCredentials):
        await service.login(
            LoginRequest(identifier="no-such-user", password="x"), source_ip="10.1.0.1"
        )
    assert hasher.verify_calls == 1

    hasher.verify_calls = 0
    with pytest.raises(InvalidCredentials):
        await service.login(
            LoginRequest(identifier="basiltt", password="wrong"), source_ip="10.2.0.1"
        )
    assert hasher.verify_calls == 1


@pytest.mark.perf
@pytest.mark.asyncio
async def test_unknown_user_timing_matches_wrong_password_within_tolerance() -> None:
    repo = FakeUserRepository()
    hasher = Hasher(pepper="test-pepper")
    repo.add(make_user(password_hash=await hasher.hash(PASSWORD)))
    service = LoginService(repo, hasher, per_ip_throttle=PerIpLoginThrottle(max_attempts=1000))

    samples = 5
    unknown_durations = []
    wrong_durations = []
    for i in range(samples):
        start = time.perf_counter()
        with pytest.raises(InvalidCredentials):
            await service.login(
                LoginRequest(identifier="no-such-user", password="x"), source_ip=f"10.1.{i}.1"
            )
        unknown_durations.append(time.perf_counter() - start)

        start = time.perf_counter()
        with pytest.raises(InvalidCredentials):
            await service.login(
                LoginRequest(identifier="basiltt", password="wrong"), source_ip=f"10.2.{i}.1"
            )
        wrong_durations.append(time.perf_counter() - start)

    avg_unknown = sum(unknown_durations) / samples
    avg_wrong = sum(wrong_durations) / samples
    # Generous tolerance for a CI-shared runner: both paths run one real
    # Argon2id verification, so they should be in the same ballpark.
    assert avg_unknown == pytest.approx(avg_wrong, rel=0.6)


@pytest.mark.asyncio
async def test_per_ip_throttle_blocks_independent_of_username() -> None:
    repo = FakeUserRepository()
    hasher = Hasher(pepper="test-pepper")
    repo.add(make_user(password_hash=await hasher.hash(PASSWORD)))
    throttle = PerIpLoginThrottle(max_attempts=2, window_s=60.0)
    service = LoginService(repo, hasher, per_ip_throttle=throttle)

    for _ in range(2):
        with pytest.raises(InvalidCredentials):
            await service.login(
                LoginRequest(identifier="no-such-user", password="x"), source_ip="10.9.9.9"
            )

    with pytest.raises(InvalidCredentials) as exc:
        await service.login(
            LoginRequest(identifier="basiltt", password=PASSWORD), source_ip="10.9.9.9"
        )
    assert str(exc.value) == "Username or password is incorrect"


@pytest.mark.asyncio
async def test_successful_login_resets_failed_count_and_lockout() -> None:
    repo = FakeUserRepository()
    hasher = Hasher(pepper="test-pepper")
    user = make_user(password_hash=await hasher.hash(PASSWORD), failed_login_count=3)
    repo.add(user)
    service = LoginService(repo, hasher, per_ip_throttle=PerIpLoginThrottle(max_attempts=1000))

    await service.login(LoginRequest(identifier="basiltt", password=PASSWORD), source_ip="10.0.0.1")

    stored = repo.users[str(user.id)]
    assert stored.failed_login_count == 0
    assert stored.locked_until is None


@pytest.mark.asyncio
async def test_stale_argon2_params_trigger_rehash_on_login() -> None:
    repo = FakeUserRepository()
    hasher = Hasher(pepper="test-pepper")
    stale_params = {"m": 8, "t": 1, "p": 1}
    stale_hash = await hasher.hash(PASSWORD, stale_params)
    user = make_user(password_hash=stale_hash, algo_params=stale_params)
    repo.add(user)
    service = LoginService(repo, hasher, per_ip_throttle=PerIpLoginThrottle(max_attempts=1000))

    await service.login(LoginRequest(identifier="basiltt", password=PASSWORD), source_ip="10.0.0.1")

    assert len(repo.rehash_calls) == 1
    stored = repo.users[str(user.id)]
    assert stored.password_hash != stale_hash
    assert await hasher.verify(stored.password_hash, PASSWORD) is True


@pytest.mark.asyncio
async def test_successful_login_persists_hashed_mfa_challenge_when_repository_injected() -> None:
    """E09-S02: `MfaService.verify()`/`.check_recovery()` must be able to look the
    `mfa_token` challenge up by its hash, so `login()` must persist a
    `mfa_challenges` row (never the token itself) when an `MfaRepository`
    is wired in."""
    repo = FakeUserRepository()
    mfa_repo = FakeMfaRepository()
    hasher = Hasher(pepper="test-pepper")
    user = make_user(password_hash=await hasher.hash(PASSWORD), mfa_methods=(MfaMethodKind.TOTP,))
    repo.add(user)
    service = LoginService(
        repo,
        hasher,
        per_ip_throttle=PerIpLoginThrottle(max_attempts=1000),
        mfa_repository=mfa_repo,
    )

    result = await service.login(
        LoginRequest(identifier="basiltt", password=PASSWORD), source_ip="10.0.0.1"
    )

    assert len(mfa_repo.challenges) == 1
    challenge = next(iter(mfa_repo.challenges.values()))
    assert challenge.purpose == "login"
    assert challenge.mfa_token_hash != result.mfa_token
    assert str(challenge.user_id) == str(user.id)


# -- #2295 (Q6): a user who must enrol TOTP first --------------------------------------------------


@pytest.mark.asyncio
async def test_user_who_must_enrol_gets_an_enrolment_only_login_and_no_challenge() -> None:
    repo = FakeUserRepository()
    mfa_repo = FakeMfaRepository()
    hasher = Hasher(pepper="test-pepper")
    user = make_user(
        password_hash=await hasher.hash(PASSWORD), mfa_methods=(), failed_login_count=2
    )
    repo.add(user)
    service = LoginService(
        repo, hasher, per_ip_throttle=PerIpLoginThrottle(max_attempts=1000), mfa_repository=mfa_repo
    )

    result = await service.login(
        LoginRequest(identifier="basiltt", password=PASSWORD), source_ip="10.0.0.1"
    )

    assert result == EnrolmentOnlyLogin(user_id=user.id)
    assert mfa_repo.challenges == {}
    assert repo.users[str(user.id)].failed_login_count == 0  # a real password match


@pytest.mark.asyncio
@pytest.mark.parametrize("methods", [(), (MfaMethodKind.TOTP,)])
async def test_user_not_required_to_use_mfa_still_fails_closed(
    methods: tuple[MfaMethodKind, ...],
) -> None:
    """C-12.2 forbids the state (#965 refuses it); a password-only session is not specified."""
    repo = FakeUserRepository()
    hasher = Hasher(pepper="test-pepper")
    password_hash = await hasher.hash(PASSWORD)
    repo.add(make_user(password_hash=password_hash, mfa_required=False, mfa_methods=methods))

    with pytest.raises(NotImplementedError):
        await _service(repo).login(
            LoginRequest(identifier="basiltt", password=PASSWORD), source_ip="10.0.0.1"
        )
