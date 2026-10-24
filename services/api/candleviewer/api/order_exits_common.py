"""The exit routes' shared steps (E29-T04 #913 slice 4; 24-internal-schemas.md Sec.8.4 "The exit
routes").

`DELETE` / `PATCH /orders/{orderId}` (`api/order_exits.py`) and `POST /orders/cancel-all`
(`api/order_cancel_all.py`) each take these from here, so neither writes them again (the
orchestrator's ruling of 2026-10-24 19:43Z):

- `exit_caller`: who asks, as the exit service takes it (`oms.exits.ExitCaller`): the accounts the
  principal reaches, its records' actor and the request's correlation id;
- `run_claimed`: step 9's in-flight guard around step 11's run. The principal's key is claimed for
  the operation, or the guard's refusal (`409 idempotency_in_flight`, `429 rate_limited`, each
  with `Retry-After: 1`) goes to the caller's `refused`, which records it before it is answered
  (C-2.9). A claimed exit runs as the runtime's tracked task, shielded from the client's
  disconnect, and the claim is released when that task ends, never when the request does.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, Protocol

from fastapi import Request
from fastapi.responses import Response

from candleviewer.api.order_admission import submit_actor
from candleviewer.api.order_principal import TradingPrincipal
from candleviewer.auth.scopes import account_scope
from candleviewer.observability.context import current_request_uuid
from candleviewer.oms.exits import ExitCaller, ExitOperation, ExitOutcome, InFlightGuard

__all__ = ["ExitRuntime", "exit_caller", "run_claimed"]


class _Exits(Protocol):
    @property
    def guard(self) -> InFlightGuard: ...


class ExitRuntime(Protocol):
    """`oms_wiring.OmsRuntime` as the exit routes run an exit on it."""

    @property
    def exits(self) -> _Exits: ...

    def run(self, coro: Coroutine[Any, Any, Response]) -> asyncio.Task[Response]: ...


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
) -> Response:
    """The exit `make()` builds, under the in-flight guard's claim of the principal's `key` for
    `operation` (module docstring): a refusal is `refused(outcome)`'s answer, nothing run; a
    runtime that refuses the run (`OmsNotReady`, its stop begun) releases the claim and raises."""
    claimed = oms.exits.guard.claim(user_id, operation, key)
    if isinstance(claimed, ExitOutcome):
        return await refused(claimed)
    release = claimed
    try:
        task = oms.run(make())  # a refused run closes the coroutine itself
    except BaseException:
        release()
        raise
    task.add_done_callback(lambda _done: release())
    return await asyncio.shield(task)
