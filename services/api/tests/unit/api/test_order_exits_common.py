"""E29-T04 (#913) slice 4: the exit routes' shared steps (`api/order_exits_common.py`, the
orchestrator's ruling of 2026-10-24 19:43Z): `exit_caller`, `run_claimed`'s in-flight guard around
the exit's run (24 Sec.8.4 steps 9 and 11) on the real `InFlightGuard`, the runtime a fake that
tracks the run as `OmsRuntime.run` does, and `exit_fault`, the shared renderer's answer to a fault,
each exit `500` paged (the ruling of 2026-10-25 02:50Z (2)), with the Fable lens's SEC-S4D2A-02
and -04 (a refusal raised past the exit service, logged; a fault's answer that raises, the last
resort's `500`). Nothing sleeps: an exit is held open on an event."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from fastapi.responses import JSONResponse, Response
from starlette.requests import Request
from structlog.testing import capture_logs

import candleviewer
from candleviewer.api import order_exits_common as common
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.order_exits_common import exit_caller, exit_refusals, run_claimed
from candleviewer.api.order_principal import TradingPrincipal
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.observability.context import bind_context
from candleviewer.observability.metrics import Metrics
from candleviewer.oms.errors import (
    OmsError,
    OmsNotReady,
    OrderHistoryRefused,
    OrderMachinesFull,
    OrderNotFound,
    StoreUnavailable,
    problem_for,
)
from candleviewer.oms.exits import ExitOutcome, InFlightGuard
from candleviewer.storage.repositories.accounts import GrantScope, OwnerScope

USER, KEY = uuid.uuid4(), uuid.uuid4()


@dataclass
class _Exits:
    guard: InFlightGuard = field(default_factory=InFlightGuard)


@dataclass
class _Runtime:
    """`OmsRuntime.run` as the routes see it: a tracked task, or, the coroutine closed, what it
    raises instead (`refuse`): `OmsNotReady` once its stop has begun, a `RuntimeError` on another
    loop than the one that started it (CR-S3C2-01)."""

    exits: _Exits = field(default_factory=_Exits)
    refuse: BaseException | None = None
    tasks: list[asyncio.Task[Response]] = field(default_factory=list)

    def run(self, coro: Coroutine[Any, Any, Response]) -> asyncio.Task[Response]:
        if self.refuse is not None:
            coro.close()
            raise self.refuse
        task = asyncio.get_running_loop().create_task(coro)
        self.tasks.append(task)
        return task


def _held(oms: _Runtime) -> bool:
    """Whether the principal's key is held for `cancel` (a fresh claim refused as in flight)."""
    again = oms.exits.guard.claim(USER, "cancel", KEY)
    if isinstance(again, ExitOutcome):
        return True
    again()
    return False


async def _never(_outcome: ExitOutcome) -> Response:
    raise AssertionError("a claimed exit is never refused")


def _unfaulted(error: Exception) -> Response:
    raise AssertionError("an exit that answers raises no fault") from error


def _faults(seen: list[Exception]) -> Callable[[Exception], Response]:
    """A route's `faulted`, as `exit_fault` answers, keeping each fault it is handed in `seen`."""

    def faulted(error: Exception) -> Response:
        seen.append(error)
        return JSONResponse({"code": "internal_error"}, 500)

    return faulted


async def test_a_claimed_exit_runs_as_the_runtimes_task_and_releases_when_it_ends() -> None:
    oms, gate = _Runtime(), asyncio.Event()

    async def exit_() -> Response:
        await gate.wait()
        return JSONResponse({"ok": True}, 202)

    answer = asyncio.create_task(
        run_claimed(oms, USER, "cancel", KEY, exit_, refused=_never, faulted=_unfaulted)
    )
    await asyncio.sleep(0)
    assert len(oms.tasks) == 1 and _held(oms)  # held while the exit runs
    gate.set()
    got = await answer
    assert got.status_code == 202 and not _held(oms)  # released with the task's end


