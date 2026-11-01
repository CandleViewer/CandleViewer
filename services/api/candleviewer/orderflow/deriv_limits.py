"""Derivatives-history bounds (E24-T01 #665, E24-T03 #667) - the ONE constants module.

The threat model's G1 window cap and the read-side caps of `/market/open-interest` and
`/market/liquidations` (`docs/security/threat-models/E24-derivatives.md` D12; 22-api). Validated
before any store query. `tests/unit/orderflow/test_deriv_limits.py` asserts every value verbatim,
so a change is a reviewed diff.
"""

from __future__ import annotations

from typing import Final

from candleviewer.orderflow.errors import OrderflowError

MAX_WINDOW_DAYS_OI: Final = 400
MAX_WINDOW_DAYS_LIQ: Final = 31
MAX_LIMIT: Final = 500
DEFAULT_LIMIT: Final = 100
#: Not read here: the enforced TTL is `funding.CURSOR_TTL_S`, which `funding.decode_cursor`
#: (the one cursor codec both derivatives routes share) applies; `test_deriv_limits.py` pins
#: the two equal, so this module stays the one place the bound is stated.
CURSOR_TTL_S: Final = 3600
CURSOR_MAX_LEN: Final = 512
#: REST `cluster_window_ms` ceiling; WS keeps the 23 topic registry's 5000 (`ws/topics.py`).
CLUSTER_WINDOW_MS_MAX_REST: Final = 60_000
US_PER_DAY: Final = 86_400 * 1_000_000


class DerivInvalidRequest(OrderflowError):
    """Request bounds violated; `code` is the 22-api error-registry code (400)."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class DerivSymbolUnlisted(OrderflowError):
    """A well-formed symbol the instruments catalogue does not list (422)."""


def check_window(
    start_us: int | None, end_us: int | None, *, now_us: int, max_days: int
) -> tuple[int, int]:
    """Resolve `[start, end)` (end defaults to now, start to end - max) or raise."""
    end = end_us if end_us is not None else now_us
    start = start_us if start_us is not None else end - max_days * US_PER_DAY
    if start >= end or end - start > max_days * US_PER_DAY:
        raise DerivInvalidRequest(
            "invalid_time_range", f"from/to must be ordered and span <= {max_days} days"
        )
    return start, end


def check_limit(limit: int) -> int:
    if not 1 <= limit <= MAX_LIMIT:
        raise DerivInvalidRequest("validation_failed", f"limit must be 1..{MAX_LIMIT}")
    return limit


__all__ = [
    "CLUSTER_WINDOW_MS_MAX_REST",
    "CURSOR_MAX_LEN",
    "CURSOR_TTL_S",
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "MAX_WINDOW_DAYS_LIQ",
    "MAX_WINDOW_DAYS_OI",
    "DerivInvalidRequest",
    "DerivSymbolUnlisted",
    "check_limit",
    "check_window",
]
