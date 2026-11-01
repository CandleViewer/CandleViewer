"""#2695 (SR-015 / SR-016): second-factor and recovery-code refusals count on the account.

The services are built by `AuthService.start()` over in-memory fakes, so the wiring is what is
tested: refusals spread over several challenges reach the login's `LOCKOUT_THRESHOLD` and lock the
account for `LOCKOUT_DURATION`, the password step no longer zeroes the count before the second
factor, a completed sign-in does, and an open challenge of a locked account is refused with the
same `401` as a wrong code. The per-address budget (#4664) is unchanged. Fixed clock, no wait
(the minimum-time hold keeps its minimum and skips the wait), no network.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from prometheus_client import REGISTRY

from candleviewer.api.auth import make_auth_router
from candleviewer.auth.csrf import CsrfCodec
from candleviewer.auth.errors import (
    AccountLocked,
    MfaChallengeInvalid,
    MfaChallengeLocked,
    MfaCodeInvalid,
    RecoveryCodeInvalid,
)
from candleviewer.auth.failure_hold import FailureHold
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.login_service import LOCKOUT_DURATION, LOCKOUT_THRESHOLD
from candleviewer.auth.mfa_service import CHALLENGE_ATTEMPT_CAP
from candleviewer.auth.models import (
    LoginRequest,
    MfaChallengeResult,
    MfaMethodKind,
    MfaVerifiedResult,
    MfaVerifyRequest,
    UserRecord,
)
from candleviewer.auth.service import AuthService
from candleviewer.auth.throttle import PerIpLoginThrottle
from candleviewer.auth.totp import generate_code, time_step_for
from tests.unit.api._fakes import AuditService, Identity, sessions
from tests.unit.auth.auth_fakes import FakeUserRepository, make_user, no_wait
from tests.unit.auth.mfa_fakes import FakeMfaKeyring, FakeMfaRepository

_PEPPER = "test-pepper"
_PASSWORD = "correct-horse-battery-staple"
_SEED = bytes(range(20))  # an integer-built TOTP seed (C-13.5), never a real one
_NOW = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)


class _Clock:
    def __init__(self) -> None:
        self.now = _NOW

    def __call__(self) -> datetime:
        return self.now


class _World:
    """`AuthService` over fakes: one active user with one confirmed TOTP method."""

    def __init__(self, auth: AuthService, users: FakeUserRepository, user: UserRecord) -> None:
        self.auth, self.users, self.uid = auth, users, str(user.id)
        self.clock = cast(_Clock, auth._clock)

    @property
    def row(self) -> UserRecord:
        return self.users.users[self.uid]

    async def sign_in(self) -> str:
        """The password step; returns the challenge's `mfa_token`."""
        result = await self.auth.login.login(
            LoginRequest(identifier="basiltt", password=_PASSWORD), source_ip="10.0.0.1"
        )
        assert isinstance(result, MfaChallengeResult)
        return result.mfa_token

    def code(self) -> str:
        return generate_code(_SEED, time_step_for(self.clock.now.timestamp()))

    def wrong_codes(self, n: int) -> Iterator[str]:
        valid = {generate_code(_SEED, time_step_for(_NOW.timestamp()) + o) for o in range(-2, 3)}
        return iter([c for c in (f"{i:06d}" for i in range(100)) if c not in valid][:n])

    async def verify(self, token: str, code: str) -> MfaVerifiedResult:
        request = MfaVerifyRequest(mfa_token=token, method=MfaMethodKind.TOTP, code=code)
        return await self.auth.mfa.verify(request)

    async def refuse_codes(self, token: str, n: int) -> None:
        for code in self.wrong_codes(n):
            with pytest.raises((MfaCodeInvalid, MfaChallengeLocked)):
                await self.verify(token, code)

    async def refuse_recovery(self, token: str, n: int) -> None:
        for i in range(n):
            with pytest.raises((RecoveryCodeInvalid, MfaChallengeLocked)):
                await self.auth.mfa.check_recovery(token, f"zzzz-zzzz-{i:04d}")


@pytest.fixture
async def world() -> AsyncIterator[_World]:
    clock, users, mfa_repo, keyring = (
        _Clock(),
        FakeUserRepository(),
        FakeMfaRepository(),
        FakeMfaKeyring(),
    )
    user = make_user(password_hash=await Hasher(pepper=_PEPPER).hash(_PASSWORD))
    users.add(user)
    method = await mfa_repo.create_pending_method(
        str(user.id), secret_enc=keyring.encrypt(_SEED), secret_key_ref=keyring.key_ref, label=""
    )
    await mfa_repo.seed_confirmed(str(method.id), now=clock.now)
    auth = AuthService(
        users, pepper=_PEPPER, mfa_repository=mfa_repo, mfa_keyring=keyring, clock=clock
    )
    await auth.start(ctx=None)  # type: ignore[arg-type]  # no settings needed outside live
    auth.login._failure_hold = FailureHold(sleep=no_wait)
    auth.mfa._failure_hold = FailureHold(sleep=no_wait)
    await auth.mfa.regenerate_recovery_codes(str(user.id))
    yield _World(auth, users, user)
    await auth.stop(grace_s=1.0)