async def test_a_refused_claim_answers_through_refused_and_runs_nothing() -> None:
    oms, seen = _Runtime(), list[ExitOutcome]()
    first = oms.exits.guard.claim(USER, "cancel", KEY)
    assert not isinstance(first, ExitOutcome)

    async def refused(outcome: ExitOutcome) -> Response:
        seen.append(outcome)
        return JSONResponse({"code": outcome.code}, outcome.status)

    def make() -> Coroutine[Any, Any, Response]:
        raise AssertionError("a refused claim builds no exit")

    got = await run_claimed(oms, USER, "cancel", KEY, make, refused=refused, faulted=_unfaulted)
    [outcome] = seen
    assert (got.status_code, outcome.code, outcome.retry_after_s) == (
        409, "idempotency_in_flight", 1,
    )  # fmt: skip
    assert oms.tasks == []


async def test_a_cancelled_caller_leaves_the_exit_running_and_its_claim_held_until_it_ends() -> (
    None
):
    """A client that left: the shielded exit goes on, and the key stays claimed until it ends,
    so a repeat meanwhile is in flight (24 Sec.8.4)."""
    oms, gate = _Runtime(), asyncio.Event()

    async def exit_() -> Response:
        await gate.wait()
        return JSONResponse({"ok": True}, 202)

    answer = asyncio.create_task(
        run_claimed(oms, USER, "cancel", KEY, exit_, refused=_never, faulted=_unfaulted)
    )
    await asyncio.sleep(0)
    answer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await answer
    [task] = oms.tasks
    assert not task.done() and _held(oms)
    gate.set()
    assert (await task).status_code == 202
    await asyncio.sleep(0)  # the done-callback's turn
    assert not _held(oms)


@pytest.mark.parametrize(
    "refusal",
    [OmsNotReady(), RuntimeError("the OMS runs on the event loop that started it (CR-S3C2-01)")],
    ids=["stopping", "another_loop"],
)
async def test_a_runtime_that_refuses_the_run_releases_the_claim_and_raises(
    refusal: BaseException,
) -> None:
    """`OmsRuntime.run` refuses with `OmsNotReady` once its stop has begun and with a
    `RuntimeError` on another loop: whatever it raises, the claim is released, nothing run, and
    the error goes on to the route."""
    oms = _Runtime(refuse=refusal)

    async def exit_() -> Response:
        raise AssertionError("never run")

    with pytest.raises(type(refusal)):
        await run_claimed(oms, USER, "cancel", KEY, exit_, refused=_never, faulted=_unfaulted)
    assert not _held(oms) and oms.tasks == []


async def test_a_fault_the_exit_raises_is_faulteds_answer_in_its_task_and_frees_its_key() -> None:
    """A fault the exit does not answer is `faulted`'s answer (the route's, through `exit_fault`),
    given in the exit's own task, which ends all the same: its claim is released with it, and
    nothing goes on to the app's own `500` (the orchestrator's ruling of 2026-10-25 02:50Z (2))."""
    oms, seen = _Runtime(), list[Exception]()

    async def exit_() -> Response:
        raise RuntimeError("a fault the exit did not answer")

    got = await run_claimed(oms, USER, "cancel", KEY, exit_, refused=_never, faulted=_faults(seen))
    [task] = oms.tasks
    assert got.status_code == 500 and [type(error) for error in seen] == [RuntimeError]
    assert task.done() and task.result() is got and not _held(oms)


