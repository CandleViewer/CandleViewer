"""The exit routes' shared steps (E29-T04 #913 slice 4; 24-internal-schemas.md Sec.8.4 "The exit
routes").

`DELETE` / `PATCH /orders/{orderId}` (`api/order_exits.py`) and `POST /orders/cancel-all`
(`api/order_cancel_all.py`) each take these from here, so neither writes them again (the
orchestrator's ruling of 2026-10-24 19:43Z):

- `exit_caller`: who asks, as the exit service takes it (`oms.exits.ExitCaller`): the accounts the
  principal reaches, its records' actor and the request's correlation id;
- `exit_refusals`: `oms_exit_refused_total{operation,code}` (20 Sec.12.1, ruling Q14), the one
  counter every exit refusal is counted in, the unaudited `501` and `oms_not_ready` included;
- `run_claimed`: step 9's in-flight guard around step 11's run. The principal's key is claimed for
  the operation, or the guard's refusal (`409 idempotency_in_flight`, `429 rate_limited`, each
  with `Retry-After: 1`) goes to the caller's `refused`, which records it before it is answered
  (C-2.9). A claimed exit runs as the runtime's tracked task, shielded from the client's
  disconnect, and the claim is released when that task ends, never when the request does. A
  fault the exit raises is the caller's `faulted` answer, given in that task, so a fault is
  answered, paged and counted even once its client left; a `faulted` that raises too is the
  last resort's redacted `500`, logged CRITICAL by the two classes alone and marked as a page
  (`cv_page`, the log pager's mark), never an unanswered task (SEC-S4D2A-04);
- `exit_problem` and `exit_response`: an exit's answer as the exit service's `ExitOutcome` gives
  it, a refusal's 22 problem or the `202` with the order as the exit left it;
- `exit_fault`: the answer to a fault no outcome answers (the orchestrator's ruling of 2026-10-25
  02:50Z (2)). Every exit `500` pages, once: a fault whose problem row pages is paged by that row
  (`api.order_problems`), and any other, an `OmsError` whose row does not page or an error that
  is no `OmsError`, renders the redacted `500 internal_error` and pages the exit routes' one page
  for its class, `EXIT_FAULT_PAGE` and the class's name, never the fault's text. The page is the
  same for every fault of a class, so the pager's alerting folds the repeats of a class into the
  one it holds; `LogPager` keeps none itself, each fault its `cv_page` line. An `OmsError` whose
  row is a 4xx or a 503 escaped the exit service, which records every refusal it answers: its
  row's problem, unaudited and unpaged, logged `oms_exit_refusal_escaped` by its class alone so
  it is told apart from a recorded refusal (SEC-S4D2A-02).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from typing import Any, Final, Protocol, cast

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse, Response

from candleviewer.api.order_acceptance import order_body
from candleviewer.api.order_admission import submit_actor
from candleviewer.api.order_principal import TradingPrincipal
from candleviewer.api.order_problems import order_problem
from candleviewer.auth.scopes import account_scope
from candleviewer.domain.primitives import Environment
from candleviewer.observability.context import current_request_uuid
from candleviewer.observability.metrics import BoundedMetric, Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.oms.errors import INTERNAL_ERROR, OmsError, problem_for
from candleviewer.oms.exits import ExitCaller, ExitOperation, ExitOutcome, InFlightGuard
from candleviewer.statechart.plugins import Pager
from candleviewer.storage.repositories.orders import ORDER_STATE_OF, ScopedOrder
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode

__all__ = [
    "EXIT_FAULT_PAGE", "EXIT_REFUSED_METRIC", "ExitRuntime", "exit_caller", "exit_fault",
    "exit_problem", "exit_refusals", "exit_response", "run_claimed",
]  # fmt: skip

EXIT_REFUSED_METRIC: Final = "oms_exit_refused_total"
#: The exit routes' one page for an unexpected exit failure: this key and the fault's class (the
#: orchestrator's ruling of 2026-10-25 02:50Z (2); `exit_fault`).
EXIT_FAULT_PAGE: Final = "oms_exit_unexpected_failure"
_STORED: Final = cast(Mapping[str, str], ORDER_STATE_OF)
_MEDIA: Final = "application/problem+json"
#: The redacted `500` (22 `InternalError`): its code and its title alone.
_FAULT: Final = ExitOutcome(kind="refused", status=INTERNAL_ERROR.status, code=INTERNAL_ERROR.code)


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class _Exits(Protocol):
    @property
    def guard(self) -> InFlightGuard: ...


class ExitRuntime(Protocol):
    """`oms_wiring.OmsRuntime` as the exit routes run an exit on it."""

    @property
    def exits(self) -> _Exits: ...

    def run(self, coro: Coroutine[Any, Any, Response]) -> asyncio.Task[Response]: ...


def exit_refusals(metrics: Metrics) -> BoundedMetric:
    """`oms_exit_refused_total`, labelled `operation` then `code`, as the catalogue declares it:
    every exit router takes the same counter (a repeated, identical registration returns it)."""
    spec = next(spec for spec in CATALOGUE if spec.name == EXIT_REFUSED_METRIC)
    return metrics.counter(spec.name, spec.help, spec.labels, max_series=spec.max_series)


def exit_caller(principal: TradingPrincipal, request: Request) -> ExitCaller:
    """The exit service's caller: the principal's accounts (`auth.scopes.account_scope`), its
    records' actor (`submit_actor`) and the request's correlation id."""
    return ExitCaller(
        scope=account_scope(principal.snapshot),
        actor=submit_actor(principal, request),
        request_id=current_request_uuid(),
    )


async def run_claimed(
    oms: ExitRuntime,
    user_id: uuid.UUID,
    operation: ExitOperation,
    key: uuid.UUID,
    make: Callable[[], Coroutine[Any, Any, Response]],
    *,
    refused: Callable[[ExitOutcome], Awaitable[Response]],
    faulted: Callable[[Exception], Response],
) -> Response:
    """The exit `make()` builds, under the in-flight guard's claim of the principal's `key` for
    `operation` (module docstring): a refusal is `refused(outcome)`'s answer, nothing run; a fault
    the exit raises is `faulted(error)`'s, in the exit's own task; a runtime that refuses the run
    (`OmsNotReady`, its stop begun) releases the claim and raises."""
    claimed = oms.exits.guard.claim(user_id, operation, key)
    if isinstance(claimed, ExitOutcome):
        return await refused(claimed)
    release = claimed
    try:
        task = oms.run(_fault_answered(make, faulted))  # a refused run closes the coroutine itself
    except BaseException:
        release()
        raise
    task.add_done_callback(lambda _done: release())
    return await asyncio.shield(task)


async def _fault_answered(
    make: Callable[[], Coroutine[Any, Any, Response]], faulted: Callable[[Exception], Response]
) -> Response:
    """The claimed exit, built here so a run the runtime refused leaves nothing unawaited: its
    answer, or `faulted`'s for a fault it raises; a cancellation goes on. A `faulted` that raises
    too is the last resort's redacted `500` (module docstring)."""
    try:
        return await make()
    except Exception as exc:  # a fault no outcome answered: the route's answer, in this task
        try:
            return faulted(exc)
        except Exception as failed:  # the last resort: its 500, paged by the classes alone
            _log().critical(
                "oms_exit_fault_answer_failed", fault=type(exc).__name__,
                failure=type(failed).__name__, cv_page=True,
            )  # fmt: skip
            return exit_problem(_FAULT)


