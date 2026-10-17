"""Domain models for the auth module (M18): password sign-in (E09-S01).

Pydantic v2 request/result types for `POST /auth/login`, matching
`docs/plan/22-api-openapi.yaml` `LoginRequest`/`LoginResponse`/`TokenBundle`/
`MfaChallengeResponse`. The row-shaped `UserRecord` mirrors the columns
`0001_identity_rbac_sessions_mfa.py` created that this ticket's scope reads
or writes; it is a plain read/write DTO for `UserRepository`, not the
`User` API schema (which additionally carries roles/permissions assembled
elsewhere).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from candleviewer.domain.text import refuse_unstorable_text


class UserStatus(StrEnum):
    INVITED = "invited"
    ACTIVE = "active"
    DISABLED = "disabled"
    LOCKED = "locked"


class MfaMethodKind(StrEnum):
    TOTP = "totp"
    WEBAUTHN = "webauthn"
    RECOVERY_CODE = "recovery_code"


class LoginRequest(BaseModel):
    """`docs/plan/22-api-openapi.yaml` `LoginRequest`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    identifier: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=512)
    device_name: str | None = Field(default=None, max_length=120)

    @field_validator("identifier")
    @classmethod
    def _storable_identifier(cls, value: str) -> str:
        return refuse_unstorable_text(value)


