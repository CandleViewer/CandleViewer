"""GENERATED FILE — DO NOT EDIT BY HAND.

Regenerate with `uv run --project services/api python scripts/generate_protocol_models.py`.
Source: docs/plan/22-api-openapi.yaml, via datamodel-code-generator.
"""

from __future__ import annotations

from ipaddress import IPv4Address, IPv6Address
from typing import Annotated, Any, Literal
from uuid import UUID

import re
from decimal import Decimal as _StdlibDecimal

from pydantic import (
    field_validator,
    PlainSerializer,
    BeforeValidator,
    AnyUrl,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    RootModel,
    SecretStr,
    StrictBool,
    StrictFloat,
    Strict,
)


_C6_DECIMAL = re.compile("^-?[0-9]+(\\.[0-9]+)?$")


def _c6_decimal(value: object) -> _StdlibDecimal:
    """Convention C6: a decimal on the wire is a string that fully matches the contract's
    `Decimal` pattern, checked before any conversion. Trusted code may pass a `Decimal`; the
    `Decimal` validation that follows refuses a non-finite one."""
    if isinstance(value, _StdlibDecimal):
        return value
    if isinstance(value, str) and _C6_DECIMAL.fullmatch(value):
        return _StdlibDecimal(value)
    raise ValueError(f"must be a decimal string matching {_C6_DECIMAL.pattern} (convention C6)")


Decimal = Annotated[
    _StdlibDecimal,
    PlainSerializer(lambda d: format(d, "f"), return_type=str),
    BeforeValidator(_c6_decimal),
]
"""Arbitrary-precision decimal (convention C6): serialises as a JSON/YAML
string on the wire, but is a real `decimal.Decimal` in Python — money and
size/price fields must never round-trip through float."""


