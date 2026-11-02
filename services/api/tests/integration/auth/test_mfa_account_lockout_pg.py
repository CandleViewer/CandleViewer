"""Integration (#2695, SR-015 / SR-016): second-factor refusals lock the account on Postgres 16.

`MfaService` over the real `SqlAlchemyMfaRepository` and `SqlAlchemyUserRepository`: refusals
spread over two login challenges set `users.locked_until`, and refusals running at once on
separate challenges count without a lost update and apply the lock once; a right code racing
`LOCKOUT_THRESHOLD` refusals never clears the lock they set (the conditional reset, the read of
record on PR #5380). Fixed auth clock that
tracks the wall clock (rows carry DB-stamped `created_at`), no wait. Needs Docker
(testcontainers); the CI `integration` job runs it.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from prometheus_client import REGISTRY

from candleviewer.auth.errors import MfaChallengeLocked, MfaCodeInvalid
from candleviewer.auth.login_service import LOCKOUT_DURATION, LOCKOUT_THRESHOLD
from candleviewer.auth.mfa_service import CHALLENGE_ATTEMPT_CAP, MfaService, _hash_token
from candleviewer.auth.models import (
    MfaChallengeRecord,
    MfaMethodKind,
    MfaMethodRecord,
    MfaVerifyRequest,
    UserRecord,
)
from candleviewer.auth.totp import generate_code, time_step_for
from candleviewer.storage.repositories.mfa_sqlalchemy import SqlAlchemyMfaRepository
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.users_sqlalchemy import SqlAlchemyUserRepository
from scripts.seed_fixture_user import seed
from tests.unit.auth.auth_fakes import no_wait
from tests.unit.auth.mfa_fakes import FakeMfaKeyring

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_NOW = datetime.now(UTC).replace(microsecond=0)
_SEED = bytes(range(20))  # an integer-built TOTP seed (C-13.5)
_PASSWORD = "correct horse battery"  # noqa: S105 -- throwaway fixture password


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT,
            env={
                **os.environ,
                "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg"),
            },
            check=True,
        )
        yield dsn


class _Rig:
    def __init__(self, dsn: str) -> None:
        self.rel = SqlAlchemyRelationalRepository(dsn)
        self.mfa = SqlAlchemyMfaRepository(
            self.rel,
            lambda **f: MfaMethodRecord.model_validate(f),
            lambda **f: MfaChallengeRecord.model_validate(f),
        )
        self.users = SqlAlchemyUserRepository(
            self.rel, lambda **f: UserRecord.model_validate(f), clock=lambda: _NOW
        )
        self.keyring = FakeMfaKeyring()
        self.svc = MfaService(
            self.mfa, self.keyring, clock=lambda: _NOW, sleep=no_wait, users=self.users
        )

    async def enrolled_user(self, dsn: str, name: str) -> str:
        user_id = await seed(dsn, name, _PASSWORD)
        assert user_id is not None
        method = await self.mfa.create_pending_method(
            user_id,
            secret_enc=self.keyring.encrypt(_SEED),
            secret_key_ref=self.keyring.key_ref,
            label="it",
        )
        confirmed = await self.mfa.complete_enrollment(
            user_id,
            method_id=str(method.id),
            time_step=time_step_for(_NOW.timestamp()) - 20,
            now=_NOW,
            code_hashes=(),
        )
        assert confirmed
        return user_id

    async def challenge(self, user_id: str, token: str) -> str:
        await self.mfa.create_challenge(
            user_id,
            purpose="login",
            mfa_token_hash=_hash_token(token),
            expires_at=_NOW + timedelta(minutes=5),
        )
        return token

    async def refuse(self, token: str, code: str) -> None:
        request = MfaVerifyRequest(mfa_token=token, method=MfaMethodKind.TOTP, code=code)
        with pytest.raises((MfaCodeInvalid, MfaChallengeLocked)):
            await self.svc.verify(request)


def _wrong_codes() -> list[str]:
    valid = {generate_code(_SEED, time_step_for(_NOW.timestamp()) + o) for o in range(-2, 3)}
    return [c for c in (f"{i:06d}" for i in range(100)) if c not in valid]


def _lockouts() -> float:
    return float(REGISTRY.get_sample_value("auth_lockouts_total") or 0.0)


async def test_mfa_refusals_across_challenges_lock_account_pg(pg_dsn: str) -> None:
    rig = _Rig(pg_dsn)
    try:
        user_id = await rig.enrolled_user(pg_dsn, "mfa-lock-a")
        codes = iter(_wrong_codes())
        first = await rig.challenge(user_id, "mfa-lock-a-1")
        for _ in range(CHALLENGE_ATTEMPT_CAP - 1):
            await rig.refuse(first, next(codes))
        second = await rig.challenge(user_id, "mfa-lock-a-2")
        for _ in range(LOCKOUT_THRESHOLD - CHALLENGE_ATTEMPT_CAP + 1):
            await rig.refuse(second, next(codes))

        row = await rig.users.find_by_id(user_id)
        assert row is not None
        assert row.failed_login_count == LOCKOUT_THRESHOLD
        assert row.locked_until == _NOW + LOCKOUT_DURATION
    finally:
        await rig.rel.dispose()


async def test_mfa_concurrent_refusals_count_exactly_and_lock_once_pg(pg_dsn: str) -> None:
    rig = _Rig(pg_dsn)
    try:
        user_id = await rig.enrolled_user(pg_dsn, "mfa-lock-b")
        tokens = [await rig.challenge(user_id, f"mfa-lock-b-{i}") for i in range(LOCKOUT_THRESHOLD)]
        before = _lockouts()

        await asyncio.gather(
            *(rig.refuse(t, c) for t, c in zip(tokens, _wrong_codes()[: len(tokens)], strict=True))
        )

        row = await rig.users.find_by_id(user_id)
        assert row is not None
        assert row.failed_login_count == LOCKOUT_THRESHOLD  # no lost update
        assert row.locked_until == _NOW + LOCKOUT_DURATION
        assert _lockouts() == before + 1
    finally:
        await rig.rel.dispose()


async def test_mfa_right_code_racing_threshold_refusals_keeps_lock_pg(
    pg_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`LOCKOUT_THRESHOLD + 1` attempts at once: the right code passes its lock read, then waits
    at the challenge's satisfaction until `LOCKOUT_THRESHOLD` wrong codes have locked the account;
    its conditional reset then matches no row, so it is refused and the lock stands."""
    rig = _Rig(pg_dsn)
    try:
        user_id = await rig.enrolled_user(pg_dsn, "mfa-lock-c")
        right = await rig.challenge(user_id, "mfa-lock-c-right")
        others = [await rig.challenge(user_id, f"mfa-lock-c-{i}") for i in range(LOCKOUT_THRESHOLD)]
        arrived, gate, satisfy = asyncio.Event(), asyncio.Event(), rig.mfa.satisfy_challenge

        async def held(*args: Any, **kwargs: Any) -> bool:
            arrived.set()
            await gate.wait()
            return await satisfy(*args, **kwargs)

        monkeypatch.setattr(rig.mfa, "satisfy_challenge", held)

        async def refusals() -> None:
            await arrived.wait()
            wrong = zip(others, _wrong_codes()[: len(others)], strict=True)
            await asyncio.gather(*(rig.refuse(token, code) for token, code in wrong))
            gate.set()

        code = generate_code(_SEED, time_step_for(_NOW.timestamp()))
        request = MfaVerifyRequest(mfa_token=right, method=MfaMethodKind.TOTP, code=code)
        outcome, _ = await asyncio.gather(
            rig.svc.verify(request), refusals(), return_exceptions=True
        )

        assert isinstance(outcome, MfaChallengeLocked)
        row = await rig.users.find_by_id(user_id)
        assert row is not None
        assert row.failed_login_count == LOCKOUT_THRESHOLD  # the refused right code: uncounted
        assert row.locked_until == _NOW + LOCKOUT_DURATION
    finally:
        await rig.rel.dispose()


async def test_record_sign_in_unless_locked_keeps_a_lock_pg(pg_dsn: str) -> None:
    rig = _Rig(pg_dsn)
    try:
        user_id = await rig.enrolled_user(pg_dsn, "mfa-lock-d")
        for _ in range(LOCKOUT_THRESHOLD):
            await rig.users.record_login_failure(
                user_id,
                lockout_threshold=LOCKOUT_THRESHOLD,
                lock_duration=LOCKOUT_DURATION,
                now=_NOW,
            )

        kept = await rig.users.record_sign_in_unless_locked(user_id, now=_NOW)
        expired = await rig.users.record_sign_in_unless_locked(user_id, now=_NOW + LOCKOUT_DURATION)

        assert (kept, expired) == (False, True)
        row = await rig.users.find_by_id(user_id)
        assert row is not None
        assert (row.failed_login_count, row.locked_until) == (0, None)
    finally:
        await rig.rel.dispose()