async def test_a_fault_once_its_caller_left_is_still_answered_in_the_exits_task() -> None:
    """A client that left: the shielded exit goes on, and a fault it raises then is `faulted`'s
    answer all the same, in its task, with no request awaiting it, so it is paged and counted;
    the claim is released as the task ends."""
    oms, gate, seen = _Runtime(), asyncio.Event(), list[Exception]()

    async def exit_() -> Response:
        await gate.wait()
        raise RuntimeError("a fault once the caller left")

    faulted = _faults(seen)
    answer = asyncio.create_task(
        run_claimed(oms, USER, "cancel", KEY, exit_, refused=_never, faulted=faulted)
    )
    await asyncio.sleep(0)
    answer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await answer
    [task] = oms.tasks
    gate.set()
    assert (await task).status_code == 500 and [type(error) for error in seen] == [RuntimeError]
    await asyncio.sleep(0)  # the done-callback's turn
    assert not _held(oms)


async def test_an_exit_the_runtimes_stop_cancels_releases_its_claim() -> None:
    """`OmsRuntime.stop()` cancels the exits its drain left running: each claim is released as its
    task ends, so a stopped runtime's guard holds no key."""
    oms, gate = _Runtime(), asyncio.Event()

    async def exit_() -> Response:
        await gate.wait()
        return JSONResponse({"ok": True}, 202)

    answer = asyncio.create_task(
        run_claimed(oms, USER, "cancel", KEY, exit_, refused=_never, faulted=_unfaulted)
    )
    await asyncio.sleep(0)
    [task] = oms.tasks
    task.cancel()  # as `stop()` cancels what its drain left
    with pytest.raises(asyncio.CancelledError):
        await answer
    assert task.cancelled() and not _held(oms)


@pytest.mark.parametrize("owner", [True, False], ids=["owner", "manager"])
def test_exit_caller_takes_the_principals_scope_actor_and_request_id(owner: bool) -> None:
    roles = frozenset({"owner"} if owner else {"manager"})
    principal = TradingPrincipal(uuid.uuid4(), PrincipalSnapshot(USER, roles, frozenset()))
    request = Request({"type": "http", "headers": [], "client": ("192.0.2.7", 4321)})
    request_id = uuid.uuid4()
    with bind_context(request_id=request_id):
        caller = exit_caller(principal, request)
    assert isinstance(caller.scope, OwnerScope if owner else GrantScope)
    assert (caller.actor.user_id, caller.actor.session_id) == (USER, principal.session_id)
    assert caller.actor.role == ",".join(sorted(roles))
    assert caller.request_id == request_id


def test_exit_refusals_is_the_catalogues_counter_one_for_every_router() -> None:
    """Ruling Q14: one `oms_exit_refused_total{operation,code}`, which D1's and cancel-all's
    routers both count through; a second router's call returns the same counter."""
    metrics = Metrics("demo")
    first, again = exit_refusals(metrics), exit_refusals(metrics)
    assert first is again
    first.labels("cancel", "conflict").inc()
    labels = {"env": "demo", "operation": "cancel", "code": "conflict"}
    assert metrics.registry.get_sample_value("oms_exit_refused_total", labels) == 1


def test_exit_refusals_keeps_the_catalogues_66_series_then_breaches() -> None:
    """The counter takes the catalogue's `max_series`, 66 (`operation` by `code`): every series up
    to it is kept, so no exit's refusal is dropped early, and the next one is the cardinality
    guard's breach, a no-op, never a raise."""
    counter = exit_refusals(Metrics("demo"))
    for n in range(66):
        counter.labels(("amend", "cancel", "cancel_all")[n % 3], f"code_{n}").inc()
    assert (counter.series_count, counter.breached) == (66, False)
    counter.labels("cancel", "one_more").inc()
    assert (counter.series_count, counter.breached) == (66, True)


def test_run_claimed_is_the_in_flight_guards_one_claimer() -> None:
    """SEC-S4C2A-01: a claim has no deadline, so the guard's 1,024 / 64 bounds hold only while
    every claim is released at its exit's end, which `run_claimed` does on every path (the tests
    above). No other module reaches the guard; a new caller is reviewed here first. The order
    lane's `OnLaneExits.guard` (`oms_wiring.py`) forwards the guard to `run_claimed` in place, on
    the serving loop, and never claims or releases it."""
    pkg = Path(candleviewer.__file__).resolve().parent
    reach = re.compile(r"\.guard\.claim\(|\bexits\.guard\b")
    users = {
        p.relative_to(pkg).as_posix()
        for p in pkg.rglob("*.py")
        if reach.search(p.read_text(encoding="utf-8"))
    }
    assert users == {"api/order_exits_common.py", "oms_wiring.py"}


