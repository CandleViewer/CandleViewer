"""In-memory `MfaRepository`, `MfaKeyring` and `SystemEventWriter` fakes for E09 MFA unit tests,
and the rig the TOTP clock-skew tests share (#2146). No database, no real key."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Literal, NoReturn

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from candleviewer.auth.errors import MfaKeyringUnavailable, MfaSealInvalid
from candleviewer.auth.mfa_service import MfaService, _hash_token
from candleviewer.auth.models import (
    MfaChallengeRecord,
    MfaMethodKind,
    MfaMethodRecord,
    MfaVerifyRequest,
)
from candleviewer.auth.recovery_codes import normalize_recovery_code
from candleviewer.auth.totp import TOTP_STEP_SECONDS, generate_code, time_step_for
from candleviewer.auth.totp_skew import SKEW_HOLD_S, TotpSkewReporter
from candleviewer.observability.health_probes import SystemEvent, SystemEventWriter
from tests.unit.auth.auth_fakes import no_wait

#: Integer-built test keys (C-13.5), never a real one: TOTP sealing and recovery-code HMAC.
TEST_TOTP_KEY, TEST_RECOVERY_KEY = bytes(range(32)), bytes(range(32, 64))
#: The `secret_key_ref` the env keys' old seal carries; an imported keyring still reads it.
LEGACY_KEY_REF = "local-dev-v1"
_CODE_MAX = 512  # bytes once normalised, as M2's `_auth_keyring` bounds a code


def recovery_digest(code: str, key: bytes = TEST_RECOVERY_KEY) -> str:
    """A code's digest in the env key's old format, as `FakeMfaKeyring` makes one: the HMAC-SHA256
    of the normalised code under `key`, with no user bound."""
    norm = normalize_recovery_code(code).encode()
    if len(norm) > _CODE_MAX:
        raise ValueError("recovery code too long")
    return hmac.new(key, norm, hashlib.sha256).hexdigest()


class FakeMfaKeyring:
    """An `MfaKeyring` over test keys (#2152), in the env keys' old formats: a TOTP seal is
    AES-256-GCM `nonce || ct || tag` with no AAD under `LEGACY_KEY_REF`, a recovery-code digest the
    HMAC-SHA256 of the normalised code with no user bound. It refuses as M2's keyring does through
    `admin.wiring`: while `down` names a reason every call refuses with it (`available` answers
    false); a ref outside `held` (when set) is not held; a seal that does not open is
    `MfaSealInvalid` (a wrong code) and a code over the bound a `ValueError`. It records each
    seed it opens (`opened`), so a test can assert the verifier zeroed it, and keeps the sync
    fixture helpers `encrypt`, `decrypt`, `key_ref` and `digest` for seeding rows."""

    key_ref = LEGACY_KEY_REF

    def __init__(
        self, totp_key: bytes = TEST_TOTP_KEY, recovery_key: bytes = TEST_RECOVERY_KEY
    ) -> None:
        self._aead, self._digest_key = AESGCM(totp_key), recovery_key
        self.opened: list[bytearray] = []
        #: While set, the reason every call refuses with (the KEK or the keyring is down).
        self.down: str | None = None
        #: When set, the only refs whose key is held (`auth_key_not_held` for any other).
        self.held: frozenset[str] | None = None

    def _require(self, *key_refs: str) -> None:
        if self.down is not None:
            raise MfaKeyringUnavailable(self.down)
        if self.held is not None and not set(key_refs) <= self.held:
            raise MfaKeyringUnavailable("auth_key_not_held")

    async def available(self, *key_refs: str) -> bool:
        try:
            self._require(*key_refs)
        except MfaKeyringUnavailable:
            return False
        return True

    async def seal_totp_seed(
        self, seed: bytes | bytearray, user_id: uuid.UUID
    ) -> tuple[bytes, str]:
        self._require()
        return self.encrypt(bytes(seed)), self.key_ref

    async def open_totp_seed(self, blob: bytes, key_ref: str, user_id: uuid.UUID) -> bytearray:
        self._require(key_ref)
        try:
            seed = bytearray(self.decrypt(blob))
        except (InvalidTag, ValueError):
            raise MfaSealInvalid("auth_seal_invalid") from None
        self.opened.append(seed)
        return seed

    async def recovery_code_digests(self, code: str, user_id: uuid.UUID) -> tuple[str, ...]:
        self._require()
        return (self.digest(code),)

    def encrypt(self, seed: bytes) -> bytes:
        nonce = os.urandom(12)
        return nonce + self._aead.encrypt(nonce, seed, None)

    def decrypt(self, blob: bytes) -> bytes:
        return self._aead.decrypt(blob[:12], blob[12:], None)

    def digest(self, code: str) -> str:
        return recovery_digest(code, self._digest_key)

    def __repr__(self) -> str:
        return "FakeMfaKeyring(***)"

    def __reduce_ex__(self, protocol: object) -> NoReturn:
        raise TypeError("FakeMfaKeyring cannot be pickled")


class FakeMfaRepository:
    def __init__(self) -> None:
        self.methods: dict[str, MfaMethodRecord] = {}
        self.challenges: dict[str, MfaChallengeRecord] = {}
        self.recovery_codes: dict[str, dict[str, str | None]] = {}
        # user_id -> {code_id: code_hash}, used_at tracked in `used_codes`
        self.used_codes: set[str] = set()
        #: #2911: users both completions read as `disabled` or gone under their user-row lock.
        self.disabled_users: set[str] = set()
        #: `security.mfa_recovery_used`, one user id per committed spend (contract, #2344).
        self.recovery_events: list[str] = []

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
    ) -> MfaMethodRecord | Literal[False] | None:
        """Single-threaded fake: the claim, the revocations and the code swap happen in
        one synchronous step, the atomicity the SQL unit of work provides."""
        if user_id in self.disabled_users:
            return False
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

    async def seed_confirmed(self, method_id: str, *, now: datetime) -> MfaMethodRecord:
        """Test seeding only, not `MfaRepository`: mark *method_id* confirmed at *now*.
        Production confirms through `complete_enrollment` alone (#2295)."""
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

    async def find_unused_recovery_code(
        self, user_id: str, *, code_hashes: Sequence[str]
    ) -> str | None:
        for code_id, row in self.recovery_codes.items():
            matches = (
                row["user_id"] == user_id
                and row["code_hash"] in code_hashes  # `code_hash = ANY` (#2152 BQ-3)
                and row["used_at"] is None
            )
            if matches:
                return code_id
        return None

    async def count_unused_recovery_codes(self, user_id: str) -> int:
        return sum(
            1
            for row in self.recovery_codes.values()
            if row["user_id"] == user_id and row["used_at"] is None
        )

    async def complete_recovery(
        self, user_id: str, *, challenge_id: str, code_id: str, now: datetime
    ) -> bool | None:
        """Single-threaded fake of the SQL unit of work (#2344): the user's status and both
        conditions are checked before anything changes, so a disabled user (`None`) or a lost
        race leaves the code, the challenge and the methods as they were."""
        if user_id in self.disabled_users:
            return None
        row = self.recovery_codes.get(code_id)
        challenge = self.challenges.get(challenge_id)
        if row is None or row["user_id"] != user_id or row["used_at"] is not None:
            return False
        if challenge is None or str(challenge.user_id) != user_id:
            return False
        if challenge.satisfied_at is not None:
            return False
        row["used_at"] = now.isoformat()
        self.challenges[challenge_id] = challenge.model_copy(update={"satisfied_at": now})
        for method_id, method in list(self.methods.items()):
            if str(method.user_id) == user_id and method.revoked_at is None:
                self.methods[method_id] = method.model_copy(update={"revoked_at": now})
        self.recovery_events.append(user_id)
        return True


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
        self.enc = FakeMfaKeyring()
        self.reporter = TotpSkewReporter(sink or self.events)
        self.svc = MfaService(
            self.repo,
            self.enc,
            clock=self.clock,
            skew_reporter=self.reporter,
            sleep=no_wait,
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
            await self.repo.seed_confirmed(str(method.id), now=self.now)
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
