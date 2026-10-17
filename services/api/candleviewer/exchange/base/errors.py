"""Internal exchange error taxonomy (`docs/plan/24-internal-schemas.md` §8.6).

Every exchange error (transport or business rejection) is mapped, at the
adapter boundary, to exactly one of these types. No `retCode` integer, and
no exchange-specific error string, escapes the exchange adapter (C-2.2, adapter
rule 1, §14.2). An error class not in this taxonomy is a defect: the
boundary wrapper re-raises it as `UnknownStateError` with the original
preserved as `__cause__` (acceptance criterion 4).

`AuthError` and `ClockDriftError` carry safety semantics that gate trading
(§8.6, §2.8): auth failures are never retried silently, and clock drift
blocks trading mode system-wide until resolved. These semantics are
documented here, in the docstrings, so a later ticket (E29, OMS) cannot
reinterpret them.
"""

from __future__ import annotations

from enum import StrEnum


class OmsErrorCode(StrEnum):
    """Stable internal error code, verbatim from §8.6. Used as the
    `exchange_errors_total{class,...}` metric label and the log field."""

    AUTH_ERROR = "AUTH_ERROR"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    IP_NOT_ALLOWED = "IP_NOT_ALLOWED"
    CLOCK_DRIFT = "CLOCK_DRIFT"
    RATE_LIMITED = "RATE_LIMITED"
    RATE_BUDGET_EXCEEDED = "RATE_BUDGET_EXCEEDED"
    INSUFFICIENT_MARGIN = "INSUFFICIENT_MARGIN"
    INSTRUMENT_FILTER = "INSTRUMENT_FILTER"
    REDUCE_ONLY_VIOLATION = "REDUCE_ONLY_VIOLATION"
    POSITION_MODE_MISMATCH = "POSITION_MODE_MISMATCH"
    LEVERAGE_ERROR = "LEVERAGE_ERROR"
    RISK_LIMIT_EXCEEDED = "RISK_LIMIT_EXCEEDED"
    ORDER_NOT_FOUND = "ORDER_NOT_FOUND"
    DUPLICATE_CLIENT_ID = "DUPLICATE_CLIENT_ID"
    ORDER_CAP_EXCEEDED = "ORDER_CAP_EXCEEDED"
    MARKET_CLOSED = "MARKET_CLOSED"
    PRICE_OUT_OF_BOUNDS = "PRICE_OUT_OF_BOUNDS"
    TRANSPORT_ERROR = "TRANSPORT_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    UNKNOWN_STATE = "UNKNOWN_STATE"
    EXCHANGE_UNKNOWN = "EXCHANGE_UNKNOWN"


class ExchangeError(Exception):
    """Base of the internal exchange-error taxonomy.

    Every subclass carries `retryable` (whether the OMS may resend the same
    request, e.g. reusing `order_link_id` per C-2.10) and `retry_after_s`
    (a hint from the exchange's own rate-limit headers, when present).
    `user_message` is plain language, safe to render directly in the UI —
    downstream code never renders a raw exception string or a bare exchange
    code (accessibility note, ticket body).
    """

    code: OmsErrorCode = OmsErrorCode.EXCHANGE_UNKNOWN

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        retry_after_s: float | None = None,
        user_message: str | None = None,
        exchange_ret_code: int | None = None,
        exchange_ret_msg: str | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.retry_after_s = retry_after_s
        self.user_message = user_message if user_message is not None else message
        self.exchange_ret_code = exchange_ret_code
        self.exchange_ret_msg = exchange_ret_msg


class AuthError(ExchangeError):
    """Invalid API key, bad signature, or permission denied (retCodes
    10003/10004/10005). **Never retried silently** — the calling code must
    disable the offending account and alert the owner (§8.6 OMS behaviour
    column); a caller that retries an `AuthError` without a human-in-the-loop
    is a defect."""

    code = OmsErrorCode.AUTH_ERROR

    def __init__(self, message: str, **kwargs: object) -> None:
        kwargs.setdefault("retryable", False)
        super().__init__(message, **kwargs)  # type: ignore[arg-type]