class _Pager:
    """A recording pager; `refuse` raises instead."""

    def __init__(self, *, refuse: bool = False) -> None:
        self.pages: list[tuple[str, str, str]] = []
        self.refuse = refuse

    def raise_alert(self, severity: str, summary: str, *, machine_kind: str) -> None:
        if self.refuse:
            raise RuntimeError("the pager is down")
        self.pages.append((severity, summary, machine_kind))


_SPEC: Any = load_openapi_spec()  # a parsed YAML document, walked untyped
#: 22's `InternalError` example: the redacted `500` its text says every exit route answers.
[_FAULT_BODY] = [
    shown["value"]
    for shown in _SPEC["components"]["responses"]["InternalError"]["content"][
        "application/problem+json"
    ]["examples"].values()
]
_TEXT = "a defect naming order 0a000000-0000-4000-8000-000000000003"


@pytest.mark.parametrize(
    ("error", "page"),
    [
        (OrderHistoryRefused(_TEXT), "oms_exit_unexpected_failure:OrderHistoryRefused"),
        (RuntimeError(_TEXT), "oms_exit_unexpected_failure:RuntimeError"),
        (OrderMachinesFull(_TEXT), "oms_order_fault:OrderMachinesFull"),
    ],
    ids=["no-row", "no-oms-error", "a-row-that-pages"],
)
def test_every_exit_500_is_the_redacted_500_paged_once_by_its_class(
    error: Exception, page: str
) -> None:
    """The orchestrator's ruling of 2026-10-25 02:50Z (2): a fault no outcome answers is 22's
    redacted `500 internal_error`, and it pages once, by its class alone and never its text: a row
    that pages with its own page (`order_problem`'s) and no other, any other fault, an `OmsError`
    no row pages or an error that is no `OmsError`, with the exit routes' one page."""
    pager = _Pager()
    code, answer = common.exit_fault(error, pager=pager)
    assert (code, answer.status_code, answer.media_type) == (
        "internal_error", 500, "application/problem+json",
    )  # fmt: skip
    assert json.loads(bytes(answer.body)) == _FAULT_BODY and "retry-after" not in answer.headers
    assert pager.pages == [("page", page, "order")]
    assert _TEXT not in bytes(answer.body).decode() and _TEXT not in page


def test_the_exit_routes_page_is_its_key_and_the_faults_class() -> None:
    assert common.EXIT_FAULT_PAGE == "oms_exit_unexpected_failure"


def test_a_refusal_raised_as_an_error_is_its_rows_problem_and_pages_nothing() -> None:
    """An `OmsError` whose row is no `500` is no fault: its row's problem, as `order_problem`
    renders it, counted under its own code, and no page."""
    pager = _Pager()
    code, answer = common.exit_fault(StoreUnavailable(), pager=pager)
    assert (code, answer.status_code, pager.pages) == ("store_unavailable", 503, [])
    assert json.loads(bytes(answer.body))["code"] == "store_unavailable"


