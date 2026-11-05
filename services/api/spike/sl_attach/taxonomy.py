"""Each sample's three readings of a failure (#856 Scope "failure taxonomy"; the scout's §3):
the raw `retCode`, the code the adapter reports as built (`mapping.map_ret_code` and the port's
create rules), and the code `24` §8.6 assigns. Where the two codes differ the sample says so
(`divergent`). The divergence is a finding for the ADR, never a fix in this ticket (BQ-7), and
§8.6 has no `trading-stop`-specific row, so a stop write's code reads its general row.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from candleviewer.exchange.bybit.mapping import OPEN_CREATE_CODES, map_ret_code

_IF, _RISK, _MARGIN = "INSTRUMENT_FILTER", "RISK_LIMIT_EXCEEDED", "INSUFFICIENT_MARGIN"
_AUTH, _RATE, _MODE = "AUTH_ERROR", "RATE_LIMITED", "POSITION_MODE_MISMATCH"
_UNAVAILABLE, _TRANSPORT = "SERVICE_UNAVAILABLE", "TRANSPORT_ERROR"
#: `24` §8.6's table, retCode -> internal code, as written (the general rows; the create-only
#: variants are in `s86_code`).
S86: Final[dict[int, str]] = {
    10001: _IF,
    10002: "CLOCK_DRIFT",
    10003: _AUTH,
    10004: _AUTH,
    10005: "PERMISSION_DENIED",
    10006: _RATE,
    10010: "IP_NOT_ALLOWED",
    10016: _UNAVAILABLE,
    10018: _RATE,
    10019: _UNAVAILABLE,
    10403: _RATE,
    10404: _IF,
    10429: _RATE,
    33004: _AUTH,
    110001: "ORDER_NOT_FOUND",
    110003: "PRICE_OUT_OF_BOUNDS",
    110004: _MARGIN,
    110007: _MARGIN,
    110012: _MARGIN,
    110013: _RISK,
    110014: _MARGIN,
    110016: _RISK,
    110017: "REDUCE_ONLY_VIOLATION",
    110020: "ORDER_CAP_EXCEEDED",
    110024: _MODE,
    110025: _MODE,
    110026: _IF,
    110028: _MODE,
    110031: _RISK,
    110036: "LEVERAGE_ERROR",
    110038: "LEVERAGE_ERROR",
    110043: "LEVERAGE_ERROR",
    110044: _MARGIN,
    110045: _MARGIN,
    110047: _RISK,
    110048: _RISK,
    110073: _IF,
    110079: "UNKNOWN_STATE",
    110086: _RISK,
    110089: _RISK,
    3400139: _RISK,
}
#: §8.6's "Retryable: yes" rows. Its "Order creates" rule takes `retryable` away from a create
#: only for the open outcomes (10016, 10019), 110079 and an unmapped code (already outside the
#: set): a create's rate limit (10006, 10018, 10403, 10429) stays retryable, as the adapter
#: retries it (`rest.py`'s `RateLimitError` branch).
S86_RETRYABLE: Final = frozenset({10006, 10016, 10018, 10019, 10403, 10429, 110079})
_NOT_RESENT: Final = OPEN_CREATE_CODES | {110079}
_DUPLICATES: Final = frozenset({20006, 110072})
UNKNOWN: Final = "EXCHANGE_UNKNOWN"


def s86_code(ret_code: int, ret_msg: str, *, create: bool) -> str:
    """The internal code §8.6 assigns to a venue answer with a code."""
    if create and (
        ret_code in _DUPLICATES or (ret_code == 10001 and "duplicate" in ret_msg.lower())
    ):
        return "DUPLICATE_CLIENT_ID"
    if create and ret_code in OPEN_CREATE_CODES:
        return _TRANSPORT
    return S86.get(ret_code, UNKNOWN)


def s86_transport(status: int | None, *, create: bool) -> str:
    """§8.6's transport-level line: HTTP 403, 429, 5xx; anything else (a timeout, a reset, an
    unreadable answer) is a transport error. A create's 5xx is an open outcome ("Order
    creates"): `TRANSPORT_ERROR`, as the adapter's `AmbiguousResultError` reports it."""
    if status == 403:
        return "IP_NOT_ALLOWED"
    if status == 429:
        return _RATE
    if status is not None and 500 <= status <= 599 and not create:
        return _UNAVAILABLE
    return _TRANSPORT


def adapter_code(ret_code: int, ret_msg: str, *, create: bool) -> tuple[str, bool]:
    """The code and `retryable` the adapter reports as built: `map_ret_code`, and for a create
    the port's open outcome (10016, 10019: an ambiguous result, never resent). A create's
    `UNKNOWN_STATE` (110079, unmapped) is never resent; its rate limit is retried."""
    if create and ret_code in OPEN_CREATE_CODES:
        return _TRANSPORT, False
    error = map_ret_code(ret_code, ret_msg, create=create)
    unknown = error.code.value == "UNKNOWN_STATE"
    return error.code.value, error.retryable and not (create and unknown)


def msg_class(ret_code: int, ret_msg: str) -> str:
    """`retMsg` as a short token: the raw text can carry identifiers, so it is never kept."""
    text = ret_msg.lower()
    if ret_code == 0:
        return "ok"
    for token in ("duplicate", "not modified", "zero position", "too many visits"):
        if token in text:
            return token.replace(" ", "_")
    return "other"


@dataclass(frozen=True, slots=True)
class Reading:
    ret_code: int | None
    ret_msg_class: str | None
    adapter_error_code: str | None
    s86_code: str | None
    retryable: bool | None
    divergent: bool


OK: Final = Reading(0, "ok", None, None, None, divergent=False)


def read_answer(ret_code: int, ret_msg: str, adapter: str | None, *, create: bool) -> Reading:
    """A venue answer with a code: `adapter` is the code the port reported (an ack's
    `error_code`, or a raised error's), `None` when it reported none."""
    internal = s86_code(ret_code, ret_msg, create=create)
    retryable = ret_code in S86_RETRYABLE and not (create and ret_code in _NOT_RESENT)
    seen = adapter if adapter is not None else adapter_code(ret_code, ret_msg, create=create)[0]
    return Reading(
        ret_code, msg_class(ret_code, ret_msg), seen, internal, retryable, seen != internal
    )


def read_transport(adapter: str, status: int | None, *, create: bool) -> Reading:
    """A failure with no venue code: a transport fault, or a local refusal (never sent)."""
    local = adapter == "RATE_BUDGET_EXCEEDED"
    internal = adapter if local else s86_transport(status, create=create)
    return Reading(None, None, adapter, internal, None, adapter != internal)
