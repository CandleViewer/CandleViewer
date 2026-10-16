"""In-memory `MfaRepository` and `SystemEventWriter` fakes for E09 MFA unit tests, and the rig the
TOTP clock-skew tests share (#2146). No database."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

from candleviewer.auth.envelope import TotpEncryptor
from candleviewer.auth.mfa_service import MfaService, _hash_token
from candleviewer.auth.models import (
    MfaChallengeRecord,
    MfaMethodKind,
    MfaMethodRecord,
    MfaVerifyRequest,
)
from candleviewer.auth.totp import TOTP_STEP_SECONDS, generate_code, time_step_for
from candleviewer.auth.totp_skew import SKEW_HOLD_S, TotpSkewReporter
from candleviewer.observability.health_probes import SystemEvent, SystemEventWriter


class FakeMfaRepository:
    def __init__(self) -> None:
        self.methods: dict[str, MfaMethodRecord] = {}
        self.challenges: dict[str, MfaChallengeRecord] = {}
        self.recovery_codes: dict[str, dict[str, str | None]] = {}
        # user_id -> {code_id: code_hash}, used_at tracked in `used_codes`
        self.used_codes: set[str] = set()

    # -- mfa_methods ---------------------------------------------------

    def add_method(self, method: MfaMethodRecord) -> None:
        self.methods[str(method.id)] = method

    async def create_pending_method(
        self,
        user_id: str,
        *,
        secret_enc: bytes,
        secret_key_ref: str,
        label: str,
    ) -> MfaMethodRecord:
        method = MfaMethodRecord(
            id=uuid.uuid4(),
            user_id=uuid.UUID(user_id),
            kind=MfaMethodKind.TOTP,
            label=label,
            secret_enc=secret_enc,
            secret_key_ref=secret_key_ref,
            created_at=datetime.now(),
        )
        self.methods[str(method.id)] = method
        return method

    async def find_pending_method(self, method_id: str, user_id: str) -> MfaMethodRecord | None:
        """The SQL `_CONFIRMABLE` rule: never confirmed, not revoked, the user's latest
        method (insertion order stands in for `created_at`)."""
        method = self.methods.get(method_id)
        own = [m for m in self.methods.values() if str(m.user_id) == user_id]
        if (
            method is None
            or not own
            or own[-1].id != method.id
            or method.confirmed_at is not None
            or method.revoked_at is not None
            or method.last_accepted_time_step is not None
        ):
            return None
        return method

    async def supersede_pending_methods(self, user_id: str, *, now: datetime) -> None:
        for method_id, m in list(self.methods.items()):
            if str(m.user_id) == user_id and m.confirmed_at is None and m.revoked_at is None:
                self.methods[method_id] = m.model_copy(update={"revoked_at": now})

    async def complete_enrollment(
        self,
        user_id: str,
        *,
        method_id: str,
        time_step: int,
        now: datetime,
        code_hashes: tuple[str, ...],
    ) -> MfaMethodRecord | None:
        """Single-threaded fake: the claim, the revocations and the code swap happen in
        one synchronous step, the atomicity the SQL unit of work provides."""
        if await self.find_pending_method(method_id, user_id) is None:
            return None
        claimed = self.methods[method_id].model_copy(
            update={"confirmed_at": now, "last_accepted_time_step": time_step}
        )
        self.methods[method_id] = claimed
        for other_id, m in list(self.methods.items()):
            mine = str(m.user_id) == user_id and other_id != method_id
            if mine and m.kind == MfaMethodKind.TOTP and m.revoked_at is None:
                self.methods[other_id] = m.model_copy(update={"revoked_at": now})
        await self.replace_recovery_codes(user_id, code_hashes=code_hashes)
        return claimed

    async def confirm_method(self, method_id: str, *, now: datetime) -> MfaMethodRecord:
        method = self.methods[method_id]
        confirmed = method.model_copy(update={"confirmed_at": now})
        self.methods[method_id] = confirmed
        return confirmed

    async def find_active_totp_methods(self, user_id: str) -> tuple[MfaMethodRecord, ...]:
        return tuple(
            m
            for m in self.methods.values()
            if str(m.user_id) == user_id
            and m.kind == MfaMethodKind.TOTP
            and m.confirmed_at is not None
            and m.revoked_at is None
        )

    async def find_active_methods(self, user_id: str) -> tuple[MfaMethodRecord, ...]:
        return tuple(
            m
            for m in self.methods.values()
            if str(m.user_id) == user_id and m.confirmed_at is not None and m.revoked_at is None
        )

    async def record_time_step(self, method_id: str, *, time_step: int) -> bool:
        method = self.methods[method_id]
        last_step = method.last_accepted_time_step
        if last_step is not None and time_step <= last_step:
            return False
        self.methods[method_id] = method.model_copy(update={"last_accepted_time_step": time_step})
        return True

    async def revoke_method(self, method_id: str, *, now: datetime) -> None:
        method = self.methods[method_id]
        self.methods[method_id] = method.model_copy(update={"revoked_at": now})

    async def touch_method_used(self, method_id: str, *, now: datetime) -> None:
        method = self.methods[method_id]
        self.methods[method_id] = method.model_copy(update={"last_used_at": now})

    # -- mfa_challenges --------------------------------------------------

    async def create_challenge(
        self,
        user_id: str,
        *,
        purpose: str,
        mfa_token_hash: str,
        expires_at: datetime,
    ) -> MfaChallengeRecord:
        challenge = MfaChallengeRecord(
            id=uuid.uuid4(),
            user_id=uuid.UUID(user_id),
            mfa_token_hash=mfa_token_hash,
            purpose=purpose,
            attempts=0,
            satisfied_at=None,
            expires_at=expires_at,
            created_at=datetime.now(),
        )
        self.challenges[str(challenge.id)] = challenge
        return challenge

    async def find_open_challenge_by_token_hash(
        self, mfa_token_hash: str
    ) -> MfaChallengeRecord | None:
        for challenge in self.challenges.values():
            if challenge.mfa_token_hash == mfa_token_hash and challenge.satisfied_at is None:
                return challenge
        return None

    async def record_challenge_attempt(self, challenge_id: str) -> int:
        challenge = self.challenges[challenge_id]
        new_count = challenge.attempts + 1
        self.challenges[challenge_id] = challenge.model_copy(update={"attempts": new_count})
        return new_count

    async def satisfy_challenge(self, challenge_id: str, *, now: datetime) -> bool:
        challenge = self.challenges[challenge_id]
        if challenge.satisfied_at is not None:
            return False
        self.challenges[challenge_id] = challenge.model_copy(update={"satisfied_at": now})
        return True

    # -- recovery_codes ----------------------------------------------------

    async def replace_recovery_codes(self, user_id: str, *, code_hashes: tuple[str, ...]) -> None:
        self.recovery_codes = {
            k: v for k, v in self.recovery_codes.items() if v["user_id"] != user_id
        }
        for code_hash in code_hashes:
            code_id = str(uuid.uuid4())
            self.recovery_codes[code_id] = {
                "user_id": user_id,
                "code_hash": code_hash,
                "used_at": None,
            }

    async def find_unused_recovery_code(self, user_id: str, *, code_hash: str) -> str | None:
        for code_id, row in self.recovery_codes.items():
            matches = (
                row["user_id"] == user_id
                and row["code_hash"] == code_hash
                and row["used_at"] is None
            )
            if matches:
                return code_id
        return None

    async def consume_recovery_code(self, code_id: str, *, now: datetime) -> bool:
        row = self.recovery_codes[code_id]
        if row["used_at"] is not None:
            return False
        row["used_at"] = now.isoformat()
        return True

    async def count_unused_recovery_codes(self, user_id: str) -> int:
        return sum(
            1
            for row in self.recovery_codes.values()
            if row["user_id"] == user_id and row["used_at"] is None
        )

    async def set_mfa_required_reenroll(self, user_id: str) -> None:
        for method_id, method in list(self.methods.items()):
            if str(method.user_id) == user_id and method.kind == MfaMethodKind.TOTP:
                self.methods[method_id] = method.model_copy(update={"confirmed_at": None})


class RecordingSystemEvents:
    """`SystemEventWriter` that keeps what it was given; `fail_with` makes every write raise."""

    def __init__(self, fail_with: BaseException | None = None) -> None:
        self.written: list[SystemEvent] = []
        self._fail_with = fail_with

    async def write(self, event: SystemEvent) -> None:
        if self._fail_with is not None:
            raise self._fail_with
        self.written.append(event)


class StalledSystemEvents:
    """`SystemEventWriter` whose write never completes: only a caller's own timeout ends it."""

    async def write(self, event: SystemEvent) -> None:
        await asyncio.Event().wait()