def _lockouts() -> float:
    return float(REGISTRY.get_sample_value("auth_lockouts_total") or 0.0)


# -- red before #2695 --------------------------------------------------------------------------


async def test_mfa_verify_refusals_across_challenges_lock_account(world: _World) -> None:
    before = _lockouts()
    await world.refuse_codes(await world.sign_in(), CHALLENGE_ATTEMPT_CAP - 1)
    await world.refuse_codes(await world.sign_in(), LOCKOUT_THRESHOLD - CHALLENGE_ATTEMPT_CAP + 1)

    assert world.row.locked_until == world.clock.now + LOCKOUT_DURATION
    assert _lockouts() == before + 1
    with pytest.raises(AccountLocked):
        await world.sign_in()  # the right password, refused while the account is locked


async def test_mfa_check_recovery_refusals_count_toward_account_lock(world: _World) -> None:
    before = _lockouts()
    await world.refuse_recovery(await world.sign_in(), CHALLENGE_ATTEMPT_CAP - 1)
    await world.refuse_recovery(
        await world.sign_in(), LOCKOUT_THRESHOLD - CHALLENGE_ATTEMPT_CAP + 1
    )

    assert world.row.locked_until == world.clock.now + LOCKOUT_DURATION
    assert _lockouts() == before + 1
    with pytest.raises(AccountLocked):
        await world.sign_in()


async def test_login_password_match_with_challenge_keeps_account_counter(world: _World) -> None:
    await world.refuse_codes(await world.sign_in(), LOCKOUT_THRESHOLD - 1)

    await world.sign_in()

    assert world.row.failed_login_count == LOCKOUT_THRESHOLD - 1


async def test_mfa_verify_locked_account_open_challenge_refused(world: _World) -> None:
    held_open = await world.sign_in()
    await world.refuse_codes(await world.sign_in(), LOCKOUT_THRESHOLD)
    assert world.row.locked_until is not None

    with pytest.raises(MfaChallengeLocked):  # the right code, on a challenge with no refusal
        await world.verify(held_open, world.code())
    assert world.row.failed_login_count == LOCKOUT_THRESHOLD  # the lock is not counted again


# -- negative controls (green before and after) -------------------------------------------------


async def test_mfa_verify_valid_code_after_refusals_resets_account_counter(world: _World) -> None:
    token = await world.sign_in()
    await world.refuse_codes(token, LOCKOUT_THRESHOLD - 1)

    result = await world.verify(token, world.code())

    assert result.user_id == uuid.UUID(world.uid)
    assert (world.row.failed_login_count, world.row.locked_until) == (0, None)


async def test_mfa_refusals_below_threshold_leave_account_unlocked(world: _World) -> None:
    before = _lockouts()
    await world.refuse_codes(await world.sign_in(), LOCKOUT_THRESHOLD - 2)
    await world.refuse_recovery(await world.sign_in(), 1)

    assert world.row.locked_until is None
    assert _lockouts() == before
    await world.sign_in()  # still answered with a challenge


async def test_mfa_verify_unknown_or_expired_challenge_changes_no_account_counter(
    world: _World,
) -> None:
    token = await world.sign_in()
    world.clock.now += timedelta(minutes=6)  # past the challenge's 5-minute life
    for unknown in ("never-issued-token", token):
        with pytest.raises(MfaChallengeInvalid):
            await world.verify(unknown, "000000")

    assert (world.row.failed_login_count, world.row.locked_until) == (0, None)


# -- the router answer and the per-address budget (#4664) are unchanged ---------------------------


class _RefusingMfa:
    """Refuses each check with the next error of *errors*; counts the checks."""

    def __init__(self, *errors: Exception) -> None:
        self.errors, self.checks = list(errors), 0

    async def verify(self, *_args: object) -> MfaVerifiedResult:
        self.checks += 1
        raise self.errors.pop(0)


class _RouterAuth:
    is_active = mfa_is_active = sessions_is_active = True

    def __init__(self, mfa: _RefusingMfa) -> None:
        self.mfa, self.login, self.sessions = mfa, None, sessions()


async def test_mfa_locked_account_answer_matches_wrong_code_and_spends_one_place() -> None:
    mfa = _RefusingMfa(MfaCodeInvalid("x"), MfaChallengeLocked("x"))
    budget = PerIpLoginThrottle(max_attempts=2, window_s=60.0, clock=lambda: 0.0)
    router = make_auth_router(
        cast(Any, _RouterAuth(mfa)),
        AuditService(),
        identity=Identity(),
        csrf=CsrfCodec(b"\x05" * 32),
        mfa_refusal_budget=budget,
    )
    app = FastAPI()
    app.include_router(router)
    body = {"mfa_token": "t" * 20, "method": "totp", "code": "000000"}
    transport = httpx.ASGITransport(app=app, client=("10.0.0.1", 50000))
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        wrong, locked, over = [await client.post("/auth/mfa/verify", json=body) for _ in "abc"]

    assert (wrong.status_code, locked.status_code) == (401, 401)
    assert locked.json() == wrong.json()
    assert over.status_code == 429  # two refusals spend the budget of two, as before
    assert mfa.checks == 2
