"""The one table of the answer each OMS error gets at the HTTP edge (E29-T04, #913).

The plan's taxonomy (section 3) with ruling R12: `RATE_BUDGET_EXCEEDED` is `429
exchange_rate_limited` with `Retry-After`, the clock-drift block `503 clock_drift` with
`Retry-After`, `OrderLinkIdExhausted` `500 internal_error` and a page, a stale `If-Match` `412
version_conflict`. Every code is in the contract's `x-error-codes` registry with the status the
table gives it, and a business rejection carries the exchange's return code only, never its text
(SR-E29-09). Each refusal's `detail`, the sentence a problem body carries, is pinned word for word,
and each `errors[].rule` code to its wire value, which 22 `placeOrder` names.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.domain.order_entry import OrderEntryRefusal
from candleviewer.oms.errors import (
    INTERNAL_ERROR,
    PROBLEMS,
    RULE_INTENT_MISMATCH,
    RULE_NATIVE_STOP_REQUIRED,
    RULE_SIZING_MODE_UNSUPPORTED,
    RULE_STOP_UNIT_UNSUPPORTED,
    AccountScopeDenied,
    AnchorTaken,
    AuditNotDurable,
    ClockDriftBlocked,
    DuplicateOrderLinkId,
    EnvironmentMismatch,
    ExchangeRejected,
    ExchangeUnavailable,
    FieldError,
    IdempotencyInFlight,
    IdempotencyKeyReuse,
    InvalidOrderLinkId,
    LotSizeViolation,
    OmsError,
    OrderEntryRefused,
    OrderInvalid,
    OrderLinkIdExhausted,
    OrderMachinesFull,
    OrderNotAmendable,
    OrderNotFound,
    OrderRefused,
    Problem,
    RateBudgetExceeded,
    RiskRefused,
    SessionNotArmed,
    StopRequestInFlight,
    StopRequestPending,
    StopUnitUnsupported,
    StoreUnavailable,
    SubmissionRefused,
    TickSizeViolation,
    TradingDisabled,
    VersionConflict,
    problem_for,
)
from candleviewer.oms.validator import OrderPlacementRefused

_SPEC: Any = load_openapi_spec()  # a parsed YAML document, walked untyped
_REGISTRY: dict[str, int] = {entry["code"]: entry["status"] for entry in _SPEC["x-error-codes"]}
#: 22 `placeOrder`'s description on one line: a YAML block keeps its line breaks.
_PLACE_ORDER: str = " ".join(
    next(
        op["description"]
        for item in _SPEC["paths"].values()
        for op in item.values()
        if isinstance(op, dict) and op.get("operationId") == "placeOrder"
    ).split()
)
#: The `errors[].rule` codes of the order path's refusals, written out independently.
_RULES = (
    "native_stop_required",
    "intent_mismatch",
    "stop_unit_unsupported",
    "sizing_mode_unsupported",
)

#: An order-entry gate refusal (#3382), as the shared kernel builds one.
_GATE = OrderEntryRefusal("maintenance", "Order entry is paused for maintenance.")

#: The plan's table and R12, and slice 2b's rows, written out independently of `PROBLEMS`.
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
    (IdempotencyInFlight(retry_after_s=1), 409, "idempotency_in_flight", True, False),
    (StopRequestPending(retry_after_s=1), 409, "stop_request_in_flight", True, False),
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
    (OrderMachinesFull("1000 live machines"), 500, "internal_error", False, True),
    (ExchangeRejected(ret_code=110007), 502, "exchange_error", False, False),
    (ClockDriftBlocked(retry_after_s=5), 503, "clock_drift", True, False),
    (StoreUnavailable(), 503, "store_unavailable", False, False),
    (ExchangeUnavailable(retry_after_s=5), 503, "exchange_unavailable", True, False),
    (AuditNotDurable("the audit did not land"), 503, "audit_unavailable", False, False),
    (OrderEntryRefused(_GATE), 403, "trading_disabled", False, False),
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
    by_inheritance = {StopUnitUnsupported, OrderPlacementRefused, OrderEntryRefused}  # base's
    assert set(PROBLEMS) == {type(row[0]) for row in _EXPECTED} - by_inheritance


@pytest.mark.parametrize(
    "error",
    [
        InvalidOrderLinkId("x"),
        DuplicateOrderLinkId("cvd-x"),
        OmsError("unmapped"),
        AnchorTaken("ux_ia_principal_ref"),  # the pipeline answers these: one that escapes it
        StopRequestInFlight("in flight"),  # is a fault
        SubmissionRefused("account_not_live"),
    ],
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


@pytest.mark.parametrize(
    "error",
    [
        RateBudgetExceeded,
        ClockDriftBlocked,
        IdempotencyInFlight,
        StopRequestPending,
        ExchangeUnavailable,
    ],
)
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


def test_each_rule_code_is_its_wire_value() -> None:
    """`errors[].rule` is a free string in the contract, and every other test compares through
    these constants, so this is the test a changed literal fails."""
    constants = (
        RULE_NATIVE_STOP_REQUIRED,
        RULE_INTENT_MISMATCH,
        RULE_STOP_UNIT_UNSUPPORTED,
        RULE_SIZING_MODE_UNSUPPORTED,
    )
    assert constants == _RULES


@pytest.mark.parametrize("rule", _RULES)
def test_place_order_names_each_rule_code(rule: str) -> None:
    assert f"`{rule}`" in _PLACE_ORDER


#: Each refusal's fixed `detail`, written out independently of the classes.
_DETAILS: dict[type[OrderRefused], str] = {
    OrderRefused: "The order request was refused.",
    OrderInvalid: "The order failed validation.",
    TickSizeViolation: "A price is not a multiple of the instrument's tick size.",
    LotSizeViolation: "The quantity breaks the instrument's lot step, size or notional limits.",
    AccountScopeDenied: "The exchange account is not one you may trade.",
    RiskRefused: "The account's risk limits or profile do not allow this order.",
    TradingDisabled: "Order entry is disabled.",
    OrderPlacementRefused: "Order entry is paused: the terminal is read-only.",
    SessionNotArmed: "This session is not armed for live trading.",
    OrderNotFound: "No such order.",
    IdempotencyKeyReuse: "The Idempotency-Key was first used with another request.",
    VersionConflict: "The order has changed since the version you named.",
    OrderNotAmendable: "The order cannot be amended in its current state.",
    RateBudgetExceeded: "The exchange rate budget is spent; retry later.",
    ExchangeRejected: "The exchange refused the order.",
    ClockDriftBlocked: "Order entry is paused until the clock is back in sync.",
    StoreUnavailable: "Orders cannot be recorded right now, so none is sent.",
    IdempotencyInFlight: "A request with this Idempotency-Key is still being processed.",
    StopRequestPending: "Send the entry again once the position's stop request is answered.",
    ExchangeUnavailable: "The exchange did not answer, so the order was not sent.",
}


@pytest.mark.parametrize(
    ("cls", "detail"), list(_DETAILS.items()), ids=[cls.__name__ for cls in _DETAILS]
)
def test_each_refusal_has_its_own_fixed_default_detail(
    cls: type[OrderRefused], detail: str
) -> None:
    assert cls.default_detail == detail


def test_every_refusal_the_table_answers_has_its_detail_pinned() -> None:
    assert {cls for cls in PROBLEMS if issubclass(cls, OrderRefused)} <= set(_DETAILS)


def test_environment_mismatch_names_both_environments() -> None:
    mismatch = EnvironmentMismatch(order_environment="demo", route_environment="live")
    assert (mismatch.order_environment, mismatch.route_environment) == ("demo", "live")
    assert str(mismatch) == "an order for demo met a route to live (C-2.11)"


def test_the_gates_refusal_keeps_its_reason_and_its_own_detail() -> None:
    """`TradingDisabledProblem`: the gate's `reason` member, and its detail, CandleViewer's own."""
    refused = OrderEntryRefused(_GATE)
    assert (refused.reason, refused.detail, refused.errors) == (
        "maintenance",
        "Order entry is paused for maintenance.",
        (),
    )
    assert isinstance(refused, TradingDisabled) and str(refused) == refused.detail


@pytest.mark.parametrize("code", ["idempotency_in_flight", "stop_request_in_flight"])
def test_place_order_names_each_conflict_it_answers(code: str) -> None:
    assert f"`409 {code}`" in _PLACE_ORDER
