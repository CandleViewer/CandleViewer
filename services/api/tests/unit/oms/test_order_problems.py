"""The one table of the answer each OMS error gets at the HTTP edge (E29-T04, #913).

The plan's taxonomy (section 3) with ruling R12: `RATE_BUDGET_EXCEEDED` is `429
exchange_rate_limited` with `Retry-After`, the clock-drift block `503 clock_drift` with
`Retry-After`, `OrderLinkIdExhausted` `500 internal_error` and a page, a stale `If-Match` `412
version_conflict`. Every code is in the contract's `x-error-codes` registry with the status the
table gives it, and a business rejection carries the exchange's return code only, never its text
(SR-E29-09).
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.oms.errors import (
    INTERNAL_ERROR,
    PROBLEMS,
    AccountScopeDenied,
    ClockDriftBlocked,
    DuplicateOrderLinkId,
    EnvironmentMismatch,
    ExchangeRejected,
    FieldError,
    IdempotencyKeyReuse,
    InvalidOrderLinkId,
    LotSizeViolation,
    OmsError,
    OrderInvalid,
    OrderLinkIdExhausted,
    OrderNotAmendable,
    OrderNotFound,
    OrderRefused,
    Problem,
    RateBudgetExceeded,
    RiskRefused,
    SessionNotArmed,
    StopUnitUnsupported,
    StoreUnavailable,
    TickSizeViolation,
    TradingDisabled,
    VersionConflict,
    problem_for,
)
from candleviewer.oms.validator import OrderPlacementRefused

_SPEC: Any = load_openapi_spec()  # a parsed YAML document, walked untyped
_REGISTRY: dict[str, int] = {entry["code"]: entry["status"] for entry in _SPEC["x-error-codes"]}

#: The plan's table and R12, written out independently of `PROBLEMS`.
_EXPECTED: list[tuple[OmsError, int, str, bool, bool]] = [
    (OrderInvalid(), 400, "validation_failed", False, False),
    (StopUnitUnsupported(), 400, "validation_failed", False, False),
    (TickSizeViolation(), 400, "tick_size_violation", False, False),
    (LotSizeViolation(), 400, "lot_size_violation", False, False),
    (AccountScopeDenied(), 403, "account_scope_denied", False, False),
    (RiskRefused(), 403, "risk_limit_breached", False, False),
    (TradingDisabled(), 403, "trading_disabled", False, False),
    (
        OrderPlacementRefused(reason_code=None, reason_text=None),
        403,
        "trading_disabled",
        False,
        False,
    ),
    (SessionNotArmed(), 403, "session_not_armed", False, False),
    (OrderNotFound(), 404, "not_found", False, False),
    (IdempotencyKeyReuse(), 409, "idempotency_key_reuse", False, False),
    (VersionConflict(), 412, "version_conflict", False, False),
    (OrderNotAmendable(), 422, "order_not_amendable", False, False),
    (RateBudgetExceeded(retry_after_s=2), 429, "exchange_rate_limited", True, False),
    (OrderLinkIdExhausted(first="a", last="b"), 500, "internal_error", False, True),
    (
        EnvironmentMismatch(order_environment="demo", route_environment="live"),
        500,
        "internal_error",
        False,
        True,
    ),
    (ExchangeRejected(ret_code=110007), 502, "exchange_error", False, False),
    (ClockDriftBlocked(retry_after_s=5), 503, "clock_drift", True, False),
    (StoreUnavailable(), 503, "store_unavailable", False, False),
]


@pytest.mark.parametrize(
    ("error", "status", "code", "retry_after", "pages"),
    _EXPECTED,
    ids=[type(row[0]).__name__ for row in _EXPECTED],
)
def test_problem_for_answers_each_error_as_the_plan_and_r12_say(
    error: OmsError, status: int, code: str, retry_after: bool, pages: bool
) -> None:
    assert problem_for(error) == Problem(status, code, retry_after=retry_after, pages=pages)


def test_every_answer_is_a_registered_code_with_its_registered_status() -> None:
    answers = {(problem.code, problem.status) for problem in PROBLEMS.values()}
    assert sorted(code for code, status in answers if _REGISTRY.get(code) != status) == []


def test_the_table_has_one_row_per_error_class_and_nothing_else() -> None:
    by_inheritance = {StopUnitUnsupported, OrderPlacementRefused}  # answered by their base class
    assert set(PROBLEMS) == {type(row[0]) for row in _EXPECTED} - by_inheritance


@pytest.mark.parametrize(
    "error",
    [InvalidOrderLinkId("x"), DuplicateOrderLinkId("cvd-x"), OmsError("unmapped")],
)
def test_an_error_the_table_does_not_name_is_an_internal_error(error: OmsError) -> None:
    assert problem_for(error) == INTERNAL_ERROR == Problem(500, "internal_error")


def test_exchange_rejected_cannot_carry_the_exchanges_text() -> None:
    """SR-E29-09, 24 Sec.8.6 code-only rule: the constructor takes the return code alone."""
    assert list(inspect.signature(ExchangeRejected).parameters) == ["ret_code"]
    rejected = ExchangeRejected(ret_code=110007)
    assert (rejected.ret_code, rejected.detail, rejected.errors) == (
        110007,
        "The exchange refused the order.",
        (),
    )
    assert str(rejected) == rejected.detail


@pytest.mark.parametrize("error", [RateBudgetExceeded, ClockDriftBlocked])
@pytest.mark.parametrize("seconds", [0, -1])
def test_a_retry_after_answer_needs_a_positive_delay(error: Any, seconds: int) -> None:
    with pytest.raises(ValueError, match="retry_after_s"):
        error(retry_after_s=seconds)


def test_a_refusal_keeps_its_detail_and_every_error_in_order() -> None:
    errors = (
        FieldError("stop_loss", "native_stop_required", "No stop."),
        FieldError("intent", "intent_mismatch", "Wrong intent."),
    )
    refused = OrderInvalid("2 rules failed.", errors=iter(errors))
    assert (refused.detail, refused.errors, str(refused)) == (
        "2 rules failed.",
        errors,
        "2 rules failed.",
    )


@pytest.mark.parametrize(
    "cls", [cls for cls in PROBLEMS if issubclass(cls, OrderRefused)], ids=lambda cls: cls.__name__
)
def test_every_refusal_has_a_fixed_default_detail(cls: type[OrderRefused]) -> None:
    assert cls.default_detail.endswith(".") and cls.default_detail != OrderRefused.default_detail


def test_environment_mismatch_names_both_environments() -> None:
    mismatch = EnvironmentMismatch(order_environment="demo", route_environment="live")
    assert (mismatch.order_environment, mismatch.route_environment) == ("demo", "live")
    assert str(mismatch) == "an order for demo met a route to live (C-2.11)"
