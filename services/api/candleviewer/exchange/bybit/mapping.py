"""Bybit `retCode` -> internal taxonomy mapping
(`docs/plan/24-internal-schemas.md` §8.6, ticket body "mapping.py").

`map_ret_code` is exhaustive over the documented table: every code Bybit is
known to return maps to exactly one `ExchangeError` subclass, and anything
else (including a code Bybit adds later) raises `UnknownStateError` with the
raw code/message preserved — never a silent pass-through (acceptance
criterion 6, C-2.2 adapter rule 1).
"""

from __future__ import annotations

from candleviewer.exchange.base.errors import (
    AuthError,
    ClockDriftError,
    DuplicateClientIdError,
    ExchangeError,
    InstrumentFilterError,
    InsufficientMarginError,
    NotFoundError,
    RateLimitError,
    UnknownStateError,
)

#: retCode -> (exception class, extra kwargs). `10001` is handled specially
#: in `map_ret_code` because its taxonomy target depends on the message text
#: (duplicate `orderLinkId` vs. a generic parameter error). Entries that map
#: to `InstrumentFilterError` carry the filter name §8.6 associates with
#: that retCode, since `InstrumentFilterError` requires one. The codes #3005
#: re-checked follow the official v5 error table (page dated 2026-10-14; §8.6
#: says how to re-verify it): every `*_not_modified` filter is a benign no-op,
#: and every risk-limit refusal shares `risk_limit_tier`.
_RET_CODE_MAP: dict[int, tuple[type[ExchangeError], dict[str, str]]] = {
    10002: (ClockDriftError, {}),
    10003: (AuthError, {}),
    10004: (AuthError, {}),
    10005: (AuthError, {}),
    10006: (RateLimitError, {}),
    10010: (AuthError, {}),
    10016: (RateLimitError, {}),
    10018: (RateLimitError, {}),
    10019: (RateLimitError, {}),
    10403: (RateLimitError, {}),
    10404: (InstrumentFilterError, {"filter_name": "unknown_op_or_category"}),
    10429: (RateLimitError, {}),
    20006: (DuplicateClientIdError, {}),
    110001: (NotFoundError, {}),
    110003: (InstrumentFilterError, {"filter_name": "price_out_of_bounds"}),
    110004: (InsufficientMarginError, {}),
    110007: (InsufficientMarginError, {}),
    110012: (InsufficientMarginError, {}),
    110013: (InstrumentFilterError, {"filter_name": "risk_limit_tier"}),
    110014: (InsufficientMarginError, {}),
    110016: (InstrumentFilterError, {"filter_name": "risk_limit_tier"}),
    110017: (InstrumentFilterError, {"filter_name": "reduce_only_violation"}),
    110020: (InstrumentFilterError, {"filter_name": "max_open_orders"}),
    110024: (InstrumentFilterError, {"filter_name": "position_mode_switch_open_position"}),
    110025: (InstrumentFilterError, {"filter_name": "position_mode_not_modified"}),
    110026: (InstrumentFilterError, {"filter_name": "margin_mode_not_modified"}),
    110028: (InstrumentFilterError, {"filter_name": "position_mode_switch_open_orders"}),
    110031: (InstrumentFilterError, {"filter_name": "risk_limit_tier"}),
    110036: (InstrumentFilterError, {"filter_name": "leverage_refused_margin_mode"}),
    110038: (InstrumentFilterError, {"filter_name": "leverage_refused_margin_mode"}),
    110043: (InstrumentFilterError, {"filter_name": "leverage_not_modified"}),
    110044: (InsufficientMarginError, {}),
    110045: (InsufficientMarginError, {}),
    110047: (InstrumentFilterError, {"filter_name": "risk_limit_tier"}),
    110048: (InstrumentFilterError, {"filter_name": "risk_limit_tier"}),
    110072: (DuplicateClientIdError, {}),
    110073: (InstrumentFilterError, {"filter_name": "margin_mode_switch_failed"}),
    110079: (UnknownStateError, {}),
    110086: (InstrumentFilterError, {"filter_name": "risk_limit_tier"}),
    110089: (InstrumentFilterError, {"filter_name": "risk_limit_tier"}),
    3400139: (InstrumentFilterError, {"filter_name": "risk_limit_tier"}),
}

_DUPLICATE_MARKERS = ("duplicate", "orderlinkid", "order_link_id")


def map_ret_code(ret_code: int, ret_msg: str) -> ExchangeError:
    """Map one Bybit `(retCode, retMsg)` pair to an `ExchangeError` instance.

    Never called with `ret_code == 0` (the caller checks success first).
    `10001` needs the message text to disambiguate a generic parameter
    error from a duplicate-`orderLinkId` rejection (§8.6 row 2); every other
    code is a straight table lookup. An unmapped code always raises
    `UnknownStateError` — that is the acceptance-criterion-6 contract, not a
    bug to silence.
    """
    if ret_code == 10001:
        lowered = ret_msg.lower()
        if any(marker in lowered for marker in _DUPLICATE_MARKERS):
            return DuplicateClientIdError(
                ret_msg, exchange_ret_code=ret_code, exchange_ret_msg=ret_msg
            )
        return InstrumentFilterError(
            ret_msg,
            filter_name="unknown",
            exchange_ret_code=ret_code,
            exchange_ret_msg=ret_msg,
        )

    error_cls = _RET_CODE_MAP.get(ret_code)
    if error_cls is None:
        return UnknownStateError(
            f"Unmapped Bybit retCode {ret_code}: {ret_msg}",
            exchange_ret_code=ret_code,
            exchange_ret_msg=ret_msg,
        )
    cls_, extra_kwargs = error_cls
    # mypy cannot narrow `**extra_kwargs: dict[str, str]` against each
    # subclass's own keyword-only signature (e.g. `filter_name` on
    # `InstrumentFilterError` only); the table above is the single source of
    # truth and is itself fully typed, so this is a targeted, justified
    # override rather than a blanket suppression.
    return cls_(ret_msg, exchange_ret_code=ret_code, exchange_ret_msg=ret_msg, **extra_kwargs)  # type: ignore[arg-type]
