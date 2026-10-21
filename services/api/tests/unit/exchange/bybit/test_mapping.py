"""Mapping-table tests (ticket scenario "Unknown retCode is loud" + DoD
"coverage >=85%"). Exhaustiveness over the documented §8.6 table and the
UnknownStateError fallback for anything not in it. #3005: every code the official v5
table changed or added, fed through the corpus error envelope (C-13.5).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

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
from candleviewer.exchange.bybit.mapping import map_ret_code
from tests._corpus import rest

RISK_LIMIT = "risk_limit_tier"
LEVERAGE_IN_MODE = "leverage_refused_margin_mode"
#: The official v5 error table, https://bybit-exchange.github.io/docs/v5/error (page dated
#: 2026-10-14), verified by main-orchestrator for #2893 S15: retCode -> (text, class, filter).
#: The text is S15's where S15 quotes one, else #3005's wording of the table, not verbatim.
OFFICIAL_V5: dict[int, tuple[str, type[ExchangeError], str | None]] = {
    110013: ("Cannot set leverage due to risk limit level.", InstrumentFilterError, RISK_LIMIT),
    110016: ("quantity exceeds risk limit", InstrumentFilterError, RISK_LIMIT),
    110017: ("orderQty will be truncated to zero", InstrumentFilterError, "reduce_only_violation"),
    110024: (
        "You have an existing position, so the position mode cannot be switched.",
        InstrumentFilterError,
        "position_mode_switch_open_position",
    ),
    110025: (
        "Position mode has not been modified.",
        InstrumentFilterError,
        "position_mode_not_modified",
    ),
    110026: (
        "Cross/isolated margin mode has not been modified.",
        InstrumentFilterError,
        "margin_mode_not_modified",
    ),
    110028: (
        "You have existing open orders, so the position mode cannot be switched.",
        InstrumentFilterError,
        "position_mode_switch_open_orders",
    ),
    110031: ("non-existing risk limit info", InstrumentFilterError, RISK_LIMIT),
    110036: ("leverage change refused in cross / PM mode", InstrumentFilterError, LEVERAGE_IN_MODE),
    110038: ("leverage change refused in cross / PM mode", InstrumentFilterError, LEVERAGE_IN_MODE),
    110044: ("Available margin is insufficient.", InsufficientMarginError, None),
    110045: ("", InsufficientMarginError, None),  # no official text in #3005 or S15
    110047: ("risk limit cannot be adjusted", InstrumentFilterError, RISK_LIMIT),
    110048: ("risk limit cannot be adjusted", InstrumentFilterError, RISK_LIMIT),
    110073: ("Set margin mode failed", InstrumentFilterError, "margin_mode_switch_failed"),
    110086: ("order leverage exceeds the tier", InstrumentFilterError, RISK_LIMIT),
    110089: ("exceeds the maximum risk limit level", InstrumentFilterError, RISK_LIMIT),
    3400139: ("positions+orders exceed the risk limit", InstrumentFilterError, RISK_LIMIT),
}


@pytest.mark.parametrize(
    ("ret_code", "expected_type"),
    [
        (10002, ClockDriftError),
        (10003, AuthError),
        (10004, AuthError),
        (10005, AuthError),
        (10006, RateLimitError),
        (10010, AuthError),
        (10016, RateLimitError),
        (10018, RateLimitError),
        (10019, RateLimitError),
        (10403, RateLimitError),
        (10404, InstrumentFilterError),
        (10429, RateLimitError),
        (20006, DuplicateClientIdError),
        (33004, AuthError),
        (110001, NotFoundError),
        (110003, InstrumentFilterError),
        (110004, InsufficientMarginError),
        (110007, InsufficientMarginError),
        (110012, InsufficientMarginError),
        (110014, InsufficientMarginError),
        (110017, InstrumentFilterError),
        (110020, InstrumentFilterError),
        (110025, InstrumentFilterError),
        (110043, InstrumentFilterError),
        (110044, InsufficientMarginError),
        (110072, DuplicateClientIdError),
        (110079, UnknownStateError),
    ],
)
def test_map_ret_code_covers_documented_table(ret_code: int, expected_type: type) -> None:
    """The table as an order create meets it: the only call a duplicate can answer (R9)."""
    error = map_ret_code(ret_code, "some message", create=True)
    assert isinstance(error, expected_type)
    assert error.exchange_ret_code == ret_code


def test_map_ret_code_10001_generic_parameter_error() -> None:
    error = map_ret_code(10001, "params error: qty invalid", create=True)
    assert isinstance(error, InstrumentFilterError)
    assert not isinstance(error, DuplicateClientIdError)


def test_map_ret_code_10001_duplicate_order_link_id() -> None:
    error = map_ret_code(10001, "orderLinkId is duplicate", create=True)
    assert isinstance(error, DuplicateClientIdError)


def test_a_10001_that_only_names_the_field_is_not_a_duplicate() -> None:
    """#2877 R9: the text must say "duplicate"; naming `orderLinkId` is a parameter error."""
    error = map_ret_code(10001, "orderLinkId is invalid", create=True)
    assert type(error) is InstrumentFilterError