@pytest.mark.parametrize(
    ("error", "escaped"),
    [
        (StoreUnavailable(), True),
        (OrderNotFound(), True),
        (OrderMachinesFull(_TEXT), False),
        (OrderHistoryRefused(_TEXT), False),
        (RuntimeError(_TEXT), False),
    ],
    ids=["a-503-row", "a-4xx-row", "a-row-that-pages", "no-row", "no-oms-error"],
)
def test_a_refusal_raised_past_the_exit_service_is_logged_by_its_class_alone(
    error: Exception, escaped: bool
) -> None:
    """SEC-S4D2A-02 (the Fable lens at 38bfb62e): the exit service answers each refusal as an
    outcome it records, so an `OmsError` whose row is a 4xx or a 503, raised past it, is its row's
    problem, unaudited and unpaged: it is logged, `oms_exit_refusal_escaped`, a warning naming its
    class alone (never its text or its traceback), so it is told apart from a refusal the service
    recorded. A fault whose `500` pages, by its row or by `exit_fault`, is no escaped refusal."""
    with capture_logs() as logs:
        _, answer = common.exit_fault(error, pager=_Pager())
    lines = [line for line in logs if line["event"] == "oms_exit_refusal_escaped"]
    if not escaped:
        assert answer.status_code == 500 and lines == []
        return
    assert isinstance(error, OmsError) and answer.status_code == problem_for(error).status
    named = {"event": "oms_exit_refusal_escaped", "failure": type(error).__name__}
    assert lines == [named | {"log_level": "warning"}]


def test_a_second_fault_of_a_class_pages_the_same_page_for_the_pager_to_fold() -> None:
    """One page for the class: a fault's page is the key and its class alone, the same for every
    fault of the class whatever its text, so the pager's alerting folds a repeat into the page it
    holds (`LogPager` keeps none itself: each is its `cv_page` line); another class pages anew."""
    pager = _Pager()
    for error in (RuntimeError("one defect"), RuntimeError("another"), KeyError("an order")):
        common.exit_fault(error, pager=pager)
    first, again, other = (summary for _, summary, _ in pager.pages)
    assert first == again == f"{common.EXIT_FAULT_PAGE}:RuntimeError"
    assert other == f"{common.EXIT_FAULT_PAGE}:KeyError"


def test_a_fault_is_logged_with_its_traceback_and_a_failing_pager_never_the_answer() -> None:
    """The fault is logged by its class with its traceback (the redaction filter renders it, as
    the app's own `500` handler logs one); a pager that raises is logged, never the answer."""
    error = RuntimeError(_TEXT)
    with capture_logs() as logs:
        code, answer = common.exit_fault(error, pager=_Pager(refuse=True))
    assert (code, answer.status_code) == ("internal_error", 500)
    [logged] = [line for line in logs if line["event"] == common.EXIT_FAULT_PAGE]
    assert (logged["failure"], logged["exc_info"]) == ("RuntimeError", error)
    failed = [line for line in logs if line["event"] == "oms_pager_failed"]
    assert [(line["summary"], line["failure"]) for line in failed] == [
        (f"{common.EXIT_FAULT_PAGE}:RuntimeError", "RuntimeError"),
    ]


async def test_a_faults_answer_that_raises_is_the_last_resorts_500_paged_by_class() -> None:
    """SEC-S4D2A-04 (the Fable lens at 38bfb62e): `faulted`, the route's answer to a fault, that
    raises too leaves no task unanswered: the answer is the redacted `500` all the same (22
    `InternalError`), in the exit's task, logged CRITICAL by the two classes alone and marked as a
    page (`cv_page`, the log pager's mark), so this `500` pages too; the claim is released as the
    task ends."""
    oms = _Runtime()

    async def exit_() -> Response:
        raise RuntimeError(_TEXT)

    def broken(error: Exception) -> Response:
        raise KeyError(_TEXT)

    with capture_logs() as logs:
        got = await run_claimed(oms, USER, "cancel", KEY, exit_, refused=_never, faulted=broken)
    [task] = oms.tasks
    assert (got.status_code, json.loads(bytes(got.body))) == (500, _FAULT_BODY)
    assert task.done() and task.result() is got and not _held(oms)
    assert [line for line in logs if line["log_level"] == "critical"] == [{
        "event": "oms_exit_fault_answer_failed", "fault": "RuntimeError", "failure": "KeyError",
        "cv_page": True, "log_level": "critical",
    }]  # fmt: skip
