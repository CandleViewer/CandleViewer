"""The order routes' problem bodies (E29-T04 #913, slice 3; `api.order_problems`).

Every row of `oms.errors.PROBLEMS` is rendered and validated with jsonschema against the schema 22
declares for its status on the order routes, as `tests/contract/test_order_contract_t04.py`
validates; then each member the renderer's docstring names, the paging and the redaction, and a
recorded 429 or 502 as a first answer and as a repeat.
"""

from __future__ import annotations

import json
from typing import Any, Literal
from uuid import uuid4

import pytest
from fastapi.responses import JSONResponse
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from structlog.testing import capture_logs

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.order_problems import order_problem, outcome_problem
from candleviewer.domain.order_entry import OrderEntryRefusal
from candleviewer.oms.errors import (
    PROBLEMS,
    AccountScopeDenied,
    AuditNotDurable,
    ClockDriftBlocked,
    DuplicateOrderLinkId,
    EnvironmentMismatch,
    ExchangeRejected,
    ExchangeUnavailable,
    FieldError,
    IdempotencyInFlight,
    IdempotencyKeyReuse,
    LotSizeViolation,
    OmsError,
    OrderEntryRefused,
    OrderInvalid,
    OrderLinkIdExhausted,
    OrderMachinesFull,
    OrderNotAmendable,
    OrderNotFound,
    OrderRefused,
    ProfileNotFound,
    RateBudgetExceeded,
    RiskRefused,
    SessionNotArmed,
    StopRequestPending,
    StoreUnavailable,
    TickSizeViolation,
    TradingDisabled,
    VersionConflict,
)
from candleviewer.oms.submit import SubmitOutcome
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode
from tests.openapi_helpers import deref

_SPEC: Any = load_openapi_spec()  # a parsed YAML document, walked untyped
_CODES: dict[str, Any] = {entry["code"]: entry for entry in _SPEC["x-error-codes"]}
_OPS: dict[str, Any] = {
    op["operationId"]: op
    for item in _SPEC["paths"].values()
    for op in item.values()
    if isinstance(op, dict) and "operationId" in op
}
_GATE = OrderEntryRefusal("maintenance", "Order entry is paused for maintenance.")
_FIRST, _LAST = "cvd-0MduI3fiqJ6h0wkltsuR4U-JelO-00en", "cvd-0MduI3fiqJ6h0wkltsuR4U-JelO-zzen"
_REDACTED = {"type", "title", "status", "code"}

#: One error of each class `PROBLEMS` names, as the order path raises it.
_ROWS: dict[type[OmsError], OmsError] = {
    OrderInvalid: OrderInvalid(errors=(FieldError("stop_loss", "native_stop_required", "No."),)),
    TickSizeViolation: TickSizeViolation(),
    LotSizeViolation: LotSizeViolation(),
    AccountScopeDenied: AccountScopeDenied(),
    RiskRefused: RiskRefused(),
    TradingDisabled: TradingDisabled(),
    SessionNotArmed: SessionNotArmed(),
    OrderNotFound: OrderNotFound(),
    ProfileNotFound: ProfileNotFound(),
    IdempotencyKeyReuse: IdempotencyKeyReuse(),
    IdempotencyInFlight: IdempotencyInFlight(retry_after_s=1),
    StopRequestPending: StopRequestPending(retry_after_s=5),
    VersionConflict: VersionConflict(),
    OrderNotAmendable: OrderNotAmendable(),
    RateBudgetExceeded: RateBudgetExceeded(retry_after_s=2),
    OrderLinkIdExhausted: OrderLinkIdExhausted(first=_FIRST, last=_LAST),
    EnvironmentMismatch: EnvironmentMismatch(order_environment="demo", route_environment="live"),
    OrderMachinesFull: OrderMachinesFull("1024 order machines are live"),
    ExchangeRejected: ExchangeRejected(ret_code=110007),
    ClockDriftBlocked: ClockDriftBlocked(retry_after_s=5),
    StoreUnavailable: StoreUnavailable(),
    ExchangeUnavailable: ExchangeUnavailable(retry_after_s=3),
    AuditNotDurable: AuditNotDurable("the order's write-ahead audit did not land"),
}
#: The `Retry-After` each error above holds, for the rows that carry one.
_DELAYS: dict[type[OmsError], int] = {
    IdempotencyInFlight: 1,
    StopRequestPending: 5,
    RateBudgetExceeded: 2,
    ClockDriftBlocked: 5,
    ExchangeUnavailable: 3,
}
_PAGING = [cls for cls, problem in PROBLEMS.items() if problem.pages]


class _Pager:
    """A recording pager; `refuse` raises instead."""

    def __init__(self, *, refuse: bool = False) -> None:
        self.pages: list[tuple[str, str, str]] = []
        self.refuse = refuse

    def raise_alert(self, severity: str, summary: str, *, machine_kind: str) -> None:
        if self.refuse:
            raise RuntimeError("the pager is down")
        self.pages.append((severity, summary, machine_kind))


