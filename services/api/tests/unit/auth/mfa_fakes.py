"""In-memory `MfaRepository` and `SystemEventWriter` fakes for E09 MFA unit tests. No database."""

from __future__ import annotations

import uuid
from datetime import datetime

from candleviewer.auth.models import MfaChallengeRecord, MfaMethodKind, MfaMethodRecord
from candleviewer.observability.health_probes import SystemEvent


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
        method = self.methods.get(method_id)
        if method is None or str(method.user_id) != user_id or method.confirmed_at is not None:
            return None
        return method

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