class MfaVerifyRequest(BaseModel):
    """`docs/plan/22-api-openapi.yaml` `MfaVerifyRequest` (webauthn fields
    omitted — out of this ticket's scope)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mfa_token: str = Field(min_length=1)
    method: MfaMethodKind
    code: str = Field(pattern=r"^[0-9A-Za-z-]{6,32}$")


class MfaEnrollRequest(BaseModel):
    """`docs/plan/22-api-openapi.yaml` `MfaEnrollRequest` (`webauthn` is
    rejected — out of scope, see the ticket's "Out of scope")."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    method: MfaMethodKind
    label: str = Field(default="", max_length=60)


class MfaEnrollConfirmRequest(BaseModel):
    """`docs/plan/22-api-openapi.yaml` `MfaEnrollConfirmRequest`.

    `code` is the six-digit TOTP code, ASCII digits only: a looser check let other scripts'
    digits reach `verify_code` (#2605).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    method_id: uuid.UUID
    code: str = Field(pattern=r"^[0-9]{6}$")


class MfaRecoveryRequest(BaseModel):
    """`docs/plan/22-api-openapi.yaml` `/auth/mfa/recovery` inline request
    schema."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mfa_token: str = Field(min_length=1)
    recovery_code: str = Field(min_length=8, max_length=64)


class TokenBundle(BaseModel):
    """`docs/plan/22-api-openapi.yaml` `TokenBundle`.

    Real token minting (the `cv_refresh` cookie, JWT `access_token`
    contents, session-row creation) is E09-S03 scope ("Session lifetime,
    idle lock and revocation semantics" — this ticket's own "Out of scope").
    `LoginService` therefore never constructs one; the router only ever
    returns `MfaChallengeResponse` today, matching this story's own scope
    ("`/auth/mfa/verify` (E09-S02) completes it")."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    access_token: str
    token_type: str = "Bearer"  # noqa: S105 reason=RFC6750-scheme-name-not-a-secret owner=@CandleViewer/security review=2027-03-25
    expires_in: int
    refresh_expires_in: int | None = None
    refresh_token: str | None = None


class MfaChallengeResult(BaseModel):
    """Successful-credentials outcome: an MFA challenge was issued.

    `mfa_token` is opaque to the router — `LoginService` returns the raw
    value once, at issuance, and never re-derives or re-exposes it (only
    `mfa_token_hash` is persisted, mirroring `sessions.refresh_token_hash`'s
    pattern of never storing a bearer secret in the clear)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mfa_token: str
    methods: tuple[MfaMethodKind, ...]
    expires_in: int = 300


class UserRecord(BaseModel):
    """Row-shaped view of `users` columns this ticket's scope touches.

    Not the API-facing `User` schema (no roles/permissions — those come
    from `user_roles`/`role_permissions`, out of this story's scope).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: uuid.UUID
    username: str
    email: str
    password_hash: str
    password_algo_params: dict[str, int]
    status: UserStatus
    mfa_required: bool
    failed_login_count: int
    locked_until: datetime | None
    mfa_methods: tuple[MfaMethodKind, ...] = ()


class MfaMethodRecord(BaseModel):
    """Row-shaped view of `mfa_methods` columns E09-S02 touches.

    `secret_enc`/`secret_key_ref` are only ever populated for `kind=totp`
    (`mfa_totp_shape` CHECK) and are never serialised back to an HTTP
    response — see `auth/mfa_service.py`'s explicit note on this."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: uuid.UUID
    user_id: uuid.UUID
    kind: MfaMethodKind
    label: str = ""
    secret_enc: bytes | None = None
    secret_key_ref: str | None = None
    last_accepted_time_step: int | None = None
    confirmed_at: datetime | None = None
    last_used_at: datetime | None = None
    created_at: datetime
    revoked_at: datetime | None = None


class MfaChallengeRecord(BaseModel):
    """Row-shaped view of `mfa_challenges` (`purpose in
    ('login','step_up','enroll')`)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: uuid.UUID
    user_id: uuid.UUID
    mfa_token_hash: str
    purpose: str
    attempts: int
    satisfied_at: datetime | None
    expires_at: datetime
    created_at: datetime


class MfaEnrollResult(BaseModel):
    """`docs/plan/22-api-openapi.yaml` `MfaEnrollResponse`. `otpauth_uri` and
    `recovery_codes` are returned exactly once, at enrolment — never
    reconstructable afterwards (ticket "Secret handling": "returned to the
    client exactly once ... and never again")."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    method_id: uuid.UUID
    method: MfaMethodKind
    otpauth_uri: str | None = None
    secret_base32: str | None = None
    recovery_codes: tuple[str, ...] = ()


class MfaMethodView(BaseModel):
    """`docs/plan/22-api-openapi.yaml` `MfaMethod` — the API-facing,
    secret-free projection of `MfaMethodRecord` (SCR-112 security
    settings)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: uuid.UUID
    kind: MfaMethodKind
    label: str | None
    active: bool
    created_at: datetime
    last_used_at: datetime | None = None


class MfaVerifiedResult(BaseModel):
    """Successful `POST /auth/mfa/verify` or `/auth/mfa/recovery` outcome.

    Mirrors `MfaChallengeResult`'s own documented boundary: minting a real
    `TokenBundle`/session is E09-S03 scope, so `MfaService` returns this
    typed marker instead of fabricating an unsigned token (see
    `mfa_service.py`'s `verify`/`recovery` docstrings)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: uuid.UUID
    forced_totp_reenroll: bool = False


class RecoveryCodesRegenerated(BaseModel):
    """`POST /auth/mfa/recovery`-adjacent regeneration result (ticket
    "`POST /auth/mfa/recovery` regenerates codes ... and auditing
    `auth.recovery_codes_regenerated`") — shown exactly once, like
    enrolment's own codes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    recovery_codes: tuple[str, ...]


# -- E09-S03: session lifetime / idle lock / rotation -----------------------


class SessionRecord(BaseModel):
    """Row-shaped view of `sessions` columns `SessionService` touches
    (`21-database-schema.md` §3.1.4)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: uuid.UUID
    user_id: uuid.UUID
    refresh_token_hash: str
    access_token_jti: uuid.UUID | None
    issued_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    revoked_reason: str | None
    ip: str | None
    user_agent: str | None
    device_label: str | None
    is_electron: bool
    mfa_satisfied_at: datetime | None
    idle_timeout_s: int = 900
    #: E09-S04 step-up state, persisted on the row (migration 0009).
    step_up_elevations: dict[str, datetime] = Field(default_factory=dict)
    step_up_failures: int = 0
    readonly_until: datetime | None = None
    #: #2911: the owner's `users.status`, read with the row by `find_by_id` and
    #: `find_by_refresh_hash`; `None` from any other read, or when the user row is gone.
    #: `refresh` and `require_active` refuse on `None` (fail closed), so those reads must
    #: always populate it (pinned on Postgres by the #2911 integration tests).
    user_status: UserStatus | None = None

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def idle_deadline(self) -> datetime:
        return self.last_seen_at + timedelta(seconds=self.idle_timeout_s)

    def is_idle_locked(self, *, now: datetime) -> bool:
        return not self.is_revoked and self.idle_deadline() <= now

    def is_absolute_expired(self, *, now: datetime) -> bool:
        return self.expires_at <= now


class SessionView(BaseModel):
    """`docs/plan/22-api-openapi.yaml` `UserSession` — the API-facing,
    secret-free projection of `SessionRecord` for `GET /auth/sessions`
    (SCR-112)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: uuid.UUID
    device_name: str | None = None
    ip: str | None = None
    user_agent: str | None = None
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    current: bool = False


class SessionIntrospection(BaseModel):
    """`GET /auth/session` result the router projects into the OpenAPI
    `SessionInfo` shape (identity/roles/permissions live outside this
    module's scope — `auth` returns only what it owns: the session's own
    liveness state)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: uuid.UUID
    user_id: uuid.UUID
    issued_at: datetime
    expires_at: datetime
    idle_deadline: datetime
    mfa_satisfied_at: datetime | None = None


class MintedSession(BaseModel):
    """Result of minting a brand-new session (first login, or the head of
    a fresh rotation family with no predecessor). Carries the *raw*
    refresh token exactly once, at mint time — mirrors `MfaChallengeResult.
    mfa_token`'s "never re-derives or re-exposes it" pattern; only
    `refresh_token_hash` is ever persisted (`sessions.refresh_token_hash`,
    "SECRET: raw token never stored")."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: uuid.UUID
    access_token_jti: uuid.UUID
    #: Raw opaque access-token handle (ADR-0020 option 1), returned once; only
    #: a truncated SHA-256 of it is stored, in `sessions.access_token_jti`.
    access_token: str
    refresh_token: str
    issued_at: datetime
    expires_at: datetime


class RefreshOutcome(BaseModel):
    """`POST /auth/refresh` success outcome: the new session replacing the
    presented one (ticket "every refresh issues a new `sessions` row ...
    marks the old `revoked_reason='rotated'`, and links them")."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    minted: MintedSession
    previous_session_id: uuid.UUID


class InviteRole(StrEnum):
    """Roles an invite may carry: `viewer` only (owner decision #1778 AC, #2109).
    `owner` and `manager` are never granted by invitation; the owner promotes
    after activation."""

    VIEWER = "viewer"


class InviteCreateRequest(BaseModel):
    """`POST /users` body (`CreateUserRequest`). `account_access` must be
    empty: a new user starts with zero bindings (E27/E39 grant them)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    username: str = Field(min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9._-]+$")
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    display_name: str | None = Field(default=None, max_length=80)
    roles: tuple[InviteRole, ...] = Field(min_length=1, max_length=1)
    mfa_required: bool = True
    account_access: tuple[dict[str, object], ...] = Field(default=(), max_length=0)


class InviteRecord(BaseModel):
    """Row-shaped join of `user_invites` and its `users` row.

    `pending_password_hash` is a SECRET and is never serialised to a response."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: uuid.UUID
    user_id: uuid.UUID
    role: str
    username: str
    email: str
    display_name: str | None = None
    user_status: UserStatus = UserStatus.INVITED
    expires_at: datetime
    consumed_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime
    pending_password_hash: str | None = Field(default=None, repr=False)
    #: Set only when a legacy invite's non-viewer role was downgraded at redemption.
    downgraded_from: str | None = None


class InviteView(BaseModel):
    """`GET /invites/{token}`: the minimum needed to render the form."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    display_name: str
    role: str
    expires_at: datetime


class CreatedInvite(BaseModel):
    """Result of creating/re-issuing an invite. `token` is the raw one-time
    token: returned once to the owner, never stored or logged."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: uuid.UUID
    username: str
    email: str
    display_name: str | None
    role: str
    token: str = Field(repr=False)
    expires_at: datetime
    created_at: datetime


class EnrollmentStart(BaseModel):
    """Redemption step 1 result: the invitee's TOTP enrolment material (the
    invite token itself continues to identify the redemption)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    method_id: uuid.UUID
    otpauth_uri: str | None = None
    secret_base32: str | None = None