class ClockDriftError(ExchangeError):
    """Request timestamp outside `recv_window` (retCode 10002). **Blocks all
    order entry system-wide** until a clock resync completes — this is a
    trading-mode gate, not a per-request retry (§8.6, §2.8)."""

    code = OmsErrorCode.CLOCK_DRIFT

    def __init__(self, message: str, **kwargs: object) -> None:
        kwargs.setdefault("retryable", False)
        super().__init__(message, **kwargs)  # type: ignore[arg-type]


class RateLimitError(ExchangeError):
    """Per-UID or per-IP rate limit hit (retCodes 10006/10018/10403/10429).
    Retryable with backoff; feeds the token-bucket governor (§8.7)."""

    code = OmsErrorCode.RATE_LIMITED

    def __init__(self, message: str, **kwargs: object) -> None:
        kwargs.setdefault("retryable", True)
        super().__init__(message, **kwargs)  # type: ignore[arg-type]


class InsufficientMarginError(ExchangeError):
    """Insufficient wallet/available balance or margin (retCodes
    110004/110007/110012/110014/110044/110045). Never retryable as-is; the
    leg-failure policy (§9.5) applies."""

    code = OmsErrorCode.INSUFFICIENT_MARGIN

    def __init__(self, message: str, **kwargs: object) -> None:
        kwargs.setdefault("retryable", False)
        super().__init__(message, **kwargs)  # type: ignore[arg-type]


class InstrumentFilterError(ExchangeError):
    """A price/qty/notional filter was violated (`InstrumentPolicy.
    validate_order`, §1.3 rule 3). Always names the specific violated filter
    (`min_order_qty`, `qty_step`, `min_notional`, `max_mkt_order_qty`,
    `price_scale`, `min_price`, `max_price`) — never a generic message,
    because the UI renders the filter name."""

    code = OmsErrorCode.INSTRUMENT_FILTER

    def __init__(self, message: str, *, filter_name: str, **kwargs: object) -> None:
        kwargs.setdefault("retryable", False)
        super().__init__(message, **kwargs)  # type: ignore[arg-type]
        self.filter_name = filter_name


class DuplicateClientIdError(ExchangeError):
    """`order_link_id` was already accepted (retCodes 10001/20006/110072).
    Per C-2.10 / §14.2 rule 2, this means *already accepted, not a failure*:
    the caller must resolve it via success-after-lookup, never resubmit
    under a new id."""

    code = OmsErrorCode.DUPLICATE_CLIENT_ID

    def __init__(self, message: str, **kwargs: object) -> None:
        kwargs.setdefault("retryable", False)
        super().__init__(message, **kwargs)  # type: ignore[arg-type]


class NotFoundError(ExchangeError):
    """Referenced order/resource does not exist on the exchange (retCode
    110001). On cancel: treat as already-terminal and reconcile; on amend:
    reject (§8.6)."""

    code = OmsErrorCode.ORDER_NOT_FOUND

    def __init__(self, message: str, **kwargs: object) -> None:
        kwargs.setdefault("retryable", False)
        super().__init__(message, **kwargs)  # type: ignore[arg-type]


class TransportError(ExchangeError):
    """HTTP 5xx, connection reset, or `asyncio.TimeoutError` after send.
    Retryable; an ambiguous timeout after send leaves the order state
    `Unknown` pending reconciliation (§8.2, §8.6 "Transport-level" row)."""

    code = OmsErrorCode.TRANSPORT_ERROR

    def __init__(self, message: str, **kwargs: object) -> None:
        kwargs.setdefault("retryable", True)
        super().__init__(message, **kwargs)  # type: ignore[arg-type]


class UnknownStateError(ExchangeError):
    """Catch-all for an exchange error class that is not in this taxonomy, or
    a response the adapter cannot interpret confidently (retCode 110079,
    "processing"). The boundary wrapper raises this with the original
    exception chained as `__cause__` and increments
    `exchange_errors_total{class="UNKNOWN_STATE",...}` — see acceptance
    criterion 4 (`E08-T01`)."""

    code = OmsErrorCode.UNKNOWN_STATE

    def __init__(self, message: str, **kwargs: object) -> None:
        kwargs.setdefault("retryable", True)
        super().__init__(message, **kwargs)  # type: ignore[arg-type]