def _body(response: JSONResponse) -> dict[str, Any]:
    assert response.media_type == "application/problem+json"
    body: dict[str, Any] = json.loads(bytes(response.body))
    return body


def _validate(schema: Any, body: object) -> None:
    Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER).validate(body)


def _component(name: str) -> Any:
    return deref(_SPEC, {"$ref": f"#/components/schemas/{name}"})


def _schema(status: int) -> Any:
    """The problem schema 22 declares for `status` on `placeOrder`, else on `amendOrder`."""
    for operation in ("placeOrder", "amendOrder"):
        declared = _OPS[operation]["responses"].get(str(status))
        if declared is not None:
            return deref(_SPEC, declared)["content"]["application/problem+json"]["schema"]
    raise AssertionError(f"no order route declares {status}")


def _outcome(status: Literal[429, 502], **fields: Any) -> SubmitOutcome:
    """A recorded 429 or 502 of an order with no group."""
    code = {429: "exchange_rate_limited", 502: "exchange_error"}[status]
    return SubmitOutcome(status, uuid4(), uuid4(), None, "rejected", code, **fields)


def test_every_row_of_the_table_is_rendered_here() -> None:
    assert set(_ROWS) == set(PROBLEMS)
    assert set(_DELAYS) == {cls for cls, problem in PROBLEMS.items() if problem.retry_after}


@pytest.mark.parametrize("cls", list(_ROWS), ids=[cls.__name__ for cls in _ROWS])
def test_each_row_renders_a_body_its_22_schema_takes(cls: type[OmsError]) -> None:
    """The status, the code, its type and its registry title, valid against the schema the order
    routes declare for that status; only a row that pages pages."""
    problem, pager = PROBLEMS[cls], _Pager()
    response = order_problem(_ROWS[cls], pager=pager)
    body = _body(response)
    _validate(_schema(problem.status), body)
    assert (response.status_code, body["status"], body["code"]) == (
        problem.status, problem.status, problem.code,
    )  # fmt: skip
    assert body["type"] == f"https://candleviewer.local/errors/{problem.code}"
    title = ERROR_META[ErrorCode(problem.code)].title
    assert body["title"] == title == _CODES[problem.code]["title"]
    assert len(pager.pages) == int(problem.pages)


@pytest.mark.parametrize("cls", list(_ROWS), ids=[cls.__name__ for cls in _ROWS])
def test_retry_after_is_in_the_body_and_the_header_where_the_row_says_so(
    cls: type[OmsError],
) -> None:
    response = order_problem(_ROWS[cls], pager=_Pager())
    delay = _DELAYS.get(cls)
    assert _body(response).get("retry_after_seconds") == delay
    assert response.headers.get("retry-after") == (None if delay is None else str(delay))


def test_a_refusal_carries_its_own_detail_and_every_rule_that_failed() -> None:
    errors = (
        FieldError("stop_loss", "native_stop_required", "No stop."),
        FieldError("intent", "intent_mismatch", "Wrong intent."),
    )
    body = _body(order_problem(OrderInvalid("2 rules failed.", errors=errors)))
    assert body["detail"] == "2 rules failed."
    assert body["errors"] == [
        {"field": "stop_loss", "rule": "native_stop_required", "message": "No stop."},
        {"field": "intent", "rule": "intent_mismatch", "message": "Wrong intent."},
    ]
    assert "errors" not in _body(order_problem(RiskRefused()))


def test_the_gates_refusal_is_a_trading_disabled_problem_with_its_reason() -> None:
    body = _body(order_problem(OrderEntryRefused(_GATE)))
    _validate(_component("TradingDisabledProblem"), body)
    assert (body["reason"], body["detail"]) == ("maintenance", _GATE.detail)


def test_any_other_trading_disabled_refusal_is_a_plain_problem_with_no_reason() -> None:
    body = _body(order_problem(TradingDisabled()))
    assert "reason" not in body
    with pytest.raises(ValidationError, match="'reason' is a required property"):
        _validate(_component("TradingDisabledProblem"), body)


@pytest.mark.parametrize(("ret_code", "exchange"), [(110007, {"ret_code": 110007}), (None, None)])
def test_a_business_rejection_carries_the_return_code_alone(
    ret_code: int | None, exchange: dict[str, int] | None
) -> None:
    """SR-E29-09: `OrderExchangeProblem` refuses any other `exchange` member."""
    body = _body(order_problem(ExchangeRejected(ret_code=ret_code)))
    _validate(_component("OrderExchangeProblem"), body)
    assert body.get("exchange") == exchange


@pytest.mark.parametrize("cls", _PAGING, ids=[cls.__name__ for cls in _PAGING])
def test_a_row_that_pages_pages_once_and_answers_the_redacted_500(cls: type[OmsError]) -> None:
    """An invariant broken: paged by the error's class alone, and nothing of its text, which may
    name an id or an environment, reaches the body."""
    pager, error = _Pager(), _ROWS[cls]
    response = order_problem(error, pager=pager)
    assert pager.pages == [("page", f"oms_order_fault:{cls.__name__}", "order")]
    assert (response.status_code, set(_body(response))) == (500, _REDACTED)
    assert str(error) not in bytes(response.body).decode()


