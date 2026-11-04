"""Shared HTTP plumbing of the alert routers: `/alerts` (E40-T02), `/alerts/deliveries*` and
`/notifications` (E40-T04).

* `Problem`: an RFC 9457 refusal (`application/problem+json`) raised from a dependency or a
  handler, sent with `Retry-After` when it carries `retry_after_seconds`; `Refused` carries a
  ready response (the shared SR-026 query refusal) as is.
* `ProblemRoute`: the route class that renders both, and answers a refused write-ahead audit
  record (`AuditUnavailable`, `AuditWriterStopped`) with the operations' declared 503,
  `audit_unavailable` (as `api/drawings.py` refuses one, there as `store_unavailable`): the
  request fails closed (C-2.9), nothing having changed.
* `caller()`: the one caller dependency, so the authorization order is written once:
  no resolver wired → 501 (fail closed); no verified session → 401; the operation's permission
  missing → 403 with `required_permissions`, counted first (`authz_denied_total`, SR-125) and
  then recorded through *refused* (`RefusalRecords.forbidden`); then SR-026 - any query key the
  operation does not declare → 422 - before anything is read. `permission=None` is an operation
  whose `x-rbac` declares no permission (`listNotifications`): a session is still required, and
  there is no role refusal to count or record.
* `RefusalRecords`: the alert routes' refusal records (`rbac.denied`, `alert.denied`,
  `alert.scope_refused`) within one budget per acting user (22 "Alert write bounds and refusal
  records", #5696): past it a refusal writes no record and is counted (`on_held`), and the user's
  next record carries the count; a record not written gives its slot back and fails the request.

Every `Problem` here, in `alert_body.py`, `alert_deliveries.py` and `notifications.py` answers
one of 22's `x-error-codes` with its status (`tests/contract/test_alert_inbox_contract.py`); the
`/alerts` CRUD router's two 503s are #1131's.

RBAC is enforced here, server-side (C-12.4); ownership (`scope: self`) stays with each router,
which knows its rows.
"""

# No `from __future__ import annotations`: FastAPI evaluates the dependency signatures at
# definition time.

import inspect
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, Protocol

import structlog
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from candleviewer.api.query_allowlist import undeclared_query_refusal
from candleviewer.api.view_as_subject import acting_user
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.audit.writer import AuditUnavailable, AuditWriterStopped
from candleviewer.auth.metrics import count_authz_denial
from candleviewer.observability.context import current_request_uuid
from candleviewer.observability.http_duration import route_template
from candleviewer.rules.manager import Actor

#: The alert routes' two permissions, imported from here by both routers.
READ, WRITE = "alerts:read", "alerts:write"

#: Session -> `Actor` (sync or async); None when the request carries no verified session.
Resolver = Callable[[Request], Actor | Awaitable[Actor | None] | None]
#: Records a role refusal before its 403: the caller, the missing permission, the request.
OnForbidden = Callable[[Actor, str, Request], Awaitable[None]]


class AuditEmitter(Protocol):
    """The M19 audit writer's `emit` as the routers call it (write-ahead, C-2.9)."""

    async def emit(self, action: str, **fields: Any) -> None: ...


class RefusalBudget(Protocol):
    """A per-user bound on refusal records (`alert_deliveries.DenialBudget` fits)."""

    def admit(self, user_id: str) -> int | None: ...
    def restore(self, user_id: str, carried: int) -> None: ...


class Problem(Exception):
    def __init__(self, status: int, code: str, title: str, detail: str, **extra: Any) -> None:
        super().__init__(detail)
        self.status, self.code, self.title, self.detail, self.extra = (
            status, code, title, detail, extra,
        )  # fmt: skip

    def response(self) -> JSONResponse:
        retry = self.extra.get("retry_after_seconds")
        return JSONResponse(
            status_code=self.status,
            media_type="application/problem+json",
            headers=None if retry is None else {"Retry-After": str(retry)},
            content={
                "type": f"https://candleviewer.local/errors/{self.code}",
                "title": self.title,
                "status": self.status,
                "code": self.code,
                "detail": self.detail,
                **self.extra,
            },
        )


class Refused(Exception):
    """A ready refusal raised from a dependency: the shared SR-026 query refusal, sent as is."""

    def __init__(self, response: JSONResponse) -> None:
        super().__init__(response.status_code)
        self.response = response


