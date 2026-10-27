"""The order routes' problem bodies (E29-T04 #913, slice 3): an OMS refusal as RFC 9457.

`order_problem(error)` renders an `OmsError` with its `oms.errors.PROBLEMS` row (`problem_for`):
the status, the `x-error-codes` slug and its `ERROR_META` title, the refusal's own `detail` and
`errors[]`, `retry_after_seconds` with the `Retry-After` header where the row says so, the
order-entry gate's `reason` (`TradingDisabledProblem`; any other `trading_disabled` is a plain
`Problem`) and a business rejection's `exchange.ret_code` alone (`OrderExchangeProblem`,
SR-E29-09). A row that pages pages the operator and answers the redacted 500, its code and title
only, as does an error no row names, unpaged; an error that is no `OrderRefused` answers its code
and title only too, as its text may name an id. A `500 internal_error` adds its request's
`instance` (`internal_instance`, 22 `InternalError`; CG11). `outcome_problem(outcome)` renders a
recorded 429 or 502 (`SubmitOutcome`): `Retry-After` on a first 429 only (22 `placeOrder`), a
502's return code alone. The repeat of either answers `Idempotency-Replayed: true` (22,
Idempotency), and a repeated 429, which is not retryable under its key, says to send the order
again under a new one.

A plain module, like `api/exchange_keys.py`'s problems, with no router (the composition guard
fails an `api` module whose router `create_app` leaves out): slice 3's route calls it. Every
`detail` is CandleViewer's own fixed text (`oms.errors`): never the exchange's, an id or a secret
(C-12.6).
"""

from __future__ import annotations

from typing import Any, Final

import structlog
from fastapi.responses import JSONResponse

from candleviewer.observability.context import current_request_uuid
from candleviewer.oms.errors import (
    INTERNAL_ERROR,
    PROBLEMS,
    ExchangeRejected,
    OmsError,
    OrderEntryRefused,
    OrderRefused,
    Problem,
    RateBudgetExceeded,
    problem_for,
)
from candleviewer.oms.submit import SubmitOutcome
from candleviewer.statechart.plugins import LogPager, Pager
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode

__all__ = ["internal_instance", "order_problem", "outcome_problem"]

_MEDIA: Final = "application/problem+json"
_TYPE: Final = "https://candleviewer.local/errors/"


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def order_problem(error: OmsError, *, pager: Pager | None = None) -> JSONResponse:
    """`error`'s problem (module docstring); a row that pages pages first, on `pager`."""
    problem = problem_for(error)
    if problem.pages:
        _page(pager if pager is not None else LogPager(), error)
    if not isinstance(error, OrderRefused) or problem.code == INTERNAL_ERROR.code:
        return _response(problem)
    errors = [{"field": e.field, "rule": e.rule, "message": e.message} for e in error.errors]
    return _response(
        problem,
        detail=error.detail,
        errors=errors or None,
        retry_after_seconds=_retry_after_s(error) if problem.retry_after else None,
        reason=error.reason if isinstance(error, OrderEntryRefused) else None,
        exchange=_exchange(error),
    )


def internal_instance(code: str) -> str | None:
    """A `500 internal_error`'s `instance` (22 `InternalError`; CG11, the orchestrator's ruling of
    2026-10-26 19:24Z): `urn:cv:req:{id}`, the id `CorrelationMiddleware` bound for the request,
    which `X-Correlation-Id` echoes and the logs carry, so the answer names its request. Any other
    code carries none (`instance` on every problem answer is post-GA), nor does a `500` outside a
    request, where no id is bound."""
    request_id = current_request_uuid() if code == INTERNAL_ERROR.code else None
    return None if request_id is None else f"urn:cv:req:{request_id}"


def outcome_problem(outcome: SubmitOutcome) -> JSONResponse:
    """A recorded 429 or 502 (module docstring); a 202 is an acceptance, never a problem."""
    if outcome.status == 429:
        rate = PROBLEMS[RateBudgetExceeded]
        if outcome.replayed:  # recorded under the key: no `Retry-After`, a new key is the way on
            return _response(rate, replayed=True, detail=RateBudgetExceeded.replayed_detail)
        detail = RateBudgetExceeded.default_detail
        return _response(rate, detail=detail, retry_after_seconds=outcome.retry_after_s)
    if outcome.status == 502:
        exchange = None if outcome.ret_code is None else {"ret_code": outcome.ret_code}
        rejected = PROBLEMS[ExchangeRejected]
        return _response(
            rejected,
            replayed=outcome.replayed,
            detail=ExchangeRejected.default_detail,
            exchange=exchange,
        )
    raise ValueError("a 202 is an acceptance, never a problem")


def _response(problem: Problem, *, replayed: bool = False, **members: object) -> JSONResponse:
    """The body of `problem`'s code with each member that is set and, on an `internal_error`, its
    request's `instance` (`internal_instance`); `retry_after_seconds` sets the `Retry-After`
    header too, and a repeat of a recorded answer `Idempotency-Replayed: true`."""
    code = problem.code
    body: dict[str, object] = {
        "type": f"{_TYPE}{code}",
        "title": ERROR_META[ErrorCode(code)].title,
        "status": problem.status,
        "code": code,
    }
    body |= {name: value for name, value in members.items() if value is not None}
    if (instance := internal_instance(code)) is not None:
        body["instance"] = instance
    retry = members.get("retry_after_seconds")
    headers = {} if retry is None else {"Retry-After": str(retry)}
    if replayed:
        headers["Idempotency-Replayed"] = "true"
    return JSONResponse(body, problem.status, headers, media_type=_MEDIA)


def _retry_after_s(error: OrderRefused) -> int | None:
    """The `Retry-After` a refusal holds when its row carries one (`retry_after_s`, `PROBLEMS`)."""
    delay = getattr(error, "retry_after_s", None)
    return delay if type(delay) is int else None


def _exchange(error: OrderRefused) -> dict[str, int] | None:
    """A business rejection's `exchange` member: the return code alone, never the exchange's text
    (SR-E29-09)."""
    if isinstance(error, ExchangeRejected) and error.ret_code is not None:
        return {"ret_code": error.ret_code}
    return None


def _page(pager: Pager, error: OmsError) -> None:
    """An invariant broken (`Problem.pages`): paged by the error's class alone. The pager is a
    synchronous sink; one that raises is logged, never the answer."""
    summary = f"oms_order_fault:{type(error).__name__}"
    try:
        pager.raise_alert("page", summary, machine_kind="order")
    except Exception as exc:
        _log().critical("oms_pager_failed", summary=summary, failure=type(exc).__name__)
