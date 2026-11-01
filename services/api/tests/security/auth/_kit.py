"""Shared fixtures for the E09-X02 abuse-case suite (fixed clock, in-memory fakes, no network)."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

from candleviewer.auth.mfa_service import MfaService, _hash_token
from candleviewer.auth.models import MfaEnrollRequest, MfaMethodKind
from candleviewer.auth.totp import generate_code, time_step_for
from tests.unit.auth.auth_fakes import no_wait
from tests.unit.auth.mfa_fakes import FakeMfaKeyring, FakeMfaRepository

NOW = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)
RC_KEY = b"k" * 32


class Clock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


class MfaKit:
    """One MfaService + fake repo; `enrol()` yields a confirmed TOTP seed per user."""

    def __init__(self, clock: Clock | None = None) -> None:
        self.clock = clock or Clock()
        self.repo = FakeMfaRepository()
        self.enc = FakeMfaKeyring(os.urandom(32), RC_KEY)
        self.svc = MfaService(self.repo, self.enc, clock=self.clock, sleep=no_wait)

    async def enrol(self, user: uuid.UUID) -> bytes:
        res = await self.svc.enroll(
            str(user), MfaEnrollRequest(method=MfaMethodKind.TOTP, label=""), account_name="a"
        )
        seed = self.enc.decrypt(self.repo.methods[str(res.method_id)].secret_enc)  # type: ignore[arg-type]
        step = time_step_for(self.clock.now.timestamp()) - 1
        await self.svc.confirm_enrollment(
            str(user), method_id=str(res.method_id), code=generate_code(seed, step)
        )
        return seed

    async def challenge(self, user: uuid.UUID, token: str) -> str:
        await self.repo.create_challenge(
            str(user),
            purpose="login",
            mfa_token_hash=_hash_token(token),
            expires_at=self.clock.now + timedelta(minutes=5),
        )
        return token

    def code(self, seed: bytes, offset: int = 0) -> str:
        return generate_code(seed, time_step_for(self.clock.now.timestamp()) + offset)
