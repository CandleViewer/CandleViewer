"""GENERATED FILE — DO NOT EDIT BY HAND.

Regenerate with `uv run --project services/api python scripts/generate_protocol_models.py`.
Source: docs/plan/22-api-openapi.yaml, via datamodel-code-generator.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from decimal import Decimal as _StdlibDecimal

from pydantic import (
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
)


Decimal = Annotated[
    _StdlibDecimal,
    PlainSerializer(lambda d: format(d, "f"), return_type=str),
    BeforeValidator(_StdlibDecimal),
]
"""Arbitrary-precision decimal (convention C6): serialises as a JSON/YAML
string on the wire, but is a real `decimal.Decimal` in Python — money and
size/price fields must never round-trip through float."""


class Symbol(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description="Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.",
            examples=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            pattern="^[A-Z0-9]{2,20}USDT$",
        ),
    ]


class Count(RootModel[int]):
    root: Annotated[int, Field(ge=0, le=2400)]


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
    fe_dropped_frames_total: Annotated[int, Field(ge=0, le=2400)]
    fe_gpu_memory_mb: Annotated[float | None, Field(ge=0.0, le=65536.0)] = None


class Error(BaseModel):
    field: str | None = None
    rule: str | None = None
    message: str | None = None


class Exchange(BaseModel):
    ret_code: int | None = None
    ret_msg: str | None = None
    endpoint: str | None = None
    request_id: str | None = None


class Problem(BaseModel):
    type: Annotated[AnyUrl, Field(description="`https://candleviewer.local/errors/{code}`.")]
    title: str
    status: Annotated[int, Field(ge=400, le=599)]
    detail: str | None = None
    instance: Annotated[
        str | None,
        Field(
            description="Correlation id, `urn:cv:req:{uuid}`; matches the `X-Request-Id` header and the audit entry."
        ),
    ] = None
    code: Annotated[
        str, Field(description="Stable machine-readable error code from `x-error-codes`.")
    ]
    errors: Annotated[list[Error] | None, Field(description="Field-level validation failures.")] = (
        None
    )
    required_permissions: list[str] | None = None
    retry_after_seconds: int | None = None
    exchange: Annotated[
        Exchange | None, Field(description="Present when the failure originated at Bybit.")
    ] = None


class PageMeta(BaseModel):
    next_cursor: str | None = None
    has_more: bool
    count: Annotated[
        int,
        Field(
            description="Items in this page (not the total, which is never computed for unbounded sets)."
        ),
    ]
    total: Annotated[
        int | None, Field(description="Present only where a cheap exact count exists.")
    ] = None


class Page(BaseModel):
    items: list[Any]
    meta: PageMeta


class InstrumentsPageMeta(PageMeta):
    cache_age_s: Annotated[
        float, Field(description="Seconds since this snapshot was last fetched from Bybit.")
    ]
    stale_since: Annotated[
        AwareDatetime | None,
        Field(description="When the cache started missing its refresh cadence; null if fresh."),
    ]


class CoverageHole(BaseModel):
    start_us: Annotated[int, Field(description="Gap start, exchange epoch microseconds.")]
    end_us: Annotated[int, Field(description="Gap end, exchange epoch microseconds.")]


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
            description='Requested-range gaps the local cache has no bars for yet (QA defect #1622 blocker 1 / E08-S06 "Cache hit" scenario — `GET /market/klines` is cache-only until a live `KlineFetcher` lands, so it reports holes here instead of silently pretending the exchange was consulted).'
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


class TokenBundle(BaseModel):
    access_token: str
    token_type: Literal["Bearer"]
    expires_in: Annotated[int, Field(description="Access-token lifetime in seconds (600).")]
    refresh_expires_in: Annotated[
        int | None, Field(description="Refresh-token lifetime in seconds (2592000).")
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
    expires_in: int
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
    remember_device_days: Annotated[int | None, Field(ge=0, le=30)] = 0


class MfaEnrollRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    method: Literal["totp", "webauthn"]
    label: Annotated[str | None, Field(max_length=60)] = None


class MfaEnrollResponse(BaseModel):
    method_id: UUID
    method: Literal["totp", "webauthn", "recovery_code"]
    otpauth_uri: str | None = None
    webauthn_creation_options: dict[str, Any] | None = None
    recovery_codes: Annotated[
        list[str] | None, Field(description="Shown exactly once, on first enrolment.")
    ] = None


class MfaEnrollConfirmRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    method_id: UUID
    code: str | None = None
    webauthn_attestation: dict[str, Any] | None = None


class MfaMethod(BaseModel):
    id: UUID | None = None
    kind: Literal["totp", "webauthn", "recovery_code"] | None = None
    label: str | None = None
    active: bool | None = None
    created_at: AwareDatetime | None = None
    last_used_at: AwareDatetime | None = None


class RefreshRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    refresh_token: Annotated[
        str | None, Field(description="Only for clients that cannot use cookies.")
    ] = None


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    current_password: SecretStr
    new_password: Annotated[SecretStr, Field(max_length=512, min_length=12)]


class UserSession(BaseModel):
    id: UUID | None = None
    device_name: str | None = None
    ip: str | None = None
    user_agent: str | None = None
    created_at: AwareDatetime | None = None
    last_seen_at: AwareDatetime | None = None
    expires_at: AwareDatetime | None = None
    current: bool | None = None


class User(BaseModel):
    id: UUID
    username: str
    email: EmailStr
    display_name: str | None = None
    roles: list[Literal["owner", "manager", "viewer"]]
    status: Literal["invited", "active", "disabled", "locked"]
    mfa_enabled: bool | None = None
    mfa_required: bool | None = None
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
    status: Literal["invited", "active", "disabled", "locked"] | None = None
    roles: Annotated[list[Literal["owner", "manager", "viewer"]] | None, Field(min_length=1)] = None
    mfa_required: bool | None = None


class Role(BaseModel):
    id: UUID | None = None
    name: Literal["owner", "manager", "viewer"] | None = None
    description: str | None = None
    permissions: list[str] | None = None
    user_count: int | None = None


class AccountAccessGrantInput(BaseModel):
    exchange_account_id: UUID
    level: Annotated[Literal["read", "trade"], Field(description="`trade` implies `read`.")]


class AccountAccessGrant(AccountAccessGrantInput):
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
        str,
        Field(
            description="Open set of machine codes the client renders as text: `ws_heartbeat`, `rest_only` (REST polling replaced the private WS), `ws_silent` (no REST success yet either), `no_success` (nothing for the 30 s down window), `never_connected`.\n"
        ),
    ]
    heartbeat_age_ms: Annotated[
        int | None,
        Field(
            description="Milliseconds since the last authenticated private-WS heartbeat; `null` before the first.",
            ge=0,
        ),
    ]
    rest_only: Annotated[
        bool,
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
        bool | None,
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
    label: Annotated[str | None, Field(max_length=80)] = None
    enabled: bool | None = None
    active_profile_id: UUID | None = None
    position_mode: Literal["one_way", "hedge"] | None = None
    margin_mode: Literal["cross", "isolated", "portfolio"] | None = None


class ApiKey(BaseModel):
    id: UUID
    exchange_account_id: UUID
    key_id_masked: Annotated[str, Field(description="First and last 4 characters only.")]
    label: Annotated[str | None, Field(max_length=80)] = None
    status: Literal["pending", "active", "rotating", "revoked", "expired", "invalid"]
    read_only: bool | None = None
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
    read_only: bool | None = False
    expected_uid: Annotated[
        str | None,
        Field(description="Must equal the account's `exchange_uid`; mismatch is rejected."),
    ] = None


class KeyVerification(BaseModel):
    passed: bool
    uid: str | None = None
    unified: bool | None = None
    permissions: dict[str, list[str]] | None = None
    withdraw_enabled: Annotated[
        bool, Field(description="Must be false; a true value causes rejection.")
    ]
    ip_whitelist: list[str] | None = None
    ip_whitelist_matches_egress: bool | None = None
    clock_offset_ms: int | None = None
    probe_ret_code: int | None = None
    warnings: list[str] | None = None


class ApiKeyWithVerification(BaseModel):
    key: ApiKey | None = None
    verification: KeyVerification | None = None


class RotateApiKeyRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    api_key: SecretStr
    api_secret: SecretStr
    label: Annotated[str | None, Field(max_length=80)] = None
    overlap_seconds: Annotated[int | None, Field(ge=0, le=3600)] = 300


class ApiKeyRotation(BaseModel):
    rotation_id: UUID | None = None
    old_key_id: UUID | None = None
    new_key: ApiKey | None = None
    verification: KeyVerification | None = None
    overlap_until: AwareDatetime | None = None
    state: Literal["overlapping", "completed", "failed"] | None = None


class Rest(BaseModel):
    ok: bool | None = None
    latency_ms: int | None = None
    ret_code: int | None = None
    error: str | None = None


class Websocket(BaseModel):
    ok: bool | None = None
    latency_ms: int | None = None
    error: str | None = None


class KeyTestResult(BaseModel):
    passed: bool | None = None
    checked_at: AwareDatetime | None = None
    rest: Rest | None = None
    websocket: Websocket | None = None
    verification: KeyVerification | None = None


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
    atr_period: Annotated[int | None, Field(description="Used when `unit=atr`.", ge=2, le=200)] = 14
    atr_bar_type: (
        Literal["time", "tick", "volume", "range", "delta", "renko", "pnf", "heikin_ashi"] | None
    ) = None
    atr_param: Annotated[str | None, Field(max_length=24)] = None


class Sizing(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    mode: Annotated[
        Literal[
            "fixed_qty", "fixed_notional", "pct_equity", "risk_based", "pct_position", "profile"
        ],
        Field(
            description="How a request expresses order size.\n\n**Persistence contract.** The Postgres type `sizing_mode`\n(`21-database-schema.md` §Enums) holds only the four *resolved* modes\n`fixed_qty | fixed_notional | pct_equity | risk_based`. The two extra API values are\n**request-time sugar that never reaches the database**; the OMS resolves them before\nany row is written, and `orders.requested_qty_mode` / `account_profiles.sizing_mode`\ntherefore always contain a resolved value:\n\n| API value | Resolution | Stored as |\n|---|---|---|\n| `pct_position` | `pct` % of the *current open position* qty on that symbol/account (scale-out, flatten-partial). Rejected with `validation_failed` if no position is open. | `fixed_qty` |\n| `profile` | Inherit the active `AccountProfile.sizing` block verbatim. | whatever the profile's own mode resolves to |\n\nContract test `enum_parity_sizing_mode` asserts (a) the DB enum equals this enum minus\n`x-db-enum-superset`, and (b) no persisted row ever holds a superset value.\n"
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
            description="Arbitrary-precision decimal transported as a string (convention C6).",
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
    round_to_lot: bool | None = True


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
    max_open_positions: Annotated[int | None, Field(ge=0, le=100)] = None
    max_position_notional_usd: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    max_orders_per_minute: Annotated[int | None, Field(ge=1, le=600)] = None
    max_consecutive_losses: Annotated[int | None, Field(ge=1, le=50)] = None
    lockout_minutes_after_breach: Annotated[int | None, Field(ge=0, le=1440)] = 60


class AccountProfileInput(BaseModel):
    name: Annotated[str, Field(max_length=80, min_length=1)]
    leverage: Annotated[
        str,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ]
    sizing: Sizing
    stop_loss: Offset | None = None
    take_profit: Offset | None = None
    trailing_stop: Offset | None = None
    risk_caps: RiskCaps | None = None
    allowed_symbols: Annotated[
        list[Symbol] | None,
        Field(description='Empty means "all instruments permitted by the deployment".'),
    ] = None
    require_native_stop: Annotated[
        Literal[True],
        Field(description="Always true; the safety invariant cannot be disabled (arch P4)."),
    ] = True
    default_time_in_force: Literal["GTC", "IOC", "FOK", "PostOnly"] | None = None
    default_tpsl_mode: Literal["Full", "Partial"] | None = None


class AccountProfile(AccountProfileInput):
    id: UUID | None = None
    exchange_account_id: UUID | None = None
    is_active: bool | None = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None


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
    price_scale: int | None = None
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
    funding_interval_minutes: int | None = None
    launch_time: AwareDatetime | None = None
    copy_trading: bool | None = None
    revision: Annotated[
        int | None, Field(description="Increments whenever Bybit changes the instrument metadata.")
    ] = None
    updated_at: AwareDatetime | None = None
    delisted: Annotated[
        bool | None,
        Field(description="Derived: true when `status` is not `Trading` or `PreLaunch`."),
    ] = None
    status_reason: Annotated[
        str | None,
        Field(description="Human-readable explanation of `status`, for screen readers (#182)."),
    ] = None


class RiskLimitTier(BaseModel):
    tier: int | None = None
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
    recorded: bool | None = None
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
    stale: bool | None = None


class Bar(BaseModel):
    index: Annotated[
        int | None,
        Field(
            description="Bar index, strictly increasing within (series, generation) (24 §3.1). Always present on /market/bars; `t` may repeat for non-time bars (#2014).",
            ge=0,
        ),
    ] = None
    generation: Annotated[
        int | None,
        Field(
            description="ADR-0033 series generation (= epoch); 0 until ADR-0033 is ratified. Always present on /market/bars.",
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
    trades: int | None = None
    confirm: Annotated[
        bool | None, Field(description="False for the in-progress bar (Bybit `confirm` semantics).")
    ] = None
    delta: Decimal | None = None
    cvd: Decimal | None = None
    min_delta: Decimal | None = None
    max_delta: Decimal | None = None


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
    meta: DataMeta


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
    trades: int | None = None


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
    stacked: bool | None = None
    stack_size: int | None = None
    estimated: bool | None = False


class UnfinishedAuction(BaseModel):
    high: bool | None = None
    low: bool | None = None


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
    price_grouping: int | None = None
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
    tpo_count: int | None = None


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
        bool | None,
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
    is_block_trade: bool | None = None
    cluster_size: Annotated[
        int | None, Field(description="Number of raw prints merged when clustering is on.")
    ] = None
    tick_direction: Literal["PlusTick", "ZeroPlusTick", "MinusTick", "ZeroMinusTick"] | None = None


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
    u: Annotated[int, Field(description="Monotonic update id from Bybit.")]
    seq: Annotated[int, Field(description="Cross-topic sequence from Bybit.")]
    ts: AwareDatetime
    bids: Annotated[list[Bid], Field(description="[price, size], descending.")]
    asks: Annotated[list[Ask], Field(description="[price, size], ascending.")]
    stale: bool | None = None


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
    time_bucket_ms: int | None = None
    price_grouping: int | None = None
    times: list[AwareDatetime] | None = None
    prices: list[Decimal] | None = None
    bid_matrix: Annotated[
        list[list[float]] | None, Field(description="Row-major [price][time] resting bid size.")
    ] = None
    ask_matrix: Annotated[
        list[list[float]] | None, Field(description="Row-major [price][time] resting ask size.")
    ] = None
    max_value: float | None = None
    normalize: Literal["none", "column", "window"] | None = None
    estimated: bool | None = False


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
    ]
    estimated: Annotated[
        bool | None, Field(description="True for heuristic metrics (arch P10).")
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
    side: Literal["buy", "sell"] | None = None
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
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    cluster_size: int | None = None


class Interval(BaseModel):
    from_: Annotated[AwareDatetime | None, Field(alias="from")] = None
    to: AwareDatetime | None = None
    tier: Literal["questdb", "parquet"] | None = None
    rows: int | None = None


class Gap(BaseModel):
    from_: Annotated[AwareDatetime | None, Field(alias="from")] = None
    to: AwareDatetime | None = None
    reason: (
        Literal[
            "ws_disconnect",
            "backend_restart",
            "retention_purge",
            "never_recorded",
            "exchange_outage",
        ]
        | None
    ) = None


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
    gaps: list[Gap] | None = None


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
    pinned: bool | None = None
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
    retention_days: int | None = None
    disk_bytes: int | None = None
    rows_last_hour: int | None = None
    lag_ms: int | None = None
    added_by: UUID | None = None


class Estimate(BaseModel):
    daily_bytes_estimate: int | None = None
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
        ]
        | None,
        Field(min_length=1),
    ] = ["trades", "orderbook_delta", "tickers", "liquidations"]
    depth: Literal[1, 50, 200, 500] | None = 200
    pinned: bool | None = False
    retention_days: Annotated[int | None, Field(ge=1, le=3650)] = 30


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
    pinned: bool | None = None
    retention_days: Annotated[int | None, Field(ge=1, le=3650)] = None


class Connection(BaseModel):
    endpoint: str | None = None
    state: Literal["connecting", "connected", "degraded", "disconnected"] | None = None
    subscribed_topics: int | None = None
    connected_since: AwareDatetime | None = None
    reconnects_last_hour: int | None = None
    last_ping_ms: int | None = None


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
    lag_ms: int | None = None
    rows_last_hour: int | None = None
    dropped_messages: int | None = None
    resyncs_last_hour: int | None = None
    last_event_at: AwareDatetime | None = None


class RecordingStatus(BaseModel):
    overall: Annotated[
        Literal["healthy", "degraded", "warning", "down", "not_deployed"] | None,
        Field(
            description="`not_deployed` = module not built yet; ranks as healthy for `overall`. Rank: down > warning > degraded > healthy."
        ),
    ] = None
    connections: list[Connection] | None = None
    symbols: list[Symbol1] | None = None
    ingest_rate_msgs_per_sec: int | None = None
    write_backlog_rows: int | None = None
    generated_at: AwareDatetime | None = None


class Tier(BaseModel):
    tier: Literal["questdb", "parquet", "postgres"] | None = None
    used_bytes: int | None = None
    retention_days: int | None = None


class Symbol2(BaseModel):
    symbol: Annotated[
        str | None,
        Field(
            description="Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.",
            examples=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            pattern="^[A-Z0-9]{2,20}USDT$",
        ),
    ] = None
    used_bytes: int | None = None
    daily_growth_bytes: int | None = None
    pinned: bool | None = None


class StorageUsage(BaseModel):
    disk_total_bytes: int | None = None
    disk_used_bytes: int | None = None
    disk_free_bytes: int | None = None
    projected_full_at: AwareDatetime | None = None
    daily_growth_bytes: int | None = None
    tiers: list[Tier] | None = None
    symbols: list[Symbol2] | None = None
    generated_at: AwareDatetime | None = None


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
    retain_days: Annotated[int, Field(ge=1, le=3650)]
    action: Literal["drop", "archive_parquet", "downsample", "pin"]
    symbol: Annotated[Symbol | None, Field(description="Null = global default.")] = None
    applies_to_pinned: bool | None = False


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
    depth: int | None = None
    rows: int | None = None
    bytes: int | None = None
    gap_count: int | None = None


class CreateReplaySessionRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    symbols: Annotated[list[Symbol], Field(max_length=8, min_length=1)]
    from_: Annotated[AwareDatetime, Field(alias="from")]
    to: AwareDatetime
    speed: Annotated[
        float | None,
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
    depth: Literal[1, 50, 200, 500] | None = 200
    paper_account_id: UUID | None = None
    autostart: bool | None = False


class ReplaySession(BaseModel):
    id: UUID | None = None
    state: Literal["created", "buffering", "playing", "paused", "finished", "error"] | None = None
    symbols: list[Symbol] | None = None
    from_: Annotated[AwareDatetime | None, Field(alias="from")] = None
    to: AwareDatetime | None = None
    cursor_ts: AwareDatetime | None = None
    speed: float | None = None
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
    depth: int | None = None
    paper_account_id: UUID | None = None
    created_by: UUID | None = None
    created_at: AwareDatetime | None = None
    progress_pct: Annotated[float | None, Field(ge=0.0, le=100.0)] = None
    error: str | None = None


class ReplayControlRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    action: Literal["play", "pause", "seek", "step", "set_speed", "restart"]
    speed: Annotated[float | None, Field(ge=0.0, le=100.0)] = None
    to: Annotated[AwareDatetime | None, Field(description="Required for `seek`.")] = None
    step_events: Annotated[int | None, Field(ge=1, le=100000)] = None
    step_ms: Annotated[int | None, Field(ge=1, le=3600000)] = None


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
        int | None,
        Field(
            description="Max time to cancel the loser after the winner's fill notice arrives on the WS.",
            ge=100,
            le=60000,
        ),
    ] = 2000


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
    refresh_on_fill_pct: Annotated[float | None, Field(ge=1.0, le=100.0)] = 100
    randomize_display_pct: Annotated[float | None, Field(ge=0.0, le=50.0)] = 0


class Twap(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    duration_seconds: Annotated[int | None, Field(ge=10, le=86400)] = None
    slices: Annotated[int | None, Field(ge=2, le=500)] = None
    randomize_pct: Annotated[float | None, Field(ge=0.0, le=50.0)] = 0
    limit_offset_ticks: Annotated[
        int | None, Field(description="Omit for market slices.", ge=0, le=1000)
    ] = None


class Chase(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    offset_ticks: Annotated[int | None, Field(ge=0, le=100)] = 0
    max_chases: Annotated[int | None, Field(ge=1, le=500)] = 20
    max_slippage_ticks: Annotated[int | None, Field(ge=1, le=10000)] = None
    repricing_interval_ms: Annotated[int | None, Field(ge=50, le=10000)] = 250
    fallback_to_market: bool | None = False


class Scaled(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    levels: Annotated[int | None, Field(ge=2, le=50)] = None
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


class TakeProfitLevel(BaseModel):
    offset: Offset | None = None
    pct_of_position: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None


class Bracket(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    take_profit_levels: Annotated[list[TakeProfitLevel] | None, Field(max_length=10)] = None
    move_stop_to_breakeven_at: Offset | None = None


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


class PlaceOrderRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    exchange_account_id: UUID
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
    ) = "entry"
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
    reduce_only: bool | None = False
    close_on_trigger: bool | None = False
    position_idx: Annotated[
        Literal[0, 1, 2] | None, Field(description="Required in hedge mode (1 = long, 2 = short).")
    ] = None
    trigger: TriggerSpec | None = None
    stop_loss: Offset | None = None
    take_profit: Offset | None = None
    tpsl_mode: Literal["Full", "Partial"] | None = None
    algo: AlgoSpec | None = None
    profile_id: Annotated[
        UUID | None, Field(description="Override the account's active profile for this order.")
    ] = None
    arm_token: Annotated[
        str | None,
        Field(description="Required when the request originates from one-click/hotkey entry."),
    ] = None
    note: Annotated[str | None, Field(max_length=280)] = None


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


class CancelAllRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    exchange_account_ids: Annotated[
        list[UUID] | None, Field(description="Empty = every account in scope.")
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
        bool | None, Field(description="Protects TP/SL exits from a blanket cancel.")
    ] = True


class Order(BaseModel):
    is_paper: Annotated[
        bool | None,
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
        Field(description="Deterministic, derived from the Idempotency-Key.", max_length=36),
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
    state: Literal[
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
    ]
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
    reduce_only: bool | None = None
    close_on_trigger: bool | None = None
    position_idx: int | None = None
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
    rejected_reason: str | None = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None


class OrderEvent(BaseModel):
    id: int | None = None
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
        ]
        | None,
        Field(
            description="Append-only OMS event taxonomy. Exact 1:1 mirror of the Postgres type\n`order_event_kind` (`21-database-schema.md`, table `order_events`) — no supersets,\nno omissions; contract test `enum_parity_order_event_kind` asserts set equality.\n"
        ),
    ] = None
    event_ts: AwareDatetime | None = None
    payload: dict[str, Any] | None = None


class Overrides(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    profile_id: UUID | None = None
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
        bool | None,
        Field(description="Keep the leg in the group for auditability but do not send it."),
    ] = False


class TradeGroupLegInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    exchange_account_id: UUID
    overrides: Annotated[
        Overrides | None,
        Field(
            description="Per-leg overrides layered on top of the account profile and request defaults."
        ),
    ] = None


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
    ) = "entry"
    reduce_only: bool | None = False
    atomicity: Literal["best_effort", "all_or_none"] | None = "best_effort"
    compensate: Annotated[
        Literal["none", "flatten_filled"] | None,
        Field(description="Applies when `all_or_none` fails after sending."),
    ] = "none"
    max_concurrent_legs: Annotated[int | None, Field(ge=1, le=20)] = 5
    defaults: Defaults | None = None
    algo: AlgoSpec | None = None
    legs: Annotated[list[TradeGroupLegInput], Field(max_length=25, min_length=1)]
    arm_token: str | None = None
    note: Annotated[str | None, Field(max_length=280)] = None
    rule_id: Annotated[
        UUID | None, Field(description="Set when the group originates from the rule engine.")
    ] = None


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
    message: Annotated[str | None, Field(description="Persisted as `rejection_message`.")] = None
    exchange_ret_code: int | None = None
    retryable: bool | None = None


class Totals(BaseModel):
    requested_legs: int | None = None
    submitted_legs: int | None = None
    rejected_legs: int | None = None
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
            description="Per-leg amendments; when present, the top-level fields are ignored for those legs."
        ),
    ] = None


class Result(BaseModel):
    exchange_account_id: UUID | None = None
    ok: bool | None = None
    affected: int | None = None
    error: LegError | None = None


class BulkAccountResult(BaseModel):
    results: list[Result] | None = None
    requested: int | None = None
    succeeded: int | None = None


class Result1(BaseModel):
    leg_id: UUID | None = None
    exchange_account_id: UUID | None = None
    ok: bool | None = None
    affected: int | None = None
    error: LegError | None = None


class BulkLegResult(BaseModel):
    trade_group_id: UUID | None = None
    results: list[Result1] | None = None
    requested: int | None = None
    succeeded: int | None = None


class KillSwitch(BaseModel):
    engaged: bool
    scope: Literal["global", "accounts"]
    exchange_account_ids: list[UUID] | None = None
    engaged_at: AwareDatetime | None = None
    engaged_by: UUID | None = None
    reason: str | None = None


class SetKillSwitchRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    engaged: bool
    scope: Literal["global", "accounts"]
    exchange_account_ids: list[UUID] | None = None
    cancel_open_orders: bool | None = True
    flatten_positions: bool | None = False
    disarm_rules: bool | None = True
    reason: Annotated[str, Field(max_length=280, min_length=3)]


class Actions(BaseModel):
    orders_cancelled: int | None = None
    positions_flattened: int | None = None
    rules_disarmed: int | None = None
    failures: list[dict[str, Any]] | None = None


class KillSwitchResult(BaseModel):
    state: KillSwitch | None = None
    actions: Actions | None = None


class Position(BaseModel):
    is_paper: Annotated[
        bool | None,
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
        bool | None,
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
            description="Arms the trailing stop only once price reaches this level.",
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
    arm_token: str | None = None


class ReversePositionRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    size_mode: Literal["same", "profile", "custom"] | None = "same"
    qty: Annotated[
        str | None,
        Field(
            description="Required when `size_mode=custom`.",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    order_type: Literal["market", "limit"] | None = "market"
    price: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    arm_token: str | None = None


class Execution(BaseModel):
    is_paper: Annotated[
        bool | None,
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
    is_maker: bool | None = None
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
            description="Arbitrary-precision decimal transported as a string (convention C6).",
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
    const: str | float | bool


class RuleMetricRef(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    metric: Annotated[str, Field(pattern="^[a-z][a-z0-9_]{1,48}$")]
    params: dict[str, Any] | None = None
    symbol: Symbol | None = None
    account_id: UUID | None = None
    timeframe: str | None = None


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
            description="Order-sending actions (`place_order`, `flatten_*`, `reverse_position`,\n`scale_in`, `scale_out`, `modify_*`, `cancel_*`, `reduce_leverage`,\n`arm_chase_limit`, `start_*`) require the rule to be `armed` and the author to\nhold `orders:write` on every bound account. `widen_stop` additionally requires\nan owner with an elevated session - it is the only action that can increase\nrisk, so it is gated separately from the rest.\n"
        ),
    ]
    params: Annotated[
        dict[str, Any], Field(description="Validated against a per-action JSON Schema.")
    ]
    on_error: Literal["abort_remaining", "continue", "retry_once"] | None = "abort_remaining"
    targets: Literal["scope_accounts", "originating_account", "all_accounts"] | None = (
        "scope_accounts"
    )
    dry_run_only: bool | None = False


class RuleLimits(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    once: bool | None = False
    once_per: Literal["position", "day", "group", "rule_lifetime"] | None = None
    cooldown_ms: Annotated[int | None, Field(ge=0)] = 1000
    max_fires_per_hour: Annotated[int | None, Field(ge=1)] = 60
    max_fires_per_day: Annotated[int | None, Field(ge=1)] = 500
    max_actions_per_fire: Annotated[int | None, Field(ge=1, le=10)] = 10
    max_notional_per_fire: Decimal | None = None
    max_daily_notional: Decimal | None = None
    require_confirmation: bool | None = False
    evaluation_timeout_ms: Annotated[int | None, Field(ge=10, le=5000)] = 250
    kill_switch_on_error_count: Annotated[int | None, Field(ge=1)] = 5


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
    interval_ms: Annotated[int | None, Field(description="Required for `on_timer`.", ge=100)] = None
    cron: Annotated[
        str | None, Field(description="Required for `on_schedule`; 5-field UTC cron.")
    ] = None
    metric: Annotated[str | None, Field(description="Required for `on_metric_change`.")] = None
    debounce_ms: Annotated[int | None, Field(ge=0)] = 0


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
    version: int | None = None
    bindings: RuleBindings | None = None
    last_run_at: AwareDatetime | None = None
    last_run_status: Literal["running", "ok", "error", "aborted", "throttled"] | None = None
    fire_count_24h: int | None = None
    created_by: UUID | None = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None


class LastSimulation(BaseModel):
    run_id: UUID | None = None
    ir_hash: str | None = None
    completed_at: AwareDatetime | None = None
    fires: int | None = None


class RuleVersion(BaseModel):
    id: UUID | None = None
    rule_id: UUID | None = None
    version: int | None = None
    ir_hash: str | None = None
    is_active: bool | None = None
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
        ]
        | None
    ) = None
    message: str | None = None
    severity: Literal["error", "warning"] | None = None
    class_: Annotated[
        Literal["syntax", "semantics", "safety", "performance"] | None, Field(alias="class")
    ] = None


class RuleValidationResult(BaseModel):
    valid: bool
    errors: list[RuleValidationIssue]
    warnings: list[RuleValidationIssue]
    referenced_variables: list[str] | None = None
    referenced_actions: list[str] | None = None
    estimated_evaluations_per_minute: int | None = None
    blocks_arming: Annotated[
        bool | None,
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
    speed: Annotated[float | None, Field(ge=0.0, le=100.0)] = 0
    starting_equity_usd: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None


class Action(BaseModel):
    ts: AwareDatetime | None = None
    action: str | None = None
    params: dict[str, Any] | None = None
    would_have_succeeded: bool | None = None
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
    evaluations: int | None = None
    fires: int | None = None
    suppressed_by_guard: int | None = None
    actions: list[Action] | None = None
    hypothetical_pnl_delta_usd: Decimal | None = None
    errors: list[str] | None = None
    duration_ms: int | None = None


class RuleRun(BaseModel):
    id: UUID | None = None
    rule_id: UUID | None = None
    rule_version_id: UUID | None = None
    kind: Literal["live", "simulation"] | None = None
    status: Literal["running", "ok", "error", "aborted", "throttled"] | None = None
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    evaluations: int | None = None
    fires: int | None = None
    errors: int | None = None
    error_message: str | None = None


class RuleEvent(BaseModel):
    id: int | None = None
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
    id: int | None = None
    alert_id: UUID | None = None
    channel: Literal["in_app", "email", "webhook", "push", "desktop"] | None = None
    status: Literal["queued", "sent", "failed", "suppressed", "acked"] | None = None
    severity: Literal["debug", "info", "warning", "error", "critical"] | None = None
    title: str | None = None
    message: str | None = None
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
    duration_seconds: int | None = None
    outcome: Literal["win", "loss", "breakeven", "open"] | None = None
    rating: Annotated[int | None, Field(ge=1, le=5)] = None
    tags: list[str] | None = None
    setup: str | None = None
    notes_count: int | None = None


class Mistake(RootModel[str]):
    root: Annotated[str, Field(max_length=120)]


class UpdateJournalTradeRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    rating: Annotated[int | None, Field(ge=1, le=5)] = None
    tags: list[Tag] | None = None
    setup: Annotated[str | None, Field(max_length=200)] = None
    mistakes: list[Mistake] | None = None
    checklist: list[dict[str, Any]] | None = None


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
    trades: int | None = None
    wins: int | None = None
    losses: int | None = None
    breakeven: int | None = None
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
    longest_win_streak: int | None = None
    longest_loss_streak: int | None = None


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
    trades: int | None = None
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
        bool | None,
        Field(
            description="At most one live default per user; `true` clears the previous default in the same transaction."
        ),
    ] = False
    icon_token: Annotated[
        Literal["workspace.default"] | None,
        Field(
            description="Design-system icon token for the workspace (a token name, never a URL or markup).\n**Open-ended for readers:** clients must tolerate values they do not know, so adding a token\nis an additive change (C-6.3). Writers must send a listed value; the server keeps the same\nallow-list. `workspace.default` is the only token until the design-system icon registry\n(CMP-019) publishes workspace icons.\n"
        ),
    ] = "workspace.default"
    sort_order: Annotated[
        int | None,
        Field(description="Client-defined tab order; ties break by `id`.", ge=0, le=32767),
    ] = 0


class Workspace(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    is_default: bool
    icon_token: Annotated[
        Literal["workspace.default"],
        Field(
            description="Design-system icon token for the workspace (a token name, never a URL or markup).\n**Open-ended for readers:** clients must tolerate values they do not know, so adding a token\nis an additive change (C-6.3). Writers must send a listed value; the server keeps the same\nallow-list. `workspace.default` is the only token until the design-system icon registry\n(CMP-019) publishes workspace icons.\n"
        ),
    ]
    sort_order: Annotated[int, Field(ge=0, le=32767)]
    layout_count: Annotated[int, Field(description="Live layouts.", ge=0, le=32)]
    created_at: AwareDatetime
    updated_at: Annotated[
        AwareDatetime,
        Field(
            description="Concurrency token (also the `ETag`) for the workspace metadata only; layout writes do not change it. Always exactly 6 fractional digits plus `Z` (`YYYY-MM-DDTHH:MM:SS.ffffffZ`) and strictly increasing on every write. Echo it exactly as received; never re-serialise it through a client date type."
        ),
    ]


class Size(RootModel[float]):
    root: Annotated[float, Field(gt=0.0, le=1.0)]


class LayoutGridLeaf(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: Literal["leaf"]
    slot: Annotated[
        int, Field(description="`slot_index` of a pane in the same layout.", ge=0, le=15)
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


class PaneSettingValue2(RootModel[int]):
    root: Annotated[
        int,
        Field(
            description="A flat setting value: a string, an integer or other finite number (each keeps its kind), a boolean, `null`, or an array of at most 32 such strings, numbers or booleans; objects are not allowed. Strings, also inside arrays, are at most 256 characters as sent and are then sanitised like `WorkspaceInput.name` (the name strip set and trimming), except that an empty result is kept; a lone surrogate is rule `invalid_unicode`. Numbers, also inside arrays, lie within ±1e15, so they read back with the same kind and value. A non-zero number must have |x| ≥ 1e-15 (`number_out_of_range`); zero is allowed. `-0.0` is stored as `0.0`.",
            ge=-1000000000000000,
            le=1000000000000000,
        ),
    ]


class PaneSettingValue3(RootModel[float]):
    root: Annotated[
        float,
        Field(
            description="A flat setting value: a string, an integer or other finite number (each keeps its kind), a boolean, `null`, or an array of at most 32 such strings, numbers or booleans; objects are not allowed. Strings, also inside arrays, are at most 256 characters as sent and are then sanitised like `WorkspaceInput.name` (the name strip set and trimming), except that an empty result is kept; a lone surrogate is rule `invalid_unicode`. Numbers, also inside arrays, lie within ±1e15, so they read back with the same kind and value. A non-zero number must have |x| ≥ 1e-15 (`number_out_of_range`); zero is allowed. `-0.0` is stored as `0.0`.",
            ge=-1000000000000000.0,
            le=1000000000000000.0,
        ),
    ]


class PaneSettingValue41(RootModel[str]):
    root: Annotated[str, Field(max_length=256)]


class PaneSettingValue42(RootModel[int]):
    root: Annotated[int, Field(ge=-1000000000000000, le=1000000000000000)]


class PaneSettingValue43(RootModel[float]):
    root: Annotated[float, Field(ge=-1000000000000000.0, le=1000000000000000.0)]


class PaneSettingValue4(
    RootModel[list[PaneSettingValue41 | PaneSettingValue42 | PaneSettingValue43 | bool]]
):
    root: Annotated[
        list[PaneSettingValue41 | PaneSettingValue42 | PaneSettingValue43 | bool],
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
            | bool
            | PaneSettingValue4
            | None,
        ]
        | None,
        Field(
            description="Kind-specific flat settings (for example DOM depth, tape filters, CVD anchor, visible range), at most 32 keys. Every key must match `^[a-z][a-z0-9_]{0,31}$` (`422` rule `invalid_setting_key`); the server enforces this because generators cannot express key patterns. Numbers keep their kind (`1` stays `1`, `1.0` stays `1.0`). Omitted means `{}`.",
            max_length=32,
        ),
    ] = None


class LayoutPaneInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    slot_index: Annotated[
        int,
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
        ],
        Field(
            description="Pane kind (`lp_kind`, `21-database-schema.md` §3.8.1). **Open-ended for readers:** clients\nmust tolerate values they do not know, so adding a kind is an additive change (C-6.3);\nwriters must send a listed value. Market panes (`chart`, `dom`, `tape`, `profile`, `cvd`,\n`oi`, `deep_stats`, `regime`) may bind a `symbol` and `interval_code`; account panes\n(`positions`, `journal`, `watchlist`, `alerts`) show many symbols and carry neither (rule\n`property_not_allowed_for_kind`). A heatmap lives in the `dom` pane and orders in the\n`positions` pane. A footprint is a `chart` pane; until chart templates exist (#2411) it is\nmarked by `pane_config.settings.footprint: true`, its options as further flat `footprint_*`\nsettings.\n"
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
            description="Indicator preset references; omitted means `[]`. A non-empty list is refused (`422` rule `indicator_preset_not_found`) until `indicator_presets` ships (E13-T03); then every id must name a preset the caller may use.",
            max_length=16,
        ),
    ] = None
    pane_config: PaneConfig | None = None
    scale_mode: Annotated[
        Literal["auto", "linked", "manual", "log"] | None,
        Field(description="Price-scale behaviour (`lp_scale`). **Open-ended for readers.**"),
    ] = "auto"


class LayoutPane(BaseModel):
    slot_index: Annotated[int, Field(ge=0, le=15)]
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
        ],
        Field(
            description="Pane kind (`lp_kind`, `21-database-schema.md` §3.8.1). **Open-ended for readers:** clients\nmust tolerate values they do not know, so adding a kind is an additive change (C-6.3);\nwriters must send a listed value. Market panes (`chart`, `dom`, `tape`, `profile`, `cvd`,\n`oi`, `deep_stats`, `regime`) may bind a `symbol` and `interval_code`; account panes\n(`positions`, `journal`, `watchlist`, `alerts`) show many symbols and carry neither (rule\n`property_not_allowed_for_kind`). A heatmap lives in the `dom` pane and orders in the\n`positions` pane. A footprint is a `chart` pane; until chart templates exist (#2411) it is\nmarked by `pane_config.settings.footprint: true`, its options as further flat `footprint_*`\nsettings.\n"
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
    price_grouping: int | None = None
    imbalance_ratio: float | None = None
    min_stack: int | None = None
    show_unfinished_auctions: bool | None = None


class Indicator(BaseModel):
    code: str | None = None
    params: dict[str, Any] | None = None
    pane: Literal["main", "sub1", "sub2", "sub3"] | None = None


class PriceScale(BaseModel):
    mode: Literal["linear", "logarithmic", "percent"] | None = None
    auto_fit: bool | None = None
    right_margin_bars: int | None = None


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


class ChartTemplateInput(BaseModel):
    name: Annotated[str, Field(max_length=80, min_length=1)]
    shared: bool | None = False
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


class Level(RootModel[float]):
    root: Annotated[float, Field(ge=-1000.0, le=1000.0)]


class DrawingGeometry(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    points: Annotated[list[DrawingPoint], Field(max_length=500, min_length=1)]
    extend_left: bool | None = None
    extend_right: bool | None = None
    levels: Annotated[
        list[Level] | None,
        Field(
            description="Fibonacci levels (fib tools only): unique finite numbers; a duplicate is rule `duplicate_level`.",
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


class DrawingStyle(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    colour: Annotated[str | None, Field(pattern="^#[0-9a-fA-F]{6}$")] = None
    fill_colour: Annotated[str | None, Field(pattern="^#[0-9a-fA-F]{6}$")] = None
    fill_opacity: Annotated[float | None, Field(ge=0.0, le=1.0)] = None
    width: Annotated[int | None, Field(ge=1, le=8)] = None
    dash: Literal["solid", "dashed", "dotted"] | None = None
    font_size: Annotated[int | None, Field(ge=8, le=48)] = None


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
    locked: bool | None = False
    visible: bool | None = True
    z_index: Annotated[int | None, Field(ge=-32768, le=32767)] = 0


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
    locked: bool
    visible: bool
    z_index: Annotated[int, Field(ge=-32768, le=32767)]
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


class IndicatorPresetInput(BaseModel):
    name: Annotated[str, Field(max_length=80, min_length=1)]
    indicator_code: Annotated[str, Field(max_length=40)]
    params: dict[str, Any]
    is_default: bool | None = False


class IndicatorPreset(IndicatorPresetInput):
    id: UUID | None = None
    owner_user_id: UUID | None = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None


class Appearance(BaseModel):
    theme: Literal["dark", "light", "system"] | None = None
    density: Literal["compact", "comfortable", "spacious"] | None = None
    font_scale: Annotated[float | None, Field(ge=0.75, le=2.0)] = None
    reduce_motion: bool | None = None
    high_contrast: bool | None = None


class Accessibility(BaseModel):
    reduced_motion: Literal["system", "on", "off"] | None = None
    increased_contrast: Literal["system", "on", "off"] | None = None
    disable_canvas_animation: bool | None = None
    always_show_tables: bool | None = None
    thick_focus_ring: bool | None = None
    announce_prices: Literal["off", "significant", "always"] | None = None
    verbosity: Literal["low", "normal", "high"] | None = None
    keyboard_only: bool | None = None


class Chart(BaseModel):
    default_bar_type: (
        Literal["time", "tick", "volume", "range", "delta", "renko", "pnf", "heikin_ashi"] | None
    ) = None
    default_param: str | None = None
    crosshair_sync: bool | None = None
    bar_close_countdown: bool | None = None
    price_scale_mode: Literal["linear", "logarithmic", "percent"] | None = None


class Orderflow(BaseModel):
    heatmap_bid_colour: str | None = None
    heatmap_ask_colour: str | None = None
    imbalance_ratio: float | None = None
    min_stack: int | None = None
    value_area_pct: float | None = None
    big_trade_threshold_mode: Literal["absolute", "relative", "zscore"] | None = None
    big_trade_k: float | None = None


class Trading(BaseModel):
    one_click_armed: bool | None = None
    arm_timeout_seconds: int | None = None
    confirm_market_orders: bool | None = None
    confirm_flatten: bool | None = None
    default_environment: Annotated[
        Literal["live", "demo", "testnet"] | None,
        Field(
            description="Structural environment selector (arch P9). Mirrors the Postgres type `exchange_env`."
        ),
    ] = None
    default_qty_presets: list[Decimal] | None = None


class Notifications(BaseModel):
    desktop_enabled: bool | None = None
    email_enabled: bool | None = None
    webhook_url: str | None = None
    quiet_hours: dict[str, Any] | None = None


class Data(BaseModel):
    default_depth: int | None = None
    stale_badge_after_ms: int | None = None
    max_history_bars: int | None = None


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
            examples=["order.buy_market", "position.flatten", "chart.toggle_footprint"],
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
    scope: Literal["global", "chart", "dom", "tape", "orders", "positions"]
    requires_arm: Annotated[
        bool | None, Field(description="Forced true for order-sending actions.")
    ] = True
    confirm: bool | None = False
    params: dict[str, Any] | None = None


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
    acknowledged_unsafe: bool


class HotkeyProfile(HotkeyProfileInput):
    id: UUID | None = None
    owner_user_id: UUID | None = None
    is_active: bool | None = None
    updated_at: AwareDatetime | None = None


class AuditEntry(BaseModel):
    id: int | None = None
    ts: AwareDatetime | None = None
    actor_user_id: UUID | None = None
    actor_username: str | None = None
    action: str | None = None
    subject_type: str | None = None
    subject_id: str | None = None
    outcome: Literal["success", "failure", "denied"] | None = None
    severity: Literal["debug", "info", "warning", "error", "critical"] | None = None
    ip: str | None = None
    user_agent: str | None = None
    request_id: str | None = None
    detail: dict[str, Any] | None = None
    entry_hash: str | None = None
    prev_hash: str | None = None


class Component(BaseModel):
    name: str | None = None
    state: Annotated[
        Literal["healthy", "degraded", "warning", "down", "not_deployed"] | None,
        Field(
            description="`not_deployed` = module not built yet; ranks as healthy for `overall`. Rank: down > warning > degraded > healthy."
        ),
    ] = None
    latency_ms: int | None = None
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
    version: str | None = None
    git_sha: str | None = None
    environment: str | None = None
    uptime_seconds: int | None = None
    server_time: AwareDatetime | None = None
    clock_offset_ms: Annotated[
        int | None,
        Field(description="null until exchange time sync (E08) lands; never a fabricated 0."),
    ] = None
    components: list[Component] | None = None
    alerts_active: int | None = None


class Override(BaseModel):
    user_id: UUID | None = None
    value: Any | None = None


class FeatureFlag(BaseModel):
    key: str | None = None
    kind: Literal["boolean", "percentage", "variant"] | None = None
    description: str | None = None
    value: Annotated[Any | None, Field(description="Resolved value for the caller.")] = None
    default_value: Annotated[Any | None, Field(description="Deployment default.")] = None
    overrides: list[Override] | None = None
    updated_by: UUID | None = None
    updated_at: AwareDatetime | None = None


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
            description="Boolean, number (percentage) or string (variant), matching the flag kind."
        ),
    ]
    overrides: list[Override1] | None = None
    reason: Annotated[str | None, Field(max_length=280)] = None
    evidence_url: Annotated[
        AnyUrl | None, Field(description="Required for gated flags such as `trading.live_enabled`.")
    ] = None


class Backup(BaseModel):
    id: UUID | None = None
    kind: (
        Literal["pg_basebackup", "pg_dump", "questdb_snapshot", "parquet_sync", "config_bundle"]
        | None
    ) = None
    status: Literal["running", "ok", "failed", "verified", "restored"] | None = None
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    size_bytes: int | None = None
    location: str | None = None
    checksum_sha256: str | None = None
    encrypted: bool | None = None
    retention_until: AwareDatetime | None = None
    verified_at: AwareDatetime | None = None
    error: str | None = None


class Job(BaseModel):
    id: UUID | None = None
    kind: (
        Literal[
            "instrument_refresh",
            "audit_export",
            "backup",
            "backup_verify",
            "rule_simulation",
            "retention_sweep",
            "reconciliation",
            "archive_import",
        ]
        | None
    ) = None
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"] | None = None
    progress_pct: Annotated[float | None, Field(ge=0.0, le=100.0)] = None
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


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
    onboarding_complete: bool | None = None


class Account2(BaseModel):
    exchange_account_id: UUID | None = None
    orders_per_minute_limit: int | None = None
    orders_per_minute_used: int | None = None
    rate_budget_pct_used: Annotated[float | None, Field(ge=0.0, le=100.0)] = None
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
    open_positions: int | None = None
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
    complete: bool
    dismissed: bool
    items: list[Item]


class Notification(BaseModel):
    id: UUID
    kind: Literal["alert", "rule", "order", "risk", "system"]
    severity: Literal["debug", "info", "warning", "error", "critical"]
    title: str
    body: str | None = None
    created_at: AwareDatetime
    read_at: AwareDatetime | None = None
    symbol: str | None = None
    exchange_account_id: UUID | None = None
    source_id: Annotated[
        UUID | None,
        Field(
            description="Id of the originating alert delivery, rule event, order or system event."
        ),
    ] = None
    route: Annotated[
        str | None, Field(description="Deep link to the screen that explains this notification.")
    ] = None


class WatchlistInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: Annotated[str, Field(max_length=80, min_length=1)]
    symbols: Annotated[list[Symbol], Field(max_length=200)]
    columns: Annotated[
        list[str] | None, Field(description="Column ids shown for this watchlist, in order.")
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
    recording: bool | None = None
    coverage: Annotated[
        Literal["recorded", "live_only"],
        Field(
            description="`live_only` means no local history exists for this symbol, so criteria that need recorded history were skipped for this row rather than evaluated as zero.\n"
        ),
    ]


class IndicatorDescriptor(BaseModel):
    id: str
    name: str
    category: Literal["trend", "momentum", "volatility", "volume", "orderflow"] | None = None
    pane: Literal["price", "sub", "both"]
    compute: Annotated[
        Literal["client_worker", "server"],
        Field(
            description="`server` indicators are read from `orderflow_metrics` and require recorded history; `client_worker` indicators are computed from bars already in the client.\n"
        ),
    ]
    estimated: Annotated[
        bool | None, Field(description="True for heuristic signals that infer unobservable intent.")
    ] = False
    params_schema: Annotated[
        dict[str, Any],
        Field(
            description="JSON Schema for this indicator's parameters; the settings form renders from it."
        ),
    ]
    defaults: dict[str, Any] | None = None


class ExchangeCall(BaseModel):
    at: AwareDatetime | None = None
    endpoint: str | None = None
    http_status: int | None = None
    ret_code: int | None = None
    ret_msg: str | None = None
    latency_ms: int | None = None
    request_redacted: dict[str, Any] | None = None
    response_redacted: dict[str, Any] | None = None


class Reconciliation(BaseModel):
    last_checked_at: AwareDatetime | None = None
    verdict: Literal["in_sync", "drifted", "repaired", "unresolvable"] | None = None
    detail: str | None = None


class OrderDiagnostics(BaseModel):
    order: Order
    events: list[OrderEvent]
    exchange_calls: Annotated[
        list[ExchangeCall] | None,
        Field(
            description="Request/response pairs with credentials, signatures and headers redacted."
        ),
    ] = None
    reconciliation: Reconciliation | None = None


class Rejection(BaseModel):
    code: (
        Literal[
            "cap_breached",
            "symbol_not_allowed",
            "insufficient_margin",
            "rate_budget_exhausted",
            "account_locked",
            "key_invalid",
            "leverage_unavailable",
            "kill_switch_engaged",
        ]
        | None
    ) = None
    message: str | None = None


class Leg1(BaseModel):
    exchange_account_id: UUID
    account_label: str | None = None
    account_profile_id: UUID | None = None
    would_submit: bool
    resolved: ResolvedLegParams | None = None
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
    accounts_targeted: int | None = None
    accounts_submittable: int | None = None
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
    open_positions: int | None = None
    gross_notional_usd: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    positions_without_native_stop: Annotated[
        int | None,
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
    cap_utilisation_pct: Annotated[float | None, Field(ge=0.0)] = None
    open_positions: int | None = None
    frozen: bool | None = None
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
    enabled: bool | None = True
    min_reloads: Annotated[int | None, Field(ge=2, le=50)] = 3
    price_tolerance_ticks: Annotated[int | None, Field(ge=0, le=10)] = 0
    window_ms: Annotated[int | None, Field(ge=200, le=60000)] = 5000


class StopRun(BaseModel):
    enabled: bool | None = True
    lookback_bars: Annotated[int | None, Field(ge=2, le=500)] = 20
    penetration_ticks: Annotated[int | None, Field(ge=1, le=100)] = 2
    reversal_pct: Annotated[float | None, Field(ge=0.0, le=100.0)] = 60


class Absorption(BaseModel):
    enabled: bool | None = True
    min_volume_multiple: Annotated[float | None, Field(ge=1.0, le=50.0)] = 3
    max_price_move_ticks: Annotated[int | None, Field(ge=0, le=50)] = 1


class Exhaustion(BaseModel):
    enabled: bool | None = True
    min_delta_divergence: Annotated[float | None, Field(ge=0.0)] = 0.5


class BigTrade(BaseModel):
    mode: Literal["absolute_usd", "percentile"] | None = "percentile"
    absolute_usd: Annotated[
        str | None,
        Field(
            description="Arbitrary-precision decimal transported as a string (convention C6).",
            examples=["63120.50", "-0.0004", "0"],
            pattern="^-?[0-9]+(\\.[0-9]+)?$",
        ),
    ] = None
    percentile: Annotated[float | None, Field(ge=50.0, le=99.99)] = 99


class DetectorConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    iceberg: Iceberg1 | None = None
    stop_run: StopRun | None = None
    absorption: Absorption | None = None
    exhaustion: Exhaustion | None = None
    big_trade: BigTrade | None = None


class DetectorMethodology(BaseModel):
    detector: Literal["iceberg", "stop_run", "absorption", "exhaustion", "big_trade", "regime"]
    display_name: str | None = None
    inputs: list[str]
    assumption: Annotated[str, Field(description="The inference being made, stated plainly.")]
    false_positive_modes: list[str]
    confidence_basis: str | None = None


class Signal(BaseModel):
    name: str | None = None
    value: float | None = None
    weight: float | None = None
    contribution: float | None = None
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
    confidence: Annotated[float | None, Field(ge=0.0, le=1.0)] = None
    as_of: AwareDatetime | None = None
    signals: list[Signal]


class Signal1(BaseModel):
    id: str
    display_name: str | None = None
    type: Literal["number", "boolean", "price", "quantity", "duration", "enum"]
    unit: str | None = None
    enum_values: list[str] | None = None
    params_schema: dict[str, Any] | None = None
    requires_recording: bool | None = False
    estimated: bool | None = False
    description: str | None = None
    valid_range: str | None = None
    warmup_bars: int | None = None
    deterministic: bool | None = None
    confidence: Literal["exact", "estimated"] | None = None
    dependencies: list[str] | None = None
    when_unavailable: str | None = None
    available: bool | None = True
    unavailable_reason: str | None = None
    missing_dependency: dict[str, Any] | None = None
    recorder_action: dict[str, Any] | None = None


class Operator(BaseModel):
    id: str | None = None
    arity: Annotated[int | None, Field(ge=1, le=3)] = None
    operand_types: list[str] | None = None
    result_type: str | None = None


class Action1(BaseModel):
    id: str
    display_name: str | None = None
    params_schema: dict[str, Any] | None = None
    required_permissions: list[str]
    requires_step_up: bool | None = False
    idempotent: bool | None = None
    guarded: bool | None = None
    targets: dict[str, str] | None = None
    available: bool | None = True
    simulate_only: bool | None = False
    restriction: str | None = None
    notes: str | None = None
    loosens_risk: Annotated[
        bool | None,
        Field(
            description="Actions that can widen or remove a stop are flagged so the editors can warn and the engine can gate them behind the owner-only permission.\n"
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
    vocabulary_version: int | None = None
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
    version: str
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
    total: int | None = None
    active: int | None = None
    without_mfa: int | None = None


class Accounts(AdminSliceStatus):
    total: int | None = None
    enabled: int | None = None
    keys_expiring_30d: int | None = None
    keys_invalid: int | None = None


class Recorder(AdminSliceStatus):
    symbols_recording: int | None = None
    symbols_degraded: int | None = None
    lag_seconds_p99: float | None = None


class Storage(AdminSliceStatus):
    used_bytes: int | None = None
    free_bytes: int | None = None
    days_until_full: float | None = None


class Trading1(AdminSliceStatus):
    live_enabled: bool | None = None
    kill_switch_engaged: bool | None = None
    open_positions: int | None = None


class Incidents(AdminSliceStatus):
    open: int | None = None


class AdminOverview(BaseModel):
    generated_at: AwareDatetime | None = None
    users: Users | None = None
    accounts: Accounts | None = None
    recorder: Recorder | None = None
    storage: Annotated[
        Storage | None,
        Field(
            description="`days_until_full` is `null` unless growth is measured; the estimated fallback exists only in `CapacityReport.storage`."
        ),
    ] = None
    trading: Trading1 | None = None
    incidents_open: int | None = None
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
    used_bytes: int | None = None
    daily_growth_bytes: int | None = None
    pinned: bool | None = None
    retention_days: int | None = None


class Storage1(AdminSliceStatus):
    used_bytes: int | None = None
    free_bytes: int | None = None
    daily_growth_bytes: int | None = None
    days_until_full: float | None = None
    per_symbol: list[PerSymbolItem] | None = None
    projection_basis: Annotated[
        Literal["measured", "estimated", "nothing_recorded"] | None,
        Field(
            description="Source of `daily_growth_bytes`. `measured`: the recorder's DiskBudget fit. `estimated`: no measurement yet, so 0.75 GB/day per recorded symbol (7.5e8 bytes, upper bound of the 0.5-0.75 band at 200-depth); `estimated` is `true` (convention C10). `nothing_recorded`: no symbol recorded, so growth is `0` by fact and `days_until_full` is `null`. **Open-ended for readers:** clients must tolerate values they do not know, so adding a basis is an additive change (C-6.3).\n"
        ),
    ] = None
    estimated: Annotated[
        bool | None,
        Field(
            description="`true` iff `projection_basis` is `estimated`; otherwise `false` or omitted."
        ),
    ] = None


class Ingestion(AdminSliceStatus):
    messages_per_sec: float | None = None
    queue_depth: int | None = None
    dropped_last_hour: int | None = None


class RateBudgetItem(BaseModel):
    exchange_account_id: UUID | None = None
    label: str | None = None
    limit_per_minute: int | None = None
    peak_used_per_minute: int | None = None
    utilisation_pct: float | None = None


class SubaccountCapacity(AdminSliceStatus):
    tier: Annotated[
        Literal["regular", "business_kyc"] | None,
        Field(
            description="**Open-ended for readers:** clients must tolerate values they do not know, so adding a tier is an additive change (C-6.3).\n"
        ),
    ] = None
    cap: Annotated[
        int | None,
        Field(description="5 for `regular`, 20 for `business_kyc`, `null` while unrecorded."),
    ] = None
    used: Annotated[
        int | None,
        Field(
            description="Most non-deleted live sub-accounts (`exchange_accounts.kind = sub`, `env = live`) under any one main account: the cap binds live exchange UIDs, per main (C-2.11).\n",
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
    title: str | None = None
    detail: str | None = None
    occurrences: int | None = None
    first_seen_at: AwareDatetime
    last_seen_at: AwareDatetime
    acknowledged_by: UUID | None = None
    resolved_at: AwareDatetime | None = None
    runbook_ref: str | None = None


class Key(BaseModel):
    exchange_account_id: UUID | None = None
    key_id_prefix: str | None = None
    status: Literal["pending", "active", "rotating", "revoked", "expired", "invalid"] | None = None
    age_days: int | None = None
    expires_at: AwareDatetime | None = None
    withdrawal_permission_present: Annotated[
        bool | None, Field(description="MUST be false; true raises a critical finding immediately.")
    ] = None
    ip_whitelist_matches_expected: bool | None = None
    last_verified_at: AwareDatetime | None = None


class Auth(BaseModel):
    users_without_mfa: int | None = None
    failed_logins_24h: int | None = None
    denied_requests_24h: int | None = None
    active_elevated_sessions: int | None = None


class Audit(BaseModel):
    last_chain_verification_at: AwareDatetime | None = None
    chain_intact: bool | None = None
    entries_total: int | None = None


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


class AuthenticatedResponse(BaseModel):
    status: Literal["authenticated"]
    tokens: TokenBundle
    user: User


class LoginResponse(RootModel[AuthenticatedResponse | MfaChallengeResponse]):
    root: Annotated[AuthenticatedResponse | MfaChallengeResponse, Field(discriminator="status")]


class SessionInfo(BaseModel):
    user: User
    permissions: list[str]
    account_scope: list[UUID]
    allowed_environments: list[Literal["live", "demo", "testnet"]] | None = None
    kill_switch: KillSwitch | None = None
    server_time: AwareDatetime
    step_up_expires_at: Annotated[
        AwareDatetime | None,
        Field(
            description="Latest live step-up grace-window expiry on this session (E09-S04); null if none."
        ),
    ] = None
    clock_offset_ms: Annotated[
        int | None,
        Field(
            description="Backend clock minus Bybit server time; |offset| > 1000 ms is an incident."
        ),
    ] = None
    api_version: str | None = None
    feature_flags: Annotated[
        dict[str, Any] | None, Field(description="Flags resolved for this user.")
    ] = None


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
    mfa_required: bool | None = True
    account_access: list[AccountAccessGrantInput] | None = None


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
    balance_stale: bool | None = None
    balance_stale_since: Annotated[
        AwareDatetime | None,
        Field(
            description="Last refresh plus the 10 s threshold while `balance_stale` is true, else `null`."
        ),
    ] = None
    health: Annotated[
        AccountHealth | None, Field(description="`null` until the account is monitored.")
    ] = None
    enabled: bool | None = True
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None


class OrderWithEvents(Order):
    events: list[OrderEvent] | None = None
    executions: list[Execution] | None = None


class TradeGroupLeg(BaseModel):
    id: UUID | None = None
    trade_group_id: UUID | None = None
    exchange_account_id: UUID | None = None
    account_profile_id: Annotated[
        UUID | None,
        Field(
            description="The profile that produced `resolved`. Null when the ticket overrode the profile entirely."
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
        int | None,
        Field(
            description="Deterministic submission order within the group, so a partial fan-out is reproducible."
        ),
    ] = None
    resolved: ResolvedLegParams | None = None
    orders: list[UUID] | None = None
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
        bool | None,
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
        bool | None,
        Field(
            description="True when the paper matcher produced this record rather than the exchange. Orthogonal to `environment` (24-internal-schemas.md section 1.2)."
        ),
    ] = False
    id: UUID
    client_group_ref: str | None = None
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
        int | None, Field(description="Index of the visible tab in `children`.", ge=0, le=15)
    ] = 0


class Watchlist(WatchlistInput):
    id: UUID | None = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None


class CapacityReport(BaseModel):
    generated_at: AwareDatetime | None = None
    storage: Storage1 | None = None
    ingestion: Ingestion | None = None
    rate_budget: list[RateBudgetItem] | None = None
    rate_budget_status: AdminSliceStatus | None = None
    subaccounts: SubaccountCapacity | None = None


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
        float | None, Field(description="Equality tolerance for float comparisons.")
    ] = None


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
    n: Annotated[int | None, Field(description="Required for `n_of`.", ge=1)] = None


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
    window_ms: Annotated[int, Field(ge=100, le=86400000)]
    min_count: Annotated[int | None, Field(ge=1)] = 1


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
    limits: RuleLimits | None = None
    variables: Annotated[
        dict[str, RuleMetricRef | RuleOperand1 | RuleArithmeticNode] | None,
        Field(description="Named intermediate expressions, evaluated before `conditions`."),
    ] = None


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


class RuleInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: Annotated[str, Field(max_length=120, min_length=1)]
    description: Annotated[str | None, Field(max_length=1000)] = None
    scope: Literal["global", "account", "symbol", "position", "trade_group"]
    editor: Literal["form", "graph"] | None = "form"
    tags: list[Tag] | None = None
    bindings: RuleBindings | None = None
    ir: RuleIr
    graph_layout: Annotated[
        dict[str, Any] | None,
        Field(
            description="Node/edge coordinates for the node-graph editor. Ignored by the engine."
        ),
    ] = None
    note: Annotated[str | None, Field(max_length=280)] = None


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
    trigger_mode: Literal["once", "every_time", "once_per_bar"] | None = "once"
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
    expires_at: AwareDatetime | None = None
    webhook_url: AnyUrl | None = None
    enabled: bool | None = True


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
        Literal["1x1", "2x1", "1x2", "2x2", "1+3", "3x3", "custom"] | None,
        Field(
            description="Named grid (`lay_preset`, `21-database-schema.md` §3.8.1) or `custom`. A named preset stores\nonly its name and fixed cell proportions: `grid_spec` is `null`, and a pane's `slot_index`\nis its cell in row-major reading order (a slot beyond the preset's cells is placed by the\nclient, e.g. floating). Any other arrangement, including a named grid whose divider was\ndragged, is saved as `custom` with its tree in `grid_spec`. **Open-ended for readers.**\n"
        ),
    ] = "1x1"
    grid_spec: Annotated[
        LayoutGridSpec | None,
        Field(description="Required when `grid_preset` is `custom`, otherwise `null` or omitted."),
    ] = None
    crosshair_sync: Annotated[
        bool | None,
        Field(description="Layout default for crosshair sync between panes of one sync group."),
    ] = True
    level_sync: Annotated[
        bool | None, Field(description="Layout default for price-level sync.")
    ] = False
    symbol_sync: Annotated[bool | None, Field(description="Layout default for symbol sync.")] = (
        False
    )
    hotkey_slot: Annotated[
        int | None,
        Field(
            description="`Ctrl+1..9` binding; unique among the workspace's live layouts (`409 conflict`, rule `hotkey_slot_taken`).",
            ge=1,
            le=9,
        ),
    ] = None
    is_default: Annotated[
        bool | None,
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
    crosshair_sync: bool
    level_sync: bool
    symbol_sync: bool
    hotkey_slot: Annotated[int | None, Field(ge=1, le=9)]
    is_default: bool
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
        bool,
        Field(
            description="Always `true`: the catalogue is static. User-saved presets are layouts with a `hotkey_slot`."
        ),
    ]
    pane_count: Annotated[int, Field(ge=0, le=16)]
    layout: LayoutInput


class WorkspaceBundle(BaseModel):
    schema_version: str
    exported_at: AwareDatetime | None = None
    workspace: WorkspaceInput
    layouts: list[LayoutInput]
    chart_templates: list[ChartTemplateInput] | None = None
    drawings: list[DrawingInput] | None = None
    indicator_presets: list[IndicatorPresetInput] | None = None


class Alert(AlertInput):
    id: UUID | None = None
    owner_user_id: UUID | None = None
    fire_count: int | None = None
    last_fired_at: AwareDatetime | None = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None


RuleArithmeticNode.model_rebuild()
RuleBooleanNode.model_rebuild()
RuleTemporalNode.model_rebuild()
WorkspaceDetail.model_rebuild()
LayoutGridSpec.model_rebuild()
LayoutGridSplit.model_rebuild()