def _json_integer(value: object) -> object:
    """JSON Schema's `integer` is a number with no fractional part, so `5.0` is `5`; anything else
    goes to the strict `int` check, which refuses a string, a boolean and `5.5` (#906 slice G2a)."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


JsonInt = Annotated[int, Strict(), BeforeValidator(_json_integer)]
"""A JSON Schema `integer`: an `int`, or a float with no fractional part, and nothing else."""


def _refuse_null(value: object) -> object:
    """An optional member the contract does not let be `null` (#906 slice G2b): left out it is
    `None`; sent as `null` it is refused, with a constant message that never carries the input."""
    if value is None:
        raise ValueError("null is not allowed: leave the member out")
    return value


def _take_null(value: object) -> object:
    """A model no request body reaches takes `null` where a request model it extends refuses it."""
    return value


class Symbol(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description="Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.",
            examples=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            pattern="^[A-Z0-9]{2,20}USDT$",
        ),
    ]


class Count(RootModel[JsonInt]):
    root: Annotated[JsonInt, Field(ge=0, le=2400)]


class TelemetryBucketCounts(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    counts: Annotated[list[Count], Field(max_length=9)]


class FrontendTelemetry(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    screen: Annotated[str, Field(description="Sitemap route id.", pattern="^R-[0-9]{3}$")]
    engine_version: Annotated[str, Field(pattern="^[0-9]{1,3}\\.[0-9]{1,3}\\.[0-9]{1,4}$")]
    fe_frame_time_ms: Annotated[
        TelemetryBucketCounts,
        Field(description="Edges ms: 4, 8, 12, 16, 20, 33, 50, 100, +Inf (9 slots)."),
    ]
    fe_ws_decode_ms: Annotated[
        TelemetryBucketCounts,
        Field(description="Edges ms: 0.1, 0.25, 0.5, 1, 2, 4, 5, 10, +Inf (9 slots)."),
    ]
    fe_dropped_frames_total: Annotated[JsonInt, Field(ge=0, le=2400)]
    fe_gpu_memory_mb: Annotated[StrictFloat | None, Field(ge=0.0, le=65536.0)] = None
    __null_refused = field_validator("fe_gpu_memory_mb", mode="before")(_refuse_null)


class ReconciliationPass(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    pass_id: UUID
    exchange_account_id: UUID
    trigger: Literal["manual"]
    joined: Annotated[
        StrictBool,
        Field(description="True when a pass already running answered, so no second pass started."),
    ]


class ReconciliationResolveRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    reason: Annotated[
        str,
        Field(
            description="Why the operator resolves it, written to the `oms.reconcile` record; human text that must carry no secret.\n",
            max_length=280,
            min_length=3,
        ),
    ]


class ReconciliationResolved(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    exchange_account_id: UUID
    resolved: Annotated[
        Literal["stale_lockout", "divergent"],
        Field(description="The reconciliation job's state the operator's decision left (B19)."),
    ]
    resolved_at: AwareDatetime


class Error(BaseModel):
    field: str | None = None
    rule: str | None = None
    message: str | None = None
    symbol: Annotated[
        str | None,
        Field(
            description="The instrument whose exchange limit the value breaks, for a rule that checks one.",
            examples=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            pattern="^[A-Z0-9]{2,20}USDT$",
        ),
    ] = None
    limit: Annotated[
        str | None,
        Field(
            description="The limit the value breaks, in the member's own unit.",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None


class Exchange(BaseModel):
    ret_code: JsonInt | None = None
    ret_msg: str | None = None
    endpoint: str | None = None
    request_id: str | None = None


class Problem(BaseModel):
    type: Annotated[AnyUrl, Field(description="`https://candleviewer.local/errors/{code}`.")]
    title: str
    status: Annotated[JsonInt, Field(ge=400, le=599)]
    detail: str | None = None
    instance: Annotated[
        str | None,
        Field(
            description="Correlation id, `urn:cv:req:{uuid}`; matches the `X-Correlation-Id` header and the audit entry."
        ),
    ] = None
    code: Annotated[
        str, Field(description="Stable machine-readable error code from `x-error-codes`.")
    ]
    errors: Annotated[list[Error] | None, Field(description="Field-level validation failures.")] = (
        None
    )
    required_permissions: list[str] | None = None
    retry_after_seconds: JsonInt | None = None
    idle_locked_at: Annotated[
        AwareDatetime | None,
        Field(
            description="`session_idle_locked` only: the session's `idle_deadline`, which is when it idle-locked, unless `POST /auth/lock` locked it first (the lock moment is then the `auth.session_locked` audit row's time), so it may be later than `server_time`. Read the problem code or `session.locked`, never this time, to tell that a session is locked.\n"
        ),
    ] = None
    revoked_reason: Annotated[
        Literal["expired", "unlock_attempts_exceeded", "revoked"] | None,
        Field(
            description="`session_revoked` only. `expired`: the 12 h absolute lifetime elapsed. `unlock_attempts_exceeded`: five consecutive wrong unlock passwords. `revoked`: any other revocation; the specific cause is not disclosed.\n"
        ),
    ] = None
    exchange: Annotated[
        Exchange | None, Field(description="Present when the failure originated at Bybit.")
    ] = None
    action_class: Annotated[
        str | None,
        Field(
            description="`step_up_required` only: the step-up class the refused request needs, one of the `action_class` values of `POST /auth/step-up`.\n"
        ),
    ] = None
    challenge_id: Annotated[
        UUID | None,
        Field(
            description="`step_up_required` only: the challenge this refusal issued (#2304), a random UUIDv4 scoped to the issuing session, so a value from another session is unknown. One challenge is live per session; a newer refusal supersedes it. Send it as `challenge_id` to `POST /auth/step-up`, which requires it while the challenge is live, whatever the class; a step-up for a no-grace class must send it.\n"
        ),
    ] = None
    challenge_expires_at: Annotated[
        AwareDatetime | None,
        Field(
            description="`step_up_required` only: when the challenge expires, 5 minutes after issue (server clock). The client drops the held request then, without sending it.\n"
        ),
    ] = None
    action_summary: Annotated[
        str | None,
        Field(
            description="`step_up_required` only: server-composed text naming exactly what the refused request would execute, built from the validated request (for example \"Release kill switch, scope global\"). It comes from a fixed per-route template. Request values appear in it only as validated enum values (bare) or as identifiers and server-resolved labels (quoted, each bounded by its own schema's `maxLength` or `format`), never as free text such as a `reason`, and never as key material, a password, a token, a TOTP or recovery code or any field the redaction deny-list names (C-12.6). A label alone never identifies an account or a rule, because labels can be renamed and need not be unique: each account named in it is followed by its `environment` and `exchange_uid` and each rule by the environments its scope includes, rendered bare (for example \"Release kill switch, accounts 'demo-1' (demo, UID 1001234)\" or \"Arm rule 'Break-even' (live)\"); an account's `environment` and `exchange_uid` never change after it is registered. Naming a rule this way is provisional: two rules can share a label and environments, and `rules:write` can rename a rule and change its scope and its active version without a step-up, so the route slice of #2304 decides, before any rule template ships, whether a rule is also named by its bound accounts and whether the grant that arms it is also bound to its active version. Before a label is quoted, an apostrophe or a backslash in it is preceded by a backslash, and every character outside printable ASCII (U+0020 to U+007E) is written as `\\u{`, its code point in upper-case hex zero-padded to four digits, and `}` (U+000A becomes `\\u{000A}`, U+202E becomes `\\u{202E}` and U+1F600 becomes `\\u{1F600}`). That covers line breaks and other control characters, bidi embedding, override and isolate marks and look-alike quotation marks, so the quotes bound the label: the label `demo-1' (demo)` is quoted as `'demo-1\\' (demo)'`. The step-up dialog shows it verbatim as its accessible description; a client never composes its own.\n"
        ),
    ] = None
    target: Annotated[
        str | None,
        Field(
            description="`step_up_required` only: the exact, case-sensitive text a typed confirmation must equal when the action asks for one (for example the account name), else null. Like `action_summary`, it is an identifier or a server-resolved label of the validated request, never free text or credential material. It is a label only when no other object of its kind that the caller can see has that label, compared case-insensitively, and the label is printable ASCII; otherwise it is the object's identifier.\n"
        ),
    ] = None
    step_up_reason: Annotated[
        str | None,
        Field(
            description='`step_up_required` only: the server-composed sentence saying why this action needs a fresh step-up, the line the step-up dialog (SCR-006, E09-D06) shows under the action, shown verbatim; the client adds no prefix and never composes its own. Present only when `action_class` is `live_enablement` or `killswitch`, carrying SCR-006\'s no-grace sentence verbatim: "Live enablement and kill-switch disable always need a fresh code, even right after a recent step-up." Omitted for every other class. Fixed text, never built from the request, so it carries no request value, label or credential material. Optional, additive (C-6.3).\n'
        ),
    ] = None
    failures_remaining: Annotated[
        JsonInt | None,
        Field(
            description="`mfa_invalid` from `POST /auth/step-up` only: how many more step-up attempts this session has before a failure downgrades it to read-only, 2 after its first consecutive failure and 1 after its second; the next failure is the third and answers `403 session_read_only` instead, without this member. It counts this session's own consecutive step-up failures only, the count stored on its session row: never another session's, never the account's sign-in lockout counter, so it reveals nothing beyond what this session has itself been told. A successful step-up starts the count again. Optional, additive (C-6.3).\n",
            ge=1,
            le=2,
        ),
    ] = None
    recording_started_at: Annotated[
        AwareDatetime | None,
        Field(
            description="`no_data_recorded` from `GET /market/bars` only: when recording of the symbol's trade tape began, so the client can offer the first recorded window; null when nothing was ever recorded for the symbol. Optional, additive (C-6.3).\n"
        ),
    ] = None


class PageMeta(BaseModel):
    next_cursor: str | None = None
    has_more: StrictBool
    count: Annotated[
        JsonInt,
        Field(
            description="Items in this page (not the total, which is never computed for unbounded sets)."
        ),
    ]
    total: Annotated[
        JsonInt | None, Field(description="Present only where a cheap exact count exists.")
    ] = None


class Page(BaseModel):
    items: list[Any]
    meta: PageMeta


class InstrumentsPageMeta(PageMeta):
    cache_age_s: Annotated[
        StrictFloat, Field(description="Seconds since this snapshot was last fetched from Bybit.")
    ]
    stale_since: Annotated[
        AwareDatetime | None,
        Field(description="When the cache started missing its refresh cadence; null if fresh."),
    ]


class CoverageHole(BaseModel):
    start_us: Annotated[JsonInt, Field(description="Gap start, exchange epoch microseconds.")]
    end_us: Annotated[JsonInt, Field(description="Gap end, exchange epoch microseconds.")]


class DataMeta(PageMeta):
    sources: Annotated[
        list[Literal["questdb", "parquet", "postgres", "exchange_rest", "memory", "tape"]] | None,
        Field(
            description="Tiers whose rows are in this response (provenance, 24 §2): `tape` = bars built locally from the recorded trade tape; `questdb` = exchange-kline rows in the hot tier; `parquet` = cold tier; `exchange_rest` = rows just backfilled from Bybit."
        ),
    ] = None
    recording_started_at: AwareDatetime | None = None
    generated_at: AwareDatetime | None = None
    coverage_holes: Annotated[
        list[CoverageHole] | None,
        Field(
            description='Requested-range gaps the local cache has no bars for yet (QA defect #1622 blocker 1 / E08-S06 "Cache hit" scenario — `GET /market/klines` is cache-only until a live `KlineFetcher` lands, so it reports holes here instead of silently pretending the exchange was consulted). On `/market/bars` and `/market/klines` a range of the window the server cannot serve from its store is listed here too, so a missing range is named, never silently absent (#5396).'
        ),
    ] = None


class KlineInterval(
    RootModel[Literal["1", "3", "5", "15", "30", "60", "120", "240", "360", "720", "D", "W", "M"]]
):
    root: Annotated[
        Literal["1", "3", "5", "15", "30", "60", "120", "240", "360", "720", "D", "W", "M"],
        Field(description="Bybit-compatible interval codes (minutes, or D/W/M)."),
    ]


class LoginRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    identifier: Annotated[
        str, Field(description="Username or email.", max_length=254, min_length=1)
    ]
    password: Annotated[SecretStr, Field(max_length=512, min_length=1)]
    device_name: Annotated[
        str | None, Field(description="Shown in the session list.", max_length=120)
    ] = None
    __null_refused = field_validator("device_name", mode="before")(_refuse_null)


class TokenBundle(BaseModel):
    access_token: str
    token_type: Literal["Bearer"]
    expires_in: Annotated[JsonInt, Field(description="Access-token lifetime in seconds (600).")]
    refresh_expires_in: Annotated[
        JsonInt | None,
        Field(
            description='Refresh-token lifetime in seconds (2592000). For an enrolment-only session it counts down to that session\'s absolute expiry, at most 900 (see "Enrolment-only session").\n'
        ),
    ] = None
    refresh_token: Annotated[
        str | None,
        Field(
            description="Returned only to non-cookie clients that set `cookie_auth:false` on login."
        ),
    ] = None


class MfaChallengeResponse(BaseModel):
    status: Literal["mfa_required"]
    mfa_token: str
    methods: list[Literal["totp", "webauthn", "recovery_code"]]
    expires_in: JsonInt
    webauthn_challenge: dict[str, Any] | None = None


class MfaVerifyRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    mfa_token: str
    method: Literal["totp", "webauthn", "recovery_code"]
    code: Annotated[
        str | None,
        Field(description="TOTP digits or a recovery code.", pattern="^[0-9A-Za-z-]{6,32}$"),
    ] = None
    webauthn_assertion: dict[str, Any] | None = None
    remember_device_days: Annotated[JsonInt, Field(ge=0, le=30)] = 0
    __null_refused = field_validator("code", "webauthn_assertion", mode="before")(_refuse_null)


class MfaEnrollRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    method: Literal["totp", "webauthn"]
    label: Annotated[str | None, Field(max_length=60)] = None
    __null_refused = field_validator("label", mode="before")(_refuse_null)


class MfaEnrollResponse(BaseModel):
    method_id: UUID
    method: Literal["totp", "webauthn", "recovery_code"]
    otpauth_uri: str | None = None
    webauthn_creation_options: dict[str, Any] | None = None


class MfaEnrollConfirmRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    method_id: UUID
    code: str | None = None
    webauthn_attestation: dict[str, Any] | None = None
    __null_refused = field_validator("code", "webauthn_attestation", mode="before")(_refuse_null)


class MfaMethod(BaseModel):
    id: UUID | None = None
    kind: Literal["totp", "webauthn", "recovery_code"] | None = None
    label: str | None = None
    active: StrictBool | None = None
    created_at: AwareDatetime | None = None
    last_used_at: AwareDatetime | None = None


class RefreshRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    refresh_token: Annotated[
        str | None, Field(description="Only for clients that cannot use cookies.")
    ] = None
    __null_refused = field_validator("refresh_token", mode="before")(_refuse_null)


class Argon2Params(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    m: Annotated[JsonInt, Field(description="Memory cost in KiB (65536 = 64 MiB).", ge=1)]
    t: Annotated[JsonInt, Field(description="Time cost (passes over memory).", ge=1)]
    p: Annotated[JsonInt, Field(description="Parallelism (lanes).", ge=1)]


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    current_password: Annotated[SecretStr, Field(max_length=512, min_length=1)]
    new_password: Annotated[SecretStr, Field(max_length=512, min_length=1)]


class ChangePasswordResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    status: Literal["password_changed"]
    tokens: TokenBundle


class UnlockRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    password: Annotated[SecretStr, Field(max_length=512, min_length=1)]


class SessionState(BaseModel):
    id: Annotated[
        UUID, Field(description="Server-side session id (`sid`); `POST /auth/refresh` rotates it.")
    ]
    issued_at: Annotated[
        AwareDatetime,
        Field(
            description="When this session id was issued (sign-in, or the refresh that rotated it)."
        ),
    ]
    expires_at: Annotated[
        AwareDatetime,
        Field(
            description="End of the 12 h absolute lifetime. Refresh, extend, lock and unlock never move it.\n"
        ),
    ]
    idle_deadline: Annotated[
        AwareDatetime,
        Field(
            description="When the idle lock engages unless activity is recorded first (`last_seen_at + idle_timeout_s`). Only `POST /auth/session/extend` and `POST /auth/unlock` move it; `POST /auth/refresh` carries it over unchanged. Once `locked`, the moment it locked, unless `POST /auth/lock` locked the session first: lock never moves it, and the lock moment is the `auth.session_locked` audit row's time. So after a lock by request it may be later than `server_time`: read `session.locked`, never this time, to tell that the session is locked.\n"
        ),
    ]
    idle_timeout_s: Annotated[
        JsonInt,
        Field(
            description="Idle timeout of this session in seconds (per user, 5 to 60 minutes).",
            ge=300,
            le=3600,
        ),
    ]
    locked: Annotated[
        StrictBool,
        Field(
            description="True once `idle_deadline` has passed or `POST /auth/lock` locked the session; only `POST /auth/unlock` clears it.\n"
        ),
    ]


class SessionExtendResponse(BaseModel):
    session: SessionState
    server_time: AwareDatetime


class UserSession(BaseModel):
    id: UUID | None = None
    device_name: str | None = None
    ip: str | None = None
    user_agent: str | None = None
    created_at: AwareDatetime | None = None
    last_seen_at: AwareDatetime | None = None
    expires_at: AwareDatetime | None = None
    current: StrictBool | None = None


class User(BaseModel):
    id: UUID
    username: str
    email: Annotated[
        str,
        Field(
            description="The address as stored, not a verified mailbox. The pattern is the database check `users_email_fmt` (`position('@' in email) > 1`): an `@` that is not the first character, and nothing about the rest. A special-use domain such as `.local` is accepted (an operator-set address like `owner@candleviewer.local` is valid data), so this is a pattern and not `format: email`.\n",
            pattern="^[^@]+@",
        ),
    ]
    display_name: str | None = None
    roles: list[Literal["owner", "manager", "viewer"]]
    status: Literal["invited", "active", "disabled", "locked"]
    mfa_enabled: Annotated[
        StrictBool | None,
        Field(
            description="The user has at least one confirmed, unrevoked MFA method. Always present in `AuthenticatedResponse` and `SessionInfo`.\n"
        ),
    ] = None
    mfa_required: Annotated[
        StrictBool | None,
        Field(
            description='MFA is mandatory for this user; C-12.2 requires it for every user. Always present in `AuthenticatedResponse` and `SessionInfo`. While `mfa_enabled` is false, every session of the user is enrolment-only (see "Enrolment-only session"): clients test exactly `mfa_required === true && mfa_enabled === false`.\n'
        ),
    ] = None
    last_login_at: AwareDatetime | None = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None


class UserWithInvite(User):
    invite_url: Annotated[
        str | None, Field(description="One-time link, valid 72 h. Shown once.")
    ] = None
    invite_expires_at: AwareDatetime | None = None


class UpdateUserRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    display_name: Annotated[str | None, Field(max_length=80)] = None
    status: Annotated[
        Literal["active", "disabled"] | None,
        Field(description="`invited` and `locked` are not settable (`400 validation_failed`)."),
    ] = None
    roles: Annotated[list[Literal["owner", "manager", "viewer"]] | None, Field(min_length=1)] = None
    mfa_required: Annotated[
        Literal[True] | None,
        Field(
            description="TOTP is mandatory for every user (C-12.2); `false` is `400 validation_failed`."
        ),
    ] = None
    __null_refused = field_validator("status", "roles", "mfa_required", mode="before")(_refuse_null)


class Role(BaseModel):
    id: UUID | None = None
    name: Literal["owner", "manager", "viewer"] | None = None
    description: str | None = None
    permissions: list[str] | None = None
    user_count: JsonInt | None = None


class AccountAccessGrantInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    exchange_account_id: UUID
    level: Annotated[Literal["read", "trade"], Field(description="`trade` implies `read`.")]


class AccountAccessGrant(BaseModel):
    exchange_account_id: UUID
    level: Annotated[Literal["read", "trade"], Field(description="`trade` implies `read`.")]
    account_label: str | None = None
    environment: Annotated[
        Literal["live", "demo", "testnet"] | None,
        Field(
            description="Structural environment selector (arch P9). Mirrors the Postgres type `exchange_env`."
        ),
    ] = None
    granted_at: AwareDatetime | None = None
    granted_by: UUID | None = None


class AccountHealth(BaseModel):
    state: Literal["healthy", "degraded", "down"]
    reason: Annotated[
        Literal["ws_heartbeat", "rest_only", "ws_silent", "no_success", "never_connected"],
        Field(
            description="Closed set of machine codes the client renders as text, never exchange-supplied text: `ws_heartbeat`, `rest_only` (REST polling replaced the private WS), `ws_silent` (the WS heartbeat lapsed and there has been no REST success within the down window either), `no_success` (nothing for the 30 s down window), `never_connected`.\n"
        ),
    ]
    heartbeat_age_ms: Annotated[
        JsonInt | None,
        Field(
            description="Milliseconds since the last authenticated private-WS heartbeat; `null` before the first.",
            ge=0,
        ),
    ]
    rest_only: Annotated[
        StrictBool,
        Field(
            description="True while `degraded`; rule actions that need sub-second reaction are flagged."
        ),
    ]
    changed_at: Annotated[
        AwareDatetime,
        Field(
            description="When `state` last changed; a new value marks a discrete transition to announce."
        ),
    ]


class WalletBalance(BaseModel):
    is_paper: Annotated[
        StrictBool,
        Field(
            description="True when the paper matcher produced this record rather than the exchange. Orthogonal to `environment` (24-internal-schemas.md section 1.2)."
        ),
    ] = False
    coin: Annotated[str | None, Field(examples=["USDT"])] = None
    equity: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    wallet_balance: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    available_balance: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    unrealised_pnl: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    account_im_rate: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    account_mm_rate: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    updated_at: AwareDatetime | None = None


class CreateExchangeAccountRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    exchange: Annotated[
        Literal["bybit"],
        Field(
            description="Exchange identifier. v1 supports Bybit only (locked scope: Bybit USDT linear perpetuals).\nMirrors the Postgres type `exchange_code`; the adapter abstraction\n(`24-internal-schemas.md`) exists so a second value can be added without a breaking change.\n"
        ),
    ]
    environment: Annotated[
        Literal["live", "demo", "testnet"],
        Field(
            description="Structural environment selector (arch P9). Mirrors the Postgres type `exchange_env`."
        ),
    ]
    kind: Literal["main", "sub"]
    label: Annotated[str, Field(max_length=80, min_length=1)]
    exchange_uid: Annotated[str, Field(pattern="^[0-9]{4,20}$")]
    parent_account_id: Annotated[UUID | None, Field(description="Required when `kind=sub`.")] = None


class UpdateExchangeAccountRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    label: Annotated[str | None, Field(max_length=80, min_length=1)] = None
    enabled: Annotated[
        StrictBool | None,
        Field(
            description="`false` disables the account; with open exposure it needs the `open_exposure` query choice."
        ),
    ] = None
    active_profile_id: Annotated[
        UUID | None,
        Field(
            description="Not honoured: a value sent is ignored, since an account's default profile moves only through the default binding's own operation (`setAccountDefaultProfile`); this member is dropped at E27's next contract touch (#895).\n"
        ),
    ] = None
    position_mode: Literal["one_way", "hedge"] | None = None
    margin_mode: Literal["cross", "isolated", "portfolio"] | None = None
    __null_refused = field_validator("label", "enabled", "position_mode", "margin_mode", mode="before")(_refuse_null)


class OpenExposureChoice(RootModel[Literal["leave_positions", "flatten_first"]]):
    root: Annotated[
        Literal["leave_positions", "flatten_first"],
        Field(
            description="How an action that ends CandleViewer's management of an account treats its open exposure (SR-E27-07); see `components.parameters.OpenExposure`."
        ),
    ]


class AssignedUser(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    user_id: UUID
    username: str
    level: Literal["read", "trade"]


class ArmedRule(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    rule_id: UUID
    name: str


class ApiKey(BaseModel):
    id: UUID
    exchange_account_id: UUID
    key_id_masked: Annotated[
        str,
        Field(
            description="At most the last 4 characters of the key id: `...` plus `key_id_last4` (SR-E27-03). The rest is never stored in clear.",
            pattern="^\\.\\.\\.[A-Za-z0-9]{4}$",
        ),
    ]
    label: Annotated[str | None, Field(max_length=80)] = None
    status: Annotated[
        Literal["pending", "active", "rotating", "revoked", "expired", "invalid"],
        Field(
            description="Only `active` and `rotating` keys are signable (`21-database-schema.md` §3.2.3a). `invalid`: the exchange rejected the key's credential (exchange refusal codes `10003` or `10004`), which `24-internal-schemas.md` §8.6 answers by marking the key `invalid`; it is not signable.\n"
        ),
    ]
    read_only: StrictBool | None = None
    expires_at: AwareDatetime | None = None
    created_at: AwareDatetime | None = None
    last_verified_at: AwareDatetime | None = None
    rotation_due_at: Annotated[
        AwareDatetime | None,
        Field(
            description="`created_at` plus the deployment's key-rotation policy (default 90 days), never the exchange-reported `expires_at`; `null` unless the key is `active`.\n"
        ),
    ] = None
    rotation_state: Annotated[
        Literal["ok", "warn", "overdue"] | None,
        Field(
            description="`warn` inside the warning window (default 14 days), `overdue` past `rotation_due_at`. Age alone never disables a key. `null` unless the key is `active`.\n"
        ),
    ] = None


class CreateApiKeyRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    api_key: Annotated[SecretStr, Field(max_length=128, min_length=8)]
    api_secret: Annotated[SecretStr, Field(max_length=256, min_length=8)]
    label: Annotated[str | None, Field(max_length=80)] = None
    read_only: StrictBool = False
    expected_uid: Annotated[
        str | None,
        Field(description="Must equal the account's `exchange_uid`; mismatch is rejected."),
    ] = None
    __null_refused = field_validator("label", "expected_uid", mode="before")(_refuse_null)


class Permission(RootModel[str]):
    root: Annotated[str, Field(pattern="^[A-Za-z][A-Za-z0-9]{0,63}$")]


class IpWhitelistItem(RootModel[str]):
    root: Annotated[str, Field(max_length=49, pattern="^([*]|[0-9A-Fa-f:.]{2,45}(/[0-9]{1,3})?)$")]


class KeyVerificationNotRead(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    passed: Literal[False]
    egress_ip: Annotated[
        IPv4Address | IPv6Address | None,
        Field(
            description="The deployment's configured egress IP (`CV_EGRESS_IP`), the one address a key's IP whitelist may hold; `null` while none is configured. It comes from configuration, never from a request header. It is the address the Owner adds to the key's whitelist at the exchange when the exchange refused the egress IP or `ip_whitelist_matches_egress` is false (US-ACCT-003). Confidential: served only to a caller holding `keys:manage` or `keys:read`, and never written to an audit record or used as a metric label.\n"
        ),
    ] = None


class KeyExchangeProblem(Problem):
    exchange: Annotated[
        Exchange | None, Field(description="Present when the failure originated at Bybit.")
    ] = None


class OrderExchangeProblem(Problem):
    exchange: Annotated[
        Exchange | None, Field(description="Present when the failure originated at Bybit.")
    ] = None


class RotateApiKeyRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    api_key: SecretStr
    api_secret: SecretStr
    label: Annotated[str | None, Field(max_length=80)] = None
    __null_refused = field_validator("label", mode="before")(_refuse_null)


class Rest(BaseModel):
    ok: StrictBool | None = None
    latency_ms: JsonInt | None = None
    ret_code: JsonInt | None = None
    error: (
        Literal[
            "auth_error",
            "permission_denied",
            "ip_not_allowed",
            "clock_drift",
            "rate_limited",
            "service_unavailable",
            "transport_error",
            "timeout",
            "exchange_unknown",
            "vault_refused",
        ]
        | None
    ) = None


class Websocket(BaseModel):
    ok: StrictBool | None = None
    latency_ms: JsonInt | None = None
    error: (
        Literal[
            "auth_error",
            "permission_denied",
            "ip_not_allowed",
            "clock_drift",
            "rate_limited",
            "service_unavailable",
            "transport_error",
            "timeout",
            "exchange_unknown",
            "vault_refused",
        ]
        | None
    ) = None


class Offset(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    unit: Annotated[
        Literal["ticks", "percent", "r_multiple", "atr", "price"],
        Field(
            description='Unit in which a stop/target distance is expressed.\n\n**Persistence contract.** The Postgres type `offset_unit` holds\n`ticks | percent | r_multiple | atr`. The API additionally accepts `price`, meaning\n"`value` is an absolute price level, not a distance"; the OMS converts it to a\n`ticks` distance from the resolved entry/reference price before persisting, so\n`account_profiles.sl_offset_unit` / `tp_offset_unit` never store `price`.\nContract test `enum_parity_offset_unit` asserts this.\n'
        ),
    ]
    value: Annotated[
        str,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ]
    atr_period: Annotated[JsonInt, Field(description="Used when `unit=atr`.", ge=2, le=200)] = 14
    atr_bar_type: (
        Literal["time", "tick", "volume", "range", "delta", "renko", "pnf", "heikin_ashi"] | None
    ) = None
    atr_param: Annotated[str | None, Field(max_length=24)] = None
    __null_refused = field_validator("atr_bar_type", "atr_param", mode="before")(_refuse_null)


class Sizing(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    mode: Annotated[
        Literal[
            "fixed_qty", "fixed_notional", "pct_equity", "risk_based", "pct_position", "profile"
        ],
        Field(
            description="How a request expresses order size.\n\n**Persistence contract.** The Postgres type `sizing_mode`\n(`21-database-schema.md` §Enums) holds only the four *resolved* modes\n`fixed_qty | fixed_notional | pct_equity | risk_based`. The two extra API values are\n**request-time sugar that never reaches the database**; the OMS resolves them before\nany row is written, and `orders.requested_qty_mode` / `account_profiles.sizing_mode`\ntherefore always contain a resolved value:\n\n| API value | Resolution | Stored as |\n|---|---|---|\n| `pct_position` | `pct` % of the *current open position* qty on that symbol/account (scale-out, flatten-partial). Rejected with `validation_failed` if no position is open. `placeOrder` refuses it (`sizing_mode_unsupported`) until the position read reaches the size step (an interim). | `fixed_qty` |\n| `profile` | Inherit the active `AccountProfile.profile.sizing` block verbatim. | whatever the profile's own mode resolves to |\n\nContract test `enum_parity_sizing_mode` asserts (a) the DB enum equals this enum minus\n`x-db-enum-superset`, and (b) no persisted row ever holds a superset value.\n"
        ),
    ]
    qty: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    notional_usd: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    pct: Annotated[
        str | None,
        Field(
            description="Percent of equity (`pct_equity`) or of the position (`pct_position`).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    risk_per_trade_usd: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    risk_per_trade_pct: Annotated[
        str | None,
        Field(
            description="Percent of equity lost at the stop (`risk_based`): `0.5` is 0.5 %, at most 100.",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    max_notional_usd: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    round_to_lot: StrictBool = True
    __null_refused = field_validator("qty", "notional_usd", "pct", "risk_per_trade_usd", "risk_per_trade_pct", "max_notional_usd", mode="before")(_refuse_null)


class RiskCaps(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    max_daily_loss_usd: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    max_daily_loss_pct: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    max_open_positions: Annotated[JsonInt | None, Field(ge=0, le=100)] = None
    max_position_notional_usd: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    max_orders_per_minute: Annotated[JsonInt | None, Field(ge=1, le=600)] = None
    max_consecutive_losses: Annotated[JsonInt | None, Field(ge=1, le=50)] = None
    lockout_minutes_after_breach: Annotated[JsonInt, Field(ge=0, le=1440)] = 60


class ProfileSymbolPattern(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description="A listed USDT linear perpetual (`BTCUSDT`), or an anchored suffix pattern (`*USDT`) that is stored as written and matched against the listed, trading linear USDT perpetuals each time it is evaluated (SR-E28-06). A bare `*` is refused.\n",
            examples=["BTCUSDT", "*USDT"],
            pattern="^(\\*[A-Z0-9]{0,16}|[A-Z0-9]{2,16})USDT$",
        ),
    ]


class ProfileSizing(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    mode: Annotated[
        Literal["fixed_qty", "fixed_notional", "pct_equity", "risk_based"],
        Field(
            description="A profile's sizing mode, the Postgres type `sizing_mode` exactly: a profile never holds `SizingMode`'s request-time values `pct_position` and `profile`.\n"
        ),
    ]
    qty: Annotated[Decimal | None, Field(description="Contracts per order, above 0.")] = None
    notional_usd: Annotated[Decimal | None, Field(description="USDT per order, above 0.")] = None
    pct: Annotated[
        Decimal | None, Field(description="Percent of equity per order, above 0 and at most 100.")
    ] = None
    risk_per_trade_pct: Annotated[
        Decimal | None,
        Field(description="Percent of equity lost at the stop, above 0 and at most 100."),
    ] = None
    risk_per_trade_usd: Annotated[
        Decimal | None, Field(description="USDT lost at the stop, above 0.")
    ] = None
    min_leg_notional_usd: Annotated[
        str,
        Field(
            description="A leg below this notional, in USDT, is skipped rather than rejected; at least 0.",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = "0"


class ProfileStopLoss(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    unit: Annotated[
        Literal["ticks", "percent", "atr"],
        Field(
            description="A profile stop's unit: `offset_unit` without `r_multiple` (`ap_sl_unit`), because the stop defines R (24-internal-schemas.md section 9.3.1), and never `price`.\n"
        ),
    ]
    value: Annotated[
        str,
        Field(
            description="The distance, above 0, in whole ticks or in percent (1.5 is 1.5 %).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = "10"
    atr_period: Annotated[JsonInt, Field(ge=2, le=200)] = 14
    atr_multiple: Annotated[
        str,
        Field(
            description="The multiple of the ATR, above 0.",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = "2"
    fallback_pct: Annotated[
        str,
        Field(
            description="The stop while the ATR is unavailable, in percent, above 0 and below 100.",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = "2"


class ProfileTakeProfit(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    unit: Annotated[
        Literal["ticks", "percent", "r_multiple", "atr"],
        Field(
            description="A profile take-profit's unit, the Postgres type `offset_unit` exactly; never `price`."
        ),
    ]
    value: Annotated[
        str,
        Field(
            description="The distance, above 0, in `unit`; `r_multiple` is a multiple of the stop distance.",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ]


class ProfileTakeProfitRung(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    qty_pct: Annotated[
        str,
        Field(
            description="Percent of the leg's filled size, above 0 and at most 100.",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ]
    r: Annotated[
        str,
        Field(
            description="The target, in R multiples of the stop distance, above 0.",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ]


class ProfileRiskCaps(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    max_position_notional_usd: Annotated[Decimal | None, Field(description="USDT, above 0.")] = None
    max_position_pct_equity: Annotated[
        Decimal | None, Field(description="Percent of equity, above 0 and at most 100.")
    ] = None
    max_daily_loss_usd: Annotated[
        Decimal | None, Field(description="USDT lost in a day, above 0.")
    ] = None
    max_daily_loss_pct: Annotated[
        Decimal | None,
        Field(
            description="Percent of equity lost in a day, at least 0.1 and at most 50 (SCR-131)."
        ),
    ] = None
    max_open_positions: Annotated[JsonInt | None, Field(ge=1, le=50)] = None
    max_concurrent_orders: Annotated[JsonInt | None, Field(ge=1, le=500)] = None
    max_leverage_cap: Annotated[
        Decimal | None, Field(description="At least 1, at most 100, and at least `leverage`.")
    ] = None
    max_orders_per_minute: Annotated[JsonInt, Field(ge=1, le=600)] = 30


class ProfileWarning(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    code: Annotated[
        Literal["all_symbols", "no_symbols", "sizing_below_min_order", "stop_beyond_liquidation"],
        Field(
            description="`all_symbols`: every listed symbol is allowed, by the flag or by the pattern `*USDT`; a write, which reads the instrument list, also flags an allow-list whose entries together match every listed symbol. Consider restricting. `no_symbols`: no symbol is allowed, so the profile sizes nothing (decision D11): an empty `allowed_symbols` without `all_symbols`, or the pattern `*USDT` in `blocked_symbols`; a write also flags a profile that allows none of the listed symbols. `sizing_below_min_order`: at the account's current equity the sizing gives less than `symbol`'s minimum order, and `message` works the example. `stop_beyond_liquidation`: the stop lies beyond the estimated liquidation distance at `leverage` (SR-E28-26). Open-ended for readers: a client shows a code it does not know by its `message` (C-6.3).\n"
        ),
    ]
    message: str
    field: Annotated[str | None, Field(description="The JSON path of the member it is about.")] = (
        None
    )
    symbol: Annotated[
        str | None,
        Field(
            description="Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.",
            examples=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            pattern="^[A-Z0-9]{2,20}USDT$",
        ),
    ] = None
    estimated: Annotated[StrictBool, Field(description="Derived from an estimate (C10).")] = False


class AccountProfileInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: Annotated[
        str,
        Field(
            description="Unique per account, in any letter case. It holds no control character (U+0000 to U+001F) and no unpaired surrogate. It holds no character of category Cc or Cf either, such as DEL, U+200B, U+202E or U+FEFF (`not_allowed`).\n",
            max_length=80,
            min_length=1,
            pattern="^[^\\x00-\\x1F]+$",
        ),
    ]
    is_default: Annotated[
        StrictBool,
        Field(
            description="The account's default, its ceiling (decision D7). A profile write never changes it: the default binding moves only through its own operation (`setAccountDefaultProfile`), so `true` on a create, or on a replace a value other than the stored one, is refused (`default_has_own_operation`).\n"
        ),
    ] = False
    enabled: Annotated[StrictBool, Field(description="A disabled profile sizes nothing.")] = True
    trading_enabled: Annotated[
        StrictBool,
        Field(
            description="The profile sizes orders only when set, and then bounds every cap (decision D11)."
        ),
    ] = False
    leverage: Annotated[
        str,
        Field(
            description="At least 1, at most 100, and at most the exchange maximum of each allowed symbol.",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ]
    margin_mode: Annotated[
        Literal["cross", "isolated"],
        Field(description="`MarginMode` without `portfolio` (`ap_margin_mode`)."),
    ] = "cross"
    position_mode: Literal["one_way", "hedge"] = "one_way"
    sizing: ProfileSizing
    stop_loss: Annotated[
        ProfileStopLoss | None,
        Field(description="Required with `risk_based`; left out, it is 10 ticks."),
    ] = None
    take_profit: Annotated[
        ProfileTakeProfit | None, Field(description="`null` or left out: no take-profit distance.")
    ] = None
    take_profit_ladder: Annotated[
        list[ProfileTakeProfitRung], Field(max_length=10, validate_default=True)
    ] = []
    risk_caps: ProfileRiskCaps | None = None
    all_symbols: Annotated[
        StrictBool,
        Field(description="Allows every listed USDT linear perpetual, with no `allowed_symbols`."),
    ] = False
    allowed_symbols: Annotated[
        list[ProfileSymbolPattern],
        Field(
            description="Empty without `all_symbols`, it allows nothing (decision D11).",
            max_length=500,
            validate_default=True,
        ),
    ] = []
    blocked_symbols: Annotated[
        list[ProfileSymbolPattern],
        Field(
            description="Refused even when allowed, by `allowed_symbols` or `all_symbols`.",
            max_length=500,
            validate_default=True,
        ),
    ] = []
    require_native_stop: Annotated[
        Literal[True],
        Field(
            description="Always true; the safety invariant cannot be disabled (arch P4). The order path never reads it: the stop requirement keys on each order's effect on the position (SR-E29-01).\n"
        ),
    ] = True
    default_time_in_force: Literal["GTC", "IOC", "FOK", "PostOnly"] = "GTC"
    reduce_only_default: StrictBool = False
    slippage_tolerance_bps: Annotated[
        JsonInt,
        Field(description="The slippage a market order may take, in basis points.", ge=0, le=1000),
    ] = 10
    __null_refused = field_validator("stop_loss", "risk_caps", mode="before")(_refuse_null)


class AccountProfile(BaseModel):
    id: UUID
    exchange_account_id: UUID
    environment: Annotated[
        Literal["live", "demo", "testnet"],
        Field(
            description="It is the account's environment, so a client can badge it wherever profiles are listed (C-2.11), and it is never writable.\n"
        ),
    ]
    version: Annotated[JsonInt, Field(ge=1)]
    created_at: AwareDatetime
    updated_at: AwareDatetime
    warnings: list[ProfileWarning]
    profile: AccountProfileInput


class AccountDefaultBindingInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    profile_id: Annotated[UUID, Field(description="A live profile of this account.")]


class AccountDefaultBinding(BaseModel):
    exchange_account_id: UUID
    environment: Annotated[
        Literal["live", "demo", "testnet"],
        Field(
            description="It is the account's environment, so a client can badge it wherever profiles are listed (C-2.11), and it is never writable.\n"
        ),
    ]
    profile_id: UUID
    version: Annotated[JsonInt, Field(ge=1)]


class Instrument(BaseModel):
    symbol: Annotated[
        str,
        Field(
            description="Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.",
            examples=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            pattern="^[A-Z0-9]{2,20}USDT$",
        ),
    ]
    category: Literal["linear"]
    base_coin: str | None = None
    quote_coin: str | None = None
    settle_coin: str | None = None
    contract_type: Annotated[str | None, Field(examples=["LinearPerpetual"])] = None
    status: Literal["Trading", "PreLaunch", "Delivering", "Closed"] | None = None
    tick_size: Annotated[
        str,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ]
    price_scale: JsonInt | None = None
    qty_step: Annotated[
        str,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ]
    min_order_qty: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    max_order_qty: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    min_notional_value: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    max_leverage: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    leverage_step: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    funding_interval_minutes: JsonInt | None = None
    launch_time: AwareDatetime | None = None
    copy_trading: StrictBool | None = None
    revision: Annotated[
        JsonInt | None,
        Field(description="Increments whenever Bybit changes the instrument metadata."),
    ] = None
    updated_at: AwareDatetime | None = None
    delisted: Annotated[
        StrictBool | None,
        Field(description="Derived: true when `status` is not `Trading` or `PreLaunch`."),
    ] = None
    status_reason: Annotated[
        str | None,
        Field(description="Human-readable explanation of `status`, for screen readers (#182)."),
    ] = None


class RiskLimitTier(BaseModel):
    tier: JsonInt | None = None
    risk_limit_value: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    initial_margin: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    maintenance_margin: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    max_leverage: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None


class InstrumentDetail(Instrument):
    risk_limit_tiers: list[RiskLimitTier] | None = None
    recorded: StrictBool | None = None
    recording_started_at: AwareDatetime | None = None
    stale_since: Annotated[
        AwareDatetime | None,
        Field(description="When this instrument's cache entry started missing refresh cadence."),
    ] = None


class Ticker(BaseModel):
    symbol: Annotated[
        str | None,
        Field(
            description="Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.",
            examples=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            pattern="^[A-Z0-9]{2,20}USDT$",
        ),
    ] = None
    last_price: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    mark_price: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    index_price: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    bid1_price: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    bid1_size: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    ask1_price: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    ask1_size: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    price_change_pct_24h: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    high_24h: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    low_24h: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    volume_24h: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    turnover_24h: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    open_interest: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    open_interest_value: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    funding_rate: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    next_funding_time: AwareDatetime | None = None
    ts: AwareDatetime | None = None
    stale: StrictBool | None = None


class TickersItem(Ticker):
    symbol: Annotated[
        str,
        Field(
            description="Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.",
            examples=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            pattern="^[A-Z0-9]{2,20}USDT$",
        ),
    ]
    ts: AwareDatetime
    stale: StrictBool


class TickersResponse(BaseModel):
    items: Annotated[
        list[TickersItem],
        Field(
            description="One `Ticker` per requested symbol the snapshot holds, in the order first requested, each with its `symbol`, `ts`, `stale` and every field the snapshot has a value for, `high_24h` and `low_24h` included. A field Bybit leaves empty is left out, never `null`.",
            max_length=200,
        ),
    ]
    unknown_symbols: Annotated[
        list[Symbol],
        Field(
            description="The requested symbols the snapshot has no ticker for, each once, in the order first requested; empty when every symbol was found.",
            max_length=200,
        ),
    ]
    meta: PageMeta


class Bar(BaseModel):
    index: Annotated[
        JsonInt | None,
        Field(
            description="Bar index, strictly increasing within (series, generation) (24 §3.1). Always present on /market/bars; `t` may repeat for non-time bars (#2014).",
            ge=0,
        ),
    ] = None
    generation: Annotated[
        JsonInt | None,
        Field(
            description="ADR-0033 series generation (= epoch): an opaque id that a builder cold start or a rebuild replaces, normally with a higher one; index restarts inside it. Compare for equality only: a change in either direction is a new epoch. Never read it as a time. Always present on /market/bars.",
            ge=0,
        ),
    ] = None
    t: Annotated[AwareDatetime, Field(description="Bar open time; not unique for non-time bars.")]
    close_time: Annotated[AwareDatetime | None, Field(description="Present for non-time bars.")] = (
        None
    )
    o: Annotated[
        str,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ]
    h: Annotated[
        str,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ]
    l: Annotated[
        str,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ]
    c: Annotated[
        str,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ]
    v: Annotated[
        str,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ]
    turnover: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    trades: JsonInt | None = None
    confirm: Annotated[
        StrictBool | None,
        Field(description="False for the in-progress bar (Bybit `confirm` semantics)."),
    ] = None
    gap_before: Annotated[
        StrictBool,
        Field(
            description="True when a gap precedes this bar: the recorded trade tape had a gap before the bar's first print, or the builder marked a discontinuity before it (24 §3.3), so the bar may be incomplete at its start. The same flag as the stored row's `gap_before` (21 §4.8) and the WS `bars` item's (23 §14.3). Absent means `false`: a bar not built from the tape (a `kline` row) and a row stored before the column existed both read `false`. Optional, additive (C-6.3)."
        ),
    ] = False
    partial: Annotated[
        StrictBool,
        Field(
            description="True when the bar is not built from a complete tape window (24 §3.1), such as the first bar a builder forms after it starts inside the bar's window, so its open, volume and order flow may cover only part of the bar. The same flag as the stored row's `partial` (21 §4.8) and the WS `bars` item's (23 §14.3). Absent means `false`, as for `gap_before`. Optional, additive (C-6.3)."
        ),
    ] = False
    delta: Decimal | None = None
    cvd: Decimal | None = None
    min_delta: Decimal | None = None
    max_delta: Decimal | None = None


class BarsMeta(DataMeta):
    spec_hash: Annotated[
        str | None,
        Field(
            description="The served series' bar spec hash (24 §3.1), the WS `bars` snapshot's `meta.spec_hash` for the same series.",
            pattern="^[0-9a-f]{64}$",
        ),
    ] = None
    build_version: Annotated[
        JsonInt | None,
        Field(
            description="The lowest bar builder version among the bars served, by the WS `bars` snapshot rule (23 §6.1): a served bar is never traced to newer code than the code that built it. A page with no bar carries the running version.",
            ge=1,
        ),
    ] = None
    stale: Annotated[
        StrictBool,
        Field(
            description="True when a bar served was built below the running builder version, so `build_version` is below the running one and a later read may serve that window rebuilt. Absent means `false`."
        ),
    ] = False


class FootprintCell(BaseModel):
    price: Annotated[
        str,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ]
    bid_volume: Annotated[
        str,
        Field(
            description="Volume traded into the bid (taker sells).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ]
    ask_volume: Annotated[
        str,
        Field(
            description="Volume traded into the ask (taker buys).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ]
    delta: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    total_volume: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    trades: JsonInt | None = None


class FootprintImbalance(BaseModel):
    price: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    direction: Literal["buy", "sell"] | None = None
    ratio: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    stacked: StrictBool | None = None
    stack_size: JsonInt | None = None
    estimated: StrictBool = False


class UnfinishedAuction(BaseModel):
    high: StrictBool | None = None
    low: StrictBool | None = None


class FootprintBar(Bar):
    poc_price: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    value_area_high: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    value_area_low: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    unfinished_auction: UnfinishedAuction | None = None
    cells: list[FootprintCell] | None = None
    imbalances: list[FootprintImbalance] | None = None


class FootprintResponse(BaseModel):
    symbol: Annotated[
        str,
        Field(
            description="Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.",
            examples=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            pattern="^[A-Z0-9]{2,20}USDT$",
        ),
    ]
    bar_type: (
        Literal["time", "tick", "volume", "range", "delta", "renko", "pnf", "heikin_ashi"] | None
    ) = None
    param: str | None = None
    tick_size: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    price_grouping: JsonInt | None = None
    bars: list[FootprintBar]
    meta: DataMeta


class ProfileRow(BaseModel):
    price: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    volume: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    buy_volume: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    sell_volume: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    delta: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    tpo_count: JsonInt | None = None


class ProfilePeriod(BaseModel):
    period_start: AwareDatetime | None = None
    period_end: AwareDatetime | None = None
    total_volume: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    poc_price: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    value_area_high: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    value_area_low: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    naked_poc: Annotated[
        StrictBool | None,
        Field(description="True while this period's POC has not been retraded by a later bar."),
    ] = None
    rows: list[ProfileRow] | None = None
    hvn: list[Decimal] | None = None
    lvn: list[Decimal] | None = None


class ProfileResponse(BaseModel):
    symbol: Annotated[
        str | None,
        Field(
            description="Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.",
            examples=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            pattern="^[A-Z0-9]{2,20}USDT$",
        ),
    ] = None
    kind: Literal["volume", "delta", "tpo"] | None = None
    split: Literal["composite", "session", "fixed"] | None = None
    profiles: list[ProfilePeriod] | None = None
    meta: DataMeta | None = None


class PublicTrade(BaseModel):
    id: str | None = None
    ts: AwareDatetime | None = None
    price: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    size: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    side: Annotated[
        Literal["buy", "sell"] | None,
        Field(description="Taker/aggressor side, taken directly from Bybit `S`."),
    ] = None
    is_block_trade: StrictBool | None = None
    is_liquidation: Annotated[
        StrictBool,
        Field(description="The print is liquidation-origin, as on WS `TradesBatch` (23 §14.2)."),
    ] = False
    is_big_trade: Annotated[
        StrictBool,
        Field(
            description="The big-trade engine's flag against `meta.big_trade_threshold`; never recomputed by a client. On a cluster, true when any member print is flagged (the engine has no cluster-level evaluation)."
        ),
    ] = False
    cluster_size: Annotated[
        JsonInt | None, Field(description="Number of raw prints merged when clustering is on.")
    ] = None
    tick_direction: Literal["PlusTick", "ZeroPlusTick", "MinusTick", "ZeroMinusTick"] | None = None


class TradesPageMeta(PageMeta):
    big_trade_threshold: Annotated[
        str,
        Field(
            description="The engine's current effective threshold, absolute: base units when `big_trade_mode` is `absolute_size`, USDT when it is `notional` or `percentile`.",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ]
    big_trade_mode: Literal["absolute_size", "notional", "percentile"]


class Bid(RootModel[list[Decimal]]):
    root: Annotated[list[Decimal], Field(max_length=2, min_length=2)]


class Ask(RootModel[list[Decimal]]):
    root: Annotated[list[Decimal], Field(max_length=2, min_length=2)]


class OrderbookSnapshot(BaseModel):
    symbol: Annotated[
        str,
        Field(
            description="Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.",
            examples=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            pattern="^[A-Z0-9]{2,20}USDT$",
        ),
    ]
    depth: Literal[1, 50, 200, 500]
    u: Annotated[JsonInt, Field(description="Monotonic update id from Bybit.")]
    seq: Annotated[JsonInt, Field(description="Cross-topic sequence from Bybit.")]
    ts: AwareDatetime
    bids: Annotated[list[Bid], Field(description="[price, size], descending.")]
    asks: Annotated[list[Ask], Field(description="[price, size], ascending.")]
    stale: StrictBool | None = None


class Sample(RootModel[JsonInt]):
    root: Annotated[JsonInt, Field(ge=0)]


class HeatmapSegment(BaseModel):
    from_: Annotated[AwareDatetime, Field(alias="from")]
    to: AwareDatetime
    source: Annotated[
        Literal["hot", "cold", "reconstructed", "downsampled"],
        Field(
            description="`hot` QuestDB cells, `cold` Parquet cells, `reconstructed` rebuilt from recorded book snapshots and deltas, `downsampled` older than the 180-day boundary (21 §7)."
        ),
    ]
    effective_resolution_ms: Annotated[
        JsonInt,
        Field(
            description="The finest time resolution the span's data holds; never finer than its source recorded.",
            ge=100,
        ),
    ]


class MetricPoint(BaseModel):
    t: AwareDatetime
    v: Decimal | None
    meta: Annotated[
        dict[str, Any] | None,
        Field(
            description="Per-point detail for event-like metrics (iceberg, stop_run, absorption)."
        ),
    ] = None


class MetricSeries(BaseModel):
    metric: Literal[
        "cvd",
        "delta",
        "min_max_delta",
        "trades_per_sec",
        "volume_per_sec",
        "book_updates_per_sec",
        "tape_acceleration",
        "imbalance_ratio",
        "absorption",
        "exhaustion",
        "iceberg",
        "stop_run",
        "adx",
        "atr",
        "hurst",
        "regime",
        "vwap",
        "open_interest_delta",
        "funding_basis",
        "liquidation_intensity",
        "big_trade_notional",
        "big_trade_zscore",
    ]
    estimated: Annotated[
        StrictBool | None, Field(description="True for heuristic metrics (arch P10).")
    ] = None
    params: dict[str, Any] | None = None
    unit: Annotated[
        str | None, Field(examples=["base_volume", "index", "ratio", "confidence", "usd", "price"])
    ] = None
    points: list[MetricPoint]


class MetricsResponse(BaseModel):
    symbol: Annotated[
        str | None,
        Field(
            description="Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.",
            examples=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            pattern="^[A-Z0-9]{2,20}USDT$",
        ),
    ] = None
    bar_type: (
        Literal["time", "tick", "volume", "range", "delta", "renko", "pnf", "heikin_ashi"] | None
    ) = None
    param: str | None = None
    series: list[MetricSeries] | None = None
    meta: DataMeta | None = None


class Liquidation(BaseModel):
    ts: AwareDatetime | None = None
    symbol: Annotated[
        str | None,
        Field(
            description="Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.",
            examples=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            pattern="^[A-Z0-9]{2,20}USDT$",
        ),
    ] = None
    side: Annotated[
        Literal["buy", "sell"] | None,
        Field(
            description="The print's side as the `side` query parameter reads it; which position was liquidated follows the adapter's mapping of Bybit's `S` (24 §2.5 `liquidated_side`), never a client's own reading of the venue field."
        ),
    ] = None
    price: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    size: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    notional_usd: Annotated[
        str | None,
        Field(
            description="`price × size` in USD, computed once at ingest (a cluster: the sum).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    cluster_size: Annotated[JsonInt | None, Field(ge=1)] = None


class Coverage(BaseModel):
    first_available_ts: AwareDatetime | None
    covered_from: AwareDatetime | None
    covered_to: AwareDatetime | None
    no_coverage: StrictBool


class LiquidationsPageMeta(PageMeta):
    coverage: Coverage


class OpenInterestPoint(BaseModel):
    t: AwareDatetime
    open_interest: Annotated[
        str,
        Field(
            description="Base-coin open interest, both sides.",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ]
    open_interest_value: Annotated[
        Decimal | None,
        Field(description="USD value from the ticker; `null` on a `rest` point (never computed)."),
    ]
    interval: Literal["1s", "5min", "15min", "30min", "1h", "4h", "1d"]
    source: Literal["ws_ticker", "rest"]


class Gap(BaseModel):
    from_: Annotated[AwareDatetime, Field(alias="from")]
    to: AwareDatetime


class Coverage1(BaseModel):
    from_: Annotated[AwareDatetime | None, Field(alias="from")]
    to: AwareDatetime | None
    native_interval: Literal["1s", "5min", "15min", "30min", "1h", "4h", "1d"]
    source: Literal["ws_ticker", "rest"]
    gaps: list[Gap]


class OpenInterestPageMeta(PageMeta):
    coverage: Coverage1


class Interval(BaseModel):
    from_: Annotated[AwareDatetime | None, Field(alias="from")] = None
    to: AwareDatetime | None = None
    tier: Literal["questdb", "parquet"] | None = None
    rows: JsonInt | None = None


class Gap1(BaseModel):
    from_: Annotated[AwareDatetime | None, Field(alias="from")] = None
    to: AwareDatetime | None = None
    reason: Annotated[
        Literal[
            "ws_disconnect",
            "backend_restart",
            "retention_purge",
            "never_recorded",
            "exchange_outage",
            "backpressure_drop",
            "seq_jump",
        ]
        | None,
        Field(
            description="`backpressure_drop`: rows dropped under write backpressure, the level-3 write gate included; `seq_jump`: an order-book update-id jump. **Open-ended for readers:** a reason a client does not know is still a gap (C-6.3)."
        ),
    ] = None


class Stream(BaseModel):
    stream: (
        Literal[
            "trades",
            "orderbook_delta",
            "orderbook_snapshot",
            "tickers",
            "klines",
            "liquidations",
            "open_interest",
            "funding",
        ]
        | None
    ) = None
    intervals: list[Interval] | None = None
    gaps: list[Gap1] | None = None


class DataCoverage(BaseModel):
    symbol: Annotated[
        str | None,
        Field(
            description="Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.",
            examples=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            pattern="^[A-Z0-9]{2,20}USDT$",
        ),
    ] = None
    streams: list[Stream] | None = None
    generated_at: AwareDatetime | None = None


class RecordedSymbol(BaseModel):
    id: UUID
    symbol: Annotated[
        str,
        Field(
            description="Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.",
            examples=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            pattern="^[A-Z0-9]{2,20}USDT$",
        ),
    ]
    reason: Literal["manual", "chart_open", "position_open", "rule_dependency", "alert_dependency"]
    pinned: StrictBool | None = None
    state: Literal["idle", "starting", "recording", "degraded", "stopping", "stopped", "error"]
    streams: (
        list[
            Literal[
                "trades",
                "orderbook_delta",
                "orderbook_snapshot",
                "tickers",
                "klines",
                "liquidations",
                "open_interest",
                "funding",
            ]
        ]
        | None
    ) = None
    depth: Literal[1, 50, 200, 500] | None = None
    started_at: AwareDatetime | None = None
    retention_days: JsonInt | None = None
    disk_bytes: JsonInt | None = None
    rows_last_hour: JsonInt | None = None
    lag_ms: JsonInt | None = None
    added_by: UUID | None = None
    lingering: StrictBool | None = None
    linger_until: AwareDatetime | None = None
    refusal: Annotated[
        Literal["symbol_cap", "disk_pressure", "chart_open", "position_open"] | None,
        Field(
            description="Why the server refuses the next start (`symbol_cap`, `disk_pressure`; such a symbol has no row, so only status carries it) or stop (`chart_open`, `position_open`) of a symbol, null or omitted when none; `position_open` outranks `chart_open` when both hold, and a role-restricted view never carries `position_open` (R-I2). **Open-ended for readers:** clients must tolerate values they do not know, so adding one is an additive change (C-6.3)."
        ),
    ] = None


class Estimate(BaseModel):
    daily_bytes_estimate: JsonInt | None = None
    basis: Annotated[
        str | None, Field(examples=["~0.5-0.75 GB/day/symbol compressed at depth 200"])
    ] = None
    warning: str | None = None


class RecordedSymbolWithEstimate(RecordedSymbol):
    estimate: Annotated[
        Estimate | None,
        Field(
            description="Planning estimate, replaced by measured rates once the recorder has run for an hour."
        ),
    ] = None


class AddRecordedSymbolRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    symbol: Annotated[
        str,
        Field(
            description="Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.",
            examples=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            pattern="^[A-Z0-9]{2,20}USDT$",
        ),
    ]
    streams: Annotated[
        list[
            Literal[
                "trades",
                "orderbook_delta",
                "orderbook_snapshot",
                "tickers",
                "klines",
                "liquidations",
                "open_interest",
                "funding",
            ]
        ],
        Field(min_length=1),
    ] = ["trades", "orderbook_delta", "tickers", "liquidations"]
    depth: Literal[1, 50, 200, 500] = 200
    pinned: StrictBool = False
    retention_days: Annotated[JsonInt | None, Field(ge=1, le=3650)] = 30


class UpdateRecordedSymbolRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    streams: Annotated[
        list[
            Literal[
                "trades",
                "orderbook_delta",
                "orderbook_snapshot",
                "tickers",
                "klines",
                "liquidations",
                "open_interest",
                "funding",
            ]
        ]
        | None,
        Field(min_length=1),
    ] = None
    depth: Literal[1, 50, 200, 500] | None = None
    pinned: StrictBool | None = None
    retention_days: Annotated[JsonInt | None, Field(ge=1, le=3650)] = None
    __null_refused = field_validator("streams", "depth", "pinned", mode="before")(_refuse_null)


class Connection(BaseModel):
    endpoint: str | None = None
    state: Literal["connecting", "connected", "degraded", "disconnected"] | None = None
    subscribed_topics: JsonInt | None = None
    connected_since: AwareDatetime | None = None
    reconnects_last_hour: JsonInt | None = None
    last_ping_ms: JsonInt | None = None


class Symbol1(BaseModel):
    symbol: Annotated[
        str | None,
        Field(
            description="Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.",
            examples=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            pattern="^[A-Z0-9]{2,20}USDT$",
        ),
    ] = None
    state: (
        Literal["idle", "starting", "recording", "degraded", "stopping", "stopped", "error"] | None
    ) = None
    lag_ms: JsonInt | None = None
    rows_last_hour: JsonInt | None = None
    dropped_messages: JsonInt | None = None
    resyncs_last_hour: JsonInt | None = None
    last_event_at: AwareDatetime | None = None
    lingering: StrictBool | None = None
    linger_until: AwareDatetime | None = None
    refusal: Annotated[
        Literal["symbol_cap", "disk_pressure", "chart_open", "position_open"] | None,
        Field(
            description="Why the server refuses the next start (`symbol_cap`, `disk_pressure`; such a symbol has no row, so only status carries it) or stop (`chart_open`, `position_open`) of a symbol, null or omitted when none; `position_open` outranks `chart_open` when both hold, and a role-restricted view never carries `position_open` (R-I2). **Open-ended for readers:** clients must tolerate values they do not know, so adding one is an additive change (C-6.3)."
        ),
    ] = None


class RecorderPolicySettings(BaseModel):
    autostart_delay_s: Annotated[JsonInt, Field(ge=0)]
    autostop_grace_s: Annotated[JsonInt, Field(ge=0)]
    max_symbols: Annotated[JsonInt, Field(ge=1)]
    warn_pct: Annotated[JsonInt, Field(ge=1, le=100)]
    autostop_pct: Annotated[JsonInt, Field(ge=1, le=100)]
    halt_pct: Annotated[JsonInt, Field(ge=1, le=100)]
    autorecord_enabled: StrictBool


class Tier(BaseModel):
    tier: Literal["questdb", "parquet", "postgres"] | None = None
    used_bytes: JsonInt | None = None
    retention_days: JsonInt | None = None


class Symbol2(BaseModel):
    symbol: Annotated[
        str | None,
        Field(
            description="Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.",
            examples=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            pattern="^[A-Z0-9]{2,20}USDT$",
        ),
    ] = None
    used_bytes: JsonInt | None = None
    daily_growth_bytes: JsonInt | None = None
    pinned: StrictBool | None = None


class StorageUsage(BaseModel):
    disk_total_bytes: JsonInt | None = None
    disk_used_bytes: JsonInt | None = None
    disk_free_bytes: JsonInt | None = None
    projected_full_at: AwareDatetime | None = None
    daily_growth_bytes: JsonInt | None = None
    tiers: list[Tier] | None = None
    symbols: list[Symbol2] | None = None
    generated_at: AwareDatetime | None = None
    cap_bytes: Annotated[JsonInt | None, Field(ge=1)] = None
    level: Literal[0, 1, 2, 3] | None = None
    write_gate: Literal["open", "closed"] | None = None
    write_gate_reason: Annotated[
        Literal["disk_halt", "volume_refused"] | None,
        Field(
            description="Why the write gate is closed, null when open. **Open-ended for readers:** adding a value is an additive change (C-6.3)."
        ),
    ] = None
    accelerate_retention: StrictBool | None = None


class RetentionPolicyInput(BaseModel):
    stream: Literal[
        "trades",
        "orderbook_delta",
        "orderbook_snapshot",
        "tickers",
        "klines",
        "liquidations",
        "open_interest",
        "funding",
    ]
    retain_days: Annotated[JsonInt, Field(ge=1, le=3650)]
    action: Literal["drop", "archive_parquet", "downsample", "pin"]
    symbol: Annotated[Symbol | None, Field(description="Null = global default.")] = None
    applies_to_pinned: StrictBool = False


class RetentionPolicy(RetentionPolicyInput):
    id: UUID | None = None
    updated_at: AwareDatetime | None = None


class RecordingSession(BaseModel):
    id: UUID | None = None
    recorded_symbol_id: UUID | None = None
    symbol: Annotated[
        str | None,
        Field(
            description="Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.",
            examples=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            pattern="^[A-Z0-9]{2,20}USDT$",
        ),
    ] = None
    state: (
        Literal["idle", "starting", "recording", "degraded", "stopping", "stopped", "error"] | None
    ) = None
    started_at: AwareDatetime | None = None
    ended_at: AwareDatetime | None = None
    streams: (
        list[
            Literal[
                "trades",
                "orderbook_delta",
                "orderbook_snapshot",
                "tickers",
                "klines",
                "liquidations",
                "open_interest",
                "funding",
            ]
        ]
        | None
    ) = None
    depth: JsonInt | None = None
    rows: JsonInt | None = None
    bytes: JsonInt | None = None
    gap_count: JsonInt | None = None


class CreateReplaySessionRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    symbols: Annotated[list[Symbol], Field(max_length=8, min_length=1)]
    from_: Annotated[AwareDatetime, Field(alias="from")]
    to: AwareDatetime
    speed: Annotated[
        StrictFloat,
        Field(description="0 = as fast as possible (used by rule simulation).", ge=0.0, le=100.0),
    ] = 1
    streams: (
        list[
            Literal[
                "trades",
                "orderbook_delta",
                "orderbook_snapshot",
                "tickers",
                "klines",
                "liquidations",
                "open_interest",
                "funding",
            ]
        ]
        | None
    ) = None
    depth: Literal[1, 50, 200, 500] = 200
    paper_account_id: UUID | None = None
    autostart: StrictBool = False
    __null_refused = field_validator("streams", mode="before")(_refuse_null)


class ReplaySession(BaseModel):
    id: UUID | None = None
    state: Literal["created", "buffering", "playing", "paused", "finished", "error"] | None = None
    symbols: list[Symbol] | None = None
    from_: Annotated[AwareDatetime | None, Field(alias="from")] = None
    to: AwareDatetime | None = None
    cursor_ts: AwareDatetime | None = None
    speed: StrictFloat | None = None
    streams: (
        list[
            Literal[
                "trades",
                "orderbook_delta",
                "orderbook_snapshot",
                "tickers",
                "klines",
                "liquidations",
                "open_interest",
                "funding",
            ]
        ]
        | None
    ) = None
    depth: JsonInt | None = None
    paper_account_id: UUID | None = None
    created_by: UUID | None = None
    created_at: AwareDatetime | None = None
    progress_pct: Annotated[StrictFloat | None, Field(ge=0.0, le=100.0)] = None
    error: str | None = None


class ReplayControlRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    action: Literal["play", "pause", "seek", "step", "set_speed", "restart"]
    speed: Annotated[StrictFloat | None, Field(ge=0.0, le=100.0)] = None
    to: Annotated[AwareDatetime | None, Field(description="Required for `seek`.")] = None
    step_events: Annotated[JsonInt | None, Field(ge=1, le=100000)] = None
    step_ms: Annotated[JsonInt | None, Field(ge=1, le=3600000)] = None
    __null_refused = field_validator("speed", "to", "step_events", "step_ms", mode="before")(_refuse_null)


class TriggerSpec(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    price: Annotated[
        str,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ]
    trigger_by: Literal["LastPrice", "MarkPrice", "IndexPrice"] | None = None
    direction: Literal["rise", "fall"]
    __null_refused = field_validator("trigger_by", mode="before")(_refuse_null)


class Oco(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    other_price: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    other_trigger: TriggerSpec | None = None
    cancel_timeout_ms: Annotated[
        JsonInt,
        Field(
            description="Max time to cancel the loser after the winner's fill notice arrives on the WS.",
            ge=100,
            le=60000,
        ),
    ] = 2000
    __null_refused = field_validator("other_price", "other_trigger", mode="before")(_refuse_null)


class Iceberg(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    display_qty: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    refresh_on_fill_pct: Annotated[StrictFloat, Field(ge=1.0, le=100.0)] = 100
    randomize_display_pct: Annotated[StrictFloat, Field(ge=0.0, le=50.0)] = 0
    __null_refused = field_validator("display_qty", mode="before")(_refuse_null)


class Twap(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    duration_seconds: Annotated[JsonInt | None, Field(ge=10, le=86400)] = None
    slices: Annotated[JsonInt | None, Field(ge=2, le=500)] = None
    randomize_pct: Annotated[StrictFloat, Field(ge=0.0, le=50.0)] = 0
    limit_offset_ticks: Annotated[
        JsonInt | None, Field(description="Omit for market slices.", ge=0, le=1000)
    ] = None
    __null_refused = field_validator("duration_seconds", "slices", "limit_offset_ticks", mode="before")(_refuse_null)


class Chase(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    offset_ticks: Annotated[JsonInt, Field(ge=0, le=100)] = 0
    max_chases: Annotated[JsonInt, Field(ge=1, le=500)] = 20
    max_slippage_ticks: Annotated[JsonInt | None, Field(ge=1, le=10000)] = None
    repricing_interval_ms: Annotated[JsonInt, Field(ge=50, le=10000)] = 250
    fallback_to_market: StrictBool = False
    __null_refused = field_validator("max_slippage_ticks", mode="before")(_refuse_null)


class Scaled(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    levels: Annotated[JsonInt | None, Field(ge=2, le=50)] = None
    from_price: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    to_price: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    distribution: Literal["equal", "linear", "geometric"] | None = None
    skew: Annotated[
        str | None,
        Field(
            description=">1 weights size toward `to_price`.",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    __null_refused = field_validator("levels", "from_price", "to_price", "distribution", "skew", mode="before")(_refuse_null)


class TakeProfitLevel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    offset: Offset | None = None
    pct_of_position: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    __null_refused = field_validator("offset", "pct_of_position", mode="before")(_refuse_null)


class Bracket(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    take_profit_levels: Annotated[list[TakeProfitLevel] | None, Field(max_length=10)] = None
    move_stop_to_breakeven_at: Offset | None = None
    __null_refused = field_validator("take_profit_levels", "move_stop_to_breakeven_at", mode="before")(_refuse_null)


class AlgoSpec(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["none", "oco", "iceberg", "twap", "chase", "scaled", "bracket"]
    oco: Oco | None = None
    iceberg: Iceberg | None = None
    twap: Twap | None = None
    chase: Chase | None = None
    scaled: Scaled | None = None
    bracket: Bracket | None = None
    __null_refused = field_validator("oco", "iceberg", "twap", "chase", "scaled", "bracket", mode="before")(_refuse_null)


class PlaceOrderRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    exchange_account_id: Annotated[
        UUID,
        Field(
            description="An account outside the caller's grants and one that does not exist are refused alike (`403 account_scope_denied`), audited, before any exchange call (SR-E29-13)."
        ),
    ]
    symbol: Annotated[
        str,
        Field(
            description="Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.",
            examples=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            pattern="^[A-Z0-9]{2,20}USDT$",
        ),
    ]
    side: Literal["buy", "sell"]
    order_type: Literal["market", "limit"]
    intent: Literal[
        "entry",
        "stop_loss",
        "take_profit",
        "scale_in",
        "scale_out",
        "flatten",
        "reverse",
        "algo_child",
    ] = "entry"
    sizing: Sizing
    price: Annotated[
        str | None,
        Field(
            description="Required for `limit`.",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    time_in_force: Literal["GTC", "IOC", "FOK", "PostOnly"] | None = None
    reduce_only: StrictBool = False
    close_on_trigger: StrictBool = False
    position_idx: Annotated[
        Literal[0, 1, 2] | None, Field(description="Required in hedge mode (1 = long, 2 = short).")
    ] = None
    trigger: TriggerSpec | None = None
    stop_loss: Offset | None = None
    take_profit: Offset | None = None
    tpsl_mode: Literal["Full", "Partial"] | None = None
    algo: AlgoSpec | None = None
    profile_id: Annotated[
        UUID | None,
        Field(
            description="An alternate profile of this order's account; it only narrows the account's bound profile, its default profile (`is_default`, D7; later narrows, as on `createTradeGroup`; SR-E28-03): every cap the guard reads and the allowed symbols stay the bound profile's or stricter. Any other id, another account's, a deleted one or one that does not exist, is `404 not_found`, decided at validation, after the account-scope check and before the order is sized, the same answer for each, never a `403`."
        ),
    ] = None
    note: Annotated[str | None, Field(max_length=280)] = None
    __null_refused = field_validator("price", "time_in_force", "position_idx", "trigger", "stop_loss", "take_profit", "tpsl_mode", "algo", "note", mode="before")(_refuse_null)


class AmendOrderRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    price: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    qty: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    trigger_price: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    take_profit: Offset | None = None
    stop_loss: Offset | None = None
    __null_refused = field_validator("price", "qty", "trigger_price", mode="before")(_refuse_null)


class CancelAllRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    exchange_account_ids: Annotated[
        list[UUID] | None,
        Field(
            description="Empty means the caller's granted accounts that allow trading (an Owner's: every account of the environment); one id outside them, or one that does not exist, refuses the whole request (SR-E29-13).",
            max_length=100,
        ),
    ] = None
    symbol: Symbol | None = None
    intents: (
        list[
            Literal[
                "entry",
                "stop_loss",
                "take_profit",
                "scale_in",
                "scale_out",
                "flatten",
                "reverse",
                "algo_child",
            ]
        ]
        | None
    ) = None
    exclude_reduce_only: Annotated[
        StrictBool,
        Field(
            description="Leaves reduce-only exits out of a blanket cancel; a recorded stop's row is never cancelled here, whatever this says (24-internal-schemas.md section 8.8 rule 6)."
        ),
    ] = True
    __null_refused = field_validator("exchange_account_ids", "intents", mode="before")(_refuse_null)


class Order(BaseModel):
    is_paper: Annotated[
        StrictBool,
        Field(
            description="True when the paper matcher produced this record rather than the exchange. Orthogonal to `environment` (24-internal-schemas.md section 1.2)."
        ),
    ] = False
    id: UUID
    exchange_account_id: UUID
    trade_group_id: UUID | None = None
    trade_group_leg_id: UUID | None = None
    parent_order_id: UUID | None = None
    order_link_id: Annotated[
        str | None,
        Field(
            description="Generated by the server once, before the first send, by the 24-internal-schemas.md section 8.3 scheme (`OUR_ID`), or `ext-` and 32 hex digits for an adopted exchange order (`EXT_ID`); never derived from the `Idempotency-Key` or any other client-supplied string (section 8.3 rule 1). Every retry re-sends it unchanged (C-2.10).",
            max_length=36,
            pattern="^(cv[ldtp]-[0-7][0-9A-Za-z]{21}-[0-9A-Za-z]{4}-[0-9A-Za-z]{2}(en|sl|tp|sc|fl|ac)|ext-[0-9a-f]{32})$",
        ),
    ] = None
    exchange_order_id: str | None = None
    symbol: Annotated[
        str,
        Field(
            description="Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.",
            examples=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            pattern="^[A-Z0-9]{2,20}USDT$",
        ),
    ]
    side: Literal["buy", "sell"]
    order_type: Literal["market", "limit"]
    intent: (
        Literal[
            "entry",
            "stop_loss",
            "take_profit",
            "scale_in",
            "scale_out",
            "flatten",
            "reverse",
            "algo_child",
        ]
        | None
    ) = None
    provenance: Annotated[
        Literal["placed", "reconciliation", "recorded_stop"] | None,
        Field(
            description="How the order's row came to exist, set once by its writer and never by a request\n(`orders.provenance`, `21-database-schema.md` section 3.3.4; not `origin`, which names\nthe intent's source in 24-internal-schemas.md section 8.1): `placed`, the OMS's own\nsubmission (`placeOrder`, `createTradeGroup` legs, algo children, rule actions, the\nposition routes' closes); `reconciliation`, an exchange order that reconciliation\nadopted as `untracked` (24-internal-schemas.md section 8.5 step 3c, E29-T06);\n`recorded_stop`, the TP/SL order of a stop the OMS recorded (section 8.8 rule 6), which\nE29-T05 materialises bound to its exchange `orderId` when it first appears, on its push\nor in reconciliation, so that every execution has an order. It decides nothing: an order\nor fill is OMS intent only through a row or a recorded stop bound to it (section 8.3).\n"
        ),
    ] = None
    state: Annotated[
        Literal[
            "new",
            "pending_submit",
            "submitted",
            "accepted",
            "partially_filled",
            "filled",
            "pending_cancel",
            "cancelled",
            "pending_amend",
            "rejected",
            "expired",
            "untracked",
            "triggered",
            "unknown",
            "quarantined",
            "killed",
            "held",
        ],
        Field(
            description="The persisted order state (`order_state`). Its `submitted` is the chart's `submitting` and its `accepted` the chart's `submitted`: read `lifecycle_state` for the chart state. The chart-to-database mapping is in 24-internal-schemas.md section 8.2 (added by E29-T03's implementation). **Open-ended for readers:** clients must tolerate values they do not know, so adding a state is an additive change (C-6.3). A client shows an order in a state it does not know as live (non-terminal), never as closed or gone: it ends on a known terminal state or when its id arrives in the WS `orders` frame's `removed` (23-ws-protocol.md section 15.1)."
        ),
    ]
    lifecycle_state: Annotated[
        Literal[
            "draft",
            "validated",
            "submitting",
            "submitted",
            "triggered",
            "partially_filled",
            "cancel_pending",
            "amend_pending",
            "unknown",
            "quarantined",
            "untracked",
            "held",
            "filled",
            "cancelled",
            "rejected",
            "expired",
            "killed",
        ]
        | None,
        Field(
            description="The B1 chart state of the order, verbatim; null until the OMS records it."
        ),
    ] = None
    qty: Annotated[
        str,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ]
    filled_qty: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    remaining_qty: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    price: Decimal | None = None
    avg_fill_price: Decimal | None = None
    time_in_force: Literal["GTC", "IOC", "FOK", "PostOnly"] | None = None
    reduce_only: StrictBool | None = None
    close_on_trigger: StrictBool | None = None
    position_idx: JsonInt | None = None
    trigger_price: Decimal | None = None
    trigger_by: Literal["LastPrice", "MarkPrice", "IndexPrice"] | None = None
    trigger_direction: Literal["rise", "fall"] | None = None
    take_profit: Decimal | None = None
    stop_loss: Decimal | None = None
    tpsl_mode: Literal["Full", "Partial"] | None = None
    algo: AlgoSpec | None = None
    environment: Annotated[
        Literal["live", "demo", "testnet"] | None,
        Field(
            description="Structural environment selector (arch P9). Mirrors the Postgres type `exchange_env`."
        ),
    ] = None
    rejected_reason: Annotated[
        str | None,
        Field(
            description="CandleViewer's reason, never the exchange's text, which only the audited diagnostics read serves (SR-E29-09)."
        ),
    ] = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None


class OrderEvent(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: JsonInt | None = None
    kind: Annotated[
        Literal[
            "local_create",
            "submit_attempt",
            "ack",
            "reject",
            "fill",
            "partial_fill",
            "amend_request",
            "amend_ack",
            "cancel_request",
            "cancel_ack",
            "expire",
            "exchange_push",
            "reconcile_diff",
            "error",
            "kill",
            "adopt",
        ]
        | None,
        Field(
            description="Append-only OMS event taxonomy. Exact 1:1 mirror of the Postgres type\n`order_event_kind` (`21-database-schema.md`, table `order_events`) — no supersets,\nno omissions; contract test `enum_parity_order_event_kind` asserts set equality.\n**Open-ended for readers:** clients must tolerate values they do not know, so adding a\nkind is an additive change (C-6.3).\n"
        ),
    ] = None
    event_ts: AwareDatetime | None = None


class TradeGroupDefinitionMember(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    exchange_account_id: UUID
    enabled: Annotated[
        StrictBool,
        Field(
            description="A disabled member stays in the definition, and a ticket does not target it."
        ),
    ] = True


class TradeGroupDefinitionInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: Annotated[
        str,
        Field(
            description="Unique among live definitions, compared case-insensitively (`ux_tgd_name`).",
            max_length=80,
            min_length=1,
        ),
    ]
    environment: Annotated[
        Literal["live", "demo", "testnet"],
        Field(
            description="Structural environment selector (arch P9). Mirrors the Postgres type `exchange_env`."
        ),
    ]
    members: Annotated[
        list[TradeGroupDefinitionMember],
        Field(
            description="At most 20, one per account, as a group's legs (SR-E28-17): a repeated `exchange_account_id` is `422 validation_failed` with `rule: duplicate_account`.\n",
            max_length=20,
            min_length=1,
        ),
    ]


class Member(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    exchange_account_id: UUID
    ready: StrictBool
    reason: Annotated[
        Literal[
            "member_disabled",
            "account_disabled",
            "key_invalid",
            "account_unhealthy",
            "account_locked",
            "kill_switch_engaged",
            "trading_disabled",
        ]
        | None,
        Field(
            description="Null when the member is ready, else why it is not; `member_disabled` is a member the definition disables, which `total` does not count. **Open-ended for readers:** clients must tolerate values they do not know, so adding a reason is an additive change (C-6.3); a reason a client does not know is read by `ready: false`.\n"
        ),
    ]


class TradeGroupReadiness(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    ready: Annotated[JsonInt, Field(description="The enabled members that are ready.", ge=0)]
    total: Annotated[JsonInt, Field(description="The enabled members.", ge=0)]
    members: Annotated[
        list[Member], Field(description="Every member, a disabled one included.", max_length=20)
    ]


class Overrides(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    profile_id: Annotated[
        UUID | None,
        Field(
            description="An alternate profile of this leg's account; it only narrows the bound profile. Any other id, a profile of another account (granted or not), a deleted one or one that does not exist, refuses the whole request with `404 not_found`, decided at validation, after the account-scope check and before any leg is sized, the same answer for each, never a `403` (SR-E28-03).\n"
        ),
    ] = None
    sizing: Sizing | None = None
    price: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    leverage: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    stop_loss: Offset | None = None
    take_profit: Offset | None = None
    trailing_stop: Offset | None = None
    time_in_force: Literal["GTC", "IOC", "FOK", "PostOnly"] | None = None
    tpsl_mode: Literal["Full", "Partial"] | None = None
    position_idx: Literal[0, 1, 2] | None = None
    skip: Annotated[
        StrictBool,
        Field(description="Keep the leg in the group for auditability but do not send it."),
    ] = False
    __null_refused = field_validator("profile_id", "sizing", "price", "leverage", "stop_loss", "take_profit", "trailing_stop", "time_in_force", "tpsl_mode", "position_idx", mode="before")(_refuse_null)


class TradeGroupLegInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    exchange_account_id: Annotated[
        UUID,
        Field(
            description="A leg on an account outside the caller's grants, or on one that does not exist, refuses the whole group alike with `403 account_scope_denied`, audited, before any exchange call; never a per-leg rejection (OM-E01, programme threat F1, E28 PF-E01; SR-E29-13)."
        ),
    ]
    overrides: Annotated[
        Overrides | None,
        Field(
            description="Per-leg values that only narrow the account's bound profile, after the request's `defaults` (later narrows; see `createTradeGroup`, SR-E28-03).\n"
        ),
    ] = None
    __null_refused = field_validator("overrides", mode="before")(_refuse_null)


class Defaults(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    sizing: Sizing | None = None
    price: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    time_in_force: Literal["GTC", "IOC", "FOK", "PostOnly"] | None = None
    trigger: TriggerSpec | None = None
    stop_loss: Offset | None = None
    take_profit: Offset | None = None
    trailing_stop: Offset | None = None
    tpsl_mode: Literal["Full", "Partial"] | None = None
    __null_refused = field_validator("sizing", "price", "time_in_force", "trigger", "stop_loss", "take_profit", "trailing_stop", "tpsl_mode", mode="before")(_refuse_null)


class CreateTradeGroupRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    symbol: Annotated[
        str,
        Field(
            description="Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.",
            examples=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            pattern="^[A-Z0-9]{2,20}USDT$",
        ),
    ]
    side: Literal["buy", "sell"]
    order_type: Literal["market", "limit"]
    intent: Literal[
        "entry",
        "stop_loss",
        "take_profit",
        "scale_in",
        "scale_out",
        "flatten",
        "reverse",
        "algo_child",
    ] = "entry"
    reduce_only: StrictBool = False
    atomicity: Literal["best_effort", "all_or_none"] = "best_effort"
    compensate: Annotated[
        Literal["none", "flatten_filled"],
        Field(description="Applies when `all_or_none` fails after sending."),
    ] = "none"
    max_concurrent_legs: Annotated[JsonInt, Field(ge=1, le=20)] = 5
    defaults: Defaults | None = None
    algo: AlgoSpec | None = None
    legs: Annotated[
        list[TradeGroupLegInput],
        Field(
            description="At most 20 legs, one per account (SR-E28-17; the Business-KYC sub-account ceiling of ADR-0008). Two legs on one `exchange_account_id` refuse the whole request, on `previewTradeGroup` too, with `422 validation_failed` and `rule: duplicate_account`: a check of the body alone, answered as the body's other refusals are, before any account is resolved, so it says nothing about any account.\n",
            max_length=20,
            min_length=1,
        ),
    ]
    note: Annotated[str | None, Field(max_length=280)] = None
    __null_refused = field_validator("defaults", "algo", "note", mode="before")(_refuse_null)


class ResolvedLegParams(BaseModel):
    qty: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    price: Decimal | None = None
    leverage: Annotated[
        str | None,
        Field(
            description="Persisted as `resolved_leverage`.",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    stop_loss_price: Annotated[
        str | None,
        Field(
            description="Persisted as `resolved_sl_price`. Never null - the native-stop invariant.",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    take_profit_price: Annotated[
        Decimal | None, Field(description="Persisted as `resolved_tp_price`.")
    ] = None
    trailing_stop_distance: Decimal | None = None
    notional_usd: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    risk_usd: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    estimated_fee_usd: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    sizing_explanation: Annotated[
        str | None,
        Field(
            description='Human-readable derivation, shown in the ticket\'s "why this size" tooltip.'
        ),
    ] = None


class LegError(BaseModel):
    code: Annotated[
        str | None,
        Field(description="One of the `x-error-codes` slugs; persisted as `rejection_code`."),
    ] = None
    message: Annotated[
        str | None,
        Field(
            description="Persisted as `rejection_message`: the OMS's own text for `code`, never the exchange's `ret_msg` (SR-E29-09)."
        ),
    ] = None
    exchange_ret_code: JsonInt | None = None
    retryable: StrictBool | None = None


class Totals(BaseModel):
    requested_legs: JsonInt | None = None
    submitted_legs: JsonInt | None = None
    rejected_legs: JsonInt | None = None
    filled_qty: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    target_qty: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    realised_pnl: Decimal | None = None


class Reason(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description="For `entry_refused` only: the refusing check's code, the exchange rejection's mapped code, or the venue read's code (`open_exposure`, `exchange_unavailable`), from the `x-error-codes` catalogue (for example `risk_limit_breached`, `trading_disabled`, `rate_limited`, `timeout`). A code, never free text. Null for every other `outcome`, which already says what happened.\n",
            max_length=64,
            pattern="^[a-z][a-z0-9_]*$",
        ),
    ]


class Leg(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    leg_id: UUID
    price: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    qty: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    stop_loss: Offset | None = None
    take_profit: Offset | None = None
    __null_refused = field_validator("price", "qty", mode="before")(_refuse_null)


class AmendTradeGroupRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    price: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    stop_loss: Offset | None = None
    take_profit: Offset | None = None
    trailing_stop: Offset | None = None
    legs: Annotated[
        list[Leg] | None,
        Field(
            description="Per-leg amendments; when present, the top-level fields are ignored for those legs.",
            max_length=20,
        ),
    ] = None
    __null_refused = field_validator("price", "legs", mode="before")(_refuse_null)


class Result(BaseModel):
    exchange_account_id: UUID | None = None
    ok: StrictBool | None = None
    affected: JsonInt | None = None
    error: LegError | None = None


class BulkAccountResult(BaseModel):
    results: list[Result] | None = None
    requested: JsonInt | None = None
    succeeded: JsonInt | None = None


class Result1(BaseModel):
    leg_id: UUID | None = None
    exchange_account_id: UUID | None = None
    ok: StrictBool | None = None
    affected: JsonInt | None = None
    error: LegError | None = None


class BulkLegResult(BaseModel):
    trade_group_id: UUID | None = None
    results: list[Result1] | None = None
    requested: JsonInt | None = None
    succeeded: JsonInt | None = None


class KillSwitch(BaseModel):
    engaged: StrictBool
    scope: Literal["global", "accounts"]
    exchange_account_ids: list[UUID] | None = None
    engaged_at: AwareDatetime | None = None
    engaged_by: UUID | None = None
    reason: str | None = None


class SetKillSwitchRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    engaged: StrictBool
    scope: Literal["global", "accounts"]
    exchange_account_ids: list[UUID] | None = None
    cancel_open_orders: StrictBool = True
    flatten_positions: StrictBool = False
    disarm_rules: StrictBool = True
    reason: Annotated[str, Field(max_length=280, min_length=3)]
    __null_refused = field_validator("exchange_account_ids", mode="before")(_refuse_null)


class Failure(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    exchange_account_id: UUID | None = None
    ok: StrictBool | None = None
    affected: JsonInt | None = None
    error: LegError | None = None


class Actions(BaseModel):
    orders_cancelled: JsonInt | None = None
    positions_flattened: JsonInt | None = None
    rules_disarmed: JsonInt | None = None
    failures: Annotated[
        list[Failure] | None,
        Field(
            description="The accounts whose cancel or flatten failed at the exchange, shaped as `BulkAccountResult` rows; `error` is CandleViewer's code, never the exchange's text (SR-E29-09).\n"
        ),
    ] = None


class KillSwitchResult(BaseModel):
    state: KillSwitch | None = None
    actions: Actions | None = None


class Position(BaseModel):
    is_paper: Annotated[
        StrictBool,
        Field(
            description="True when the paper matcher produced this record rather than the exchange. Orthogonal to `environment` (24-internal-schemas.md section 1.2)."
        ),
    ] = False
    id: UUID
    exchange_account_id: UUID
    symbol: Annotated[
        str,
        Field(
            description="Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.",
            examples=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            pattern="^[A-Z0-9]{2,20}USDT$",
        ),
    ]
    side: Literal["long", "short", "flat"]
    position_idx: Literal[0, 1, 2] | None = None
    size: Annotated[
        str,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ]
    avg_price: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    mark_price: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    position_value: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    leverage: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    margin_mode: Literal["cross", "isolated", "portfolio"] | None = None
    unrealised_pnl: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    realised_pnl_session: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    liq_price: Decimal | None = None
    bust_price: Decimal | None = None
    take_profit: Decimal | None = None
    stop_loss: Decimal | None = None
    trailing_stop: Annotated[
        str | None,
        Field(
            description="Price distance, not a percentage (Bybit semantics).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    tpsl_mode: Literal["Full", "Partial"] | None = None
    native_stop_present: Annotated[
        StrictBool | None,
        Field(
            description="False is an alarm condition; the OMS re-asserts the stop and raises a critical alert."
        ),
    ] = None
    trade_group_id: UUID | None = None
    r_multiple: Decimal | None = None
    updated_at: AwareDatetime | None = None


class Account(BaseModel):
    exchange_account_id: UUID | None = None
    size: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    side: Literal["long", "short"] | None = None
    unrealised_pnl: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None


class AggregatePosition(BaseModel):
    symbol: Annotated[
        str | None,
        Field(
            description="Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.",
            examples=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            pattern="^[A-Z0-9]{2,20}USDT$",
        ),
    ] = None
    net_size: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    gross_size: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    weighted_avg_price: Annotated[
        str | None,
        Field(
            description="The quantity-weighted average entry price of the legs when every leg is on one side. Absent when the legs mix sides (decision D3, ruled on #915): an average across a long and a short is no price anyone can trade against.\n",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    unrealised_pnl: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    accounts: list[Account] | None = None


class SetTpSlRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    take_profit: Offset | None = None
    stop_loss: Offset | None = None
    trailing_stop: Offset | None = None
    activation_price: Annotated[
        str | None,
        Field(
            description="Arms the trailing stop only once price reaches this level. Omitted, it arms at once, and its record takes the `sl_trigger_by` price the writer reads as its activation price (24-internal-schemas.md section 8.8 rule 6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    tpsl_mode: Literal["Full", "Partial"] | None = None
    tp_size: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    sl_size: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    tp_trigger_by: Literal["LastPrice", "MarkPrice", "IndexPrice"] | None = None
    sl_trigger_by: Literal["LastPrice", "MarkPrice", "IndexPrice"] | None = None
    __null_refused = field_validator("activation_price", "tpsl_mode", "tp_size", "sl_size", "tp_trigger_by", "sl_trigger_by", mode="before")(_refuse_null)


class TpSlResult(BaseModel):
    position_id: UUID | None = None
    take_profit: Decimal | None = None
    stop_loss: Decimal | None = None
    trailing_stop_distance: Decimal | None = None
    trailing_stop_requested: Offset | None = None
    activation_price: Decimal | None = None
    tpsl_mode: Literal["Full", "Partial"] | None = None
    applied_at: AwareDatetime | None = None


class ClosePositionRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    order_type: Literal["market", "limit"]
    price: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    pct: Annotated[
        str | None,
        Field(
            description="0 < pct <= 100. Mutually exclusive with `qty`.",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    qty: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    time_in_force: Literal["GTC", "IOC", "FOK", "PostOnly"] | None = None
    __null_refused = field_validator("price", "pct", "qty", "time_in_force", mode="before")(_refuse_null)


class ReversePositionRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    size_mode: Annotated[
        Literal["profile"],
        Field(
            description="The entry is always sized by the account profile (C-12.5); `same` and `custom` were removed before the route was implemented (#915).\n"
        ),
    ] = "profile"
    order_type: Annotated[Literal["market", "limit"], Field(description="The entry's.")] = "market"
    price: Annotated[
        str | None,
        Field(
            description="The entry's limit price.",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    __null_refused = field_validator("price", mode="before")(_refuse_null)


class Execution(BaseModel):
    is_paper: Annotated[
        StrictBool,
        Field(
            description="True when the paper matcher produced this record rather than the exchange. Orthogonal to `environment` (24-internal-schemas.md section 1.2)."
        ),
    ] = False
    id: UUID | None = None
    exec_id: str | None = None
    order_id: UUID | None = None
    exchange_account_id: UUID | None = None
    trade_group_id: UUID | None = None
    symbol: Annotated[
        str | None,
        Field(
            description="Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.",
            examples=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            pattern="^[A-Z0-9]{2,20}USDT$",
        ),
    ] = None
    side: Literal["buy", "sell"] | None = None
    exec_qty: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    exec_price: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    exec_value: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    fee: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    fee_rate: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    fee_coin: str | None = None
    is_maker: StrictBool | None = None
    exec_type: Literal["Trade", "AdlTrade", "Funding", "BustTrade", "Settle"] | None = None
    exec_pnl: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    ts: AwareDatetime | None = None


class ClosedPnl(BaseModel):
    id: UUID | None = None
    exchange_account_id: UUID | None = None
    symbol: Annotated[
        str | None,
        Field(
            description="Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.",
            examples=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            pattern="^[A-Z0-9]{2,20}USDT$",
        ),
    ] = None
    side: Literal["long", "short"] | None = None
    qty: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    avg_entry_price: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    avg_exit_price: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    closed_pnl: Annotated[
        str | None,
        Field(
            description="Net of fees, as the venue's closed-PnL endpoint reports it (#915).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    cum_entry_value: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    cum_exit_value: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    leverage: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    opened_at: AwareDatetime | None = None
    closed_at: AwareDatetime | None = None


class RuleOperand1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    const: str | StrictFloat | StrictBool


class RuleMetricRef(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    metric: Annotated[str, Field(pattern="^[a-z][a-z0-9_]{1,48}$")]
    params: dict[str, Any] | None = None
    symbol: Symbol | None = None
    account_id: UUID | None = None
    timeframe: str | None = None
    __null_refused = field_validator("params", mode="before")(_refuse_null)


class RuleAction(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    node_id: str
    type: Annotated[
        Literal[
            "place_order",
            "modify_stop_loss",
            "modify_take_profit",
            "cancel_order",
            "cancel_all_orders",
            "move_to_breakeven",
            "scale_out",
            "scale_in",
            "flatten_position",
            "flatten_all_positions",
            "reverse_position",
            "halt_new_orders",
            "resume_new_orders",
            "reduce_leverage",
            "widen_stop",
            "tighten_stop",
            "arm_chase_limit",
            "start_iceberg_slice",
            "start_twap",
            "send_notification",
            "log_journal_tag",
            "set_variable",
            "emit_signal",
            "pause_rule",
            "enable_rule",
        ],
        Field(
            description="Order-sending actions (`place_order`, `flatten_*`, `reverse_position`,\n`scale_in`, `scale_out`, `modify_*`, `cancel_*`, `reduce_leverage`,\n`arm_chase_limit`, `start_*`) require the rule to be `armed` and the author to\nhold `orders:write` on every bound account. An action that could loosen a stop\nis refused for every role (`stop_loosening`, 24-internal-schemas.md section 8.8\nrule 5): `widen_stop` is retired and stays in this enum only so stored documents\nkeep their hashes.\n"
        ),
    ]
    params: Annotated[
        dict[str, Any], Field(description="Validated against a per-action JSON Schema.")
    ]
    on_error: Literal["abort_remaining", "continue", "retry_once"] = "abort_remaining"
    targets: Literal["scope_accounts", "originating_account", "all_accounts"] = "scope_accounts"
    dry_run_only: StrictBool = False


class RuleLimits(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    once: StrictBool = False
    once_per: Literal["position", "day", "group", "rule_lifetime"] | None = None
    cooldown_ms: Annotated[JsonInt, Field(ge=0)] = 1000
    max_fires_per_hour: Annotated[JsonInt, Field(ge=1)] = 60
    max_fires_per_day: Annotated[JsonInt, Field(ge=1)] = 500
    max_actions_per_fire: Annotated[JsonInt, Field(ge=1, le=10)] = 10
    max_notional_per_fire: Decimal | None = None
    max_daily_notional: Decimal | None = None
    require_confirmation: StrictBool = False
    evaluation_timeout_ms: Annotated[JsonInt, Field(ge=10, le=5000)] = 250
    kill_switch_on_error_count: Annotated[JsonInt, Field(ge=1)] = 5


class RuleTrigger(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: Literal[
        "on_price_update",
        "on_bar_close",
        "on_order_fill",
        "on_position_open",
        "on_position_close",
        "on_position_update",
        "on_timer",
        "on_metric_change",
        "on_signal",
        "on_schedule",
        "pre_trade_check",
        "on_book_update",
        "on_liquidation",
    ]
    timeframe: Annotated[str | None, Field(description="Required for `on_bar_close`.")] = None
    interval_ms: Annotated[
        JsonInt | None, Field(description="Required for `on_timer`.", ge=100)
    ] = None
    cron: Annotated[
        str | None, Field(description="Required for `on_schedule`; 5-field UTC cron.")
    ] = None
    metric: Annotated[str | None, Field(description="Required for `on_metric_change`.")] = None
    debounce_ms: Annotated[JsonInt, Field(ge=0)] = 0


class RuleIrScope(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    level: Literal["global", "account", "symbol", "position", "trade_group"]
    account_ids: list[UUID] = []
    symbols: Annotated[list[Symbol], Field(validate_default=True)] = []
    applies_to: Literal["open_positions", "pending_orders", "account", "any"] = "any"
    environments: list[Literal["live", "demo", "testnet"]] = ["demo"]
    exclude_algo_children: StrictBool = True


class RuleBindings(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    exchange_account_ids: list[UUID] | None = None
    symbols: list[Symbol] | None = None
    trade_group_ids: list[UUID] | None = None


class Tag(RootModel[str]):
    root: Annotated[str, Field(max_length=40)]


class Rule(BaseModel):
    id: UUID
    name: str
    description: str | None = None
    mode: Literal["disabled", "simulate", "armed"]
    scope: Literal["global", "account", "symbol", "position", "trade_group"]
    editor: Literal["form", "graph"] | None = None
    tags: list[str] | None = None
    active_version_id: UUID | None = None
    version: JsonInt | None = None
    bindings: Annotated[
        RuleBindings | None,
        Field(
            description="Never emitted: the accounts a rule applies to are its IR's `scope.account_ids`, and a later contract delta removes this member."
        ),
    ] = None
    last_run_at: AwareDatetime | None = None
    last_run_status: Literal["running", "ok", "error", "aborted", "throttled"] | None = None
    fire_count_24h: JsonInt | None = None
    created_by: UUID | None = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None


class LastSimulation(BaseModel):
    run_id: UUID | None = None
    ir_hash: str | None = None
    completed_at: AwareDatetime | None = None
    fires: JsonInt | None = None


class RuleVersion(BaseModel):
    id: UUID | None = None
    rule_id: UUID | None = None
    version: JsonInt | None = None
    ir_hash: str | None = None
    is_active: StrictBool | None = None
    created_by: UUID | None = None
    created_at: AwareDatetime | None = None
    note: str | None = None


class RuleValidationIssue(BaseModel):
    path: str | None = None
    code: (
        Literal[
            "schema_error",
            "unknown_variable",
            "unknown_function",
            "type_mismatch",
            "unreachable_branch",
            "guard_missing",
            "missing_action_param",
            "permission_required",
            "native_stop_missing",
            "unsupported_symbol",
            "unknown_metric",
            "operator_not_applicable",
            "cycle_detected",
            "dangling_port",
            "orphan_node",
            "multiple_sinks",
            "feedback_loop",
            "native_stop_violation",
            "high_frequency",
            "stop_loosening",
            "action_unavailable",
        ]
        | None
    ) = None
    message: str | None = None
    severity: Literal["error", "warning"] | None = None
    class_: Annotated[
        Literal["syntax", "semantics", "safety", "performance"] | None, Field(alias="class")
    ] = None


class RuleValidationResult(BaseModel):
    valid: StrictBool
    errors: list[RuleValidationIssue]
    warnings: list[RuleValidationIssue]
    referenced_variables: list[str] | None = None
    referenced_actions: list[str] | None = None
    estimated_evaluations_per_minute: JsonInt | None = None
    blocks_arming: Annotated[
        StrictBool | None,
        Field(description="True when any error or open safety warning refuses mode=armed."),
    ] = None


class SimulateRuleRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    version_id: Annotated[UUID | None, Field(description="Defaults to the active version.")] = None
    from_: Annotated[AwareDatetime | None, Field(alias="from")] = None
    to: AwareDatetime | None = None
    replay_session_id: UUID | None = None
    symbols: list[Symbol] | None = None
    exchange_account_ids: list[UUID] | None = None
    speed: Annotated[StrictFloat, Field(ge=0.0, le=100.0)] = 0
    starting_equity_usd: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    __null_refused = field_validator("version_id", "from_", "to", "replay_session_id", "symbols", "exchange_account_ids", "starting_equity_usd", mode="before")(_refuse_null)


class Action(BaseModel):
    ts: AwareDatetime | None = None
    action: str | None = None
    params: dict[str, Any] | None = None
    would_have_succeeded: StrictBool | None = None
    symbol: Annotated[
        str | None,
        Field(
            description="Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.",
            examples=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            pattern="^[A-Z0-9]{2,20}USDT$",
        ),
    ] = None
    exchange_account_id: UUID | None = None


class RuleSimulationResult(BaseModel):
    run_id: UUID | None = None
    rule_id: UUID | None = None
    version_id: UUID | None = None
    from_: Annotated[AwareDatetime | None, Field(alias="from")] = None
    to: AwareDatetime | None = None
    evaluations: JsonInt | None = None
    fires: JsonInt | None = None
    suppressed_by_guard: JsonInt | None = None
    actions: list[Action] | None = None
    hypothetical_pnl_delta_usd: Decimal | None = None
    errors: list[str] | None = None
    duration_ms: JsonInt | None = None


class RuleRun(BaseModel):
    id: UUID | None = None
    rule_id: UUID | None = None
    rule_version_id: UUID | None = None
    kind: Literal["live", "simulation"] | None = None
    status: Literal["running", "ok", "error", "aborted", "throttled"] | None = None
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    evaluations: JsonInt | None = None
    fires: JsonInt | None = None
    errors: JsonInt | None = None
    error_message: str | None = None


class RuleEvent(BaseModel):
    id: JsonInt | None = None
    ts: AwareDatetime | None = None
    kind: (
        Literal[
            "evaluated",
            "suppressed",
            "action_sent",
            "action_result",
            "error",
            "started",
            "finished",
        ]
        | None
    ) = None
    payload: dict[str, Any] | None = None


class AlertDelivery(BaseModel):
    id: JsonInt | None = None
    alert_id: UUID | None = None
    channel: Literal["in_app", "email", "webhook", "push", "desktop"] | None = None
    status: Literal["queued", "sent", "failed", "suppressed", "acked"] | None = None
    severity: Literal["debug", "info", "warning", "error", "critical"] | None = None
    title: str | None = None
    message: Annotated[
        str | None,
        Field(description="The delivery row `body`, falling back to `title` when `body` is empty."),
    ] = None
    symbol: Symbol | None = None
    fired_at: AwareDatetime | None = None
    acked_at: AwareDatetime | None = None
    error: str | None = None


class JournalTrade(BaseModel):
    id: UUID | None = None
    trade_group_id: UUID | None = None
    exchange_account_id: UUID | None = None
    symbol: Annotated[
        str | None,
        Field(
            description="Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.",
            examples=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            pattern="^[A-Z0-9]{2,20}USDT$",
        ),
    ] = None
    side: Literal["long", "short"] | None = None
    opened_at: AwareDatetime | None = None
    closed_at: AwareDatetime | None = None
    qty: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    avg_entry_price: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    avg_exit_price: Decimal | None = None
    gross_pnl: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    fees: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    realised_pnl: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    r_multiple: Decimal | None = None
    max_favourable_excursion: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    max_adverse_excursion: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    duration_seconds: JsonInt | None = None
    outcome: Literal["win", "loss", "breakeven", "open"] | None = None
    rating: Annotated[JsonInt | None, Field(ge=1, le=5)] = None
    tags: list[str] | None = None
    setup: str | None = None
    notes_count: JsonInt | None = None


class Mistake(RootModel[str]):
    root: Annotated[str, Field(max_length=120)]


class UpdateJournalTradeRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    rating: Annotated[JsonInt | None, Field(ge=1, le=5)] = None
    tags: list[Tag] | None = None
    setup: Annotated[str | None, Field(max_length=200)] = None
    mistakes: list[Mistake] | None = None
    checklist: list[dict[str, Any]] | None = None
    __null_refused = field_validator("tags", "mistakes", "checklist", mode="before")(_refuse_null)


class NoteInput(BaseModel):
    body: Annotated[str, Field(description="Markdown.", max_length=20000, min_length=1)]
    snapshot_ref: Annotated[
        str | None, Field(description="Reference to a stored chart snapshot.")
    ] = None


class Note(NoteInput):
    id: UUID | None = None
    author_user_id: UUID | None = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None


class Totals1(BaseModel):
    trades: JsonInt | None = None
    wins: JsonInt | None = None
    losses: JsonInt | None = None
    breakeven: JsonInt | None = None
    win_rate: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    gross_profit: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    gross_loss: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    net_pnl: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    fees: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    profit_factor: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    expectancy_r: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    avg_win_r: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    avg_loss_r: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    max_drawdown: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    max_drawdown_pct: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    longest_win_streak: JsonInt | None = None
    longest_loss_streak: JsonInt | None = None


class EquityCurveItem(BaseModel):
    t: AwareDatetime | None = None
    equity: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    pnl: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None


class Row(BaseModel):
    key: str | None = None
    trades: JsonInt | None = None
    win_rate: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    net_pnl: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    expectancy_r: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None


class Breakdown(BaseModel):
    group_by: str | None = None
    rows: list[Row] | None = None


class JournalAnalytics(BaseModel):
    totals: Totals1 | None = None
    equity_curve: list[EquityCurveItem] | None = None
    breakdowns: list[Breakdown] | None = None
    generated_at: AwareDatetime | None = None


class WorkspaceInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: Annotated[
        str,
        Field(
            description="At most 40 characters as sent, at least 1 after sanitising (above), SCR-020. Unique per user, case-insensitive, among live workspaces (`409 conflict`, rule `name_taken`).",
            max_length=40,
            min_length=1,
        ),
    ]
    is_default: Annotated[
        StrictBool,
        Field(
            description="At most one live default per user; `true` clears the previous default in the same transaction."
        ),
    ] = False
    icon_token: Annotated[
        Literal["workspace.default"],
        Field(
            description="Design-system icon token for the workspace (a token name, never a URL or markup).\n**Open-ended for readers:** clients must tolerate values they do not know, so adding a token\nis an additive change (C-6.3). Writers must send a listed value; the server keeps the same\nallow-list. `workspace.default` is the only token until the design-system icon registry\n(CMP-019) publishes workspace icons.\n"
        ),
    ] = "workspace.default"
    sort_order: Annotated[
        JsonInt,
        Field(description="Client-defined tab order; ties break by `id`.", ge=0, le=32767),
    ] = 0


class Workspace(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    is_default: StrictBool
    icon_token: Annotated[
        Literal["workspace.default"],
        Field(
            description="Design-system icon token for the workspace (a token name, never a URL or markup).\n**Open-ended for readers:** clients must tolerate values they do not know, so adding a token\nis an additive change (C-6.3). Writers must send a listed value; the server keeps the same\nallow-list. `workspace.default` is the only token until the design-system icon registry\n(CMP-019) publishes workspace icons.\n"
        ),
    ]
    sort_order: Annotated[JsonInt, Field(ge=0, le=32767)]
    layout_count: Annotated[JsonInt, Field(description="Live layouts.", ge=0, le=32)]
    created_at: AwareDatetime
    updated_at: Annotated[
        AwareDatetime,
        Field(
            description="Concurrency token (also the `ETag`) for the workspace metadata only; layout writes do not change it. Always exactly 6 fractional digits plus `Z` (`YYYY-MM-DDTHH:MM:SS.ffffffZ`) and strictly increasing on every write. Echo it exactly as received; never re-serialise it through a client date type."
        ),
    ]


class Size(RootModel[StrictFloat]):
    root: Annotated[StrictFloat, Field(gt=0.0, le=1.0)]


class LayoutGridLeaf(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: Literal["leaf"]
    slot: Annotated[
        JsonInt, Field(description="`slot_index` of a pane in the same layout.", ge=0, le=15)
    ]


class PaneIntervalCode(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description="`<bar_type>:<param>`, exactly the `bar_type` and `param` of `/market/bars` (and of the WS topic `bars.{symbol}.{bar_type}.{param}`): `param` at most 24 characters, no leading zeros, and no trailing zeros in a `volume`/`delta` fraction, so each value has one spelling (`volume:0.5`, never `volume:0.50`), e.g. `time:1`, `time:D`, `tick:500`, `volume:0.5`, `renko:atr:14`, `pnf:10:3`. A `volume` or `delta` threshold must also be greater than 0 (`422` rule `interval_not_positive`).",
            examples=["time:1", "time:240", "tick:500", "renko:atr:14"],
            max_length=36,
            pattern="^(time|heikin_ashi):(1|3|5|15|30|60|120|240|360|720|D|W|M)$|^(tick|range):[1-9][0-9]{0,8}$|^(volume|delta):(0|[1-9][0-9]{0,10})(\\.[0-9]{0,11}[1-9])?$|^renko:([1-9][0-9]{0,8}|atr:[1-9][0-9]{0,2})$|^pnf:[1-9][0-9]{0,8}:[1-9][0-9]{0,2}$",
        ),
    ]


class PaneSettingValue1(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description="A flat setting value: a string, an integer or other finite number (each keeps its kind), a boolean, `null`, or an array of at most 32 such strings, numbers or booleans; objects are not allowed. Strings, also inside arrays, are at most 256 characters as sent and are then sanitised like `WorkspaceInput.name` (the name strip set and trimming), except that an empty result is kept; a lone surrogate is rule `invalid_unicode`. Numbers, also inside arrays, lie within ±1e15, so they read back with the same kind and value. A non-zero number must have |x| ≥ 1e-15 (`number_out_of_range`); zero is allowed. `-0.0` is stored as `0.0`.",
            max_length=256,
        ),
    ]


class PaneSettingValue2(RootModel[JsonInt]):
    root: Annotated[
        JsonInt,
        Field(
            description="A flat setting value: a string, an integer or other finite number (each keeps its kind), a boolean, `null`, or an array of at most 32 such strings, numbers or booleans; objects are not allowed. Strings, also inside arrays, are at most 256 characters as sent and are then sanitised like `WorkspaceInput.name` (the name strip set and trimming), except that an empty result is kept; a lone surrogate is rule `invalid_unicode`. Numbers, also inside arrays, lie within ±1e15, so they read back with the same kind and value. A non-zero number must have |x| ≥ 1e-15 (`number_out_of_range`); zero is allowed. `-0.0` is stored as `0.0`.",
            ge=-1000000000000000,
            le=1000000000000000,
        ),
    ]


class PaneSettingValue3(RootModel[StrictFloat]):
    root: Annotated[
        StrictFloat,
        Field(
            description="A flat setting value: a string, an integer or other finite number (each keeps its kind), a boolean, `null`, or an array of at most 32 such strings, numbers or booleans; objects are not allowed. Strings, also inside arrays, are at most 256 characters as sent and are then sanitised like `WorkspaceInput.name` (the name strip set and trimming), except that an empty result is kept; a lone surrogate is rule `invalid_unicode`. Numbers, also inside arrays, lie within ±1e15, so they read back with the same kind and value. A non-zero number must have |x| ≥ 1e-15 (`number_out_of_range`); zero is allowed. `-0.0` is stored as `0.0`.",
            ge=-1000000000000000.0,
            le=1000000000000000.0,
        ),
    ]


class PaneSettingValue41(RootModel[str]):
    root: Annotated[str, Field(max_length=256)]


class PaneSettingValue42(RootModel[JsonInt]):
    root: Annotated[JsonInt, Field(ge=-1000000000000000, le=1000000000000000)]


class PaneSettingValue43(RootModel[StrictFloat]):
    root: Annotated[StrictFloat, Field(ge=-1000000000000000.0, le=1000000000000000.0)]


class PaneSettingValue4(
    RootModel[list[PaneSettingValue41 | PaneSettingValue42 | PaneSettingValue43 | StrictBool]]
):
    root: Annotated[
        list[PaneSettingValue41 | PaneSettingValue42 | PaneSettingValue43 | StrictBool],
        Field(
            description="A flat setting value: a string, an integer or other finite number (each keeps its kind), a boolean, `null`, or an array of at most 32 such strings, numbers or booleans; objects are not allowed. Strings, also inside arrays, are at most 256 characters as sent and are then sanitised like `WorkspaceInput.name` (the name strip set and trimming), except that an empty result is kept; a lone surrogate is rule `invalid_unicode`. Numbers, also inside arrays, lie within ±1e15, so they read back with the same kind and value. A non-zero number must have |x| ≥ 1e-15 (`number_out_of_range`); zero is allowed. `-0.0` is stored as `0.0`.",
            max_length=32,
        ),
    ]


class PaneConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    sync_group: Annotated[
        Literal["A", "B", "C"] | None,
        Field(
            description="Cross-pane sync group (SCR-023); `null` or omitted means not synced. The axis defaults live on the layout (`crosshair_sync`, `symbol_sync`, `level_sync`)."
        ),
    ] = None
    settings: Annotated[
        dict[
            str,
            PaneSettingValue1
            | PaneSettingValue2
            | PaneSettingValue3
            | StrictBool
            | PaneSettingValue4
            | None,
        ]
        | None,
        Field(
            description="Kind-specific flat settings (for example DOM depth, tape filters, CVD anchor, visible range), at most 32 keys. Every key must match `^[a-z][a-z0-9_]{0,31}$` (`422` rule `invalid_setting_key`); the server enforces this because generators cannot express key patterns. Numbers keep their kind (`1` stays `1`, `1.0` stays `1.0`). Omitted means `{}`.",
            max_length=32,
        ),
    ] = None
    __null_refused = field_validator("settings", mode="before")(_refuse_null)


class LayoutPaneInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    slot_index: Annotated[
        JsonInt,
        Field(description="Unique within the layout (`422` rule `duplicate_slot`).", ge=0, le=15),
    ]
    pane_kind: Annotated[
        Literal[
            "chart",
            "dom",
            "tape",
            "profile",
            "cvd",
            "oi",
            "deep_stats",
            "regime",
            "positions",
            "journal",
            "watchlist",
            "alerts",
            "scanner",
        ],
        Field(
            description="Pane kind (`lp_kind`, `21-database-schema.md` §3.8.1). **Open-ended for readers:** clients\nmust tolerate values they do not know, so adding a kind is an additive change (C-6.3);\nwriters must send a listed value. Market panes (`chart`, `dom`, `tape`, `profile`, `cvd`,\n`oi`, `deep_stats`, `regime`) may bind a `symbol` and `interval_code`; account panes\n(`positions`, `journal`, `watchlist`, `alerts`) show many symbols and carry neither (rule\n`property_not_allowed_for_kind`). `scanner` (SCR-104) also shows many symbols and carries\nneither, but holds no account data: its rows are `runScanner`'s public market values;\nE08-T09 PR 2a (`0054_scanner_presets`) added it to `lp_kind`. A heatmap lives in the\n`dom` pane and orders in the `positions` pane. A footprint is a `chart` pane; until chart\ntemplates exist (#2411) it is marked by `pane_config.settings.footprint: true`, its\noptions as further flat `footprint_*` settings.\n"
        ),
    ]
    symbol: Annotated[
        str | None,
        Field(
            description="Bound symbol, market panes only: a Bybit USDT linear perpetual symbol of at most 20 characters (the DB `symbol_code` domain). It is not checked against the instrument catalogue. A non-null symbol on a live layout counts as chart-open for auto-recording.",
            pattern="^[A-Z0-9]{2,16}USDT$",
        ),
    ] = None
    interval_code: Annotated[
        PaneIntervalCode | None,
        Field(description="Bar series of a market pane; `null` for panes without one."),
    ] = None
    chart_template_id: Annotated[
        UUID | None,
        Field(
            description="Chart template reference. Every non-null value is refused (`422` rule `chart_template_not_found`) until `chart_templates` ships; then it must name a template the caller may use."
        ),
    ] = None
    indicator_preset_ids: Annotated[
        list[UUID] | None,
        Field(
            description="Indicator preset references; omitted means `[]`. A non-empty list is refused (`422` rule `indicator_preset_not_found`) until panes resolve preset references; the preset store alone (E13-T03) does not lift this. Then every id must name a preset the caller may use.",
            max_length=16,
        ),
    ] = None
    pane_config: PaneConfig | None = None
    scale_mode: Annotated[
        Literal["auto", "linked", "manual", "log"],
        Field(description="Price-scale behaviour (`lp_scale`). **Open-ended for readers.**"),
    ] = "auto"
    __null_refused = field_validator("indicator_preset_ids", "pane_config", mode="before")(_refuse_null)


class LayoutPane(BaseModel):
    slot_index: Annotated[JsonInt, Field(ge=0, le=15)]
    pane_kind: Annotated[
        Literal[
            "chart",
            "dom",
            "tape",
            "profile",
            "cvd",
            "oi",
            "deep_stats",
            "regime",
            "positions",
            "journal",
            "watchlist",
            "alerts",
            "scanner",
        ],
        Field(
            description="Pane kind (`lp_kind`, `21-database-schema.md` §3.8.1). **Open-ended for readers:** clients\nmust tolerate values they do not know, so adding a kind is an additive change (C-6.3);\nwriters must send a listed value. Market panes (`chart`, `dom`, `tape`, `profile`, `cvd`,\n`oi`, `deep_stats`, `regime`) may bind a `symbol` and `interval_code`; account panes\n(`positions`, `journal`, `watchlist`, `alerts`) show many symbols and carry neither (rule\n`property_not_allowed_for_kind`). `scanner` (SCR-104) also shows many symbols and carries\nneither, but holds no account data: its rows are `runScanner`'s public market values;\nE08-T09 PR 2a (`0054_scanner_presets`) added it to `lp_kind`. A heatmap lives in the\n`dom` pane and orders in the `positions` pane. A footprint is a `chart` pane; until chart\ntemplates exist (#2411) it is marked by `pane_config.settings.footprint: true`, its\noptions as further flat `footprint_*` settings.\n"
        ),
    ]
    symbol: Annotated[str | None, Field(pattern="^[A-Z0-9]{2,16}USDT$")]
    interval_code: PaneIntervalCode | None
    chart_template_id: UUID | None
    indicator_preset_ids: Annotated[list[UUID], Field(max_length=16)]
    pane_config: PaneConfig
    scale_mode: Annotated[
        Literal["auto", "linked", "manual", "log"],
        Field(description="Price-scale behaviour (`lp_scale`). **Open-ended for readers.**"),
    ]


class Footprint(BaseModel):
    cell_type: Literal["volume", "bid_ask", "delta", "delta_total"] | None = None
    display_mode: Literal["profile", "box"] | None = None
    price_grouping: JsonInt | None = None
    imbalance_ratio: StrictFloat | None = None
    min_stack: JsonInt | None = None
    show_unfinished_auctions: StrictBool | None = None
    __null_refused = field_validator("cell_type", "display_mode", "price_grouping", "imbalance_ratio", "min_stack", "show_unfinished_auctions", mode="before")(_refuse_null)


class Indicator(BaseModel):
    code: str | None = None
    params: dict[str, Any] | None = None
    pane: Literal["main", "sub1", "sub2", "sub3"] | None = None
    __null_refused = field_validator("code", "params", "pane", mode="before")(_refuse_null)


class PriceScale(BaseModel):
    mode: Literal["linear", "logarithmic", "percent"] | None = None
    auto_fit: StrictBool | None = None
    right_margin_bars: JsonInt | None = None
    __null_refused = field_validator("mode", "auto_fit", "right_margin_bars", mode="before")(_refuse_null)


class Config(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    chart_type: (
        Literal[
            "candlestick",
            "hollow_candlestick",
            "bar",
            "line",
            "area",
            "baseline",
            "step_line",
            "equi_volume",
            "delta_volume",
            "heikin_ashi",
        ]
        | None
    ) = None
    bar_type: (
        Literal["time", "tick", "volume", "range", "delta", "renko", "pnf", "heikin_ashi"] | None
    ) = None
    param: str | None = None
    footprint: Footprint | None = None
    indicators: list[Indicator] | None = None
    colours: dict[str, str] | None = None
    price_scale: PriceScale | None = None
    __null_refused = field_validator("chart_type", "bar_type", "param", "footprint", "indicators", "colours", "price_scale", mode="before")(_refuse_null)


class ChartTemplateInput(BaseModel):
    name: Annotated[str, Field(max_length=80, min_length=1)]
    shared: StrictBool = False
    config: Annotated[
        Config,
        Field(
            description="Chart configuration blob; validated against the chart-engine schema in `26-chart-engine-design.md`."
        ),
    ]


class ChartTemplate(ChartTemplateInput):
    id: UUID | None = None
    owner_user_id: UUID | None = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None


class DrawingPoint(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    t: Annotated[
        str,
        Field(
            description="RFC 3339 UTC instant with `Z`, at most millisecond precision, years 2000-2099.",
            examples=["2026-09-13T12:00:00Z", "2026-09-13T12:00:00.250Z"],
            pattern="^20[0-9]{2}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](\\.[0-9]{1,3})?Z$",
        ),
    ]
    p: Annotated[
        str,
        Field(
            description="Chart-space price coordinate as a decimal string; may be negative. Stored and returned verbatim, never converted to a float.",
            examples=["61200.00", "-12.5"],
            pattern="^-?(0|[1-9][0-9]{0,14})(\\.[0-9]{1,12})?$",
        ),
    ]


class Level(RootModel[StrictFloat]):
    root: Annotated[
        StrictFloat,
        Field(
            description="A non-zero number must have |x| ≥ 1e-6 (`number_out_of_range`); zero is allowed. `-0.0` is stored as `0.0`.",
            ge=-1000.0,
            le=1000.0,
        ),
    ]


class DrawingGeometry(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    points: Annotated[list[DrawingPoint], Field(max_length=500, min_length=1)]
    extend_left: StrictBool | None = None
    extend_right: StrictBool | None = None
    levels: Annotated[
        list[Level] | None,
        Field(
            description="Fibonacci levels (fib tools only): unique finite numbers; a duplicate is rule `duplicate_level`. Non-zero items must have |x| ≥ 1e-6 (`number_out_of_range`).",
            max_length=24,
            min_length=1,
        ),
    ] = None
    bands: Annotated[
        list[Literal[1, 2, 3]] | None,
        Field(
            description="Standard-deviation bands (`anchored_vwap` only).",
            max_length=3,
            min_length=1,
        ),
    ] = None
    text: Annotated[
        str | None,
        Field(
            description="Text content (`text` and `callout` only), 1..1000 code points after control-character stripping (LF is kept).",
            max_length=1000,
            min_length=1,
        ),
    ] = None
    __null_refused = field_validator("extend_left", "extend_right", "levels", "bands", "text", mode="before")(_refuse_null)


class DrawingStyle(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    colour: Annotated[str | None, Field(pattern="^#[0-9a-fA-F]{6}$")] = None
    fill_colour: Annotated[str | None, Field(pattern="^#[0-9a-fA-F]{6}$")] = None
    fill_opacity: Annotated[
        StrictFloat | None,
        Field(
            description="A non-zero number must have |x| ≥ 1e-6 (`number_out_of_range`); zero is allowed. `-0.0` is stored as `0.0`.",
            ge=0.0,
            le=1.0,
        ),
    ] = None
    width: Annotated[JsonInt | None, Field(ge=1, le=8)] = None
    dash: Literal["solid", "dashed", "dotted"] | None = None
    font_size: Annotated[JsonInt | None, Field(ge=8, le=48)] = None
    __null_refused = field_validator("colour", "fill_opacity", "width", "dash", "font_size", mode="before")(_refuse_null)


class DrawingInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    symbol: Annotated[
        str,
        Field(
            description="Bybit USDT linear perpetual symbol, at most 20 characters (the DB symbol_code domain).",
            examples=["BTCUSDT", "ETHUSDT"],
            pattern="^[A-Z0-9]{2,16}USDT$",
        ),
    ]
    tool: Annotated[
        Literal[
            "trendline",
            "horizontal_line",
            "vertical_line",
            "ray",
            "extended_line",
            "parallel_channel",
            "rectangle",
            "ellipse",
            "triangle",
            "fib_retracement",
            "fib_extension",
            "fib_timezone",
            "pitchfork",
            "gann_fan",
            "text",
            "arrow",
            "callout",
            "measure",
            "long_position",
            "short_position",
            "price_range",
            "date_range",
            "brush",
            "polyline",
            "anchored_vwap",
        ],
        Field(
            description="Drawing tool. **Open-ended for readers:** clients must tolerate values they do not know, so\nadding a tool is an additive change (C-6.3). Writers must send one of the listed values.\n\nRequired point count per tool (`geometry.points`):\n\n- exactly 1: `horizontal_line`, `vertical_line`, `text`, `anchored_vwap`\n- exactly 2: `trendline`, `ray`, `extended_line`, `rectangle`, `ellipse`, `fib_retracement`,\n  `fib_timezone`, `gann_fan`, `arrow`, `callout`, `measure`, `price_range`, `date_range`\n- exactly 3: `parallel_channel`, `triangle`, `fib_extension`, `pitchfork`, `long_position`,\n  `short_position`\n- 2..500: `brush`; 2..100: `polyline`\n\nTool-specific `geometry` keys (any other combination is `422` rule `property_not_allowed_for_tool`):\n`text` is required for `text` and `callout` (rule `text_required`) and forbidden elsewhere;\n`levels` only for `fib_retracement`, `fib_extension`, `fib_timezone`; `bands` only for\n`anchored_vwap`; `extend_left` / `extend_right` are allowed on every tool.\nA horizontal ray is a `horizontal_line` with `extend_left: false` and `extend_right: true`.\n"
        ),
    ]
    layout_id: Annotated[
        UUID | None,
        Field(
            description="Layout scope. A non-null value must be one of the caller's live layouts, else 422 rule `layout_not_found`; every non-null value is refused until layouts ship (E15-T01)."
        ),
    ] = None
    geometry: DrawingGeometry
    style: Annotated[
        DrawingStyle | None,
        Field(
            description="Optional; omitted means no style overrides (stored as `{}`, returned as `{}`)."
        ),
    ] = None
    label: Annotated[
        str | None,
        Field(
            description="Display label, 1..120 code points after control-character stripping.",
            max_length=120,
            min_length=1,
        ),
    ] = None
    locked: StrictBool = False
    visible: StrictBool = True
    z_index: Annotated[JsonInt, Field(ge=-32768, le=32767)] = 0
    __null_refused = field_validator("style", mode="before")(_refuse_null)


class Drawing(BaseModel):
    id: UUID
    owner_user_id: UUID
    symbol: Annotated[
        str,
        Field(
            description="Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.",
            examples=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            pattern="^[A-Z0-9]{2,20}USDT$",
        ),
    ]
    tool: Annotated[
        Literal[
            "trendline",
            "horizontal_line",
            "vertical_line",
            "ray",
            "extended_line",
            "parallel_channel",
            "rectangle",
            "ellipse",
            "triangle",
            "fib_retracement",
            "fib_extension",
            "fib_timezone",
            "pitchfork",
            "gann_fan",
            "text",
            "arrow",
            "callout",
            "measure",
            "long_position",
            "short_position",
            "price_range",
            "date_range",
            "brush",
            "polyline",
            "anchored_vwap",
        ],
        Field(
            description="Drawing tool. **Open-ended for readers:** clients must tolerate values they do not know, so\nadding a tool is an additive change (C-6.3). Writers must send one of the listed values.\n\nRequired point count per tool (`geometry.points`):\n\n- exactly 1: `horizontal_line`, `vertical_line`, `text`, `anchored_vwap`\n- exactly 2: `trendline`, `ray`, `extended_line`, `rectangle`, `ellipse`, `fib_retracement`,\n  `fib_timezone`, `gann_fan`, `arrow`, `callout`, `measure`, `price_range`, `date_range`\n- exactly 3: `parallel_channel`, `triangle`, `fib_extension`, `pitchfork`, `long_position`,\n  `short_position`\n- 2..500: `brush`; 2..100: `polyline`\n\nTool-specific `geometry` keys (any other combination is `422` rule `property_not_allowed_for_tool`):\n`text` is required for `text` and `callout` (rule `text_required`) and forbidden elsewhere;\n`levels` only for `fib_retracement`, `fib_extension`, `fib_timezone`; `bands` only for\n`anchored_vwap`; `extend_left` / `extend_right` are allowed on every tool.\nA horizontal ray is a `horizontal_line` with `extend_left: false` and `extend_right: true`.\n"
        ),
    ]
    layout_id: UUID | None
    geometry: DrawingGeometry
    style: DrawingStyle
    label: str | None
    locked: StrictBool
    visible: StrictBool
    z_index: Annotated[JsonInt, Field(ge=-32768, le=32767)]
    created_at: AwareDatetime
    updated_at: Annotated[
        AwareDatetime,
        Field(
            description="Concurrency token (also the `ETag`). Always exactly 6 fractional digits plus `Z` (`YYYY-MM-DDTHH:MM:SS.ffffffZ`) and strictly increasing on every write. Echo it exactly as received; never re-serialise it through a client date type."
        ),
    ]


class DrawingBatchCreateOp(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    op: Literal["create"]
    id: Annotated[
        UUID | None,
        Field(
            description="Optional client-chosen id (UUIDv7 recommended); taken ids are `409 id_unavailable`."
        ),
    ] = None
    drawing: DrawingInput
    __null_refused = field_validator("id", mode="before")(_refuse_null)


class DrawingBatchUpdateOp(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    op: Literal["update"]
    id: UUID
    if_match: Annotated[
        str,
        Field(
            description="`updated_at` of the version being replaced: echo it exactly as received (6 fractional digits plus `Z`); never re-serialise it through a client date type. A token that does not match is a 422 on `operations.N.if_match`.",
            pattern="^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{6}Z$",
        ),
    ]
    drawing: DrawingInput


class DrawingBatchDeleteOp(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    op: Literal["delete"]
    id: UUID
    if_match: Annotated[
        str,
        Field(
            description="`updated_at` of the version being deleted: echo it exactly as received (6 fractional digits plus `Z`); never re-serialise it through a client date type. A token that does not match is a 422 on `operations.N.if_match`.",
            pattern="^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{6}Z$",
        ),
    ]


class DrawingBatchRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    operations: Annotated[
        list[
            Annotated[
                DrawingBatchCreateOp | DrawingBatchUpdateOp | DrawingBatchDeleteOp,
                Field(discriminator="op"),
            ]
        ],
        Field(
            description="Applied in order. More than 200 items is `413 payload_too_large`.",
            max_length=200,
            min_length=1,
        ),
    ]


class DrawingBatchResult(BaseModel):
    created: list[Drawing]
    updated: list[Drawing]
    deleted: list[UUID]


class IndicatorPresetStyle(RootModel[dict[str, Any]]):
    root: Annotated[dict[str, Any], Field(max_length=0)]


class IndicatorPreset(BaseModel):
    id: UUID
    owner_user_id: Annotated[UUID | None, Field(description="The owner; `null` for a built-in.")]
    indicator_code: Annotated[str, Field(pattern="^[a-z0-9_]{2,32}$")]
    name: str
    params: Annotated[
        dict[str, Any],
        Field(description="Every parameter of the indicator, as stored when the preset was saved."),
    ]
    style: IndicatorPresetStyle
    pane_target: Literal["overlay", "subpane"]
    is_builtin: Annotated[
        StrictBool,
        Field(
            description="Set by the server only: `true` for the seeded built-ins, which never change (`403`, rule `builtin_immutable`)."
        ),
    ]
    is_favourite: StrictBool
    created_at: AwareDatetime
    updated_at: AwareDatetime


class Appearance(BaseModel):
    theme: Literal["dark", "light", "system"] | None = None
    density: Literal["compact", "comfortable", "spacious"] | None = None
    font_scale: Annotated[StrictFloat | None, Field(ge=0.75, le=2.0)] = None
    reduce_motion: StrictBool | None = None
    high_contrast: StrictBool | None = None


class Accessibility(BaseModel):
    reduced_motion: Literal["system", "on", "off"] | None = None
    increased_contrast: Literal["system", "on", "off"] | None = None
    disable_canvas_animation: StrictBool | None = None
    always_show_tables: StrictBool | None = None
    thick_focus_ring: StrictBool | None = None
    announce_prices: Literal["off", "significant", "always"] | None = None
    verbosity: Literal["low", "normal", "high"] | None = None
    keyboard_only: StrictBool | None = None


class Chart(BaseModel):
    default_bar_type: (
        Literal["time", "tick", "volume", "range", "delta", "renko", "pnf", "heikin_ashi"] | None
    ) = None
    default_param: str | None = None
    crosshair_sync: StrictBool | None = None
    bar_close_countdown: StrictBool | None = None
    price_scale_mode: Literal["linear", "logarithmic", "percent"] | None = None


class Orderflow(BaseModel):
    heatmap_bid_colour: str | None = None
    heatmap_ask_colour: str | None = None
    imbalance_ratio: StrictFloat | None = None
    min_stack: JsonInt | None = None
    value_area_pct: StrictFloat | None = None
    big_trade_threshold_mode: Literal["absolute", "relative", "zscore"] | None = None
    big_trade_k: StrictFloat | None = None


class Trading(BaseModel):
    one_click_armed: StrictBool | None = None
    arm_timeout_seconds: JsonInt | None = None
    confirm_market_orders: StrictBool | None = None
    confirm_flatten: StrictBool | None = None
    default_environment: Annotated[
        Literal["live", "demo", "testnet"] | None,
        Field(
            description="Structural environment selector (arch P9). Mirrors the Postgres type `exchange_env`."
        ),
    ] = None
    default_qty_presets: list[Decimal] | None = None


class Notifications(BaseModel):
    desktop_enabled: StrictBool | None = None
    email_enabled: StrictBool | None = None
    webhook_url: Annotated[
        str | None,
        Field(
            description="A credential-bearing URL, which may embed a token. `GET` answers it in full to its owner only; a view-as read answers its masked form. It is never logged. A `settings.change` record carries its masked form, its scheme and host only: `scheme://host/…`, or `…` when it lacks either, when its host is neither a DNS name of letter, digit and hyphen labels nor an IP address free of a zone, or when it holds a tab or a line break. An empty value stays empty."
        ),
    ] = None
    quiet_hours: dict[str, Any] | None = None


class Data(BaseModel):
    default_depth: JsonInt | None = None
    stale_badge_after_ms: JsonInt | None = None
    max_history_bars: JsonInt | None = None


class FieldMeta(BaseModel):
    overridden: list[str] | None = None
    updated_at: AwareDatetime | None = None


class Settings(BaseModel):
    appearance: Appearance | None = None
    accessibility: Annotated[
        Accessibility | None,
        Field(description="SCR-117 preferences (E47-S07); closed enums, presentation-only."),
    ] = None
    chart: Chart | None = None
    orderflow: Orderflow | None = None
    trading: Trading | None = None
    notifications: Notifications | None = None
    data: Data | None = None
    field_meta: Annotated[FieldMeta | None, Field(alias="_meta")] = None


class SettingsPatch(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )


class HotkeyBinding(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    action: Annotated[
        str,
        Field(
            description="A command id of the client's default keymap, `apps/web/src/keymap/keymap.json` (E49-T04), which is the one action vocabulary; `HotkeyBindingAuditInput.command_id` carries the same ids. No parallel set of action names exists.",
            examples=["ticket.side_buy", "positions.close_all", "chart.footprint_toggle"],
            max_length=60,
        ),
    ]
    keys: Annotated[
        str,
        Field(
            description="Chord notation, e.g. `Ctrl+Shift+F` or a sequence `Esc Esc`.",
            max_length=60,
        ),
    ]
    scope: Annotated[
        Literal[
            "global",
            "chart",
            "dom",
            "tape",
            "orders",
            "positions",
            "auth",
            "workspace",
            "ticket",
            "replay",
            "rules",
            "admin",
            "settings",
        ],
        Field(
            description="The view the binding is active in (E10-S02, #305). It is fixed by the action: the\nscope that the `context` of its `keymap.json` command maps to in this table. The table\ngoes by `context`, not by id prefix: `global.auth.submit` is an `Auth` command, so its\nscope is `auth`.\n\n| `keymap.json` context | `scope`     |\n| --------------------- | ----------- |\n| `Global`              | `global`    |\n| `Auth`                | `auth`      |\n| `Workspace`           | `workspace` |\n| `Chart`               | `chart`     |\n| `DOM`                 | `dom`       |\n| `Ticket`              | `ticket`    |\n| `Positions`           | `positions` |\n| `Replay`              | `replay`    |\n| `Rules`               | `rules`     |\n| `Admin`               | `admin`     |\n| `Settings`            | `settings`  |\n\nSeven contexts had no scope among the original six, so each has its own (`auth`,\n`workspace`, `ticket`, `replay`, `rules`, `admin`, `settings`) rather than a fold into\nanother scope. The defaults reuse a key in contexts the keymap declares never active\ntogether (`B` is `ticket.side_buy` and `replay.bookmark`; `Enter` is\n`global.auth.submit`, `positions.open_sltp` and `rules.inspect_node`), and one shared\nscope would make each such pair a `conflict` under `createHotkeyProfile`'s rule. The\norder ticket is `ticket`, not `orders`: `05-accessibility-standard.md` §3.4 makes the\nOrder Ticket and Positions & Orders separate regions. `tape` and `orders` have no\nclient context yet. **Open-ended for readers:** clients must tolerate values they do\nnot know, so adding a scope is an additive change (C-6.3). Writers must send a listed\nvalue, the one this table gives the action.\n"
        ),
    ]
    requires_arm: Annotated[
        StrictBool,
        Field(
            description="Forced true for exactly the mutations `ArmToken` requires the token for; never forced for the C-2.6 carve-out `ArmToken` lists, nor for engaging the kill switch (no order mutation)."
        ),
    ] = True
    confirm: StrictBool = False
    params: dict[str, Any] | None = None
    __null_refused = field_validator("params", mode="before")(_refuse_null)


class HotkeyProfileInput(BaseModel):
    name: Annotated[str, Field(max_length=80, min_length=1)]
    bindings: Annotated[list[HotkeyBinding], Field(max_length=200)]


class HotkeyBindingAuditInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    command_id: Annotated[str, Field(max_length=64, pattern="^[a-z0-9_]+([.][a-z0-9_]+){1,3}$")]
    before: Annotated[str, Field(max_length=64)]
    after: Annotated[str, Field(max_length=64)]
    acknowledged_unsafe: StrictBool


class HotkeyProfile(HotkeyProfileInput):
    id: UUID | None = None
    owner_user_id: UUID | None = None
    is_active: StrictBool | None = None
    updated_at: AwareDatetime | None = None


class Detail(BaseModel):
    model_config = ConfigDict(
        extra="allow",
    )
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    elided: Annotated[
        list[Literal["before", "after"]] | None,
        Field(
            description="States the server withholds (over its size caps for a page, not a JSON object, or nested deeper than 128 levels); absent when none were withheld. A stored `null` state is never listed.",
            max_length=2,
        ),
    ] = None


class AuditEntry(BaseModel):
    id: Annotated[
        JsonInt,
        Field(
            description="Chain position (`audit_log.id`); increasing, not contiguous. Informational."
        ),
    ]
    ts: Annotated[
        AwareDatetime,
        Field(description="Event time recorded by the audit writer (UTC, microseconds)."),
    ]
    actor_user_id: Annotated[UUID | None, Field(description="Null for system and rule actors.")]
    actor_username: Annotated[
        str | None, Field(description="Actor label recorded at write time; survives user deletion.")
    ] = None
    action: str
    subject_type: Annotated[str | None, Field(description="Recorded subject kind (`object_kind`).")]
    subject_id: str | None
    subject_label: Annotated[
        str | None, Field(description="Human name of the subject at the time. Informational.")
    ] = None
    outcome: Literal["success", "failure", "denied"]
    severity: Literal["debug", "info", "warning", "error", "critical"]
    reason: Annotated[
        str | None,
        Field(
            description="Stable machine-readable code for a denial or failure, for example `owner_only` or `missing_permission:audit:read`; never prose."
        ),
    ] = None
    environment: Literal["live", "demo", "testnet"] | None = None
    session_id: UUID | None = None
    ip: Annotated[str | None, Field(description="Actor IP address (PII).")] = None
    user_agent: Annotated[str | None, Field(description="Informational.")] = None
    request_id: Annotated[
        str | None, Field(description="Id of the request that produced the entry.")
    ] = None
    detail: Annotated[
        Detail,
        Field(
            description="The recorded, already-redacted state change: `before` and `after`, each an object or null. `{}` in a Manager's projection. A state the server withholds (over its size caps for a page, not a JSON object, or nested deeper than 128 levels) is `null` and its name is listed in `elided`. A stored `null` state is never listed."
        ),
    ]
    entry_hash: Annotated[
        str | None,
        Field(
            description="SHA-256 (hex) over the hashed fields and `prev_hash`; null for a Manager."
        ),
    ]
    prev_hash: Annotated[
        str | None,
        Field(
            description="`entry_hash` of the previous entry (64 zeros for the first); null for a Manager."
        ),
    ]


class Component(BaseModel):
    name: str | None = None
    state: Annotated[
        Literal["healthy", "degraded", "warning", "down", "not_deployed"] | None,
        Field(
            description="`not_deployed` = module not built yet; ranks as healthy for `overall`. Rank: down > warning > degraded > healthy."
        ),
    ] = None
    latency_ms: JsonInt | None = None
    latency_unit: Literal["ms"] | None = None
    detail: str | None = None
    last_good_at: AwareDatetime | None = None


class HealthReport(BaseModel):
    overall: Annotated[
        Literal["healthy", "degraded", "warning", "down", "not_deployed"] | None,
        Field(
            description="`not_deployed` = module not built yet; ranks as healthy for `overall`. Rank: down > warning > degraded > healthy."
        ),
    ] = None
    version: Annotated[
        str | None, Field(max_length=32, min_length=1, pattern="^[!-~](?:[ -~]*[!-~])?$")
    ] = None
    git_sha: str | None = None
    environment: str | None = None
    uptime_seconds: JsonInt | None = None
    server_time: AwareDatetime | None = None
    clock_offset_ms: Annotated[
        JsonInt | None,
        Field(description="null until exchange time sync (E08) lands; never a fabricated 0."),
    ] = None
    components: list[Component] | None = None
    alerts_active: JsonInt | None = None


class Override(BaseModel):
    user_id: UUID | None = None
    value: Any | None = None


class FeatureFlag(BaseModel):
    key: str | None = None
    kind: Literal["boolean", "percentage", "variant"] | None = None
    description: str | None = None
    value: Annotated[Any | None, Field(description="Resolved value for the caller.")] = None
    default_value: Annotated[
        Any | None,
        Field(
            description="Deployment default: the deployment-wide stored value resolution falls back to (`feature_flags.default_value`, E42-T03). A `PUT` writes it on a `boolean` or `variant` flag; on a `percentage` flag it writes `rollout_pct` instead. Omitted when the list's `resolution` is `fail_closed` or the flag is `unreadable`.\n"
        ),
    ] = None
    overrides: Annotated[
        list[Override] | None,
        Field(description="Omitted when the list's `resolution` is `fail_closed` (E42-T03)."),
    ] = None
    updated_by: Annotated[
        UUID | None,
        Field(
            description="Omitted when the list's `resolution` is `fail_closed` or the flag is `unreadable` (E42-T03).\n"
        ),
    ] = None
    updated_at: Annotated[
        AwareDatetime | None,
        Field(
            description="Omitted when the list's `resolution` is `fail_closed` (E42-T03). An `unreadable` flag keeps it: it is the `expected_updated_at` of the write that repairs the flag.\n"
        ),
    ] = None
    unreadable: Annotated[
        StrictBool | None,
        Field(
            description="`true` when this flag's stored row is unreadable (malformed, or a kind mismatch): the flag alone resolves to its fail-closed value, and a `PUT` with a valid value repairs it (E42-T03). Sent only as `true`.\n"
        ),
    ] = None


class FeatureFlagResolution(RootModel[Literal["stored", "fail_closed"]]):
    root: Annotated[
        Literal["stored", "fail_closed"],
        Field(
            description="How `GET /admin/feature-flags` resolved its list (E42-T03), a closed set; always sent. `stored`: from the flag store. `fail_closed`: the store was unreachable (its read failed or exceeded its read budget), so every flag shows its fail-closed value and omits `default_value`, `overrides`, `updated_at` and `updated_by`. A single unreadable row is not an outage: the list stays `stored` and that flag is marked `unreadable`.\n"
        ),
    ]


class Override1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    user_id: UUID
    value: Any


class SetFeatureFlagRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    value: Annotated[
        Any,
        Field(
            description="Boolean, integer 0-100 (percentage) or string (variant), matching the flag kind."
        ),
    ]
    overrides: Annotated[
        list[Override1] | None,
        Field(description="Omitted, the existing overrides stay; `[]` clears them (E42-T03)."),
    ] = None
    reason: Annotated[
        str | None,
        Field(
            description="Why the flag changed; recorded in the `flags.change` audit entry (E42-T03). The server refuses a write without it (`422 validation_failed`). It stays optional in the schema because C-6.3 classes a newly required field as breaking. A reason that carries a credential is refused as `422 validation_failed` (rule `credential_in_reason`) and recorded as `<redacted:credential>`; `setFeatureFlag` lists what counts.\n",
            max_length=280,
        ),
    ] = None
    evidence_url: Annotated[
        AnyUrl | None,
        Field(
            description="Required for gated flags such as `trading.live_enabled`. An `https` URL; recorded, never dereferenced."
        ),
    ] = None
    expected_updated_at: Annotated[
        AwareDatetime | None,
        Field(
            description="The flag's `updated_at` as the caller last read it (E42-T03). The write is applied only if the stored value still matches, else `409 conflict`. The server refuses a write without it (`422 validation_failed`); schema-optional for the same reason as `reason`.\n"
        ),
    ] = None
    __null_refused = field_validator("overrides", "reason", "evidence_url", "expected_updated_at", mode="before")(_refuse_null)


class FeatureFlagConflict(Problem):
    current: FeatureFlag


class Backup(BaseModel):
    id: UUID | None = None
    kind: (
        Literal["pg_basebackup", "pg_dump", "questdb_snapshot", "parquet_sync", "config_bundle"]
        | None
    ) = None
    status: Literal["running", "ok", "failed", "verified", "restored"] | None = None
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    size_bytes: JsonInt | None = None
    location: str | None = None
    checksum_sha256: str | None = None
    encrypted: StrictBool | None = None
    retention_until: AwareDatetime | None = None
    verified_at: AwareDatetime | None = None
    error: Annotated[
        str | None,
        Field(
            description="Why the run or its latest conclusive verification failed, as a stable code such as `checksum_mismatch` (E42-T05), never an exception message, a path or key material. A passing verification clears it and an inconclusive one (`store_unavailable`, `audit_unavailable` or `internal_error`) leaves it as it was (`verifyBackup`). Stored in `backups.error_message`; `null` when nothing failed.\n"
        ),
    ] = None
    deleted_at: Annotated[
        AwareDatetime | None,
        Field(
            description="When the artefact was deleted (`deleteBackup`, E42-T05); the catalogue row is kept. `null` while the artefact exists.\n"
        ),
    ] = None


class AuditExportResult(BaseModel):
    download_url: Annotated[
        str,
        Field(
            description="Relative API URL of the artefact. It carries no credential: fetching it is an authenticated `GET`, allowed only to the requesting user within the `audit` step-up grace window, and audited before any byte is sent (see `exportAuditLog`)."
        ),
    ]
    sha256: Annotated[
        str,
        Field(
            description="SHA-256 (hex) of the artefact bytes exactly as downloaded.",
            pattern="^[0-9a-f]{64}$",
        ),
    ]
    signature: Annotated[
        str,
        Field(
            description="Base64 of the 64-byte Ed25519 signature.",
            json_schema_extra={"contentEncoding": "base64"},
            pattern="^[A-Za-z0-9+/]{86}==$",
        ),
    ]
    signature_alg: Literal["ed25519"]
    key_id: Annotated[
        str,
        Field(
            description="Signing key: key version and the first 16 hex of the public key's SHA-256.",
            pattern="^cv-audit-export-v[0-9]+:[0-9a-f]{16}$",
        ),
    ]
    public_key: Annotated[
        str,
        Field(
            description="Base64 of the signing key's 32-byte Ed25519 public key, as the file's header line carries it. A verifier compares its SHA-256 with the fingerprint it pinned, and never trusts it on its own.",
            json_schema_extra={"contentEncoding": "base64"},
            pattern="^[A-Za-z0-9+/]{43}=$",
        ),
    ]
    compressed: StrictBool
    size_bytes: Annotated[JsonInt, Field(ge=0)]
    row_count: Annotated[
        JsonInt,
        Field(
            description="Entry lines in the file: the whole span, including entries flagged as outside the window. The header line is not counted.",
            ge=0,
        ),
    ]
    from_: Annotated[AwareDatetime, Field(alias="from", description="Requested inclusive start.")]
    to: Annotated[AwareDatetime, Field(description="Requested exclusive end.")]
    first_id: JsonInt | None = None
    last_id: JsonInt | None = None
    expires_at: Annotated[
        AwareDatetime, Field(description="The artefact is deleted after this instant.")
    ]


class AuditSigningKey(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    key_id: Annotated[
        str,
        Field(
            description="`cv-audit-export-v<N>:` and the first 16 hex of `fingerprint_sha256`, N the key's version. It finds the key and is never pinned.",
            pattern="^cv-audit-export-v[0-9]+:[0-9a-f]{16}$",
        ),
    ]
    alg: Literal["ed25519"]
    public_key: Annotated[
        str,
        Field(
            description="Base64 of the 32-byte raw Ed25519 public key (RFC 8032).",
            json_schema_extra={"contentEncoding": "base64"},
            pattern="^[A-Za-z0-9+/]{43}=$",
        ),
    ]
    fingerprint_sha256: Annotated[
        str,
        Field(
            description="Lowercase hex SHA-256 of the 32-byte raw public key: what a verifier pins.",
            pattern="^[0-9a-f]{64}$",
        ),
    ]
    status: Annotated[
        Literal["active", "retired"],
        Field(
            description="At most one key of the environment is `active`; a retired key never signs."
        ),
    ]
    verified: Annotated[
        StrictBool,
        Field(
            description="True only once M2 has opened the key's sealed seed and found that it derives `public_key` (the seal binds it, ADR-0039 decision 4); a key failing that check is refused, paged and never signs. Retiring a key destroys its seed (ADR-0039 Q3), so a retired key is never `verified`. No verifier relies on this mark."
        ),
    ]
    valid_from: Annotated[AwareDatetime, Field(description="When the key became active.")]
    valid_until: Annotated[
        AwareDatetime | None,
        Field(
            description="The `event_ts` of the `security.audit_signing_key_rotated` record of the rotation that retired the key; null while it is active."
        ),
    ]
    retired_reason: Annotated[
        Literal["scheduled", "compromise", "unrecoverable"] | None,
        Field(description="That rotation's `reason`; null while the key is active."),
    ]


class AuditSigningKeyRotation(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    active: AuditSigningKey
    retired: AuditSigningKey


class RotateAuditSigningKeyRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    reason: Annotated[
        Literal["scheduled", "compromise", "unrecoverable"],
        Field(
            description="Recorded in the rotation's record and as the retired key's `retired_reason`; `compromise` marks a seed that may have been stolen, and `unrecoverable` a key that can no longer be opened, the recovery after a KEK loss (ADR-0039 decision 6, AD-D13)."
        ),
    ]


class Account1(BaseModel):
    exchange_account_id: UUID
    label: str | None = None
    environment: Annotated[
        Literal["live", "demo", "testnet"] | None,
        Field(
            description="Structural environment selector (arch P9). Mirrors the Postgres type `exchange_env`."
        ),
    ] = None
    mode: Literal["read", "trade"]


class Session(BaseModel):
    session_id: UUID | None = None
    environment: Annotated[
        Literal["live", "demo", "testnet"] | None,
        Field(
            description="Structural environment selector (arch P9). Mirrors the Postgres type `exchange_env`."
        ),
    ] = None
    elevated_until: AwareDatetime | None = None
    one_click_armed_until: AwareDatetime | None = None


class Me(BaseModel):
    user: User
    role: Literal["owner", "manager", "viewer"]
    permissions: Annotated[
        list[str],
        Field(
            description="Flattened effective permissions, drawn from the same closed vocabulary as `x-rbac.permissions` on every operation in this file.\n"
        ),
    ]
    accounts: Annotated[
        list[Account1], Field(description="Accounts the caller may see, with the granted mode.")
    ]
    session: Session | None = None
    onboarding_complete: StrictBool | None = None


class Account2(BaseModel):
    exchange_account_id: UUID | None = None
    orders_per_minute_limit: JsonInt | None = None
    orders_per_minute_used: JsonInt | None = None
    rate_budget_pct_used: Annotated[StrictFloat | None, Field(ge=0.0, le=100.0)] = None
    daily_loss_usd: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    daily_loss_cap_usd: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    open_positions: JsonInt | None = None
    lockout_until: AwareDatetime | None = None


class EffectiveLimits(BaseModel):
    risk_caps: RiskCaps | None = None
    accounts: list[Account2] | None = None


class Item(BaseModel):
    key: Literal["tailscale", "totp", "sub_account", "api_key", "profile_limits", "demo_session"]
    state: Literal["ok", "pending", "blocked", "error", "not_applicable"]
    reason: str | None = None
    unblock_at: AwareDatetime | None = None
    action_route: str | None = None


class OnboardingChecklist(BaseModel):
    complete: StrictBool
    dismissed: StrictBool
    items: list[Item]


class Notification(BaseModel):
    id: Annotated[
        UUID,
        Field(
            description="Deterministic: uuid5(namespace, source_table + source_id), so the same source row always maps to the same notification id. The namespace is the fixed constant `x-cv-uuid5-namespace` below (24-internal-schemas.md §1.6).\n"
        ),
    ]
    kind: Literal["alert", "rule", "order", "risk", "system"]
    severity: Literal["debug", "info", "warning", "error", "critical"]
    title: str
    body: str | None = None
    created_at: AwareDatetime
    read_at: Annotated[
        AwareDatetime | None,
        Field(
            description="`acked_at` for alert deliveries; always null for rule, order and system rows until their owners define read state. Order rows come from E29's `order_events`.\n"
        ),
    ] = None
    symbol: str | None = None
    exchange_account_id: UUID | None = None
    source_id: Annotated[
        UUID | None,
        Field(
            description='Deterministic id of the originating alert delivery, rule event, order event or system event: uuid5 in the 24-internal-schemas.md §1.6 namespace over source_table + ":" + source_id (the separator keeps it distinct from `id`), never a raw database id. Raw ids of the parent alert, rule or order travel only in `route`.\n'
        ),
    ] = None
    route: Annotated[
        str | None, Field(description="Deep link to the screen that explains this notification.")
    ] = None


class Column(RootModel[str]):
    root: Annotated[str, Field(max_length=32, pattern="^[a-z][a-z0-9_]*$")]


class Watchlist(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: UUID
    name: Annotated[str, Field(max_length=80, min_length=1)]
    symbols: Annotated[list[Symbol], Field(max_length=200)]
    columns: Annotated[list[Column], Field(max_length=32)]
    version: Annotated[
        JsonInt,
        Field(
            description="Server-assigned: 1 on create, one more on each replace. `updateWatchlist` takes it back through `If-Match` (`WatchlistETag`), never in the body.\n",
            ge=1,
        ),
    ]
    created_at: AwareDatetime
    updated_at: AwareDatetime


class WatchlistInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: Annotated[
        str,
        Field(
            description="Trimmed of leading and trailing white space before it is checked and stored: E08-D07 §4.3 and DJ compare names trimmed and case-insensitively; the 1–80 characters count the trimmed name, so a name blank once trimmed is `422 validation_failed`. A name holding a control or format character (Unicode Cc or Cf) is `422 validation_failed`, as an account-profile name is. Unique among the owner's lists, case-insensitively as Postgres `lower()` folds it (`409 conflict` / `name_taken`).\n",
            max_length=80,
            min_length=1,
        ),
    ]
    symbols: Annotated[
        list[Symbol],
        Field(
            description="The list, in order: each a trading USDT linear perpetual of the instrument catalogue, none twice (`422 validation_failed`: `too_many_symbols`, `unknown_symbol`, `duplicate_symbol`).\n",
            max_length=200,
        ),
    ]
    columns: Annotated[
        list[Column] | None,
        Field(
            description="Column ids shown for this watchlist, in order: the ids of E08-D07 §4.1 (`last`, `chg_24h_pct`, `open_interest_value`, ...). Ids are stored strings and a reader skips one it does not know (E08-D07 D8), so the set is open: at most 32, each a lowercase snake_case id of at most 32 characters, none twice (`422 validation_failed` on `columns`, rule `duplicate_column`). Left out or `null`, on a create and on a replace alike, the list takes E08-D07 §4.1's default columns (`symbol`, `last`, `chg_24h_pct`, `turnover_24h`, `funding_rate`, `next_funding`, `oi_chg_24h_pct`, `spread_bps`, `rec`): a replace without `columns` resets them, as a full replace does.\n",
            max_length=32,
        ),
    ] = None


class ScannerSortKeyStatus(BaseModel):
    id: Annotated[
        Literal[
            "volume_24h",
            "price_change_pct_24h",
            "cvd",
            "tape_speed",
            "open_interest",
            "liquidation_intensity",
            "turnover_24h",
            "funding_rate",
            "spread_bps",
            "range_pct_24h",
            "tape_speed_zscore",
            "oi_change_pct_24h",
        ],
        Field(
            description="A `runScanner` ranking key. **Open-ended for readers** (C-6.3); a writer sends a listed value that `listScannerCriteria`'s `sort_keys` does not list with `available: false`. A preset stores one.\n"
        ),
    ]
    available: Annotated[
        StrictBool,
        Field(
            description="`false` while no source feeds the key: `runScanner` and the preset writes refuse it (`422` rule `criterion_unavailable`, field `sort`)."
        ),
    ]


class ScannerInputFreshness(BaseModel):
    input: Annotated[
        Literal["tickers", "open_interest", "orderflow_metrics"],
        Field(
            description="`tickers` (the 24 h ticker values), `open_interest` (the 24 h open-interest baseline) or `orderflow_metrics` (tape speed and its z-score, regime, CVD and liquidation intensity). **Open-ended for readers** (C-6.3).\n"
        ),
    ]
    as_of: Annotated[
        AwareDatetime | None,
        Field(
            description="The oldest latest-value timestamp the scan used from this input; `null` if it used none."
        ),
    ]
    stale: Annotated[
        StrictBool,
        Field(
            description="`true` when a value the scan used is stale: for `tickers`, a ticker carrying `stale: true` (`Ticker.stale`); for the others, a latest value older than 15 s (the E08-D04 `stale` threshold) at `generated_at`. A client then marks the whole scan as computed from possibly stale inputs.\n"
        ),
    ]


class ScannerCriterionId(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description="A criterion id. `ScannerFilter` lists the ids in force; a stored preset may still name one the server no longer knows or lists with `available: false` (`ScannerPreset.unavailable_criteria`, which also carries a stored `sort` key that `sort_keys` lists with `available: false`).\n",
            pattern="^[a-z][a-z0-9_]{0,39}$",
        ),
    ]


class ScannerRange(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    min: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    max: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    __null_refused = field_validator("min", "max", mode="before")(_refuse_null)


class Class(RootModel[str]):
    root: Annotated[str, Field(pattern="^[a-z][a-z0-9_]{0,31}$")]


class ScannerClassSet(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    classes: Annotated[list[Class], Field(max_length=16, min_length=1)]


class ScannerCriterion(BaseModel):
    id: Annotated[
        str,
        Field(
            description="A criterion id. `ScannerFilter` lists the ids in force; a stored preset may still name one the server no longer knows or lists with `available: false` (`ScannerPreset.unavailable_criteria`, which also carries a stored `sort` key that `sort_keys` lists with `available: false`).\n",
            pattern="^[a-z][a-z0-9_]{0,39}$",
        ),
    ]
    label: Annotated[str, Field(description="The English display name, units included.")]
    kind: Annotated[
        Literal["range", "class_set"],
        Field(description="`range` takes a `ScannerRange`, `class_set` a `ScannerClassSet`."),
    ]
    unit: Annotated[
        Literal["fraction", "usdt", "bps", "zscore", "class"],
        Field(
            description="The unit of the bounds and of the matching `ScannerRow` field; `fraction` is a decimal ratio."
        ),
    ]
    estimated: Annotated[
        StrictBool,
        Field(
            description="`true` when the value is an estimate: the client badges the criterion and its column."
        ),
    ]
    needs_recording: Annotated[
        StrictBool,
        Field(
            description="`true` when the value needs recorded history, so it is skipped for `live_only` rows."
        ),
    ]
    sortable: Annotated[
        StrictBool, Field(description="`true` when the id is also a `ScannerSortKey`.")
    ]
    available: Annotated[
        StrictBool,
        Field(
            description="`false` while no server source feeds the criterion (tape speed and regime until E10 writes `orderflow_metrics`, OI change until the recorded open-interest baseline is read): the client offers neither a filter nor a sort on it, and the server refuses one (`422` rule `criterion_unavailable`) rather than skipping it for every row. It turns `true` server-side when the source lands.\n"
        ),
    ]
    classes: Annotated[
        list[Class] | None,
        Field(
            description="Present for a `class_set` criterion only: its classes, in display order."
        ),
    ] = None


class IndicatorOutput(BaseModel):
    id: Annotated[str, Field(pattern="^[a-z][a-z0-9_]{0,31}$")]
    name: str


class Reconciliation(BaseModel):
    last_checked_at: AwareDatetime | None = None
    verdict: Literal["in_sync", "drifted", "repaired", "unresolvable"] | None = None
    detail: str | None = None


class ExchangeRecordFields(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    order_link_id: Annotated[str | None, Field(max_length=36)] = None
    exchange_order_id: Annotated[str | None, Field(max_length=64)] = None
    symbol: Annotated[
        str | None,
        Field(
            description="Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.",
            examples=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            pattern="^[A-Z0-9]{2,20}USDT$",
        ),
    ] = None
    side: Literal["buy", "sell"] | None = None
    order_type: Literal["market", "limit"] | None = None
    qty: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    price: Decimal | None = None
    time_in_force: Literal["GTC", "IOC", "FOK", "PostOnly"] | None = None
    reduce_only: StrictBool | None = None
    close_on_trigger: StrictBool | None = None
    position_idx: Literal[0, 1, 2] | None = None
    trigger_price: Decimal | None = None
    trigger_by: Literal["LastPrice", "MarkPrice", "IndexPrice"] | None = None
    trigger_direction: Literal["rise", "fall"] | None = None
    take_profit: Decimal | None = None
    stop_loss: Decimal | None = None
    tpsl_mode: Literal["Full", "Partial"] | None = None
    trailing_stop: Decimal | None = None
    activation_price: Decimal | None = None
    tp_size: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    sl_size: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    tp_trigger_by: Literal["LastPrice", "MarkPrice", "IndexPrice"] | None = None
    sl_trigger_by: Literal["LastPrice", "MarkPrice", "IndexPrice"] | None = None
    category: Annotated[
        Literal["linear"] | None, Field(description="Always explicit (SR-054).")
    ] = None
    order_filter: Annotated[
        str | None,
        Field(
            description="The cancel-all filter, always explicit so it never reaches a position's TP/SL (SR-E29-06).",
            max_length=64,
        ),
    ] = None
    leverage: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    order_status: Annotated[
        str | None,
        Field(
            description="The exchange's order status code.",
            max_length=64,
            pattern="^[A-Za-z0-9_]{1,64}$",
        ),
    ] = None
    filled_qty: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    remaining_qty: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    avg_fill_price: Decimal | None = None
    reject_reason: Annotated[
        str | None,
        Field(
            description="The exchange's reject reason code.",
            max_length=64,
            pattern="^[A-Za-z0-9_]{1,64}$",
        ),
    ] = None
    exec_id: Annotated[str | None, Field(max_length=64)] = None
    exec_qty: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    exec_price: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    fee: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    is_maker: StrictBool | None = None


class TakeProfit(BaseModel):
    price: Annotated[
        str,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ]
    qty: Annotated[
        str,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ]


class Rejection(BaseModel):
    code: Annotated[
        Literal[
            "cap_breached",
            "symbol_not_allowed",
            "insufficient_margin",
            "rate_budget_exhausted",
            "account_locked",
            "key_invalid",
            "leverage_unavailable",
            "kill_switch_engaged",
            "profile_disabled",
            "symbol_denied",
            "below_min_notional",
            "skipped",
            "no_reference_price",
            "invalid_stop_distance",
            "figure_unknown",
            "stop_beyond_liquidation",
            "account_disabled",
            "account_unhealthy",
            "trading_disabled",
            "risk_state_unavailable",
        ]
        | None,
        Field(
            description="`skipped` and the sizer's skips (24-internal-schemas.md section 9.3.4)\nmark a `skipped` leg, and every other code a `blocked` one, a member's\nreadiness reason (`TradeGroupReadiness`) included. Among them:\n- `skipped`: the request's `overrides.skip` leaves the leg out.\n- `profile_disabled`: its profile is disabled or does not trade.\n- `symbol_denied`: its profile's `blocked_symbols` holds the symbol.\n- `below_min_notional`: it sizes under the minimum quantity or notional.\n- `no_reference_price`: no mid or last price to size a market leg from.\n- `invalid_stop_distance`: its stop is not above 0 or not on the loss side.\n- `figure_unknown`: a figure its sizing needs is not cached.\n- `stop_beyond_liquidation`: its stop would not fire before liquidation.\n- `account_disabled`: its account is disabled.\n- `account_unhealthy`: its account fails the health check.\n- `trading_disabled`: order entry is closed for its account.\n- `risk_state_unavailable`: the risk gate has no state to judge it by.\n\n**Open-ended for readers:** clients must tolerate values they do not know,\nso adding a code is an additive change (C-6.3); a code a client does not\nknow is read by the leg's `status`.\n"
        ),
    ] = None
    message: str | None = None


class Leg1(BaseModel):
    exchange_account_id: UUID
    account_label: str | None = None
    account_profile_id: UUID | None = None
    would_submit: StrictBool
    status: Annotated[
        Literal["ready", "warn", "skipped", "blocked"],
        Field(
            description="The leg's state as text (SCR-061): `would_submit` is true exactly for `ready` and `warn`. A `warn` leg carries `warnings`; a `skipped` or `blocked` one carries `rejection`, whose `code` says why.\n"
        ),
    ]
    warnings: Annotated[
        list[Literal["stop_fallback"]] | None,
        Field(
            description="A `warn` leg's caveats. `stop_fallback`: its stop uses the profile's `fallback_sl_offset_pct`, as no ATR reading served (SR-E28-12).\n"
        ),
    ] = None
    resolved: ResolvedLegParams | None = None
    take_profits: Annotated[
        list[TakeProfit] | None,
        Field(
            description="The leg's take-profits as the sizer resolves them, one per rung, each a price and the quantity it closes (24-internal-schemas.md section 9.3.3).\n",
            max_length=10,
        ),
    ] = None
    estimated_margin_usd: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    estimated_risk_usd: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    rejection: Rejection | None = None


class Totals2(BaseModel):
    accounts_targeted: JsonInt | None = None
    accounts_submittable: JsonInt | None = None
    total_qty: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    total_notional_usd: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    total_risk_usd: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    total_estimated_fee_usd: Annotated[
        str | None,
        Field(
            description='The `resolved.estimated_fee_usd` of the legs that would be submitted, summed (SCR-061\'s "est. fee").\n',
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None


class TradeGroupPreview(BaseModel):
    legs: list[Leg1]
    totals: Totals2


class Totals3(BaseModel):
    equity_usd: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    unrealised_pnl_usd: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    realised_pnl_today_usd: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    open_positions: JsonInt | None = None
    gross_notional_usd: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    positions_without_native_stop: Annotated[
        JsonInt | None,
        Field(
            description="MUST be zero in steady state; any non-zero value is a violation of the native-stop safety invariant and is surfaced as a critical banner.\n"
        ),
    ] = None


class Lockout(BaseModel):
    reason: Literal["daily_loss", "consecutive_losses", "max_positions", "manual"] | None = None
    since: AwareDatetime | None = None
    until: AwareDatetime | None = None


class Account3(BaseModel):
    exchange_account_id: UUID | None = None
    label: str | None = None
    equity_usd: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    unrealised_pnl_usd: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    realised_pnl_today_usd: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    daily_loss_cap_usd: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    cap_utilisation_pct: Annotated[StrictFloat | None, Field(ge=0.0)] = None
    open_positions: JsonInt | None = None
    frozen: StrictBool | None = None
    lockout: Lockout | None = None


class RiskSummary(BaseModel):
    scope: Literal["global", "accounts"]
    environment: Annotated[
        Literal["live", "demo", "testnet"] | None,
        Field(
            description="Structural environment selector (arch P9). Mirrors the Postgres type `exchange_env`."
        ),
    ] = None
    kill_switch: KillSwitch | None = None
    totals: Totals3 | None = None
    accounts: list[Account3]


class Iceberg1(BaseModel):
    enabled: StrictBool = True
    min_reloads: Annotated[JsonInt, Field(ge=2, le=50)] = 3
    price_tolerance_ticks: Annotated[JsonInt, Field(ge=0, le=10)] = 0
    window_ms: Annotated[JsonInt, Field(ge=200, le=60000)] = 5000


class StopRun(BaseModel):
    enabled: StrictBool = True
    lookback_bars: Annotated[JsonInt, Field(ge=2, le=500)] = 20
    penetration_ticks: Annotated[JsonInt, Field(ge=1, le=100)] = 2
    reversal_pct: Annotated[StrictFloat, Field(ge=0.0, le=100.0)] = 60


class Absorption(BaseModel):
    enabled: StrictBool = True
    min_volume_multiple: Annotated[StrictFloat, Field(ge=1.0, le=50.0)] = 3
    max_price_move_ticks: Annotated[JsonInt, Field(ge=0, le=50)] = 1


class Exhaustion(BaseModel):
    enabled: StrictBool = True
    min_delta_divergence: Annotated[StrictFloat, Field(ge=0.0)] = 0.5


class BigTrade(BaseModel):
    mode: Literal["absolute_usd", "percentile"] = "percentile"
    absolute_usd: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    percentile: Annotated[StrictFloat, Field(ge=50.0, le=99.99)] = 99
    __null_refused = field_validator("absolute_usd", mode="before")(_refuse_null)


class DetectorConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    iceberg: Iceberg1 | None = None
    stop_run: StopRun | None = None
    absorption: Absorption | None = None
    exhaustion: Exhaustion | None = None
    big_trade: BigTrade | None = None
    __null_refused = field_validator("iceberg", "stop_run", "absorption", "exhaustion", "big_trade", mode="before")(_refuse_null)


class DetectorMethodology(BaseModel):
    detector: Literal["iceberg", "stop_run", "absorption", "exhaustion", "big_trade", "regime"]
    display_name: str | None = None
    inputs: list[str]
    assumption: Annotated[str, Field(description="The inference being made, stated plainly.")]
    false_positive_modes: list[str]
    confidence_basis: str | None = None


class Signal(BaseModel):
    name: str | None = None
    value: StrictFloat | None = None
    weight: StrictFloat | None = None
    contribution: StrictFloat | None = None
    direction: Literal["supports", "opposes", "neutral"] | None = None


class RegimeExplanation(BaseModel):
    symbol: Annotated[
        str,
        Field(
            description="Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.",
            examples=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            pattern="^[A-Z0-9]{2,20}USDT$",
        ),
    ]
    regime: Literal["trending_up", "trending_down", "ranging", "volatile_expansion", "compression"]
    confidence: Annotated[StrictFloat | None, Field(ge=0.0, le=1.0)] = None
    as_of: AwareDatetime | None = None
    signals: list[Signal]


class Signal1(BaseModel):
    id: str
    display_name: str | None = None
    type: Literal["number", "boolean", "price", "quantity", "duration", "enum"]
    unit: str | None = None
    enum_values: list[str] | None = None
    params_schema: dict[str, Any] | None = None
    requires_recording: StrictBool = False
    estimated: StrictBool = False
    description: str | None = None
    valid_range: str | None = None
    warmup_bars: JsonInt | None = None
    deterministic: StrictBool | None = None
    confidence: Literal["exact", "estimated"] | None = None
    dependencies: list[str] | None = None
    when_unavailable: str | None = None
    available: StrictBool = True
    unavailable_reason: str | None = None
    missing_dependency: dict[str, Any] | None = None
    recorder_action: dict[str, Any] | None = None


class Operator(BaseModel):
    id: str | None = None
    arity: Annotated[JsonInt | None, Field(ge=1, le=3)] = None
    operand_types: list[str] | None = None
    result_type: str | None = None


class Action1(BaseModel):
    id: str
    display_name: str | None = None
    params_schema: dict[str, Any] | None = None
    required_permissions: list[str]
    requires_step_up: StrictBool = False
    idempotent: StrictBool | None = None
    guarded: StrictBool | None = None
    targets: dict[str, str] | None = None
    available: StrictBool = True
    simulate_only: StrictBool = False
    restriction: str | None = None
    notes: str | None = None
    loosens_risk: Annotated[
        StrictBool,
        Field(
            description="Always false: no rule may loosen a stop, and an action that could is refused for every role (`stop_loosening`, 24-internal-schemas.md section 8.8 rule 5). The field stays until the 24-internal-schemas.md section 19.26 follow-up retires it.\n"
        ),
    ] = False


class Guard(BaseModel):
    id: str | None = None
    params_schema: dict[str, Any] | None = None


class Trigger(BaseModel):
    id: str | None = None
    description: str | None = None
    required_fields: list[str] | None = None


class RuleVocabulary(BaseModel):
    ir_version: str | None = None
    signals: list[Signal1]
    operators: list[Operator]
    actions: list[Action1]
    guards: list[Guard]
    triggers: list[Trigger] | None = None
    vocabulary_version: JsonInt | None = None
    arm_live_permission: str | None = None


class Marker(BaseModel):
    at: AwareDatetime | None = None
    kind: Literal["entry", "exit", "stop_moved", "scale_in", "scale_out", "rule_fired"] | None = (
        None
    )
    price: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    label: str | None = None


class JournalTradeContext(BaseModel):
    journal_trade_id: UUID
    symbol: Annotated[
        str,
        Field(
            description="Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.",
            examples=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            pattern="^[A-Z0-9]{2,20}USDT$",
        ),
    ]
    from_: Annotated[AwareDatetime, Field(alias="from")]
    to: AwareDatetime
    bars: list[Bar] | None = None
    footprint: list[FootprintBar] | None = None
    executions: list[Execution] | None = None
    markers: list[Marker] | None = None
    coverage: DataCoverage


class BuildInfo(BaseModel):
    version: Annotated[str, Field(max_length=32, min_length=1, pattern="^[!-~](?:[ -~]*[!-~])?$")]
    commit: str
    built_at: AwareDatetime
    api_version: str | None = None
    ws_protocol_version: str | None = None
    electron_version: str | None = None


class AdminSliceStatus(BaseModel):
    status: Annotated[
        Literal["ok", "error", "unavailable"] | None,
        Field(
            description="**Open-ended for readers:** clients must tolerate values they do not know, so adding an outcome is an additive change (C-6.3).\n"
        ),
    ] = None
    detail: Annotated[str | None, Field(max_length=200)] = None
    generated_at: Annotated[
        AwareDatetime | None,
        Field(
            description="When the slice was read; at most 5 s older than the response (slice cache)."
        ),
    ] = None


class Users(AdminSliceStatus):
    total: JsonInt | None = None
    active: JsonInt | None = None
    without_mfa: JsonInt | None = None


class Accounts(AdminSliceStatus):
    total: JsonInt | None = None
    enabled: JsonInt | None = None
    keys_expiring_30d: JsonInt | None = None
    keys_invalid: JsonInt | None = None


class Recorder(AdminSliceStatus):
    symbols_recording: JsonInt | None = None
    symbols_degraded: JsonInt | None = None
    lag_seconds_p99: StrictFloat | None = None


class Storage(AdminSliceStatus):
    used_bytes: JsonInt | None = None
    free_bytes: JsonInt | None = None
    days_until_full: StrictFloat | None = None


class Trading1(AdminSliceStatus):
    live_enabled: StrictBool | None = None
    kill_switch_engaged: StrictBool | None = None
    open_positions: JsonInt | None = None


class Incidents(AdminSliceStatus):
    open: JsonInt | None = None


class AdminOverview(BaseModel):
    generated_at: AwareDatetime | None = None
    users: Users | None = None
    accounts: Annotated[
        Accounts | None,
        Field(
            description="Counts are scoped to the serving environment (C-2.11), never demo and live together."
        ),
    ] = None
    recorder: Recorder | None = None
    storage: Annotated[
        Storage | None,
        Field(
            description="`days_until_full` is `0` when the disk has no headroom left; otherwise it is `null` unless growth is measured. The estimated fallback exists only in `CapacityReport.storage`."
        ),
    ] = None
    trading: Trading1 | None = None
    incidents_open: JsonInt | None = None
    incidents: Incidents | None = None


class PerSymbolItem(BaseModel):
    symbol: Annotated[
        str | None,
        Field(
            description="Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.",
            examples=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            pattern="^[A-Z0-9]{2,20}USDT$",
        ),
    ] = None
    used_bytes: JsonInt | None = None
    daily_growth_bytes: JsonInt | None = None
    pinned: StrictBool | None = None
    retention_days: JsonInt | None = None


class Storage1(AdminSliceStatus):
    used_bytes: JsonInt | None = None
    free_bytes: JsonInt | None = None
    daily_growth_bytes: JsonInt | None = None
    days_until_full: StrictFloat | None = None
    per_symbol: list[PerSymbolItem] | None = None
    projection_basis: Annotated[
        Literal["measured", "estimated", "nothing_recorded"] | None,
        Field(
            description="Source of `daily_growth_bytes`. `measured`: the recorder's DiskBudget fit. `estimated`: no measurement yet, so 0.75 GB/day per recorded symbol (7.5e8 bytes, upper bound of the 0.5-0.75 band at 200-depth); `estimated` is `true` (convention C10). `nothing_recorded`: no symbol recorded, so growth is `0` by fact and `days_until_full` is `null`, or `0` when the disk has no headroom left (as for every basis). **Open-ended for readers:** clients must tolerate values they do not know, so adding a basis is an additive change (C-6.3).\n"
        ),
    ] = None
    estimated: Annotated[
        StrictBool | None,
        Field(
            description="`true` iff `projection_basis` is `estimated`; otherwise `false` or omitted."
        ),
    ] = None


class Ingestion(AdminSliceStatus):
    messages_per_sec: StrictFloat | None = None
    queue_depth: JsonInt | None = None
    dropped_last_hour: JsonInt | None = None


class RateBudgetItem(BaseModel):
    exchange_account_id: UUID | None = None
    label: str | None = None
    limit_per_minute: JsonInt | None = None
    peak_used_per_minute: JsonInt | None = None
    utilisation_pct: StrictFloat | None = None


class SubaccountCapacity(AdminSliceStatus):
    tier: Annotated[
        Literal["regular", "business_kyc"] | None,
        Field(
            description="**Open-ended for readers:** clients must tolerate values they do not know, so adding a tier is an additive change (C-6.3).\n"
        ),
    ] = None
    cap: Annotated[
        JsonInt | None,
        Field(description="5 for `regular`, 20 for `business_kyc`, `null` while unrecorded."),
    ] = None
    used: Annotated[
        JsonInt | None,
        Field(
            description="Most non-deleted sub-accounts in the process environment (live in production; C-2.11) under any one main account (`exchange_accounts.kind = sub`): the cap binds exchange UIDs, per main. The process environment is `CV_ENV`, the process-scope key (`20-architecture.md` §7.2), not the per-session `/session/environment` switch.\n",
            ge=0,
        ),
    ] = None
    tier_source: Annotated[
        Literal["recorded", "unrecorded"] | None,
        Field(description="Deliberately closed; readers may rely on these two values."),
    ] = None
    recorded_at: Annotated[
        AwareDatetime | None,
        Field(
            description="When the tier was recorded (the setting's `updated_at`); `null` if never."
        ),
    ] = None


class Incident(BaseModel):
    id: UUID
    component: str
    severity: Literal["debug", "info", "warning", "error", "critical"]
    status: Literal["open", "acknowledged", "resolved"]
    title: Annotated[str | None, Field(max_length=200)] = None
    detail: Annotated[str | None, Field(max_length=2000)] = None
    occurrences: Annotated[JsonInt | None, Field(ge=1)] = None
    first_seen_at: AwareDatetime
    last_seen_at: AwareDatetime
    acknowledged_by: UUID | None = None
    resolved_at: AwareDatetime | None = None
    runbook_ref: str | None = None
    acknowledged_at: AwareDatetime | None = None
    signature: Annotated[
        str | None,
        Field(
            description="Stable grouping key (E42-T05): a hash of the component, the error class and the normalised message. Equal signatures in one component are the same fault.\n",
            pattern="^[0-9a-f]{16}$",
        ),
    ] = None


class StatechartMachine(BaseModel):
    machine_key: Annotated[str, Field(description="The `machineKey` of this machine.")]
    machine_kind: Annotated[str, Field(description="Catalogue id (`28-statechart-catalogue.md`).")]
    environment: Annotated[
        Literal["live", "demo", "testnet"],
        Field(
            description="Structural environment selector (arch P9). Mirrors the Postgres type `exchange_env`."
        ),
    ]
    state: Annotated[
        str,
        Field(
            description="The published state as on the `machines.{entity}.state` topic: the active direct child of the chart root (the first region's, for a parallel chart).\n"
        ),
    ]
    machine_hash: Annotated[
        str,
        Field(
            description="The snapshot's chart hash (sha256 of the canonical chart JSON).",
            pattern="^[0-9a-f]{64}$",
        ),
    ]
    lock_matches: Annotated[
        StrictBool,
        Field(
            description="Whether `machine_hash` equals the committed `machine_hashes.lock` entry."
        ),
    ]
    chain_trips: Annotated[
        JsonInt,
        Field(
            description="The snapshot's `chain_trips` count; above 0 the machine is latched degraded.",
            ge=0,
        ),
    ]
    degraded: Annotated[
        StrictBool, Field(description="`chain_trips > 0`; cleared only by an operator.")
    ]
    deferred_depth: Annotated[
        JsonInt | None,
        Field(
            description="Deferred events held in the snapshot (`onUnhandled: defer`); `null` if it carries no deferred list.\n",
            ge=0,
        ),
    ]
    updated_at: Annotated[AwareDatetime, Field(description="When the snapshot was written.")]


class RecentEvent(BaseModel):
    event_type: str
    phase: Literal["ahead", "commit", "fault"]
    from_states: list[str] | None = None
    to_states: list[str] | None = None
    faulted: StrictBool | None = None
    occurred_at: AwareDatetime


class StatechartMachineDetail(BaseModel):
    snapshots: AdminSliceStatus
    events: AdminSliceStatus | None = None
    machine: StatechartMachine | None = None
    context_summary: Annotated[
        dict[str, str | StrictFloat | StrictBool | None] | None,
        Field(description="Redacted scalar context; only the keys allowed for the kind."),
    ] = None
    configuration: Annotated[
        list[str] | None, Field(description="Every active state id, ancestors included, sorted.")
    ] = None
    config: Annotated[
        dict[str, Any] | None,
        Field(
            description="The chart JSON registered for the kind (`statechart/machines/*.machine.json`)."
        ),
    ] = None
    recent_events: Annotated[
        list[RecentEvent] | None,
        Field(
            description="The latest `machine_events` rows, newest first, without payloads.",
            max_length=50,
        ),
    ] = None


class StatechartExport(BaseModel):
    machine_kind: str
    machine_hash: Annotated[
        str,
        Field(
            description="sha256 of the registered chart's canonical JSON (`registry.machine_hash`).",
            pattern="^[0-9a-f]{64}$",
        ),
    ]
    stately: Annotated[
        dict[str, Any],
        Field(
            description="The chart without the six CV policy keys, importable into Stately Studio."
        ),
    ]


class StatechartKindSummary(BaseModel):
    machine_kind: str
    environment: Annotated[
        Literal["live", "demo", "testnet"],
        Field(
            description="Structural environment selector (arch P9). Mirrors the Postgres type `exchange_env`."
        ),
    ]
    machines: Annotated[JsonInt, Field(ge=1)]
    by_state: Annotated[
        dict[str, JsonInt],
        Field(description="Live machines per published `state`; a state with none is left out."),
    ]
    chain_trips: Annotated[JsonInt, Field(description="Sum over the machines.", ge=0)]
    degraded_machines: Annotated[
        JsonInt, Field(description="Machines whose `chain_trips` latch is set.", ge=0)
    ]
    dropped_receipts: Annotated[
        JsonInt | None,
        Field(
            description="`cv_machine_dropped_receipts_total` for the kind since process start (the library counts per interpreter and never persists it); `null` when the metric cannot be read.\n",
            ge=0,
        ),
    ]


class StartViewAsRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    target_user_id: Annotated[UUID, Field(description="The `User.id` to view as.")]
    reason: Annotated[
        str,
        Field(
            description="Why the viewer needs this view; mandatory (SCR-124). It is recorded in the `admin.view_as_started` record only: never shown to the target, never part of a step-up `action_summary` and never written to a log line.\n",
            max_length=500,
            min_length=1,
            pattern="[^\\s\\u00AD\\u034F\\u061C\\u115F\\u1160\\u17B4\\u17B5\\u180B-\\u180F\\u200B-\\u200F\\u2028-\\u202F\\u2060-\\u206F\\u2800\\u3164\\uFE00-\\uFE0F\\uFEFF\\uFFA0\\uFFF9-\\uFFFB]",
        ),
    ]


class ViewAsContext(BaseModel):
    target_user_id: Annotated[UUID, Field(description="The target's `User.id`.")]
    target_username: Annotated[
        str, Field(description="The target's `User.username`.", max_length=40)
    ]
    target_display_name: Annotated[
        str | None,
        Field(
            description="The target's `User.display_name`; the banner falls back to the username.",
            max_length=80,
        ),
    ]
    started_at: AwareDatetime
    expires_at: Annotated[
        AwareDatetime,
        Field(description="`started_at` plus 30 minutes, set by the server; nothing extends it."),
    ]
    read_only: Annotated[Literal[True], Field(description="Always true: it never allows a change.")]
    state: Annotated[
        Literal["active", "expired"],
        Field(
            description="`active`: the session views as the target. `expired`: the server ended the context (at `expires_at`, or because the viewer or the target stopped being eligible), and it is held until `DELETE /auth/session/view-as` clears it. Until then every operation but the viewer's own ones and the protective writes answers `403 view_as_expired`.\n"
        ),
    ]


class Key(BaseModel):
    exchange_account_id: UUID | None = None
    key_id_masked: Annotated[
        str | None,
        Field(
            description="At most the last 4 characters of the key id: `...` plus `key_id_last4` (SR-E27-03), as `ApiKey.key_id_masked`.",
            pattern="^\\.\\.\\.[A-Za-z0-9]{4}$",
        ),
    ] = None
    status: Annotated[
        Literal["pending", "active", "rotating", "revoked", "expired", "invalid"] | None,
        Field(
            description="Only `active` and `rotating` keys are signable (`21-database-schema.md` §3.2.3a). `invalid`: the exchange rejected the key's credential (exchange refusal codes `10003` or `10004`), which `24-internal-schemas.md` §8.6 answers by marking the key `invalid`; it is not signable.\n"
        ),
    ] = None
    age_days: JsonInt | None = None
    expires_at: AwareDatetime | None = None
    withdrawal_permission_present: Annotated[
        StrictBool | None,
        Field(description="MUST be false; true raises a critical finding immediately."),
    ] = None
    ip_whitelist_matches_expected: StrictBool | None = None
    last_verified_at: AwareDatetime | None = None


class Auth(BaseModel):
    users_without_mfa: JsonInt | None = None
    failed_logins_24h: JsonInt | None = None
    denied_requests_24h: JsonInt | None = None
    active_elevated_sessions: JsonInt | None = None


class Audit(BaseModel):
    last_chain_verification_at: AwareDatetime | None = None
    chain_intact: StrictBool | None = None
    entries_total: JsonInt | None = None


class Finding(BaseModel):
    severity: Literal["debug", "info", "warning", "error", "critical"] | None = None
    code: str | None = None
    message: str | None = None


class SecuritySummary(BaseModel):
    generated_at: AwareDatetime | None = None
    keys: list[Key] | None = None
    auth: Auth | None = None
    audit: Audit | None = None
    findings: list[Finding] | None = None


class KekRewrapRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    environment: Annotated[
        Literal["live", "demo", "testnet"],
        Field(
            description="Structural environment selector (arch P9). Mirrors the Postgres type `exchange_env`."
        ),
    ]
    to_version: Annotated[
        JsonInt,
        Field(
            description="The environment's current KEK version; rows move from `to_version - 1`. The maximum is that of the `integer` column `kek_versions.version`.\n",
            ge=2,
            le=2147483647,
        ),
    ]


class KekRewrapResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    run_id: Annotated[
        UUID, Field(description="This run. Every audit record of the run carries it.")
    ]
    environment: Annotated[
        Literal["live", "demo", "testnet"],
        Field(
            description="Structural environment selector (arch P9). Mirrors the Postgres type `exchange_env`."
        ),
    ]
    from_version: Annotated[
        JsonInt,
        Field(description="The previous KEK version, `to_version - 1`.", ge=1, le=2147483646),
    ]
    to_version: Annotated[JsonInt, Field(ge=2, le=2147483647)]
    resumed: Annotated[
        StrictBool,
        Field(
            description="True when this run opened with `security.kek_rotation_resumed`: an earlier run had already moved rows of this rotation and unrevoked API key rows were still left at `from_version`. False when it opened with `security.kek_rotation_started`: no earlier run had moved a row, or no row was left to move.\n"
        ),
    ]
    rewrapped: Annotated[
        JsonInt, Field(description="API key rows this run moved to `to_version`.", ge=0)
    ]
    remaining: Annotated[
        JsonInt,
        Field(
            description="Rows of the environment still at `from_version` after this run: unrevoked API key rows, failed rows included, plus auth keyring rows and the environment's audit export signing keys still holding a seed (`audit_signing_keys`, ADR-0039 decision 6, Q3), which only the rotation boot moves.\n",
            ge=0,
        ),
    ]
    failed: Annotated[
        JsonInt,
        Field(
            description="API key rows this run could not re-wrap. Each stays at `from_version` and is audited as `security.kek_rotation_failed`.\n",
            ge=0,
        ),
    ]
    complete: Annotated[
        StrictBool,
        Field(
            description="True when the run ended with `security.kek_rotated`: no unrevoked API key row, no auth keyring row and no signing key holding a seed is left at `from_version`, and no row failed. False when it ended with `security.kek_rotation_incomplete`.\n"
        ),
    ]


class TradingDisabledProblem(Problem):
    code: Annotated[
        Literal["trading_disabled"],
        Field(description="Stable machine-readable error code from `x-error-codes`."),
    ]
    reason: Annotated[
        Literal[
            "maintenance",
            "account_disabled_by_policy",
            "no_active_key",
            "account_unhealthy",
            "account_stale",
        ],
        Field(
            description="Why the shared order-entry gate refused an order (#837 Q5; E42-T03 and E27-T04). The server's set is closed and listed in `24-internal-schemas.md` 8.10. `account_stale` (E29-T06, #914): reconciliation has failed for 2 minutes on the account and no operator has resolved it yet (`resolveReconciliation`). **Open-ended for readers:** clients must tolerate values they do not know, so adding a reason is an additive change (C-6.3).\n"
        ),
    ]


class AuthenticatedResponse(BaseModel):
    status: Literal["authenticated"]
    tokens: TokenBundle
    user: User


class LoginResponse(RootModel[AuthenticatedResponse | MfaChallengeResponse]):
    root: Annotated[AuthenticatedResponse | MfaChallengeResponse, Field(discriminator="status")]


class MfaEnrollConfirmResponse(AuthenticatedResponse):
    mfa_method: MfaMethod
    recovery_codes: Annotated[
        list[str],
        Field(
            description="The user's 10 new single-use recovery codes (SR-022), shown exactly once. The previous set stopped working when these were issued.\n",
            max_length=10,
            min_length=10,
        ),
    ]


class SessionInfo(BaseModel):
    user: User
    permissions: list[str]
    account_scope: Annotated[
        list[UUID],
        Field(
            description="Accounts whose view grant is live and not frozen; an Owner holds no grant rows, so [] does not mean all."
        ),
    ]
    allowed_environments: list[Literal["live", "demo", "testnet"]] | None = None
    kill_switch: KillSwitch | None = None
    server_time: AwareDatetime
    step_up_expires_at: Annotated[
        AwareDatetime | None,
        Field(
            description='Latest live step-up grace-window expiry on this session (E09-S04); null if none. Always null while the session is idle-locked and in the `POST /auth/unlock` response: no elevation survives the lock (see "Idle lock").\n'
        ),
    ] = None
    clock_offset_ms: Annotated[
        JsonInt | None,
        Field(
            description="Backend clock minus Bybit server time; |offset| > 1000 ms is an incident."
        ),
    ] = None
    api_version: str | None = None
    feature_flags: Annotated[
        dict[str, Any] | None, Field(description="Flags resolved for this user.")
    ] = None
    session: SessionState


class CreateUserRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    username: Annotated[str, Field(max_length=40, min_length=3, pattern="^[a-zA-Z0-9._-]+$")]
    email: EmailStr
    display_name: Annotated[str | None, Field(max_length=80)] = None
    roles: Annotated[
        list[Literal["viewer"]],
        Field(
            description="Invites grant `viewer` only (#2109); the owner promotes after activation.",
            max_length=1,
            min_length=1,
        ),
    ]
    mfa_required: StrictBool = True
    account_access: list[AccountAccessGrantInput] | None = None
    __null_refused = field_validator("display_name", "account_access", mode="before")(_refuse_null)


class ExchangeAccount(BaseModel):
    id: UUID
    exchange: Annotated[
        Literal["bybit"],
        Field(
            description="Exchange identifier. v1 supports Bybit only (locked scope: Bybit USDT linear perpetuals).\nMirrors the Postgres type `exchange_code`; the adapter abstraction\n(`24-internal-schemas.md`) exists so a second value can be added without a breaking change.\n"
        ),
    ]
    environment: Annotated[
        Literal["live", "demo", "testnet"],
        Field(
            description="Structural environment selector (arch P9). Mirrors the Postgres type `exchange_env`."
        ),
    ]
    kind: Literal["main", "sub"]
    label: Annotated[str, Field(max_length=80)]
    exchange_uid: str
    parent_account_id: UUID | None = None
    connection_state: (
        Literal["pending", "connected", "degraded", "disconnected", "disabled"] | None
    ) = None
    key_status: Literal["missing", "pending", "active", "rotating", "expired", "invalid"] | None = (
        None
    )
    position_mode: Literal["one_way", "hedge"] | None = None
    margin_mode: Literal["cross", "isolated", "portfolio"] | None = None
    active_profile_id: UUID | None = None
    balance: WalletBalance | None = None
    balance_stale: StrictBool | None = None
    balance_stale_since: Annotated[
        AwareDatetime | None,
        Field(
            description="Last refresh plus the 10 s threshold while `balance_stale` is true, else `null`."
        ),
    ] = None
    health: Annotated[
        AccountHealth | None, Field(description="`null` until the account is monitored.")
    ] = None
    enabled: StrictBool = True
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None


class AccountConsequenceSummary(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    exchange_account_id: UUID
    open_positions: Annotated[
        list[Position], Field(description="Every open position, with its native stop-loss state.")
    ]
    working_orders: Annotated[JsonInt, Field(description="Orders working on the exchange.", ge=0)]
    running_algos: Annotated[JsonInt, Field(description="Emulated algos still running.", ge=0)]
    assigned_users: Annotated[
        list[AssignedUser],
        Field(description="Users granted this account through `user_account_access`."),
    ]
    armed_rules: Annotated[
        list[ArmedRule],
        Field(
            description="Armed rules scoped to the account, listed by name; the action disarms them."
        ),
    ]


class OpenExposureProblem(Problem):
    consequences: AccountConsequenceSummary | None = None
    remedy: Annotated[
        Literal["leave_positions", "fix_key"] | None,
        Field(
            description="What the client does after `409 exposure_unknown`; `components.parameters.OpenExposure` says which applies. `leave_positions`: send the disable or the revoke again with `open_exposure=leave_positions`; a delete is not sent again, the account is disabled instead (`updateExchangeAccount` with `enabled: false`) and never deleted, and that disable must carry `open_exposure=leave_positions`: without a choice it is `409 exposure_unknown` again. `fix_key`: put the key right at the exchange, then send the request again; until then no choice proceeds. The resend is a new request with a new `Idempotency-Key`: under the same key the identical request replays the stored `409` for 24 h, and a request with another `open_exposure` is `409 idempotency_key_reuse` (the Idempotency rule of `info.description`). It advises the SCR-129 dialog: the choice stays the Owner's (SR-E27-07), and a client never sends it on its own. Closed: a new value is a breaking change (C-6.3).\n"
        ),
    ] = None


class KeyVerification(BaseModel):
    passed: StrictBool
    uid: str | None = None
    uta: Annotated[
        StrictBool | None,
        Field(
            description="From the key-info `uta` field; the deprecated `unified` field is never read."
        ),
    ] = None
    read_only: Annotated[
        StrictBool | None,
        Field(description="From the key-info `readOnly` field, which alone decides write access."),
    ] = None
    permissions: Annotated[
        dict[str, list[Permission]] | None,
        Field(
            description="As reported. Every right must be on the `createApiKey` allow-list (step 2). A group or right whose name is not a plain identifier is left out of the display, though the right is still refused.\n",
            max_length=32,
        ),
    ] = None
    withdraw_enabled: Annotated[
        StrictBool,
        Field(
            description="Must be false; a true value causes rejection. Sent only once the key's rights were read, never as a default (`KeyVerificationNotRead`)."
        ),
    ]
    ip_whitelist: Annotated[
        list[IpWhitelistItem] | None,
        Field(
            description="At most 20 entries, each an address, a range or `*`: any other entry is left out of the display.\n",
            max_length=20,
        ),
    ] = None
    ip_whitelist_matches_egress: Annotated[
        StrictBool | None,
        Field(
            description="True only when the whitelist is non-empty and every entry is the configured egress IP itself (no wildcard, no range)."
        ),
    ] = None
    egress_ip: Annotated[
        IPv4Address | IPv6Address | None,
        Field(
            description="The deployment's configured egress IP (`CV_EGRESS_IP`), the one address a key's IP whitelist may hold; `null` while none is configured. It comes from configuration, never from a request header. It is the address the Owner adds to the key's whitelist at the exchange when the exchange refused the egress IP or `ip_whitelist_matches_egress` is false (US-ACCT-003). Confidential: served only to a caller holding `keys:manage` or `keys:read`, and never written to an audit record or used as a metric label.\n"
        ),
    ] = None
    clock_offset_ms: JsonInt | None = None
    probe_ret_code: JsonInt | None = None
    warnings: list[Literal["key_expiring_soon", "clock_skew"]] | None = None


class KeyVerificationPassed(KeyVerification):
    passed: Literal[True]


class KeyRejectedProblem(Problem):
    code: Annotated[
        Literal["validation_failed"],
        Field(description="Stable machine-readable error code from `x-error-codes`."),
    ]
    verification: KeyVerification | KeyVerificationNotRead | None = None


class ApiKeyRotation(BaseModel):
    rotation_id: UUID | None = None
    old_key_id: UUID | None = None
    new_key: ApiKey | None = None
    verification: KeyVerification | None = None
    overlap_until: AwareDatetime | None = None
    state: Literal["overlapping", "completed", "failed"] | None = None


class KeyTestResult(BaseModel):
    passed: Annotated[
        StrictBool | None,
        Field(
            description="True only when the verification passed, the REST probe succeeded and, with `include_ws`, the private WS `auth` succeeded.\n"
        ),
    ] = None
    checked_at: AwareDatetime | None = None
    rest: Rest | None = None
    websocket: Annotated[
        Websocket | None,
        Field(
            description="Omitted when `include_ws` is false: that half did not run, and no `ok: true` is sent for it.\n"
        ),
    ] = None
    verification: Annotated[
        KeyVerification | KeyVerificationNotRead | None,
        Field(
            description="The verification as far as the pipeline got. Omitted when the REST half reached no verdict (a timeout, an outage, a refused signature, a clock outside the `recv_window` or a rate limit): an earlier check's standing result is never shown in its place, because an outage must not read as a pass (SR-E27-18). A key the exchange refused before its rights were read is `KeyVerificationNotRead`.\n"
        ),
    ] = None


class KlineResponse(BaseModel):
    symbol: Annotated[
        str,
        Field(
            description="Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.",
            examples=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            pattern="^[A-Z0-9]{2,20}USDT$",
        ),
    ]
    interval: str | None = None
    bar_type: (
        Literal["time", "tick", "volume", "range", "delta", "renko", "pnf", "heikin_ashi"] | None
    ) = None
    bars: list[Bar]
    meta: BarsMeta


class HeatmapResponse(BaseModel):
    symbol: Annotated[
        str | None,
        Field(
            description="Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.",
            examples=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            pattern="^[A-Z0-9]{2,20}USDT$",
        ),
    ] = None
    from_: Annotated[AwareDatetime | None, Field(alias="from")] = None
    to: AwareDatetime | None = None
    time_bucket_ms: JsonInt | None = None
    price_grouping: JsonInt | None = None
    times: list[AwareDatetime] | None = None
    prices: list[Decimal] | None = None
    bid_matrix: Annotated[
        list[list[StrictFloat]] | None,
        Field(description="Row-major [price][time] resting bid size."),
    ] = None
    ask_matrix: Annotated[
        list[list[StrictFloat]] | None,
        Field(description="Row-major [price][time] resting ask size."),
    ] = None
    max_value: StrictFloat | None = None
    normalize: Literal["none", "column", "window"] | None = None
    estimated: StrictBool = False
    first_available: Annotated[
        AwareDatetime | None,
        Field(
            description="Start of the symbol's earliest recorded book history (heatmap cells, book snapshots or book deltas, whichever is older); null when nothing was ever recorded (E21-T03)."
        ),
    ] = None
    history: Annotated[
        Literal["full", "partial", "none"] | None,
        Field(
            description="`full`: recorded history covers the requested `from`. `partial`: it starts later, and the response starts at the bucket holding `first_available`. `none`: no recorded history in the window, with empty axes and matrices (not an error)."
        ),
    ] = None
    samples: Annotated[
        list[Sample] | None,
        Field(
            description="One per `times` entry: the native 100 ms book samples aggregated into the column (24 §6.1). 0 is a column with no recorded data (a gap, never interpolated); a complete column holds `effective_time_bucket_ms / 100`."
        ),
    ] = None
    estimated_columns: Annotated[
        list[StrictBool] | None,
        Field(
            description="One per `times` entry; true for a column built from a resyncing book or an unverified snapshot (24 §6.3)."
        ),
    ] = None
    effective_time_bucket_ms: Annotated[
        Literal[100, 250, 500, 1000, 5000, 60000] | None,
        Field(
            description="The bucket the `times` axis is built at; coarser than `time_bucket_ms` only when `clamped`."
        ),
    ] = None
    segments: Annotated[
        list[HeatmapSegment] | None,
        Field(
            description="Consecutive spans of the served range, oldest first, each with its source and effective resolution."
        ),
    ] = None
    clamped: Annotated[
        StrictBool,
        Field(description="True when the server coarsened the bucket to fit its column cap."),
    ] = False
    next_cursor: Annotated[
        str | None,
        Field(
            description="Continues with the older remainder of the window (newest first); null when none remains.",
            max_length=128,
        ),
    ] = None


class RecordingStatus(BaseModel):
    overall: Annotated[
        Literal["healthy", "degraded", "warning", "down", "not_deployed"] | None,
        Field(
            description="`not_deployed` = module not built yet; ranks as healthy for `overall`. Rank: down > warning > degraded > healthy."
        ),
    ] = None
    connections: list[Connection] | None = None
    symbols: list[Symbol1] | None = None
    ingest_rate_msgs_per_sec: JsonInt | None = None
    write_backlog_rows: JsonInt | None = None
    generated_at: AwareDatetime | None = None
    role_restricted: StrictBool | None = None
    policy: RecorderPolicySettings | None = None


class OrderWithEvents(Order):
    events: list[OrderEvent] | None = None
    executions: list[Execution] | None = None


class TradeGroupDefinition(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: UUID
    created_at: AwareDatetime
    updated_at: AwareDatetime
    definition: TradeGroupDefinitionInput
    readiness: Annotated[
        TradeGroupReadiness,
        Field(
            description="Its members' readiness, as of the read; never stored; the `ETag` does not version it.\n"
        ),
    ]


class TradeGroupLeg(BaseModel):
    id: UUID | None = None
    trade_group_id: UUID | None = None
    exchange_account_id: UUID | None = None
    account_profile_id: Annotated[
        UUID | None,
        Field(
            description="The profile the leg was sized from (24-internal-schemas.md section 9.1). Null only once that profile row is gone; the leg's snapshot keeps the id.\n"
        ),
    ] = None
    status: (
        Literal[
            "pending",
            "submitted",
            "rejected",
            "open",
            "partially_filled",
            "filled",
            "cancelled",
            "closed",
            "error",
        ]
        | None
    ) = None
    sequence_no: Annotated[
        JsonInt | None,
        Field(
            description="Deterministic submission order within the group, so a partial fan-out is reproducible."
        ),
    ] = None
    resolved: ResolvedLegParams | None = None
    orders: list[UUID] | None = None
    order_details: Annotated[
        list[Order] | None,
        Field(
            description="The leg's orders as `Order` objects, each with its state, in the order of `orders`. Set on `placeOrder`'s `202` (`OrderAcceptance`); the other trade-group answers omit it and list `orders` only.\n"
        ),
    ] = None
    target_qty: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    filled_qty: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    avg_entry_price: Decimal | None = None
    avg_exit_price: Decimal | None = None
    native_sl_confirmed: Annotated[
        StrictBool | None,
        Field(
            description="True once the exchange has acknowledged a native stop-loss on this leg. The safety invariant (arch P4) requires this to become true for every filled leg; a filled leg with `false` is an alertable condition, not a cosmetic gap.\n"
        ),
    ] = None
    native_sl_confirmed_at: AwareDatetime | None = None
    risk_usd: Decimal | None = None
    realised_pnl: Decimal | None = None
    fees_paid: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    error: LegError | None = None
    submitted_at: AwareDatetime | None = None
    closed_at: AwareDatetime | None = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None


class TradeGroup(BaseModel):
    is_paper: Annotated[
        StrictBool,
        Field(
            description="True when the paper matcher produced this record rather than the exchange. Orthogonal to `environment` (24-internal-schemas.md section 1.2)."
        ),
    ] = False
    id: UUID
    client_group_ref: Annotated[
        UUID | None,
        Field(
            description="The placing request's `Idempotency-Key` (24-internal-schemas.md section 8.3 rule 1), or the server-minted UUID of a rule-, alert- or replay-originated group, as canonical lower-case UUID text.\n"
        ),
    ] = None
    symbol: Annotated[
        str,
        Field(
            description="Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.",
            examples=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            pattern="^[A-Z0-9]{2,20}USDT$",
        ),
    ]
    side: Literal["buy", "sell"]
    intent: (
        Literal[
            "entry",
            "stop_loss",
            "take_profit",
            "scale_in",
            "scale_out",
            "flatten",
            "reverse",
            "algo_child",
        ]
        | None
    ) = None
    status: Literal[
        "draft", "submitting", "partially_open", "open", "closing", "closed", "failed", "cancelled"
    ]
    atomicity: Literal["best_effort", "all_or_none"] | None = None
    algo: AlgoSpec | None = None
    rule_id: UUID | None = None
    created_by: UUID | None = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None
    closed_at: AwareDatetime | None = None
    note: str | None = None
    legs: list[TradeGroupLeg]
    totals: Totals | None = None


class OrderAcceptance(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    trade_group: TradeGroup | None
    order: Order | None
    reconciling: Annotated[
        StrictBool,
        Field(
            description="True when, as of the answer, the answered order is unresolved, its `lifecycle_state` `validated`, `submitting`, `unknown` or `quarantined`, or its state could not be read; a first answer included, and a repeat's too. A replay of a stored answer (`Idempotency-Replayed: true`) is that answer, so its value is as of the first one. False for every other state, `held` included. A separate member, because `OrderLifecycleState` mirrors the database enum and has no such value.\n"
        ),
    ]


class ReverseAcceptance(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    close: OrderAcceptance
    open: Annotated[
        OrderAcceptance | None,
        Field(
            description="The entry, or null when none was sent (`outcome` other than `reversed`)."
        ),
    ]
    outcome: Annotated[
        Literal["reversed", "close_unfilled", "close_partially_filled", "entry_refused"],
        Field(
            description="`reversed`: the close filled and the entry was accepted or, for a reversal decided from its anchors after a crash, the entry as it ended (`open` names it, `rejected` or `cancelled` included), never an assumed success; while `open.reconciling` is true the entry is not yet known to rest or fill, and reconciliation settles the symbol's exposure. `close_unfilled`: the close had not filled at the deadline, so no entry was sent and the position is as it was. `close_partially_filled`: the close had partly filled at the deadline, so no entry was sent and the position is smaller. `entry_refused`: the close filled but no entry rests: a check refused it (risk cap, rate reserve, kill switch, the deadline) or the exchange rejected it, so the account is flat on this symbol; or, before any entry was sent, the venue's own read of the position did not show it flat (`reason` `open_exposure`: size is left on the symbol; `exchange_unavailable`: the read failed, so whether size is left is not known). The last three are outcomes, not failures to hide: a client shows them as they are. A reversal decided from its anchors after a crash never answers `entry_refused`: when its entry's anchor exists, the entry's end is in `open`, so a client reads `open.state` as well as `outcome`.\n"
        ),
    ]
    reason: Annotated[
        Reason | None,
        Field(
            description="For `entry_refused` only: the refusing check's code, the exchange rejection's mapped code, or the venue read's code (`open_exposure`, `exchange_unavailable`), from the `x-error-codes` catalogue (for example `risk_limit_breached`, `trading_disabled`, `rate_limited`, `timeout`). A code, never free text. Null for every other `outcome`, which already says what happened.\n"
        ),
    ] = None


class JournalTradeDetail(JournalTrade):
    mistakes: list[str] | None = None
    checklist: list[dict[str, Any]] | None = None
    executions: list[Execution] | None = None
    notes: list[Note] | None = None
    rule_id: UUID | None = None


class LayoutGridTabset(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: Literal["tabset"]
    children: Annotated[list[LayoutGridLeaf], Field(max_length=16, min_length=1)]
    active: Annotated[
        JsonInt, Field(description="Index of the visible tab in `children`.", ge=0, le=15)
    ] = 0


class IndicatorPresetInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: Annotated[
        str,
        Field(
            description="At most 80 characters as sent, at least 1 after sanitising (above). Unique per owner and `indicator_code`, case-insensitive, among live presets (`409 conflict`, rule `name_taken`); a copy of a built-in may keep its name.",
            max_length=80,
            min_length=1,
        ),
    ]
    indicator_code: Annotated[
        str,
        Field(
            description="An indicator `id` from `listIndicators`. A value outside the pattern is rule `invalid_indicator_code`, and one that names no catalogue indicator is `unknown_indicator`; neither message echoes the value. Immutable once saved.",
            max_length=32,
            pattern="^[a-z0-9_]{2,32}$",
        ),
    ]
    params: Annotated[
        dict[str, Any],
        Field(
            description="The indicator's parameters, checked against its descriptor's `params_schema` (`listIndicators`) before anything is stored, and never clamped. Only the first parameter defect is reported: a key the descriptor does not declare (rule `additionalProperties` on `params`), else the first parameter, in the descriptor's order, that breaks one of its keywords (`type`, `enum`, `minimum`, `maximum` or `multipleOf` on `params.<name>`); the message names the bound, never the value. Stored complete and canonical: an omitted parameter is stored at its default, so changing a default later never alters a saved preset. At most 4 KiB, nesting depth 4 and 64 keys (rules `params_too_large`, `params_too_deep` and `params_too_many_keys`).\n",
            max_length=64,
        ),
    ]
    style: Annotated[
        IndicatorPresetStyle | None,
        Field(
            description="Optional; omitted means no style overrides (stored and returned as `{}`)."
        ),
    ] = None
    pane_target: Annotated[
        Literal["overlay", "subpane"],
        Field(
            description="Where the indicator draws: over the price pane, or in a sub-pane of its own."
        ),
    ] = "overlay"
    is_favourite: Annotated[
        StrictBool,
        Field(
            description="Starred in the indicator picker. A built-in is starred by saving a copy of it (`createIndicatorPreset`), possible only once `listIndicators` lists the built-in's indicator."
        ),
    ] = False
    __null_refused = field_validator("style", mode="before")(_refuse_null)


class Job(BaseModel):
    id: UUID | None = None
    kind: Annotated[
        Literal[
            "instrument_refresh",
            "audit_export",
            "backup",
            "backup_verify",
            "backup_restore",
            "rule_simulation",
            "retention_sweep",
            "reconciliation",
            "archive_import",
            "retention_purge",
        ]
        | None,
        Field(
            description="**Open-ended for readers:** clients must tolerate values they do not know, so adding a kind is an additive change (C-6.3)."
        ),
    ] = None
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"] | None = None
    progress_pct: Annotated[StrictFloat | None, Field(ge=0.0, le=100.0)] = None
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    result: Annotated[
        AuditExportResult | dict[str, Any] | None,
        Field(
            description='Kind-specific outcome once `status` is `succeeded`, otherwise null. For `kind: audit_export` it is an `AuditExportResult` or null (enforced by the `if`/`then` below); other kinds carry their own object. For `kind: backup` it is `{backup_id}`, plus `audit: "unavailable"` when the run\'s `stage: finished` record could not be written (`createBackup`), and for `kind: backup_verify` it is `{backup_id, verify_method}`, where `verify_method` is `restore_smoke`, `checksum`, `pg_verifybackup` or `duckdb_scan` (the values of `backups.verify_method`, E42-T05); a `backup_restore` result is defined with the restore contract (#3084).'
        ),
    ] = None
    error: Annotated[
        str | None,
        Field(
            description="Why a `failed` job failed, as a stable code, never a message. Open-ended for readers. A failed `audit_export` job has produced no downloadable file; it fails with `export_too_large` (its span is over `audit_export_max_rows`, or its file over `audit_export_max_bytes`; nothing is left on disk), `signing_key_rotated` (its header names a key that was no longer the active one when it came to sign), `signing_unavailable` (no KEK held, no usable key or a key that cannot be opened, or a signer failure), `audit_unavailable` (the signer refused because its write-ahead record could not be written, or the export's completion record could not be written, and its file is removed: an audit outage is answered as one) or `internal_error` (ADR-0039)."
        ),
    ] = None


class ScannerRow(BaseModel):
    symbol: Annotated[
        str,
        Field(
            description="Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.",
            examples=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            pattern="^[A-Z0-9]{2,20}USDT$",
        ),
    ]
    last_price: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    price_change_pct_24h: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    volume_24h: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    open_interest: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    cvd: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    tape_speed: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    liquidation_intensity: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    recording: StrictBool | None = None
    coverage: Annotated[
        Literal["recorded", "live_only"],
        Field(
            description="`live_only` means no local history exists for this symbol, so criteria that need recorded history were skipped for this row rather than evaluated as zero.\n"
        ),
    ]
    turnover_24h: Annotated[
        Decimal | None, Field(description="24 h turnover in USDT, `Ticker.turnover_24h`.")
    ] = None
    funding_rate: Annotated[
        Decimal | None,
        Field(description="The current funding rate, a fraction, `Ticker.funding_rate`."),
    ] = None
    spread_bps: Annotated[
        Decimal | None,
        Field(
            description="`(ask1_price - bid1_price) / mid * 10000` in decimal arithmetic, `mid` being `(ask1_price + bid1_price) / 2`, from the same `Ticker`.\n"
        ),
    ] = None
    range_pct_24h: Annotated[
        Decimal | None,
        Field(
            description="`(high_24h - low_24h) / low_24h`, a fraction, from the same `Ticker`, in decimal arithmetic; `null` while `high_24h` or `low_24h` is unknown.\n"
        ),
    ] = None
    oi_change_pct_24h: Annotated[
        Decimal | None,
        Field(
            description="`(open_interest - open_interest 24 h earlier) / open_interest 24 h earlier`, a fraction, from recorded open interest; `null` for a `live_only` row.\n"
        ),
    ] = None
    tape_speed_zscore: Annotated[
        Decimal | None,
        Field(
            description="The latest `tape_speed_zscore` metric (`24-internal-schemas.md` §7.2); an estimate (`listScannerCriteria`); `null` for a `live_only` row.\n"
        ),
    ] = None
    regime: Annotated[
        str | None,
        Field(
            description="The latest regime class, one of the classes `listScannerCriteria` lists for `regime`; an estimate; `null` for a `live_only` row.\n",
            pattern="^[a-z][a-z0-9_]{0,31}$",
        ),
    ] = None
    price_path_24h: Annotated[
        list[Decimal | None] | None,
        Field(
            description="Last price at each of the 24 hourly marks ending at `meta.generated_at`, oldest first, for a 24 h trend line; an hour with no price is `null`. Absent when the server holds no hourly prices for the symbol.\n",
            max_length=24,
        ),
    ] = None
    skipped_criteria: Annotated[
        list[ScannerCriterionId] | None,
        Field(
            description="The active criteria skipped for this row because it is `live_only` and they need recorded history (`needs_recording`), in `listScannerCriteria` order; empty for a `recorded` row.\n"
        ),
    ] = None


class ScannerMeta(DataMeta):
    capped: Annotated[
        StrictBool,
        Field(
            description="`true` when more instruments matched than `limit` returned (then `has_more` is `true` too): the rows are the first `limit` in the `sort` order.\n"
        ),
    ]
    inputs: Annotated[
        list[ScannerInputFreshness],
        Field(description="One entry per input the scan read, in no particular order."),
    ]


class ScannerFilter(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    price_change_pct_24h: ScannerRange | None = None
    turnover_24h: ScannerRange | None = None
    funding_rate: ScannerRange | None = None
    oi_change_pct_24h: ScannerRange | None = None
    spread_bps: ScannerRange | None = None
    tape_speed_zscore: ScannerRange | None = None
    range_pct_24h: ScannerRange | None = None
    regime: ScannerClassSet | None = None
    __null_refused = field_validator("price_change_pct_24h", "turnover_24h", "funding_rate", "oi_change_pct_24h", "spread_bps", "tape_speed_zscore", "range_pct_24h", "regime", mode="before")(_refuse_null)


class ScannerPresetInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: Annotated[
        str,
        Field(
            description="At most 80 characters as sent, at least 1 after sanitising (above). Unique per owner, case-insensitive (`409 conflict`, rule `name_taken`).",
            max_length=80,
            min_length=1,
        ),
    ]
    filter: ScannerFilter
    sort: Annotated[
        Literal[
            "volume_24h",
            "price_change_pct_24h",
            "cvd",
            "tape_speed",
            "open_interest",
            "liquidation_intensity",
            "turnover_24h",
            "funding_rate",
            "spread_bps",
            "range_pct_24h",
            "tape_speed_zscore",
            "oi_change_pct_24h",
        ],
        Field(description="The ranking the preset applies; omitted means `turnover_24h`."),
    ] = "turnover_24h"
    is_default: Annotated[
        StrictBool,
        Field(
            description="The preset a new scanner pane opens with. At most one per owner: setting it clears the owner's previous default (`createScannerPreset`)."
        ),
    ] = False


class ScannerPreset(BaseModel):
    id: UUID
    name: str
    filter: Annotated[
        ScannerFilter, Field(description="The stored criteria the server knows today.")
    ]
    sort: Annotated[
        Literal[
            "volume_24h",
            "price_change_pct_24h",
            "cvd",
            "tape_speed",
            "open_interest",
            "liquidation_intensity",
            "turnover_24h",
            "funding_rate",
            "spread_bps",
            "range_pct_24h",
            "tape_speed_zscore",
            "oi_change_pct_24h",
        ],
        Field(
            description="A `runScanner` ranking key. **Open-ended for readers** (C-6.3); a writer sends a listed value that `listScannerCriteria`'s `sort_keys` does not list with `available: false`. A preset stores one.\n"
        ),
    ]
    is_default: StrictBool
    unavailable_criteria: Annotated[
        list[ScannerCriterionId],
        Field(
            description="Criteria the stored filter names that the server no longer knows or lists with `available: false`, never silently dropped (and the stored `sort` key when `sort_keys` lists it with `available: false`; `sort` is returned as stored): they are left out of `filter` and `runScanner`, and listed here until a `PUT` saves the preset without them. Usually empty.\n"
        ),
    ]
    version: Annotated[
        JsonInt,
        Field(
            description="1 on create, raised by one on every change; informative only (no `If-Match`).",
            ge=1,
        ),
    ]
    created_at: AwareDatetime
    updated_at: AwareDatetime


class IndicatorDescriptor(BaseModel):
    id: str
    name: str
    category: Literal["trend", "momentum", "volatility", "volume", "orderflow"] | None = None
    pane: Literal["price", "sub", "both"]
    compute: Annotated[
        Literal["client_worker", "server"],
        Field(
            description="Set by the server from the indicator's rule eligibility (ADR-0034), never taken from a request. `server` indicators are computed by the backend indicator kernel from tape-built bars and delivered on the WS topic `indicators.{symbol}.{bar_type}.{param}` (`23-ws-protocol.md` §6.1); `client_worker` indicators are computed in the chart engine's worker from bars already in the client.\n"
        ),
    ]
    estimated: Annotated[
        StrictBool, Field(description="True for heuristic signals that infer unobservable intent.")
    ] = False
    params_schema: Annotated[
        dict[str, Any],
        Field(
            description="JSON Schema for this indicator's parameters; the settings form renders from it."
        ),
    ]
    defaults: dict[str, Any] | None = None
    outputs: Annotated[
        list[IndicatorOutput] | None,
        Field(
            description="The indicator's series, in the order its kernel emits them (the WS `v` of a `server` instance, `23-ws-protocol.md` §14.10). `name` is the label screen readers use.\n",
            min_length=1,
        ),
    ] = None
    warmup_bars: Annotated[
        JsonInt | None,
        Field(
            description="Closed bars before the first value at `defaults` (`24-internal-schemas.md` §7.4); it grows with period-like parameters. An output is `null` before it, never 0.\n",
            ge=0,
        ),
    ] = None
    unit: Annotated[
        Literal[
            "price",
            "qty",
            "notional",
            "ratio",
            "pct",
            "bps",
            "count",
            "ms",
            "zscore",
            "enum",
            "bool",
        ]
        | None,
        Field(
            description="Every output's unit (24 §7.1); a client renders one it does not know unitless. **Open-ended for readers:** clients must tolerate values they do not know, so adding a unit is an additive change (C-6.3).\n"
        ),
    ] = None
    nullable_when: Annotated[
        str | None,
        Field(
            description="When an output is `null`, with the bar count and reason, for screen readers."
        ),
    ] = None


class ExchangeCallRecord(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    event_id: Annotated[JsonInt, Field(description="The `OrderEvent.id` it belongs to.")]
    at: AwareDatetime
    transport: Annotated[
        Literal["rest", "ws_trade", "ws_private"],
        Field(description="A REST call, a trade-socket request or a private-stream push."),
    ]
    method: Annotated[Literal["GET", "POST"] | None, Field(description="REST only.")] = None
    endpoint: Annotated[
        str | None,
        Field(
            description="REST path only, never with a query string.",
            max_length=64,
            pattern="^/[A-Za-z0-9/._-]*$",
        ),
    ] = None
    op: Annotated[
        str | None,
        Field(
            description="Trade-socket operation only.", max_length=64, pattern="^[a-z][a-z0-9._-]*$"
        ),
    ] = None
    req_id: Annotated[
        str | None, Field(description="Trade-socket request id only.", max_length=64)
    ] = None
    topic: Annotated[
        str | None,
        Field(
            description="Private-stream topic of a push only.",
            max_length=64,
            pattern="^[a-z][a-z0-9._-]*$",
        ),
    ] = None
    http_status: JsonInt | None = None
    ret_code: JsonInt | None = None
    ret_msg: Annotated[str | None, Field(max_length=2048)] = None
    latency_ms: Annotated[JsonInt | None, Field(ge=0)] = None
    request_redacted: ExchangeRecordFields | None = None
    response_redacted: ExchangeRecordFields | None = None


class CapacityReport(BaseModel):
    generated_at: AwareDatetime | None = None
    storage: Storage1 | None = None
    ingestion: Ingestion | None = None
    rate_budget: list[RateBudgetItem] | None = None
    rate_budget_status: AdminSliceStatus | None = None
    subaccounts: SubaccountCapacity | None = None


class ApiKeyWithVerification(BaseModel):
    key: ApiKey
    verification: KeyVerificationPassed


class OrderDiagnostics(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    order: Order
    events: list[OrderEvent]
    exchange_calls: Annotated[
        list[ExchangeCallRecord] | None,
        Field(
            description="The order's stored exchange records, oldest first, each linked to its event by `event_id` (SR-E29-08).\n"
        ),
    ] = None
    reconciliation: Reconciliation | None = None


class RuleArithmeticNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    node_id: str
    op: Literal["add", "sub", "mul", "div", "abs", "min", "max", "neg", "pct_of"]
    operands: Annotated[
        list[RuleMetricRef | RuleOperand1 | RuleArithmeticNode], Field(max_length=8, min_length=1)
    ]


class RuleComparisonNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    node_id: str
    op: Literal[
        "gt",
        "gte",
        "lt",
        "lte",
        "eq",
        "neq",
        "between",
        "outside",
        "crosses_above",
        "crosses_below",
        "changed",
        "is_true",
        "is_false",
        "in_set",
        "not_in_set",
    ]
    left: Annotated[
        RuleMetricRef | RuleOperand1 | RuleArithmeticNode,
        Field(
            description="A value position in the condition tree. Exactly one form is present:\na metric reference, a constant, or an arithmetic node.\n"
        ),
    ]
    right: Annotated[
        RuleMetricRef | RuleOperand1 | RuleArithmeticNode | None,
        Field(
            description="A value position in the condition tree. Exactly one form is present:\na metric reference, a constant, or an arithmetic node.\n"
        ),
    ] = None
    right2: Annotated[
        RuleMetricRef | RuleOperand1 | RuleArithmeticNode | None,
        Field(description="Upper bound for `between` / `outside`."),
    ] = None
    set_values: list[str] | None = None
    tolerance: Annotated[
        StrictFloat | None, Field(description="Equality tolerance for float comparisons.")
    ] = None
    __null_refused = field_validator("right", "right2", "set_values", mode="before")(_refuse_null)


class RuleBooleanNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    node_id: str
    op: Literal["all_of", "any_of", "none_of", "n_of"]
    children: Annotated[
        list[RuleComparisonNode | RuleBooleanNode | RuleTemporalNode],
        Field(max_length=32, min_length=1),
    ]
    n: Annotated[JsonInt | None, Field(description="Required for `n_of`.", ge=1)] = None


class RuleTemporalNode(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    node_id: str
    op: Literal["sustained_for", "occurred_within", "count_within", "stable_for"]
    child: Annotated[
        RuleComparisonNode | RuleBooleanNode | RuleTemporalNode,
        Field(
            description="A node in the boolean DAG: a comparison leaf, a boolean combinator, or a temporal window. Every node carries a stable `node_id`, which is what lets the node-graph editor attach coordinates in `graph_layout` without putting cosmetics in the IR.\n"
        ),
    ]
    window_ms: Annotated[JsonInt, Field(ge=100, le=86400000)]
    min_count: Annotated[JsonInt, Field(ge=1)] = 1


class RuleIr(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    ir_version: Literal[1]
    trigger: RuleTrigger
    conditions: Annotated[
        RuleComparisonNode | RuleBooleanNode | RuleTemporalNode,
        Field(
            description="A node in the boolean DAG: a comparison leaf, a boolean combinator, or a temporal window. Every node carries a stable `node_id`, which is what lets the node-graph editor attach coordinates in `graph_layout` without putting cosmetics in the IR.\n"
        ),
    ]
    actions: Annotated[list[RuleAction], Field(max_length=10, min_length=1)]
    scope: RuleIrScope
    limits: RuleLimits | None = None
    variables: Annotated[
        dict[str, RuleMetricRef | RuleOperand1 | RuleArithmeticNode] | None,
        Field(description="Named intermediate expressions, evaluated before `conditions`."),
    ] = None
    __null_refused = field_validator("limits", "variables", mode="before")(_refuse_null)


class AlertConditionIr(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    ir_version: Literal[1]
    trigger: RuleTrigger
    conditions: Annotated[
        RuleComparisonNode | RuleBooleanNode | RuleTemporalNode,
        Field(
            description="A node in the boolean DAG: a comparison leaf, a boolean combinator, or a temporal window. Every node carries a stable `node_id`, which is what lets the node-graph editor attach coordinates in `graph_layout` without putting cosmetics in the IR.\n"
        ),
    ]
    variables: dict[str, RuleMetricRef | RuleOperand1 | RuleArithmeticNode] | None = None
    limits: RuleLimits | None = None
    __null_refused = field_validator("variables", "limits", mode="before")(_refuse_null)


class RuleInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: Annotated[str, Field(max_length=120, min_length=1)]
    description: Annotated[str | None, Field(description="Not stored yet.", max_length=1000)] = None
    scope: Annotated[
        Literal["global", "account", "symbol", "position", "trade_group"],
        Field(
            description="The rule's level, until a later contract delta drops it: a save stores `ir.scope.level` and does not read this member beside it, so a value that differs is ignored, not stored."
        ),
    ]
    editor: Annotated[Literal["form", "graph"], Field(description="Not stored yet.")] = "form"
    tags: Annotated[list[Tag] | None, Field(description="Not stored yet.")] = None
    ir: RuleIr
    graph_layout: Annotated[
        dict[str, Any] | None,
        Field(
            description="Node/edge coordinates for the node-graph editor. Ignored by the engine; not stored yet."
        ),
    ] = None
    note: Annotated[str | None, Field(max_length=280)] = None
    __null_refused = field_validator("description", "tags", "graph_layout", "note", mode="before")(_refuse_null)


class RuleUpdateInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: Annotated[str, Field(max_length=120, min_length=1)]
    description: Annotated[str | None, Field(description="Not stored yet.", max_length=1000)] = None
    scope: Annotated[
        Literal["global", "account", "symbol", "position", "trade_group"],
        Field(
            description="The rule's level, until a later contract delta drops it: a save stores `ir.scope.level` and does not read this member beside it, so a value that differs is ignored, not stored."
        ),
    ]
    editor: Annotated[Literal["form", "graph"], Field(description="Not stored yet.")] = "form"
    tags: Annotated[list[Tag] | None, Field(description="Not stored yet.")] = None
    ir: RuleIr
    graph_layout: Annotated[
        dict[str, Any] | None,
        Field(
            description="Node/edge coordinates for the node-graph editor. Ignored by the engine; not stored yet."
        ),
    ] = None
    note: Annotated[str | None, Field(max_length=280)] = None
    expected_version: Annotated[
        JsonInt | None,
        Field(
            description="The rule version the client edited, read only when `If-Match` is absent.",
            ge=1,
        ),
    ] = None
    __null_refused = field_validator("description", "tags", "graph_layout", "note", "expected_version", mode="before")(_refuse_null)


class RuleDetail(Rule):
    ir: RuleIr | None = None
    graph_layout: dict[str, Any] | None = None
    ir_hash: str | None = None
    last_simulation: LastSimulation | None = None


class RuleVersionDetail(RuleVersion):
    ir: RuleIr | None = None
    graph_layout: dict[str, Any] | None = None


class AlertInput(BaseModel):
    name: Annotated[str, Field(max_length=120, min_length=1)]
    symbol: Symbol | None = None
    exchange_account_id: UUID | None = None
    trigger_mode: Literal["once", "every_time", "once_per_bar"] = "once"
    channels: Annotated[
        list[Literal["in_app", "email", "webhook", "push", "desktop"]], Field(min_length=1)
    ]
    condition_ir: AlertConditionIr
    message_template: Annotated[
        str | None,
        Field(
            description="Mustache-style placeholders resolved from the rule context.",
            max_length=500,
        ),
    ] = None
    severity: Literal["debug", "info", "warning", "error", "critical"] | None = None
    expires_at: Annotated[
        AwareDatetime | None,
        Field(
            description="A past instant is refused with `422 validation_failed` (E40-D02 CC-10)."
        ),
    ] = None
    webhook_url: AnyUrl | None = None
    enabled: StrictBool = True
    cooldown_seconds: Annotated[
        JsonInt | None,
        Field(
            description="Minimum seconds between two firings; omitted on create = 60, omitted on replace = unchanged (E40-D02 CC-5).",
            ge=0,
            le=86400,
        ),
    ] = None
    __null_refused = field_validator("message_template", "severity", "cooldown_seconds", mode="before")(_refuse_null)


class WorkspaceDetail(Workspace):
    layouts: Annotated[
        list[Layout], Field(description="Live layouts ordered by `id` ascending.", max_length=32)
    ]


class LayoutGridSpec(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    version: Annotated[Literal[1], Field(description="Tree format version.")]
    root: Annotated[
        LayoutGridSplit | LayoutGridTabset | LayoutGridLeaf, Field(discriminator="type")
    ]


class LayoutGridSplit(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: Literal["row", "column"]
    children: Annotated[
        list[
            Annotated[
                LayoutGridSplit | LayoutGridTabset | LayoutGridLeaf, Field(discriminator="type")
            ]
        ],
        Field(max_length=16, min_length=2),
    ]
    sizes: Annotated[list[Size], Field(max_length=16, min_length=2)]


class LayoutInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: Annotated[
        str,
        Field(
            description="At most 40 characters as sent, at least 1 after sanitising, as for workspace names. Unique per workspace, case-insensitive, among live layouts (`409 conflict`, rule `name_taken`).",
            max_length=40,
            min_length=1,
        ),
    ]
    grid_preset: Annotated[
        Literal["1x1", "2x1", "1x2", "2x2", "1+3", "3x3", "custom"],
        Field(
            description="Named grid (`lay_preset`, `21-database-schema.md` §3.8.1) or `custom`. A named preset stores\nonly its name and fixed cell proportions: `grid_spec` is `null`, and a pane's `slot_index`\nis its cell in row-major reading order (a slot beyond the preset's cells is placed by the\nclient, e.g. floating). Any other arrangement, including a named grid whose divider was\ndragged, is saved as `custom` with its tree in `grid_spec`. **Open-ended for readers.**\n"
        ),
    ] = "1x1"
    grid_spec: Annotated[
        LayoutGridSpec | None,
        Field(description="Required when `grid_preset` is `custom`, otherwise `null` or omitted."),
    ] = None
    crosshair_sync: Annotated[
        StrictBool,
        Field(description="Layout default for crosshair sync between panes of one sync group."),
    ] = True
    level_sync: Annotated[StrictBool, Field(description="Layout default for price-level sync.")] = (
        False
    )
    symbol_sync: Annotated[StrictBool, Field(description="Layout default for symbol sync.")] = False
    hotkey_slot: Annotated[
        JsonInt | None,
        Field(
            description="`Ctrl+1..9` binding; unique among the workspace's live layouts (`409 conflict`, rule `hotkey_slot_taken`).",
            ge=1,
            le=9,
        ),
    ] = None
    is_default: Annotated[
        StrictBool,
        Field(
            description="At most one live default per workspace; `true` clears the previous default in the same transaction."
        ),
    ] = False
    panes: Annotated[
        list[LayoutPaneInput],
        Field(
            description="In any order: panes are keyed by `slot_index`, and responses sort by it.",
            max_length=16,
            min_length=0,
        ),
    ]


class Layout(BaseModel):
    id: UUID
    workspace_id: UUID
    name: str
    grid_preset: Annotated[
        Literal["1x1", "2x1", "1x2", "2x2", "1+3", "3x3", "custom"],
        Field(
            description="Named grid (`lay_preset`, `21-database-schema.md` §3.8.1) or `custom`. A named preset stores\nonly its name and fixed cell proportions: `grid_spec` is `null`, and a pane's `slot_index`\nis its cell in row-major reading order (a slot beyond the preset's cells is placed by the\nclient, e.g. floating). Any other arrangement, including a named grid whose divider was\ndragged, is saved as `custom` with its tree in `grid_spec`. **Open-ended for readers.**\n"
        ),
    ]
    grid_spec: LayoutGridSpec | None
    crosshair_sync: StrictBool
    level_sync: StrictBool
    symbol_sync: StrictBool
    hotkey_slot: Annotated[JsonInt | None, Field(ge=1, le=9)]
    is_default: StrictBool
    panes: Annotated[
        list[LayoutPane], Field(description="Ordered by `slot_index` ascending.", max_length=16)
    ]
    created_at: AwareDatetime
    updated_at: Annotated[
        AwareDatetime,
        Field(
            description="Concurrency token (also the `ETag`) of the whole layout aggregate, panes included: every write changes it, including a pane-only change and a default switch made by another layout. Always exactly 6 fractional digits plus `Z` (`YYYY-MM-DDTHH:MM:SS.ffffffZ`) and strictly increasing. Echo it exactly as received; never re-serialise it through a client date type."
        ),
    ]


class LayoutPreset(BaseModel):
    id: Annotated[UUID, Field(description="Stable for the life of the catalogue entry.")]
    name: str
    description: str | None
    is_builtin: Annotated[
        StrictBool,
        Field(
            description="Always `true`: the catalogue is static. User-saved presets are layouts with a `hotkey_slot`."
        ),
    ]
    pane_count: Annotated[JsonInt, Field(ge=0, le=16)]
    layout: LayoutInput


class WorkspaceBundle(BaseModel):
    schema_version: str
    exported_at: AwareDatetime | None = None
    workspace: WorkspaceInput
    layouts: list[LayoutInput]
    chart_templates: list[ChartTemplateInput] | None = None
    drawings: list[DrawingInput] | None = None
    indicator_presets: Annotated[
        list[IndicatorPresetInput] | None,
        Field(
            description="Export holds only the caller's live presets, never a built-in or another user's: at most 500, the per-user cap of `createIndicatorPreset`, and never truncated to the import limits below. Import (E15-S07; no operation takes a bundle yet) never trusts them: every item is validated again as on `createIndicatorPreset`, so `is_builtin` and `owner_user_id` are never honoured (an item carrying either is refused), the importer owns what is imported, and the array is imported whole or not at all. The server refuses it whole beyond 200 items or 1 MiB of preset JSON (SR-E13-07's import limits; the 1 MiB counts this array, not the whole bundle), on any invalid item, or when it would take the importer past 500 live presets.\n"
        ),
    ] = None


class Alert(AlertInput):
    id: UUID | None = None
    owner_user_id: UUID | None = None
    fire_count: JsonInt | None = None
    last_fired_at: AwareDatetime | None = None
    cooldown_seconds: Annotated[
        JsonInt | None,
        Field(
            description="Minimum seconds between two firings; omitted on create = 60, omitted on replace = unchanged (E40-D02 CC-5).",
            ge=0,
            le=86400,
        ),
    ] = None
    snoozed_until: Annotated[
        AwareDatetime | None,
        Field(
            description="UTC instant until which firings are suppressed; null = not snoozed (CC-3)."
        ),
    ] = None
    disarm_reason: Annotated[
        Literal["source_unavailable"] | None,
        Field(
            description="Why the server disarmed the alert (`enabled=false`); null otherwise. Cleared when the alert is re-enabled (CC-3)."
        ),
    ] = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None
    _AlertInput__null_refused = field_validator("message_template", "severity", "cooldown_seconds", mode="before")(_take_null)


RuleArithmeticNode.model_rebuild()
RuleBooleanNode.model_rebuild()
RuleTemporalNode.model_rebuild()
WorkspaceDetail.model_rebuild()
LayoutGridSpec.model_rebuild()
LayoutGridSplit.model_rebuild()