@pytest.mark.parametrize(
    "error",
    [
        OmsError("the first persist refused the order's own rows"),
        DuplicateOrderLinkId(_FIRST),
        OrderRefused("A refusal no row names."),
    ],
    ids=["oms_error", "duplicate_id", "unmapped_refusal"],
)
def test_an_error_no_row_names_is_the_redacted_500_unpaged(error: OmsError) -> None:
    pager = _Pager()
    response = order_problem(error, pager=pager)
    body = _body(response)
    _validate(_schema(500), body)
    assert (response.status_code, set(body), pager.pages) == (500, _REDACTED, [])


def test_an_error_that_is_no_refusal_answers_its_code_and_title_only() -> None:
    body = _body(order_problem(AuditNotDurable("the order's write-ahead audit did not land")))
    assert (body["status"], set(body)) == (503, _REDACTED)


def test_a_pager_that_fails_is_logged_never_the_answer() -> None:
    with capture_logs() as logs:
        response = order_problem(_ROWS[OrderMachinesFull], pager=_Pager(refuse=True))
    assert response.status_code == 500
    assert any(line["event"] == "oms_pager_failed" for line in logs)


def test_with_no_pager_given_a_row_that_pages_pages_through_the_log() -> None:
    with capture_logs() as logs:
        order_problem(_ROWS[OrderMachinesFull])
    pages = [line["summary"] for line in logs if line.get("cv_page") is True]
    assert pages == ["oms_order_fault:OrderMachinesFull"]


def test_a_first_429_renders_as_the_refusal_before_the_persist_does() -> None:
    """The recorded first 429 carries its `Retry-After`, as a refused headroom read's does."""
    response = outcome_problem(_outcome(429, retry_after_s=3))
    assert bytes(response.body) == bytes(order_problem(RateBudgetExceeded(retry_after_s=3)).body)
    assert response.headers["retry-after"] == "3"


def test_a_repeated_429_is_not_retryable_under_its_key_and_says_to_use_a_new_one() -> None:
    """22 `placeOrder`: the 429 at the send is recorded under its key, so the repeat carries no
    `Retry-After`, in the header or the body, and its detail names the way on, a new key, rather
    than telling the client to retry."""
    response = outcome_problem(_outcome(429, replayed=True))
    body = _body(response)
    _validate(_schema(429), body)
    assert "retry_after_seconds" not in body and "retry-after" not in response.headers
    assert body["detail"] == RateBudgetExceeded.replayed_detail != RateBudgetExceeded.default_detail
    assert "new Idempotency-Key" in body["detail"] and "retry" not in body["detail"].lower()


@pytest.mark.parametrize("ret_code", [110007, None])
def test_a_recorded_502_renders_as_the_business_rejection_does(ret_code: int | None) -> None:
    response = outcome_problem(_outcome(502, ret_code=ret_code))
    assert bytes(response.body) == bytes(order_problem(ExchangeRejected(ret_code=ret_code)).body)


@pytest.mark.parametrize(
    ("status", "fields"),
    [(429, {"retry_after_s": 3}), (502, {"ret_code": 110007})],
    ids=["429", "502"],
)
def test_a_first_answer_is_no_replay(status: Literal[429, 502], fields: dict[str, Any]) -> None:
    assert "idempotency-replayed" not in outcome_problem(_outcome(status, **fields)).headers


@pytest.mark.parametrize(
    ("status", "fields"),
    [(429, {}), (502, {"ret_code": 110007}), (502, {})],
    ids=["429", "502", "502_no_ret_code"],
)
def test_a_repeated_429_or_502_says_it_is_a_replay_and_has_no_retry_after(
    status: Literal[429, 502], fields: dict[str, Any]
) -> None:
    """22 (Idempotency, `placeOrder`): the 429 and the 502 a request recorded are replayed from
    the anchor with `Idempotency-Replayed: true` and no `Retry-After`."""
    response = outcome_problem(_outcome(status, **fields, replayed=True))
    _validate(_schema(status), _body(response))
    assert response.headers["idempotency-replayed"] == "true"
    assert "retry-after" not in response.headers


@pytest.mark.parametrize("ret_code", [110007, None])
def test_a_repeated_502_is_its_first_answers_body(ret_code: int | None) -> None:
    first = outcome_problem(_outcome(502, ret_code=ret_code))
    repeat = outcome_problem(_outcome(502, ret_code=ret_code, replayed=True))
    assert bytes(repeat.body) == bytes(first.body)


def test_an_acceptance_is_never_a_problem() -> None:
    with pytest.raises(ValueError, match="never a problem"):
        outcome_problem(SubmitOutcome(202, uuid4(), uuid4(), None, "submitted"))
