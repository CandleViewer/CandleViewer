"""E29-T04 (#913) slice 4: the exit routes' shared steps (`api/order_exits_common.py`, the
orchestrator's ruling of 2026-10-24 19:43Z): `exit_caller`, and `run_claimed`'s in-flight guard
around the exit's run (24 Sec.8.4 steps 9 and 11) on the real `InFlightGuard`, the runtime a fake
that tracks the run as `OmsRuntime.run` does. Nothing sleeps: an exit is held open on an event."""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import Coroutine
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from fastapi.responses import JSONResponse, Response
from starlette.requests import Request

import candleviewer
from candleviewer.api.order_exits_common import exit_caller, exit_refusals, run_claimed
from candleviewer.api.order_principal import TradingPrincipal
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.observability.context import bind_context
from candleviewer.observability.metrics import Metrics
from candleviewer.oms.errors import OmsNotReady
from candleviewer.oms.exits import ExitOutcome, InFlightGuard
from candleviewer.storage.repositories.accounts import GrantScope, OwnerScope

USER, KEY = uuid.uuid4(), uuid.uuid4()


@dataclass
class _Exits:
    guard: InFlightGuard = field(default_factory=InFlightGuard)


@dataclass
class _Runtime:
    """`OmsRuntime.run` as the routes see it: a tracked task, or `OmsNotReady` (the coroutine
    closed) once its stop has begun."""

    exits: _Exits = field(default_factory=_Exits)
    stopping: bool = False
    tasks: list[asyncio.Task[Response]] = field(default_factory=list)

    def run(self, coro: Coroutine[Any, Any, Response]) -> asyncio.Task[Response]:
        if self.stopping:
            coro.close()
            raise OmsNotReady
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


async def test_a_claimed_exit_runs_as_the_runtimes_task_and_releases_when_it_ends() -> None:
    oms, gate = _Runtime(), asyncio.Event()

    async def exit_() -> Response:
        await gate.wait()
        return JSONResponse({"ok": True}, 202)

    answer = asyncio.create_task(run_claimed(oms, USER, "cancel", KEY, exit_, refused=_never))
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

    got = await run_claimed(oms, USER, "cancel", KEY, make, refused=refused)
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

    answer = asyncio.create_task(run_claimed(oms, USER, "cancel", KEY, exit_, refused=_never))
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


async def test_a_runtime_that_refuses_the_run_releases_the_claim_and_raises() -> None:
    oms = _Runtime(stopping=True)

    async def exit_() -> Response:
        raise AssertionError("never run")

    with pytest.raises(OmsNotReady):
        await run_claimed(oms, USER, "cancel", KEY, exit_, refused=_never)
    assert not _held(oms)


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


def test_run_claimed_is_the_in_flight_guards_one_claimer() -> None:
    """SEC-S4C2A-01: a claim has no deadline, so the guard's 1,024 / 64 bounds hold only while
    every claim is released at its exit's end, which `run_claimed` does on every path (the tests
    above). No other module reaches the guard; a new caller is reviewed here first."""
    pkg = Path(candleviewer.__file__).resolve().parent
    reach = re.compile(r"\.guard\.claim\(|\bexits\.guard\b")
    users = {
        p.relative_to(pkg).as_posix()
        for p in pkg.rglob("*.py")
        if reach.search(p.read_text(encoding="utf-8"))
    }
    assert users == {"api/order_exits_common.py"}
