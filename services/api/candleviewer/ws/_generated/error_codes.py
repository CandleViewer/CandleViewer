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
    PAYLOAD_TOO_LARGE = "payload_too_large"
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
    title: str


ERROR_META: Final[dict[ErrorCode, ErrorMeta]] = {
    ErrorCode.VALIDATION_FAILED: ErrorMeta(("rest",), None, False, None, None, "Request body or parameters failed schema validation"),
    ErrorCode.UNSUPPORTED_CATEGORY: ErrorMeta(("rest",), None, False, None, None, "Only Bybit USDT linear perpetuals are supported in v1"),
    ErrorCode.TICK_SIZE_VIOLATION: ErrorMeta(("rest",), None, False, None, None, "Price is not a multiple of the instrument tick size"),
    ErrorCode.LOT_SIZE_VIOLATION: ErrorMeta(("rest",), None, False, None, None, "Quantity violates the instrument qty step / min / max"),
    ErrorCode.INVALID_CURSOR: ErrorMeta(("rest",), None, False, None, None, "Pagination cursor is malformed or expired"),
    ErrorCode.INVALID_TIME_RANGE: ErrorMeta(("rest",), None, False, None, None, "from/to range is inverted or exceeds the allowed window"),
    ErrorCode.UNAUTHENTICATED: ErrorMeta(("rest",), None, False, None, None, "Missing, malformed or expired access token"),
    ErrorCode.MFA_REQUIRED: ErrorMeta(("rest",), None, False, None, None, "Multi-factor authentication challenge must be completed"),
    ErrorCode.MFA_INVALID: ErrorMeta(("rest",), None, False, None, None, "MFA code rejected"),
    ErrorCode.REFRESH_TOKEN_INVALID: ErrorMeta(("rest",), None, False, None, None, "Refresh token unknown, rotated away, or revoked (possible reuse attack)"),
    ErrorCode.STEP_UP_REQUIRED: ErrorMeta(("rest",), None, False, None, None, "A dangerous action needs a live step-up elevation for its action class"),
    ErrorCode.SESSION_READ_ONLY: ErrorMeta(("rest",), None, False, None, None, "Session is read-only for 5 minutes after three invalid step-up codes"),
    ErrorCode.POSITIONS_UNKNOWN: ErrorMeta(("rest",), None, False, None, None, "Open-position state is unavailable; resend with acknowledge_unknown_positions=true"),
    ErrorCode.FORBIDDEN: ErrorMeta(("rest", "ws",), "any", False, None, None, "Authenticated but lacking the required permission"),
    ErrorCode.CSRF_TOKEN_INVALID: ErrorMeta(("rest",), None, False, None, None, "CSRF token missing, not matching the __Host-cv_csrf cookie, or not bound to this session (SR-041)"),
    ErrorCode.ACCOUNT_SCOPE_DENIED: ErrorMeta(("rest", "ws",), "any", False, None, None, "Caller has no granted access to the targeted exchange account"),
    ErrorCode.TRADING_DISABLED: ErrorMeta(("rest",), None, False, None, None, "Kill-switch or maintenance mode engaged, or live trading not enabled for this deployment"),
    ErrorCode.RISK_LIMIT_BREACHED: ErrorMeta(("rest",), None, False, None, None, "Per-account profile risk cap (daily loss, max position, allowed symbols) would be exceeded"),
    ErrorCode.NOT_FOUND: ErrorMeta(("rest",), None, False, None, None, "Resource does not exist or is out of the caller's scope"),
    ErrorCode.CONFLICT: ErrorMeta(("rest",), None, False, None, None, "Concurrent modification or state conflict"),
    ErrorCode.IDEMPOTENCY_KEY_REUSE: ErrorMeta(("rest",), None, False, None, None, "Idempotency-Key reused with a different request payload"),
    ErrorCode.IDEMPOTENCY_IN_FLIGHT: ErrorMeta(("rest",), None, True, None, None, "A request with this Idempotency-Key is still being processed"),
    ErrorCode.VERSION_CONFLICT: ErrorMeta(("rest",), None, False, None, None, "If-Match / ETag precondition failed"),
    ErrorCode.PAYLOAD_TOO_LARGE: ErrorMeta(("rest",), None, False, None, None, "Request body or batch exceeds the operation's size ceiling"),
    ErrorCode.GONE: ErrorMeta(("rest",), None, False, None, None, "Resource existed but was purged by retention policy"),
    ErrorCode.ORDER_NOT_AMENDABLE: ErrorMeta(("rest",), None, False, None, None, "Order is in a terminal or transitional state and cannot be amended"),
    ErrorCode.RULE_IR_INVALID: ErrorMeta(("rest",), None, False, None, None, "Rule intermediate representation failed semantic validation"),
    ErrorCode.INSUFFICIENT_BALANCE: ErrorMeta(("rest",), None, False, None, None, "Exchange rejected the order for insufficient margin"),
    ErrorCode.NO_DATA_RECORDED: ErrorMeta(("rest", "ws",), "any", False, None, None, "Requested window predates the start of recording for this symbol"),
    ErrorCode.BAR_WINDOW_TOO_LARGE: ErrorMeta(("rest",), None, False, None, None, "Bar window exceeds the hard cap (400 d time / 31 d or 250 000 bars non-time)"),
    ErrorCode.RESPONSE_TOO_LARGE: ErrorMeta(("rest",), None, False, None, None, "Bar page would exceed the response size ceiling; request a smaller `limit`"),
    ErrorCode.RATE_LIMITED: ErrorMeta(("rest",), None, True, None, None, "Per-user API rate limit exceeded"),
    ErrorCode.EXCHANGE_RATE_LIMITED: ErrorMeta(("rest",), None, True, None, None, "Bybit per-UID rate budget exhausted (10006/10018) \u2014 request shed locally"),
    ErrorCode.INTERNAL_ERROR: ErrorMeta(("rest", "ws",), "any", True, None, None, "Unhandled server error (correlation id in `instance`)"),
    ErrorCode.EXCHANGE_ERROR: ErrorMeta(("rest",), None, True, None, None, "Bybit returned a non-zero retCode"),
    ErrorCode.EXCHANGE_UNAVAILABLE: ErrorMeta(("rest", "ws",), "any", True, None, None, "Exchange connectivity lost (WS down and REST failing)"),
    ErrorCode.STORE_UNAVAILABLE: ErrorMeta(("rest",), None, True, None, None, "QuestDB / Postgres / Parquet tier unavailable"),
    ErrorCode.DEGRADED_DATA: ErrorMeta(("rest", "ws",), "any", True, None, None, "Local store is behind the exchange beyond the freshness SLO"),
    ErrorCode.TIMEOUT: ErrorMeta(("rest",), None, True, None, None, "Upstream exchange call exceeded the deadline"),
    ErrorCode.PROTOCOL_VIOLATION: ErrorMeta(("ws",), "connection", False, None, 1002, "Frame out of order or malformed envelope"),
    ErrorCode.FRAME_MALFORMED: ErrorMeta(("ws",), "connection", False, None, 1002, "Binary body inconsistent with its header"),
    ErrorCode.UNSUPPORTED_PROTOCOL: ErrorMeta(("ws",), "connection", False, None, 1002, "No mutually supported subprotocol offered"),
    ErrorCode.NOT_AUTHENTICATED: ErrorMeta(("ws",), "connection", False, "unauthenticated", 4401, "Frame sent before auth_ok"),
    ErrorCode.AUTH_FAILED: ErrorMeta(("ws",), "connection", False, "unauthenticated", 4401, "Token invalid or signature rejected"),
    ErrorCode.AUTH_TIMEOUT: ErrorMeta(("ws",), "connection", False, None, 4401, "No auth frame within 10 s of open"),
    ErrorCode.TOKEN_EXPIRED: ErrorMeta(("ws",), "connection", True, "unauthenticated", 4401, "Access token expired; refresh over REST and re-auth"),
    ErrorCode.UNKNOWN_TOPIC: ErrorMeta(("ws",), "topic", False, "not_found", None, "Topic name not in the catalogue"),
    ErrorCode.INVALID_TOPIC_FORMAT: ErrorMeta(("ws",), "topic", False, "validation_failed", None, "Malformed topic string"),
    ErrorCode.UNSUPPORTED_SYMBOL: ErrorMeta(("ws",), "topic", False, "unsupported_category", None, "Not a Bybit USDT linear perpetual, or unknown instrument"),
    ErrorCode.INVALID_OPTIONS: ErrorMeta(("ws",), "topic", False, "validation_failed", None, "Subscription option out of range or unknown key"),
    ErrorCode.ENCODING_UNSUPPORTED: ErrorMeta(("ws",), "topic", False, None, None, "Binary encoding requested on a structured-only topic"),
    ErrorCode.SUBSCRIPTION_LIMIT: ErrorMeta(("ws",), "topic", True, "rate_limited", None, "200-subscription ceiling reached"),
    ErrorCode.TOO_MANY_TOPICS: ErrorMeta(("ws",), "request", True, "rate_limited", None, "More than 50 topics in one sub frame"),
    ErrorCode.DUPLICATE_SUBSCRIPTION: ErrorMeta(("ws",), "topic", False, "conflict", None, "Already subscribed; retune with ctl"),
    ErrorCode.NOT_SUBSCRIBED: ErrorMeta(("ws",), "topic", False, "not_found", None, "ctl/resync on a topic with no subscription"),
    ErrorCode.RESYNC_RATE_LIMITED: ErrorMeta(("ws",), "topic", True, "rate_limited", None, "More than 5 resyncs per minute on one topic; subscription revoked"),
    ErrorCode.CLIENT_RATE_LIMITED: ErrorMeta(("ws",), "connection", True, "rate_limited", 4429, "Inbound frame rate exceeded"),
    ErrorCode.SLOW_CONSUMER: ErrorMeta(("ws",), "connection", True, None, 4429, "Outbound queue overflow; connection closed"),
    ErrorCode.REPLAY_SESSION_NOT_FOUND: ErrorMeta(("ws",), "topic", False, "not_found", None, "Unknown or destroyed replay_session_id"),
    ErrorCode.REPLAY_SESSION_ENDED: ErrorMeta(("ws",), "topic", False, "gone", None, "Replay finished or was destroyed; subscription revoked"),
    ErrorCode.USER_DISABLED: ErrorMeta(("ws",), "connection", False, "forbidden", 4403, "Account disabled mid-session"),
}

#: Codes legal on the WebSocket (23-ws-protocol.md 10.2): WS-only plus dual-surface.
WS_ERROR_CODES: Final[frozenset[ErrorCode]] = frozenset(
    code for code, meta in ERROR_META.items() if "ws" in meta.surfaces
)
