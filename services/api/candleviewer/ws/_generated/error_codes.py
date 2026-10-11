"""GENERATED FILE - DO NOT EDIT BY HAND.

Generator: tools/errorcodes/generate.py (E17-T05).
Source: docs/plan/22-api-openapi.yaml (x-error-codes, x-error-codes-ws). Edit the YAML and run `make gen`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final, NamedTuple


class ErrorCode(StrEnum):
    VALIDATION_FAILED = "validation_failed"
    UNSUPPORTED_CATEGORY = "unsupported_category"
    TICK_SIZE_VIOLATION = "tick_size_violation"
    LOT_SIZE_VIOLATION = "lot_size_violation"
    INVALID_CURSOR = "invalid_cursor"
    INVALID_TIME_RANGE = "invalid_time_range"
    UNAUTHENTICATED = "unauthenticated"
    MFA_REQUIRED = "mfa_required"
    MFA_INVALID = "mfa_invalid"
    REFRESH_TOKEN_INVALID = "refresh_token_invalid"
    STEP_UP_REQUIRED = "step_up_required"
    SESSION_READ_ONLY = "session_read_only"
    POSITIONS_UNKNOWN = "positions_unknown"
    FORBIDDEN = "forbidden"
    CSRF_TOKEN_INVALID = "csrf_token_invalid"
    ACCOUNT_SCOPE_DENIED = "account_scope_denied"
    TRADING_DISABLED = "trading_disabled"
    RISK_LIMIT_BREACHED = "risk_limit_breached"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    IDEMPOTENCY_KEY_REUSE = "idempotency_key_reuse"
    IDEMPOTENCY_IN_FLIGHT = "idempotency_in_flight"
    VERSION_CONFLICT = "version_conflict"
    GONE = "gone"
    ORDER_NOT_AMENDABLE = "order_not_amendable"
    RULE_IR_INVALID = "rule_ir_invalid"
    INSUFFICIENT_BALANCE = "insufficient_balance"
    NO_DATA_RECORDED = "no_data_recorded"
    BAR_WINDOW_TOO_LARGE = "bar_window_too_large"
    RESPONSE_TOO_LARGE = "response_too_large"
    RATE_LIMITED = "rate_limited"
    EXCHANGE_RATE_LIMITED = "exchange_rate_limited"
    INTERNAL_ERROR = "internal_error"
    EXCHANGE_ERROR = "exchange_error"
    EXCHANGE_UNAVAILABLE = "exchange_unavailable"
    STORE_UNAVAILABLE = "store_unavailable"
    DEGRADED_DATA = "degraded_data"
    TIMEOUT = "timeout"
    PROTOCOL_VIOLATION = "protocol_violation"
    FRAME_MALFORMED = "frame_malformed"
    UNSUPPORTED_PROTOCOL = "unsupported_protocol"
    NOT_AUTHENTICATED = "not_authenticated"
    AUTH_FAILED = "auth_failed"
    AUTH_TIMEOUT = "auth_timeout"
    TOKEN_EXPIRED = "token_expired"
    UNKNOWN_TOPIC = "unknown_topic"
    INVALID_TOPIC_FORMAT = "invalid_topic_format"
    UNSUPPORTED_SYMBOL = "unsupported_symbol"
    INVALID_OPTIONS = "invalid_options"
    ENCODING_UNSUPPORTED = "encoding_unsupported"
    SUBSCRIPTION_LIMIT = "subscription_limit"
    TOO_MANY_TOPICS = "too_many_topics"
    DUPLICATE_SUBSCRIPTION = "duplicate_subscription"
    NOT_SUBSCRIBED = "not_subscribed"
    RESYNC_RATE_LIMITED = "resync_rate_limited"
    CLIENT_RATE_LIMITED = "client_rate_limited"
    SLOW_CONSUMER = "slow_consumer"
    REPLAY_SESSION_NOT_FOUND = "replay_session_not_found"
    REPLAY_SESSION_ENDED = "replay_session_ended"
    USER_DISABLED = "user_disabled"


class ErrorMeta(NamedTuple):
    surfaces: tuple[str, ...]
    scope: str | None
    retryable: bool
    rest_analogue: str | None
    close_code: int | None


ERROR_META: Final[dict[ErrorCode, ErrorMeta]] = {
    ErrorCode.VALIDATION_FAILED: ErrorMeta(("rest",), None, False, None, None),
    ErrorCode.UNSUPPORTED_CATEGORY: ErrorMeta(("rest",), None, False, None, None),
    ErrorCode.TICK_SIZE_VIOLATION: ErrorMeta(("rest",), None, False, None, None),
    ErrorCode.LOT_SIZE_VIOLATION: ErrorMeta(("rest",), None, False, None, None),
    ErrorCode.INVALID_CURSOR: ErrorMeta(("rest",), None, False, None, None),
    ErrorCode.INVALID_TIME_RANGE: ErrorMeta(("rest",), None, False, None, None),
    ErrorCode.UNAUTHENTICATED: ErrorMeta(("rest",), None, False, None, None),
    ErrorCode.MFA_REQUIRED: ErrorMeta(("rest",), None, False, None, None),
    ErrorCode.MFA_INVALID: ErrorMeta(("rest",), None, False, None, None),
    ErrorCode.REFRESH_TOKEN_INVALID: ErrorMeta(("rest",), None, False, None, None),
    ErrorCode.STEP_UP_REQUIRED: ErrorMeta(("rest",), None, False, None, None),
    ErrorCode.SESSION_READ_ONLY: ErrorMeta(("rest",), None, False, None, None),
    ErrorCode.POSITIONS_UNKNOWN: ErrorMeta(("rest",), None, False, None, None),
    ErrorCode.FORBIDDEN: ErrorMeta(("rest", "ws",), "any", False, None, None),
    ErrorCode.CSRF_TOKEN_INVALID: ErrorMeta(("rest",), None, False, None, None),
    ErrorCode.ACCOUNT_SCOPE_DENIED: ErrorMeta(("rest", "ws",), "any", False, None, None),
    ErrorCode.TRADING_DISABLED: ErrorMeta(("rest",), None, False, None, None),
    ErrorCode.RISK_LIMIT_BREACHED: ErrorMeta(("rest",), None, False, None, None),
    ErrorCode.NOT_FOUND: ErrorMeta(("rest",), None, False, None, None),
    ErrorCode.CONFLICT: ErrorMeta(("rest",), None, False, None, None),
    ErrorCode.IDEMPOTENCY_KEY_REUSE: ErrorMeta(("rest",), None, False, None, None),
    ErrorCode.IDEMPOTENCY_IN_FLIGHT: ErrorMeta(("rest",), None, True, None, None),
    ErrorCode.VERSION_CONFLICT: ErrorMeta(("rest",), None, False, None, None),
    ErrorCode.GONE: ErrorMeta(("rest",), None, False, None, None),
    ErrorCode.ORDER_NOT_AMENDABLE: ErrorMeta(("rest",), None, False, None, None),
    ErrorCode.RULE_IR_INVALID: ErrorMeta(("rest",), None, False, None, None),
    ErrorCode.INSUFFICIENT_BALANCE: ErrorMeta(("rest",), None, False, None, None),
    ErrorCode.NO_DATA_RECORDED: ErrorMeta(("rest", "ws",), "any", False, None, None),
    ErrorCode.BAR_WINDOW_TOO_LARGE: ErrorMeta(("rest",), None, False, None, None),
    ErrorCode.RESPONSE_TOO_LARGE: ErrorMeta(("rest",), None, False, None, None),
    ErrorCode.RATE_LIMITED: ErrorMeta(("rest",), None, True, None, None),
    ErrorCode.EXCHANGE_RATE_LIMITED: ErrorMeta(("rest",), None, True, None, None),
    ErrorCode.INTERNAL_ERROR: ErrorMeta(("rest", "ws",), "any", True, None, None),
    ErrorCode.EXCHANGE_ERROR: ErrorMeta(("rest",), None, True, None, None),
    ErrorCode.EXCHANGE_UNAVAILABLE: ErrorMeta(("rest", "ws",), "any", True, None, None),
    ErrorCode.STORE_UNAVAILABLE: ErrorMeta(("rest",), None, True, None, None),
    ErrorCode.DEGRADED_DATA: ErrorMeta(("rest", "ws",), "any", True, None, None),
    ErrorCode.TIMEOUT: ErrorMeta(("rest",), None, True, None, None),
    ErrorCode.PROTOCOL_VIOLATION: ErrorMeta(("ws",), "connection", False, None, 1002),
    ErrorCode.FRAME_MALFORMED: ErrorMeta(("ws",), "connection", False, None, 1002),
    ErrorCode.UNSUPPORTED_PROTOCOL: ErrorMeta(("ws",), "connection", False, None, 1002),
    ErrorCode.NOT_AUTHENTICATED: ErrorMeta(("ws",), "connection", False, "unauthenticated", 4401),
    ErrorCode.AUTH_FAILED: ErrorMeta(("ws",), "connection", False, "unauthenticated", 4401),
    ErrorCode.AUTH_TIMEOUT: ErrorMeta(("ws",), "connection", False, None, 4401),
    ErrorCode.TOKEN_EXPIRED: ErrorMeta(("ws",), "connection", True, "unauthenticated", 4401),
    ErrorCode.UNKNOWN_TOPIC: ErrorMeta(("ws",), "topic", False, "not_found", None),
    ErrorCode.INVALID_TOPIC_FORMAT: ErrorMeta(("ws",), "topic", False, "validation_failed", None),
    ErrorCode.UNSUPPORTED_SYMBOL: ErrorMeta(("ws",), "topic", False, "unsupported_category", None),
    ErrorCode.INVALID_OPTIONS: ErrorMeta(("ws",), "topic", False, "validation_failed", None),
    ErrorCode.ENCODING_UNSUPPORTED: ErrorMeta(("ws",), "topic", False, None, None),
    ErrorCode.SUBSCRIPTION_LIMIT: ErrorMeta(("ws",), "topic", True, "rate_limited", None),
    ErrorCode.TOO_MANY_TOPICS: ErrorMeta(("ws",), "request", True, "rate_limited", None),
    ErrorCode.DUPLICATE_SUBSCRIPTION: ErrorMeta(("ws",), "topic", False, "conflict", None),
    ErrorCode.NOT_SUBSCRIBED: ErrorMeta(("ws",), "topic", False, "not_found", None),
    ErrorCode.RESYNC_RATE_LIMITED: ErrorMeta(("ws",), "topic", True, "rate_limited", None),
    ErrorCode.CLIENT_RATE_LIMITED: ErrorMeta(("ws",), "connection", True, "rate_limited", 4429),
    ErrorCode.SLOW_CONSUMER: ErrorMeta(("ws",), "connection", True, None, 4429),
    ErrorCode.REPLAY_SESSION_NOT_FOUND: ErrorMeta(("ws",), "topic", False, "not_found", None),
    ErrorCode.REPLAY_SESSION_ENDED: ErrorMeta(("ws",), "topic", False, "gone", None),
    ErrorCode.USER_DISABLED: ErrorMeta(("ws",), "connection", False, "forbidden", 4403),
}

#: Codes legal on the WebSocket (23-ws-protocol.md 10.2): WS-only plus dual-surface.
WS_ERROR_CODES: Final[frozenset[ErrorCode]] = frozenset(
    code for code, meta in ERROR_META.items() if "ws" in meta.surfaces
)