class SkewRig:
    """`MfaService` over `FakeMfaRepository`, a recording event sink and a clock the test moves.
    Methods are added with a given seed, so nothing random is drawn."""

    def __init__(self, sink: SystemEventWriter | None = None) -> None:
        self.events = RecordingSystemEvents()  # what the reporter writes, unless `sink` replaces it
        self.now = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)
        self.user = uuid.uuid4()
        self.repo = FakeMfaRepository()
        self.enc = TotpEncryptor(os.urandom(32))
        self.reporter = TotpSkewReporter(sink or self.events)
        self.svc = MfaService(
            self.repo,
            self.enc,
            recovery_code_key=b"k" * 32,
            clock=self.clock,
            skew_reporter=self.reporter,
        )

    def clock(self) -> datetime:
        return self.now

    def advance(self, steps: int) -> None:
        self.now += timedelta(seconds=TOTP_STEP_SECONDS * steps)

    def code(self, seed: bytes, offset: int = 0) -> str:
        """The code of `seed` for the step `offset` steps from the current one."""
        return generate_code(seed, time_step_for(self.now.timestamp()) + offset)

    async def flush(self) -> None:
        """Let every hold elapse and publish what was held."""
        await self.reporter.publish_due(self.now.timestamp() + SKEW_HOLD_S)

    async def add_method(self, seed: bytes, *, confirmed: bool = True) -> str:
        method = await self.repo.create_pending_method(
            str(self.user),
            secret_enc=self.enc.encrypt(seed),
            secret_key_ref=self.enc.key_ref,
            label="",
        )
        if confirmed:
            await self.repo.confirm_method(str(method.id), now=self.now)
        return str(method.id)

    async def verify(self, token: str, code: str) -> None:
        """One `verify` call on the login challenge `token` (opened on first use)."""
        digest = _hash_token(token)
        if not any(c.mfa_token_hash == digest for c in self.repo.challenges.values()):
            expires = self.now + timedelta(minutes=5)
            await self.repo.create_challenge(
                str(self.user), purpose="login", mfa_token_hash=digest, expires_at=expires
            )
        request = MfaVerifyRequest(mfa_token=token, method=MfaMethodKind.TOTP, code=code)
        await self.svc.verify(request)