class ProblemRoute(APIRoute):
    """Turns `Problem` (or a ready `Refused`) raised in a dependency or handler into an RFC 9457
    response, and a refused audit write into the declared 503 (see the module docstring)."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        inner = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await inner(request)
            except Problem as p:
                return p.response()
            except Refused as r:
                return r.response
            except (AuditUnavailable, AuditWriterStopped) as exc:  # fails closed: logged apart
                _log().error("alerts_audit_unavailable", error=type(exc).__name__)
                return Problem(503, "audit_unavailable", "Audit unavailable",
                               "The audit record could not be written; nothing was done.",
                               ).response()  # fmt: skip

        return handler


def _log() -> Any:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger("candleviewer.api.alerts_http")


def _no_count() -> None:
    return None


class RefusalRecords:
    """The alert routes' refusal records within one budget per acting user (module docstring),
    the viewer while viewing (#3085): the record names them, and spends their budget."""

    def __init__(
        self, audit: AuditEmitter, budget: RefusalBudget, on_held: Callable[[], None] = _no_count
    ) -> None:
        self._audit, self._budget, self._on_held = audit, budget, on_held

    async def write_refusal(
        self,
        action: str,
        actor: Actor,
        *,
        reason: str,
        kind: str | None = None,
        object_id: str | None = None,
        after: dict[str, Any] | None = None,
        severity: Severity | None = None,
        session_id: str | None = None,
    ) -> None:
        """*action*, outcome denied, written ahead of its refusal within the caller's budget;
        past the budget it is counted (`on_held`) and the caller's next record carries it."""
        who = acting_user(actor.user_id)
        carried = self._budget.admit(who)
        if carried is None:
            self._on_held()
            return
        state = (after or {}) | ({"suppressed_before": carried} if carried else {})
        extra: dict[str, Any] = {"after_state": state} if state else {}
        if severity is not None:
            extra["severity"] = severity
        if session_id is not None:
            extra["session_id"] = session_id
        try:
            await self._audit.emit(
                action, actor_label=who, actor_user_id=who, object_kind=kind,
                object_id=object_id, request_id=current_request_uuid(),
                outcome=AuditOutcome.DENIED, reason=reason, **extra,
            )  # fmt: skip
        except BaseException:  # not written: its slot and its count go back to the budget
            self._budget.restore(who, carried)
            raise

    async def forbidden(self, actor: Actor, permission: str, request: Request) -> None:
        """A role refusal's `rbac.denied` (SR-062), in `enforce`'s reason form. It comes before
        any lookup, so it names no object and reads alike for any id: the method and the route
        template stand in for it."""
        route = f"{request.method} {route_template(request.scope)}"
        await self.write_refusal(
            "rbac.denied", actor, reason=f"missing_permission:{permission}:self",
            after={"route": route}, severity=Severity.WARNING, session_id=actor.session_id,
        )  # fmt: skip


def caller(
    resolver: Resolver | None,
    permission: str | None,
    query: frozenset[str] | None = None,
    refused: OnForbidden | None = None,
) -> Callable[[Request], Awaitable[Actor]]:
    """The dependency resolving the caller of one operation (see the module docstring)."""

    async def dep(request: Request) -> Actor:
        if resolver is None:
            raise Problem(501, "not_implemented", "Not implemented", "no principal resolver")
        got = resolver(request)
        actor: Actor | None = await got if inspect.isawaitable(got) else got
        if actor is None:
            raise Problem(401, "unauthenticated", "Unauthenticated", "no verified session")
        if permission is not None and permission not in actor.perms:
            # SR-125: counted before the record, so no refusal goes uncounted if it fails.
            count_authz_denial(permission, ("owner",) if actor.is_owner else ())
            if refused is not None:
                await refused(actor, permission, request)
            raise Problem(403, "forbidden", "Forbidden", f"requires {permission}",
                          required_permissions=[permission])  # fmt: skip
        if query is not None:
            refusal = undeclared_query_refusal(request, query)
            if refusal is not None:
                raise Refused(refusal)
        return actor

    return dep


__all__ = [
    "READ",
    "WRITE",
    "AuditEmitter",
    "OnForbidden",
    "Problem",
    "ProblemRoute",
    "RefusalBudget",
    "RefusalRecords",
    "Refused",
    "Resolver",
    "caller",
]