@pytest.mark.parametrize(
    ("ret_code", "text", "expected_type"),
    [
        (110072, "OrderLinkedID is duplicate", UnknownStateError),
        (20006, "duplicate reqId", UnknownStateError),
        (10001, "orderLinkId is duplicate", InstrumentFilterError),
    ],
)
def test_a_duplicate_code_on_any_call_but_a_create_is_no_duplicate(
    ret_code: int, text: str, expected_type: type[ExchangeError]
) -> None:
    """#2877 R9: a cancel or an amend meeting a duplicate code is answered, not adopted:
    `create` is false unless the caller says so."""
    assert type(map_ret_code(ret_code, text)) is expected_type
    assert type(map_ret_code(ret_code, text, create=False)) is expected_type


#: The key-verification fixtures (E27-T03): documented-shape stand-ins from the v5 error table.
KEY_FIXTURES = Path(__file__).parents[3] / "fixtures" / "key_verification"


def test_an_expired_key_is_an_auth_error_never_retried() -> None:
    """33004, the v5 error table's "(Derivatives) Your api key has expired" (UTA section,
    bybit-exchange/docs@19518b90fb36): a typed `AuthError`, which gates trading, not an
    unmapped `UnknownStateError` that leaves a create's outcome open (#2877)."""
    body: dict[str, Any] = json.loads(
        (KEY_FIXTURES / "error_33004.json").read_text(encoding="utf-8")
    )
    for create in (True, False):
        error = map_ret_code(body["retCode"], body["retMsg"], create=create)
        assert type(error) is AuthError and error.retryable is False
        assert (error.exchange_ret_code, error.exchange_ret_msg) == (33004, body["retMsg"])


@pytest.mark.parametrize("ret_code", [170001, 999999, -1, 42])
def test_map_ret_code_unknown_raises_unknown_state_error(ret_code: int) -> None:
    error = map_ret_code(ret_code, "never seen before")
    assert isinstance(error, UnknownStateError)
    assert error.exchange_ret_code == ret_code
    assert error.retryable is True


@pytest.mark.parametrize("ret_code", sorted(OFFICIAL_V5))
def test_map_ret_code_follows_the_official_v5_table(ret_code: int) -> None:
    """The corpus error envelope (`rest/error_10002.json`) with the code and its official text:
    the class and filter of `24-internal-schemas.md` section 8.6, and never retryable."""
    text, expected_type, filter_name = OFFICIAL_V5[ret_code]
    envelope = {**rest("rest/error_10002.json"), "retCode": ret_code, "retMsg": text}
    error = map_ret_code(envelope["retCode"], envelope["retMsg"])
    assert type(error) is expected_type
    assert getattr(error, "filter_name", None) == filter_name
    assert error.retryable is False
    assert (error.exchange_ret_code, error.exchange_ret_msg) == (ret_code, text)