def exit_problem(outcome: ExitOutcome) -> JSONResponse:
    """A refused exit's 22 problem, in `api.order_problems`' shape: its code's title, the
    service's own `detail` and `errors[]`, `retry_after_seconds` with `Retry-After` where the
    outcome holds one, the order-entry gate's `reason`, and a venue refusal's `exchange.ret_code`
    alone, never its text (SR-E29-09)."""
    code, ret = outcome.code or "internal_error", outcome.exchange_ret_code
    errors = [{"field": e.field, "rule": e.rule, "message": e.message} for e in outcome.errors]
    members: dict[str, object] = {
        "type": f"https://candleviewer.local/errors/{code}",
        "title": ERROR_META[ErrorCode(code)].title, "status": outcome.status, "code": code,
        "detail": outcome.detail, "errors": errors or None,
        "retry_after_seconds": outcome.retry_after_s, "reason": outcome.reason,
        "exchange": None if ret is None else {"ret_code": ret},
    }  # fmt: skip
    body = {name: value for name, value in members.items() if value is not None}
    retry = outcome.retry_after_s
    headers = {} if retry is None else {"Retry-After": str(retry)}
    return JSONResponse(body, outcome.status, headers, media_type=_MEDIA)


def exit_fault(error: Exception, *, pager: Pager) -> tuple[str, JSONResponse]:
    """A fault an exit route met that no outcome answers, as the code it is counted under and its
    22 problem (module docstring): an `OmsError` whose row is no `500`, or pages, is its row's
    problem (`order_problem`, its row's own page on `pager`), one whose row does not page logged
    `oms_exit_refusal_escaped` by its class (SEC-S4D2A-02); any other is the redacted `500
    internal_error`, logged by its class with its traceback (the redaction filter renders it, as
    the app's own `500` handler does) and paged on `pager`, `EXIT_FAULT_PAGE` and its class's name;
    a pager that raises is logged, never the answer."""
    problem = problem_for(error) if isinstance(error, OmsError) else INTERNAL_ERROR
    if isinstance(error, OmsError) and (problem.pages or problem.status != INTERNAL_ERROR.status):
        if not problem.pages:  # a refusal past the exit service, which records its own: unaudited
            _log().warning("oms_exit_refusal_escaped", failure=type(error).__name__)
        return problem.code, order_problem(error, pager=pager)
    failure = type(error).__name__
    _log().error(EXIT_FAULT_PAGE, failure=failure, exc_info=error)
    summary = f"{EXIT_FAULT_PAGE}:{failure}"
    try:
        pager.raise_alert("page", summary, machine_kind="order")
    except Exception as exc:  # the page is lost, never the answer
        _log().critical("oms_pager_failed", summary=summary, failure=type(exc).__name__)
    answer = order_problem(error) if isinstance(error, OmsError) else exit_problem(_FAULT)
    return problem.code, answer


def exit_response(outcome: ExitOutcome, scoped: ScopedOrder, env: Environment) -> Response:
    """22 `cancelOrder`'s answer to an admitted exit: a refusal's problem (`exit_problem`), else
    `202` with the order (`order_body`) as the exit left it, `unknown` too: its row read again, in
    the state B1's step settled, in its trade group and environment."""
    if outcome.kind == "refused":
        return exit_problem(outcome)
    row = scoped.order if outcome.row is None else outcome.row
    chart = outcome.lifecycle_state or row.lifecycle_state
    state = row.state if chart is None else _STORED.get(chart, row.state)
    return JSONResponse(order_body(row, scoped.trade_group_id, env, state, chart), 202)
