"""Coverage for the internal exchange error taxonomy
(`docs/plan/24-internal-schemas.md` §8.6): each subclass's default
`retryable` value and its `code` label."""

from __future__ import annotations

import pytest

from candleviewer.exchange.base.errors import (
    AmbiguousResultError,
    AuthError,
    ClockDriftError,
    DuplicateClientIdError,
    ExchangeError,
    InstrumentFilterError,
    InsufficientMarginError,
    NotFoundError,
    OmsErrorCode,
    RateBudgetExceededError,
    RateLimitError,
    ServiceUnavailableError,
    TransportError,
    UnknownStateError,
)


@pytest.mark.parametrize(
    ("error_cls", "expected_code", "expected_retryable"),
    [
        (AuthError, OmsErrorCode.AUTH_ERROR, False),
        (ClockDriftError, OmsErrorCode.CLOCK_DRIFT, False),
        (RateLimitError, OmsErrorCode.RATE_LIMITED, True),
        (InsufficientMarginError, OmsErrorCode.INSUFFICIENT_MARGIN, False),
        (DuplicateClientIdError, OmsErrorCode.DUPLICATE_CLIENT_ID, False),
        (NotFoundError, OmsErrorCode.ORDER_NOT_FOUND, False),
        (TransportError, OmsErrorCode.TRANSPORT_ERROR, True),
        (ServiceUnavailableError, OmsErrorCode.SERVICE_UNAVAILABLE, True),
        (UnknownStateError, OmsErrorCode.UNKNOWN_STATE, True),
        (AmbiguousResultError, OmsErrorCode.TRANSPORT_ERROR, False),
    ],
)
def test_error_subclass_defaults_code_and_retryable(
    error_cls: type[ExchangeError], expected_code: OmsErrorCode, expected_retryable: bool
) -> None:
    err = error_cls("boom")
    assert err.code == expected_code
    assert err.retryable is expected_retryable
    assert err.user_message == "boom"


def test_error_subclass_retryable_can_be_overridden() -> None:
    err = RateLimitError("boom", retryable=False)
    assert err.retryable is False


def test_an_ambiguous_create_is_a_transport_error_never_made_retryable() -> None:
    err = AmbiguousResultError("boom", order_link_id="cv-1", retryable=True)
    assert isinstance(err, TransportError) and err.retryable is False
    assert err.order_link_id == "cv-1"


def test_the_venues_outage_is_a_transport_level_error_never_a_rate_limit() -> None:
    """#2863: 10016 and 10019 are the venue's outage (24 section 8.6, `SERVICE_UNAVAILABLE`):
    retried as a transport fault is, never drained from the rate budget as a rate limit is."""
    err = ServiceUnavailableError("boom", exchange_ret_code=10016)
    assert isinstance(err, TransportError) and not isinstance(err, RateLimitError)
    assert not isinstance(err, AmbiguousResultError)


def test_a_refused_budget_names_which_budget_refused() -> None:
    """24 §14.4 (G-8b, OQ-2): a refused token and a private stream refused at the cap are both
    `RATE_BUDGET_EXCEEDED` and retryable, and `reason` tells them apart for metrics and audit."""
    token = RateBudgetExceededError("no token")
    cap = RateBudgetExceededError("no stream", reason="stream_cap")
    assert (token.reason, cap.reason) == ("token_bucket", "stream_cap")
    assert token.code == cap.code == OmsErrorCode.RATE_BUDGET_EXCEEDED
    assert token.retryable and cap.retryable


def test_instrument_filter_error_carries_filter_name() -> None:
    err = InstrumentFilterError("qty too small", filter_name="min_order_qty")
    assert err.filter_name == "min_order_qty"
    assert err.code == OmsErrorCode.INSTRUMENT_FILTER


def test_exchange_error_base_defaults() -> None:
    err = ExchangeError("boom")
    assert err.code == OmsErrorCode.EXCHANGE_UNKNOWN
    assert err.retryable is False
    assert err.retry_after_s is None
    assert err.exchange_ret_code is None
    assert err.exchange_ret_msg is None


def test_exchange_error_user_message_overrides_message() -> None:
    err = ExchangeError("internal detail", user_message="please try again")
    assert err.user_message == "please try again"
    assert str(err) == "internal detail"
