"""`InviteService` (E09-S05, US-ONB-006): invite-based user creation and redemption.

The only way a user account comes into existence: the owner mints a 256-bit
single-use token (stored only as a sha256 hash, valid 72 h); the invitee sets a
password and enrols TOTP; only then does `users.status` flip to `active`.

Redemption is two persisted steps so an abandoned enrolment leaves the account
unusable rather than half-open:

1. `begin_redemption` atomically consumes the token (a conditional UPDATE, so
   of two concurrent redemptions exactly one wins), parks the Argon2id hash in
   the invite row - NOT in `users.password_hash`, so no sign-in is possible -
   and starts TOTP enrolment.
2. `complete_redemption` verifies the first TOTP code, then activates the user
   and moves the password hash across.

The role is always `viewer` (#2109); a legacy stored non-viewer role is downgraded at
redemption. Callers cannot pass one. The raw
token is never logged, stored, or put in an exception message. Unknown /
expired / redeemed / revoked tokens raise `InviteRejected` (distinct `reason`
for audit only) so the edge can render one uniform error.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from candleviewer.auth.errors import (
    InviteConflict,
    InviteNotFound,
    InviteRejected,
    MfaCodeInvalid,
    MfaCodeReused,
    MfaEnrollmentNotFound,
    PasswordPolicyViolation,
)
from candleviewer.auth.hashing import DEFAULT_ARGON2_PARAMS, Hasher
from candleviewer.auth.invite_repository import InviteAudit, InviteRepository
from candleviewer.auth.metrics import (
    users_invites_created_total,
    users_invites_pending,
    users_invites_redeemed_total,
    users_invites_rejected_total,
)
from candleviewer.auth.models import (
    CreatedInvite,
    EnrollmentStart,
    InviteCreateRequest,
    InviteRecord,
    InviteRole,
    InviteView,
    MfaEnrollRequest,
    MfaEnrollResult,
    MfaMethodKind,
    UserStatus,
)
from candleviewer.auth.throttle import PerIpLoginThrottle

#: Ticket: invite valid for 72 hours.
INVITE_TTL = timedelta(hours=72)
#: After the token is consumed the invitee has this long to finish TOTP.
ENROLL_WINDOW = timedelta(minutes=30)
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 512
#: Local deny list (SR-028); a full breached-password corpus is later hardening.
_COMMON_PASSWORDS = frozenset(
    {
        "password1234",
        "passwordpassword",
        "123456789012",
        "qwertyuiop12",
        "letmein123456",
        "administrator",
        "candleviewer1",
        "iloveyou12345",
    }
)

Clock = Callable[[], datetime]
#: Write-ahead audit hook for a legacy-role downgrade: `(invite, stored_role)`.
DowngradeAudit = Callable[[InviteRecord, str], Awaitable[None]]
#: The refusals of a body that never reached a token lookup. Closed: the reason is a metric label.
InviteTamperReason = Literal["role_tamper", "identity_tamper"]


def _is_viewer_role(role: str) -> bool:
    """True only for the one role an invite may grant (#2109)."""
    return role == InviteRole.VIEWER.value


def _utc_now() -> datetime:
    return datetime.now(UTC)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def check_password_policy(password: str, *, username: str, email: str) -> None:
    """SR-028: >= 12 chars, not trivially patterned, not derived from identity."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyViolation(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordPolicyViolation("Password is too long")
    lowered = password.lower()
    if len(set(lowered)) < 4 or lowered in _COMMON_PASSWORDS:
        raise PasswordPolicyViolation("Password is too easy to guess")
    local = email.split("@", 1)[0].lower()
    if (len(username) >= 3 and username.lower() in lowered) or (
        len(local) >= 3 and local in lowered
    ):
        raise PasswordPolicyViolation("Password must not contain your username or email")


class _MfaLike(Protocol):
    async def enroll(
        self, user_id: str, request: MfaEnrollRequest, *, account_name: str
    ) -> MfaEnrollResult: ...

    async def confirm_enrollment(
        self, user_id: str, *, method_id: str, code: str
    ) -> tuple[MfaMethodKind, tuple[str, ...]]: ...


class InviteService:
    def __init__(
        self,
        repository: InviteRepository,
        hasher: Hasher,
        mfa: _MfaLike,
        *,
        clock: Clock = _utc_now,
        throttle: PerIpLoginThrottle | None = None,
    ) -> None:
        self._repo = repository
        self._hasher = hasher
        self._mfa = mfa
        self._clock = clock
        self._throttle = throttle or PerIpLoginThrottle(max_attempts=10, window_s=60.0)

    # -- owner side --------------------------------------------------------

    async def create(
        self, request: InviteCreateRequest, *, invited_by: uuid.UUID, audit: InviteAudit
    ) -> CreatedInvite:
        """`POST /users`. Raises `InviteConflict` (email/username taken) or what `audit` raises."""
        now = self._clock()
        token = secrets.token_urlsafe(32)
        user_id = uuid.uuid4()
        role = request.roles[0].value
        expires_at = now + INVITE_TTL
        created = await self._repo.create_user_with_invite(
            user_id=user_id,
            invite_id=uuid.uuid4(),
            email=request.email,
            username=request.username,
            display_name=request.display_name,
            role=role,
            placeholder_password_hash=_placeholder_hash(),
            invited_by=invited_by,
            token_hash=hash_token(token),
            expires_at=expires_at,
            audit=audit,
        )
        if not created:
            raise InviteConflict("email or username already in use")
        users_invites_created_total.labels(role).inc()
        users_invites_pending.inc()
        return CreatedInvite(
            user_id=user_id,
            username=request.username,
            email=request.email,
            display_name=request.display_name,
            role=role,
            token=token,
            expires_at=expires_at,
            created_at=now,
        )

    async def reissue(
        self, user_id: uuid.UUID, *, invited_by: uuid.UUID, audit: InviteAudit
    ) -> CreatedInvite:
        """Revokes every open invite of a still-`invited` user and mints a new
        one (same bound role). Raises `InviteNotFound`, and what `audit` raises."""
        now = self._clock()
        token = secrets.token_urlsafe(32)
        record = await self._repo.reissue(
            user_id,
            invite_id=uuid.uuid4(),
            token_hash=hash_token(token),
            invited_by=invited_by,
            expires_at=now + INVITE_TTL,
            now=now,
            audit=audit,
        )
        if record is None:
            raise InviteNotFound("no invited user with this id")
        users_invites_created_total.labels(record.role).inc()
        return CreatedInvite(
            user_id=record.user_id,
            username=record.username,
            email=record.email,
            display_name=record.display_name,
            role=record.role,
            token=token,
            expires_at=record.expires_at,
            created_at=record.created_at,
        )

    async def revoke(self, user_id: uuid.UUID, *, audit: InviteAudit) -> None:
        if not await self._repo.revoke_open(user_id, now=self._clock(), audit=audit):
            raise InviteNotFound("no pending invite for this user")
        users_invites_pending.dec()

    async def list_pending(self) -> tuple[InviteRecord, ...]:
        pending = await self._repo.list_pending(now=self._clock())
        users_invites_pending.set(len(pending))
        return pending

    # -- invitee side ------------------------------------------------------

    def now(self) -> datetime:
        return self._clock()

    def is_blocked(self, source_ip: str) -> bool:
        return self._throttle.is_blocked(source_ip)

    def refuse(self, reason: InviteTamperReason, *, source_ip: str) -> None:
        """Count and charge a refusal that never reached a token lookup (a body that claims a role
        or an identity): the same metric and per-source budget as every other refusal."""
        self._reject(reason, source_ip)

    async def inspect(self, token: str, *, source_ip: str) -> InviteView:
        """`GET /invites/{token}`: validates without consuming."""
        record = await self._find_open_or_reject(token, source_ip)
        return InviteView(
            display_name=record.display_name or record.username,
            role=record.role,
            expires_at=record.expires_at,
        )

    async def begin_redemption(
        self, token: str, *, password: str, source_ip: str
    ) -> EnrollmentStart:
        """Consume the token, park the password, start TOTP enrolment."""
        record = await self._find_open_or_reject(token, source_ip)
        check_password_policy(password, username=record.username, email=record.email)
        pending_hash = await self._hasher.hash(password, DEFAULT_ARGON2_PARAMS)
        consumed = await self._repo.consume(
            hash_token(token), now=self._clock(), pending_password_hash=pending_hash
        )
        if consumed is None:
            # Lost a race with another redemption, or revoked/expired since the lookup.
            raise self._reject(await self._classify(token), source_ip)
        enrol = await self._mfa.enroll(
            str(consumed.user_id),
            MfaEnrollRequest(method=MfaMethodKind.TOTP, label="Authenticator"),
            account_name=consumed.email,
        )
        return EnrollmentStart(
            method_id=enrol.method_id,
            otpauth_uri=enrol.otpauth_uri,
            secret_base32=enrol.secret_base32,
        )

    async def complete_redemption(
        self,
        token: str,
        *,
        method_id: str,
        code: str,
        source_ip: str,
        audit_downgrade: DowngradeAudit,
    ) -> tuple[InviteRecord, tuple[str, ...]]:
        """Verify the first TOTP code and activate the account. Returns the
        invite (role) and the one-time recovery codes."""
        record = await self._repo.find_by_token_hash(hash_token(token))
        now = self._clock()
        if record is None:
            raise self._reject("unknown", source_ip)
        if (
            record.consumed_at is None
            or record.revoked_at is not None
            or record.pending_password_hash is None
            or record.user_status is not UserStatus.INVITED
            or now > record.consumed_at + ENROLL_WINDOW
        ):
            raise self._reject(_reason_for(record, now), source_ip)
        try:
            _kind, recovery_codes = await self._mfa.confirm_enrollment(
                str(record.user_id), method_id=method_id, code=code
            )
        except (MfaCodeInvalid, MfaCodeReused, MfaEnrollmentNotFound) as exc:
            self._throttle.record_failure(source_ip)
            users_invites_rejected_total.labels("enrollment_invalid").inc()
            raise InviteRejected("enrollment_invalid") from exc
        pending_hash = record.pending_password_hash
        stored_role = record.role
        if not _is_viewer_role(stored_role):
            # Legacy invite minted before #2109: never grant more than viewer.
            # Audit first (C-2.9, write-ahead): if the audit write fails, nothing changes.
            # The hook is a required argument; a falsy value still fails closed.
            if audit_downgrade is None:
                raise InviteRejected("enrollment_invalid")
            await audit_downgrade(record, stored_role)
            await self._repo.downgrade_to_viewer(record.user_id)
            record = record.model_copy(
                update={"role": InviteRole.VIEWER.value, "downgraded_from": stored_role}
            )
        activated = await self._repo.activate_user(
            record.user_id,
            password_hash=pending_hash,
            algo_params=DEFAULT_ARGON2_PARAMS,
            now=now,
        )
        if not activated:
            raise self._reject("redeemed", source_ip)
        users_invites_redeemed_total.inc()
        users_invites_pending.dec()
        return record, recovery_codes

    # -- helpers -----------------------------------------------------------

    async def _classify(self, token: str) -> str:
        record = await self._repo.find_by_token_hash(hash_token(token))
        return "unknown" if record is None else _reason_for(record, self._clock())

    def _reject(self, reason: str, source_ip: str) -> InviteRejected:
        users_invites_rejected_total.labels(reason).inc()
        self._throttle.record_failure(source_ip)
        return InviteRejected(reason)

    async def _find_open_or_reject(self, token: str, source_ip: str) -> InviteRecord:
        record = await self._repo.find_by_token_hash(hash_token(token))
        if record is None:
            raise self._reject("unknown", source_ip)
        reason = _reason_for(record, self._clock())
        if reason != "open":
            raise self._reject(reason, source_ip)
        return record


def _placeholder_hash() -> str:
    # Satisfies `users_pwd_argon`; never verifies (the random tail is not a
    # valid Argon2id digest), so an invited user cannot sign in.
    return "$argon2id$v=19$m=65536,t=3,p=4$" + secrets.token_hex(16)


def _reason_for(record: InviteRecord, now: datetime) -> str:
    if record.revoked_at is not None:
        return "revoked"
    if record.consumed_at is not None:
        return "redeemed"
    if record.expires_at <= now:
        return "expired"
    return "open"
